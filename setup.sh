#!/usr/bin/env bash
# agent-playbook setup (POSIX shell): a thin bootstrap. Twin: setup.ps1.
# It finds Python 3.8+ (python3, then python) and runs setup/setup.py with it in isolated mode,
# passing every flag through; setup/setup.py does the work, on every platform (its docstring has the
# modes, the deploy lock and the ownership rule). With no Python 3.8+ it exits 2 and says what to
# install. Under Git Bash on Windows this finds the Windows Python, which deploys exactly as
# setup.ps1 does (home from USERPROFILE).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
    cat <<'EOF'
Usage: setup.sh [options]

Deploys agent-playbook into the AI providers you choose. Safe to re-run.

  --providers LIST   comma-separated subset of: claude,codex,gemini,kiro (or "all").
                     Default: interactive -- the detected ones, confirmed; otherwise all.
  --dry-run          print every change instead of making it; nothing is written.
  --yes              accept every default without asking (create a local store repo
                     when none exists, create the engine branch, back up and replace
                     a file of yours that is in the way). Your own ~/.claude/CLAUDE.md
                     or ~/.gemini/GEMINI.md is never replaced: the playbook loads beside it.
                     For Gemini CLI, setup then adds "AGENT-PLAYBOOK.md" to context.fileName
                     in ~/.gemini/settings.json, with or without --yes; when it cannot edit
                     that file (comments in it, say), it prints the line to add by hand.
  --stores-url URL   clone the store repo from URL when it is missing.
  --no-stores        do not set up a store repo (memory is disabled until you do).
  --uninstall        remove what setup deployed for the chosen providers: links into
                     this repo, the files it wrote and you did not edit (by the deploy
                     lock), the Claude Code settings entries; restore each .bak setup
                     made, and kiro-cli's default agent when setup set it.
  --purge            with --uninstall: also remove ~/.agent-playbook/config and the
                     repo's memory link. The store repo itself is never touched.
  -h, --help         this text.

Requires Python 3.8+ (python3 or python) and git. setup/setup.py does the work.

Environment: AGENT_PLAYBOOK_STORES (store repo path), AGENT_PLAYBOOK_CONFIG (pointer
file path), AGENT_PLAYBOOK_SKIP_KIRO_CLI=1 (do not change kiro-cli's global settings).
AGENT_PLAYBOOK_TEST_VENV_DIR and AGENT_PLAYBOOK_TEST_GEMINI_HELPER are for the setup
scenario test only (the venv folder to use instead of the repo's .venv-agent-playbook,
and a script to run instead of providers/gemini/context-filename.py).
EOF
}

for a in "$@"; do
    case "$a" in -h|--help) usage; exit 0 ;; esac
done

PYTHON=""
for c in python3 python; do
    if command -v "$c" >/dev/null 2>&1 \
        && "$c" -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3, 8) else 1)' >/dev/null 2>&1; then
        PYTHON="$c"
        break
    fi
done
if [ -z "$PYTHON" ]; then
    {
        echo "ERROR: setup needs Python 3.8+ (tried: python3, python) and found none."
        echo "  Install it (python.org, or your package manager), then run setup.sh again."
        echo "  What an earlier setup deployed is listed in ${HOME:-~}/.agent-playbook/deploy-lock.tsv;"
        echo "  README.md (Uninstall) says how to remove it by hand."
    } >&2
    exit 2
fi

AGENT_PLAYBOOK_SETUP_NAME=setup.sh exec "$PYTHON" -X utf8 -I "$SCRIPT_DIR/setup/setup.py" "$@"
