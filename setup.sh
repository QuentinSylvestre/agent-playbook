#!/usr/bin/env bash
set -euo pipefail

# On Git Bash/MSYS (Windows), the default winsymlinks mode silently falls
# back to COPYING a file's content when the process lacks
# SeCreateSymbolicLinkPrivilege -- `ln -s` returns success (exit 0) and
# prints nothing wrong, but the "symlink" is actually a disconnected,
# never-updating copy. `nativestrict` forces a genuine native symlink
# attempt: it succeeds when Developer Mode is enabled (Windows 10+'s
# unprivileged-symlink-creation path, the same one .NET/PowerShell already
# use) or the process is elevated, and fails LOUDLY otherwise -- turning a
# silent broken deployment into a catchable error. No-op on Linux/WSL/macOS,
# where $MSYS is not consulted; does not override an already-set $MSYS.
export MSYS="${MSYS:-winsymlinks:nativestrict}"

# agent-playbook setup script (Linux / WSL / macOS / Git Bash). Twin: setup.ps1.
# Deploys the playbook into the AI providers you choose by linking their config
# directories to this repo, and prepares what the playbook needs around it: the
# Python venv, the store repo, the pointer file and the engine branch.
#
# Modes (see --help):
#   interactive -- a terminal and no --yes: detects installed providers, asks before
#                  replacing a file of yours, offers the store repo and engine branch.
#   --yes       -- the same defaults with no questions (new local store repo when none).
#   neither     -- no terminal (scripts, test-parity.sh): every provider, a file of
#                  yours is backed up and replaced, and the store repo, engine branch
#                  and memory link are only reported, never created.
#
# Kiro overlay merge: for a shared skill dir, kiro discipline deltas live under
# providers/kiro/skills/<name>/ and are APPENDED to the deployed copy at setup time:
#   - SKILL.md overlay : OVERLAY.md          -> appended to the deployed SKILL.md
#   - aux-file overlay  : <stem>.OVERLAY.md  -> appended to the deployed <stem>.md
#     (e.g. memory-rules.OVERLAY.md -> memory-rules.md)
# Any overlay forces a copy of the skill dir (a single file inside a symlinked dir
# cannot be overwritten); aux merges run AFTER the whole-dir cp. SKILL.OVERLAY.md is
# reserved/forbidden (SKILL.md uses the bare OVERLAY.md) and an overlay whose target
# file is absent is skipped with a warning. See merge_overlay / apply_aux_overlays below.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SHARED_DIR="$SCRIPT_DIR/shared"
ALL_PROVIDERS="claude codex gemini kiro"

usage() {
    cat <<'EOF'
Usage: setup.sh [options]

Deploys agent-playbook into the AI providers you choose. Safe to re-run.

  --providers LIST   comma-separated subset of: claude,codex,gemini,kiro (or "all").
                     Default: interactive -- the detected ones, confirmed; otherwise all.
  --dry-run          print every change instead of making it; nothing is written.
  --yes              accept every default without asking (create a local store repo
                     when none exists, create the engine branch, back up and replace
                     a file of yours that is in the way).
  --stores-url URL   clone the store repo from URL when it is missing.
  --no-stores        do not set up a store repo (memory is disabled until you do).
  --uninstall        remove what setup deployed (links into this repo, generated
                     copies, restored .bak files) for the chosen providers.
  --purge            with --uninstall: also remove ~/.agent-playbook/config and the
                     repo's memory link. The store repo itself is never touched.
  -h, --help         this text.

Environment: AGENT_PLAYBOOK_STORES (store repo path), AGENT_PLAYBOOK_CONFIG (pointer
file path), AGENT_PLAYBOOK_SKIP_KIRO_CLI=1 (do not change kiro-cli's global settings).
EOF
}

PROVIDERS_ARG="" DRY_RUN=0 YES=0 STORES_URL="" NO_STORES=0 UNINSTALL=0 PURGE=0
while [ $# -gt 0 ]; do
    case "$1" in
        --providers) [ $# -ge 2 ] || { echo "ERROR: --providers needs a value" >&2; exit 2; }; PROVIDERS_ARG="$2"; shift 2 ;;
        --providers=*) PROVIDERS_ARG="${1#*=}"; shift ;;
        --dry-run) DRY_RUN=1; shift ;;
        --yes|-y) YES=1; shift ;;
        --stores-url) [ $# -ge 2 ] || { echo "ERROR: --stores-url needs a value" >&2; exit 2; }; STORES_URL="$2"; shift 2 ;;
        --stores-url=*) STORES_URL="${1#*=}"; shift ;;
        --no-stores) NO_STORES=1; shift ;;
        --uninstall) UNINSTALL=1; shift ;;
        --purge) PURGE=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "ERROR: unknown option: $1 (see --help)" >&2; exit 2 ;;
    esac
done
[ "$PURGE" -eq 1 ] && [ "$UNINSTALL" -eq 0 ] && { echo "ERROR: --purge only goes with --uninstall" >&2; exit 2; }

INTERACTIVE=0
if [ "$YES" -eq 0 ] && [ -t 0 ] && [ -t 1 ]; then INTERACTIVE=1; fi

# --- Small helpers ---------------------------------------------------------

# act <command...>: run a filesystem-changing command, or print it under --dry-run.
act() {
    if [ "$DRY_RUN" -eq 1 ]; then
        echo "    DRY: $*"
    else
        "$@"
    fi
}

# write_text <dest> <text>: write text (already carrying its trailing newline) to dest.
write_text() {
    if [ "$DRY_RUN" -eq 1 ]; then
        echo "    DRY: write $1"
    else
        printf '%s' "$2" > "$1"
    fi
}

# ask <question> <default y|n>: y/n answer; the default when not interactive.
ask() {
    local q="$1" def="$2" ans
    if [ "$INTERACTIVE" -eq 0 ]; then
        [ "$def" = y ]
        return
    fi
    read -r -p "  $q [$( [ "$def" = y ] && echo Y/n || echo y/N )] " ans || ans=""
    ans="${ans:-$def}"
    case "$ans" in y|Y|yes|YES) return 0 ;; *) return 1 ;; esac
}

