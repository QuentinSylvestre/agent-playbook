"""Selftest for acp-driver.py against fake-kiro.py. No network, no real kiro-cli, about 30 seconds.

Run: <python> -I shared/skills/qkiro-delegate/scripts/selftest.py
Prints `FAIL: <check>` lines, then `qkiro-delegate selftest: N checks, M failed`. Exit 0 only when none failed.
Each scenario runs a real driver process against the stub in its own temp directory. Every process it starts
(driver, and the stub when a driver was killed) is ended before it returns.
"""
import importlib.util
import io
import threading
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
DRIVER = HERE / "acp-driver.py"
STUB = HERE / "fake-kiro.py"
PY = sys.executable
FAILS, CHECKS = [], [0]
LIVE = []  # (Popen, work) of every driver started


def chk(name, cond, detail=""):
    CHECKS[0] += 1
    if not cond:
        FAILS.append("%s%s" % (name, (": " + detail) if detail else ""))


def load_driver_module():
    spec = importlib.util.spec_from_file_location("acp_driver", str(DRIVER))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def start(root, name, scenario=None, policy=None, extra=(), kiro=None, wait_ready=True, newgroup=False, queued=None):
    work, cwd = root / name / "work", root / name / "cwd"
    work.mkdir(parents=True)
    cwd.mkdir(parents=True)
    if scenario is not None:
        (cwd / "scenario.json").write_text(json.dumps(scenario), encoding="utf-8")
    if policy is not None:
        (work / "policy.json").write_text(policy if isinstance(policy, str) else json.dumps(policy), encoding="utf-8")
    if queued is not None:
        (work / "in").mkdir()
        send(work, 1, queued)
    cmd = [PY, "-I", str(DRIVER), "run", "--work", str(work), "--cwd", str(cwd), "--kiro", str(kiro or STUB),
           "--stop-grace", "1", "--cancel-grace", "1", *extra]
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if newgroup and os.name == "nt" else 0
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=flags)
    LIVE.append((proc, work))
    if wait_ready:
        end = time.time() + 20
        while time.time() < end and proc.poll() is None:
            st = status(work)
            if st and st.get("state") == "ready":
                break
            time.sleep(0.1)
    return proc, work, cwd


