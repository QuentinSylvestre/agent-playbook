"""Selftest for claude-delegate.py against fake-claude.py. No network, no real claude, about a minute.

Run: <python> -I shared/skills/qclaude-delegate/scripts/selftest.py
Prints `FAIL: <check>` lines, then `qclaude-delegate selftest: N checks, M failed`. Exit 0 only when none failed.
Each scenario runs a real `claude-delegate.py run` process against the stub in its own temp directory. Every process
it starts (and a stub child it recorded) is ended before it returns.

The full run ends with mutants: copies of claude-delegate.py with one safety check broken, each run against the
group of scenarios meant to catch it. A mutant the suite does not catch is a failed check.

Options (for maintainers): --driver PATH runs the suite against another copy of the script; --groups a,b runs only
those groups and no mutants; --mutants adds the mutants to a --groups run.
"""
import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
DRIVER = HERE / "claude-delegate.py"
STUB = HERE / "fake-claude.py"
PY = sys.executable
FAILS, CHECKS = [], [0]
LIVE = []  # Popen of every run started
COUNTER = [0]
API_KEY = "FAKE-APIKEY-9f3a7c1d-4e2b-DO-NOT-LOG"
LEAK = "sk-ant-api03-LEAKYLEAKY0123456789"  # leak-scan: ignore (fake key the redaction test plants)
GROUPS = ("units", "basic", "resume", "refusal", "mismatch", "exit", "args", "timeout", "kill", "waiter", "secret")


def chk(name, cond, detail=""):
    CHECKS[0] += 1
    if not cond:
        FAILS.append("%s%s" % (name, (": " + detail) if detail else ""))


def load_module():
    spec = importlib.util.spec_from_file_location("claude_delegate", str(DRIVER))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def read(path):
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return ""


def jread(path):
    try:
        return json.loads(read(path))
    except ValueError:
        return None