# A path in the pointer file's form: absolute, forward slashes. Under Git Bash this
# is the Windows mixed form (C:/Users/...) so setup.sh and setup.ps1 write the same bytes.
native_path() {
    if command -v cygpath >/dev/null 2>&1; then
        cygpath -m "$1"
    else
        printf '%s' "$1"
    fi
}

# is_engine_link <path>: a symlink whose target lies inside this repo.
is_engine_link() {
    [ -L "$1" ] || return 1
    local t
    t="$(readlink "$1")"
    case "$t" in "$SCRIPT_DIR"/*|"$SCRIPT_DIR") return 0 ;; *) return 1 ;; esac
}

# --- Manifest reader -------------------------------------------------------

MANIFEST_KINDS=()
MANIFEST_DESTS=()
MANIFEST_SOURCES=()
MANIFEST_MODES=()

read_manifest() {
    local manifest_path="$1"
    if [ ! -f "$manifest_path" ]; then
        echo "ERROR: manifest not found: $manifest_path" >&2
        exit 2
    fi
    local line_num=0 count=0
    local valid_kinds="symlink-file symlink-dir copy-file copy-dir-recursive merge-file template-file seed-file"
    while IFS= read -r line; do
        line_num=$((line_num + 1))
        [[ "$line" =~ ^[[:space:]]*# ]] && continue
        [[ "$line" =~ ^[[:space:]]*$ ]] && continue
        local col_count
        col_count=$(printf '%s' "$line" | awk -F'\t' '{print NF}')
        if [ "$col_count" -ne 4 ]; then
            echo "ERROR: manifest line $line_num has $col_count columns (expected 4): $line" >&2
            exit 2
        fi
        local kind dest source mode
        IFS=$'\t' read -r kind dest source mode <<< "$line"
        local found=0
        for k in $valid_kinds; do [ "$k" = "$kind" ] && found=1 && break; done
        if [ "$found" -eq 0 ]; then
            echo "ERROR: manifest line $line_num has unknown kind '$kind': $line" >&2
            exit 2
        fi
        MANIFEST_KINDS+=("$kind")
        MANIFEST_DESTS+=("$dest")
        MANIFEST_SOURCES+=("$source")
        MANIFEST_MODES+=("$mode")
        count=$((count + 1))
    done < "$manifest_path"
    echo "  Manifest: $count entries loaded"
}

# Kiro IDE per-user config dir. Platform-divergent, so each twin resolves its own:
# ${XDG_CONFIG_HOME:-~/.config}/Kiro/User here; %APPDATA%\Kiro\User in setup.ps1.
# Under Git Bash/MSYS, $APPDATA is inherited from Windows -- prefer it so this
# twin targets the real IDE location rather than a POSIX path that cannot exist.
if [ -n "${APPDATA:-}" ] && command -v cygpath >/dev/null 2>&1; then
    KIRO_IDE_USER_DIR="$(cygpath -u "$APPDATA")/Kiro/User"
else
    KIRO_IDE_USER_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/Kiro/User"
fi

expand_dest() {
    local dest="$1"
    if [[ "$dest" == "<KIRO_IDE_USER>/"* ]]; then
        printf '%s' "$KIRO_IDE_USER_DIR/${dest:16}"
    elif [[ "$dest" == "~/"* ]]; then
        printf '%s' "$HOME/${dest:2}"
    else
        printf '%s' "$dest"
    fi
}

expand_source() {
    local source="$1"
    printf '%s' "$SCRIPT_DIR/$source"
}

# --- Template rendering ----------------------------------------------------
# Byte contract (lockstep with setup.ps1 Render-Template and the template-aware
# comparison in verify-deployment.py): strip trailing newlines, substitute
# tokens, emit a single trailing LF. Deliberately the same shape as
# merge_overlay so both generated-file paths share one contract.
#
# Templates use forward slashes for everything AFTER the token.
#
# NO backslash escaping here, deliberately. setup.ps1's Render-Template escapes
# backslashes for JSON because a Windows root (C:\Users\X) needs it; this twin
# is the POSIX deploy path, where $HOME and $SCRIPT_DIR never contain a
# backslash, so escaping would be dead code. (Bash parameter expansion cannot
# express it anyway -- ${v//\\/\\\\} is a silent no-op, verified on bash 5.2.)
# The cross-shell contract is therefore: both twins emit identical bytes for
# every value either can encounter on its own platform -- which is what
# test-parity.sh's render-equivalence assertion checks.
render_template() {
    local src="$1"
    local body
    body="$(cat "$src")"
    # Forward slashes, not backslashes: templates embed these tokens in file://
    # URIs and plain markdown as well as JSON, and forward slashes are valid in
    # all three with no escaping needed. $HOME/$SCRIPT_DIR are already
    # forward-slash on every platform bash runs on, so this is normally a
    # no-op -- it exists for symmetry with setup.ps1's Render-Template, which
    # must convert a native Windows backslash path.
    body="${body//\{\{USER_HOME\}\}/${HOME//\\//}}"
    body="${body//\{\{PLAYBOOK_ROOT\}\}/${SCRIPT_DIR//\\//}}"
    printf '%s\n' "$body"
}

copy_template() {
    local src="$1" dest="$2"
    local rendered
    rendered="$(render_template "$src")"

    # Remove stale symlink if present (migration from symlink-based setup)
    if [ -L "$dest" ]; then
        echo "  REMOVE SYMLINK: $dest"
        act rm "$dest"
    fi

    if [ -e "$dest" ] && [ "$rendered" = "$(cat "$dest")" ]; then
        echo "  OK: $dest (matches rendered source)"
        return
    fi

    write_text "$dest" "$rendered"$'\n'
    echo "  RENDERED: $src -> $dest"
}

# seed-file: render only when the destination is ABSENT. The app owns the live
# file (it rewrites mcp.json at runtime), so the repo copy is a restore seed --
# overwriting it would clobber in-app changes and, for secret-bearing configs,
# the user's live credentials. Refresh the repo copy deliberately, not by deploy.
copy_seed() {
    local src="$1" dest="$2"
    if [ -e "$dest" ]; then
        echo "  OK: $dest (present; seed not overwritten)"
        return
    fi
    write_text "$dest" "$(render_template "$src")"$'\n'
    echo "  SEEDED: $src -> $dest"
}

# --- Linking ---------------------------------------------------------------

# make_way <path>: a non-link file or folder of the user's sits where a link goes.
# Returns 0 when the path is free afterwards (backed up to .bak), 1 to skip it.
make_way() {
    local p="$1"
    if [ "$INTERACTIVE" -eq 1 ]; then
        echo "  $p exists and is not a playbook link."
        if ! ask "Back it up to ${p}.bak and replace it with the playbook's?" y; then
            echo "  SKIPPED: $p (kept as is)"
            return 1
        fi
    fi
    echo "  BACKUP: $p -> ${p}.bak"
    act mv "$p" "${p}.bak"
    return 0
}

link_file() {
    local target="$1"  # source file in repo
    local link="$2"    # symlink to create

    if [ -L "$link" ]; then
        local current_target
        current_target="$(readlink "$link")"
        if [ "$current_target" = "$target" ]; then
            echo "  OK: $link -> $target"
            return
        fi
        echo "  UPDATE: $link (was -> $current_target)"
        act rm "$link"
    elif [ -e "$link" ]; then
        make_way "$link" || return 0
    fi

    act ln -s "$target" "$link"
    echo "  LINKED: $link -> $target"
}

link_dir() {
    local target="$1"
    local link="$2"

    if [ -L "$link" ]; then
        local current_target
        current_target="$(readlink "$link")"
        if [ "$current_target" = "$target" ]; then
            echo "  OK: $link -> $target"
            return
        fi
        echo "  UPDATE: $link (was -> $current_target)"
        act rm "$link"
    elif [ -d "$link" ]; then
        make_way "$link" || return 0
    fi

    act ln -s "$target" "$link"
    echo "  LINKED: $link -> $target"
}

# list_shared_skills: the shared skill names, one per line. .trash / synced / .bucket-*
# are the Claude Code app's own skill-sync cache (it writes beside the skills it finds),
# never a playbook skill.
list_shared_skills() {
    local d n
    for d in "$SHARED_DIR/skills"/*/; do
        [ -d "$d" ] || continue
        n="$(basename "$d")"
        case "$n" in .trash|synced|.bucket-*) continue ;; esac
        printf '%s\n' "$n"
    done
}

