"""File-driven ACP client for kiro-cli v3: lets an orchestrator delegate turns to a kiro-cli agent.

Two subcommands, stdlib only (run with the playbook venv: <python> -I acp-driver.py ...):

  run   --work DIR --cwd DIR [--kiro PATH] [--mode ID] [--model ID] [--effort LEVEL]
        [--turn-timeout S] [--total-timeout S] [--startup-timeout S] [--stop-grace S] [--cancel-grace S]
      Starts `kiro acp --agent-engine v3` as a child and serves it from <work>:
        in/NNN.txt     a prompt; NNN is exactly three digits. Write it as in/NNN.tmp and rename it. Never write
                       in/NNN.txt directly: the driver also skips a file modified in the last 0.5 s, but only the
                       rename is safe.
        out/NNN.txt    the reply, streamed. Permission decisions and tool failures are appended to it.
        out/NNN.done   appears when turn NNN ends; holds the stop reason.
        in/stop        end the run (a turn in progress is cancelled first, with --cancel-grace s, default 30, to end). kiro-cli's stdin is
                       closed, it gets --stop-grace seconds (default 5) to exit, then its tree is killed.
        policy.json    optional permission policy, read afresh on every request (see below). No file: all tools trusted.
        status.json    {"state","pid","pid_start","kiro_pid","turn","refusals","updated","reason"}, written first
                       thing. state is one of starting | ready | turn N running | turn N done | stopped | failed.
        FAILED         two lines: the reason, then `Next action: ...`. The driver then exits 1.
        events.log     every request, decision and notification type. Secrets are redacted.
        session.txt    the ACP session id.
      The driver fails (FAILED, kiro-cli killed, exit 1) when: kiro-cli cannot start, initialize or session/new
      fails or times out, a requested model or effort is unsupported or cannot be confirmed through
      session/set_config_option, the mode or a selected value drifts in a later config_option_update,
      a turn runs past --turn-timeout, a turn gets a JSON-RPC
      error reply, the run passes --total-timeout, the driver gets SIGINT or SIGBREAK (SIGTERM too on POSIX; on
      Windows SIGTERM is a hard kill that no handler sees), or kiro-cli exits. The drift check never stops:
      it is made when a reply arrives (before out/NNN.done is written), on every idle pass, and before stopped.
      On every exit it kills the process tree of the one kiro-cli it started, and nothing else. On Windows
      kiro-cli runs in a Job Object that kills its whole tree when the driver dies, even by a hard kill. Known
      gap: the job is assigned right after the process starts (a suspended start needs NtResumeProcess, which is
      undocumented), so a child spawned in that first millisecond escapes the job and is not killed (a documented
      limit). Only when no job could be created does the driver fall back to `taskkill /T`.
      POSIX: this standalone CLI resets inherited SIGCHLD to default and is its child's sole reaper.
      It observes exit without reaping via waitid/WNOWAIT, or kqueue on BSD/macOS, reserving the leader
      PID until group TERM/KILL cleanup finishes. Missing/broken observation or lost ownership fails
      closed with a cleanup error; it never authorizes group signals from PID absence or timestamps.

  wait  --work DIR [--turn N] [--timeout S] [--poll S] [--status-grace S]
      Blocks until out/N.done, FAILED, a dead driver, a stopped run or the timeout. N defaults to the highest
      numbered prompt in in/. Prints `key: value` lines (turn, state, reply, stop_reason, refusals, reason, next).
      Exit: 0 turn done, 1 run failed, 2 timeout (wait again), 3 driver dead (its pid is gone or reused, or no
      status.json appeared within --status-grace, default 15 s), 4 run stopped before the turn finished,
      5 nothing to wait for (no in/NNN.txt yet).

Permission policy (<work>/policy.json, optional):
  Default: all tools are trusted (the user's choice, 2026-10-17, as in PowerAtlas); the policy tightens it.
  {"default": "allow"|"reject", "allow": [RULE, ...], "deny": [RULE, ...]}   ("default" defaults to "allow")
  A RULE is an object whose keys all must match (AND). Keys, each a string or a list of strings:
    capability       consent.capability: shell, fs_read, fs_write, mcp, subagent, skill, web_fetch
    kind             toolCall.kind: execute, read, edit, delete, search, other
    title            exact toolCall.title, case-insensitive
    resource         exact consent.resource (an MCP "server/tool", a skill or agent name, a web host)
    command_prefix   shell only. In an allow rule: the whole command must be ONE simple command (no & | ; < > ` $( ) or
                     newline) starting with the prefix at a word boundary. In a deny rule: any piece of the command.
    path_under       file tools. Every path the request names must lie under one of the directories (allow);
                     any one of them under one of the directories is enough (deny). Relative paths (the request's
                     and the rule's) are taken against the session cwd and symlinks are resolved.
    command_contains deny rules only: case-insensitive substring of the command or the request title.
    note             free text, ignored.
  Command rules are best-effort. There is no shell parser: `pwsh -Command "git push"`, `git -C x push`,
  `cmd /c git push`, an env-var prefix or quoting defeat command_prefix, and command_contains only catches text
  that appears literally. Do not rely on them to stop a determined or confused agent. Prefer capability, resource
  and path_under rules, and tell the delegate in its brief what it must not do.
  A request with no consent block takes its capability from toolCall.kind (execute: shell, edit and delete:
  fs_write, read and search: fs_read).
  Order: a matching deny wins; else a matching allow runs the tool (allow_once, never allow_always); else the
  policy's "default". No policy file allows everything; a policy file that is unreadable or invalid rejects
  everything (a broken tightening never fails open). A request in a shape the rules cannot read matches no rule. Every request and decision is logged, and each refusal is appended to the turn's out file.
  The policy only matters when the bound mode asks: kiro_default on a machine whose permissions.yaml says
  `all: allow` never sends a request, so the delegate then runs with the user's full privileges.
"""
import argparse
import json
import os
import queue
import re
import select
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

ACP_PROTOCOL_VERSION = 1
SHELL_CONTROL = re.compile(r"[&|;<>`\n\r]|\$\(|\)")
SEGMENT_SPLIT = re.compile(r"&&|\|\||[;&|\n\r]|\$\(|`")
ALLOW_KEYS = {"capability", "kind", "title", "resource", "command_prefix", "path_under", "note"}
DENY_KEYS = ALLOW_KEYS | {"command_contains"}
MATCH_KEYS = DENY_KEYS - {"note"}
TERMINAL_STATES = ("stopped", "failed")
KIND_CAPABILITY = {"execute": "shell", "edit": "fs_write", "delete": "fs_write", "read": "fs_read", "search": "fs_read"}
PROMPT_STEM = re.compile(r"\d{3}")
SETTLE_SECONDS = 0.5


