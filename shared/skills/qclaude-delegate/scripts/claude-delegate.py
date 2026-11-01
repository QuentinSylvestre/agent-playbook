"""Runs one turn of a headless Claude Code session for an orchestrator that delegates a task to it.

Two subcommands, stdlib only (run with the playbook venv: <python> -I claude-delegate.py ...):

  run   --work DIR --cwd DIR --prompt-file F [--model M] [--effort E] [--resume SESSION | --continue-work]
        [--timeout S] [--claude PATH]
      Runs `claude -p --permission-mode auto --output-format stream-json --verbose` once, with the prompt on stdin
      (never in argv), and exits when the turn ends. Foreground; the caller backgrounds it. Turn N is one more than
      the highest events-NNN.jsonl in <work> (the first turn is 001). Files, all in <work>:
        status.json      {"state","pid","pid_start","claude_pid","turn","session_id","refusals","updated","reason"},
                         written first thing, replaced atomically. state: starting | running | done | failed.
        events-NNN.jsonl every stdout line of the turn, one JSON object per line, secrets redacted.
        stderr-NNN.log   claude's stderr, redacted.
        run-NNN.log      this tool's own log: claude's pid and flags, the init line, the reason of a failure.
        session.txt      the session id, written once the init event has passed every assertion.
        result-NNN.json  {"ok","turn","session_id","model","permission_mode","subtype","is_error","result","num_turns",
                         "duration_ms","estimated_usage","api_key_source","permission_denials","refusals",
                         "failure"?}. Written (atomically) when claude sent a result event, before FAILED-NNN.
                         estimated_usage: {"usd" (this turn), "session_total_usd", "note", "basis"}. The result
                         event's total_cost_usd is the session's running total, so usd is that total minus the one
                         recorded by the latest earlier turn of the same session. Both are API-price estimates.
                         A turn after a failed turn of the same session that left no result also absorbs that
                         turn's usage; a session resumed from elsewhere puts its whole earlier total in turn 1.
        reply-NNN.txt    the result text.
        FAILED-NNN       two lines: the reason, then `Next action: ...`. The run then exits 1.
      A turn is finished when result-NNN.json (ok true) or FAILED-NNN exists. It fails when: claude cannot start; the
      init event reports a permissionMode other than auto, or a model that is not the one requested (a full id must
      match exactly, an alias such as `sonnet` must appear in it as whole hyphen-separated words), or, on a resume,
      another session id (a flag that fails open is the thing to catch); the stream has no init event at all, a
      check on it raises (a malformed field) or did not complete, or the result event names no session or another
      one than the init event (the checks above run on the init event); any exception in the event handler
      fails the turn and is named in the reason; the turn
      runs past --timeout (default 1800 s); claude exits nonzero or without a result event; the result event says
      is_error or a subtype other than success; the run
      gets SIGINT or SIGBREAK (SIGTERM too on POSIX; on Windows SIGTERM is a hard kill that no handler sees).
      --continue-work resumes the session in <work>/session.txt, so a multi-turn delegation is a sequence of runs
      in one work folder, each with the same --cwd. --resume SESSION resumes a session started elsewhere.
      Effort is passed through and cannot be asserted: the init event does not report it.
      On every exit it kills the process tree of the one claude it started, and nothing else (a Job Object on
      Windows that also kills the tree if this process dies by a hard kill; a process group on POSIX, signalled
      even after a normal exit so a leftover child ends too, where a hard-killed run leaves claude to die on its
      closed stdout). Coverage limit: the POSIX group kill after a normal exit has only been reviewed, not run;
      the selftest's orphan scenario passes on Windows through the Job Object, and no POSIX machine ran it.
      Known gap on Windows: the job is assigned right
      after the process starts, so a child spawned in that first millisecond escapes it. Only when no job could
      be created does the run fall back to `taskkill /T`.
      A busy folder (a live run still starting or running in it) is refused with exit 2. A turn number is claimed
      by creating events-NNN.jsonl exclusively, so two runs started together never share one; the busy check is
      repeated after the claim, ignoring a status of a higher turn (the lower claimant proceeds, the higher one
      sees its status and exits 2). Two runs that both pass both checks before either writes status.json are not stopped.

  wait  --work DIR [--turn N] [--timeout S] [--poll S] [--status-grace S]
      Blocks until turn N finishes, fails, its run dies, or the timeout. N defaults to the turn in status.json
      (pass --turn when waiting for a follow-up turn: a stale status.json from the previous turn is otherwise
      read). Prints `key: value` lines (turn, state, reply, result, session_id, subtype, refusals, refused,
      estimated_usage, reason, next).
      Exit: 0 turn done, 1 turn failed, 2 timeout (wait again), 3 run dead (its pid is gone or reused, no
      status.json appeared within --status-grace, default 15 s, or the folder moved past the turn without a
      result), 5 nothing to wait for (no such work folder). 4 is not used: this tool has no stop request.

Exit codes of `run`: 0 finished turn, 1 failed turn, 2 bad arguments or busy folder.
"""
import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