# link_skills <skills dir>: one link per shared skill inside the provider's own skills
# folder, so the provider's other skills (built-in, the user's, another pack's) stay.
# A folder of the user's with a playbook skill's name is never replaced: it is reported.
link_skills() {
    local dir="$1" name dest
    if [ -L "$dir" ]; then
        if is_engine_link "$dir"; then
            # the old layout linked the whole folder to shared/skills
            echo "  CONVERT: $dir (one link per skill instead of the whole folder)"
            act rm "$dir"
        else
            echo "  SKIPPED: $dir links to $(readlink "$dir"), not to this repo; link the skills by hand"
            return 0
        fi
    fi
    act mkdir -p "$dir"
    while IFS= read -r name; do
        dest="$dir/$name"
        if [ -e "$dest" ] && [ ! -L "$dest" ]; then
            echo "  KEPT: $dest is your own folder; the playbook's $name skill is not linked there"
            continue
        fi
        link_dir "$SHARED_DIR/skills/$name" "$dest"
    done < <(list_shared_skills)
    # a playbook link whose skill is gone from the repo
    for dest in "$dir"/*; do
        if [ -L "$dest" ] && [ ! -e "$dest" ] && is_engine_link "$dest"; then
            echo "  REMOVE: $dest (dangling)"
            act rm "$dest"
        fi
    done
}

# --- Providers -------------------------------------------------------------

provider_detected() {
    case "$1" in
        claude) [ -d "$HOME/.claude" ] || command -v claude >/dev/null 2>&1 ;;
        codex)  [ -d "$HOME/.codex" ] || command -v codex >/dev/null 2>&1 ;;
        gemini) [ -d "$HOME/.gemini" ] || command -v gemini >/dev/null 2>&1 ;;
        kiro)   [ -d "$HOME/.kiro" ] || [ -d "$KIRO_IDE_USER_DIR" ] || command -v kiro-cli >/dev/null 2>&1 ;;
    esac
}

normalize_providers() {
    local list="${1//,/ }" p out=""
    [ "$list" = "all" ] && list="$ALL_PROVIDERS"
    for p in $list; do
        case " $ALL_PROVIDERS " in
            *" $p "*) case " $out " in *" $p "*) ;; *) out="$out $p" ;; esac ;;
            *) echo "ERROR: unknown provider '$p' (one of: ${ALL_PROVIDERS// /, })" >&2; exit 2 ;;
        esac
    done
    printf '%s' "${out# }"
}

choose_providers() {
    if [ -n "$PROVIDERS_ARG" ]; then
        PROVIDERS="$(normalize_providers "$PROVIDERS_ARG")"
        return
    fi
    if [ "$UNINSTALL" -eq 1 ] && [ -n "$(config_value providers)" ]; then
        PROVIDERS="$(normalize_providers "$(config_value providers)")"
        return
    fi
    if [ "$INTERACTIVE" -eq 0 ]; then
        PROVIDERS="$ALL_PROVIDERS"
        return
    fi
    local p found=""
    for p in $ALL_PROVIDERS; do provider_detected "$p" && found="$found $p"; done
    found="${found# }"
    echo "  Detected: ${found:-none}"
    local ans
    read -r -p "  Deploy to which providers? (comma-separated; Enter for: ${found:-all}) " ans || ans=""
    PROVIDERS="$(normalize_providers "${ans:-${found:-all}}")"
}

wants() { case " $PROVIDERS " in *" $1 "*) return 0 ;; *) return 1 ;; esac; }

# --- Pointer file (shared/AGENTS.md § Config Repo Locations) ---------------

CONFIG_FILE="${AGENT_PLAYBOOK_CONFIG:-$HOME/.agent-playbook/config}"

config_value() {
    [ -f "$CONFIG_FILE" ] || return 0
    sed -n "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*//p" "$CONFIG_FILE" | tail -1 | sed 's/[[:space:]]*$//'
}

