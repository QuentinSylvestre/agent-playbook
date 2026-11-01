"""A stand-in for kiro-cli, for selftest.py only. Never a substitute for the real agent.

Speaks the subset of ACP the driver uses, over stdio:
  fake-kiro.py acp --agent-engine v3                serve ACP (model/effort CLI flags are rejected)
  fake-kiro.py chat _ get-kas-token                 print a fixed fake token
It reads <cwd>/scenario.json (optional): {"mode_reply": "...", "model_reply": "...", "initialize_delay": S,
"exit_after_session_new": true, "ignore_eof": true, "long_token": true}. Prompts are directive lines, one per line:
  SAY <text>                      send an agent message
  PERM <capability> <kind> <title> | <rawInput JSON>
                                  ask permission, then say ALLOWED, or REFUSED when not allowed
  SLEEP <seconds>                 wait, ending early with stopReason "cancelled" on session/cancel
  STUBBORN <seconds>              wait and ignore session/cancel
  ECHO_TOKEN                      say the token the driver supplied, in a tool_call title and a permission request
  ECHO_ARN                        the same with the profile ARN
  ECHO_REQUEST / ECHO_NOTIFY      send an unknown request / an `error` notification carrying the token
  ECHO_ERROR                      end the turn with a JSON-RPC error whose message carries the token
  DRIFT_MODE <mode>               send a config_option_update that moves the mode, then end the turn at once
  DRIFT_LATER <mode> <seconds>    send it from a timer, after the turn has ended
  CRASH                           exit at once
It exits when its stdin closes, unless the scenario says ignore_eof (then it must be killed).
"""
import json
import os
import queue
import sys
import threading
import time

FAKE_TOKEN = "FAKE-TOKEN-9f3a7c1d-4e2b-DO-NOT-LOG"
LONG_TOKEN = "LONGTOK-" + "abcdefghij0123456789" * 90  # 1808 characters
FAKE_ARN = "arn:aws:fake:profile/FAKE-PROFILE-ARN-0001"