REQUIRED_MODE = "auto"
TERMINAL_STATES = ("done", "failed")
EVENTS_FILE = re.compile(r"events-(\d{3})\.jsonl")
SESSION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{7,}")
SAFE_VALUE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/\[\]-]*")
EFFORTS = ("low", "medium", "high", "xhigh", "max")
SECRET_ENV_NAME = re.compile(r"(?i)(token|secret|api_?key|passw(or)?d|credential|bearer|_key$|^key$)")
USAGE_BASIS = ("usd is this turn: the session total minus the previous recorded total of the same session; "
               "a session resumed from elsewhere puts its whole earlier total in its first turn here, and a turn "
               "after a failed turn of the same session that left no result also absorbs that turn's usage")
USAGE_NOTE = {
    True: "API-price equivalent; not billed on a subscription (apiKeySource is none)",
    False: "Claude Code's API-price estimate; apiKeySource is not none, so this account may be billed",
}


# ---------------------------------------------------------------- secrets

class Redactor:
    """Replaces every known secret (and secret-shaped text) in every string before anything reaches a file.

    Known secrets are the values of environment variables whose name says token, secret, key or password."""

    def __init__(self, env=None):
        self.secrets = set()
        for name, value in (os.environ if env is None else env).items():
            if SECRET_ENV_NAME.search(name):
                self.add(value)

    def add(self, *values):
        for v in values:
            if isinstance(v, str) and len(v) >= 12:
                self.secrets.add(v)

    def text(self, s):
        for sec in sorted(self.secrets, key=len, reverse=True):
            s = s.replace(sec, "[redacted]")
        s = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", "Bearer [redacted]", s)
        s = re.sub(r"\bsk-ant-[A-Za-z0-9_-]{8,}", "[redacted]", s)
        s = re.sub(r'(?i)((?:access_?token|authorization|api_?key)\s*[:=]\s*)"?[^\s",}]{8,}"?', r"\1[redacted]", s)
        return s

    def obj(self, o):
        """Redacts every string leaf of a parsed JSON value, so the line stays valid JSON."""
        if isinstance(o, str):
            return self.text(o)
        if isinstance(o, list):
            return [self.obj(x) for x in o]
        if isinstance(o, dict):
            return {k: self.obj(v) for k, v in o.items()}
        return o


# ---------------------------------------------------------------- processes (Windows job object, liveness)

def _k32():
    """kernel32 with 64-bit-safe signatures (Windows only)."""
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.restype = wintypes.HANDLE
    k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    k.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    k.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    k.CreateJobObjectW.restype = wintypes.HANDLE
    k.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    k.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    k.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    k.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    return k


def proc_start(pid):
    """The process creation time as an int, or None when this platform cannot say. Tells a reused pid from the original."""
    try:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes
            k = _k32()
            h = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
            if not h:
                return None
            try:
                t = [wintypes.FILETIME() for _ in range(4)]
                if not k.GetProcessTimes(h, *[ctypes.byref(x) for x in t]):
                    return None
                return (t[0].dwHighDateTime << 32) | t[0].dwLowDateTime
            finally:
                k.CloseHandle(h)
        with open("/proc/%d/stat" % pid, encoding="utf-8") as f:
            return int(f.read().rsplit(")", 1)[1].split()[19])
    except (OSError, ValueError, IndexError):
        return None