STORES="${AGENT_PLAYBOOK_STORES:-$(config_value stores)}"
STORES="${STORES:-$HOME/.agent-playbook/stores}"

write_pointer() {
    local url="${STORES_URL:-$(config_value stores_url)}"
    local text
    text="# agent-playbook pointer file, written by setup (shared/AGENTS.md, Config Repo Locations).
root=$(native_path "$SCRIPT_DIR")
stores=$(native_path "$STORES")
"
    [ -n "$url" ] && text="${text}stores_url=$url
"
    text="${text}engine_branch=local-improvements
providers=${PROVIDERS// /,}
"
    if [ -f "$CONFIG_FILE" ] && [ "$(cat "$CONFIG_FILE")"$'\n' = "$text" ]; then
        echo "  OK: $CONFIG_FILE"
        return
    fi
    act mkdir -p "$(dirname "$CONFIG_FILE")"
    write_text "$CONFIG_FILE" "$text"
    echo "  WROTE: $CONFIG_FILE"
}

# --- Prerequisites ---------------------------------------------------------

PYTHON=""
check_prereqs() {
    local missing=0 c
    for c in python3 python; do
        if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3, 8) else 1)' 2>/dev/null; then
            PYTHON="$c"
            break
        fi
    done
    if [ -n "$PYTHON" ]; then
        echo "  OK: Python $("$PYTHON" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])') ($PYTHON)"
    else
        echo "  MISSING: Python 3.8+ -- install it (python.org, or your package manager), then re-run setup"
        missing=1
    fi
    if command -v git >/dev/null 2>&1; then
        echo "  OK: $(git --version)"
    else
        echo "  MISSING: git -- install it (git-scm.com, or your package manager), then re-run setup"
        missing=1
    fi
    local probe
    probe="$(mktemp -d 2>/dev/null || echo "${TMPDIR:-/tmp}/apb-probe-$$")"
    mkdir -p "$probe"
    if ln -s "$probe" "$probe/link" 2>/dev/null && [ -L "$probe/link" ]; then
        echo "  OK: symlinks can be created"
    else
        echo "  MISSING: symlink rights -- on Windows enable Developer Mode (Settings > System > For developers) or run elevated"
        missing=1
    fi
    rm -rf "$probe"
    if command -v node >/dev/null 2>&1; then
        echo "  OK: Node $(node --version) (optional: qdocument-interaction, Playwright)"
    else
        echo "  NOTE: Node not found (optional: only qdocument-interaction's creation libraries and the Playwright MCP need it)"
    fi
    if [ "$missing" -eq 1 ]; then
        if [ "$DRY_RUN" -eq 1 ]; then
            echo "  (dry run: continuing to show the plan)"
        else
            echo "ERROR: a required prerequisite is missing (above); nothing was deployed." >&2
            exit 2
        fi
    fi
}

# --- Python venv (one interpreter for every playbook script) --------------
# Twin of setup.ps1's venv step: <repo>/.venv-agent-playbook, stdlib only, created
# --without-pip from the system Python 3.8+, rebuilt when it no longer runs.

venv_step() {
    local vdir="$SCRIPT_DIR/.venv-agent-playbook" vpy
    vpy="$vdir/bin/python"
    [ -x "$vdir/Scripts/python.exe" ] && vpy="$vdir/Scripts/python.exe"
    if [ -x "$vpy" ] && "$vpy" -c 'import sys' 2>/dev/null; then
        echo "  OK: $vdir"
        return
    fi
    if [ -z "$PYTHON" ]; then
        echo "  SKIPPED: no Python 3.8+ to create $vdir"
        return
    fi
    if [ -d "$vdir" ] && [ ! -f "$vdir/pyvenv.cfg" ] && [ -n "$(ls -A "$vdir" 2>/dev/null)" ]; then
        echo "ERROR: $vdir exists, is not empty and is not a venv (no pyvenv.cfg). Move or delete it, then run setup again." >&2
        exit 2
    fi
    act "$PYTHON" -m venv --clear --without-pip "$vdir"
    echo "  CREATED: $vdir"
}

# --- Store repo, memory link, engine branch --------------------------------

TEMPLATES_MEMORY="$SCRIPT_DIR/templates/memory"

seed_user_memory() {
    local mem="$STORES/user/memory" f
    [ -d "$mem" ] && return 0
    if [ -d "$SCRIPT_DIR/memory" ] && [ ! -L "$SCRIPT_DIR/memory" ]; then
        echo "  NOTE: $SCRIPT_DIR/memory is a real folder (the layout before the store repo held user memory);"
        echo "        move it to $mem, then re-run setup to link it"
        return 0
    fi
    echo "  SEED: $mem (empty user memory from templates/memory/)"
    act mkdir -p "$mem"
    for f in "$TEMPLATES_MEMORY"/*; do
        [ -f "$f" ] && act cp "$f" "$mem/"
    done
}

create_store() {
    echo "  CREATE: $STORES (a new local store repo; add a remote and push it to keep it)"
    act mkdir -p "$STORES"
    act git -C "$STORES" init -q
    write_text "$STORES/.gitignore" "user/memory/.dream-journal.jsonl
*/STORE.tmp-*
"
}