def status(work):
    try:
        return json.loads((work / "status.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def send(work, n, text):
    tmp = work / "in" / ("%03d.tmp" % n)
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, work / "in" / ("%03d.txt" % n))


def waiter(work, timeout=15, turn=None, extra=()):
    cmd = [PY, "-I", str(DRIVER), "wait", "--work", str(work), "--timeout", str(timeout), "--poll", "0.1", *extra]
    if turn is not None:
        cmd += ["--turn", str(turn)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 30)
    return r.returncode, r.stdout


def finish(proc, work, stop=True):
    if stop and proc.poll() is None:
        (work / "in" / "stop").write_text("", encoding="utf-8")
    try:
        proc.wait(20)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    return proc.returncode


def read(path):
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return ""


def stub_pid_of(cwd):
    """The stub's own pid, written by the stub. status.json's kiro_pid is the Popen pid, which under a venv is a launcher."""
    try:
        return int((Path(cwd) / "stub.pid").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def state_is(work, state, secs=15):
    end = time.time() + secs
    while time.time() < end:
        if (status(work) or {}).get("state") == state:
            return True
        time.sleep(0.05)
    return False


def pid_gone(mod, pid, secs=10):
    end = time.time() + secs
    while time.time() < end:
        if not mod.pid_alive(pid):
            return True
        time.sleep(0.1)
    return False


def scenarios(root, mod):
    # 1. Handshake, a turn, stop.
    proc, work, cwd = start(root, "ok")
    chk("handshake: reaches ready", (status(work) or {}).get("state") == "ready", repr(status(work)))
    chk("handshake: omitted model and effort retain and record session defaults",
        (status(work) or {}).get("model") == "claude-sonnet-4.6" and (status(work) or {}).get("effort") == "high", repr(status(work)))
    chk("handshake: session id written", read(work / "session.txt") == "sess_fake-0001", read(work / "session.txt"))
    send(work, 1, "SAY hello from the delegate")
    rc, out = waiter(work)
    chk("turn: waiter exit 0", rc == 0, "%s %r" % (rc, out))
    chk("turn: waiter prints reply path and stop reason", "reply: " in out and "stop_reason: end_turn" in out, out)
    reply = read(work / "out" / "001.txt")
    chk("turn: reply text streamed", "hello from the delegate" in reply and "[end of turn: end_turn]" in reply, reply)
    chk("turn: status says turn 1 done", (status(work) or {}).get("state") == "turn 1 done", repr(status(work)))
    chk("turn: stop ends the driver with 0", finish(proc, work) == 0)
    chk("turn: final status stopped", (status(work) or {}).get("state") == "stopped", repr(status(work)))
    chk("turn: no FAILED file", not (work / "FAILED").exists())
    chk("turn: stub gone after stop", pid_gone(mod, stub_pid_of(cwd)))
    rc, out = waiter(work, timeout=2, turn=2)
    chk("waiter: a stopped run before the turn exists exits 4", rc == 4, "%s %r" % (rc, out))

    # 2. Mode and model read-back.
    proc, work, cwd = start(root, "mode", scenario={"mode_reply": "vibe"}, wait_ready=False)
    rc = finish(proc, work, stop=False)
    chk("mode mismatch: driver exits 1", rc == 1, str(rc))
    chk("mode mismatch: FAILED names the mode", "mode mismatch" in read(work / "FAILED") and "vibe" in read(work / "FAILED"), read(work / "FAILED"))
    chk("mode mismatch: events.log records it", "mode mismatch" in read(work / "events.log"))
    chk("mode mismatch: stub gone", pid_gone(mod, stub_pid_of(cwd)))
    chk("mode mismatch: status failed", (status(work) or {}).get("state") == "failed")
    rc, out = waiter(work, turn=1, timeout=2)
    chk("mode mismatch: waiter reports exit 1 with the reason", rc == 1 and "mode mismatch" in out, "%s %r" % (rc, out))
    chk("mode mismatch: FAILED and the waiter both name a next action", "Next action:" in read(work / "FAILED") and "next: " in out, out)

    proc, work, cwd = start(root, "model", scenario={"model_set_reply": "claude-sonnet-4.6"},
                            extra=["--model", "claude-opus-4.5"], wait_ready=False)
    chk("model mismatch: driver exits 1", finish(proc, work, stop=False) == 1)
    chk("model mismatch: FAILED names the model", "model" in read(work / "FAILED") and any(s in read(work / "FAILED") for s in ("mismatch", "drift")), read(work / "FAILED"))
    proc, work, cwd = start(root, "model-ok", extra=["--model", "claude-opus-4.5"])
    chk("model match: ready", (status(work) or {}).get("state") == "ready", repr(status(work)))
    chk("model selection uses ACP, not an unsupported launch flag", "session/set_config_option model=claude-opus-4.5" in read(cwd / "wire.log")
        and (status(work) or {}).get("model") == "claude-opus-4.5", read(cwd / "wire.log"))
    finish(proc, work)

    proc, work, cwd = start(root, "model-effort", extra=["--model", "claude-opus-4.5", "--effort", "max"], queued="SAY selected")
    rc, out = waiter(work)
    log = read(cwd / "wire.log")
    chk("model and effort are confirmed before a queued prompt", rc == 0 and
        0 <= log.find("session/set_config_option model=") < log.find("session/set_config_option effortLevel=max") < log.find("session/prompt"), log)
    chk("literal max is selected and recorded", (status(work) or {}).get("effort") == "max", repr(status(work)))
    chk("advertised effort choices are recorded", 'choices=["low", "medium", "high", "max"]' in read(work / "events.log"), read(work / "events.log"))
    finish(proc, work)

    for key, target, flag in (("model", "claude-opus-4.5", "--model"), ("effortLevel", "max", "--effort")):
        proc, work, cwd = start(root, "pending-old-" + key, scenario={"set_old_snapshot": key},
                                extra=[flag, target], queued="SAY selected after old snapshot")
        rc, out = waiter(work)
        chk("wire pending %s: old-current unrelated snapshot still reaches a confirmed prompt" % key,
            rc == 0 and "selected after old snapshot" in read(work / "out/001.txt")
            and read(cwd / "wire.log").count("session/prompt") == 1, out + read(work / "FAILED"))
        finish(proc, work)

    proc, work, cwd = start(root, "config-already-selected", extra=["--model", "claude-sonnet-4.6", "--effort", "high"])
    chk("values already selected are confirmed without setters", (status(work) or {}).get("state") == "ready"
        and "session/set_config_option" not in read(cwd / "wire.log"), read(cwd / "wire.log"))
    finish(proc, work)

    failures = [
        ("model-unsupported", {}, ["--model", "no-such-model"], "unsupported model"),
        ("effort-unsupported", {"effort_choices": ["low", "medium", "high"]}, ["--effort", "max"], "unsupported effortLevel"),
        ("effort-missing", {"omit_options": ["effortLevel"]}, ["--effort", "max"], "unsupported effortLevel"),
        ("model-missing", {"omit_options": ["model"]}, ["--model", "claude-sonnet-4.6"], "unsupported model"),
        ("effort-wrong", {"effort_set_reply": "high"}, ["--effort", "max"], "effort mismatch"),
        ("effort-error", {"set_error": "effortLevel"}, ["--effort", "max"], "effortLevel failed"),
        ("model-error", {"set_error": "model"}, ["--model", "claude-opus-4.5"], "model failed"),
        ("effort-unconfirmed", {"set_missing_readback": "effortLevel"}, ["--effort", "max"], "effort drift"),
        ("model-unconfirmed", {"set_missing_readback": "model"}, ["--model", "claude-opus-4.5"], "model drift"),
        ("effort-no-snapshot", {"set_no_options": "effortLevel"}, ["--effort", "max"], "effort mismatch"),
        ("model-no-snapshot", {"set_no_options": "model"}, ["--model", "claude-opus-4.5"], "model mismatch"),
        ("new-model-removes-effort", {"effort_reply": "max", "model_omit_options": ["effortLevel"]},
         ["--model", "claude-opus-4.5", "--effort", "max"], "unsupported effortLevel"),
        ("selection-drift", {"set_drift_before_reply": "effortLevel"}, ["--effort", "max"], "effort drift"),
        ("new-model-effort-choices", {"model_effort_choices": ["low", "high"]},
         ["--model", "claude-opus-4.5", "--effort", "max"], "unsupported effortLevel"),
    ]
    for name, scenario, extra, reason in failures:
        proc, work, cwd = start(root, name, scenario=scenario, extra=extra, wait_ready=False, queued="SAY must not run")
        chk(name + ": fails with the config reason", finish(proc, work, stop=False) == 1 and reason in read(work / "FAILED"), read(work / "FAILED"))
        chk(name + ": queued prompt never reaches the server", "session/prompt" not in read(cwd / "wire.log")
            and not (work / "out" / "001.done").exists(), read(cwd / "wire.log"))

    for name, directive in (("model", "DRIFT_MODEL claude-sonnet-4.6"), ("effort", "DRIFT_EFFORT high")):
        proc, work, cwd = start(root, name + "-drift", extra=["--model", "claude-opus-4.5", "--effort", "max"])
        send(work, 1, directive)
        send(work, 2, "SAY must not run")
        rc, out = waiter(work, turn=2)
        chk(name + " drift fails the turn and blocks the next queued prompt", rc == 1 and name + " drift" in read(work / "FAILED")
            and read(cwd / "wire.log").count("session/prompt") == 1 and not (work / "out" / "001.done").exists(), read(work / "FAILED"))
        finish(proc, work, stop=False)
    proc, work, cwd = start(root, "mode-custom", extra=["--mode", "custom_agent"])
    chk("a requested non-default mode is bound and read back", (status(work) or {}).get("state") == "ready")
    finish(proc, work)
    proc, work, cwd = start(root, "nokiro", kiro=root / "does-not-exist.py", wait_ready=False)
    chk("missing kiro: exits 1 with a clear FAILED", finish(proc, work, stop=False) == 1 and "kiro-cli not found" in read(work / "FAILED"), read(work / "FAILED"))
    proc, work, cwd = start(root, "agent-exit", scenario={"exit_after_session_new": True})
    time.sleep(0.5)
    chk("agent exit after the handshake: FAILED", finish(proc, work, stop=False) == 1 and "exited" in read(work / "FAILED"), read(work / "FAILED"))

    # 3. Permission policy over the wire.
    allow_git = {"default": "reject", "allow": [{"capability": "shell", "command_prefix": "git status"}]}
    proc, work, cwd = start(root, "perm-allow", policy=allow_git)
    send(work, 1, 'PERM shell execute Running: git status | {"command": "git status"}')
    rc, out = waiter(work)
    chk("policy allow: turn done", rc == 0, "%s %r" % (rc, out))
    chk("policy allow: tool ran", "ALLOWED: Running: git status" in read(work / "out" / "001.txt"), read(work / "out" / "001.txt"))
    chk("policy allow: decision logged", "PERMISSION ALLOW (allow[0])" in read(work / "events.log"), read(work / "events.log"))
    send(work, 2, 'PERM shell execute Running: git status && rm -rf x | {"command": "git status && rm -rf x"}')
    rc, out = waiter(work)
    chk("compound command is not allowed by a prefix rule", "REFUSED: Running: git status && rm -rf x" in read(work / "out" / "002.txt"), read(work / "out" / "002.txt"))
    chk("compound command: refusal appended to the out file", "[permission REFUSED" in read(work / "out" / "002.txt"))
    chk("refusal counted in status and waiter output", (status(work) or {}).get("refusals") == 1 and "refusals: 1" in out, out)
    finish(proc, work)

    proc, work, cwd = start(root, "perm-nopolicy")
    send(work, 1, 'PERM shell execute Running: git status | {"command": "git status"}')
    rc, out = waiter(work)
    reply = read(work / "out" / "001.txt")
    chk("no policy: all tools trusted, request allowed", rc == 0 and "ALLOWED: Running: git status" in reply and "REFUSED" not in reply, reply)
    chk("no policy: logged as ALLOW with the default", "PERMISSION ALLOW (default: all tools trusted" in read(work / "events.log"), read(work / "events.log"))
    finish(proc, work)

    proc, work, cwd = start(root, "perm-default-allow", policy={"deny": [{"capability": "shell", "command_contains": "push"}]})
    send(work, 1, 'PERM shell execute Running: git log | {"command": "git log"}')
    waiter(work)
    chk("deny-only policy: an unnamed tool is allowed by the default", "ALLOWED: Running: git log" in read(work / "out" / "001.txt"), read(work / "out" / "001.txt"))
    send(work, 2, 'PERM shell execute Running: git push | {"command": "git push"}')
    waiter(work)
    chk("deny-only policy: the denied tool is refused", "REFUSED: Running: git push" in read(work / "out" / "002.txt"), read(work / "out" / "002.txt"))
    finish(proc, work)

    proc, work, cwd = start(root, "perm-badpolicy", policy="{not json")
    send(work, 1, 'PERM shell execute Running: git status | {"command": "git status"}')
    waiter(work)
    chk("unreadable policy: rejects", "REFUSED" in read(work / "out" / "001.txt") and "not valid JSON" in read(work / "out" / "001.txt"), read(work / "out" / "001.txt"))
    finish(proc, work)

    deny_wins = {"allow": [{"capability": "shell", "command_prefix": "git"}],
                 "deny": [{"capability": "shell", "command_contains": "push"}]}
    proc, work, cwd = start(root, "perm-deny", policy=deny_wins)
    send(work, 1, 'PERM shell execute Running: git push origin main | {"command": "git push origin main"}')
    waiter(work)
    reply = read(work / "out" / "001.txt")
    chk("deny beats allow", "REFUSED: Running: git push origin main" in reply and "deny[0]" in reply, reply)
    send(work, 2, 'PERM shell execute Running: git log | {"command": "git log"}')
    waiter(work)
    chk("the same policy still allows what the deny does not name", "ALLOWED: Running: git log" in read(work / "out" / "002.txt"), read(work / "out" / "002.txt"))
    finish(proc, work)

    # 4. Timeouts and a dead driver.
    proc, work, cwd = start(root, "turn-timeout", scenario={"ignore_eof": True}, extra=["--turn-timeout", "2"])
    stub_pid = stub_pid_of(cwd)
    send(work, 1, "SLEEP 60")
    t0 = time.time()
    rc, out = waiter(work, timeout=20)
    chk("turn timeout: waiter exit 1 with the reason", rc == 1 and "timed out after 2s" in out, "%s %r" % (rc, out))
    chk("turn timeout: prompt in seconds, not minutes", time.time() - t0 < 15, str(time.time() - t0))
    chk("turn timeout: driver exits 1", finish(proc, work, stop=False) == 1)
    chk("turn timeout: out file notes it", "timed out" in read(work / "out" / "001.txt"), read(work / "out" / "001.txt"))
    chk("turn timeout: a stub that ignores stdin EOF is already dead when the driver exits", stub_pid and not mod.pid_alive(stub_pid), str(stub_pid))
    chk("turn timeout: no .done written", not (work / "out" / "001.done").exists())

    # A stub that ignores EOF is gone by the time status says stopped: the stop path kills the tree after the grace.
    proc, work, cwd = start(root, "stop-kill", scenario={"ignore_eof": True})
    stub_pid = stub_pid_of(cwd)
    (work / "in" / "stop").write_text("", encoding="utf-8")
    chk("stop: status reaches stopped", state_is(work, "stopped"), repr(status(work)))
    chk("stop: the stub that ignores EOF is dead the moment status says stopped", stub_pid and not mod.pid_alive(stub_pid), str(stub_pid))
    chk("stop: the driver exits 0", finish(proc, work, stop=False) == 0)

    # A turn that ignores session/cancel: the grace ends it and the reason says so.
    proc, work, cwd = start(root, "cancel-grace")
    send(work, 1, "STUBBORN 30")
    time.sleep(1.0)
    (work / "in" / "stop").write_text("", encoding="utf-8")
    chk("cancel grace: driver exits 1", finish(proc, work, stop=False) == 1)
    chk("cancel grace: the reason names the stop request, not the turn timeout",
        "did not end within 1s of the stop request" in read(work / "FAILED") and "timed out" not in read(work / "FAILED"), read(work / "FAILED"))

    # A JSON-RPC error reply to a prompt fails the run instead of looking like a finished turn.
    proc, work, cwd = start(root, "turn-error", scenario={"long_token": True})
    send(work, 1, "ECHO_ERROR")
    rc, out = waiter(work)
    chk("turn error: waiter exits 1, not 0", rc == 1 and "error reply" in out, "%s %r" % (rc, out))
    chk("turn error: no .done written", not (work / "out" / "001.done").exists())
    chk("turn error: the out file records it", "errored" in read(work / "out" / "001.txt"), read(work / "out" / "001.txt"))
    finish(proc, work, stop=False)
    leaks = [str(p) for p in (root / "turn-error").rglob("*") if p.is_file() and "LONGTOK-abcdefgh" in read(p)]
    chk("turn error: the token inside the error payload reaches no file", not leaks, repr(leaks))

    # The mode is checked again after the handshake.
    proc, work, cwd = start(root, "drift")
    log = read(work / "events.log")
    chk("session/new logs its option ids and values", 'options=mode="kiro_default" model="claude-sonnet-4.6"' in log, log[:600])
    send(work, 1, "DRIFT_MODE vibe")
    rc, out = waiter(work)
    chk("mode drift with no sleep: the reply arriving with the update still fails the run", rc == 1 and "mode drift" in out, "%s %r" % (rc, out))
    chk("mode drift with no sleep: the turn is not reported done", not (work / "out" / "001.done").exists())
    chk("mode drift: the update's keys and option values are logged", 'update config_option_update keys=configOptions,sessionUpdate options=mode="vibe"' in read(work / "events.log"), read(work / "events.log")[-400:])
    finish(proc, work, stop=False)

    # Drift that arrives after the turn ended, with the driver idle (between turns, or after the last one).
    proc, work, cwd = start(root, "drift-idle")
    send(work, 1, "DRIFT_LATER vibe 1.5")
    rc, out = waiter(work)
    chk("idle drift: the turn itself finishes cleanly", rc == 0, "%s %r" % (rc, out))
    chk("idle drift: the run then fails by itself, before any stop", state_is(work, "failed", 10) and "mode drift" in read(work / "FAILED"), repr(status(work)))
    chk("idle drift: the driver exits 1, not stopped", finish(proc, work, stop=False) == 1 and (status(work) or {}).get("state") == "failed")
    rc, out = waiter(work, turn=2, timeout=2)
    chk("idle drift: a waiter for the next turn reports the failure", rc == 1 and "mode drift" in out, "%s %r" % (rc, out))
    rc, out = waiter(work, turn=1, timeout=2)
    chk("idle drift: the earlier valid completed turn remains successful", rc == 0, "%s %r" % (rc, out))

    # Prompts run in stem order; a later settled prompt does not overtake an earlier unsettled one.
    proc, work, cwd = start(root, "order")
    (work / "in" / "001.txt").write_text("SAY first", encoding="utf-8")
    (work / "in" / "002.txt").write_text("SAY second", encoding="utf-8")
    old = time.time() - 30
    os.utime(work / "in" / "002.txt", (old, old))
    rc, out = waiter(work, turn=2)
    log = read(work / "events.log")
    chk("prompt order: 001 runs before 002 although 002 settled first", rc == 0 and 0 <= log.find("PROMPT 001") < log.find("PROMPT 002"), log[-500:])
    finish(proc, work)

    # A prompt file dated in the future would never settle: it runs, with a warning.
    proc, work, cwd = start(root, "future")
    (work / "in" / "001.txt").write_text("SAY from the future", encoding="utf-8")
    soon = time.time() + 3600
    os.utime(work / "in" / "001.txt", (soon, soon))
    rc, out = waiter(work, timeout=15)
    chk("future mtime: the prompt runs", rc == 0 and "from the future" in read(work / "out" / "001.txt"), "%s %r" % (rc, out))
    chk("future mtime: the log warns", "modification time in the future" in read(work / "events.log"), read(work / "events.log")[-300:])
    finish(proc, work)

    # Drift that lands while kiro-cli is shutting down, inside the stop grace, still fails the run.
    proc, work, cwd = start(root, "drift-grace", scenario={"ignore_eof": True}, extra=["--stop-grace", "5"])
    send(work, 1, "DRIFT_LATER vibe 2.5")
    rc, out = waiter(work)
    (work / "in" / "stop").write_text("", encoding="utf-8")
    chk("drift in the stop grace: the turn itself finished", rc == 0, "%s %r" % (rc, out))
    chk("drift in the stop grace: the run ends FAILED, not stopped", finish(proc, work, stop=False) == 1
        and (status(work) or {}).get("state") == "failed" and "mode drift" in read(work / "FAILED"), repr(status(work)))
    log = read(work / "events.log")
    chk("drift in the stop grace: the drift landed after the stop began, not in the idle loop",
        0 <= log.find("driver stopping") < log.find("FAILED: mode drift"), log[-500:])

    # Prompt files: exactly three digits, and not before they settle.
    proc, work, cwd = start(root, "stems")
    (work / "in" / "7.txt").write_text("SAY seven", encoding="utf-8")
    (work / "in" / "0001.txt").write_text("SAY four digits", encoding="utf-8")
    time.sleep(1.5)
    chk("prompt files whose stem is not three digits are ignored", not list((work / "out").glob("*")), repr(list((work / "out").glob("*"))))
    rc, out = waiter(work, timeout=1)
    chk("waiter: only three-digit stems count as prompts", rc == 5, "%s %r" % (rc, out))
    finish(proc, work)
    f = root / "settle.txt"
    f.write_text("x", encoding="utf-8")
    chk("a file modified a moment ago is not settled", not mod.settled(f))
    time.sleep(0.7)
    chk("a file untouched for 0.5 s is settled", mod.settled(f))

    proc, work, cwd = start(root, "total-timeout", extra=["--total-timeout", "3"])
    chk("overall timeout: driver exits 1", finish(proc, work, stop=False) == 1)
    chk("overall timeout: FAILED names it", "overall timeout" in read(work / "FAILED"), read(work / "FAILED"))

    proc, work, cwd = start(root, "dead")
    send(work, 1, "SLEEP 60")
    time.sleep(1.0)
    stub_pid = stub_pid_of(cwd)
    proc.kill()
    proc.wait()
    rc, out = waiter(work, timeout=15)
    chk("dead driver: waiter exits 3 and says so", rc == 3 and "driver dead" in out, "%s %r" % (rc, out))
    chk("dead driver: the stub follows its closed stdin", pid_gone(mod, stub_pid), str(stub_pid))

    proc, work, cwd = start(root, "waiter-timeout")
    send(work, 1, "SLEEP 60")
    rc, out = waiter(work, timeout=1)
    chk("waiter: timeout exits 2", rc == 2 and "state: timeout" in out, "%s %r" % (rc, out))
    (work / "in" / "stop").write_text("", encoding="utf-8")
    chk("stop during a turn cancels it and ends the driver", finish(proc, work, stop=False) == 0 and
        "[end of turn: cancelled]" in read(work / "out" / "001.txt"), read(work / "out" / "001.txt"))
    rc, out = waiter(root / "ok" / "work", turn=None, timeout=1)
    chk("waiter: a finished turn is reported even after the run stopped", rc == 0, "%s %r" % (rc, out))
    empty = root / "empty"
    (empty / "in").mkdir(parents=True)
    chk("waiter: no prompt file exits 5", waiter(empty, timeout=1)[0] == 5)

    # 5. No secret reaches a file.
    proc, work, cwd = start(root, "secret", policy={"allow": [{"capability": "shell", "command_prefix": "echo"}]})
    send(work, 1, "ECHO_TOKEN\nECHO_ARN\nSAY done")
    rc, out = waiter(work)
    finish(proc, work)
    token = "FAKE-TOKEN-9f3a7c1d-4e2b-DO-NOT-LOG"
    leaked = [str(p) for p in (root / "secret").rglob("*") if p.is_file() and (token in read(p) or "FAKE-PROFILE-ARN" in read(p))]
    chk("secret: turn completed", rc == 0, "%s %r" % (rc, out))
    chk("secret: the token and profile ARN are in no file of the work or cwd directory", not leaked, repr(leaked))
    chk("secret: the reply shows the token redaction", "token seen: [redacted]" in read(work / "out" / "001.txt"), read(work / "out" / "001.txt"))
    chk("secret: the reply shows the profile ARN redaction", "arn seen: [redacted]" in read(work / "out" / "001.txt"), read(work / "out" / "001.txt"))
    chk("secret: the supply is logged without the value", "token supplied" in read(work / "events.log"))

    # A token far longer than every clip length (200 to 600 characters), carried in a tool title, a permission
    # request, an unhandled request and an error notification: nothing of it, not even its first part, may land.
    proc, work, cwd = start(root, "secret-long", scenario={"long_token": True})
    send(work, 1, "ECHO_TOKEN\nECHO_REQUEST\nECHO_NOTIFY\nSAY done")
    rc, out = waiter(work)
    finish(proc, work)
    chk("long secret: turn completed", rc == 0, "%s %r" % (rc, out))
    log = read(work / "events.log")
    chk("long secret: the request and notification paths ran", "REQUEST unhandled x/unknown" in log and "notify _kiro/some/error" in log and "TOOL tool_call in_progress Reading" in log, log[-600:])
    leaks = [str(p) for p in (root / "secret-long").rglob("*") if p.is_file() and ("LONGTOK-abcdefgh" in read(p) or "FAKE-PROFILE-ARN" in read(p))]
    chk("long secret: no file holds any part of the token", not leaks, repr(leaks))

    # 6. A killed or interrupted driver leaves no kiro-cli behind.
    if os.name == "nt":
        proc, work, cwd = start(root, "job", scenario={"ignore_eof": True})
        stub_pid = stub_pid_of(cwd)
        send(work, 1, "SLEEP 60")
        time.sleep(1.0)
        proc.kill()
        proc.wait()
        chk("hard kill: a stub that ignores EOF dies with the driver (Windows job object)", pid_gone(mod, stub_pid, 10), str(stub_pid))
    proc, work, cwd = start(root, "interrupt", newgroup=True)
    send(work, 1, "SLEEP 60")
    time.sleep(1.0)
    stub_pid = stub_pid_of(cwd)
    for _ in range(3):  # a second and third signal arriving during the cleanup must not interrupt it
        if os.name == "nt":
            proc.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            proc.terminate()
        time.sleep(0.05)
    chk("signal: the driver exits 1", finish(proc, work, stop=False) == 1)
    chk("signal: FAILED names the signal", "signal" in read(work / "FAILED"), read(work / "FAILED"))
    chk("signal: the stub is gone", pid_gone(mod, stub_pid))

    # 7. Waiter edge cases that need no driver.
    solo = root / "solo"
    (solo / "in").mkdir(parents=True)
    (solo / "in" / "001.txt").write_text("x", encoding="utf-8")
    rc, out = waiter(solo, timeout=10, extra=["--status-grace", "1"])
    chk("waiter: no status.json within the grace means the driver never started (exit 3)", rc == 3 and "never started" in out, "%s %r" % (rc, out))
    me = os.getpid()
    (solo / "status.json").write_text(json.dumps({"state": "ready", "pid": me, "pid_start": 12345}), encoding="utf-8")
    if mod.proc_start(me) is not None:
        rc, out = waiter(solo, timeout=5)
        chk("waiter: a live pid with a different creation time is a reused pid (exit 3)", rc == 3 and "driver dead" in out, "%s %r" % (rc, out))



def pending_selection_boundaries(mod, root):
    # Real request queue, dispatcher and waiter; only OS transport is omitted.
    def snapshot(model="old", effort="high"):
        return {"configOptions": [
            {"id": "mode", "currentValue": "kiro_default"},
            {"id": "model", "currentValue": model, "options": [{"value": "old"}, {"value": "new"}]},
            {"id": "effortLevel", "currentValue": effort, "options": [{"value": "high"}, {"value": "max"}]},
            {"id": "thinking", "currentValue": "off"}]}
    for key, target in (("model", "new"), ("effortLevel", "max")):
        for case in ("old-current", "regress-after-confirm", "other-protected", "withdrawn", "malformed", "unexpected"):
            base = root / ("pending-" + key + "-" + case)
            d = mod.Driver(types.SimpleNamespace(work=str(base), cwd=str(root),
                total_timeout=20, startup_timeout=2, turn_timeout=2))
            d.sid = "ordered-session"
            d.record_config(snapshot(), "fixture")
            other = "effortLevel" if key == "model" else "model"
            d.expected, d.armed = {"mode": "kiro_default", other: d.config[other]["currentValue"]}, True
            errors = []
            def select():
                try:
                    d.select_config(key, target)
                except Exception as exc:
                    errors.append(str(exc))
            thread = threading.Thread(target=select, daemon=True)
            thread.start()
            try:
                request, _ = d.send_queue.get(timeout=2)
                old = snapshot()  # unrelated thinking snapshot precedes setter processing
                if case == "other-protected":
                    next(o for o in old["configOptions"] if o["id"] == other)["currentValue"] = "new" if other == "model" else "max"
                elif case == "withdrawn":
                    old["configOptions"] = [o for o in old["configOptions"] if o["id"] != key]
                elif case == "malformed":
                    old["configOptions"].append({"id": [], "currentValue": "bad"})
                elif case == "unexpected":
                    next(o for o in old["configOptions"] if o["id"] == key)["currentValue"] = "third-value"
                handler_error = None
                try:
                    d.handle({"method": "session/update", "params": {"update": dict(old, sessionUpdate="config_option_update")}})
                except mod.Fail as exc:
                    handler_error = str(exc)
                confirmed = snapshot(model=target) if key == "model" else snapshot(effort=target)
                if case == "regress-after-confirm":
                    # Confirmation arrives, then regression, then a stale successful reply.
                    d.handle({"method": "session/update", "params": {"update": dict(confirmed, sessionUpdate="config_option_update")}})
                    d.handle({"method": "session/update", "params": {"update": dict(snapshot(), sessionUpdate="config_option_update")}})
                d.handle({"id": request["id"], "result": confirmed})
                thread.join(3)
                if case == "old-current":
                    chk("pending %s: unrelated old-current snapshot permits successful exact readback" % key,
                        not errors and not d.drift and not thread.is_alive() and d.expected.get(key) == target,
                        repr((errors, d.drift, d.config)))
                else:
                    chk("pending %s %s: fail closed despite later successful reply" % (key, case),
                        bool(errors or handler_error) and bool(d.drift) and not thread.is_alive(), repr((errors, handler_error, d.drift)))
            finally:
                d.agent_gone.set()
                thread.join(3)
                d.logf.close()


def owned_group_boundaries(mod, root):
    # All calls are real driver methods with substituted POSIX OS primitives.
    # There is no real signal, child process, procfs read or permission probe.
    for case in ("reaped-reuse-between-probe-and-signal", "reused-group-leader-already-exited"):
        d = mod.Driver(types.SimpleNamespace(work=str(root / case), cwd=str(root)))
        actions = []
        class Process:
            pid = 987654
            returncode = 0 if case == "reused-group-leader-already-exited" else None
            def wait(self, timeout):
                actions.append(("reap", timeout))
                self.returncode = 0
                return 0
        d.proc, d.posix_group, d.posix_unreaped = Process(), 987654, True
        real_os, real_start, real_signal = mod.os, mod.proc_start, mod.signal
        proxy = types.SimpleNamespace(**{key: getattr(real_os, key) for key in dir(real_os)})
        proxy.name = "posix"
        proxy.P_PID, proxy.WEXITED, proxy.WNOHANG, proxy.WNOWAIT, proxy.CLD_EXITED = 1, 2, 4, 8, 1
        def waitid(*args):
            actions.append(("externally-reaped",))
            raise ChildProcessError()
        def kill(pid, sig):
            actions.append(("absence-probe-then-reuse", pid, sig))
            raise ProcessLookupError()
        proxy.waitid, proxy.kill = waitid, kill
        proxy.killpg = lambda pid, sig: actions.append(("UNRELATED-group-signal", pid, sig))
        mod.os, mod.proc_start, mod.signal = proxy, lambda pid: None, types.SimpleNamespace(SIGTERM=15, SIGKILL=9)
        try:
            d.kill_tree()
            chk("POSIX %s: lost reservation never authorizes an unrelated group signal" % case,
                not any(a[0] == "UNRELATED-group-signal" for a in actions), repr(actions))
            chk("POSIX %s: cleanup failure is explicit and absence is never ownership proof" % case,
                bool(getattr(d, "cleanup_error", None)) and not any(a[0] == "absence-probe-then-reuse" for a in actions), repr(actions))
        finally:
            mod.os, mod.proc_start, mod.signal = real_os, real_start, real_signal
            d.logf.close()


def posix_observer_boundaries(mod, root):
    # Standalone CLI's actual spawn/observe/cleanup calls, but no real child,
    # signal disposition, kqueue or OS signal is changed on this Windows host.
    for case in ("waitid", "old-mac-kqueue", "kqueue-lost", "kqueue-registration-error", "unsupported", "sigchld-failed"):
        d = mod.Driver(types.SimpleNamespace(work=str(root / ("observer-" + case)), cwd=str(root), kiro=str(STUB)))
        actions = []
        real_os, real_select, real_signal = mod.os, getattr(mod, "select", None), mod.signal
        real_subprocess, real_threading = mod.subprocess, mod.threading
        proxy = types.SimpleNamespace(**{key: getattr(real_os, key) for key in dir(real_os)})
        proxy.name = "posix"
        for key in ("waitid", "P_PID", "WEXITED", "WNOHANG", "WNOWAIT", "CLD_EXITED"):
            if hasattr(proxy, key):
                delattr(proxy, key)
        if case == "waitid":
            proxy.P_PID, proxy.WEXITED, proxy.WNOHANG, proxy.WNOWAIT, proxy.CLD_EXITED = 1, 2, 4, 8, 1
            proxy.waitid = lambda *args: types.SimpleNamespace(si_code=1, si_status=0)
        class Process:
            pid, returncode = 987654, None
            def poll(self):
                actions.append(("FORBIDDEN-reaping-poll",))
                self.returncode = 0
                return 0
            def wait(self, timeout):
                actions.append(("final-reap", timeout))
                self.returncode = 0
                return 0
        class Kqueue:
            delivered = False
            def control(self, changes, maximum, timeout):
                if changes:
                    actions.append(("register", changes[0].ident, changes[0].fflags))
                    if case == "kqueue-registration-error":
                        raise OSError("synthetic registration failure")
                    return []
                actions.append(("observe-without-reap",))
                if case == "kqueue-lost":
                    raise OSError("synthetic observer loss")
                if not self.delivered:
                    self.delivered = True
                    return [types.SimpleNamespace(ident=987654, filter=-5, flags=0, fflags=1)]
                return []
            def close(self):
                actions.append(("close-observer",))
        def sigchld(sig, disposition):
            actions.append(("reset-SIGCHLD", sig, disposition))
            if case == "sigchld-failed":
                raise ValueError("synthetic not main thread")
        def popen(*args, **kwargs):
            actions.append(("spawn-new-session", kwargs.get("start_new_session")))
            return Process()
        proxy.killpg = lambda pid, sig: actions.append(("group-signal", pid, sig))
        sel = types.SimpleNamespace() if case == "unsupported" else types.SimpleNamespace(
            kqueue=Kqueue, kevent=lambda ident, **kw: types.SimpleNamespace(ident=ident, **kw),
            KQ_FILTER_PROC=-5, KQ_EV_ADD=1, KQ_EV_ENABLE=2, KQ_NOTE_EXIT=1)
        mod.os, mod.select = proxy, sel
        mod.signal = types.SimpleNamespace(signal=sigchld, SIGCHLD=17, SIG_DFL=0, SIGTERM=15, SIGKILL=9)
        mod.subprocess = types.SimpleNamespace(Popen=popen, PIPE=-1, TimeoutExpired=subprocess.TimeoutExpired)
        mod.threading = types.SimpleNamespace(Thread=lambda **kw: types.SimpleNamespace(start=lambda: None))
        error = None
        try:
            try:
                d.spawn()
                d.kill_tree()
            except mod.Fail as exc:
                error = str(exc)
                if d.proc is not None:
                    d.kill_tree()
            groups = [a for a in actions if a[0] == "group-signal"]
            if case in ("waitid", "old-mac-kqueue"):
                chk("POSIX observer %s: compatible startup and exited descendant escalation" % case,
                    error is None and groups == [("group-signal", 987654, 15), ("group-signal", 987654, 9)], repr((error, actions)))
                reap = next((i for i,a in enumerate(actions) if a[0] == "final-reap"), -1)
                last_signal = max((i for i,a in enumerate(actions) if a[0] == "group-signal"), default=-1)
                chk("POSIX observer %s: default SIGCHLD precedes spawn and final reap follows all signals" % case,
                    actions[:2] == [("reset-SIGCHLD", 17, 0), ("spawn-new-session", True)] and reap > last_signal
                    and not any(a[0] == "FORBIDDEN-reaping-poll" for a in actions), repr(actions))
                if case == "old-mac-kqueue":
                    chk("POSIX old macOS: kqueue observes and closes without waitid support",
                        any(a[0] == "observe-without-reap" for a in actions) and ("close-observer",) in actions, repr(actions))
            elif case in ("unsupported", "sigchld-failed"):
                chk("POSIX observer %s: actionable refusal before any child is launched" % case,
                    bool(error) and d.proc is None and not any(a[0] == "spawn-new-session" for a in actions), repr((error, actions)))
            else:
                chk("POSIX observer %s: observation failure never permits group signals" % case,
                    not groups and bool(getattr(d, "cleanup_error", None)), repr((error, actions)))
        finally:
            mod.os, mod.select, mod.signal = real_os, real_select, real_signal
            mod.subprocess, mod.threading = real_subprocess, real_threading
            d.logf.close()


def cleanup_terminal_boundaries(mod, root):
    # Actual Driver.run/kill_tree/status/FAILED flow. OS primitives, startup,
    # and child objects are substituted; no real process or signal is used.
    for case in ("permission-denied", "exit-timeout", "denied-and-timeout", "failure-then-denied", "absent-group", "clean-exit", "lost-reservation"):
        d = mod.Driver(types.SimpleNamespace(work=str(root / ("terminal-" + case)), cwd=str(root), stop_grace=0))
        actions = []
        class Process:
            pid, returncode = 987654, None
            def wait(self, timeout):
                actions.append(("final-wait", timeout))
                if case in ("exit-timeout", "denied-and-timeout"):
                    raise subprocess.TimeoutExpired("synthetic owned child", timeout)
                self.returncode = 0
                return 0
        d.proc, d.posix_group, d.posix_unreaped = Process(), 987654, True
        d.spawn = d.handshake = lambda: None
        def phase():
            if case == "failure-then-denied":
                raise mod.Fail("synthetic work failure")
        d.main_loop = phase
        d.agent_gone.set()
        real_os, real_signal, real_time = mod.os, mod.signal, mod.time
        proxy = types.SimpleNamespace(**{key: getattr(real_os, key) for key in dir(real_os)})
        proxy.name = "posix"
        proxy.P_PID, proxy.WEXITED, proxy.WNOHANG, proxy.WNOWAIT, proxy.CLD_EXITED = 1, 2, 4, 8, 1
        def waitid(*args):
            if case == "lost-reservation":
                raise ChildProcessError()
            return None  # leader remains reserved and live until final wait
        def killpg(pid, sig):
            actions.append(("group-signal", pid, sig))
            if case in ("permission-denied", "denied-and-timeout", "failure-then-denied"):
                raise PermissionError("synthetic denied owned-group signal")
            if case == "absent-group":
                raise ProcessLookupError("synthetic already absent group")
        proxy.waitid, proxy.killpg = waitid, killpg
        ticks = [0]
        def monotonic():
            ticks[0] += 4
            return ticks[0]
        clock = types.SimpleNamespace(**{key: getattr(real_time, key) for key in dir(real_time)})
        clock.monotonic = monotonic
        mod.os, mod.time = proxy, clock
        mod.signal = types.SimpleNamespace(SIGTERM=15, SIGKILL=9, SIGINT=2, SIG_IGN=1,
            getsignal=lambda sig: 0, signal=lambda *args: None)
        try:
            rc = d.run()
            final = status(d.work) or {}
            failed = read(d.work / "FAILED")
            groups = [a for a in actions if a[0] == "group-signal"]
            if case in ("absent-group", "clean-exit"):
                chk("terminal cleanup %s: confirmed exit retains successful stopped status" % case,
                    rc == 0 and final.get("state") == "stopped" and not failed and not d.cleanup_error,
                    repr((rc, final, failed, actions)))
            else:
                chk("terminal cleanup %s: failed cleanup cannot publish a clean stop" % case,
                    rc == 1 and final.get("state") == "failed" and bool(failed) and bool(d.cleanup_error),
                    repr((rc, final, failed, actions)))
                chk("terminal cleanup %s: next action prevents another worker before cleanup is resolved" % case,
                    "Next action: do not start another run" in failed and "exact owned worker" in failed
                    and "never kill processes by name" in failed, failed)
            if case in ("permission-denied", "denied-and-timeout", "failure-then-denied", "absent-group"):
                chk("terminal cleanup %s: no further group signal after denial or absence" % case,
                    groups == [("group-signal", 987654, 15)], repr(actions))
            elif case == "lost-reservation":
                chk("terminal cleanup: lost ownership never sends any group signal", not groups, repr(actions))
            else:
                chk("terminal cleanup %s: owned resistant group still receives TERM and KILL" % case,
                    groups == [("group-signal", 987654, 15), ("group-signal", 987654, 9)], repr(actions))
            if case not in ("absent-group", "clean-exit"):
                chk("terminal cleanup %s: event log never claims the driver stopped successfully" % case,
                    "driver stopped" not in read(d.work / "events.log"), read(d.work / "events.log"))
        finally:
            mod.os, mod.signal, mod.time = real_os, real_signal, real_time
            d.logf.close()


def metadata_atomic_boundaries(mod, root):
    # Actual reader/handler/snapshot and writer methods. A logging barrier holds
    # the caught-error boundary; a prepared turn tests completion under that gap.
    choices = [
        ("null", None), ("bool", True), ("number", 7), ("string", "old"), ("object", {}),
        ("null-item", [{"value": "old"}, None]),
        ("scalar-item", [{"value": "old"}, 7]),
        ("null-value", [{"value": "old"}, {"value": None}]),
        ("numeric-value", [{"value": "old"}, {"value": 7}]),
        ("group-null-options", [{"value": "old"}, {"group": "g", "options": None}]),
        ("group-object-options", [{"value": "old"}, {"group": "g", "options": {}}]),
        ("nested-bad-item", [{"value": "old"}, {"group": "g", "options": [{"options": [None]}]}]),
        ("null-group", [{"group": None, "options": [{"value": "old"}]}]),
        ("ambiguous-leaf-group", [{"value": "old", "options": []}]),
        ("empty-choice", [{"value": "old"}, {}]),
        ("mode-null", None),
        ("effort-nested-bad", [{"value": "max"}, {"options": [None]}]),
        ("valid-grouped-control", [{"value": "old"}, {"group": "g", "options": [{"value": "new"}]}])]
    observations = []
    def snapshot():
        return {"configOptions": [
            {"id": "mode", "currentValue": "kiro_default"},
            {"id": "model", "currentValue": "old", "options": [{"value": "old"}, {"value": "new"}]},
            {"id": "effortLevel", "currentValue": "max", "options": [{"value": "max"}]}]}
    def driver(case):
        d = mod.Driver(types.SimpleNamespace(work=str(root / ("metadata-" + case)), cwd=str(root), turn_timeout=2))
        d.record_config(snapshot(), "fixture")
        d.expected, d.armed = {"mode": "kiro_default", "model": "old", "effortLevel": "max"}, True
        d.sid = "metadata-synthetic-session"
        return d
    for case, options in choices:
        d = driver(case)
        bad = snapshot()
        index = 0 if case == "mode-null" else 2 if case == "effort-nested-bad" else 1
        bad["configOptions"][index]["options"] = options
        message = {"method": "session/update", "params": {"update": dict(bad, sessionUpdate="config_option_update")}}
        sink = io.BytesIO()
        d.proc = types.SimpleNamespace(pid=987654, stdin=sink, stdout=[json.dumps(message).encode()])
        entered, release, waiting, finish_turn = (threading.Event() for _ in range(4))
        phases, turn_errors = [], []
        original_log = d.log
        def log(text):
            original_log(text)
            if text.startswith("handler error") or text == "agent stdout closed":
                phases.append(text)
                entered.set()
                if not release.wait(3):
                    raise RuntimeError("metadata logging barrier timed out")
        d.log = log
        prompt = d.work / "in/001.txt"
        prompt.write_text("synthetic prepared turn", encoding="utf-8")
        d.request = lambda *a, **kw: None
        def wait(*args, **kwargs):
            waiting.set()
            if not finish_turn.wait(3):
                raise RuntimeError("metadata completion barrier timed out")
            return {"result": {"stopReason": "end_turn"}}
        d.wait = wait
        def turn():
            try:
                d.run_turn(prompt)
            except Exception as exc:
                turn_errors.append(str(exc))
        turn_thread = threading.Thread(target=turn, daemon=True)
        reader = threading.Thread(target=d.read_stdout, daemon=True)
        writer_error = None
        try:
            turn_thread.start()
            prepared = waiting.wait(2)
            reader.start()
            reached = entered.wait(2)
            at_barrier = d.drift
            try:
                d.write_message({"method": "session/prompt"}, b"synthetic queued prompt bytes")
            except Exception as exc:
                writer_error = str(exc)
            finish_turn.set()
            turn_thread.join(2)
            done = (d.work / "out/001.done").exists()
            if case == "valid-grouped-control":
                chk("atomic metadata valid control: prepared prompt and completion remain allowed",
                    prepared and reached and not at_barrier and not writer_error and bool(sink.getvalue())
                    and done and not turn_errors and not turn_thread.is_alive(), repr((phases, writer_error, done, turn_errors)))
            else:
                chk("atomic metadata %s: reader failure is published before logging releases dispatch" % case,
                    prepared and reached and bool(at_barrier) and bool(writer_error) and not sink.getvalue(),
                    repr((phases, at_barrier, writer_error, sink.getvalue())))
                chk("atomic metadata %s: a previously prepared completion cannot commit during the error gap" % case,
                    not done and bool(turn_errors) and not turn_thread.is_alive(), repr((done, turn_errors)))
            observations.append({"case": case, "prepared": prepared, "logging_barrier_reached": reached, "at_barrier_drift": at_barrier, "writer_error": writer_error,
                "prompt_bytes": len(sink.getvalue()), "completion_done": done, "turn_errors": turn_errors,
                "logging_phases": list(phases)})
        finally:
            finish_turn.set()
            release.set()
            turn_thread.join(3)
            reader.join(3)
            d.logf.close()
    # Direct snapshot exceptions must already poison state without relying on
    # read_stdout's later fallback. Includes a failure after snapshot publication.
    for case in ("direct-null", "direct-nested", "injected-log-failure"):
        d = driver(case)
        sink = io.BytesIO()
        d.proc = types.SimpleNamespace(stdin=sink)
        malformed = snapshot()
        if case == "direct-null":
            malformed["configOptions"][1]["options"] = None
        elif case == "direct-nested":
            malformed["configOptions"][1]["options"] = [{"value": "old"}, {"options": None}]
        else:
            original_log = d.log
            def log(text):
                if text.startswith("injected-log:"):
                    raise RuntimeError("synthetic snapshot logging failure")
                original_log(text)
            d.log = log
        caught, writer_error = None, None
        try:
            try:
                d.record_config(malformed, "injected-log" if case == "injected-log-failure" else "fixture")
            except Exception as exc:
                caught = type(exc).__name__
            try:
                d.write_message({"method": "session/prompt"}, b"direct snapshot prompt")
            except Exception as exc:
                writer_error = str(exc)
            chk("atomic metadata %s: snapshot exception poisons dispatch before returning" % case,
                bool(caught) and bool(d.drift) and bool(writer_error) and not sink.getvalue(),
                repr((caught, d.drift, writer_error, sink.getvalue())))
            observations.append({"case": case, "snapshot_error": caught, "drift": d.drift,
                "writer_error": writer_error, "prompt_bytes": len(sink.getvalue())})
        finally:
            d.logf.close()
    (root / "metadata-race-observations.json").write_text(json.dumps(observations, indent=2), encoding="utf-8")


def config_boundaries(mod, root):
    def driver(name):
        base = root / name
        args = types.SimpleNamespace(work=str(base / "work"), cwd=str(base),
                                     total_timeout=20, startup_timeout=5, turn_timeout=5,
                                     cancel_grace=1, stop_grace=1)
        d = mod.Driver(args)
        d.sid = "boundary-session"
        d.record_config(snapshot(), "fixture")
        d.expected = {"mode": "kiro_default"}
        d.armed = True
        return d

    def snapshot(model="old", effort="max"):
        return {"configOptions": [
            {"id": "mode", "currentValue": "kiro_default"},
            {"id": "model", "currentValue": model, "options": [{"value": "old"}, {"value": "new"}]},
            {"id": "effortLevel", "currentValue": effort, "options": [{"value": "high"}, {"value": "max"}]}]}

    def drift(d):
        changed = snapshot()
        changed["configOptions"][0]["currentValue"] = "vibe"
        d.check_drift(changed)

    # The receive thread owns snapshots. The main thread resumes only after a
    # newer notification has arrived, and must not restore the older response.
    d = driver("ordered-snapshots")
    calls = []
    real_request = d.request
    def request(method, params):
        calls.append((method, params))
        return real_request(method, params)
    d.request = request
    def wait(h, *args, **kwargs):
        rid = next(k for k, v in d.pending.items() if v is h)
        key = calls[-1][1]["configId"]
        result = snapshot(model="new", effort="max")
        d.handle({"id": rid, "result": result})
        if key == "model":
            d.check_drift(snapshot(model="new", effort="high"))
        return h["resp"]
    d.wait = wait
    try:
        d.select_config("model", "new")
        chk("receive order: newer effort notification survives model setter return",
            d.config["effortLevel"]["currentValue"] == "high", repr(d.config))
        d.select_config("effortLevel", "max")
        chk("receive order: requested effort is set after the newer notification",
            [p["configId"] for m, p in calls] == ["model", "effortLevel"], repr(calls))
    finally:
        d.logf.close()

    # A prepared prompt must be checked again at the actual transport boundary.
    d = driver("dispatch-boundary")
    sink = io.BytesIO()
    d.proc = types.SimpleNamespace(stdin=sink)
    try:
        d.assert_config()  # prompt preparation was valid
        drift(d)
        caught = None
        try:
            d.write_message({"method": "session/prompt"}, b"prompt payload")
        except mod.Fail as exc:
            caught = str(exc)
        chk("dispatch boundary: already observed drift rejects a prepared prompt",
            bool(caught and "mode drift" in caught) and not sink.getvalue(), repr((caught, sink.getvalue())))
    finally:
        d.logf.close()

    # Force a reader update to attempt entry after final validation. It must
    # remain blocked until the actual write has completed under the same lock.
    d = driver("dispatch-serialization")
    entered, attempting, applied, release = (threading.Event() for _ in range(4))
    order, errors = [], []
    class Sink:
        def write(self, data):
            order.append("write")
        def flush(self):
            pass
    d.proc = types.SimpleNamespace(stdin=Sink())
    real_assert = d.assert_config
    def assert_then_pause():
        real_assert()
        entered.set()
        if not release.wait(3):
            raise RuntimeError("dispatch test release timed out")
    d.assert_config = assert_then_pause
    def writer():
        try:
            d.write_message({"method": "session/prompt"}, b"payload")
        except Exception as exc:
            errors.append(repr(exc))
    def reader():
        attempting.set()
        drift(d)
        order.append("update")
        applied.set()
    writer_thread = threading.Thread(target=writer, daemon=True)
    reader_thread = threading.Thread(target=reader, daemon=True)
    try:
        writer_thread.start()
        entered_ok = entered.wait(2)
        reader_thread.start()
        attempting.wait(2)
        blocked = not applied.wait(0.15)
        release.set()
        writer_thread.join(3)
        reader_thread.join(3)
        chk("dispatch serialization: update cannot commit between validation and write",
            entered_ok and blocked and order == ["write", "update"] and not errors
            and not writer_thread.is_alive() and not reader_thread.is_alive(), repr((order, errors)))
    finally:
        release.set()
        writer_thread.join(3)
        reader_thread.join(3)
        d.logf.close()

    d = driver("completion-boundary")
    prompt = d.work / "in/001.txt"
    prompt.write_text("SAY work", encoding="utf-8")
    d.request = lambda *a, **kw: None
    d.wait = lambda *a, **kw: {"result": {"stopReason": "end_turn"}}
    real_line = d.write_out_line
    def end_with_update(text):
        if text.startswith("[end of turn:"):
            drift(d)
        real_line(text)
    d.write_out_line = end_with_update
    try:
        caught = None
        try:
            d.run_turn(prompt)
        except mod.Fail as exc:
            caught = str(exc)
        chk("completion boundary: drift before commit prevents the done marker",
            bool(caught and "mode drift" in caught) and not (d.work / "out/001.done").exists(), repr(caught))
    finally:
        if d.out is not None:
            d.out.close()
        d.logf.close()

    # Both published status and its temporary file must redact complete JSON,
    # including the JSON-escaped representation of a known synthetic secret.
    d = driver("config-status-secret")
    secret = 'SYNTHETIC-token-with-\\slash-and-"quote'
    d.red.add(secret)
    raw = snapshot(effort=secret)
    d.record_config(raw, "fixture")
    try:
        d.set_status("failed", reason=secret)
        files = [d.work / "status.json"]
        real_replace = mod.os.replace
        def blocked_replace(*args):
            raise PermissionError("test sharing violation")
        real_sleep = mod.time.sleep
        mod.os.replace = blocked_replace
        mod.time.sleep = lambda secs: None
        try:
            d.set_status("failed", reason=secret)
        finally:
            mod.os.replace = real_replace
            mod.time.sleep = real_sleep
        files.append(d.work / "status.json.tmp")
        chk("config status: published and temporary JSON redact synthetic secrets",
            all(p.exists() and "SYNTHETIC" not in read(p) and "[redacted]" in read(p) for p in files),
            repr([read(p) for p in files]))
    finally:
        d.logf.close()



def write_supervision_boundary(root, mod):
    # A main thread blocked on the configuration lock cannot run wait()'s
    # deadlines. The independent writer supervisor must release that lock by
    # killing only its own stalled fake child.
    base = root / "write-supervision-boundary"
    (base / "cwd").mkdir(parents=True)
    (base / "cwd/scenario.json").write_text(
        json.dumps({"pause_read_after_session_new": True}), encoding="utf-8")
    args = types.SimpleNamespace(work=str(base / "work"), cwd=str(base / "cwd"),
                                 kiro=str(STUB), mode="kiro_default", model=None, effort=None,
                                 total_timeout=20, startup_timeout=5, turn_timeout=0.5,
                                 stop_grace=1, cancel_grace=1)
    d = mod.Driver(args)
    started, lock_released = threading.Event(), threading.Event()
    errors = []
    real_write = d.write_message
    def observed_write(obj, data):
        if obj.get("method") == "session/prompt":
            started.set()
        real_write(obj, data)
    d.write_message = observed_write
    def completion_waiter():
        with d.config_lock:
            try:
                d.assert_config()
            except mod.Fail as exc:
                errors.append(str(exc))
        lock_released.set()
    contender = threading.Thread(target=completion_waiter, daemon=True)
    try:
        d.spawn()
        d.handshake()
        d.request("session/prompt", {"sessionId": d.sid,
                  "prompt": [{"type": "text", "text": "x" * (1024 * 1024)}]})
        sent = started.wait(2)
        time.sleep(0.1)
        contender.start()
        bounded = lock_released.wait(3)
        exited = False
        if bounded:
            try:
                d.proc.wait(timeout=3)  # pipe/lock release can precede OS process exit
                exited = d.proc.poll() is not None
            except subprocess.TimeoutExpired:
                pass
        chk("write supervisor: releases a blocked configuration lock without main-thread wait polling",
            sent and bounded and bool(errors) and "pipe write" in errors[0]
            and exited, repr((sent, bounded, exited, errors)))
    finally:
        d.kill_tree()
        if contender.ident is not None:
            contender.join(3)
        d.send_queue.put(None)
        d.agent_gone.wait(1)
        d.logf.close()


def config_wire_regressions(root, mod):
    for label, scenario, extra in (
        ("legacy-mode", {"legacy_mode": True}, ["--effort", "max"]),
        ("legacy-no-config", {"legacy_mode": True, "legacy_no_config": True}, []),
    ):
        proc, work, cwd = start(root, label, scenario=scenario, extra=extra)
        chk(label + ": separate mode readback preserves the original handshake behavior",
            (status(work) or {}).get("state") == "ready" and (status(work) or {}).get("mode") == "kiro_default",
            repr(status(work)))
        send(work, 1, "SAY legacy session")
        rc, out = waiter(work)
        chk(label + ": a queued turn succeeds with the bound legacy mode", rc == 0, out)
        chk(label + ": stops cleanly", finish(proc, work) == 0)

    proc, work, cwd = start(root, "malformed-drift")
    send(work, 1, "MALFORMED_DRIFT")
    rc, out = waiter(work)
    chk("malformed config: invalid identifier fails closed without a success marker",
        rc == 1 and "invalid configuration snapshot" in read(work / "FAILED")
        and not (work / "out/001.done").exists(), "%s %r" % (rc, out))
    chk("malformed config: driver exits 1", finish(proc, work, stop=False) == 1)

    proc, work, cwd = start(root, "config-secret-wire", extra=["--effort", "high"])
    # Complete an auth echo first, so the fake server has consumed its token reply.
    send(work, 1, "ECHO_TOKEN")
    chk("config secret: synthetic authentication exchange completes", waiter(work)[0] == 0)
    send(work, 2, "ECHO_CONFIG")
    rc, out = waiter(work, turn=2)
    chk("config secret: credential-bearing effort drift fails the turn", rc == 1 and "effort drift" in out, out)
    finish(proc, work, stop=False)
    leaked = [str(p) for p in work.rglob("*") if p.is_file() and
              ("FAKE-TOKEN-9f3a7c1d" in read(p) or "FAKE-PROFILE-ARN" in read(p))]
    chk("config secret: no work file contains the echoed synthetic token or ARN", not leaked, repr(leaked))

    for label, extra, stop in (
        ("turn", ["--turn-timeout", "2", "--total-timeout", "30"], False),
        ("total", ["--turn-timeout", "30", "--total-timeout", "3"], False),
        ("stop", ["--turn-timeout", "30", "--total-timeout", "30"], True),
    ):
        proc, work, cwd = start(root, "blocked-pipe-" + label,
                                scenario={"pause_read_after_session_new": True}, extra=extra)
        stub_pid = stub_pid_of(cwd)
        send(work, 1, "SAY " + "x" * (1024 * 1024))
        running = state_is(work, "turn 1 running", 5)
        # Poll the real pipe state through lack of a complete request at the fake.
        time.sleep(0.25)
        if stop:
            (work / "in/stop").write_text("", encoding="utf-8")
        started = time.time()
        rc = finish(proc, work, stop=False)
        reason = read(work / "FAILED")
        chk("blocked pipe %s: fails within bounded time and never commits success" % label,
            running and rc == 1 and time.time() - started < 10 and reason
            and not (work / "out/001.done").exists(), repr((rc, reason)))
        chk("blocked pipe %s: no complete prompt reaches the fake and its process is gone" % label,
            "session/prompt" not in read(cwd / "wire.log") and stub_pid and not mod.pid_alive(stub_pid),
            read(cwd / "wire.log"))


def residual_boundaries(mod, root):
    for shape in ("sessionId", "_meta"):
        args = types.SimpleNamespace(work=str(root / ("session-secret-" + shape)), cwd=str(root),
                                     mode="kiro_default", model=None, effort=None, startup_timeout=5)
        d = mod.Driver(args)
        token, arn = "SYNTHETIC-session-token-0007", "arn:aws:fake:profile/SYNTHETIC-session-arn"
        raw = "session-" + token + "-" + arn
        d.red.add(token, arn)
        request = d.request
        d.proc = types.SimpleNamespace(stdin=io.BytesIO())
        def respond(method, params):
            h = request(method, params)
            rid = next(k for k, v in d.pending.items() if v is h)
            result = {} if method == "initialize" else {
                "configOptions": [{"id": "mode", "currentValue": "kiro_default"}]}
            if method != "initialize":
                result.update({shape: raw if shape == "sessionId" else {"id": raw}})
            d.handle({"id": rid, "result": result})
            return h
        d.request = respond
        d.wait = lambda h, *a, **kw: h["resp"]
        try:
            d.handshake()
            persisted = read(d.work / "session.txt")
            chk("session identifier %s: known synthetic token and ARN are redacted on disk" % shape,
                token not in persisted and arn not in persisted and persisted.count("[redacted]") == 2, persisted)
            chk("session identifier %s: wire identity is preserved in memory" % shape, d.sid == raw)
        finally:
            d.logf.close()

    # These POSIX branches are mocks on Windows: no subprocess or OS signal.
    # Only an unreaped leader reserves the owned group through escalation.
    for case in ("reaped-resistant", "reserved-exited", "pid-reused", "pid-reused-after-term", "identity-unknown", "absent-group", "permission-denied"):
        args = types.SimpleNamespace(work=str(root / ("posix-" + case)), cwd=str(root))
        d = mod.Driver(args)
        actions = []
        group_alive = [True]  # SIGTERM is ignored; only SIGKILL ends the descendant
        class Process:
            pid = 987654
            returncode = 0 if case in ("reaped-resistant", "pid-reused", "identity-unknown") else None
            def poll(self):
                actions.append(("poll",))
                return self.returncode
            def wait(self, timeout):
                actions.append(("reap", timeout))
                self.returncode = 0
                return 0  # leader exit never proves the resistant group ended
        d.proc = Process()
        d.posix_group, d.posix_unreaped, d.agent_start = d.proc.pid, True, 100
        real_os, real_signal, real_start = mod.os, mod.signal, mod.proc_start
        def kill(pid, sig):
            actions.append(("identity-probe", pid, sig))
            if case != "identity-unknown":
                raise ProcessLookupError()
            raise PermissionError()
        def killpg(pid, sig):
            actions.append(("group", pid, sig))
            if case == "absent-group":
                raise ProcessLookupError()
            if case == "permission-denied":
                raise PermissionError()
            if sig == 9:
                group_alive[0] = False
        def waitid(*args):
            actions.append(("observe-unreaped",))
            if case == "pid-reused-after-term" and any(a[0] == "group" for a in actions):
                raise ChildProcessError()
            return types.SimpleNamespace(si_code=1, si_status=0)
        proxy = types.SimpleNamespace(**{key: getattr(real_os, key) for key in dir(real_os)})
        proxy.name, proxy.kill, proxy.killpg, proxy.waitid = "posix", kill, killpg, waitid
        proxy.P_PID, proxy.WEXITED, proxy.WNOHANG, proxy.WNOWAIT, proxy.CLD_EXITED = 1, 2, 4, 8, 1
        mod.os, mod.signal = proxy, types.SimpleNamespace(SIGTERM=15, SIGKILL=9)
        mod.proc_start = lambda pid: 200 if case == "pid-reused" or (case == "pid-reused-after-term" and any(a[0] == "group" for a in actions)) else None
        try:
            d.kill_tree()
            groups = [action for action in actions if action[0] == "group"]
            if case == "reserved-exited":
                chk("POSIX %s: terminate and kill the exact owned group despite leader exit" % case,
                    groups == [("group", 987654, 15), ("group", 987654, 9)] and not group_alive[0], repr(actions))
                if case == "reserved-exited":
                    reap = next((i for i, action in enumerate(actions) if action[0] == "reap"), -1)
                    kills = [i for i, action in enumerate(actions) if action[0] == "group"]
                    chk("POSIX reserved leader: no reap before final group signal", len(kills) == 2 and reap > kills[-1], repr(actions))
                    chk("POSIX reserved leader: monitoring never polls/reaps before group cleanup",
                        reap >= 0 and not any(action[0] == "poll" for action in actions[:reap]), repr(actions))
            elif case == "pid-reused-after-term":
                chk("POSIX PID reused during escalation: refuse SIGKILL to the new group",
                    groups == [("group", 987654, 15)], repr(actions))
            elif case in ("reaped-resistant", "pid-reused", "identity-unknown"):
                chk("POSIX %s: refuse all group signals" % case, not groups, repr(actions))
            else:
                chk("POSIX %s: unavailable group stops bounded escalation" % case,
                    groups == [("group", 987654, 15)], repr(actions))
            if hasattr(mod.Driver, "group_owned"):
                chk("POSIX %s: cleanup releases the stored group before reaping" % case, d.posix_group is None)
        finally:
            mod.os, mod.signal, mod.proc_start = real_os, real_signal, real_start
            d.logf.close()


def watchdog_exit_order_unit(mod, root):
    # Deterministic OS-exit lag: the writer lock is already free, but poll stays
    # live until an explicit bounded wait completes. No process is launched.
    events = []
    class Process:
        dead = False
        def poll(self):
            return 1 if self.dead else None
        def wait(self, timeout):
            events.append(("bounded-exit-wait", timeout))
            self.dead = True
            return 1
    class Driver:
        def __init__(self, args):
            self.proc = Process()
            self.config_lock = threading.Lock()
            self.transport_error = "pipe write timed out or did not end after the stop request"
            self.sid = "synthetic-session"
            self.logf = io.StringIO()
            self.send_queue = mod.queue.Queue()
            self.agent_gone = threading.Event()
            self.agent_gone.set()
        def spawn(self):
            pass
        def handshake(self):
            pass
        def write_message(self, obj, data):
            pass
        def request(self, method, params):
            self.write_message({"method": method}, b"synthetic payload")
        def assert_config(self):
            raise mod.Fail(self.transport_error)
        def kill_tree(self):
            self.proc.dead = True
    proxy = types.SimpleNamespace(Driver=Driver, Fail=mod.Fail)
    write_supervision_boundary(root / "watchdog-os-exit-lag", proxy)
    chk("watchdog OS exit lag: child exit receives its own bounded wait after lock release",
        events == [("bounded-exit-wait", 3)], repr(events))


def unit(mod, root):
    cwd = str(root / "unit-cwd")
    os.makedirs(cwd, exist_ok=True)

    def req(capability=None, kind=None, title="t", raw=None, resource=None, trig=None):
        consent = {k: v for k, v in (("capability", capability), ("resource", resource), ("triggeringResource", trig)) if v}
        return {"toolCall": {"title": title, "kind": kind, "rawInput": raw or {}},
                "options": [{"optionId": "a", "kind": "allow_once"}, {"optionId": "r", "kind": "reject_once"}],
                "_meta": {"kiro": {"consent": consent}}}

    def dec(policy, params):
        # Rule tests run in allowlist mode (default: reject) unless the case sets its own default.
        pol = dict(policy, default=policy.get("default", "reject")) if isinstance(policy, dict) else None
        return mod.decide(pol, None if pol else policy, params, cwd)[0]

    sh = lambda c: req("shell", "execute", "Running: " + c, {"command": c})
    allow = {"allow": [{"capability": "shell", "command_prefix": ["git status", "git diff"]}]}
    chk("unit: simple allowed command", dec(allow, sh("git status --short")))
    chk("unit: prefix needs a word boundary", not dec(allow, sh("git statusx")))
    chk("unit: second prefix of the list", dec(allow, sh("git  diff   HEAD")))
    for bad in ("git status; rm x", "git status | cat", "git status > f", "git status `id`", "git status $(id)", "git status\nrm x"):
        chk("unit: control characters defeat an allow prefix: %r" % bad, not dec(allow, sh(bad)))
    chk("unit: the capability must match", not dec(allow, req("fs_write", "edit", "git status", {"command": "git status"})))
    chk("unit: a rule's keys are ANDed", not dec({"allow": [{"capability": "shell", "kind": "read", "command_prefix": "git"}]}, sh("git log")))
    deny_seg = {"allow": [{"capability": "shell"}], "deny": [{"command_prefix": "git push"}]}
    chk("unit: deny prefix catches a later piece of a compound command", not dec(deny_seg, sh("git status && git push")))
    chk("unit: deny prefix catches a $( ) piece", not dec(deny_seg, sh("echo $(git push)")))
    chk("unit: unrelated command passes that deny", dec(deny_seg, sh("git status")))
    chk("unit: empty request is rejected", not dec(allow, {}))
    chk("unit: non-dict params are rejected", not dec(allow, "x"))
    chk("unit: a policy error rejects", not dec("policy is not valid JSON: x", sh("git status")))
    chk("unit: no policy file trusts all tools", mod.decide(None, None, sh("rm -rf x"), cwd)[0])
    chk("unit: default allow when no rule matches", dec({"default": "allow", "deny": [{"command_prefix": "git push"}]}, sh("git log")))
    chk("unit: an invalid default is refused", mod.validate_policy({"default": "maybe"}) is not None)
    for name, pol in (("unknown key", {"allow": [{"capability": "shell", "cmd": "x"}]}),
                      ("empty rule", {"allow": [{"note": "x"}]}),
                      ("command_contains in allow", {"allow": [{"command_contains": "x"}]}),
                      ("top-level typo", {"alow": []}),
                      ("empty list", {"allow": [{"capability": []}]}),
                      ("not an object", [])):
        chk("unit: invalid policy (%s) is refused" % name, mod.validate_policy(pol) is not None)
    chk("unit: a valid policy has no error", mod.validate_policy({"allow": [{"capability": "shell", "note": "x"}], "deny": []}) is None)
    inside = os.path.join(cwd, "sub", "f.txt")
    paths_allow = {"allow": [{"capability": "fs_write", "path_under": cwd}]}
    chk("unit: write inside the directory is allowed", dec(paths_allow, req("fs_write", "edit", "Write", {"path": inside})))
    chk("unit: a relative path is taken against the session cwd", dec(paths_allow, req("fs_write", "edit", "Write", {"path": "sub/f.txt"})))
    chk("unit: .. escaping the directory is refused", not dec(paths_allow, req("fs_write", "edit", "Write", {"path": "../escape.txt"})))
    chk("unit: a sibling with the same prefix is refused", not dec(paths_allow, req("fs_write", "edit", "Write", {"path": cwd + "-other\\f.txt"})))
    chk("unit: one path outside refuses a multi-path request", not dec(paths_allow, req("fs_write", "edit", "Write", {"paths": [inside, "/etc/x"]})))
    chk("unit: no path in the request means no path_under match", not dec(paths_allow, req("fs_write", "edit", "Write", {})))
    chk("unit: consent.resource is a path for file tools", dec(paths_allow, req("fs_write", "edit", "Write", resource=inside)))
    deny_path = {"allow": [{"capability": "fs_write"}], "deny": [{"path_under": os.path.join(cwd, ".git")}]}
    chk("unit: a deny path catches a nested file", not dec(deny_path, req("fs_write", "edit", "Write", {"path": os.path.join(cwd, ".git", "config")})))
    mcp = {"allow": [{"capability": "mcp", "resource": "docs/search"}]}
    chk("unit: mcp resource match", dec(mcp, req("mcp", "other", "Call", resource="docs/search")))
    chk("unit: mcp resource differs", not dec(mcp, req("mcp", "other", "Call", resource="docs/delete")))
    chk("unit: title match is exact and case-insensitive", dec({"allow": [{"title": "load skill: qconfig-sync"}]}, req(title="Load skill: qconfig-sync")))
    chk("unit: title is not a substring match", not dec({"allow": [{"title": "load skill"}]}, req(title="Load skill: qconfig-sync")))
    opts = [{"optionId": "x", "kind": "allow_always"}, {"optionId": "y", "kind": "reject_once"}]
    chk("unit: allow never picks allow_always", mod.pick_option(opts, True) is None)
    chk("unit: reject picks reject_once", mod.pick_option(opts, False) == "y")
    chk("unit: reject falls back to reject_always", mod.pick_option([{"optionId": "z", "kind": "reject_always"}], False) == "z")
    chk("unit: no reject option gives None", mod.pick_option([{"optionId": "a", "kind": "allow_once"}], False) is None)
    chk("unit: read_back from configOptions", mod.read_back({"configOptions": [{"id": "mode", "currentValue": "m"}, {"id": "model", "currentValue": "x.1"}]}) == ("m", "x.1"))
    chk("unit: read_back prefers modes.currentModeId", mod.read_back({"modes": {"currentModeId": "kiro_default"}}) == ("kiro_default", None))
    chk("unit: grouped config choices preserve advertised values", mod.option_values({"options": [
        {"group": "models", "options": [{"value": "sonnet"}, {"value": "opus"}]}, {"value": "other"}]}) == ["sonnet", "opus", "other"])
    rejected = subprocess.run([PY, "-I", str(STUB), "acp", "--agent-engine", "v3", "--model", "claude-sonnet-4.6"],
                              cwd=cwd, capture_output=True, text=True, timeout=5)
    chk("unit: v3 stub rejects the obsolete model launch flag", rejected.returncode == 2 and "unsupported arguments" in rejected.stderr, rejected.stderr)
    red = mod.Redactor()
    red.add("SECRET-VALUE-12345")
    sr = mod.StreamRedactor(red)
    got = sr.feed("abc SECRET-VAL") + sr.feed("UE-12345 def") + sr.flush()
    chk("unit: a secret split across chunks is redacted", "SECRET" not in got and "[redacted]" in got, got)
    chk("unit: bearer text is redacted", "abcdefghijk" not in red.text("Authorization: Bearer abcdefghijklmnop"))
    noconsent = lambda kind, raw, title="t": {"toolCall": {"title": title, "kind": kind, "rawInput": raw},
                                              "options": [{"optionId": "a", "kind": "allow_once"}]}
    chk("unit: no consent block: kind execute is the shell capability", dec(allow, noconsent("execute", {"command": "git status"}, "Running: git status")))
    chk("unit: no consent block: a shell deny rule still applies", not dec({"allow": [{"capability": "shell"}], "deny": [{"capability": "shell", "command_contains": "push"}]},
                                                                           noconsent("execute", {"command": "git push"}, "Running: git push")))
    chk("unit: no consent block: edit is fs_write with its path", dec(paths_allow, noconsent("edit", {"path": inside})))
    chk("unit: no consent block: read is fs_read, not fs_write", not dec(paths_allow, noconsent("read", {"path": inside})))
    chk("unit: no consent block and an unknown kind has no capability", not dec({"allow": [{"capability": "shell"}]}, noconsent("other", {"command": "x"})))
    rel = {"allow": [{"capability": "fs_write", "path_under": "sub"}]}
    chk("unit: a relative path_under is taken against the session cwd", dec(rel, req("fs_write", "edit", "Write", {"path": inside})))
    chk("unit: a relative path_under does not match outside the session cwd", not dec(rel, req("fs_write", "edit", "Write", {"path": os.path.join(cwd, "other", "f.txt")})))
    me = os.getpid()
    start_time = mod.proc_start(me)
    chk("unit: a live pid is alive", mod.pid_alive(me))
    chk("unit: a pid with another creation time is not the same process", start_time is None or not mod.pid_alive(me, start_time + 1))
    chk("unit: a pid with its own creation time is alive", start_time is None or mod.pid_alive(me, start_time))
    chk("unit: no such pid is not alive", not mod.pid_alive(2 ** 22 + 7) and not mod.pid_alive(None))
    red2 = mod.Redactor()
    red2.add("tok\\en-with-back-slash")
    chk("unit: a secret with a backslash is redacted as JSON text", "back-slash" not in red2.text(json.dumps({"x": "tok\\en-with-back-slash"})))
    chk("unit: kiro_command runs a .py under this interpreter", mod.kiro_command("x.py")[0] == sys.executable and mod.kiro_command("kiro-cli") == ["kiro-cli"])


def kill_tree_unit(mod, root):
    """kill_tree called directly, on a stub that ignores stdin EOF. Through a whole driver run the Windows job object
    would end the stub when the driver exits and hide a kill_tree that does nothing; here the driver stays alive."""
    for label, grace in (("immediate", 0), ("after a stdin-close grace", 1)):
        base = root / ("kt-" + label.split()[0])
        (base / "cwd").mkdir(parents=True)
        (base / "cwd" / "scenario.json").write_text(json.dumps({"ignore_eof": True}), encoding="utf-8")
        args = types.SimpleNamespace(work=str(base / "work"), cwd=str(base / "cwd"), kiro=str(STUB), model=None,
                                     mode="kiro_default", total_timeout=60, startup_timeout=30, turn_timeout=30,
                                     stop_grace=1, cancel_grace=1)
        d = mod.Driver(args)
        try:
            d.spawn()
            time.sleep(0.5)
            chk("kill_tree (%s): the stub is running before the kill" % label, d.proc.poll() is None)
            t0 = time.time()
            d.kill_tree(grace=grace)
            chk("kill_tree (%s): the stub that ignores EOF is dead when it returns" % label, d.proc.poll() is not None)
            chk("kill_tree (%s): and so is the stub's own pid" % label, not mod.pid_alive(stub_pid_of(base / "cwd")), str(stub_pid_of(base / "cwd")))
            if grace:
                chk("kill_tree (%s): it waited the grace before killing" % label, time.time() - t0 >= grace - 0.2, str(time.time() - t0))
        finally:
            if d.proc and d.proc.poll() is None:  # the stub this test started
                d.proc.kill()
                d.proc.wait()
            d.logf.close()


def main():
    mod = load_driver_module()
    root = Path(tempfile.mkdtemp(prefix="qkiro-selftest-"))
    try:
        unit(mod, root)
        residual_boundaries(mod, root)
        watchdog_exit_order_unit(mod, root)
        config_boundaries(mod, root)
        cleanup_terminal_boundaries(mod, root)
        metadata_atomic_boundaries(mod, root)
        pending_selection_boundaries(mod, root)
        owned_group_boundaries(mod, root)
        posix_observer_boundaries(mod, root)
        write_supervision_boundary(root, mod)
        kill_tree_unit(mod, root)
        config_wire_regressions(root, mod)
        scenarios(root, mod)
    except Exception as exc:  # a harness bug is a failure, not a crash
        FAILS.append("selftest harness raised %s: %s" % (type(exc).__name__, exc))
    finally:
        for proc, work in LIVE:
            if proc.poll() is None:  # unreaped, so its pid cannot have been reused: this is the driver we started
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
                else:
                    proc.kill()
                proc.wait()
        shutil.rmtree(root, ignore_errors=True)
    for f in FAILS:
        print("FAIL: %s" % f)
    print("qkiro-delegate selftest: %d checks, %d failed" % (CHECKS[0], len(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