# ---------------------------------------------------------------- secrets

class Redactor:
    """Replaces every known secret (and bearer-shaped text) before anything reaches a file."""

    def __init__(self):
        self.secrets = set()

    def add(self, *values):
        for v in values:
            if isinstance(v, str) and len(v) >= 8:
                self.secrets.add(v)
                self.secrets.add(json.dumps(v)[1:-1])  # the form it takes inside a JSON string

    def text(self, s):
        s = str(s)
        for sec in sorted(self.secrets, key=len, reverse=True):
            s = s.replace(sec, "[redacted]")
        s = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", "Bearer [redacted]", s)
        s = re.sub(r'(?i)("?(?:access_?token|authorization)"?\s*[:=]\s*)"?[^\s",}]{8,}"?', r"\1[redacted]", s)
        return s

    def holdback(self):
        return max((len(s) for s in self.secrets), default=1) - 1


class StreamRedactor:
    """Redacts a text stream chunk by chunk, holding back a tail so a secret split across chunks is still caught."""

    def __init__(self, redactor):
        self.r = redactor
        self.buf = ""

    def feed(self, chunk):
        self.buf = self.r.text(self.buf + chunk)
        keep = self.r.holdback()
        if keep <= 0:
            out, self.buf = self.buf, ""
            return out
        if len(self.buf) <= keep:
            return ""
        out, self.buf = self.buf[:-keep], self.buf[-keep:]
        return out

    def flush(self):
        out, self.buf = self.r.text(self.buf), ""
        return out


# ---------------------------------------------------------------- permission policy

def _as_list(v):
    return [v] if isinstance(v, str) else v


def validate_policy(policy):
    """-> error string, or None when the policy is usable."""
    if not isinstance(policy, dict):
        return "policy must be a JSON object"
    extra = set(policy) - {"default", "allow", "deny"}
    if extra:
        return "unknown top-level key(s): %s" % ", ".join(sorted(extra))
    if policy.get("default", "allow") not in ("allow", "reject"):
        return 'default must be "allow" or "reject"'
    for section, keys in (("allow", ALLOW_KEYS), ("deny", DENY_KEYS)):
        rules = policy.get(section, [])
        if not isinstance(rules, list):
            return "%s must be a list" % section
        for i, rule in enumerate(rules):
            where = "%s[%d]" % (section, i)
            if not isinstance(rule, dict):
                return "%s must be an object" % where
            bad = set(rule) - keys
            if bad:
                return "%s has unknown or not-permitted key(s): %s" % (where, ", ".join(sorted(bad)))
            if not (set(rule) & MATCH_KEYS):
                return "%s has no matching key (it would match everything)" % where
            for k, v in rule.items():
                if k == "note":
                    continue
                vals = _as_list(v)
                if not isinstance(vals, list) or not vals or not all(isinstance(x, str) and x.strip() for x in vals):
                    return "%s.%s must be a non-empty string or list of non-empty strings" % (where, k)
    return None


def load_policy(path):
    """-> (policy or None, error or None). (None, None) means no file: all tools trusted. An error rejects."""
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return None, None
    except OSError as exc:
        return None, "policy unreadable: %s" % type(exc).__name__
    try:
        policy = json.loads(text)
    except ValueError as exc:
        return None, "policy is not valid JSON: %s" % exc
    err = validate_policy(policy)
    return (None, "invalid policy: %s" % err) if err else (policy, None)


def _str(v):
    return v if isinstance(v, str) else None


def request_facts(params, session_cwd):
    """The fields of a session/request_permission request that the rules read. Missing ones are None or empty."""
    params = params if isinstance(params, dict) else {}
    tc = params.get("toolCall") if isinstance(params.get("toolCall"), dict) else {}
    kiro = (params.get("_meta") or {}).get("kiro") if isinstance(params.get("_meta"), dict) else None
    consent = (kiro or {}).get("consent") if isinstance(kiro, dict) else None
    consent = consent if isinstance(consent, dict) else {}
    raw = tc.get("rawInput") if isinstance(tc.get("rawInput"), dict) else {}
    title = _str(tc.get("title")) or ""
    kind = _str(tc.get("kind"))
    capability = _str(consent.get("capability")) or KIND_CAPABILITY.get(kind)
    is_shell = capability == "shell"
    commands, paths = [], []
    if is_shell:
        for c in (raw.get("command"), consent.get("triggeringResource")):
            if isinstance(c, str) and c.strip():
                commands.append(c.strip())
        if not commands and title:
            commands.append(re.sub(r"^(?i:running):\s*", "", title).strip())
    else:
        for c in (consent.get("resource"), consent.get("triggeringResource"), raw.get("path"), raw.get("file_path"),
                  raw.get("filePath")):
            if isinstance(c, str) and c.strip():
                paths.append(c.strip())
        for key in ("paths", "file_paths"):
            if isinstance(raw.get(key), list):
                paths += [p for p in raw[key] if isinstance(p, str) and p.strip()]
        for loc in tc.get("locations") if isinstance(tc.get("locations"), list) else []:
            if isinstance(loc, dict) and isinstance(loc.get("path"), str) and loc["path"].strip():
                paths.append(loc["path"].strip())
        if capability not in ("fs_read", "fs_write") and kind not in ("read", "edit", "delete", "search"):
            paths = []
    resolved = []
    for p in paths:
        try:
            resolved.append(os.path.normcase(os.path.realpath(os.path.join(session_cwd, os.path.expanduser(p)))))
        except (OSError, ValueError):
            resolved.append(None)
    return {"title": title, "kind": kind, "capability": capability, "resource": _str(consent.get("resource")),
            "commands": commands, "paths": resolved, "is_shell": is_shell, "cwd": session_cwd}


def _under(path, directory, session_cwd):
    if path is None:
        return False
    d = os.path.normcase(os.path.realpath(os.path.join(session_cwd, os.path.expanduser(directory))))
    try:
        return os.path.commonpath([path, d]) == d
    except ValueError:
        return False


def _prefix_ok(command, prefix):
    c, p = " ".join(command.split()).casefold(), " ".join(prefix.split()).casefold()
    return c == p or c.startswith(p + " ")