store_step() {
    if [ -d "$STORES/.git" ]; then
        echo "  OK: $STORES"
    elif [ "$NO_STORES" -eq 1 ]; then
        echo "  SKIPPED: store repo (--no-stores); memory stays off until $STORES exists"
        return
    elif [ -n "$STORES_URL" ]; then
        echo "  CLONE: $STORES_URL -> $STORES"
        act git clone -q "$STORES_URL" "$STORES"
    elif [ "$INTERACTIVE" -eq 1 ]; then
        echo "  No store repo at $STORES. It holds your memory, plans and artifacts (private)."
        local ans
        read -r -p "  [c]lone yours from a URL, create a [n]ew local one, or [s]kip? [n] " ans || ans=""
        case "${ans:-n}" in
            c|C) read -r -p "  Store repo URL: " STORES_URL || STORES_URL=""
                 [ -n "$STORES_URL" ] || { echo "  SKIPPED: no URL given"; return; }
                 echo "  CLONE: $STORES_URL -> $STORES"
                 act git clone -q "$STORES_URL" "$STORES" ;;
            n|N) create_store ;;
            *) echo "  SKIPPED: store repo; memory stays off until $STORES exists"; return ;;
        esac
    elif [ "$YES" -eq 1 ]; then
        create_store
    else
        echo "  NOTE: no store repo at $STORES; memory is off. Re-run with --stores-url URL or --yes, or interactively."
        return
    fi
    seed_user_memory
}

memory_link_step() {
    local link="$SCRIPT_DIR/memory" target="$STORES/user/memory"
    if [ -L "$link" ]; then
        if [ "$(readlink "$link")" = "$target" ]; then
            echo "  OK: $link -> $target"
            return
        fi
        echo "  UPDATE: $link (was -> $(readlink "$link"))"
        act rm "$link"
    elif [ -e "$link" ]; then
        echo "  NOTE: $link is a real folder; memory stays there until you move it to $target"
        return
    fi
    if [ ! -d "$target" ] && [ "$DRY_RUN" -eq 0 ]; then
        echo "  NOTE: no $target yet; the memory link is made once the store repo holds user memory"
        return
    fi
    if [ "$INTERACTIVE" -eq 0 ] && [ "$YES" -eq 0 ]; then
        echo "  NOTE: $link is not linked yet; re-run with --yes or interactively to link it to $target"
        return
    fi
    act ln -s "$target" "$link"
    echo "  LINKED: $link -> $target"
}

engine_branch_step() {
    local branch=local-improvements cur
    git -C "$SCRIPT_DIR" rev-parse --git-dir >/dev/null 2>&1 || { echo "  SKIPPED: $SCRIPT_DIR is not a git checkout"; return; }
    cur="$(git -C "$SCRIPT_DIR" symbolic-ref -q --short HEAD || true)"
    if [ "$cur" = "$branch" ]; then
        echo "  OK: on $branch"
        return
    fi
    if [ "$INTERACTIVE" -eq 0 ] && [ "$YES" -eq 0 ]; then
        echo "  NOTE: on ${cur:-a detached HEAD}; engine commits (/qconfig-sync, /qdream) land on $branch -- re-run with --yes or interactively to set it up"
        return
    fi
    ask "Engine commits (/qconfig-sync, /qdream) land on '$branch', never on main. Set it up and switch to it?" y || { echo "  SKIPPED: engine branch"; return; }
    if ! git -C "$SCRIPT_DIR" show-ref -q --verify "refs/heads/$branch"; then
        act git -C "$SCRIPT_DIR" branch -q "$branch"
        echo "  CREATED: branch $branch"
    fi
    if [ -n "$(git -C "$SCRIPT_DIR" status --porcelain --untracked-files=no)" ]; then
        echo "  NOTE: uncommitted changes in $SCRIPT_DIR; switch yourself when ready: git -C $SCRIPT_DIR switch $branch"
        return
    fi
    act git -C "$SCRIPT_DIR" switch -q "$branch"
    echo "  SWITCHED: $SCRIPT_DIR is on $branch"
}

# --- Kiro overlay merge ----------------------------------------------------

# merge_overlay <shared_file> <overlay_file> <out_file>
# Canonical merge shape (must match setup.ps1 Merge-Overlay byte-for-byte, modulo line endings):
#   non-empty overlay -> shared (trailing newlines stripped) + "\n\n" + overlay + single "\n"
#   empty overlay     -> shared (trailing newlines stripped) + single "\n"
# Command substitution $(...) strips trailing newlines, so both bodies arrive newline-free;
# printf re-adds exactly the separators above.
merge_overlay() {
    local shared_file="$1" overlay_file="$2" out_file="$3"
    local shared_body overlay_body
    shared_body="$(cat "$shared_file")"
    overlay_body="$(cat "$overlay_file")"
    if [ "$DRY_RUN" -eq 1 ]; then
        echo "    DRY: merge $overlay_file into $out_file"
        return
    fi
    if [ -n "$(printf '%s' "$overlay_body" | tr -d '[:space:]')" ]; then
        printf '%s\n\n%s\n' "$shared_body" "$overlay_body" > "$out_file"
    else
        printf '%s\n' "$shared_body" > "$out_file"
    fi
}