def read_scenario():
    try:
        with open("scenario.json", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def main(argv):
    scenario = read_scenario()
    if argv[:3] == ["chat", "_", "get-kas-token"]:
        print(json.dumps({"kind": "getKasToken", "data": {
            "accessToken": LONG_TOKEN if scenario.get("long_token") else FAKE_TOKEN,
            "expiresAt": "2099-01-01T00:00:00Z", "profileArn": FAKE_ARN, "provider": "Enterprise"}}))
        return 0
    if argv != ["acp", "--agent-engine", "v3"]:
        print("fake-kiro: unsupported arguments %r" % argv, file=sys.stderr)
        return 2
    with open("stub.pid", "w", encoding="utf-8") as f:  # the stub's own pid: under a venv the Popen pid is a launcher
        f.write(str(os.getpid()))
    inbox = queue.Queue()

    def reader():
        for line in sys.stdin:
            try:
                message = json.loads(line)
                inbox.put(message)
                if scenario.get("pause_read_after_session_new") and message.get("method") == "session/new":
                    time.sleep(60)  # leave the OS pipe unread, rather than draining it into the inbox
            except ValueError:
                pass
        inbox.put(None)

    threading.Thread(target=reader, daemon=True).start()

    out_lock = threading.Lock()

    def send(obj):
        with out_lock:
            sys.stdout.write(json.dumps(obj) + "\n")
            sys.stdout.flush()

    state = {"token": None, "arn": None, "perm_id": 0, "tc": 0}
    config = {
        "mode": {"id": "mode", "currentValue": None},
        "model": {"id": "model", "currentValue": scenario.get("model_reply", "claude-sonnet-4.6"),
                  "options": [{"value": v, "name": v} for v in scenario.get("model_choices", ["claude-sonnet-4.6", "claude-opus-4.5"])]},
        "effortLevel": {"id": "effortLevel", "currentValue": scenario.get("effort_reply", "high"),
                        "options": [{"value": v, "name": v} for v in scenario.get("effort_choices", ["low", "medium", "high", "max"])]},
        "thinking": {"id": "thinking", "currentValue": "on", "options": [{"value": "on"}, {"value": "off"}]}}
    for key in scenario.get("omit_options", []):
        config.pop(key, None)

    def wire(method, params):
        # Protocol evidence only; never serialize auth values or prompt content.
        with open("wire.log", "a", encoding="utf-8") as f:
            f.write(method + (" %s=%s" % (params.get("configId"), params.get("value"))
                             if method == "session/set_config_option" else "") + "\n")

    def eof():
        if scenario.get("ignore_eof"):  # a stub that must be killed, not just starved; it gives up after a minute
            time.sleep(60)
        os._exit(0)

    def update(sid, **fields):
        send({"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": sid, "update": fields}})

    def say(sid, text):
        update(sid, sessionUpdate="agent_message_chunk", content={"type": "text", "text": text})

    def drift(sid, key, value, malformed=False):
        config[key]["currentValue"] = value
        options = ([{"id": [], "currentValue": "bad"}] if malformed else []) + list(config.values())
        update(sid, sessionUpdate="config_option_update", configOptions=options)

    def ask(sid, capability, kind, title, raw):
        state["perm_id"] += 1
        state["tc"] += 1
        rid = "perm-%d" % state["perm_id"]
        send({"jsonrpc": "2.0", "id": rid, "method": "session/request_permission", "params": {
            "sessionId": sid,
            "toolCall": {"toolCallId": "tc-%d" % state["tc"], "title": title, "kind": kind, "rawInput": raw},
            "options": [{"optionId": "allow", "name": "Allow", "kind": "allow_once"},
                        {"optionId": "always", "name": "Always", "kind": "allow_always"},
                        {"optionId": "reject", "name": "Deny", "kind": "reject_once"}],
            "_meta": {"kiro": {"consent": {
                "capability": capability, "resource": raw.get("path") or raw.get("command") or "",
                "triggeringResource": raw.get("command") or raw.get("path") or "", "scope": "agent",
                "source": "agent-profile", "matchedRule": {"capability": capability, "effect": "ask"}}}}}})
        while True:
            msg = inbox.get()
            if msg is None:
                eof()
            if msg.get("id") == rid and "result" in msg:
                out = (msg["result"].get("outcome") or {})
                return out.get("outcome") == "selected" and out.get("optionId") == "allow"

    def prompt(sid, text):
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("SAY "):
                say(sid, line[4:] + "\n")
            elif line.startswith("PERM "):
                head, _, raw = line[5:].partition("|")
                capability, kind, title = (head.strip().split(" ", 2) + ["", ""])[:3]
                ok = ask(sid, capability, kind, title, json.loads(raw) if raw.strip() else {})
                say(sid, ("ALLOWED" if ok else "REFUSED") + ": " + title + "\n")
            elif line.startswith("SLEEP "):
                end = time.time() + float(line[6:])
                while time.time() < end:
                    try:
                        msg = inbox.get(timeout=0.1)
                    except queue.Empty:
                        continue
                    if msg is None:
                        eof()
                    if msg.get("method") == "session/cancel":
                        return "cancelled"
            elif line.startswith("STUBBORN "):  # ignores session/cancel
                time.sleep(float(line[9:]))
            elif line == "ECHO_TOKEN":
                say(sid, "token seen: %s\n" % state["token"])
                update(sid, sessionUpdate="tool_call", toolCallId="tc-x", status="in_progress",
                       title="Reading %s" % state["token"])
                ask(sid, "shell", "execute", "Running: echo %s" % state["token"], {"command": "echo %s" % state["token"]})
            elif line == "ECHO_ARN":
                say(sid, "arn seen: %s\n" % state["arn"])
                ask(sid, "shell", "execute", "Running: echo %s" % state["arn"], {"command": "echo %s" % state["arn"]})
            elif line == "ECHO_REQUEST":
                send({"jsonrpc": "2.0", "id": "req-1", "method": "x/unknown", "params": {"note": "pre %s post" % state["token"]}})
                time.sleep(0.3)
            elif line == "ECHO_NOTIFY":
                send({"jsonrpc": "2.0", "method": "_kiro/some/error", "params": {"detail": "pre %s post" % state["token"]}})
                time.sleep(0.3)
            elif line == "ECHO_ERROR":
                return "ERROR:bad %s" % state["token"]
            elif line.startswith("DRIFT_MODE "):  # at once, with no sleep: the update, then the reply
                drift(sid, "mode", line[11:])
            elif line.startswith("DRIFT_MODEL "):
                drift(sid, "model", line[12:])
            elif line.startswith("DRIFT_EFFORT "):
                drift(sid, "effortLevel", line[13:])
            elif line == "MALFORMED_DRIFT":
                drift(sid, "mode", "vibe", malformed=True)
            elif line == "ECHO_CONFIG":
                drift(sid, "effortLevel", "echo %s %s" % (state["token"], state["arn"]))
            elif line.startswith("DRIFT_LATER "):  # <mode> <seconds>: from a timer, so it can land between turns
                mode, _, secs = line[12:].partition(" ")
                threading.Timer(float(secs), lambda: drift(sid, "mode", mode)).start()
            elif line == "CRASH":
                os._exit(3)
        return "end_turn"

    sid = "sess_fake-0001"
    while True:
        msg = inbox.get()
        if msg is None:
            eof()
        m = msg.get("method")
        if m:
            wire(m, msg.get("params") or {})
        if m == "initialize":
            time.sleep(float(scenario.get("initialize_delay", 0)))
            send({"jsonrpc": "2.0", "id": 0, "method": "_kiro/auth/getAccessToken", "params": {}})
            send({"jsonrpc": "2.0", "id": msg["id"], "result": {"protocolVersion": 1, "agentCapabilities": {}}})
        elif msg.get("id") == 0 and "result" in msg:
            state["token"] = msg["result"].get("accessToken")
            state["arn"] = msg["result"].get("profileArn")
        elif m == "session/new":
            mode = scenario.get("mode_reply", ((msg["params"].get("_meta") or {}).get("kiro") or {}).get("modeId"))
            config["mode"]["currentValue"] = mode
            result = {"_meta": {"id": sid}, "configOptions": list(config.values())}
            if scenario.get("legacy_mode"):
                result["modes"] = {"currentModeId": mode}
                result["configOptions"] = [o for o in config.values() if o["id"] != "mode"]
                if scenario.get("legacy_no_config"):
                    result.pop("configOptions")
            send({"jsonrpc": "2.0", "id": msg["id"], "result": result})
            if scenario.get("exit_after_session_new"):
                return 0
        elif m == "session/set_config_option":
            params = msg["params"]
            key, value = params.get("configId"), params.get("value")
            choices = [o["value"] for o in config.get(key, {}).get("options", [])]
            if params.get("sessionId") != sid or key not in config or value not in choices or scenario.get("set_error") == key:
                send({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32602, "message": "unsupported config choice"}})
                continue
            if scenario.get("set_old_snapshot") == key:
                # A different control changes before this setter is processed.
                config["thinking"]["currentValue"] = "off"
                update(sid, sessionUpdate="config_option_update", configOptions=list(config.values()))
            override = "model_set_reply" if key == "model" else "effort_set_reply"
            config[key]["currentValue"] = scenario.get(override, value)
            if key == "model" and "model_effort_choices" in scenario:
                config["effortLevel"]["options"] = [{"value": v} for v in scenario["model_effort_choices"]]
            if key == "model":
                for removed in scenario.get("model_omit_options", []):
                    config.pop(removed, None)
            options = [o for k, o in config.items() if not (scenario.get("legacy_mode") and k == "mode")]
            update(sid, sessionUpdate="config_option_update", configOptions=options)
            result = {"configOptions": [o for o in options if scenario.get("set_missing_readback") != o["id"]]}
            if scenario.get("set_drift_before_reply") == key:
                drift(sid, key, "unexpected")
            if scenario.get("set_no_options") == key:
                result = {}
            send({"jsonrpc": "2.0", "id": msg["id"], "result": result})
        elif m == "session/prompt":
            stop = prompt(msg["params"]["sessionId"], "\n".join(
                b.get("text", "") for b in msg["params"]["prompt"] if isinstance(b, dict)))
            if stop.startswith("ERROR:"):
                send({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32000, "message": stop[6:]}})
            else:
                send({"jsonrpc": "2.0", "id": msg["id"], "result": {"stopReason": stop}})
        elif "id" in msg and "method" in msg:
            send({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": "unsupported"}})


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