def rule_matches(rule, facts, is_deny):
    for key, val in rule.items():
        if key == "note":
            continue
        vals = _as_list(val)
        folded = [v.casefold() for v in vals]
        if key == "capability":
            ok = (facts["capability"] or "").casefold() in folded and facts["capability"] is not None
        elif key == "kind":
            ok = facts["kind"] is not None and facts["kind"].casefold() in folded
        elif key == "title":
            ok = facts["title"].casefold() in folded and bool(facts["title"])
        elif key == "resource":
            ok = facts["resource"] is not None and facts["resource"] in vals
        elif key == "command_prefix":
            cmds = facts["commands"]
            if not facts["is_shell"] or not cmds:
                ok = False
            elif is_deny:
                pieces = [s.strip(" (){}'\"\t") for c in cmds for s in SEGMENT_SPLIT.split(c)]
                ok = any(_prefix_ok(s, p) for s in pieces if s for p in vals)
            else:
                ok = all(not SHELL_CONTROL.search(c) and any(_prefix_ok(c, p) for p in vals) for c in cmds)
        elif key == "command_contains":
            hay = [c.casefold() for c in facts["commands"]] + [facts["title"].casefold()]
            ok = any(f in h for f in folded for h in hay)
        elif key == "path_under":
            ps = facts["paths"]
            if not ps:
                ok = False
            elif is_deny:
                ok = any(_under(p, d, facts["cwd"]) for p in ps for d in vals)
            else:
                ok = all(any(_under(p, d, facts["cwd"]) for d in vals) for p in ps)
        else:
            ok = False
        if not ok:
            return False
    return True


def decide(policy, policy_error, params, session_cwd):
    """-> (allow, reason). No policy: allow. A policy error: reject. Else deny wins, then allow, then "default"."""
    if policy is None:
        if policy_error:
            return False, policy_error
        return True, "default: all tools trusted (no policy file)"
    facts = request_facts(params, session_cwd)
    for i, rule in enumerate(policy.get("deny", [])):
        if rule_matches(rule, facts, True):
            return False, "deny[%d]" % i
    for i, rule in enumerate(policy.get("allow", [])):
        if rule_matches(rule, facts, False):
            return True, "allow[%d]" % i
    default = policy.get("default", "allow")
    return default == "allow", "no rule matched (default: %s)" % default


def pick_option(options, want_allow):
    """-> optionId or None. Allow only ever picks allow_once; reject prefers reject_once."""
    options = [o for o in options if isinstance(o, dict) and isinstance(o.get("optionId"), str)]
    kinds = ("allow_once",) if want_allow else ("reject_once", "reject_always")
    for k in kinds:
        for o in options:
            if o.get("kind") == k:
                return o["optionId"]
    return None


# ---------------------------------------------------------------- the driver

class Fail(Exception):
    pass


def future_mtime(path):
    try:
        return path.stat().st_mtime > time.time()
    except OSError:
        return False


def settled(path):
    """True when the file was last modified at least SETTLE_SECONDS ago: a half-written prompt is not read."""
    try:
        age = time.time() - path.stat().st_mtime
    except OSError:
        return False
    return age >= SETTLE_SECONDS or age < 0  # a future mtime (clock skew, a restored file) would never settle


def next_action(reason):
    r = reason.lower()
    if "cleanup" in r:
        return "do not start another run: tell the user cleanup is unconfirmed; inspect status.json and events.log and resolve the exact owned worker first; never kill processes by name."
    if "mismatch" in r or "drift" in r:
        return "do not retry with the same flags; read events.log for what the session reported and tell the user."
    if "not found" in r:
        return "pass --kiro PATH, or tell the user kiro-cli is missing."
    if "timed out" in r or "did not end" in r or "overall timeout" in r:
        return "read the end of out/*.txt and events.log for what it was doing; start a new work folder, with a larger timeout only if the task is genuinely long."
    return "read events.log and stderr.log, then start a new work folder; do not retry more than once without telling the user."


def kiro_command(kiro):
    return [sys.executable, kiro] if str(kiro).lower().endswith(".py") else [kiro]


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
    """Windows: puts the process in a Job Object that kills its whole tree when the handle closes (the driver exiting
    or dying included). Returns (kernel32, job handle) or None. Elsewhere the process group does this job."""
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