# apply_aux_overlays <overlay_dir> <dest>
# For every <overlay_dir>/<stem>.OVERLAY.md (except the reserved SKILL.OVERLAY.md), append
# the overlay to the deployed markdown target <dest>/<stem>.md. Naming convention matches
# the consumers (e.g. memory-rules.OVERLAY.md -> memory-rules.md,
# RESEARCH_CONFIG_TEMPLATE.OVERLAY.md -> RESEARCH_CONFIG_TEMPLATE.md). SKILL.OVERLAY.md is
# rejected (SKILL.md uses the bare OVERLAY.md — never two paths to one target). An overlay
# whose target file is absent is skipped with a warning (an overlay never creates a file
# alone). Runs AFTER the whole-dir cp so it overwrites the freshly-copied targets.
apply_aux_overlays() {
    local overlay_dir="$1" dest="$2" src_dir="$3" ov ov_name target_name target_path
    [ -d "$overlay_dir" ] || return 0
    for ov in "$overlay_dir"/*.OVERLAY.md; do
        [ -f "$ov" ] || continue   # no matches -> literal glob, skip
        ov_name="$(basename "$ov")"
        [ "$ov_name" = "OVERLAY.md" ] && continue   # SKILL.md overlay, handled separately
        if [ "$ov_name" = "SKILL.OVERLAY.md" ]; then
            echo "  SKIPPED RESERVED: $ov (SKILL.md uses bare OVERLAY.md; SKILL.OVERLAY.md is forbidden)" >&2
            continue
        fi
        target_name="${ov_name%.OVERLAY.md}.md"
        target_path="$dest/$target_name"
        if [ ! -f "$src_dir/$target_name" ]; then
            echo "  SKIPPED AUX OVERLAY: $ov (no shared target '$target_name')" >&2
            continue
        fi
        merge_overlay "$src_dir/$target_name" "$ov" "$target_path"
        echo "  MERGED AUX: $target_name (shared + kiro overlay)"
    done
}

# has_any_overlay <overlay_dir>
# True if the dir carries any overlay (SKILL.md's OVERLAY.md or any aux <F>.OVERLAY.md).
# Such a skill must be COPIED (not symlinked): a single file inside a symlinked dir cannot
# be overwritten. SKILL.OVERLAY.md is reserved and does not count.
has_any_overlay() {
    local overlay_dir="$1" ov ov_name
    [ -d "$overlay_dir" ] || return 1
    [ -f "$overlay_dir/OVERLAY.md" ] && return 0
    for ov in "$overlay_dir"/*.OVERLAY.md; do
        [ -f "$ov" ] || continue
        ov_name="$(basename "$ov")"
        [ "$ov_name" = "OVERLAY.md" ] && continue
        [ "$ov_name" = "SKILL.OVERLAY.md" ] && continue
        return 0
    done
    return 1
}

# --- Deploy, per provider ----------------------------------------------------

deploy_manifest_links() {
    local mode="$1" i dest source
    for i in "${!MANIFEST_KINDS[@]}"; do
        [ "${MANIFEST_MODES[$i]}" = "$mode" ] || continue
        dest="$(expand_dest "${MANIFEST_DESTS[$i]}")"
        source="$(expand_source "${MANIFEST_SOURCES[$i]}")"
        act mkdir -p "$(dirname "$dest")"
        case "${MANIFEST_KINDS[$i]}" in
            symlink-file) link_file "$source" "$dest" ;;
            symlink-dir)  link_dir  "$source" "$dest" ;;
        esac
    done
}

deploy_claude() {
    echo "=== Claude Code ==="
    act mkdir -p "$HOME/.claude"
    deploy_manifest_links claude
    echo "  Skills (individual):"
    link_skills "$HOME/.claude/skills"
}

deploy_codex() {
    # Codex keeps built-in skills in skills/.system/: one link per skill preserves them.
    echo "=== Codex ==="
    act mkdir -p "$HOME/.codex"
    deploy_manifest_links codex
    echo "  Skills (individual):"
    link_skills "$HOME/.codex/skills"
}

deploy_gemini() {
    echo "=== Gemini CLI ==="
    act mkdir -p "$HOME/.gemini"
    deploy_manifest_links gemini
    echo "  Skills (individual):"
    link_skills "$HOME/.gemini/skills"
}

deploy_kiro() {
    local i dest source dest_parent
    echo "=== Kiro CLI ==="
    KIRO_AGENTS_DIR="$HOME/.kiro/agents"
    KIRO_SETTINGS_DIR="$HOME/.kiro/settings"
    act mkdir -p "$KIRO_AGENTS_DIR" "$KIRO_SETTINGS_DIR"

    # Deploy kiro-always entries from manifest
    for i in "${!MANIFEST_KINDS[@]}"; do
        [ "${MANIFEST_MODES[$i]}" = "kiro-always" ] || continue
        dest="$(expand_dest "${MANIFEST_DESTS[$i]}")"
        source="$(expand_source "${MANIFEST_SOURCES[$i]}")"
        dest_parent="$(dirname "$dest")"
        act mkdir -p "$dest_parent"
        if [ -f "$source" ]; then
            if [ "${MANIFEST_KINDS[$i]}" = "template-file" ]; then
                copy_template "$source" "$dest"
            elif [ "${MANIFEST_KINDS[$i]}" = "seed-file" ]; then
                copy_seed "$source" "$dest"
            elif [ -e "$dest" ] && cmp -s "$source" "$dest"; then
                echo "  OK: $dest (matches source)"
            else
                act cp "$source" "$dest"
                echo "  COPIED: $source -> $dest"
            fi
        fi
    done

    if [ "${AGENT_PLAYBOOK_SKIP_KIRO_CLI:-}" = "1" ]; then
        echo "  SKIP: kiro-cli settings (AGENT_PLAYBOOK_SKIP_KIRO_CLI=1)"
    elif command -v kiro-cli &>/dev/null; then
        if [ "$DRY_RUN" -eq 1 ]; then
            echo "    DRY: kiro-cli settings --global chat.defaultAgent kiro_default"
        elif kiro-cli settings --global chat.defaultAgent kiro_default; then
            echo "  SET: chat.defaultAgent = kiro_default (global)"
        else
            echo "  WARN: Failed to set chat.defaultAgent" >&2
        fi
    fi

    # --- Kiro IDE ---
    # Kiro IDE reads steering from ~/.kiro/steering/*.md (always-included context)
    # and skills from ~/.kiro/skills/<name>/SKILL.md (activated via / in chat).
    # Steering and plain skills are symlinks on every platform (Windows copy mode was
    # retired 2026-09-20); overlay-bearing skills are generated copies everywhere.
    echo "=== Kiro IDE ==="
    KIRO_STEERING_DIR="$HOME/.kiro/steering"
    KIRO_SKILLS_DIR="$HOME/.kiro/skills"
    act mkdir -p "$KIRO_STEERING_DIR" "$KIRO_SKILLS_DIR"

    # Steering is flat: every deployed file sits directly in ~/.kiro/steering/.
    for i in "${!MANIFEST_KINDS[@]}"; do
        [ "${MANIFEST_MODES[$i]}" = "kiro" ] || continue
        dest="$(expand_dest "${MANIFEST_DESTS[$i]}")"
        source="$(expand_source "${MANIFEST_SOURCES[$i]}")"
        link_file "$source" "$dest"
    done

    # Shared skills (with overlay-merge support). Any overlay forces a copy (symlinked
    # dirs can't have a single file overwritten); aux merges run AFTER the whole-dir cp
    # so they overwrite the freshly-copied targets.
    echo "  Shared skills:"
    local skill_dir skill_name overlay_dir skill_overlay
    KIRO_OVERLAY_ROOT="$SCRIPT_DIR/providers/kiro/skills"
    MANAGED_SKILLS=""
    for skill_dir in "$SHARED_DIR/skills"/*/; do
        skill_name="$(basename "$skill_dir")"
        [ -f "$skill_dir/SKILL.md" ] || continue
        overlay_dir="$KIRO_OVERLAY_ROOT/$skill_name"
        skill_overlay="$overlay_dir/OVERLAY.md"
        dest="$KIRO_SKILLS_DIR/$skill_name"
        if has_any_overlay "$overlay_dir"; then
            if [ -L "$dest" ]; then act rm "$dest"; fi
            act rm -rf "$dest"
            act mkdir -p "$dest"
            act cp -R "${skill_dir%/}/." "$dest/"
            # Python bytecode caches are build output, not deployables (verify-deployment skips them too).
            [ "$DRY_RUN" -eq 1 ] || find "$dest" -type d -name __pycache__ -prune -exec rm -rf {} +
            if [ -f "$skill_overlay" ]; then
                if [ -z "$(tr -d '[:space:]' < "$skill_overlay")" ]; then
                    echo "  SKIPPED EMPTY OVERLAY: $skill_name"
                fi
                merge_overlay "$skill_dir/SKILL.md" "$skill_overlay" "$dest/SKILL.md"
                echo "  MERGED: $skill_name (shared + kiro overlay)"
            fi
            # Aux overlays run after the dir copy so they overwrite the copied targets.
            apply_aux_overlays "$overlay_dir" "$dest" "${skill_dir%/}"
        else
            if [ -d "$dest" ] && [ ! -L "$dest" ] && [ ! -f "$dest/SKILL.md" ]; then
                echo "  KEPT: $dest is your own folder; the playbook's $skill_name skill is not linked there"
                continue
            fi
            # a generated copy left by an older overlay, now a plain skill: regenerate as a link
            [ -d "$dest" ] && [ ! -L "$dest" ] && act rm -rf "$dest"
            link_dir "${skill_dir%/}" "$dest"
        fi
        MANAGED_SKILLS="$MANAGED_SKILLS $skill_name"
    done

    # Kiro-specific skills
    local kiro_provider_skills="$SCRIPT_DIR/providers/kiro/skills"
    if [ -d "$kiro_provider_skills" ]; then
        echo "  Kiro-specific skills:"
        for skill_dir in "$kiro_provider_skills"/*/; do
            skill_name="$(basename "$skill_dir")"
            if [ -f "$skill_dir/SKILL.md" ]; then
                # Skip if this dir is a shared-skill overlay (SKILL.md and/or aux overlays)
                # already merged above, rather than a standalone kiro-only skill.
                has_any_overlay "$KIRO_OVERLAY_ROOT/$skill_name" && continue
                link_dir "${skill_dir%/}" "$KIRO_SKILLS_DIR/$skill_name"
                MANAGED_SKILLS="$MANAGED_SKILLS $skill_name"
            fi
        done
    fi

    # A stale playbook skill is a link into this repo that no current skill owns. Any
    # other folder is the user's own (or another pack's) and is never removed.
    echo "  Cleaning stale skills:"
    local entry entry_name
    for entry in "$KIRO_SKILLS_DIR"/*; do
        [ -e "$entry" ] || [ -L "$entry" ] || continue
        entry_name="$(basename "$entry")"
        case " $MANAGED_SKILLS " in *" $entry_name "*) continue ;; esac
        if is_engine_link "$entry"; then
            echo "  REMOVE: $entry (stale)"
            act rm "$entry"
        fi
    done

    # Cleanup stale files from previous deployments: names a previous deployment wrote
    # that the current manifest no longer owns. NEVER list a path the manifest currently
    # deploys (this runs after the steering loop and would delete the fresh link).
    # Entries are dated; drop one once every machine has certainly re-run setup since.
    echo "=== Cleanup stale files ==="
    local stale stale_dir
    for stale in "$KIRO_AGENTS_DIR/kiro_default.json" "$KIRO_STEERING_DIR/claude-code-local-data.md" "$KIRO_STEERING_DIR/v2-only/kiro-cli-local-data.md" "$KIRO_STEERING_DIR/v2-only/memory-sources.md" "$KIRO_STEERING_DIR/v2-only/session-resume-recovery-2.14.0.md" "$KIRO_STEERING_DIR/v3/kiro-cli-local-data.md" "$KIRO_STEERING_DIR/v3/memory-sources.md"; do   # kiro_default.json: 2026-08-18; the rest: 2026-09-20
        if [ -e "$stale" ] || [ -L "$stale" ]; then
            act rm -f "$stale"
            echo "  REMOVED stale: $stale"
        fi
    done
    # Directories: the retired v2-only/ and v3/ steering subdirectories (kiro-cli v2
    # retirement, 2026-09-20). Removed only when empty, so a user-placed file survives.
    for stale_dir in "$KIRO_STEERING_DIR/v2-only" "$KIRO_STEERING_DIR/v3"; do
        if [ -d "$stale_dir" ] && [ -z "$(ls -A "$stale_dir")" ]; then
            act rmdir "$stale_dir"
            echo "  REMOVED stale dir: $stale_dir"
        fi
    done

    echo ""
    echo "=== Verify v3 deployment ==="
    local v3_ok=1
    if [ "$DRY_RUN" -eq 0 ]; then
        [ -f "$KIRO_AGENTS_DIR/kiro_default.md" ] || { echo "  MISSING: $KIRO_AGENTS_DIR/kiro_default.md"; v3_ok=0; }
        [ -f "$KIRO_AGENTS_DIR/qdream_child.md" ] || { echo "  MISSING: $KIRO_AGENTS_DIR/qdream_child.md"; v3_ok=0; }
        [ -f "$KIRO_SETTINGS_DIR/permissions.yaml" ] || { echo "  MISSING: $KIRO_SETTINGS_DIR/permissions.yaml"; v3_ok=0; }
        if [ "$v3_ok" -eq 1 ]; then echo "  OK: v3 agent and permissions deployed"; fi
    fi
}

# --- Uninstall -------------------------------------------------------------

# unlink_engine <path>: remove a link into this repo, then restore <path>.bak if setup made one.
unlink_engine() {
    local p="$1"
    if is_engine_link "$p"; then
        act rm "$p"
        echo "  REMOVED: $p"
        if [ -e "$p.bak" ] || [ -L "$p.bak" ]; then
            act mv "$p.bak" "$p"
            echo "  RESTORED: $p (from $p.bak)"
        fi
    fi
}

unlink_skills() {
    local dir="$1" e
    [ -d "$dir" ] || return 0
    for e in "$dir"/*; do unlink_engine "$e"; done
}

uninstall_mode() {
    local mode="$1" i dest source
    for i in "${!MANIFEST_KINDS[@]}"; do
        [ "${MANIFEST_MODES[$i]}" = "$mode" ] || continue
        dest="$(expand_dest "${MANIFEST_DESTS[$i]}")"
        source="$(expand_source "${MANIFEST_SOURCES[$i]}")"
        case "${MANIFEST_KINDS[$i]}" in
            symlink-file|symlink-dir) unlink_engine "$dest" ;;
            template-file)
                if [ -f "$dest" ] && [ "$(render_template "$source")" = "$(cat "$dest")" ]; then
                    act rm "$dest"; echo "  REMOVED: $dest"
                elif [ -e "$dest" ]; then
                    echo "  KEPT: $dest (changed since setup rendered it)"
                fi ;;
            copy-file)
                if [ -f "$dest" ] && cmp -s "$source" "$dest"; then
                    act rm "$dest"; echo "  REMOVED: $dest"
                elif [ -e "$dest" ]; then
                    echo "  KEPT: $dest (changed since setup copied it)"
                fi ;;
            seed-file) [ -e "$dest" ] && echo "  KEPT: $dest (the app owns it; setup only seeded it)" ;;
        esac
    done
}

uninstall() {
    echo "=== Uninstall: ${PROVIDERS// /, } ==="
    if wants claude; then uninstall_mode claude; unlink_skills "$HOME/.claude/skills"; fi
    if wants codex; then uninstall_mode codex; unlink_skills "$HOME/.codex/skills"; fi
    if wants gemini; then uninstall_mode gemini; unlink_skills "$HOME/.gemini/skills"; fi
    if wants kiro; then
        uninstall_mode kiro-always
        uninstall_mode kiro
        local skill_dir name dest
        for skill_dir in "$SHARED_DIR/skills"/*/; do
            name="$(basename "$skill_dir")"
            dest="$HOME/.kiro/skills/$name"
            if has_any_overlay "$SCRIPT_DIR/providers/kiro/skills/$name" && [ -d "$dest" ] && [ ! -L "$dest" ]; then
                act rm -rf "$dest"; echo "  REMOVED: $dest (generated copy)"
            fi
        done
        unlink_skills "$HOME/.kiro/skills"
        command -v kiro-cli >/dev/null 2>&1 && echo "  NOTE: kiro-cli's chat.defaultAgent still names kiro_default; change it with: kiro-cli settings --global chat.defaultAgent <agent>"
    fi
    if [ "$PURGE" -eq 1 ]; then
        [ -L "$SCRIPT_DIR/memory" ] && { act rm "$SCRIPT_DIR/memory"; echo "  REMOVED: $SCRIPT_DIR/memory (link; the store repo is untouched)"; }
        [ -f "$CONFIG_FILE" ] && { act rm "$CONFIG_FILE"; echo "  REMOVED: $CONFIG_FILE"; }
    else
        echo "  KEPT: $CONFIG_FILE, the memory link and the store repo (--purge removes the first two)"
    fi
    echo ""
    echo "Done."
}

# --- Main ------------------------------------------------------------------

read_manifest "$SCRIPT_DIR/inventory.tsv"
[ "$DRY_RUN" -eq 1 ] && echo "  DRY RUN: nothing will be changed"
choose_providers

if [ "$UNINSTALL" -eq 1 ]; then
    uninstall
    exit 0
fi

echo "=== Prerequisites ==="
check_prereqs
echo "=== Python venv ==="
venv_step
echo "=== Store repo ==="
store_step
memory_link_step
echo "=== Engine branch ==="
engine_branch_step
echo "=== Pointer file ==="
write_pointer

for p in $ALL_PROVIDERS; do
    if wants "$p"; then
        "deploy_$p"
    fi
done

echo ""
echo "Done (providers: ${PROVIDERS// /, }). Run '/qconfig-sync' from any agent to verify."
if wants claude; then
    echo "NOTE: statusLine and notification hooks also need manual entries in"
    echo "      ~/.claude/settings.json -- see providers/claude/README.md."
    echo "      '/qconfig-sync' does not check these; it reports OK without them."
fi