def pid_of(folder, name):
    try:
        return int((Path(folder) / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def pid_gone(mod, pid, secs=10):
    if pid is None:
        return False
    end = time.time() + secs
    while time.time() < end:
        if not mod.pid_alive(pid):
            return True
        time.sleep(0.1)
    return False


def start(root, name, prompt=b"hello\n", scenario=None, extra=(), env=None, claude=None, newgroup=False, keep=False):
    """Starts `run`. The work and cwd folders are root/name/{work,cwd}; keep=True reuses them (a later turn)."""
    base = root / name
    work, cwd = base / "work", base / "cwd"
    work.mkdir(parents=True, exist_ok=keep)
    cwd.mkdir(parents=True, exist_ok=keep)
    if scenario is not None:
        (cwd / "scenario.json").write_text(json.dumps(scenario), encoding="utf-8")
    COUNTER[0] += 1
    pf = base / ("prompt-%d.txt" % COUNTER[0])
    pf.write_bytes(prompt if isinstance(prompt, bytes) else prompt.encode("utf-8"))
    cmd = [PY, "-I", str(DRIVER), "run", "--work", str(work), "--cwd", str(cwd), "--prompt-file", str(pf),
           "--claude", str(claude or STUB), *extra]
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if newgroup and os.name == "nt" else 0
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=flags,
                            env=dict(os.environ, **(env or {})))
    LIVE.append(proc)
    return proc, work, cwd


def finish(proc, secs=60):
    """-> (returncode, stdout, stderr). A run that outlives secs is killed (it is one this selftest started)."""
    try:
        out, err = proc.communicate(timeout=secs)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
    return proc.returncode, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")


def run_sync(root, name, **kw):
    proc, work, cwd = start(root, name, **kw)
    rc, out, err = finish(proc)
    return rc, out, err, work, cwd


def waiter(work, timeout=15, turn=None, extra=()):
    cmd = [PY, "-I", str(DRIVER), "wait", "--work", str(work), "--timeout", str(timeout), "--poll", "0.1", *extra]
    if turn is not None:
        cmd += ["--turn", str(turn)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 30)
    return r.returncode, r.stdout


def status(work):
    return jread(Path(work) / "status.json")


def wait_for(cond, secs=15):
    end = time.time() + secs
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def last_argv(cwd):
    lines = [l for l in read(Path(cwd) / "argv.log").splitlines() if l.strip()]
    return json.loads(lines[-1]) if lines else []


def child_record(mod, cwd):
    """-> (pid, creation time) of the child the stub recorded, read while it is running."""
    pid = pid_of(cwd, "child.pid")
    return pid, (mod.proc_start(pid) if pid else None)


def reap_child(mod, rec):
    """POSIX: ends a child the stub started that a hard kill left behind. Only a process whose pid still has the
    creation time recorded is touched, so a reused pid is never signalled. Windows: the job already ended it."""
    pid, started = rec
    if os.name != "nt" and pid and started is not None and mod.pid_alive(pid, started):
        os.kill(pid, signal.SIGKILL)


def tree_files(*roots):
    return [p for r in roots for p in Path(r).rglob("*") if p.is_file()]


# ---------------------------------------------------------------- groups

def g_units(mod, root):
    for req, rep, want in (("sonnet", "claude-sonnet-5-5", True), ("opus", "claude-sonnet-5-5", False),
                           ("claude-opus-4-7", "claude-opus-4-7", True), ("claude-opus-4-7", "claude-opus-4-7-x", False),
                           ("claude-sonnet-5", "claude-sonnet-5-5", False), ("opus[1m]", "claude-opus-4-7[1m]", True),
                           ("sonnet", None, False), ("sonn", "claude-sonnet-5-5", False), ("net", "claude-sonnet-5-5", False),
                           ("opus-4", "claude-opus-4-7", True), ("opus-7", "claude-opus-4-7", False)):
        chk("unit: model_matches(%r, %r) is %s" % (req, rep, want), mod.model_matches(req, rep) is want)
    red = mod.Redactor({"ANTHROPIC_API_KEY": API_KEY, "HARMLESS_NOTE": "do-not-redact-this-value",
                        "SHORT_TOKEN": "tiny", "GITHUB_TOKEN": "ghp_0123456789abcdef"})
    chk("unit: a secret-named env value is redacted", API_KEY not in red.text("x %s y" % API_KEY))
    chk("unit: a value under another name is kept", "do-not-redact-this-value" in red.text("do-not-redact-this-value"))
    chk("unit: a value shorter than 12 characters is not a secret", red.text("tiny") == "tiny")
    chk("unit: bearer text is redacted", "abcdefghijk" not in red.text("Authorization: Bearer abcdefghijklmnop"))
    chk("unit: sk-ant text is redacted", LEAK not in red.text("key " + LEAK))
    cleaned = red.obj({"a": ["x " + API_KEY, 3, None], "b": {"c": API_KEY}})
    chk("unit: obj redacts every string leaf and keeps the shape", API_KEY not in json.dumps(cleaned) and cleaned["a"][1] == 3, repr(cleaned))
    chk("unit: claude_command runs a .py under this interpreter",
        mod.claude_command("x.py")[0] == sys.executable and mod.claude_command("claude") == ["claude"])
    chk("unit: next_action names the turn's files", "events-004.jsonl" in mod.next_action("boom", 4))
    na = mod.next_action("claude exited with code 0 and sent no result event", 2)
    chk("unit: next_action for no result event points at stderr, not at result files", "stderr-002.log" in na and "result-002.json" not in na, na)
    chk("unit: next_action for a failed result points at the result file", "result-002.json" in mod.next_action("the result event reports subtype 'x', is_error True", 2))
    chk("unit: next_action for no init event says the turn cannot be trusted", "do not trust" in mod.next_action("the stream carried no init event, so x", 2))
    # A turn number is claimed by exclusive create, so a stale listing cannot hand out a number twice.
    claim = root / "claim"
    claim.mkdir()
    (claim / "events-001.jsonl").write_text("", encoding="utf-8")
    real, calls = mod.turn_numbers, [0]

    def stale(work):
        calls[0] += 1
        return [] if calls[0] == 1 else real(work)

    mod.turn_numbers = stale
    try:
        turn, f = mod.claim_turn(claim)
        f.close()
    finally:
        mod.turn_numbers = real
    chk("unit: a clash on the claimed turn moves on to the next number", turn == 2 and (claim / "events-002.jsonl").exists(), str(turn))
    turn, f = mod.claim_turn(claim)
    f.close()
    chk("unit: the next claim is 3", turn == 3, str(turn))
    # The busy re-check after a claim ignores a later claimant's status, so the lower claimant proceeds.
    held, me = root / "held", os.getpid()
    held.mkdir()
    (held / "status.json").write_text(json.dumps({"state": "running", "pid": me, "pid_start": mod.proc_start(me), "turn": 5}), encoding="utf-8")
    chk("unit: a live run in the folder makes it busy", "busy" in (mod.busy_message(held) or ""))
    chk("unit: an earlier claimant is not held up by a later claimant's status", mod.busy_message(held, 3) is None)
    chk("unit: a later claimant gives way to an earlier run's status", "busy" in (mod.busy_message(held, 7) or ""))
    (held / "status.json").write_text(json.dumps({"state": "done", "pid": me, "pid_start": mod.proc_start(me), "turn": 5}), encoding="utf-8")
    chk("unit: a finished run does not make the folder busy", mod.busy_message(held) is None)
    chk("unit: next_action for a mismatch says do not retry", "do not retry" in mod.next_action("model mismatch: x", 1))
    me = os.getpid()
    start_time = mod.proc_start(me)
    chk("unit: a live pid is alive", mod.pid_alive(me))
    chk("unit: a pid with another creation time is not the same process", start_time is None or not mod.pid_alive(me, start_time + 1))
    chk("unit: no such pid is not alive", not mod.pid_alive(2 ** 22 + 7) and not mod.pid_alive(None))


def g_basic(mod, root):
    text = ("line one with \"quotes\" and a back\\slash\n" + "naive cafe éè 中文 and an apostrophe's\n" * 6000)
    prompt = text.encode("utf-8")
    rc, out, err, work, cwd = run_sync(root, "basic", prompt=prompt, scenario={}, extra=["--model", "sonnet", "--effort", "high"])
    chk("basic: run exits 0", rc == 0, "%s %r %r" % (rc, out, err))
    argv = last_argv(cwd)
    chk("basic: the flags are -p, stream-json, --verbose and permission mode auto",
        "-p" in argv and "--verbose" in argv and argv[argv.index("--output-format") + 1] == "stream-json"
        and argv[argv.index("--permission-mode") + 1] == "auto", repr(argv))
    chk("basic: model and effort are passed through", argv[argv.index("--model") + 1] == "sonnet" and argv[argv.index("--effort") + 1] == "high", repr(argv))
    chk("basic: the prompt is not in argv", "line one" not in " ".join(argv) and len(" ".join(argv)) < 300)
    res = jread(work / "result-001.json") or {}
    want = "prompt bytes=%d sha256=%s first=%s" % (len(prompt), hashlib.sha256(prompt).hexdigest(), text.splitlines()[0][:80])
    chk("basic: a 300 KB prompt arrives whole through stdin", res.get("result") == want, repr(res.get("result"))[:200])
    chk("basic: reply-001.txt holds the result text", read(work / "reply-001.txt") == want)
    chk("basic: result-001.json fields", res.get("ok") is True and res.get("turn") == 1 and res.get("subtype") == "success"
        and res.get("permission_mode") == "auto" and res.get("model") == "claude-sonnet-5-5" and res.get("num_turns") == 1
        and res.get("refusals") == 0 and res.get("duration_ms") == 1234, repr(res)[:400])
    chk("basic: usage is an estimate, not a spend", (res.get("estimated_usage") or {}).get("usd") == 0.17
        and (res.get("estimated_usage") or {}).get("session_total_usd") == 0.17
        and "not billed on a subscription" in (res.get("estimated_usage") or {}).get("note", ""), repr(res.get("estimated_usage")))
    chk("basic: session.txt holds the session id", read(work / "session.txt") == "aaaaaaaa-0000-4000-8000-000000000001" == res.get("session_id"), read(work / "session.txt"))
    lines = read(work / "events-001.jsonl").splitlines()
    kinds = []
    for l in lines:
        try:
            kinds.append((json.loads(l).get("type"), json.loads(l).get("subtype")))
        except ValueError:
            kinds.append(("invalid", l[:40]))
    chk("basic: events-001.jsonl is one JSON object per line, init and result included",
        ("system", "init") in kinds and ("result", "success") in kinds and not any(k[0] == "invalid" for k in kinds), repr(kinds))
    st = status(work) or {}
    chk("basic: status is done for turn 1", st.get("state") == "done" and st.get("turn") == 1 and st.get("refusals") == 0, repr(st))
    chk("basic: no FAILED file", not list(work.glob("FAILED*")))
    chk("basic: prints the turn and the files", "turn: 1" in out and "reply: " in out and "result-001.json" in out, out)
    wrc, wout = waiter(work, turn=1)
    chk("basic: waiter exits 0 and says estimate", wrc == 0 and "estimated_usage: ~$0.17 this turn, ~$0.17 session total (API-price equivalent; not billed on a subscription" in wout, "%s %r" % (wrc, wout))
    chk("basic: waiter prints the reply path and session", "reply: " in wout and "session_id: aaaaaaaa" in wout and "refusals: 0" in wout, wout)
    chk("basic: the stub is gone", pid_gone(mod, pid_of(cwd, "stub.pid")))

    rc, out, err, work, cwd = run_sync(root, "basic-key", scenario={"api_key_source": "ANTHROPIC_API_KEY"})
    res = jread(work / "result-001.json") or {}
    chk("basic: with an API key the usage note says the account may be billed",
        rc == 0 and "may be billed" in (res.get("estimated_usage") or {}).get("note", ""), repr(res.get("estimated_usage")))

    rc, out, err, work, cwd = run_sync(root, "basic-bom", prompt=b"\xef\xbb\xbfhello\n", scenario={})
    res = jread(work / "result-001.json") or {}
    chk("basic: a UTF-8 BOM in the prompt file is dropped", rc == 0 and (res.get("result") or "").startswith("prompt bytes=6 ") and "first=hello" in res.get("result", ""), repr(res.get("result")))


def g_resume(mod, root):
    rc, out, err, work, cwd = run_sync(root, "resume", scenario={})
    sid = read(work / "session.txt")
    chk("resume: turn 1 ran", rc == 0 and sid, "%s %r" % (rc, err))
    proc, _, _ = start(root, "resume", prompt=b"second turn\n", extra=["--continue-work"], keep=True)
    rc, out, err = finish(proc)
    argv = last_argv(cwd)
    chk("resume: --continue-work exits 0 as turn 2", rc == 0 and "turn: 2" in out, "%s %r %r" % (rc, out, err))
    chk("resume: the recorded session is resumed", "--resume" in argv and argv[argv.index("--resume") + 1] == sid, repr(argv))
    res2 = jread(work / "result-002.json") or {}
    chk("resume: the same session id comes back, and no new session was started", res2.get("session_id") == sid and read(cwd / "sessions.count") == "1", repr(res2.get("session_id")))
    chk("resume: turn 1 files are kept", (work / "result-001.json").exists() and (work / "events-001.jsonl").exists() and (work / "events-002.jsonl").exists())
    wrc, wout = waiter(work, turn=2)
    chk("resume: the waiter reads turn 2", wrc == 0 and "turn: 2" in wout, wout)
    u1, u2 = (jread(work / "result-001.json") or {}).get("estimated_usage") or {}, res2.get("estimated_usage") or {}
    chk("resume: the result total is the session's running total, so turn 2 is billed only its own part",
        u1.get("usd") == 0.17 and u2.get("session_total_usd") == 0.184 and u2.get("usd") == 0.014, repr((u1, u2)))
    proc, _, _ = start(root, "resume", prompt=b"third\n", extra=["--continue-work"], keep=True)
    rc, out, err = finish(proc)
    u3 = (jread(work / "result-003.json") or {}).get("estimated_usage") or {}
    chk("resume: a third turn is numbered 3 and subtracts turn 2's total", rc == 0 and u3.get("usd") == 0.014 and u3.get("session_total_usd") == 0.198, "%s %r" % (out, u3))
    wrc, wout = waiter(work, turn=3)
    chk("resume: the waiter prints the turn and the session total", "~$0.014 this turn, ~$0.198 session total" in wout, wout)

    # A session started elsewhere.
    other = "bbbbbbbb-0000-4000-8000-000000000042"
    rc, out, err, work2, cwd2 = run_sync(root, "resume-explicit", scenario={}, extra=["--resume", other])
    chk("resume: --resume SESSION passes it on and accepts the same id back", rc == 0 and last_argv(cwd2)[last_argv(cwd2).index("--resume") + 1] == other, "%s %r" % (rc, err))

    # The session id that comes back differs: the run fails and the record stays.
    proc, _, _ = start(root, "resume", prompt=b"fourth\n", scenario={"resume_new_session": True}, extra=["--continue-work"], keep=True)
    rc, out, err = finish(proc)
    chk("resume: a different session id on resume fails the run", rc == 1 and "session mismatch" in read(work / "FAILED-004"), "%s %r" % (rc, read(work / "FAILED-004")))
    chk("resume: the failed turn did not replace the recorded session", read(work / "session.txt") == sid)

    # --continue-work with nothing to continue is a usage error and leaves no turn behind.
    rc, out, err, work3, cwd3 = run_sync(root, "resume-none", scenario={}, extra=["--continue-work"])
    chk("resume: --continue-work without session.txt exits 2 and starts nothing", rc == 2 and "no session.txt" in err and not list(work3.glob("events-*")), "%s %r" % (rc, err))


def g_refusal(mod, root):
    rc, out, err, work, cwd = run_sync(root, "refusal", scenario={"denials": ["rm -rf ../victim ."]})
    res = jread(work / "result-001.json") or {}
    chk("refusal: a refused tool call does not fail the turn", rc == 0 and res.get("ok") is True, "%s %r" % (rc, err))
    chk("refusal: result-001.json counts and lists it", res.get("refusals") == 1 and res["permission_denials"][0]["tool_name"] == "Bash"
        and res["permission_denials"][0]["tool_input"]["command"] == "rm -rf ../victim .", repr(res.get("permission_denials")))
    chk("refusal: status carries the count", (status(work) or {}).get("refusals") == 1, repr(status(work)))
    wrc, wout = waiter(work, turn=1)
    chk("refusal: the waiter prints the count and the refused call", wrc == 0 and "refusals: 1" in wout and "refused: Bash" in wout and "rm -rf" in wout, wout)
    chk("refusal: the refused tool_result is in the events", '"is_error": true' in read(work / "events-001.jsonl"))


def g_mismatch(mod, root):
    rc, out, err, work, cwd = run_sync(root, "mode", scenario={"init_mode": "plan"})
    chk("mismatch: a permission mode other than auto exits 1", rc == 1, "%s %r" % (rc, out))
    failed = read(work / "FAILED-001")
    chk("mismatch: FAILED names the mode and a next action", "permission mode mismatch" in failed and "'plan'" in failed and "Next action:" in failed, failed)
    chk("mismatch: no result file for a refused session", not (work / "result-001.json").exists() and not (work / "session.txt").exists())
    chk("mismatch: status failed", (status(work) or {}).get("state") == "failed")
    wrc, wout = waiter(work, turn=1)
    chk("mismatch: the waiter exits 1 with reason and next", wrc == 1 and "mismatch" in wout and "next: " in wout, "%s %r" % (wrc, wout))

    rc, out, err, work, cwd = run_sync(root, "model", scenario={"init_model": "claude-sonnet-5-5"}, extra=["--model", "opus"])
    chk("mismatch: an alias missing from the reported model exits 1", rc == 1 and "model mismatch" in read(work / "FAILED-001"), read(work / "FAILED-001"))
    rc, out, err, work, cwd = run_sync(root, "model-full", scenario={"init_model": "claude-sonnet-5-5"}, extra=["--model", "claude-opus-4-7"])
    chk("mismatch: a full model id that differs exits 1", rc == 1 and "model mismatch" in read(work / "FAILED-001"), read(work / "FAILED-001"))
    rc, out, err, work, cwd = run_sync(root, "model-full-ok", scenario={}, extra=["--model", "claude-opus-4-7"])
    chk("mismatch: a full model id that matches runs", rc == 0, "%s %r" % (rc, read(work / "FAILED-001")))

    # No init event means no check ran: the turn must not pass as done.
    other = "dddddddd-0000-4000-8000-000000000009"
    for i, (label, sc) in enumerate((("no init event", {"no_init": True}),
                                     ("an init event under another subtype", {"init_subtype": "session_init", "init_mode": "bypassPermissions"}))):
        for resume in (False, True):
            name = "noinit-%d-%s" % (i, "resume" if resume else "fresh")
            rc, out, err, work, cwd = run_sync(root, name, scenario=sc, extra=["--model", "sonnet"] + (["--resume", other] if resume else []))
            failed = read(work / "FAILED-001")
            res = jread(work / "result-001.json") or {}
            tag = "%s%s" % (label, ", resumed" if resume else "")
            chk("mismatch: %s fails the turn" % tag, rc == 1 and "no init event" in failed and res.get("ok") is False, "%s %r" % (rc, failed))
            chk("mismatch: %s records no session" % tag, not (work / "session.txt").exists())
            chk("mismatch: %s names a next action that does not trust the turn" % tag, "do not trust" in failed, failed)
            wrc, wout = waiter(work, turn=1)
            chk("mismatch: %s: the waiter exits 1, not 0" % tag, wrc == 1 and "state: failed" in wout, "%s %r" % (wrc, wout))
    rc, out, err, work, cwd = run_sync(root, "result-session", scenario={"result_session": "eeeeeeee-0000-4000-8000-000000000001"})
    chk("mismatch: a result event naming another session than the init event fails the turn",
        rc == 1 and "session mismatch" in read(work / "FAILED-001") and "result event" in read(work / "FAILED-001"), read(work / "FAILED-001"))
    rc, out, err, work, cwd = run_sync(root, "result-no-session", scenario={"result_no_session": True})
    chk("mismatch: a result event with no session id fails the turn",
        rc == 1 and "session mismatch" in read(work / "FAILED-001") and "None" in read(work / "FAILED-001"), "%s %r" % (rc, read(work / "FAILED-001")))

    # A malformed init field must fail the turn, not skip the check that reads it (fresh and resumed).
    for i, (label, sc) in enumerate((("a non-string model", {"init_model": 123}),
                                     ("a non-string permissionMode", {"init_mode": ["auto"]}),
                                     ("a non-string session id", {"init_session_raw": 12345}))):
        for resume in (False, True):
            name = "malformed-%d-%s" % (i, "resume" if resume else "fresh")
            rc, out, err, work, cwd = run_sync(root, name, scenario=sc, extra=["--model", "sonnet"] + (["--resume", other] if resume else []))
            failed = read(work / "FAILED-001")
            tag = "%s%s" % (label, ", resumed" if resume else "")
            chk("mismatch: init with %s fails the turn" % tag, rc == 1 and failed != "" and not (work / "session.txt").exists(), "%s %r" % (rc, failed))
            res = jread(work / "result-001.json")
            chk("mismatch: init with %s is never recorded as ok" % tag, res is None or res.get("ok") is False, repr(res)[:200])
            wrc, wout = waiter(work, turn=1)
            chk("mismatch: init with %s: the waiter exits 1" % tag, wrc == 1, "%s %r" % (wrc, wout))
            if i == 0:
                chk("mismatch: %s names the handler error" % tag, "event handler error" in failed and "AttributeError" in failed, failed)

    # The wrong session is ended at the init event, not left to run.
    proc, work, cwd = start(root, "mode-hang", scenario={"init_mode": "plan", "hang": 120})
    t0 = time.time()
    rc, out, err = finish(proc, 30)
    chk("mismatch: a wrong-mode session that would run on is ended at once", rc == 1 and time.time() - t0 < 20, "%s %.1fs" % (rc, time.time() - t0))
    chk("mismatch: and its stub and child are dead", pid_gone(mod, pid_of(cwd, "stub.pid")) and pid_gone(mod, pid_of(cwd, "child.pid")))


def g_exit(mod, root):
    rc, out, err, work, cwd = run_sync(root, "exit-code", scenario={"exit_code": 1})
    chk("exit: a nonzero exit after a result event fails the turn", rc == 1 and "exited with code 1" in read(work / "FAILED-001"), read(work / "FAILED-001"))
    res = jread(work / "result-001.json") or {}
    chk("exit: the result is kept, marked not ok", res.get("ok") is False and "exited with code 1" in res.get("failure", ""), repr(res)[:200])
    wrc, wout = waiter(work, turn=1)
    chk("exit: the waiter says failed, not done, although a result file exists", wrc == 1 and "state: failed" in wout, "%s %r" % (wrc, wout))

    rc, out, err, work, cwd = run_sync(root, "no-result", scenario={"no_result": True})
    chk("exit: no result event fails the turn", rc == 1 and "no result event" in read(work / "FAILED-001"), read(work / "FAILED-001"))
    chk("exit: and leaves no result file", not (work / "result-001.json").exists())
    failed = read(work / "FAILED-001")
    chk("exit: its next action points at stderr and the events, not at result files that do not exist",
        "stderr-001.log" in failed.split("Next action:")[-1] and "result-001.json" not in failed.split("Next action:")[-1], failed)
    wrc, wout = waiter(work, turn=1)
    chk("exit: the waiter exits 1 with a next action", wrc == 1 and "next: " in wout, wout)

    rc, out, err, work, cwd = run_sync(root, "crash", scenario={"crash_before_init": True})
    chk("exit: a crash before the init event fails the turn", rc == 1 and "exited with code 3" in read(work / "FAILED-001"), read(work / "FAILED-001"))
    chk("exit: stderr is kept", "simulated startup failure" in read(work / "stderr-001.log"), read(work / "stderr-001.log"))
    chk("exit: a crash's next action points at stderr", "stderr-001.log" in read(work / "FAILED-001").split("Next action:")[-1], read(work / "FAILED-001"))

    rc, out, err, work, cwd = run_sync(root, "error-result", scenario={"subtype": "error_max_turns", "is_error": True})
    chk("exit: a result event that is not a success fails the turn", rc == 1 and "error_max_turns" in read(work / "FAILED-001"), read(work / "FAILED-001"))
    chk("exit: its text is still readable", (work / "reply-001.txt").exists() and (jread(work / "result-001.json") or {}).get("ok") is False)

    rc, out, err, work, cwd = run_sync(root, "nobinary", claude=root / "does-not-exist.py")
    chk("exit: a missing claude exits 1 with a clear FAILED", rc == 1 and "claude not found" in read(work / "FAILED-001") and "--claude PATH" in read(work / "FAILED-001"), read(work / "FAILED-001"))


def g_args(mod, root):
    def bad(name, extra=(), prompt=b"hello\n", match=""):
        rc, out, err, work, cwd = run_sync(root, name, prompt=prompt, scenario={}, extra=extra)
        chk("args: %s exits 2" % name, rc == 2 and match in err, "%s %r" % (rc, err[-200:]))
        chk("args: %s starts nothing" % name, not list(work.glob("events-*")) and not (work / "status.json").exists())

    bad("empty-prompt", prompt=b"  \n", match="empty")
    bad("bad-effort", extra=["--effort", "turbo"], match="--effort")
    bad("bad-model", extra=["--model", "--dangerous"], match="--model")
    bad("bad-resume", extra=["--resume", "short"], match="session id")
    bad("both", extra=["--resume", "bbbbbbbb-0000", "--continue-work"], match="not allowed")
    rc, out, err, work, cwd = run_sync(root, "nofile", scenario={})
    # a prompt file that does not exist
    cmd = [PY, "-I", str(DRIVER), "run", "--work", str(work), "--cwd", str(cwd), "--prompt-file", str(root / "nope.txt"), "--claude", str(STUB)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    chk("args: a missing prompt file exits 2", r.returncode == 2 and "--prompt-file" in r.stderr, "%s %r" % (r.returncode, r.stderr))

    # A folder with a live run is busy; a second run is refused and the first is unaffected.
    proc, work, cwd = start(root, "busy", scenario={"hang": 3})
    ok = wait_for(lambda: (status(work) or {}).get("state") == "running")
    proc2, _, _ = start(root, "busy", prompt=b"again\n", keep=True)
    rc2, out2, err2 = finish(proc2, 30)
    chk("args: a second run in a busy folder exits 2 and says busy", ok and rc2 == 2 and "busy" in err2, "%s %r" % (rc2, err2))
    rc, out, err = finish(proc, 30)
    chk("args: the first run is unaffected", rc == 0 and (work / "result-001.json").exists() and not (work / "events-002.jsonl").exists(), "%s %r" % (rc, err))


def g_timeout(mod, root):
    proc, work, cwd = start(root, "timeout", scenario={"hang": 120}, extra=["--timeout", "2"])
    t0 = time.time()
    rc, out, err = finish(proc, 40)
    chk("timeout: the run exits 1", rc == 1, "%s %r" % (rc, err))
    chk("timeout: in seconds, not minutes", time.time() - t0 < 30, "%.1f" % (time.time() - t0))
    failed = read(work / "FAILED-001")
    chk("timeout: FAILED names it and the way on", "timed out after 2s" in failed and "--continue-work" in failed, failed)
    stub, child = pid_of(cwd, "stub.pid"), pid_of(cwd, "child.pid")
    chk("timeout: the stub's own pid is dead when the run exits", stub is not None and not mod.pid_alive(stub), str(stub))
    chk("timeout: and so is the child the stub started", child is not None and not mod.pid_alive(child), str(child))
    wrc, wout = waiter(work, turn=1)
    chk("timeout: the waiter exits 1 with the reason", wrc == 1 and "timed out" in wout, "%s %r" % (wrc, wout))


def g_kill(mod, root):
    # kill_tree called directly: through a whole run the Windows job object would end the stub when the run exits
    # and hide a kill_tree that does nothing; here this process stays alive.
    base = root / "kt"
    (base / "cwd").mkdir(parents=True)
    (base / "work").mkdir(parents=True)
    (base / "cwd" / "scenario.json").write_text(json.dumps({"hang": 120}), encoding="utf-8")
    args = types.SimpleNamespace(work=str(base / "work"), cwd=str(base / "cwd"), claude=str(STUB), model=None, effort=None, timeout=60)
    turn, events = mod.claim_turn(base / "work")
    r = mod.Run(args, turn, None, events)
    rec = (None, None)
    try:
        r.spawn(b"hello\n")
        up = wait_for(lambda: pid_of(base / "cwd", "child.pid") is not None)
        rec = child_record(mod, base / "cwd")
        stub, child = pid_of(base / "cwd", "stub.pid"), rec[0]
        chk("kill_tree: the stub and its child are running before the kill", up and r.proc.poll() is None and mod.pid_alive(stub) and mod.pid_alive(child))
        r.kill_tree()
        chk("kill_tree: the process it started is dead when it returns", r.proc.poll() is not None)
        chk("kill_tree: the stub's own pid is dead", pid_gone(mod, stub, 5), str(stub))
        chk("kill_tree: and so is the child it started", pid_gone(mod, child, 5), str(child))
    finally:
        if r.proc and r.proc.poll() is None:  # the stub this test started
            r.proc.kill()
            r.proc.wait()
        reap_child(mod, rec)
        r.events.close()
        r.logf.close()

    # A normal exit leaves no child behind either: the group (POSIX) or the job (Windows) is ended after the exit.
    rc, out, err, work, cwd = run_sync(root, "orphan", scenario={"orphan": True})
    rec = child_record(mod, cwd)
    chk("orphan: the turn finished although the stub left a child running", rc == 0 and rec[0] is not None, "%s %r" % (rc, err))
    chk("orphan: the child the stub left is dead when the run exits", pid_gone(mod, rec[0], 10), str(rec[0]))
    reap_child(mod, rec)

    # A hard-killed run takes the stub down with it (Windows job object; elsewhere the stub dies on its closed stdout).
    proc, work, cwd = start(root, "hardkill", scenario={"hang": 120})
    wait_for(lambda: pid_of(cwd, "child.pid") is not None)
    rec = child_record(mod, cwd)
    stub, child = pid_of(cwd, "stub.pid"), rec[0]
    proc.kill()
    proc.wait()
    chk("hard kill: the stub does not outlive its run", pid_gone(mod, stub, 10), str(stub))
    if os.name == "nt":
        chk("hard kill: nor does the stub's child (Windows job object)", pid_gone(mod, child, 10), str(child))
    reap_child(mod, rec)  # POSIX gap: the child of a hard-killed run is left; end the one the stub started

    # SIGBREAK / SIGTERM: a second and third signal during the cleanup must not interrupt it.
    proc, work, cwd = start(root, "signal", scenario={"hang": 120}, newgroup=True)
    wait_for(lambda: pid_of(cwd, "child.pid") is not None)
    stub, child = pid_of(cwd, "stub.pid"), pid_of(cwd, "child.pid")
    for _ in range(3):
        if os.name == "nt":
            proc.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            proc.terminate()
        time.sleep(0.05)
    rc, out, err = finish(proc, 30)
    chk("signal: the run exits 1", rc == 1, "%s %r" % (rc, err))
    chk("signal: FAILED names the signal", "signal" in read(work / "FAILED-001"), read(work / "FAILED-001"))
    chk("signal: the stub and its child are gone", pid_gone(mod, stub) and pid_gone(mod, child))


def g_waiter(mod, root):
    # A run that dies hard leaves status "running" with a dead pid.
    proc, work, cwd = start(root, "dead", scenario={"hang": 120})
    wait_for(lambda: pid_of(cwd, "child.pid") is not None)
    stub, rec = pid_of(cwd, "stub.pid"), child_record(mod, cwd)
    proc.kill()
    proc.wait()
    rc, out = waiter(work, timeout=15, turn=1)
    chk("waiter: a dead run exits 3 and says so", rc == 3 and "run dead" in out and "next: " in out, "%s %r" % (rc, out))
    pid_gone(mod, stub, 10)
    reap_child(mod, rec)

    proc, work, cwd = start(root, "wtimeout", scenario={"hang": 4})
    wait_for(lambda: (status(work) or {}).get("state") == "running")
    rc, out = waiter(work, timeout=1, turn=1)
    chk("waiter: a timeout exits 2 and says wait again", rc == 2 and "state: timeout" in out and "wait again" in out, "%s %r" % (rc, out))
    rc, out = waiter(work, timeout=30)
    chk("waiter: without --turn it reads the turn in status.json and finishes with the run", rc == 0 and "turn: 1" in out, "%s %r" % (rc, out))
    finish(proc, 30)

    rc, out = waiter(root / "no-such-folder", timeout=1)
    chk("waiter: no work folder exits 5", rc == 5, "%s %r" % (rc, out))
    empty = root / "empty"
    empty.mkdir()
    rc, out = waiter(empty, timeout=10, extra=["--status-grace", "1"])
    chk("waiter: no status.json within the grace means the run never started (exit 3)", rc == 3 and "never started" in out, "%s %r" % (rc, out))

    solo = root / "solo"
    solo.mkdir()
    me = os.getpid()
    (solo / "status.json").write_text(json.dumps({"state": "running", "pid": me, "pid_start": 12345, "turn": 1}), encoding="utf-8")
    if mod.proc_start(me) is not None:
        rc, out = waiter(solo, timeout=5, turn=1)
        chk("waiter: a live pid with another creation time is a reused pid (exit 3)", rc == 3 and "run dead" in out, "%s %r" % (rc, out))
    (solo / "status.json").write_text(json.dumps({"state": "done", "pid": me, "pid_start": None, "turn": 3}), encoding="utf-8")
    rc, out = waiter(solo, timeout=5, turn=2)
    chk("waiter: a folder already past the turn, with no result for it, exits 3", rc == 3 and "already at turn 3" in out, "%s %r" % (rc, out))
    (solo / "status.json").write_text(json.dumps({"state": "done", "pid": me, "pid_start": None, "turn": 1}), encoding="utf-8")
    rc, out = waiter(solo, timeout=10, turn=2, extra=["--status-grace", "1"])
    chk("waiter: a follow-up turn that never began exits 3, not a timeout", rc == 3 and "never reached turn 2" in out, "%s %r" % (rc, out))


def g_secret(mod, root):
    rc, out, err, work, cwd = run_sync(root, "secret", scenario={"leak": True}, env={"ANTHROPIC_API_KEY": API_KEY})
    chk("secret: the turn finished", rc == 0, "%s %r" % (rc, err))
    leaked = [str(p) for p in tree_files(work, cwd) if API_KEY in read(p) or LEAK in read(p)]
    chk("secret: the API key and the sk-ant string are in no file of the work or cwd folder", not leaked, repr(leaked))
    chk("secret: nor in what the run printed", API_KEY not in out + err and LEAK not in out + err)
    chk("secret: stderr was captured and redacted", "stderr leak" in read(work / "stderr-001.log") and "[redacted]" in read(work / "stderr-001.log"), read(work / "stderr-001.log"))
    chk("secret: the run log recorded the init line, redacted", "init: model=" in read(work / "run-001.log") and "leak-[redacted]" in read(work / "run-001.log"), read(work / "run-001.log")[:400])
    chk("secret: result-001.json carries the redacted api_key_source", "leak-[redacted]" in read(work / "result-001.json"))
    lines = read(work / "events-001.jsonl").splitlines()
    valid = True
    for l in lines:
        try:
            json.loads(l)
        except ValueError:
            valid = False
    chk("secret: the redacted event lines are still valid JSON", valid and any("[redacted]" in l for l in lines), repr(lines[-3:]))
    chk("secret: the reply shows the redaction", "[redacted]" in read(work / "reply-001.txt") and "[redacted]" in read(work / "result-001.json"))
    wrc, wout = waiter(work, turn=1)
    chk("secret: the waiter prints neither", wrc == 0 and API_KEY not in wout and LEAK not in wout, wout)


# ---------------------------------------------------------------- mutants

MUTANTS = (
    ("mode-assertion-removed", '        if mode != REQUIRED_MODE:\n', '        if False:\n', "mismatch"),
    ("redaction-removed", '        for sec in sorted(self.secrets, key=len, reverse=True):\n', '        for sec in []:\n', "secret"),
    ("resume-dropped", '            cmd += ["--resume", self.resume_id]\n', '            pass\n', "resume"),
    ("missing-result-is-success", '        if ev is None:\n            failure =', '        if False:\n            failure =', "exit"),
    ("kill-tree-does-nothing", '        p = self.proc\n        if p is None:\n            return\n        if os.name == "nt":\n',
     '        return\n        p = self.proc\n        if p is None:\n            return\n        if os.name == "nt":\n', "kill"),
    ("init-required-removed", '        elif self.init is None:', '        elif False:', "mismatch"),
    ("result-session-check-removed", 'elif not isinstance(ev.get("session_id"), str) or ev["session_id"] != self.session_id:',
     'elif False:', "mismatch"),
    ("result-session-optional", 'elif not isinstance(ev.get("session_id"), str) or ev["session_id"] != self.session_id:',
     'elif isinstance(ev.get("session_id"), str) and ev["session_id"] != self.session_id:', "mismatch"),
    # A handler exception must fail the turn. The init_checked guard in finish() is a second line of defence, so the
    # mutant removes both: with only one removed the other still fails the turn.
    ("handler-error-passes",
     ('self.fail_reason = self.fail_reason or "event handler error: %s: %s" % (type(exc).__name__, exc)', 'elif not self.init_checked:'),
     ('pass', 'elif False:'), "mismatch"),
    ("later-claimant-status-not-ignored", 'and st["turn"] > ignore_above:', 'and False:', "units"),
    ("stderr-redaction-removed", 'f.write(self.red.text(line.decode("utf-8", "replace")))', 'f.write(line.decode("utf-8", "replace"))', "secret"),
    ("log-redaction-removed", 'time.strftime("%H:%M:%S ") + self.red.text(msg)', 'time.strftime("%H:%M:%S ") + msg', "secret"),
    ("result-redaction-removed", '        doc = self.red.obj(doc)\n', '        pass\n', "secret"),
    ("turn-usage-not-subtracted", 'return round(total - before, 6) if total >= before else total', 'return total', "resume"),
    ("turn-claim-not-exclusive", '"x", encoding="utf-8", newline="\\n")\n        except FileExistsError:', '"a", encoding="utf-8", newline="\\n")\n        except FileExistsError:', "units"),
    ("busy-check-removed", 'if st and st.get("state") not in TERMINAL_STATES and pid_alive', 'if False and pid_alive', "args"),
    ("is-error-check-removed", 'elif ev.get("is_error") or ev.get("subtype") != "success":', 'elif False:', "exit"),
    ("model-check-removed", 'elif self.a.model and not model_matches(self.a.model, model):', 'elif False:', "mismatch"),
    ("rc-check-removed", '        elif rc != 0:\n', '        elif False:\n', "exit"),
    ("waiter-pid-check-removed", 'and not pid_alive(st.get("pid"), st.get("pid_start")):', 'and False:', "waiter"),
)


def run_mutants(root):
    src = DRIVER.read_text(encoding="utf-8")
    for name, old, new, group in MUTANTS:
        olds, news = (old, new) if isinstance(old, tuple) else ((old,), (new,))
        if any(src.count(o) != 1 for o in olds):
            chk("mutant %s: the mutation applies to exactly one place" % name, False, "found %s" % [src.count(o) for o in olds])
            continue
        mutated = src
        for o, n in zip(olds, news):
            mutated = mutated.replace(o, n)
        folder = root / ("mutant-" + name)
        folder.mkdir()
        copy = folder / "claude-delegate.py"
        copy.write_text(mutated, encoding="utf-8")
        r = subprocess.run([PY, "-I", str(Path(__file__).resolve()), "--driver", str(copy), "--groups", group],
                           capture_output=True, text=True, timeout=300)
        caught = r.returncode == 1 and "FAIL:" in r.stdout
        chk("mutant %s is caught by group %s" % (name, group), caught, "exit %s %s" % (r.returncode, r.stdout[-300:]))


# ---------------------------------------------------------------- main

def main(argv):
    global DRIVER
    ap = argparse.ArgumentParser()
    ap.add_argument("--driver")
    ap.add_argument("--groups")
    ap.add_argument("--mutants", action="store_true")
    a = ap.parse_args(argv)
    if a.driver:
        DRIVER = Path(a.driver).resolve()
    groups = a.groups.split(",") if a.groups else list(GROUPS)
    mod = load_module()
    root = Path(tempfile.mkdtemp(prefix="qclaude-selftest-"))
    try:
        for g in groups:
            if g not in GROUPS:
                FAILS.append("unknown group %r" % g)
                continue
            globals()["g_" + g](mod, root)
        if not a.groups or a.mutants:
            run_mutants(root)
    except Exception as exc:  # a harness bug is a failure, not a crash
        FAILS.append("selftest harness raised %s: %s" % (type(exc).__name__, exc))
    finally:
        for proc in LIVE:
            if proc.poll() is None:  # unreaped, so its pid cannot have been reused: a run we started. Its job
                proc.kill()          # object (Windows) or closed stdout (POSIX) takes the stub down with it.
                proc.wait()
        shutil.rmtree(root, ignore_errors=True)
    for f in FAILS:
        print("FAIL: %s" % f)
    print("qclaude-delegate selftest: %d checks, %d failed" % (CHECKS[0], len(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