class Driver:
    def __init__(self, a):
        self.a = a
        self.work = Path(a.work).resolve()
        self.cwd = os.path.abspath(a.cwd)
        self.t0 = time.time()
        self.red = Redactor()
        self.lock = threading.Lock()
        self.config_lock = threading.RLock()
        self.cleanup_lock = threading.Lock()
        self.send_queue = queue.Queue()
        self.transport_error = None
        self.pending = {}
        self.next_id = 100
        self.proc = None
        self.posix_group = None
        self.posix_unreaped = False
        self.posix_kqueue = None
        self.posix_exit = None
        self.agent_gone = threading.Event()
        self.sid = None
        self.turn = 0
        self.out = None
        self.stream = StreamRedactor(self.red)
        self.refusals = 0
        self.kiro_path = None
        self.state = "starting"
        self.job = None
        self.terminating = False
        self.pid_start = proc_start(os.getpid())
        self.drift = None
        self.armed = False
        self.config = {}
        self.legacy_mode = None
        self.expected = {}
        self.selecting = {}
        self.cleanup_error = None
        self.status_lock = threading.Lock()
        for d in ("in", "out"):
            (self.work / d).mkdir(parents=True, exist_ok=True)
        self.logf = open(self.work / "events.log", "a", encoding="utf-8")

    # ---- files
    def log(self, msg):
        self.logf.write(time.strftime("%H:%M:%S ") + self.red.text(msg) + "\n")
        self.logf.flush()

    def clip(self, value, n):
        """Redact first, then cut: a secret cut in half would no longer match and would leak its first part."""
        return self.red.text(value if isinstance(value, str) else json.dumps(value))[:n]

    def set_status(self, state, **extra):
        self.state = state
        doc = {"state": state, "pid": os.getpid(), "pid_start": self.pid_start,
               "kiro_pid": self.proc.pid if self.proc else None,
               "turn": self.turn, "refusals": self.refusals,
               "updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
               "mode": self.config.get("mode", {}).get("currentValue"),
               "model": self.config.get("model", {}).get("currentValue"),
               "effort": self.config.get("effortLevel", {}).get("currentValue"), **extra}
        with self.status_lock:
            tmp = self.work / "status.json.tmp"
            tmp.write_text(self.red.text(json.dumps(doc)), encoding="utf-8")
            for _ in range(40):
                try:
                    os.replace(tmp, self.work / "status.json")
                    return
                except PermissionError:
                    time.sleep(0.05)

    def write_out(self, text):
        if self.out is not None:
            self.out.write(self.stream.feed(text))
            self.out.flush()

    def write_out_line(self, text):
        self.write_out("\n" + text + "\n")

    # ---- process and JSON-RPC plumbing
    def spawn(self):
        a = self.a
        kiro = a.kiro or shutil.which("kiro-cli")
        if not kiro or not (shutil.which(kiro) or os.path.isfile(kiro)):
            raise Fail("kiro-cli not found (pass --kiro PATH)")
        self.kiro_path = kiro
        cmd = kiro_command(kiro) + ["acp", "--agent-engine", "v3"]
        if os.name != "nt":
            # This standalone CLI owns the child's only reaping path. Retaining
            # self.proc prevents Popen's destructor from registering it for reap.
            # Clear inherited auto-reaping before launch; no user setting changes.
            try:
                signal.signal(signal.SIGCHLD, signal.SIG_DFL)
            except (OSError, ValueError) as exc:
                raise Fail("cannot reserve the POSIX child: %s; run the standalone driver on its main thread" % type(exc).__name__)
            if not all(hasattr(os, key) for key in ("waitid", "P_PID", "WEXITED", "WNOHANG", "WNOWAIT", "CLD_EXITED")):
                if not all(hasattr(select, key) for key in ("kqueue", "kevent", "KQ_FILTER_PROC", "KQ_EV_ADD", "KQ_EV_ENABLE", "KQ_NOTE_EXIT")):
                    raise Fail("no non-reaping POSIX child observer: use a host with waitid/WNOWAIT or BSD/macOS kqueue support")
                try:
                    self.posix_kqueue = select.kqueue()
                except OSError as exc:
                    raise Fail("cannot open POSIX kqueue: %s; use a host with a working non-reaping child observer" % type(exc).__name__)
        kwargs = {"start_new_session": True} if os.name != "nt" else {}
        try:
            self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                         cwd=self.cwd, **kwargs)
        except OSError as exc:
            if self.posix_kqueue is not None:
                self.posix_kqueue.close()
                self.posix_kqueue = None
            raise Fail("cannot start kiro-cli: %s" % type(exc).__name__)
        if os.name != "nt":
            self.posix_group = self.proc.pid  # start_new_session created exactly this owned group
            self.posix_unreaped = True
            if self.posix_kqueue is not None:
                try:
                    event = select.kevent(self.proc.pid, filter=select.KQ_FILTER_PROC,
                        flags=select.KQ_EV_ADD | select.KQ_EV_ENABLE, fflags=select.KQ_NOTE_EXIT)
                    self.posix_kqueue.control([event], 0, 0)
                except OSError as exc:
                    self.posix_unreaped = False
                    raise Fail("cannot observe the reserved POSIX child: %s; inspect cleanup failure before retrying" % type(exc).__name__)
        self.job = make_job(self.proc, self.log)
        self.set_status("starting")
        threading.Thread(target=self.read_stdout, daemon=True).start()
        threading.Thread(target=self.copy_stderr, daemon=True).start()
        threading.Thread(target=self.write_loop, daemon=True).start()

    def agent_poll(self):
        """Observe POSIX exit without reaping: reserve the leader PID until group cleanup."""
        p = self.proc
        if os.name == "nt" or self.posix_group is None:
            return p.poll()
        if p.returncode is not None:
            self.posix_unreaped = False
            return p.returncode
        if not self.posix_unreaped:
            return 0
        if self.posix_kqueue is not None:
            # NOTE_EXIT observes without wait()/poll(). With SIGCHLD default and
            # no other child reaper in this CLI, the zombie keeps its PID reserved.
            try:
                for event in self.posix_kqueue.control(None, 1, 0):
                    if (event.ident != p.pid or event.filter != select.KQ_FILTER_PROC
                            or event.flags & getattr(select, "KQ_EV_ERROR", 0)):
                        raise OSError("invalid child observer event")
                    if event.fflags & select.KQ_NOTE_EXIT:
                        self.posix_exit = "unavailable (kqueue NOTE_EXIT)"  # BSD event data is not portable status readback
            except OSError:
                self.posix_unreaped = False
                self.log("POSIX child observation failed; reservation can no longer be relied on")
                return 0
            return self.posix_exit
        try:
            info = os.waitid(os.P_PID, p.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
        except (ChildProcessError, OSError):
            self.posix_unreaped = False
            return 0  # ownership was lost or cannot be established; never signal by numeric PID
        if info is None:
            return None
        return info.si_status if info.si_code == os.CLD_EXITED else -info.si_status

    def wait_agent(self, timeout):
        if os.name == "nt" or self.posix_group is None:
            return self.proc.wait(timeout)
        end = time.monotonic() + timeout
        while True:
            code = self.agent_poll()
            if code is not None:
                return code
            if time.monotonic() >= end:
                raise subprocess.TimeoutExpired("owned ACP process", timeout)
            time.sleep(0.05)

    def group_owned(self):
        # Only an unreaped child reserves the numeric group identity. Absence
        # and creation-time probes cannot authorize a later numeric signal.
        self.agent_poll()
        return self.posix_unreaped

    def kill_tree(self, grace=0):
        """Ends the process tree of the one kiro-cli this driver started. Touches no other process.

        With grace, stdin is closed first and kiro-cli gets that many seconds to exit by itself."""
        with self.cleanup_lock:
            self._kill_tree(grace)

    def _kill_tree(self, grace):
        p = self.proc
        if p is None:
            return
        if grace and self.agent_poll() is None:
            def close_stdin():  # not under self.lock: a blocked send() would hold it forever
                try:
                    p.stdin.close()
                except (OSError, ValueError):
                    pass

            threading.Thread(target=close_stdin, daemon=True).start()
            try:
                self.wait_agent(grace)
            except subprocess.TimeoutExpired:
                self.log("kiro-cli still running %ds after stdin closed: killing its tree" % grace)
        if os.name == "nt":
            if p.poll() is None:
                # The job holds exactly the processes this driver started. taskkill /T walks parent pids, which can
                # match an unrelated orphan whose stale parent pid was recycled, so it is only the fallback.
                if self.job:
                    self.job[0].TerminateJobObject(self.job[1], 1)
                else:
                    subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True)
        elif self.posix_group is not None:
            for sig in (signal.SIGTERM, signal.SIGKILL):
                if not self.group_owned():
                    self.cleanup_error = "refusing process-group cleanup: the unreaped leader reservation was lost"
                    self.log(self.cleanup_error)
                    break
                try:
                    os.killpg(self.posix_group, sig)
                except ProcessLookupError:
                    break
                except PermissionError:
                    self.cleanup_error = "process-group cleanup denied; the owned worker may still be running"
                    self.log(self.cleanup_error)
                    break
                if sig == signal.SIGTERM:
                    try:
                        self.wait_agent(3)
                    except subprocess.TimeoutExpired:
                        pass
                # Parent exit is not group exit. Always escalate surviving descendants.
            self.posix_group = None  # release group identity only after the last group signal
            self.posix_unreaped = False
        if self.job:  # closing the handle kills whatever is left in the job, children of an already exited parent included
            k, job = self.job
            self.job = None
            k.CloseHandle(job)
        try:
            p.wait(10)
        except subprocess.TimeoutExpired:
            self.cleanup_error = self.cleanup_error or "process cleanup did not confirm child exit within 10s; the owned worker may still be running"
            self.log(self.cleanup_error)
        if self.posix_kqueue is not None:
            self.posix_kqueue.close()
            self.posix_kqueue = None

    def send(self, obj):
        self.send_queue.put((obj, (json.dumps(obj) + "\n").encode("utf-8")))

    def write_message(self, obj, data):
        # This lock also protects incoming snapshots and the completion commit.
        with self.config_lock:
            if obj.get("method") == "session/prompt":
                self.assert_config()
            self.proc.stdin.write(data)
            self.proc.stdin.flush()

    def watch_write(self, finished, method):
        """A blocked pipe or config lock must not prevent deadlines or stop handling."""
        started = time.time()
        limit = self.a.turn_timeout if method == "session/prompt" else self.a.startup_timeout
        stop_at = None
        while not finished.wait(0.1):
            now = time.time()
            if (self.work / "in" / "stop").exists() and stop_at is None:
                stop_at = now + self.a.cancel_grace
            if now - self.t0 > self.a.total_timeout or now - started > limit or (stop_at is not None and now > stop_at):
                self.transport_error = "pipe write timed out or did not end after the stop request"
                self.agent_gone.set()
                self.kill_tree()
                return

    def write_loop(self):
        while True:
            item = self.send_queue.get()
            if item is None:
                return
            obj, data = item
            if self.terminating or self.transport_error:
                return
            finished = threading.Event()
            threading.Thread(target=self.watch_write, args=(finished, obj.get("method")), daemon=True).start()
            try:
                self.write_message(obj, data)
            except Fail as exc:
                self.transport_error = str(exc)
                self.agent_gone.set()
                return
            except (OSError, ValueError):
                self.agent_gone.set()
                return
            finally:
                finished.set()

    def request(self, method, params):
        with self.lock:
            self.next_id += 1
            rid = self.next_id
        h = {"ev": threading.Event(), "resp": None, "method": method}
        self.pending[rid] = h
        self.send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        return h

    def wait(self, h, timeout, what, watch_stop=False):
        """Waits for a response. Raises Fail on timeout, agent exit or the overall deadline."""
        end = time.time() + timeout
        stop_sent = False
        while not h["ev"].wait(0.2):
            if self.transport_error:
                raise Fail(self.transport_error)
            if self.drift:
                raise Fail(self.drift)
            if self.agent_gone.is_set():
                raise Fail("kiro-cli exited during %s" % what)
            if time.time() - self.t0 > self.a.total_timeout:
                raise Fail("overall timeout of %ds reached during %s" % (self.a.total_timeout, what))
            if time.time() > end:
                if stop_sent:
                    raise Fail("%s did not end within %ds of the stop request (session/cancel was sent)" % (what, self.a.cancel_grace))
                raise Fail("%s timed out after %ds" % (what, timeout))
            if watch_stop and not stop_sent and (self.work / "in" / "stop").exists():
                stop_sent = True
                self.log("stop requested during a turn: sending session/cancel")
                self.send({"jsonrpc": "2.0", "method": "session/cancel", "params": {"sessionId": self.sid}})
                end = min(end, time.time() + self.a.cancel_grace)
        if self.drift:  # the reply can arrive in the same instant as the update that moved the mode
            raise Fail(self.drift)
        if self.transport_error:
            raise Fail(self.transport_error)
        if h["resp"] is None:
            raise Fail("kiro-cli exited during %s" % what)
        return h["resp"]

    def read_stdout(self):
        for line in self.proc.stdout:
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            try:
                self.handle(msg)
            except Exception as exc:  # a handler bug must not kill the reader
                with self.config_lock:
                    self.drift = self.drift or "protocol handler failed: %s" % type(exc).__name__
                self.log("handler error %r" % exc)
                for h in list(self.pending.values()):
                    h["ev"].set()
        self.log("agent stdout closed")
        self.agent_gone.set()
        for h in list(self.pending.values()):
            h["ev"].set()

    def copy_stderr(self):
        with open(self.work / "stderr.log", "a", encoding="utf-8") as f:
            for line in self.proc.stderr:
                f.write(self.red.text(line.decode("utf-8", "replace")))
                f.flush()

    # ---- messages from the agent
    def handle(self, msg):
        if "method" in msg and "id" in msg:
            m, rid, p = msg["method"], msg["id"], msg.get("params") or {}
            if m == "_kiro/auth/getAccessToken":
                threading.Thread(target=self.token_response, args=(rid,), daemon=True).start()
            elif m == "session/request_permission":
                self.on_permission(rid, p)
            else:
                self.log("REQUEST unhandled %s %s" % (m, self.clip(p, 300)))
                self.send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "not supported by this client"}})
        elif "method" in msg:
            m, p = msg["method"], msg.get("params") or {}
            if m == "session/update":
                u = p.get("update") or {}
                kind = u.get("sessionUpdate")
                if kind == "agent_message_chunk":
                    c = u.get("content") or {}
                    if c.get("type") == "text":
                        self.write_out(c.get("text", ""))
                elif kind in ("tool_call", "tool_call_update"):
                    st, ttl = u.get("status"), u.get("title")
                    if kind == "tool_call" or st in ("completed", "failed"):
                        self.log("TOOL %s %s %s" % (kind, st, self.clip(str(ttl), 200)))
                        if st == "failed":
                            self.write_out_line("[tool failed: %s]" % ttl)
                elif kind == "config_option_update":
                    self.log("update config_option_update keys=%s options=%s" % (
                        ",".join(sorted(str(k) for k in u)), self.describe_options(u.get("configOptions"))))
                    self.check_drift(u)
                elif kind not in ("agent_thought_chunk", "session_info_update"):
                    self.log("update %s" % kind)
            else:
                self.log("notify %s%s" % (m, (" " + self.clip(p, 400)) if "error" in m else ""))
        elif "id" in msg:
            h = self.pending.get(msg["id"])
            if h:
                with self.config_lock:
                    result = msg.get("result")
                    if h.get("method") in ("session/new", "session/set_config_option") and isinstance(result, dict) and (h["method"] == "session/new" or "configOptions" in result):
                        self.record_config(result, h["method"])
                    h["resp"] = msg
                    h["ev"].set()

    def describe_options(self, options):
        """`id=currentValue` for each config option, redacted and clipped, so a real run records the wire shape."""
        if not isinstance(options, list):
            return "(no configOptions list: %s)" % type(options).__name__
        return self.clip(" ".join("%s=%s" % (o.get("id"), json.dumps(o.get("currentValue"))) for o in options
                                  if isinstance(o, dict)), 400)

    def record_config(self, result, source):
        """Apply one full snapshot in receive order. Production calls run on the reader only."""
        with self.config_lock:
            try:
                options = result.get("configOptions", [] if source == "session/new" else None)
                snapshot = {}
                if not isinstance(options, list):
                    self.drift = "invalid configuration snapshot: configOptions must be a list"
                    raise Fail(self.drift)
                for opt in options:
                    if (not isinstance(opt, dict) or not isinstance(opt.get("id"), str) or not opt["id"]
                            or opt["id"] in snapshot or not isinstance(opt.get("currentValue"), str)):
                        self.drift = "invalid configuration snapshot: option id/currentValue must be unique strings"
                        raise Fail(self.drift)
                    if "options" in opt:
                        option_values(opt)  # validate every explicit choice container before publication
                    snapshot[opt["id"]] = opt
                # ACP can report mode separately from configOptions. Preserve that
                # explicit legacy binding without retaining withdrawn config options.
                if source == "session/new" and "mode" not in snapshot:
                    modes = result.get("modes")
                    mode = modes.get("currentModeId") if isinstance(modes, dict) else None
                    if isinstance(mode, str):
                        self.legacy_mode = mode
                if self.legacy_mode is not None and "mode" not in snapshot:
                    snapshot["mode"] = {"id": "mode", "currentValue": self.legacy_mode}
                self.config = snapshot
                for key in ("model", "effortLevel"):
                    if key in snapshot:
                        opt = snapshot[key]
                        self.log("%s: %s current=%s choices=%s" % (
                            source, key, json.dumps(opt["currentValue"]), json.dumps(option_values(opt))))
                if self.armed:
                    for key, pending in list(self.selecting.items()):
                        actual = snapshot.get(key, {}).get("currentValue")
                        value = pending["value"]
                        label = "effort" if key == "effortLevel" else key
                        if value not in option_values(snapshot.get(key)):
                            self.drift = self.drift or "%s drift: pending selected value is no longer advertised" % label
                        elif actual == value:
                            # Protection starts on the first wire confirmation, not
                            # when the client merely requests a future value.
                            self.expected[key] = value
                            del self.selecting[key]
                        elif actual != pending["previous"]:
                            self.drift = self.drift or "%s drift: unexpected value during selection" % label
                    for key, value in self.expected.items():
                        actual = self.config.get(key, {}).get("currentValue")
                        if actual != value and not self.drift:
                            self.drift = "%s drift: requested %r, %s reports %r" % (
                                "effort" if key == "effortLevel" else key, value, source, actual)
                        if key in ("model", "effortLevel") and value not in option_values(self.config.get(key)) and not self.drift:
                            self.drift = "%s drift: selected value is no longer advertised" % key
            except Exception as exc:
                # Publish failure before this lock can admit a prompt or completion.
                self.drift = self.drift or "invalid configuration snapshot: %s" % type(exc).__name__
                raise

    def check_drift(self, update):
        """Check every protected option, including during selection and between queued prompts."""
        with self.config_lock:
            self.record_config(update, "config_option_update")

    def assert_config(self):
        if self.transport_error:
            raise Fail(self.transport_error)
        if self.drift:
            raise Fail(self.drift)
        if self.selecting:
            raise Fail("configuration selection is not yet confirmed")
        for key, value in self.expected.items():
            actual = self.config.get(key, {}).get("currentValue")
            if actual != value:
                raise Fail("%s mismatch: requested %r, confirmed config reports %r" % (key, value, actual))

    def select_config(self, key, value):
        if value is None:
            return
        with self.config_lock:
            self.assert_config()
            option = self.config.get(key)
            choices = option_values(option)
            if option is None or value not in choices:
                raise Fail("unsupported %s %r: advertised choices are %s" % (key, value, json.dumps(choices)))
            needs_setter = option.get("currentValue") != value
            if needs_setter:
                self.selecting[key] = {"value": value, "previous": option["currentValue"]}
                self.expected.pop(key, None)
            else:
                self.expected[key] = value
        if needs_setter:
            self.log("select config %s=%s" % (key, json.dumps(value)))
            response = self.wait(self.request("session/set_config_option", {
                "sessionId": self.sid, "configId": key, "value": value}),
                self.a.startup_timeout, "session/set_config_option " + key)
            result = response.get("result")
            if not isinstance(result, dict):
                raise Fail("session/set_config_option %s failed: %s" % (key, self.clip(response.get("error"), 300)))
            readback = next((o for o in result.get("configOptions", [])
                             if isinstance(o, dict) and o.get("id") == key), None)
            if readback is None or readback.get("currentValue") != value:
                raise Fail("%s mismatch: requested %r, session/set_config_option reports %r" % (
                    "effort" if key == "effortLevel" else key, value,
                    readback.get("currentValue") if readback else None))
        with self.config_lock:
            self.assert_config()
        self.log("confirmed config %s=%s" % (key, json.dumps(value)))

    def token_response(self, rid):
        try:
            r = subprocess.run(kiro_command(self.kiro_path) + ["chat", "_", "get-kas-token"], capture_output=True,
                               text=True, timeout=20, cwd=self.cwd)
            d = json.loads(r.stdout)["data"]
            self.red.add(d.get("accessToken"), d.get("profileArn"))
            self.send({"jsonrpc": "2.0", "id": rid, "result": {
                "accessToken": d["accessToken"], "expiresAt": d["expiresAt"],
                "profileArn": d.get("profileArn", ""), "provider": d.get("provider", "")}})
            self.log("token supplied")
        except Exception as exc:
            self.log("token fetch failed: %s" % type(exc).__name__)
            self.send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32000, "message": "token fetch failed"}})

    def on_permission(self, rid, params):
        policy, err = load_policy(self.work / "policy.json")
        allow, reason = decide(policy, err, params, self.cwd)
        facts = request_facts(params, self.cwd)
        title = self.clip(facts["title"], 200)
        option = pick_option(params.get("options") if isinstance(params.get("options"), list) else [], allow)
        if allow and option is None:
            allow, reason = False, "allowed by %s but the request offers no allow_once option" % reason
            option = pick_option(params.get("options") if isinstance(params.get("options"), list) else [], False)
        self.log("PERMISSION %s (%s) | title=%s kind=%s capability=%s resource=%s commands=%s paths=%s" % (
            "ALLOW" if allow else "REJECT", reason, title, facts["kind"], facts["capability"],
            self.clip(facts["resource"] or "", 200), self.clip(facts["commands"], 600), self.clip(facts["paths"], 400)))
        if allow:
            self.write_out_line("[permission allowed by policy %s: %s]" % (reason, title))
        else:
            self.refusals += 1
            self.write_out_line("[permission REFUSED (%s): %s] The delegate was refused this tool call." % (reason, title))
            self.set_status(self.state)
        outcome = {"outcome": "selected", "optionId": option} if option else {"outcome": "cancelled"}
        self.send({"jsonrpc": "2.0", "id": rid, "result": {"outcome": outcome}})

    # ---- run
    def handshake(self):
        a = self.a
        h = self.request("initialize", {"protocolVersion": ACP_PROTOCOL_VERSION, "clientInfo": {
            "name": "qkiro-delegate", "version": "1.0"}, "clientCapabilities": {
            "fs": {"readTextFile": False, "writeTextFile": False}, "terminal": False}})
        r = self.wait(h, a.startup_timeout, "initialize")
        if "result" not in r:
            raise Fail("initialize failed: %s" % self.clip(r.get("error"), 300))
        self.log("initialize: ok")
        h = self.request("session/new", {"cwd": self.cwd, "mcpServers": [], "workspacePaths": [self.cwd],
                                         "_meta": {"kiro": {"modeId": a.mode}}})
        r = self.wait(h, a.startup_timeout, "session/new")
        if "result" not in r:
            raise Fail("session/new failed: %s" % self.clip(r.get("error"), 300))
        res = r["result"]
        self.sid = res.get("sessionId") or (res.get("_meta") or {}).get("id")
        mode, model = read_back(res)
        self.log("session/new: %s mode=%s model=%s options=%s" % (
            self.sid, json.dumps(mode), json.dumps(model), self.describe_options(res.get("configOptions"))))
        if not self.sid:
            raise Fail("session/new returned no session id")
        (self.work / "session.txt").write_text(self.red.text(str(self.sid)), encoding="utf-8")
        if mode != a.mode:
            raise Fail("mode mismatch: requested %r, session/new reports %r" % (a.mode, mode))
        with self.config_lock:
            self.expected["mode"] = a.mode
            self.armed = True
            self.assert_config()
        self.select_config("model", a.model)
        self.select_config("effortLevel", getattr(a, "effort", None))

    def run_turn(self, path):
        self.assert_config()
        self.turn = int(path.stem)
        text = path.read_text(encoding="utf-8-sig")
        self.out = open(self.work / "out" / path.with_suffix(".txt").name, "w", encoding="utf-8")
        self.stream = StreamRedactor(self.red)
        self.set_status("turn %d running" % self.turn)
        self.log("PROMPT %s: %s" % (path.name, self.clip(text, 200).replace("\n", " ")))
        try:
            h = self.request("session/prompt", {"sessionId": self.sid, "prompt": [{"type": "text", "text": text}]})
            r = self.wait(h, self.a.turn_timeout, "turn %d" % self.turn, watch_stop=True)
        except Fail as exc:
            self.write_out_line("[%s]" % exc)
            self.out.write(self.stream.flush())
            self.out.close()
            self.out = None
            raise
        if "result" not in r:
            err = self.clip(r.get("error"), 500)
            self.write_out_line("[turn %d errored: %s]" % (self.turn, err))
            self.out.write(self.stream.flush())
            self.out.close()
            self.out = None
            raise Fail("turn %d got an error reply: %s" % (self.turn, err))
        stop = r["result"].get("stopReason")
        self.write_out_line("[end of turn: %s]" % stop)
        self.out.write(self.stream.flush())
        self.out.close()
        self.out = None
        done = self.work / "out" / (path.stem + ".done")
        with self.config_lock:
            self.assert_config()  # completion guard: no success after already observed drift
            done.write_text(self.red.text(str(stop)), encoding="utf-8")
            self.set_status("turn %d done" % self.turn, stop_reason=self.red.text(str(stop)))
        self.log("TURN END %s %s" % (path.name, stop))

    def main_loop(self):
        seen = set()
        self.set_status("ready")
        while True:
            if self.transport_error:
                raise Fail(self.transport_error)
            if self.drift:
                raise Fail(self.drift)
            if (self.work / "in" / "stop").exists():
                return
            if self.agent_gone.is_set() or self.agent_poll() is not None:
                raise Fail("kiro-cli exited (code %s)" % self.agent_poll())
            if time.time() - self.t0 > self.a.total_timeout:
                raise Fail("overall timeout of %ds reached" % self.a.total_timeout)
            unseen = [p for p in sorted((self.work / "in").glob("*.txt")) if PROMPT_STEM.fullmatch(p.stem) and p.name not in seen]
            if unseen and settled(unseen[0]):  # the lowest stem only: a later prompt never overtakes an unsettled one
                if future_mtime(unseen[0]):
                    self.log("warning: %s has a modification time in the future; treating it as settled" % unseen[0].name)
                seen.add(unseen[0].name)
                self.run_turn(unseen[0])
                continue
            time.sleep(0.2)

    def run(self):
        def on_signal(signum, frame):
            if not self.terminating:  # once failing or stopping, a signal must not interrupt the cleanup
                raise Fail("the driver received signal %d" % signum)

        for name in ("SIGTERM", "SIGBREAK", "SIGINT"):
            sig = getattr(signal, name, None)
            if sig is None or (name == "SIGINT" and signal.getsignal(sig) == signal.SIG_IGN):
                continue  # a SIGINT the parent chose to ignore (a background job) stays ignored
            signal.signal(sig, on_signal)
        try:
            try:
                self.set_status("starting")
                self.spawn()
                self.handshake()
                self.main_loop()
            except Fail as exc:
                self.fail(str(exc))
                return 1
            except KeyboardInterrupt:  # only if installing the SIGINT handler failed; harmless defence
                self.fail("the driver was interrupted")
                return 1
            except Exception as exc:
                self.fail("driver error: %s: %s" % (type(exc).__name__, exc))
                return 1
            if self.drift:
                self.fail(self.drift)
                return 1
            self.terminating = True
            self.log("driver stopping")
            self.kill_tree(grace=self.a.stop_grace)
            if self.cleanup_error:
                self.fail(self.cleanup_error)
                return 1
            self.agent_gone.wait(1.0)  # let read_stdout drain what kiro-cli wrote on its way out
            if self.drift:  # an update can land while kiro-cli is still shutting down
                self.fail(self.drift)
                return 1
            self.set_status("stopped")
            return 0
        finally:
            self.logf.flush()

    def fail(self, reason):
        self.terminating = True
        reason = self.red.text(reason)
        self.log("FAILED: " + reason)
        self.kill_tree()
        if self.cleanup_error and self.cleanup_error not in reason:
            reason += "; " + self.cleanup_error
        (self.work / "FAILED").write_text("%s\nNext action: %s\n" % (reason, next_action(reason)), encoding="utf-8")
        self.set_status("failed", reason=reason)


