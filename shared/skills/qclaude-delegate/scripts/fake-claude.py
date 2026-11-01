"""A stand-in for `claude -p`, for selftest.py only. Never a substitute for the real agent.

Takes the flags claude-delegate.py passes (-p, --output-format, --verbose, --permission-mode, --model, --effort,
--resume), reads the whole prompt from stdin, and prints stream-json lines in the shape measured on Claude Code
2.1.302 (2026-10-17): a hook line, then `system`/`init`, then `assistant` and `user` (tool_result) lines, then
`result`. It records its argv in <cwd>/argv.log and its own pid in <cwd>/stub.pid (under a venv the Popen pid is a
launcher). It reads <cwd>/scenario.json (optional); keys:
  init_model, init_mode      override what the init event reports
  api_key_source             default "none"
  resume_new_session         on --resume, report a fresh session id instead of the requested one
  denials                    list of command strings; each is a refused tool call (tool_result is_error + permission_denials)
  subtype / is_error         the result event's subtype (default "success") and is_error
  exit_code                  process exit code after the result event (default 0)
  no_result                  exit without a result event
  crash_before_init          print an error to stderr and exit 3 before any event
  hang                       seconds to keep running after init, with a child process, writing a line every 0.5 s
  leak                       put the ANTHROPIC_API_KEY value and an sk-ant- string in a tool_result, the result text,
                             stderr and the init event's apiKeySource (which the wrapper logs)
  no_init                    leave the init event out
  init_subtype               the init event's subtype (default "init"); anything else is not an init event
  init_session_raw           the init event's session_id, whatever JSON value (for malformed-init tests; init_model and
                             init_mode are likewise passed through as given, so they can be non-strings)
  result_session             the result event reports this session id instead of the init event's
  result_no_session          the result event has no session_id field
  orphan                     leave a child process running (stdio detached) after a normal exit
total_cost_usd is a running total per session, as measured: 0.17 for a new session, 0.014 more per resumed turn.
The result text is `prompt bytes=N sha256=H first=<first line>` so a test can check the prompt arrived through stdin whole.
"""
import hashlib
import json
import os
import subprocess
import sys
import time

LEAK = "sk-ant-api03-LEAKYLEAKY0123456789"  # leak-scan: ignore (fake key the redaction test plants)


def emit(obj):
    sys.stdout.buffer.write((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()


def main(argv):
    try:
        with open("scenario.json", encoding="utf-8") as f:
            sc = json.load(f)
    except (OSError, ValueError):
        sc = {}

    def flag(name):
        return argv[argv.index(name) + 1] if name in argv else None

    with open("argv.log", "a", encoding="utf-8") as f:
        f.write(json.dumps(argv) + "\n")
    with open("stub.pid", "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))
    if sc.get("crash_before_init"):
        print("fake-claude: simulated startup failure", file=sys.stderr)
        return 3
    prompt = sys.stdin.buffer.read()
    first = prompt.decode("utf-8", "replace").splitlines()[0] if prompt.strip() else ""

    resume = flag("--resume")
    count = 0
    try:
        count = int(open("sessions.count", encoding="utf-8").read())
    except (OSError, ValueError):
        pass
    if resume and not sc.get("resume_new_session"):
        sid = resume
    else:
        count += 1
        with open("sessions.count", "w", encoding="utf-8") as f:
            f.write(str(count))
        sid = "aaaaaaaa-0000-4000-8000-%012d" % count
    requested = flag("--model")
    model = sc.get("init_model") or (requested if requested and requested.startswith("claude-") else "claude-sonnet-5-5")

    emit({"type": "system", "subtype": "hook_started", "hook_name": "SessionStart:startup", "session_id": sid})
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if sc.get("leak"):
        print("stderr leak %s %s" % (key, LEAK), file=sys.stderr, flush=True)
    if not sc.get("no_init"):
        emit({"type": "system", "subtype": sc.get("init_subtype", "init"), "cwd": os.getcwd(),
              "session_id": sc.get("init_session_raw", sid),
              "model": model, "permissionMode": sc.get("init_mode") or flag("--permission-mode"),
              "apiKeySource": ("leak-" + key) if sc.get("leak") else sc.get("api_key_source", "none"),
              "claude_code_version": "2.1.302-fake"})
    emit({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "working"}]},
          "session_id": sid})

    if sc.get("hang"):
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"])
        with open("child.pid", "w", encoding="utf-8") as f:
            f.write(str(child.pid))
        end = time.time() + float(sc["hang"])
        while time.time() < end:  # a write to a closed stdout raises: the stub dies with its parent, as claude does
            emit({"type": "system", "subtype": "thinking_tokens"})
            time.sleep(0.5)

    denials = []
    for i, cmd in enumerate(sc.get("denials") or []):
        tid = "toolu_fake%02d" % i
        emit({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": tid, "name": "Bash", "input": {"command": cmd}}]}, "session_id": sid})
        emit({"type": "system", "subtype": "permission_denied", "tool_name": "Bash", "tool_use_id": tid,
              "decision_reason_type": "safetyCheck", "decision_reason": "Dangerous rm operation"})
        emit({"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": tid, "is_error": True,
             "content": "Permission for this command was denied by a built-in Claude Code safety check."}]},
              "session_id": sid})
        denials.append({"tool_name": "Bash", "tool_use_id": tid, "tool_input": {"command": cmd}})

    text = "prompt bytes=%d sha256=%s first=%s" % (len(prompt), hashlib.sha256(prompt).hexdigest(), first[:80])
    if sc.get("leak"):
        key = os.environ.get("ANTHROPIC_API_KEY", "")
        emit({"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_leak", "content": "env key %s and %s" % (key, LEAK)}]},
              "session_id": sid})
        text += " leaked %s %s" % (key, LEAK)

    try:
        with open("costs.json", encoding="utf-8") as f:
            costs = json.load(f)
    except (OSError, ValueError):
        costs = {}
    costs[sid] = round(costs[sid] + 0.014, 6) if sid in costs else 0.17
    with open("costs.json", "w", encoding="utf-8") as f:
        json.dump(costs, f)
    if sc.get("orphan"):
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"], stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        with open("child.pid", "w", encoding="utf-8") as f:
            f.write(str(child.pid))
    if not sc.get("no_result"):
        res = {"type": "result", "subtype": sc.get("subtype", "success"), "is_error": bool(sc.get("is_error")),
               "result": text, "session_id": sc.get("result_session") or sid, "total_cost_usd": costs[sid],
               "num_turns": 1, "duration_ms": 1234,
               "permission_denials": denials, "terminal_reason": "completed"}
        if sc.get("result_no_session"):
            del res["session_id"]
        emit(res)
    return int(sc.get("exit_code", 0))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
