#!/usr/bin/env python3
"""qdream-phase-hook.py -- PreToolUse guard for the Claude Code `qdream-phase` agent type.

A /qdream phase agent runs under the Dream autonomy exception (shared/AGENTS.md). Its brief lists the tool
surface; this hook makes that surface mechanical on Claude Code. It runs only while a `qdream-phase` agent runs
(declared in the agent definition providers/claude/agents/qdream-phase.md, scoped to that agent).

Rules, per tool:
  Bash     allowed only as `<venv python> -I <config-repo>/shared/skills/qdream/scripts/<script> <subcommand> ...`
           where <subcommand> is the first argument and one of PHASE_SUBCOMMANDS for that script (an allow-list:
           every orchestrator-only subcommand, --selftest and every other script are refused), with no shell
           operator outside quotes (; & | < > ( ), no `$`, no backtick and no line break anywhere.
  Write, Edit, MultiEdit, NotebookEdit
           allowed only on a file inside <home>/.agent-playbook/dream-work/handoff/, spelled with no `:` after the
           drive (no alternate data stream) and no path component ending in a dot or a space, and never on a file
           only the orchestrator or a script writes (ORCHESTRATOR_FILES, decision-<n>.json).
  Agent, Task
           allowed only with subagent_type `qdream-reader` and a prompt that opens with a child brief's marker.
  PowerShell
           refused (the agent's tools list does not offer it; this is defence in depth).
  any other tool: no decision (the agent's `tools` list is the allow-list).

Output contract with the launcher qdream-phase-hook.sh: an allowed call prints exactly ALLOW_LINE on stdout and
exits 0; a refusal exits 2 with the reason on stderr. The launcher turns anything else (a crash, another exit
code, a missing ALLOW_LINE) into exit 2, so the guard fails closed: Claude Code lets a call through on any hook
exit code other than 2.

Usage: qdream-phase-hook.py            (hook mode: PreToolUse JSON on stdin)
       qdream-phase-hook.py --selftest

Stdlib only, Python 3.8+.
"""
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ALLOW_LINE = "qdream-phase-guard: allow"
FORBIDDEN_CHARS = ("$", "`", "\n", "\r")
OPERATOR_CHARS = set("();<>|&")
WRITE_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit")
AGENT_TOOLS = ("Agent", "Task")
REFUSED_TOOLS = ("PowerShell",)
CHILD_TYPE = "qdream-reader"
CHILD_MARKERS = ("Dream Sub-agent Brief ", "Dream Verifier Brief ", "Dream Drafter Brief ")
# The subcommands a phase agent runs (sweep-handoff.md § Phases and the brief's read-only additions). A tuple
# value names the words that must follow the subcommand (`state ledger` only).
PHASE_SUBCOMMANDS = {
    "dream-sweep.py": {"brief": (), "wait": (), "extract": (), "countverify": (), "coverage": (), "gather": (),
                       "aggregate": (), "feeder": (), "singletons": (), "similar": (), "blast": (), "gate": (),
                       "handoff": (), "show": ()},
    "dream-write.py": {"ops": (), "queue": (), "state": ("ledger",)},
    "dream-manifest.py": {"context": ()},
    "dream-check.py": {"extract": (), "budget": ()},
}
ORCHESTRATOR_FILES = ("decisions.json", "answers.json", "report.md", "gate.md", "orient.json", "gather.json",
                      "working-map-seed.json")
DECISION_FILE_RE = re.compile(r"^decision-\d+\.json$")

SURFACE = ("a phase agent runs only the qdream script subcommands its brief names, one command per call, with "
           "no shell operator, redirection, pipe or variable: run `<python> -I <skill-dir>/scripts/"
           "<name>.py <subcommand> ...` and read its printed summary; read files with Read, Grep and Glob")


def _norm(path):
    """Resolve a path as Git Bash or Windows would spell it, for comparison."""
    p = path.strip()
    m = re.match(r"^/([a-zA-Z])/(.*)$", p)
    if m and os.name == "nt":
        p = "%s:/%s" % (m.group(1).upper(), m.group(2))
    return os.path.normcase(os.path.realpath(os.path.expanduser(p)))