def pid_alive(pid, start=None):
    """True when the process exists and, if `start` is given and readable, was created at that time."""
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        k = _k32()
        handle = k.OpenProcess(0x1000, False, pid)
        if not handle:
            alive = ctypes.get_last_error() == 5  # access denied: it exists
        else:
            try:
                code = wintypes.DWORD()
                alive = bool(k.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259  # STILL_ACTIVE
            finally:
                k.CloseHandle(handle)
    else:
        try:
            os.kill(pid, 0)
            alive = True
        except ProcessLookupError:
            alive = False
        except PermissionError:
            alive = True
    if alive and start is not None:
        now = proc_start(pid)
        if now is not None and now != start:
            return False
    return alive


def make_job(proc, log):
    """Windows: puts the process in a Job Object that kills its whole tree when the handle closes (this process
    exiting or dying included). Returns (kernel32, job handle) or None. Elsewhere the process group does this job."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes
        k = _k32()

        class Basic(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class IoCounters(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in ("ro", "wo", "oo", "rb", "wb", "ob")]

        class Extended(ctypes.Structure):
            _fields_ = [("Basic", Basic), ("Io", IoCounters), ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        job = k.CreateJobObjectW(None, None)
        if not job:
            raise OSError("CreateJobObject failed (%d)" % ctypes.get_last_error())
        info = Extended()
        info.Basic.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not k.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
            raise OSError("SetInformationJobObject failed (%d)" % ctypes.get_last_error())
        if not k.AssignProcessToJobObject(job, wintypes.HANDLE(int(proc._handle))):
            raise OSError("AssignProcessToJobObject failed (%d)" % ctypes.get_last_error())
        return k, job
    except Exception as exc:  # taskkill /T stays as the fallback
        log("job object unavailable (%s); relying on taskkill /T" % exc)
        return None


# ---------------------------------------------------------------- shared helpers

class Fail(Exception):
    pass


def atomic_write(path, text):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    for _ in range(40):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:  # a reader has it open for a moment (Windows)
            time.sleep(0.05)
    os.replace(tmp, path)


def read_json(path):
    for _ in range(5):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, NotADirectoryError):
            return None
        except (ValueError, PermissionError):
            time.sleep(0.05)
    return None


def turn_numbers(work):
    return sorted(int(m.group(1)) for p in work.glob("events-*.jsonl") for m in [EVENTS_FILE.fullmatch(p.name)] if m)


def claim_turn(work):
    """-> (turn, events file open for writing). The turn is claimed by creating events-NNN.jsonl exclusively, so two
    runs starting together get different numbers; on a clash the next number is tried. Raises ValueError past 999."""
    while True:
        nums = turn_numbers(work)
        turn = (nums[-1] + 1) if nums else 1
        if turn > 999:
            raise ValueError("%s already holds 999 turns; use a new work folder" % work)
        try:
            return turn, open(work / ("events-%03d.jsonl" % turn), "x", encoding="utf-8", newline="\n")
        except FileExistsError:
            continue


def busy_message(work, ignore_above=None):
    """-> why a live run holds the folder, or None. With ignore_above (the caller's own claimed turn), a status of a
    higher turn is a later claimant, not a reason for this earlier one to give way: the lower claimant proceeds."""
    st = read_json(work / "status.json")
    if st and ignore_above is not None and isinstance(st.get("turn"), int) and st["turn"] > ignore_above:
        return None
    if st and st.get("state") not in TERMINAL_STATES and pid_alive(st.get("pid"), st.get("pid_start")):
        return ("%s is busy: turn %s is %s (pid %s). Wait for it, or use a new work folder."
                % (work, st.get("turn"), st.get("state"), st.get("pid")))
    return None


def claude_command(claude):
    return [sys.executable, claude] if str(claude).lower().endswith(".py") else [claude]


def next_action(reason, turn):
    r = reason.lower()
    n = "%03d" % turn
    if "mismatch" in r:
        return "do not retry with the same flags; read the init line of events-%s.jsonl and tell the user." % n
    if "not found" in r:
        return "pass --claude PATH, or tell the user Claude Code is not installed."
    if "timed out" in r:
        return ("read the end of events-%s.jsonl for what it was doing; --continue-work with a larger --timeout "
                "only if the task is genuinely long." % n)
    if "no init event" in r or "checks did not complete" in r or "handler error" in r:
        return ("do not trust this turn: its permission mode and model were never checked. Read the end of "
                "events-%s.jsonl and tell the user." % n)
    if "no result event" in r:
        return ("no result file exists for this turn; read stderr-%s.log and the end of events-%s.jsonl, then tell "
                "the user; do not retry more than once." % (n, n))
    if "reports subtype" in r or "after its result event" in r:
        return "read result-%s.json and reply-%s.txt, then tell the user; do not retry more than once." % (n, n)
    return ("read stderr-%s.log and the end of events-%s.jsonl, then start again; do not retry more than once "
            "without telling the user." % (n, n))


def model_matches(requested, reported):
    """A full id (claude-...) must equal the reported id; an alias (sonnet, opus, haiku) must appear in it as
    whole hyphen-separated words (`sonnet` is in `claude-sonnet-5-5`, `sonn` is not)."""
    req = requested.lower().split("[")[0]
    rep = (reported or "").lower().split("[")[0]
    if req.startswith("claude-"):
        return rep == req
    want, have = req.split("-"), rep.split("-")
    return bool(req) and any(have[i:i + len(want)] == want for i in range(len(have)))


# ---------------------------------------------------------------- the run

class Run:
    def __init__(self, a, turn, resume_id, events):
        self.a = a
        self.work = Path(a.work).resolve()
        self.cwd = os.path.abspath(a.cwd)
        self.turn = turn
        self.stem = "%03d" % turn
        self.resume_id = resume_id
        self.red = Redactor()
        self.proc = None
        self.job = None
        self.init = None
        self.init_checked = False  # set only when every check on the init event ran to the end and passed
        self.result = None
        self.session_id = resume_id
        self.fail_reason = None
        self.refusals = 0
        self.terminating = False
        self.pid_start = proc_start(os.getpid())
        self.status_lock = threading.Lock()
        self.reader = None
        self.events = events
        self.logf = open(self.work / ("run-%s.log" % self.stem), "a", encoding="utf-8", newline="\n")

    # ---- files
    def log(self, msg):
        self.logf.write(time.strftime("%H:%M:%S ") + self.red.text(msg) + "\n")
        self.logf.flush()

    def set_status(self, state, **extra):
        doc = {"state": state, "pid": os.getpid(), "pid_start": self.pid_start,
               "claude_pid": self.proc.pid if self.proc else None, "turn": self.turn,
               "session_id": self.session_id, "refusals": self.refusals,
               "updated": time.strftime("%Y-%m-%dT%H:%M:%S"), **extra}
        with self.status_lock:
            atomic_write(self.work / "status.json", json.dumps(doc))

    # ---- process
    def spawn(self, prompt_bytes):
        a = self.a
        claude = a.claude or shutil.which("claude")
        if not claude or not (shutil.which(claude) or os.path.isfile(claude)):
            raise Fail("claude not found (pass --claude PATH)")
        cmd = claude_command(claude) + ["-p", "--output-format", "stream-json", "--verbose",
                                        "--permission-mode", REQUIRED_MODE]
        if a.model:
            cmd += ["--model", a.model]
        if a.effort:
            cmd += ["--effort", a.effort]
        if self.resume_id:
            cmd += ["--resume", self.resume_id]
        kwargs = {"start_new_session": True} if os.name != "nt" else {}
        try:
            self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                         cwd=self.cwd, **kwargs)
        except OSError as exc:
            raise Fail("cannot start claude: %s" % type(exc).__name__)
        self.job = make_job(self.proc, self.log)
        self.log("started claude pid %d: %s" % (self.proc.pid, " ".join(cmd[len(claude_command(claude)):])))
        self.set_status("running")
        threading.Thread(target=self.feed_stdin, args=(prompt_bytes,), daemon=True).start()
        self.reader = threading.Thread(target=self.read_stdout, daemon=True)
        self.reader.start()
        threading.Thread(target=self.copy_stderr, daemon=True).start()

    def feed_stdin(self, data):
        try:
            self.proc.stdin.write(data)
            self.proc.stdin.close()
        except (OSError, ValueError):  # claude ended or was killed before reading it all
            pass

    def kill_tree(self):
        """Ends the process tree of the one claude this run started. Touches no other process."""
        p = self.proc
        if p is None:
            return
        if os.name == "nt":
            if p.poll() is None:
                # The job holds exactly the processes this run started. taskkill /T walks parent pids, which can
                # match an unrelated orphan whose stale parent pid was recycled, so it is only the fallback.
                if self.job:
                    self.job[0].TerminateJobObject(self.job[1], 1)
                else:
                    subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True)
        else:
            # The group this run created (start_new_session: its id is claude's pid). It is signalled even after
            # claude exited, so a child left in it ends too. Callers reach here right after the exit, while the id
            # cannot yet belong to anything else; a group with no member left raises ProcessLookupError.
            for sig in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.killpg(p.pid, sig)
                except (ProcessLookupError, PermissionError):
                    break
                if sig == signal.SIGTERM:
                    try:
                        p.wait(3)
                    except subprocess.TimeoutExpired:
                        pass
                    time.sleep(0.2)  # members still in the group get a moment to end before SIGKILL
        if self.job:  # closing the handle kills whatever is left in the job, children of an already exited parent included
            k, job = self.job
            self.job = None
            k.CloseHandle(job)
        try:
            p.wait(10)
        except subprocess.TimeoutExpired:
            self.log("claude did not exit after kill")

    def copy_stderr(self):
        with open(self.work / ("stderr-%s.log" % self.stem), "a", encoding="utf-8", newline="\n") as f:
            for line in self.proc.stderr:
                f.write(self.red.text(line.decode("utf-8", "replace")))
                f.flush()

    # ---- the event stream
    def read_stdout(self):
        for raw in self.proc.stdout:
            text = raw.decode("utf-8", "replace").strip()
            if not text:
                continue
            try:
                ev = json.loads(text)
            except ValueError:
                ev = None
            self.events.write(json.dumps(self.red.obj(ev) if isinstance(ev, dict) else {"type": "raw", "line": self.red.text(text)},
                                         ensure_ascii=False) + "\n")
            self.events.flush()
            if isinstance(ev, dict):
                try:
                    self.on_event(ev)
                except Exception as exc:  # a handler bug must not kill the reader, and must not pass the turn
                    self.log("handler error %r" % exc)
                    self.fail_reason = self.fail_reason or "event handler error: %s: %s" % (type(exc).__name__, exc)

    def on_event(self, ev):
        kind, sub = ev.get("type"), ev.get("subtype")
        if kind == "system" and sub == "init" and self.init is None:
            self.init = ev
            self.check_init(ev)
        elif kind == "result":
            self.result = ev

    def check_init(self, ev):
        mode, model, sid = ev.get("permissionMode"), ev.get("model"), ev.get("session_id")
        self.log("init: model=%r permissionMode=%r session_id=%r apiKeySource=%r" % (
            model, mode, sid, ev.get("apiKeySource")))
        if mode != REQUIRED_MODE:
            self.fail_reason = "permission mode mismatch: required %r, the init event reports %r" % (REQUIRED_MODE, mode)
        elif self.a.model and not model_matches(self.a.model, model):
            self.fail_reason = "model mismatch: requested %r, the init event reports %r" % (self.a.model, model)
        elif not isinstance(sid, str) or not SESSION_ID.fullmatch(sid):
            self.fail_reason = "the init event carries no usable session id"
        elif self.resume_id and sid != self.resume_id:
            self.fail_reason = "session mismatch: resumed %r, the init event reports %r" % (self.resume_id, sid)
        if self.fail_reason:
            return
        self.session_id = sid
        atomic_write(self.work / "session.txt", sid)
        self.init_checked = True
        self.set_status("running")

    # ---- run
    def wait_for_end(self):
        deadline = time.time() + self.a.timeout
        while self.proc.poll() is None:
            if self.fail_reason:
                raise Fail(self.fail_reason)
            if time.time() > deadline:
                raise Fail("the turn timed out after %ds" % self.a.timeout)
            time.sleep(0.1)

    def turn_usd(self, session_id, total):
        """This turn's estimate: the result event's total_cost_usd is the session's running total (measured on
        Claude Code 2.1.302, 2026-10-17: a resumed turn reported the whole session), so subtract the total recorded
        by the latest earlier turn of the same session. With none recorded, the turn gets the whole total."""
        if not isinstance(total, (int, float)):
            return None
        for n in range(self.turn - 1, 0, -1):
            prev = read_json(self.work / ("result-%03d.json" % n))
            if isinstance(prev, dict) and prev.get("session_id") == session_id:
                before = (prev.get("estimated_usage") or {}).get("session_total_usd")
                if isinstance(before, (int, float)):
                    return round(total - before, 6) if total >= before else total
        return total

    def write_result(self, failure):
        ev = self.result
        denials = ev.get("permission_denials") if isinstance(ev.get("permission_denials"), list) else []
        self.refusals = len(denials)
        init = self.init or {}
        subscription = init.get("apiKeySource") == "none"
        session_id = ev.get("session_id") or self.session_id
        total = ev.get("total_cost_usd")
        doc = {"ok": failure is None, "turn": self.turn, "session_id": session_id,
               "model": init.get("model"), "requested_model": self.a.model,
               "permission_mode": init.get("permissionMode"), "subtype": ev.get("subtype"),
               "is_error": ev.get("is_error"), "result": ev.get("result"), "num_turns": ev.get("num_turns"),
               "duration_ms": ev.get("duration_ms"),
               "estimated_usage": {"usd": self.turn_usd(session_id, total), "session_total_usd": total,
                                   "note": USAGE_NOTE[subscription], "basis": USAGE_BASIS},
               "api_key_source": init.get("apiKeySource"), "claude_code_version": init.get("claude_code_version"),
               "refusals": self.refusals, "permission_denials": denials}
        if failure:
            doc["failure"] = failure
        doc = self.red.obj(doc)
        text = doc["result"] if isinstance(doc["result"], str) else ""
        atomic_write(self.work / ("reply-%s.txt" % self.stem), text)
        atomic_write(self.work / ("result-%s.json" % self.stem), json.dumps(doc, ensure_ascii=False, indent=1))

    def finish(self):
        """After claude exited: judge the turn. A result file always lands before FAILED-NNN."""
        ev, rc = self.result, self.proc.returncode
        failure = None
        if ev is None:
            failure = "claude exited with code %s and sent no result event" % rc
        elif self.init is None:  # the mode, model and resume checks all run on the init event
            failure = "the stream carried no init event, so the permission mode, model and session were never checked"
        elif not self.init_checked:
            failure = "the init event was seen but its checks did not complete, so the permission mode, model and session are unverified"
        elif not isinstance(ev.get("session_id"), str) or ev["session_id"] != self.session_id:
            failure = "session mismatch: the init event reports %r, the result event %r" % (self.session_id, ev.get("session_id"))
        elif rc != 0:
            failure = "claude exited with code %s after its result event" % rc
        elif ev.get("is_error") or ev.get("subtype") != "success":
            failure = "the result event reports subtype %r, is_error %r" % (ev.get("subtype"), ev.get("is_error"))
        if ev is not None:
            self.write_result(failure)
        if failure:
            raise Fail(failure)

    def fail(self, reason):
        self.terminating = True
        reason = self.red.text(reason)
        self.log("FAILED: " + reason)
        self.kill_tree()
        atomic_write(self.work / ("FAILED-%s" % self.stem), "%s\nNext action: %s\n" % (reason, next_action(reason, self.turn)))
        self.set_status("failed", reason=reason)

    def execute(self, prompt_bytes):
        def on_signal(signum, frame):
            if not self.terminating:  # once failing, a signal must not interrupt the cleanup
                raise Fail("the run received signal %d" % signum)

        for name in ("SIGTERM", "SIGBREAK", "SIGINT"):
            sig = getattr(signal, name, None)
            if sig is None or (name == "SIGINT" and signal.getsignal(sig) == signal.SIG_IGN):
                continue  # a SIGINT the parent chose to ignore (a background job) stays ignored
            signal.signal(sig, on_signal)
        try:
            try:
                self.set_status("starting")
                self.spawn(prompt_bytes)
                self.wait_for_end()
                self.terminating = True
                self.kill_tree()  # an exited claude: ends any child it left behind (and so closes its pipes)
                self.reader.join(10)
                if self.fail_reason:
                    raise Fail(self.fail_reason)
                self.finish()
            except Fail as exc:
                self.fail(str(exc))
                return 1
            except KeyboardInterrupt:  # only if installing the SIGINT handler failed; harmless defence
                self.fail("the run was interrupted (signal)")
                return 1
            except Exception as exc:
                self.fail("run error: %s: %s" % (type(exc).__name__, exc))
                return 1
            self.set_status("done")
            return 0
        finally:
            self.events.flush()
            self.logf.flush()


def cmd_run(a):
    work = Path(a.work).resolve()
    if a.effort and a.effort not in EFFORTS:
        return usage("--effort must be one of %s" % ", ".join(EFFORTS))
    for flag, value in (("--model", a.model),):
        if value and not SAFE_VALUE.fullmatch(value):
            return usage("%s value %r has characters that are not allowed" % (flag, value))
    if not os.path.isdir(a.cwd):
        return usage("--cwd %s is not a folder" % a.cwd)
    try:
        prompt = Path(a.prompt_file).read_bytes().decode("utf-8-sig").encode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return usage("cannot read --prompt-file as UTF-8 text: %s" % type(exc).__name__)
    if not prompt.strip():
        return usage("--prompt-file is empty")
    if a.resume and not SESSION_ID.fullmatch(a.resume):
        return usage("--resume value is not a session id")
    resume_id = a.resume
    if a.continue_work:
        try:
            resume_id = (work / "session.txt").read_text(encoding="utf-8").strip()
        except OSError:
            return usage("--continue-work: %s has no session.txt (no earlier turn reached its init event); "
                         "start without it" % work)
        if not SESSION_ID.fullmatch(resume_id):
            return usage("--continue-work: session.txt does not hold a session id")
    work.mkdir(parents=True, exist_ok=True)
    busy = busy_message(work)
    if busy:
        return usage(busy)
    try:
        turn, events = claim_turn(work)
    except ValueError as exc:
        return usage(str(exc))
    busy = busy_message(work, turn)  # a run that started between the first check and the claim
    if busy:
        events.close()
        try:
            (work / ("events-%03d.jsonl" % turn)).unlink()
        except OSError:
            pass
        return usage(busy)
    run = Run(a, turn, resume_id, events)
    code = run.execute(prompt)
    print("turn: %d\nstate: %s\nreply: %s\nresult: %s" % (
        turn, "done" if code == 0 else "failed", work / ("reply-%03d.txt" % turn), work / ("result-%03d.json" % turn)))
    if code:
        print("failed: %s" % (work / ("FAILED-%03d" % turn)))
    return code


def usage(msg):
    print("error: %s" % msg, file=sys.stderr)
    return 2


# ---------------------------------------------------------------- waiter

def cmd_wait(a):
    work = Path(a.work).resolve()
    if not work.is_dir():
        print("state: nothing to wait for\nreason: no work folder %s\nnext: start `run` with this --work first" % work)
        return 5
    t0 = time.time()
    end = t0 + a.timeout

    def report(code, turn, state, **kv):
        stem = "%03d" % turn if turn else None
        res = read_json(work / ("result-%s.json" % stem)) if stem else None
        print("turn: %s\nstate: %s" % (turn, state))
        if res:
            print("reply: %s\nresult: %s" % (work / ("reply-%s.txt" % stem), work / ("result-%s.json" % stem)))
            for k in ("session_id", "subtype", "num_turns"):
                print("%s: %s" % (k, res.get(k)))
            usage_doc = res.get("estimated_usage") or {}
            print("estimated_usage: ~$%s this turn, ~$%s session total (%s)" % (
                usage_doc.get("usd"), usage_doc.get("session_total_usd"), usage_doc.get("note")))
            print("refusals: %s" % res.get("refusals", 0))
            for d in (res.get("permission_denials") or [])[:5]:
                print("refused: %s %s" % (d.get("tool_name"), json.dumps(d.get("tool_input"), ensure_ascii=False)[:200]))
        for k, v in kv.items():
            print("%s: %s" % (k, v))
        return code

    while True:
        st = read_json(work / "status.json")
        turn = a.turn if a.turn is not None else ((st or {}).get("turn") or (turn_numbers(work) or [None])[-1])
        if turn:
            stem = "%03d" % turn
            res = read_json(work / ("result-%s.json" % stem))
            failed = work / ("FAILED-%s" % stem)
            if res is not None:
                if res.get("ok"):
                    return report(0, turn, "turn %d done" % turn)
                reason = res.get("failure") or "the result event reports an error"
                nxt = "read reply-%s.txt, then tell the user" % stem
                if failed.exists():
                    reason, _, nxt = failed.read_text(encoding="utf-8").strip().partition("\nNext action: ")
                return report(1, turn, "failed", reason=reason, next=nxt or "read reply-%s.txt" % stem)
            if failed.exists():
                reason, _, nxt = failed.read_text(encoding="utf-8").strip().partition("\nNext action: ")
                return report(1, turn, "failed", reason=reason, next=nxt or "read the end of events-%s.jsonl" % stem)
            st_turn = (st or {}).get("turn") if isinstance((st or {}).get("turn"), int) else 0
            if st and st_turn == turn and st.get("state") not in TERMINAL_STATES \
                    and not pid_alive(st.get("pid"), st.get("pid_start")):
                return report(3, turn, "run dead", reason="run pid %s is gone (or reused) and status.json says %r"
                              % (st.get("pid"), st.get("state")),
                              next="read the end of events-%s.jsonl and run-%s.log, then start again; do not kill processes by name" % (stem, stem))
            if st_turn > turn:
                return report(3, turn, "run dead", reason="status.json is already at turn %s and turn %d left no result" % (st_turn, turn),
                              next="read events-%s.jsonl, then start again" % stem)
            if st_turn < turn and time.time() - t0 > a.status_grace:
                return report(3, turn, "run dead", reason="status.json never reached turn %d within %ds: the run never started" % (turn, a.status_grace),
                              next="run `run` in the foreground once to see its error")
        if st is None and time.time() - t0 > a.status_grace:
            return report(3, turn, "run dead", reason="no status.json appeared within %ds: the run never started" % a.status_grace,
                          next="run `run` in the foreground once to see its error")
        if time.time() > end:
            return report(2, turn, "timeout", reason="no result after %ds; last state %r" % (a.timeout, (st or {}).get("state")),
                          next="wait again, or read the end of events-%s.jsonl to see progress" % ("%03d" % turn if turn else "NNN"))
        time.sleep(a.poll)


def main(argv):
    ap = argparse.ArgumentParser(prog="claude-delegate.py", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--work", required=True)
    r.add_argument("--cwd", required=True, help="the session working directory")
    r.add_argument("--prompt-file", required=True)
    r.add_argument("--model", help="passed to claude and asserted against the init event")
    r.add_argument("--effort", help="low, medium, high, xhigh or max; passed through, not assertable")
    g = r.add_mutually_exclusive_group()
    g.add_argument("--resume", metavar="SESSION", help="continue a session started elsewhere")
    g.add_argument("--continue-work", action="store_true", help="continue the session recorded in <work>/session.txt")
    r.add_argument("--timeout", type=int, default=1800, help="seconds the turn may run")
    r.add_argument("--claude", help="path to claude (default: claude on PATH); a .py file runs under this interpreter")
    w = sub.add_parser("wait")
    w.add_argument("--work", required=True)
    w.add_argument("--turn", type=int)
    w.add_argument("--timeout", type=int, default=600)
    w.add_argument("--poll", type=float, default=1.0)
    w.add_argument("--status-grace", type=int, default=15, help="seconds to wait for the first status.json of the run")
    a = ap.parse_args(argv)
    if a.cmd == "wait":
        return cmd_wait(a)
    return cmd_run(a)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