def option_values(option):
    """Flatten select choices, rejecting malformed flat/nested choice containers."""
    if option is None:
        return []  # a withdrawn/missing control is checked by its caller
    if not isinstance(option, dict) or not isinstance(option.get("options", []), list):
        raise Fail("invalid configuration choices: options must be a list")
    values = []
    for item in option.get("options", []):
        if not isinstance(item, dict):
            raise Fail("invalid configuration choices: each choice must be an object")
        if "value" in item:
            if not isinstance(item["value"], str) or "options" in item:
                raise Fail("invalid configuration choices: a leaf needs a string value")
            values.append(item["value"])
        elif "options" in item:
            if "group" in item and not isinstance(item["group"], str):
                raise Fail("invalid configuration choices: group must be a string")
            values.extend(option_values(item))
        else:
            raise Fail("invalid configuration choices: expected a value or a group")
    return values


def read_back(res):
    """-> (mode, model) as session/new reports them; None when it does not say."""
    modes = res.get("modes") if isinstance(res.get("modes"), dict) else {}
    models = res.get("models") if isinstance(res.get("models"), dict) else {}
    mode, model = modes.get("currentModeId"), models.get("currentModelId")
    for opt in res.get("configOptions") if isinstance(res.get("configOptions"), list) else []:
        if isinstance(opt, dict) and opt.get("id") == "mode" and mode is None:
            mode = opt.get("currentValue")
        if isinstance(opt, dict) and opt.get("id") == "model" and model is None:
            model = opt.get("currentValue")
    return mode, model