def _venv_pythons(root):
    return {_norm(str(root / ".venv-agent-playbook" / "Scripts" / "python.exe")),
            _norm(str(root / ".venv-agent-playbook" / "Scripts" / "python")),
            _norm(str(root / ".venv-agent-playbook" / "bin" / "python"))}


def check_bash(command, root):
    if not isinstance(command, str) or not command.strip():
        return "empty command"
    for ch in FORBIDDEN_CHARS:
        if ch in command:
            return "the command contains %r" % ch
    try:
        lex = shlex.shlex(command, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        lex.commenters = ""     # bash starts a comment only at a word start; shlex anywhere
        tokens = list(lex)
    except ValueError as exc:
        return "the command does not parse (%s)" % exc
    for tok in tokens:
        if tok and set(tok) <= OPERATOR_CHARS:
            return "the command uses the shell operator %r" % tok
    if len(tokens) < 4:
        return "not a qdream script call with a subcommand"
    if _norm(tokens[0]) not in _venv_pythons(root):
        return "the interpreter is not the playbook venv's python"
    if tokens[1] != "-I":
        return "the interpreter must run with -I as its first argument"
    script = tokens[2]
    scripts_dir = _norm(str(root / "shared" / "skills" / "qdream" / "scripts"))
    name = os.path.basename(script.replace("\\", "/"))
    if os.path.dirname(_norm(script)) != scripts_dir or name not in PHASE_SUBCOMMANDS:
        return "the script is not a qdream script a phase agent runs"
    sub, rest = tokens[3], tokens[4:]
    allowed = PHASE_SUBCOMMANDS[name]
    if sub not in allowed:
        return "`%s %s` is not a subcommand a phase agent runs (the subcommand comes first)" % (name, sub[:40])
    words = allowed[sub]
    if tuple(rest[:len(words)]) != words:
        return "`%s %s` runs only as `%s %s`" % (name, sub, sub, " ".join(words))
    if name == "dream-sweep.py" and sub == "brief" and any(
            t == "phase" or t.startswith("--kind=phase") for t in rest):
        return "a phase agent never renders a phase brief"
    return None


def check_write(path, home):
    if not isinstance(path, str) or not path.strip():
        return "no file path"
    raw = path.strip().replace("\\", "/")
    body = raw[2:] if re.match(r"^[A-Za-z]:", raw) else raw
    if ":" in body:
        return "the path holds ':' after the drive (an alternate data stream or a device)"
    if any(c != c.rstrip(". ") for c in body.split("/") if c not in ("", ".", "..")):
        return "a path component ends in a dot or a space"
    handoff = _norm(str(home / ".agent-playbook" / "dream-work" / "handoff"))
    target = _norm(path)
    if not target.startswith(handoff + os.sep):
        return "a phase agent writes only files in the work folder's handoff/ directory"
    name = os.path.basename(target)
    if name in ORCHESTRATOR_FILES or DECISION_FILE_RE.match(name):
        return "handoff/%s is written by the orchestrator or a script, never by a phase agent" % name
    return None


def decide(event, root, home):
    """Return None to allow, or the refusal reason."""
    if not isinstance(event, dict):
        return "the hook input is not a JSON object"
    tool = event.get("tool_name")
    tin = event.get("tool_input")
    if not isinstance(tin, dict):
        tin = {}
    if tool == "Bash":
        why = check_bash(tin.get("command"), root)
        return None if why is None else "%s. %s." % (why, SURFACE)
    if tool in WRITE_TOOLS:
        return check_write(tin.get("file_path") or tin.get("notebook_path"), home)
    if tool in AGENT_TOOLS:
        if tin.get("subagent_type") != CHILD_TYPE:
            return "a phase agent launches only `%s` children (got %r)" % (CHILD_TYPE, tin.get("subagent_type"))
        prompt = tin.get("prompt")
        if not isinstance(prompt, str) or not prompt.startswith(CHILD_MARKERS):
            return "a child's prompt is the one line `dream-sweep.py brief` printed for it"
        return None
    if tool in REFUSED_TOOLS:
        return "a phase agent has no %s; run the qdream scripts through Bash" % tool
    return None


def run_hook():
    try:
        event = json.loads(sys.stdin.buffer.read().decode("utf-8"))
        why = decide(event, ROOT, Path.home())
    except Exception as exc:    # fail closed on anything: the launcher refuses a non-allow outcome
        sys.stderr.write("qdream-phase guard: could not decide (%s: %s); refused\n" % (type(exc).__name__, exc))
        return 2
    if why is None:
        sys.stdout.write(ALLOW_LINE + "\n")
        return 0
    sys.stderr.write("qdream-phase guard refused this call: %s\n" % why)
    return 2


def selftest():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "repo"
        home = Path(tmp) / "home"
        py = root / ".venv-agent-playbook" / "Scripts" / "python.exe"
        scripts = root / "shared" / "skills" / "qdream" / "scripts"
        handoff = home / ".agent-playbook" / "dream-work" / "handoff"
        for d in (py.parent, scripts, handoff / "steps"):
            d.mkdir(parents=True)
        py.write_text("")
        pyq, sq = py.as_posix(), scripts.as_posix()
        good = '"%s" -I "%s/dream-sweep.py" ' % (pyq, sq)
        W = '"%s" -I %s/dream-write.py ' % (pyq, sq)
        M = '"%s" -I %s/dream-manifest.py ' % (pyq, sq)
        B = "Bash"
        cases = [
            ("bash script call", B, {"command": good + "gate --snapshot-sha abc"}, True),
            ("bash quoted section", B, {"command": '"%s" -I %s/dream-check.py extract --file x.md --section "## A (b); c"' % (pyq, sq)}, True),
            ("bash state ledger", B, {"command": W + "state ledger --plan"}, True),
            ("bash show", B, {"command": good + "show handoff/gate-items.json --id G1"}, True),
            ("bash manifest context", B, {"command": M + "context --marker phase-gather-1.md"}, True),
            ("bash sed -i", B, {"command": "sed -i s/a/b/ %s/x.json" % handoff.as_posix()}, False),
            ("bash jq redirect", B, {"command": "jq . a.json > b.json"}, False),
            ("bash mv", B, {"command": "mv a b"}, False),
            ("bash inline python", B, {"command": '"%s" -I -c "open(1)"' % pyq}, False),
            ("bash path python", B, {"command": "python %s/dream-sweep.py gate" % sq}, False),
            ("bash chained", B, {"command": good + "gate && rm -f x"}, False),
            ("bash piped", B, {"command": good + "gate | tail -5"}, False),
            ("bash redirect stderr", B, {"command": good + "gate 2>&1"}, False),
            ("bash subshell", B, {"command": good + "gate $(rm x)"}, False),
            ("bash subshell in quotes", B, {"command": good + 'gate "$(rm x)"'}, False),
            ("bash backtick", B, {"command": good + "gate `rm x`"}, False),
            ("bash newline", B, {"command": good + "gate\nrm x"}, False),
            ("bash carriage return", B, {"command": good + "gate\rrm x"}, False),
            ("bash mid-word comment then ;", B, {"command": good + "gate x#;echo PWNED"}, False),
            ("bash mid-word comment then &&", B, {"command": good + "gate x#&&echo PWNED"}, False),
            ("bash quoted comment then |", B, {"command": good + 'gate "a"#|echo PWNED'}, False),
            ("bash other script dir", B, {"command": '"%s" -I %s/evil.py gate' % (pyq, Path(tmp).as_posix())}, False),
            ("bash other qdream script", B, {"command": '"%s" -I %s/store-resolver.py find-or-create x' % (pyq, sq)}, False),
            ("bash no -I", B, {"command": '"%s" %s/dream-sweep.py gate' % (pyq, sq)}, False),
            ("bash -I after the script", B, {"command": '"%s" %s/dream-sweep.py -I gate' % (pyq, sq)}, False),
            ("bash no subcommand", B, {"command": '"%s" -I %s/dream-sweep.py' % (pyq, sq)}, False),
            ("bash selftest", B, {"command": good + "--selftest --work x"}, False),
            ("bash apply-all", B, {"command": W + "apply-all --x"}, False),
            ("bash state apply", B, {"command": W + "state apply"}, False),
            ("bash option before state apply", B, {"command": W + "state --plan apply"}, False),
            ("bash option before manifest", B, {"command": M + "--repo x manifest"}, False),
            ("bash push plan", B, {"command": W + "push --plan"}, False),
            ("bash prune", B, {"command": W + "prune --preview"}, False),
            ("bash decisions", B, {"command": good + "decisions --snapshot-sha a"}, False),
            ("bash gain", B, {"command": good + "gain --phase gather"}, False),
            ("bash phase brief", B, {"command": good + "brief --kind phase --phase gather"}, False),
            ("bash guard rebaseline", B, {"command": good + "guard --rebaseline"}, False),
            ("bash manifest clean", B, {"command": M + "clean"}, False),
            ("write progress", "Write", {"file_path": str(handoff / "progress-synthesize.json")}, True),
            ("write step", "Write", {"file_path": str(handoff / "steps" / "SYN-GATE.json")}, True),
            ("write scratch", "Write", {"file_path": str(Path(tmp) / "an.py")}, False),
            ("write the handoff folder itself", "Write", {"file_path": str(handoff)}, False),
            ("write sibling of handoff", "Write", {"file_path": str(handoff.parent / "sweep" / "x.json")}, False),
            ("write traversal", "Write", {"file_path": str(handoff / ".." / "sweep" / "x.json")}, False),
            ("write decisions", "Write", {"file_path": str(handoff / "decisions.json")}, False),
            ("write decision-3", "Write", {"file_path": str(handoff / "decision-3.json")}, False),
            ("write gate.md", "Write", {"file_path": str(handoff / "gate.md")}, False),
            ("write orient.json", "Write", {"file_path": str(handoff / "orient.json")}, False),
            ("write working-map-seed", "Write", {"file_path": str(handoff / "working-map-seed.json")}, False),
            ("write stream gate.md", "Write", {"file_path": str(handoff / "gate.md::$DATA")}, False),
            ("write stream decision", "Write", {"file_path": str(handoff / "decision-7.json:x")}, False),
            ("write trailing dot", "Write", {"file_path": str(handoff / "decisions.json.")}, False),
            ("edit memory", "Edit", {"file_path": str(root / "memory" / "MEMORY.md")}, False),
            ("agent reader", "Agent", {"subagent_type": "qdream-reader", "prompt": "Dream Verifier Brief V01. Read and follow x."}, True),
            ("agent reader other prompt", "Agent", {"subagent_type": "qdream-reader", "prompt": "do anything"}, False),
            ("agent general", "Agent", {"subagent_type": "general-purpose", "prompt": "Dream Verifier Brief V01."}, False),
            ("agent missing type", "Task", {"prompt": "x"}, False),
            ("powershell", "PowerShell", {"command": "Get-ChildItem"}, False),
            ("read", "Read", {"file_path": "/etc/passwd"}, True),
            ("not an object", None, None, False),
        ]
        failed = 0
        for label, tool, tin, allow in cases:
            event = {"tool_name": tool, "tool_input": tin} if tool else ["x"]
            why = decide(event, root, home)
            ok = (why is None) == allow
            failed += not ok
            print("%s %s%s" % ("PASS" if ok else "FAIL", label, "" if ok else " :: %s" % why))
        # hook mode end to end: the allow line, a refusal, and unreadable input
        for label, data, want_rc, want_out in (
                ("run_hook allow", json.dumps({"tool_name": "Read", "tool_input": {}}), 0, ALLOW_LINE),
                ("run_hook refuse", json.dumps({"tool_name": "Bash", "tool_input": {"command": "mv a b"}}), 2, ""),
                ("run_hook garbage", "{not json", 2, "")):
            p = subprocess.run([sys.executable, "-I", os.path.abspath(__file__)], input=data.encode("utf-8"),
                               capture_output=True)
            ok = p.returncode == want_rc and p.stdout.decode("utf-8").strip() == want_out
            failed += not ok
            print("%s %s%s" % ("PASS" if ok else "FAIL", label, "" if ok else " :: rc %d out %r" % (
                p.returncode, p.stdout[:80])))
        print("selftest: %d case(s), %d failed" % (len(cases) + 3, failed))
        return 1 if failed else 0


if __name__ == "__main__":
    if sys.argv[1:] == ["--selftest"]:
        sys.exit(selftest())
    if sys.argv[1:]:
        sys.stderr.write(__doc__)
        sys.exit(2)
    sys.exit(run_hook())
