#!/usr/bin/env bash
# Launcher for the qdream-phase PreToolUse guard (qdream-phase-hook.py).
#
# Declared in providers/claude/agents/qdream-phase.md, so it runs only while a /qdream phase agent runs.
# Claude Code runs a hook command in Git Bash on Windows. This launcher finds the config repo from
# AGENT_PLAYBOOK_ROOT or ~/.agent-playbook/config (root=), then runs the venv interpreter with -I on the
# guard, passing stdin through.
#
# It fails closed. Claude Code lets a tool call through on any hook exit code other than 2, so this
# launcher exits 0 only when the guard exited 0 AND printed exactly its allow line; every other outcome
# (no config, no venv, a broken interpreter, a crash, an unexpected exit code or output) exits 2. The agent
# definition's command adds `|| exit 2` for the case where this file itself cannot run.
ALLOW="qdream-phase-guard: allow"
root="${AGENT_PLAYBOOK_ROOT:-}"
if [ -z "$root" ] && [ -f "$HOME/.agent-playbook/config" ]; then
    root=$(sed -n 's/^root=//p' "$HOME/.agent-playbook/config" | head -n 1 | tr -d '\r')
fi
py="$root/.venv-agent-playbook/Scripts/python.exe"
[ -f "$py" ] || py="$root/.venv-agent-playbook/bin/python"
if [ -z "$root" ] || [ ! -f "$py" ] || [ ! -f "$root/providers/claude/qdream-phase-hook.py" ]; then
    echo "qdream-phase guard did not run: config repo or venv missing (run setup); call refused" >&2
    exit 2
fi
out=$("$py" -I "$root/providers/claude/qdream-phase-hook.py")
rc=$?
if [ "$rc" -eq 0 ] && [ "$(printf '%s' "$out" | tr -d '\r')" = "$ALLOW" ]; then
    exit 0
fi
if [ "$rc" -ne 2 ]; then
    echo "qdream-phase guard failed (exit $rc, no allow line); call refused" >&2
fi
exit 2