# ---------------------------------------------------------------- waiter

def read_status(work):
    for _ in range(5):
        try:
            return json.loads((work / "status.json").read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (ValueError, PermissionError):
            time.sleep(0.05)
    return None


def cmd_wait(a):
    work = Path(a.work).resolve()
    turn = a.turn
    if turn is None:
        nums = [int(p.stem) for p in (work / "in").glob("*.txt") if PROMPT_STEM.fullmatch(p.stem)] if (work / "in").is_dir() else []
        if not nums:
            print("state: nothing to wait for\nreason: no in/NNN.txt in %s\nnext: write the prompt as in/001.tmp, rename it to in/001.txt, then wait" % (work / "in"))
            return 5
        turn = max(nums)
    stem = "%03d" % turn
    reply, done, failed = work / "out" / (stem + ".txt"), work / "out" / (stem + ".done"), work / "FAILED"
    t0 = time.time()
    end = t0 + a.timeout

    def report(code, state, **kv):
        st = read_status(work) or {}
        print("turn: %d\nstate: %s" % (turn, state))
        if reply.exists():
            print("reply: %s" % reply)
        for k, v in kv.items():
            print("%s: %s" % (k, v))
        print("refusals: %s" % st.get("refusals", 0))
        return code

    while True:
        if done.exists():
            return report(0, "turn %d done" % turn, stop_reason=done.read_text(encoding="utf-8").strip())
        if failed.exists():
            reason, _, nxt = failed.read_text(encoding="utf-8").strip().partition("\nNext action: ")
            return report(1, "failed", reason=reason, next=nxt or "read events.log")
        st = read_status(work)
        if st and st.get("state") == "stopped":
            return report(4, "stopped", reason="the run was stopped (in/stop) before turn %d finished" % turn,
                          next="start a new run in a fresh work folder if the task is not finished")
        dead = (st and st.get("state") not in TERMINAL_STATES and not pid_alive(st.get("pid"), st.get("pid_start")))
        if dead:
            return report(3, "driver dead", reason="driver pid %s is gone (or reused) and status.json says %r"
                          % (st.get("pid"), st.get("state")),
                          next="read the end of events.log, then start a new run in a fresh work folder; do not kill processes by name")
        if st is None and time.time() - t0 > a.status_grace:
            return report(3, "driver dead", reason="no status.json appeared within %ds: the driver never started" % a.status_grace,
                          next="run the driver in the foreground once to see its error")
        if time.time() > end:
            return report(2, "timeout", reason="no result after %ds; last state %r" % (a.timeout, (st or {}).get("state")),
                          next="wait again, or read the end of out/%s.txt to see progress" % stem)
        time.sleep(a.poll)


def main(argv):
    ap = argparse.ArgumentParser(prog="acp-driver.py", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--work", required=True)
    r.add_argument("--cwd", required=True, help="the session working directory")
    r.add_argument("--kiro", help="path to kiro-cli (default: kiro-cli on PATH); a .py file runs under this interpreter")
    r.add_argument("--mode", default="kiro_default", help="mode bound at session/new and asserted on read-back")
    r.add_argument("--model", help="exact advertised model selected through ACP and asserted on read-back (e.g. claude-sonnet-4.6)")
    r.add_argument("--effort", help="exact advertised effortLevel selected through ACP and asserted on read-back (e.g. max); omitted preserves the session default")
    r.add_argument("--turn-timeout", type=int, default=1800)
    r.add_argument("--total-timeout", type=int, default=7200)
    r.add_argument("--startup-timeout", type=int, default=180)
    r.add_argument("--stop-grace", type=int, default=5, help="seconds kiro-cli gets to exit after in/stop before its tree is killed")
    r.add_argument("--cancel-grace", type=int, default=30, help="seconds a turn gets to end after in/stop cancels it")
    w = sub.add_parser("wait")
    w.add_argument("--work", required=True)
    w.add_argument("--turn", type=int)
    w.add_argument("--timeout", type=int, default=600)
    w.add_argument("--poll", type=float, default=1.0)
    w.add_argument("--status-grace", type=int, default=15, help="seconds to wait for the first status.json of the driver")
    a = ap.parse_args(argv)
    if a.cmd == "wait":
        return cmd_wait(a)
    return Driver(a).run()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
