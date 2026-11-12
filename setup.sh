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
# In every mode, your own ~/.claude/CLAUDE.md or ~/.gemini/GEMINI.md stays where it is and
# the playbook loads beside it (see "Co-existence" below); Codex has no such mechanism. For
# Gemini CLI that adds one name to context.fileName in ~/.gemini/settings.json, in every mode
# (--yes and no terminal included), as an agent-run install needs it too.
#
# Kiro overlay merge: for a shared skill dir, kiro discipline deltas live under
# providers/kiro/skills/<name>/ and are APPENDED to the deployed copy at setup time:
#   - SKILL.md overlay : OVERLAY.md          -> appended to the deployed SKILL.md
#   - aux-file overlay  : <stem>.OVERLAY.md  -> appended to the deployed <stem>.md
#     (e.g. memory-rules.OVERLAY.md -> memory-rules.md)
# Any overlay makes the skill a generated copy (a single file inside a symlinked dir
# cannot be overwritten). SKILL.OVERLAY.md is reserved/forbidden (SKILL.md uses the
# bare OVERLAY.md) and an overlay whose target file is absent is skipped with a
# warning. See merge_overlay / aux_overlay_targets / deploy_generated_copy below.
#
# Ownership: every regular file setup writes is recorded in the deploy lock
# (~/.agent-playbook/deploy-lock.tsv, see "Deploy lock" below), seed files excepted. A re-run
# writes only what changed, removes what it wrote once the source is gone, and moves a file you
# edited or own to <path>.bak (one backup per path) before it writes there. A backup that cannot
# be made leaves that path unchanged and ends the run non-zero.

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

Environment: AGENT_PLAYBOOK_STORES (store repo path), AGENT_PLAYBOOK_CONFIG (pointer
file path), AGENT_PLAYBOOK_SKIP_KIRO_CLI=1 (do not change kiro-cli's global settings).
AGENT_PLAYBOOK_TEST_VENV_DIR and AGENT_PLAYBOOK_TEST_GEMINI_HELPER are for test-parity.sh
only (the venv folder to use instead of the repo's .venv-agent-playbook, and a script to run
instead of providers/gemini/context-filename.py).
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

# need_dir <folder>...: make each folder (act mkdir -p). A file already at one of those paths stops
# the run before anything is written there, in a dry run too; setup.ps1's New-DirIfMissing stops
# the same way.
need_dir() {
    local d
    for d in "$@"; do
        if [ -e "$d" ] && [ ! -d "$d" ]; then
            echo "ERROR: $d is a file, not a folder; setup stopped here (move it away, then re-run setup)" >&2
            exit 1
        fi
    done
    # Folders that all exist need no mkdir process (a dry run still prints the line)
    if [ "$DRY_RUN" -eq 0 ]; then
        for d in "$@"; do [ -d "$d" ] || { act mkdir -p "$@"; return; }; done
        return 0
    fi
    act mkdir -p "$@"
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

IS_MSYS=0
case "$(uname -s 2>/dev/null)" in MINGW*|MSYS*|CYGWIN*) IS_MSYS=1 ;; esac

# long_path <path>: native_path, with every 8.3 short name (QSYLVE~1.POL) expanded under Git Bash.
# A part of the path that does not exist is kept as written.
long_path() {
    local p="$1"
    if [ "$IS_MSYS" -eq 0 ]; then printf '%s' "$p"; return; fi
    if [ -e "$p" ] || [ "$(dirname "$p")" = "$p" ]; then
        cygpath -m -l -a "$p"
    else
        printf '%s/%s' "$(long_path "$(dirname "$p")")" "$(basename "$p")"
    fi
}

# canon_path <path>: one spelling per file, for comparing paths: long_path folded to lower case
# under Git Bash (NTFS ignores case), the path itself elsewhere.
canon_path() {
    local p
    if [ "$IS_MSYS" -eq 0 ]; then printf '%s' "$1"; return; fi
    p="$(long_path "$1")"
    printf '%s' "${p,,}"
}

ENGINE_ROOT_CANON=""
[ "$IS_MSYS" -eq 1 ] && ENGINE_ROOT_CANON="$(canon_path "$SCRIPT_DIR")"
ENGINE_ROOT_LONG="$(long_path "$SCRIPT_DIR")"

# is_engine_link <path>: a symlink whose target lies inside this repo. Under Git Bash both sides are
# compared in their long, case-folded form, so a link made through the repo's 8.3 short path (or by
# setup.ps1 with other letter case) is still the playbook's.
is_engine_link() {
    [ -L "$1" ] || return 1
    local t
    t="$(readlink "$1")"
    case "$t" in "$SCRIPT_DIR"/*|"$SCRIPT_DIR") return 0 ;; esac
    [ "$IS_MSYS" -eq 1 ] || return 1
    case "$t" in /*|[A-Za-z]:*) ;; *) t="$(dirname "$1")/$t" ;; esac
    t="$(canon_path "$t")"
    case "$t" in "$ENGINE_ROOT_CANON"/*|"$ENGINE_ROOT_CANON") return 0 ;; *) return 1 ;; esac
}

# same_target <a> <b>: two link targets that name the same path.
same_target() {
    [ "$1" = "$2" ] && return 0
    [ "$IS_MSYS" -eq 1 ] && [ "$(canon_path "$1")" = "$(canon_path "$2")" ]
}

# --- Deploy lock -----------------------------------------------------------
# ~/.agent-playbook/deploy-lock.tsv names the regular files setup wrote, so a re-run can tell its
# own unedited files from yours. Lockstep with setup.ps1 (both write the same bytes on one machine:
# the template tokens render in the same C:/... form) and verify-deployment.py (which reads it for
# ORPHAN and user-folder-kept lines). Format: UTF-8, LF, no BOM.
#   line 1 : LOCK_HEADER below (it carries the format version)
#   rows   : kind<TAB>path<TAB>value, sorted by byte order, one per path and kind class
#   kind   : copy-dir-recursive (a plain file of a generated Kiro copy), merge-file (a merged file
#            of one), copy-file, template-file (the manifest rows), backup (a .bak setup made),
#            setting (a setting setup changed: the kiro-cli default agent, or the name setup added
#            to Gemini CLI's context.fileName)
#   path   : the destination, home written as ~/, forward slashes; setting: kiro-cli/chat.defaultAgent
#            or gemini/context.fileName
#   value  : sha256, lowercase hex, of the bytes setup wrote; backup: of the .bak (- for a folder
#            or a link); setting: the value setup replaced, as compact JSON (- if none; for
#            context.fileName, + when there was no settings.json and setup created it)
# The lock is untrusted input: a missing file, another first line or one malformed row means no
# lock at all (the first-run case), and only ~/ paths with no .. segment, no backslash and no colon
# are accepted (setup never writes another key). An unreadable lock is moved to deploy-lock.tsv.bak
# before the new one is written.
# Journal: each backup row is also appended to deploy-lock.journal.tsv the moment the .bak exists,
# and the context.fileName setting row the moment settings.json is edited, so a run that stops
# half-way loses neither; the next run (or uninstall) merges it, and the lock write deletes it.
#
# Ownership rule (own_rule, the one decision for every file setup writes; seed files are the one
# exception: written only when absent, never locked, never replaced):
#   no regular file at the path          -> write
#   its bytes equal what setup writes now -> keep (no rewrite), and record it
#   locked, and unchanged since setup     -> replace
#   anything else (edited, or not setup's)-> move it to <path>.bak (one backup; the next replaces it),
#                                            then write
# A <path>.bak that the lock does not show setup made (or, for a file, one changed since) is yours:
# setup leaves it and <path> untouched and says so. A move that fails leaves the path unchanged too,
# prints an ERROR, and the run ends non-zero.
LOCK_HEADER="# agent-playbook deploy lock v1 (written by setup; kind<TAB>path<TAB>sha256)"
LOCK_FILE="$HOME/.agent-playbook/deploy-lock.tsv"
LOCK_JOURNAL="$HOME/.agent-playbook/deploy-lock.journal.tsv"
LOCK_READABLE=0
LOCK_UNREADABLE=0
BACKUP_FAILED=0
LOCK_SETTING_KEY="kiro-cli/chat.defaultAgent"
LOCK_GEMINI_KEY="gemini/context.fileName"
LOCK_WORK=""
OWN_RULE_AWK='function own_rule(want, cur, lk) {
    if (cur == "-") return "write"
    if (cur == want) return "keep"
    if (lk != "-" && cur == lk) return "replace"
    return "backup"
}'

if command -v sha256sum >/dev/null 2>&1; then SHA_CMD=(sha256sum); else SHA_CMD=(shasum -a 256); fi

# sha_of <file>: lowercase hex sha256 of the file's bytes.
sha_of() {
    "${SHA_CMD[@]}" < "$1" | cut -c1-64
}

# sha_list <NUL-separated path list file>: hash<TAB>path per file, one hasher run for the whole list.
# With GNU sha256sum, -z keeps every name as it is (no backslash escaping); elsewhere an escaped
# name loses its leading backslash marker. A name holding a tab or a newline cannot be listed.
if [ "${SHA_CMD[0]}" = sha256sum ] && printf 'x' | sha256sum -z >/dev/null 2>&1; then SHA_Z=1; else SHA_Z=0; fi
sha_list() {
    [ -s "$1" ] || return 0
    if [ "$SHA_Z" -eq 1 ]; then
        xargs -0 sha256sum -z -- < "$1" | tr '\0' '\n' | awk '{ print substr($0, 1, 64) "\t" substr($0, 67) }'
    else
        xargs -0 "${SHA_CMD[@]}" -- < "$1" | awk '{ s = $0; if (substr(s, 1, 1) == "\\") s = substr(s, 2); print substr(s, 1, 64) "\t" substr(s, 67) }'
    fi
}

# lock_key <path>: the lock's spelling of a destination path (~/...), or nothing outside home.
lock_key() {
    case "$1" in
        "$HOME"/*) printf '~/%s' "${1#"$HOME"/}" ;;
        *) printf '' ;;
    esac
}

# LOCK_ROWS_AWK: exit 1 on the first row the lock format does not allow (header excluded).
LOCK_ROWS_AWK='
    NF != 3 { exit 1 }
    $1 == "setting" { if (($2 != skey && $2 != gkey) || $3 == "") exit 1; next }
    $1 !~ /^(copy-dir-recursive|merge-file|copy-file|template-file|backup)$/ { exit 1 }
    substr($2, 1, 2) != "~/" || ("/" $2 "/") ~ /\/\.\.\// || $2 ~ /[\\:]/ { exit 1 }
    $1 == "backup" && $3 == "-" { next }
    $3 !~ /^[0-9a-f]+$/ || length($3) != 64 { exit 1 }
'

# lock_path <key>: the destination path a lock key names.
lock_path() {
    printf '%s/%s' "$HOME" "${1#\~/}"
}

# KEY_PROVIDER_AWK: key_provider(key), the provider a lock row belongs to (none outside them).
KEY_PROVIDER_AWK='function key_provider(k) {
    if (index(k, "~/.kiro/") == 1 || k == "'"$LOCK_SETTING_KEY"'") return "kiro"
    if (index(k, "~/.claude/") == 1) return "claude"
    if (index(k, "~/.codex/") == 1) return "codex"
    if (index(k, "~/.gemini/") == 1 || k == "'"$LOCK_GEMINI_KEY"'") return "gemini"
    return "none"
}'

# lock_load: read the previous lock into $LOCK_WORK/old (rows only), or leave it empty.
lock_load() {
    LOCK_WORK="$(mktemp -d 2>/dev/null || echo "${TMPDIR:-/tmp}/apb-lock-$$")"
    mkdir -p "$LOCK_WORK"
    : > "$LOCK_WORK/old"
    : > "$LOCK_WORK/new"
    : > "$LOCK_WORK/held"
    # every destination the manifest names now: never retired, whatever an old row says
    local i
    for i in "${!MANIFEST_DESTS[@]}"; do lock_key "$(expand_dest "${MANIFEST_DESTS[$i]}")"; echo; done > "$LOCK_WORK/mkeys"
    # a folder (or anything not a file) at the lock or journal path: stop before any change, since
    # the lock could not be written at the end (setup.ps1's Read-DeployLock stops the same way)
    for i in "$LOCK_FILE" "$LOCK_JOURNAL"; do
        if { [ -e "$i" ] || [ -L "$i" ]; } && { [ -L "$i" ] || [ ! -f "$i" ]; }; then
            echo "ERROR: $i is not a file; setup stopped before any change (move it away, then re-run setup)" >&2
            exit 1
        fi
    done
    if [ -f "$LOCK_FILE" ]; then
        if awk -F'\t' -v header="$LOCK_HEADER" -v skey="$LOCK_SETTING_KEY" -v gkey="$LOCK_GEMINI_KEY" '
            NR == 1 { if ($0 != header) exit 1; next }'"$LOCK_ROWS_AWK" "$LOCK_FILE"; then
            LOCK_READABLE=1
            tail -n +2 "$LOCK_FILE" > "$LOCK_WORK/old"
        else
            LOCK_UNREADABLE=1
            echo "  NOTE: $LOCK_FILE is not a deploy lock this setup can read; treating this as a first run (it is kept as $LOCK_FILE.bak)"
        fi
    fi
    # backup and context.fileName rows of a run that stopped before writing its lock: newer than the
    # lock's own rows
    if [ -f "$LOCK_JOURNAL" ]; then
        if awk -F'\t' -v skey="$LOCK_SETTING_KEY" -v gkey="$LOCK_GEMINI_KEY" '
            $1 != "backup" && !($1 == "setting" && $2 == gkey) { exit 1 }'"$LOCK_ROWS_AWK" "$LOCK_JOURNAL"; then
            cat "$LOCK_JOURNAL" "$LOCK_WORK/old" > "$LOCK_WORK/old.j"
            mv "$LOCK_WORK/old.j" "$LOCK_WORK/old"
            echo "  NOTE: merged the rows an interrupted run recorded in $LOCK_JOURNAL"
        else
            echo "  NOTE: $LOCK_JOURNAL is not a journal this setup can read; ignored"
        fi
    fi
}

# lock_add <kind> <key> <value>: record a row for the lock this run writes. A path outside home has
# no lock spelling: it is not recorded.
lock_add() {
    if [ "$1" != setting ]; then
        case "$2" in
            "~/"*) case "$2" in *\\*|*:*) echo "  NOTE: $2 is not recorded in the deploy lock (its name holds \\ or :)"; return 0 ;; esac ;;
            *) echo "  NOTE: a path outside $HOME is not recorded in the deploy lock"; return 0 ;;
        esac
    fi
    printf '%s\t%s\t%s\n' "$1" "$2" "$3" >> "$LOCK_WORK/new"
}

# lock_get <kind> <key>: the previous lock's value for that row, or nothing.
lock_get() {
    awk -F'\t' -v k="$1" -v p="$2" '$1 == k && $2 == p { print $3; exit }' "$LOCK_WORK/old"
}

# lock_finish <rows to keep from the previous lock> [drop-empty]: write the new lock when its bytes
# differ. New rows win over old rows for the same path and kind class (backup, setting, or a file
# kind). With drop-empty (uninstall), a lock left with no row is deleted.
lock_finish() {
    local carry="$1" out="$LOCK_WORK/lock.tsv"
    [ "$DRY_RUN" -eq 1 ] && return 0
    awk -F'\t' '
        function cls(k) { return (k == "backup" || k == "setting") ? k : "file" }
        { key = cls($1) SUBSEP $2; if (key in seen) next; seen[key] = 1; print }
    ' "$LOCK_WORK/new" "$carry" | LC_ALL=C sort > "$LOCK_WORK/rows"
    if [ "$LOCK_UNREADABLE" -eq 1 ] && [ -f "$LOCK_FILE" ]; then
        mv -f "$LOCK_FILE" "$LOCK_FILE.bak"
        echo "  BACKUP: $LOCK_FILE -> $LOCK_FILE.bak (a deploy lock this setup cannot read)"
    fi
    if [ ! -s "$LOCK_WORK/rows" ]; then
        if [ "${2:-}" = drop-empty ] && [ -f "$LOCK_FILE" ]; then
            rm -f "$LOCK_FILE" "$LOCK_JOURNAL"
            echo "  REMOVED: $LOCK_FILE"
            return 0
        fi
        if [ ! -f "$LOCK_FILE" ]; then rm -f "$LOCK_JOURNAL"; return 0; fi
    fi
    { printf '%s\n' "$LOCK_HEADER"; cat "$LOCK_WORK/rows"; } > "$out"
    if [ -f "$LOCK_FILE" ] && cmp -s "$out" "$LOCK_FILE"; then rm -f "$LOCK_JOURNAL"; echo "  OK: $LOCK_FILE"; return 0; fi
    mkdir -p "$(dirname "$LOCK_FILE")"
    if ! { cp "$out" "$LOCK_FILE.tmp-$$" && mv -f "$LOCK_FILE.tmp-$$" "$LOCK_FILE"; }; then
        rm -f "$LOCK_FILE.tmp-$$"
        echo "ERROR: could not write $LOCK_FILE; the next run reads its rows from $LOCK_JOURNAL" >&2
        exit 1
    fi
    rm -f "$LOCK_JOURNAL"
    echo "  WROTE: $LOCK_FILE"
}

# lock_carry_rows <file>: the previous lock's rows this run keeps: rows of a provider not deployed
# now, and backup rows whose .bak is still there.
lock_carry_rows() {
    local kind key val p
    awk -F'\t' -v deployed=" $PROVIDERS " "$KEY_PROVIDER_AWK"'
        $1 != "backup" && index(deployed, " " key_provider($2) " ") == 0' "$LOCK_WORK/old" > "$1"
    while IFS=$'\t' read -r kind key val; do
        [ "$kind" = backup ] || continue
        p="$HOME/${key#\~/}"
        # a .bak reached through a linked folder is not looked at (it may lie outside the deployment)
        if no_link_parent "$p" "$HOME" && { [ -e "$p.bak" ] || [ -L "$p.bak" ]; }; then printf '%s\t%s\t%s\n' "$kind" "$key" "$val" >> "$1"; fi
    done < "$LOCK_WORK/old"
}

# no_link_parent <path> <top>: no folder between top (exclusive) and path is a link, so a write or
# delete at path cannot land outside the deployment.
no_link_parent() {
    local d="${1%/*}"
    while [ "$d" != "$2" ] && [ "${#d}" -gt "${#2}" ]; do
        [ -L "$d" ] && return 1
        d="${d%/*}"
    done
    return 0
}

# locked_files_present <rows file> <scan root> <out>: the NUL-separated paths of the rows' files that
# are regular files now. find never follows a link, so a path reached through a linked folder is
# never listed (and so never removed).
locked_files_present() {
    : > "$3"
    [ -d "$2" ] || return 0
    find "$2" -type f -print 2>/dev/null > "$3.found" || true
    # under Git Bash a row matches its file whatever the letter case (NTFS ignores it)
    awk -F'\t' -v found="$3.found" -v home="$HOME" -v fold="$IS_MSYS" '
        function k(s) { return fold ? tolower(s) : s }
        FILENAME == found { f[k($0)] = $0; next }
        { p = k(home "/" substr($2, 3)); if (p in f) print f[p] }
    ' "$3.found" "$1" | tr '\n' '\0' > "$3"
}

# remove_listed <NUL-separated path list file>: remove those files in one process, then the empty
# folders inside each Kiro skill folder they were in (and that folder, once empty).
remove_listed() {
    local d
    [ -s "$1" ] || return 0
    if [ "$DRY_RUN" -eq 1 ]; then
        tr '\0' '\n' < "$1" | sed 's/^/    DRY: rm /'
        return 0
    fi
    xargs -0 rm -f -- < "$1"
    tr '\0' '\n' < "$1" | awk -v top="$HOME/.kiro/skills/" 'index($0, top) == 1 {
        rest = substr($0, length(top) + 1); n = index(rest, "/"); if (n > 1) print substr(rest, 1, n - 1) }' \
        | LC_ALL=C sort -u > "$1.dirs"
    while IFS= read -r d; do
        [ -d "$HOME/.kiro/skills/$d" ] && [ ! -L "$HOME/.kiro/skills/$d" ] || continue
        find "$HOME/.kiro/skills/$d" -type d -empty -delete 2>/dev/null || true
    done < "$1.dirs"
}

# backup_path <path>: move a file, folder or link that is not setup's to <path>.bak, the single
# bounded backup, and record the backup in the lock and its journal at once. An existing <path>.bak
# is replaced only when the lock shows setup made it (and, for a file, that it is unchanged since);
# otherwise it is yours: nothing moves, a WARN says what to do, and it returns 2. A move that fails
# puts the older .bak back, prints an ERROR (the run then ends non-zero) and returns 1. On any
# non-zero return the caller skips its write and the lock row for that path.
backup_path() {
    local p="$1" h="-" key old aside=""
    key="$(lock_key "$p")"
    if [ -f "$p" ] && [ ! -L "$p" ]; then h="$(sha_of "$p")"; fi
    if [ -e "${p}.bak" ] || [ -L "${p}.bak" ]; then
        old="$(lock_get backup "$key")"
        if [ -z "$old" ] || { [ "$old" != "-" ] && { [ -L "${p}.bak" ] || [ ! -f "${p}.bak" ] || [ "$(sha_of "${p}.bak")" != "$old" ]; }; }; then
            echo "  WARN: ${p}.bak is not a backup setup made, so $p is left unchanged; move ${p}.bak away, then re-run setup"
            printf '%s\n' "$key" >> "$LOCK_WORK/held"
            return 2
        fi
    fi
    echo "  BACKUP: $p -> ${p}.bak"
    if [ "$DRY_RUN" -eq 1 ]; then
        echo "    DRY: mv $p ${p}.bak"
        lock_add backup "$key" "$h"
        return 0
    fi
    if [ -e "${p}.bak" ] || [ -L "${p}.bak" ]; then
        aside="${p}.bak.tmp-$$"
        mv "${p}.bak" "$aside" 2>/dev/null || aside="!"
    fi
    if [ "$aside" = "!" ] || ! mv "$p" "${p}.bak" 2>/dev/null; then
        case "$aside" in ""|"!") ;; *) mv "$aside" "${p}.bak" 2>/dev/null || true ;; esac
        echo "ERROR: could not back up $p; left unchanged" >&2
        BACKUP_FAILED=$((BACKUP_FAILED + 1))
        printf '%s\n' "$key" >> "$LOCK_WORK/held"
        return 1
    fi
    case "$aside" in "") ;; *) rm -rf "$aside" ;; esac
    lock_add backup "$key" "$h"
    case "$key" in
        "~/"*) mkdir -p "$(dirname "$LOCK_JOURNAL")"; printf 'backup\t%s\t%s\n' "$key" "$h" >> "$LOCK_JOURNAL" ;;
    esac
    return 0
}

# own_write <kind> <dest> <file holding the bytes to write>: a copy-file or template-file row
# under the ownership rule. A link at dest is removed when it points into this repo (the layout
# before copies), else backed up.
own_write() {
    local kind="$1" dest="$2" src="$3" key exp cur="-" lk action
    key="$(lock_key "$dest")"
    if [ -L "$dest" ]; then
        if is_engine_link "$dest"; then
            echo "  REMOVE SYMLINK: $dest"
            act rm "$dest"
        else
            backup_path "$dest" || return 0
        fi
    elif [ -d "$dest" ]; then
        backup_path "$dest" || return 0
    fi
    exp="$(sha_of "$src")"
    if [ -f "$dest" ] && [ ! -L "$dest" ]; then cur="$(sha_of "$dest")"; fi
    lk="$(lock_get "$kind" "$key")"
    action="$(printf '%s\t%s\t%s\n' "$exp" "$cur" "${lk:--}" | awk -F'\t' "$OWN_RULE_AWK"'{ print own_rule($1, $2, $3) }')"
    case "$action" in
        keep) echo "  OK: $dest (matches source)" ;;
        backup) backup_path "$dest" || return 0
                act cp "$src" "$dest"; echo "  WROTE: $dest (yours kept as ${dest}.bak)" ;;
        *) act cp "$src" "$dest"; echo "  WROTE: $dest" ;;
    esac
    lock_add "$kind" "$key" "$exp"
}

# lock_retire <key prefix>: rows of the previous lock under the prefix that this run did not record
# (their source is gone). A row for a current manifest destination, or for a path this run had to
# leave alone, is never retired; under Git Bash a key that differs from a recorded one only in letter
# case is the same file. Each file is removed when unchanged since setup wrote it, else backed up;
# then the empty folders above it are removed, up to the Kiro skills folder.
lock_retire() {
    local prefix="$1" w="$LOCK_WORK/retire" kind key val p h
    awk -F'\t' -v pre="$prefix" -v newf="$LOCK_WORK/new" -v heldf="$LOCK_WORK/held" -v mkf="$LOCK_WORK/mkeys" -v fold="$IS_MSYS" '
        function k(s) { return fold ? tolower(s) : s }
        FILENAME == newf { if ($1 != "backup" && $1 != "setting") rec[k($2)] = 1; next }
        FILENAME == heldf || FILENAME == mkf { if ($0 != "") rec[k($0)] = 1; next }
        $1 == "backup" || $1 == "setting" || index($2, pre) != 1 || (k($2) in rec) || ($2 in seen) { next }
        { seen[$2] = 1; print }
    ' "$LOCK_WORK/new" "$LOCK_WORK/held" "$LOCK_WORK/mkeys" "$LOCK_WORK/old" > "$w"
    [ -s "$w" ] || return 0
    p="$HOME/${prefix#\~/}"
    locked_files_present "$w" "${p%/}" "$w.lst"
    sha_list "$w.lst" > "$w.h"
    # current hash<TAB>locked hash<TAB>path, for the files still there
    awk -F'\t' -v hf="$w.h" -v home="$HOME" -v fold="$IS_MSYS" '
        function k(s) { return fold ? tolower(s) : s }
        FILENAME == hf { h[k($2)] = $1; real[k($2)] = $2; next }
        { p = k(home "/" substr($2, 3)); if (p in h) print h[p] "\t" $3 "\t" real[p] }
    ' "$w.h" "$w" > "$w.plan"
    : > "$w.rm"
    while IFS=$'\t' read -r h val p; do
        if [ "$h" = "$val" ]; then
            printf '%s\0' "$p" >> "$w.rm"
            echo "  REMOVED: $p (its source is gone)"
        else
            echo "  NOTE: $p changed since setup wrote it and its source is gone"
            backup_path "$p" || true
        fi
    done < "$w.plan"
    remove_listed "$w.rm"
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
        local col_count tabs
        tabs="${line//[!$'\t']/}"   # awk -F'\t' NF without a process: the tabs plus one
        col_count=$(( ${#tabs} + 1 ))
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
# Token values: {{USER_HOME}} is home in native_path form and {{PLAYBOOK_ROOT}} the repo root in
# long_path form, so under Git Bash both read C:/Users/... exactly as setup.ps1 writes them (the
# two twins write the same bytes, and a run through the repo's 8.3 short path renders the same).
# No backslash escaping: forward slashes are valid in every consumer (JSON, file:// URIs,
# markdown) and need none. The cross-shell contract is checked by test-parity.sh's
# render-equivalence assertion and by its deploy-lock comparison of the two twins.
render_template() {
    local src="$1"
    local body home root
    body="$(cat "$src")"
    home="$(native_path "$HOME")"
    root="$ENGINE_ROOT_LONG"
    body="${body//\{\{USER_HOME\}\}/${home//\\//}}"
    body="${body//\{\{PLAYBOOK_ROOT\}\}/${root//\\//}}"
    printf '%s\n' "$body"
}

# copy_template <template> <dest>: render into the lock's work folder, then write it under the
# ownership rule (own_write).
TEMPLATE_N=0
copy_template() {
    local src="$1" dest="$2" staged
    TEMPLATE_N=$((TEMPLATE_N + 1))
    staged="$LOCK_WORK/template-$TEMPLATE_N"
    render_template "$src" > "$staged"
    own_write template-file "$dest" "$staged"
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

# make_way <path>: a file, folder or link of the user's (a link that does not point into this
# repo) sits where a link goes. Returns 0 when the path is free afterwards (backed up to .bak),
# 1 to skip it. Only an interactive run asks; --yes and a run with no terminal back up and replace.
make_way() {
    local p="$1"
    if [ "$INTERACTIVE" -eq 1 ]; then
        echo "  $p exists and is not a playbook link."
        if ! ask "Back it up to ${p}.bak and replace it with the playbook's?" y; then
            echo "  SKIPPED: $p (kept as is)"
            return 1
        fi
    fi
    backup_path "$p" || return 1
    return 0
}

# link_way <path>: before a link is made at path. 0 when the path is free (an outdated link into
# this repo removed, anything else backed up), 1 to skip it, 2 when the right link is already there.
link_way() {
    local p="$1" target="$2" cur
    if [ -L "$p" ]; then
        cur="$(readlink "$p")"
        if same_target "$cur" "$target"; then
            echo "  OK: $p -> $target"
            return 2
        fi
        if is_engine_link "$p"; then
            echo "  UPDATE: $p (was -> $cur)"
            act rm "$p"
            return 0
        fi
        make_way "$p" || return 1
    elif [ -e "$p" ]; then
        make_way "$p" || return 1
    fi
    return 0
}

# link_file / link_dir <target in this repo> <link to create>
link_file() {
    local target="$1" link="$2" rc=0
    link_way "$link" "$target" || rc=$?
    [ "$rc" -eq 0 ] || return 0
    act ln -s "$target" "$link"
    echo "  LINKED: $link -> $target"
}

link_dir() {
    link_file "$@"
}

# list_shared_skills: the shared skill names, one per line. .trash / synced / .bucket-*
# are the Claude Code app's own skill-sync cache (it writes beside the skills it finds),
# never a playbook skill.
list_shared_skills() {
    local d n
    for d in "$SHARED_DIR/skills"/*/; do
        [ -d "$d" ] || continue
        n="${d%/}"; n="${n##*/}"   # basename, without a process: this runs once per skill per provider
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
    need_dir "$dir"
    while IFS= read -r name; do
        dest="$dir/$name"
        if [ -e "$dest" ] && [ ! -L "$dest" ]; then
            echo "  KEPT: $dest is your own folder; the playbook's $name skill is not linked there (rename or remove it, then re-run setup, to get the playbook's)"
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

# --- Co-existence with your own instruction file ------------------------------
# A file of yours at a client's global instruction path stays where it is, and the playbook loads
# beside it through the client's own side-by-side mechanism:
#   Claude Code: ~/.claude/rules/agent-playbook.md links to shared/AGENTS.md (Claude Code 2.1.322 loads
#                every ~/.claude/rules/*.md whole, links included; measured 2026-11-12).
#   Gemini CLI : ~/.gemini/AGENT-PLAYBOOK.md links to shared/AGENTS.md, and its name joins
#                context.fileName in ~/.gemini/settings.json. Source-read, not runtime-verified: Gemini
#                CLI 0.28.2 config.js:312 and memoryDiscovery.js:93-100 (read 2026-11-12).
#                providers/gemini/context-filename.py makes the edit, in every mode; the deploy lock
#                records it as a setting row (journalled at once). Your GEMINI.md is never backed up or
#                replaced: when the helper cannot edit settings.json (comments in it, which Gemini CLI
#                accepts; no venv; a dangling link; a failed write), the side link is still made, no
#                setting row is written, and a NOTE gives the line to add by hand.
#   Codex      : no side-by-side mechanism; your file gets the single .bak, then the link, and setup
#                says so.
# A file of yours: a regular file, or a link that points outside this repo to a file (your dotfiles),
# that the deploy lock does not name and whose bytes differ from shared/AGENTS.md (a byte copy is a
# copy left where a link could not be made). An older copy of shared/AGENTS.md has other bytes, so it
# counts as yours and is kept: setup cannot tell it from a file you wrote. verify-deployment.py's
# is_user_file is the same rule.
# An empty path or a link into this repo is linked as before; once the instruction file is that link,
# the co-existence link and the context.fileName entry setup added are removed, so the playbook never
# loads twice. Existing installs need no migration.
CLAUDE_SIDE_LINK="$HOME/.claude/rules/agent-playbook.md"
GEMINI_SIDE_NAME="AGENT-PLAYBOOK.md"
GEMINI_SIDE_LINK="$HOME/.gemini/$GEMINI_SIDE_NAME"
GEMINI_SETTINGS="$HOME/.gemini/settings.json"

# user_instruction_file <dest> <source>: dest is a file of your own (the rule above).
user_instruction_file() {
    [ -f "$1" ] || return 1
    if [ -L "$1" ] && is_engine_link "$1"; then return 1; fi
    [ -z "$(awk -F'\t' -v k="$(lock_key "$1")" '$2 == k && $1 != "backup" && $1 != "setting"' "$LOCK_WORK/old")" ] || return 1
    ! cmp -s "$1" "$2"
}

# drop_side_link <path>: remove a co-existence link into this repo (the instruction file is the link now).
drop_side_link() {
    if is_engine_link "$1"; then
        echo "  REMOVE: $1 (the playbook loads through the instruction file itself now)"
        act rm "$1"
    fi
}

# gemini_context <add|remove> [prior]: providers/gemini/context-filename.py on ~/.gemini/settings.json;
# prints its one line, or "unreadable <why>" when it cannot run. An exit other than the helper's own
# 0 and 3 is a crash: its output is never read as a reason.
gemini_context() {
    local py args out rc=0 helper
    # AGENT_PLAYBOOK_TEST_GEMINI_HELPER: test-parity.sh's seam for a helper that crashes
    helper="${AGENT_PLAYBOOK_TEST_GEMINI_HELPER:-$SCRIPT_DIR/providers/gemini/context-filename.py}"
    py="$(venv_python)"
    if [ ! -x "$py" ]; then echo "unreadable there is no playbook venv to edit it with"; return 0; fi
    args=("$1" --settings "$(native_path "$GEMINI_SETTINGS")" --name "$GEMINI_SIDE_NAME")
    [ "$DRY_RUN" -eq 1 ] && args+=(--dry-run)
    # the prior value travels in the environment, as in setup.ps1 (see the helper's docstring)
    out="$(CONTEXT_FILENAME_PRIOR="${2:-}" "$py" -I "$helper" "${args[@]}" 2>/dev/null)" || rc=$?
    case "$rc" in
        0|3) printf '%s\n' "$out" | head -n 1 | tr -d '\r' ;;
        *) echo "unreadable the helper failed (exit $rc)" ;;
    esac
}

# gemini_journal <prior>: the setting row, in the lock journal the moment settings.json is edited.
gemini_journal() {
    [ "$DRY_RUN" -eq 1 ] && return 0
    mkdir -p "$(dirname "$LOCK_JOURNAL")"
    printf 'setting\t%s\t%s\n' "$LOCK_GEMINI_KEY" "$1" >> "$LOCK_JOURNAL"
}

# gemini_unset <prior>: take the name setup added out of context.fileName again; the lock row stays
# when that cannot be done.
gemini_unset() {
    local res
    res="$(gemini_context remove "$1")"
    case "$res" in
        removed)
            if [ "$DRY_RUN" -eq 1 ]; then echo "    DRY: remove $GEMINI_SIDE_NAME from context.fileName in $GEMINI_SETTINGS"
            else
                echo "  REMOVED: $GEMINI_SIDE_NAME from context.fileName in $GEMINI_SETTINGS"
                [ -e "$GEMINI_SETTINGS" ] || echo "  REMOVED: $GEMINI_SETTINGS (setup created it)"
            fi ;;
        absent) ;;
        *) echo "  NOTE: $GEMINI_SETTINGS cannot be edited (${res#unreadable }); remove $GEMINI_SIDE_NAME from its context.fileName by hand"
           lock_add setting "$LOCK_GEMINI_KEY" "$1" ;;
    esac
}

claude_instructions() {
    local source="$1" dest="$2"
    if user_instruction_file "$dest" "$source"; then
        echo "  KEPT: $dest is your own file; the playbook loads beside it from $CLAUDE_SIDE_LINK (Claude Code reads every ~/.claude/rules/*.md)"
        need_dir "$(dirname "$CLAUDE_SIDE_LINK")"
        link_file "$source" "$CLAUDE_SIDE_LINK"
        return 0
    fi
    link_file "$source" "$dest"
    if [ "$DRY_RUN" -eq 1 ] || is_engine_link "$dest"; then drop_side_link "$CLAUDE_SIDE_LINK"; fi
}

gemini_instructions() {
    local source="$1" dest="$2" old res
    old="$(lock_get setting "$LOCK_GEMINI_KEY")"
    if user_instruction_file "$dest" "$source"; then
        if [ "$DRY_RUN" -eq 1 ] && [ ! -x "$(venv_python)" ]; then
            echo "    DRY: the venv is created first; then $GEMINI_SIDE_NAME is added to context.fileName of $GEMINI_SETTINGS"
        else
            res="$(gemini_context add)"
            case "$res" in
                present) [ -z "$old" ] || lock_add setting "$LOCK_GEMINI_KEY" "$old" ;;
                "added "*) lock_add setting "$LOCK_GEMINI_KEY" "${res#added }"
                           gemini_journal "${res#added }"
                           if [ "$DRY_RUN" -eq 1 ]; then echo "    DRY: add $GEMINI_SIDE_NAME to context.fileName of $GEMINI_SETTINGS"
                           else echo "  SET: $GEMINI_SIDE_NAME in context.fileName of $GEMINI_SETTINGS"; fi ;;
                *) echo "  NOTE: $GEMINI_SETTINGS cannot be edited (${res#unreadable }); add \"$GEMINI_SIDE_NAME\" to context.fileName in ~/.gemini/settings.json by hand, or Gemini CLI does not load the playbook"
                   [ -z "$old" ] || lock_add setting "$LOCK_GEMINI_KEY" "$old" ;;
            esac
        fi
        echo "  KEPT: $dest is your own file; the playbook loads beside it from $GEMINI_SIDE_LINK (listed in context.fileName)"
        link_file "$source" "$GEMINI_SIDE_LINK"
        return 0
    fi
    link_file "$source" "$dest"
    if [ "$DRY_RUN" -eq 1 ] || is_engine_link "$dest"; then
        drop_side_link "$GEMINI_SIDE_LINK"
        [ -z "$old" ] || gemini_unset "$old"
    elif [ -n "$old" ]; then
        lock_add setting "$LOCK_GEMINI_KEY" "$old"
    fi
}

codex_instructions() {
    local source="$1" dest="$2" mine=0
    if user_instruction_file "$dest" "$source"; then mine=1; fi
    link_file "$source" "$dest"
    if [ "$mine" -eq 1 ] && { [ "$DRY_RUN" -eq 1 ] || is_engine_link "$dest"; }; then
        echo "  NOTE: Codex has no way to load a second global instructions file, so yours cannot stay beside the playbook's: it is kept as ${dest}.bak"
    fi
}

# deploy_instruction_file <manifest dest> <source> <dest>: 1 when the row is no client's instruction file.
deploy_instruction_file() {
    case "$1" in
        "~/.claude/CLAUDE.md") claude_instructions "$2" "$3" ;;
        "~/.gemini/GEMINI.md") gemini_instructions "$2" "$3" ;;
        "~/.codex/AGENTS.md") codex_instructions "$2" "$3" ;;
        *) return 1 ;;
    esac
    return 0
}

# memory_source_missing <manifest source> <source> <dest>: a row whose source lies in the gitignored
# memory/ (user memory, behind the repo's memory link to the store repo) and is not there yet. No
# dangling link is made, and one an earlier run made is removed: setup says so, and a later run links
# it once the store repo holds user memory.
memory_source_missing() {
    case "$1" in memory/*) ;; *) return 1 ;; esac
    [ -e "$2" ] && return 1
    if is_engine_link "$3"; then
        echo "  REMOVE: $3 (dangling: there is no $2)"
        act rm "$3"
    fi
    echo "  NOTE: $3 is not linked yet: there is no $2 (no user memory in the store repo yet)"
    return 0
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
root=$ENGINE_ROOT_LONG
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
    need_dir "$(dirname "$CONFIG_FILE")"
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

# VENV_DIR: AGENT_PLAYBOOK_TEST_VENV_DIR is test-parity.sh's seam for a first run with no venv (a
# fresh folder outside the repo); nothing else sets it.
VENV_DIR="${AGENT_PLAYBOOK_TEST_VENV_DIR:-$SCRIPT_DIR/.venv-agent-playbook}"

# venv_python: the venv's interpreter, looked up at each call (the venv step may just have made it).
venv_python() {
    local vdir="$VENV_DIR"
    if [ -x "$vdir/Scripts/python.exe" ]; then printf '%s' "$vdir/Scripts/python.exe"; else printf '%s' "$vdir/bin/python"; fi
}

venv_step() {
    local vdir="$VENV_DIR" vpy
    vpy="$(venv_python)"
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
    need_dir "$mem"
    for f in "$TEMPLATES_MEMORY"/*; do
        [ -f "$f" ] && act cp "$f" "$mem/"
    done
}

create_store() {
    echo "  CREATE: $STORES (a new local store repo; add a remote and push it to keep it)"
    need_dir "$STORES"
    act git -C "$STORES" init -q
    write_text "$STORES/.gitignore" "user/memory/.dream-journal.jsonl
*/STORE.tmp-*
*/scratch/
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

# The home the OS reports for this user, whatever HOME says (empty when it cannot be told). Git Bash
# asks Windows for the profile folder; elsewhere the passwd entry names it.
real_home() {
    local h=""
    if [ "$IS_MSYS" -eq 1 ]; then
        # CSIDL_PROFILE (40): the profile folder Windows records, whatever HOME and USERPROFILE say
        h="$(cygpath -F 40 2>/dev/null | tr -d '\r')"
    elif command -v getent >/dev/null 2>&1; then
        h="$(getent passwd "$(id -un)" 2>/dev/null | cut -d: -f6)"
    elif command -v dscl >/dev/null 2>&1; then
        h="$(dscl . -read "/Users/$(id -un)" NFSHomeDirectory 2>/dev/null | awk '{print $2}')"
    fi
    printf '%s' "$h"
}

# True when HOME is not the user's real home (a test probe's temp dir), or the real home cannot be
# told. The repo's memory link lives in the shared working copy, so a run that cannot prove it is the
# real user's never writes it.
home_is_sandboxed() {
    local real; real="$(real_home)"
    [ -n "$real" ] || return 0
    local a b; a="$(long_path "$(native_path "$HOME")")"; b="$(long_path "$(native_path "$real")")"
    [ "$(printf '%s' "${a%/}" | tr 'A-Z' 'a-z')" != "$(printf '%s' "${b%/}" | tr 'A-Z' 'a-z')" ]
}

memory_link_step() {
    local link="$SCRIPT_DIR/memory" target="$STORES/user/memory"
    if home_is_sandboxed; then
        echo "  SKIPPED: $link (HOME is sandboxed; the repo's memory link is never written from a sandbox)"
        return
    fi
    if [ -L "$link" ]; then
        # compare one spelling per file: readlink gives /c/... where STORES may say C:/...
        if [ "$(canon_path "$(readlink "$link")")" = "$(canon_path "$target")" ]; then
            echo "  OK: $link -> $target"
            return
        fi
        if [ "$INTERACTIVE" -eq 0 ] && [ "$YES" -eq 0 ]; then
            # never repoint the repo's link unasked: a sandboxed run (test-parity) would aim it at a
            # store that is deleted afterwards
            echo "  NOTE: $link points to $(readlink "$link"), not $target; re-run with --yes or interactively to repoint it"
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
    if [ -n "$(git --no-optional-locks -C "$SCRIPT_DIR" status --porcelain --untracked-files=no)" ]; then
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
# printf re-adds exactly the separators above. out_file is a staging file in the lock's work
# folder (also under --dry-run); deploy_generated_copy copies it into place.
# File text is read with "$(<file)", the command substitution "$(cat file)" was, without starting
# cat: the same trailing-newline handling, about 6 ms where cat took 78 under Git Bash. The read
# builtin is no substitute there: it reads one byte per system call (210 ms on a 70 KB SKILL.md).

# has_non_space <text>: true when the text holds a character that is not white space
# (the test [ -n "$(printf '%s' "$text" | tr -d '[:space:]')" ], without a process).
has_non_space() {
    [[ "$1" == *[![:space:]]* ]]
}

merge_overlay() {
    local shared_file="$1" overlay_file="$2" out_file="$3"
    local shared_body overlay_body
    shared_body="$(<"$shared_file")"
    overlay_body="$(<"$overlay_file")"
    if has_non_space "$overlay_body"; then
        printf '%s\n\n%s\n' "$shared_body" "$overlay_body" > "$out_file"
    else
        printf '%s\n' "$shared_body" > "$out_file"
    fi
}

# aux_overlay_targets <overlay_dir> <src_dir>: "<target><TAB><overlay>" for every
# <overlay_dir>/<stem>.OVERLAY.md (except the reserved SKILL.OVERLAY.md), whose overlay is
# appended to the deployed markdown target <stem>.md. Naming convention matches the consumers
# (e.g. memory-rules.OVERLAY.md -> memory-rules.md, RESEARCH_CONFIG_TEMPLATE.OVERLAY.md ->
# RESEARCH_CONFIG_TEMPLATE.md). SKILL.OVERLAY.md is rejected (SKILL.md uses the bare
# OVERLAY.md -- never two paths to one target). An overlay whose target file is absent is
# skipped with a warning (an overlay never creates a file alone).
aux_overlay_targets() {
    local overlay_dir="$1" src_dir="$2" ov ov_name target_name
    [ -d "$overlay_dir" ] || return 0
    for ov in "$overlay_dir"/*.OVERLAY.md; do
        [ -f "$ov" ] || continue   # no matches -> literal glob, skip
        ov_name="${ov##*/}"
        [ "$ov_name" = "OVERLAY.md" ] && continue   # SKILL.md overlay, handled separately
        if [ "$ov_name" = "SKILL.OVERLAY.md" ]; then
            echo "  SKIPPED RESERVED: $ov (SKILL.md uses bare OVERLAY.md; SKILL.OVERLAY.md is forbidden)" >&2
            continue
        fi
        target_name="${ov_name%.OVERLAY.md}.md"
        if [ ! -f "$src_dir/$target_name" ]; then
            echo "  SKIPPED AUX OVERLAY: $ov (no shared target '$target_name')" >&2
            continue
        fi
        printf '%s\t%s\n' "$target_name" "$ov"
    done
}

# gen_expected <skill dir> <overlay dir> <name> <work folder>: the files a generated copy holds, as
# <work>/exp (rel<TAB>kind<TAB>file holding the bytes to write) and <work>/exp.h (hash<TAB>file).
gen_expected() {
    local src_dir="$1" overlay_dir="$2" name="$3" w="$4" t ov
    mkdir -p "$w/merge"
    # Never copied: __pycache__ and any fixtures/ folder (selftest data, read only from the repo).
    # Lockstep with setup.ps1 Get-FilesNoFollow and verify-deployment.py COPY_SKIP_DIRS.
    (cd "$src_dir" && find . \( -name __pycache__ -o -type d -name fixtures \) -prune -o -type f -print) | sed 's#^\./##' \
        | awk -v d="$src_dir" '{ print $0 "\tcopy-dir-recursive\t" d "/" $0 }' > "$w/plain"
    : > "$w/merged"
    if [ -f "$overlay_dir/OVERLAY.md" ]; then
        if ! has_non_space "$(<"$overlay_dir/OVERLAY.md")"; then
            echo "  SKIPPED EMPTY OVERLAY: $name"
        fi
        merge_overlay "$src_dir/SKILL.md" "$overlay_dir/OVERLAY.md" "$w/merge/SKILL.md"
        printf '%s\tmerge-file\t%s\n' SKILL.md "$w/merge/SKILL.md" >> "$w/merged"
    fi
    while IFS=$'\t' read -r t ov; do
        merge_overlay "$src_dir/$t" "$ov" "$w/merge/$t"
        printf '%s\tmerge-file\t%s\n' "$t" "$w/merge/$t" >> "$w/merged"
    done < <(aux_overlay_targets "$overlay_dir" "$src_dir")
    awk -F'\t' -v mf="$w/merged" 'FILENAME == mf { m[$1] = 1; print; next } !($1 in m)' \
        "$w/merged" "$w/plain" > "$w/exp"
    cut -f3 "$w/exp" | tr '\n' '\0' > "$w/exp.lst"
    sha_list "$w/exp.lst" > "$w/exp.h"
}

# deploy_generated_copy <skill dir> <dest> <overlay dir> <name>: an overlay-bearing skill as a
# generated copy. Every expected file's bytes are known first (the shared file, or the merge
# staged in the lock's work folder); then only the files that differ are written, each under the
# ownership rule. Files of the copy whose source is gone are left to lock_retire. A folder at dest
# that the lock names no file of is setup's (an older copy: an edited file goes to .bak) when every
# file in it sits at a path setup writes for the skill; any other such folder is yours: it is KEPT.
# Under Git Bash file names match whatever the letter case, as NTFS does.
deploy_generated_copy() {
    local src_dir="$1" dest="$2" overlay_dir="$3" name="$4"
    local w="$LOCK_WORK/gen-$name" prefix="~/.kiro/skills/$name/" nlk ncur nforeign
    local action rel kind src h full n_write=0 n_backup=0 n_keep=0
    gen_expected "$src_dir" "$overlay_dir" "$name" "$w"
    # 2. what is there now
    : > "$w/cur.lst"
    if [ -L "$dest" ]; then
        if is_engine_link "$dest"; then
            echo "  REMOVE SYMLINK: $dest (now a generated copy)"
            act rm "$dest"
        else
            make_way "$dest" || return 0
        fi
    elif [ -e "$dest" ] && [ ! -d "$dest" ]; then
        make_way "$dest" || return 0
    elif [ -d "$dest" ]; then
        # fixtures/ skipped here too: a leftover one in a copy without lock rows must not read as
        # files of yours (KEPT below); lock_retire still removes the ones the lock names
        find "$dest" \( -name __pycache__ -o -type d -name fixtures \) -prune -o -type f -print0 > "$w/cur.lst"
    fi
    sha_list "$w/cur.lst" > "$w/cur.h"
    awk -F'\t' -v pre="$prefix" 'index($2, pre) == 1 && ($1 == "copy-dir-recursive" || $1 == "merge-file") {
        print substr($2, length(pre) + 1) "\t" $3 }' "$LOCK_WORK/old" > "$w/lk"
    # 3. the decision per expected file: action<TAB>rel<TAB>kind<TAB>src<TAB>expected hash
    awk -F'\t' -v OFS='\t' -v eh="$w/exp.h" -v ch="$w/cur.h" -v lf="$w/lk" -v dp="$dest/" -v st="$w/stat" \
        -v fold="$IS_MSYS" "$OWN_RULE_AWK"'
        function k(s) { return fold ? tolower(s) : s }
        FILENAME == eh { h[$2] = $1; next }
        FILENAME == ch { cur[k(substr($2, length(dp) + 1))] = $1; ncur++; next }
        FILENAME == lf { lk[k($1)] = $2; nlk++; next }
        { r = k($1); want[r] = 1; e = h[$3]; c = (r in cur) ? cur[r] : "-"; l = (r in lk) ? lk[r] : "-"
          print own_rule(e, c, l), $1, $2, $3, e }
        END { for (r in cur) if (!(r in want)) nforeign++
              print nlk + 0, ncur + 0, nforeign + 0 > st }
    ' "$w/exp.h" "$w/cur.h" "$w/lk" "$w/exp" > "$w/plan"
    read -r nlk ncur nforeign < "$w/stat"
    if [ "$ncur" -gt 0 ] && [ "$nlk" -eq 0 ] && [ "$nforeign" -gt 0 ]; then
        echo "  KEPT: $dest is your own folder; the playbook's $name skill is not deployed there (rename or remove it, then re-run setup, to get the playbook's)"
        return 0
    fi
    need_dir "$dest"
    # 4. write only the differences. Plain files go through one tar pipe (one process per copy,
    # not one per file); merged files and backups are handled one by one.
    : > "$w/batch"
    while IFS=$'\t' read -r action rel kind src h; do
        full="$dest/$rel"
        if [ "$action" != keep ]; then
            if ! no_link_parent "$full" "$dest"; then
                echo "  SKIPPED: $full (a folder above it is a link)"
                continue
            fi
            if [ "$action" = backup ] || { [ "$action" = write ] && { [ -L "$full" ] || [ -e "$full" ]; }; }; then
                backup_path "$full" || continue
                n_backup=$((n_backup + 1))
            fi
            if [ "$kind" = copy-dir-recursive ]; then
                printf '%s\0' "$rel" >> "$w/batch"
            else
                act cp "$src" "$full"
            fi
            n_write=$((n_write + 1))
        else
            n_keep=$((n_keep + 1))
        fi
        lock_add "$kind" "$prefix$rel" "$h"
    done < "$w/plan"
    if [ -s "$w/batch" ]; then
        if [ "$DRY_RUN" -eq 1 ]; then
            echo "    DRY: copy $(tr -cd '\0' < "$w/batch" | wc -c | tr -d ' ') files from $src_dir to $dest"
        else
            (cd "$src_dir" && tar -cf - --null -T "$w/batch") | (cd "$dest" && tar -xmf -)
        fi
    fi
    if [ "$n_write" -eq 0 ]; then
        echo "  OK: $dest (generated copy, $n_keep files)"
    else
        echo "  UPDATED: $dest (generated copy: $n_write written, $n_backup backed up, $n_keep unchanged)"
    fi
}

# free_real_skill_dir <name>: a real folder at a Kiro skill name where a link goes (a generated
# copy left by an older overlay, or a folder of yours). It decides first: when every entry in it is a
# file setup wrote and left unchanged, those files are removed (lock_retire) and 0 lets the link be
# made. Otherwise nothing there is touched and 1 keeps the folder: a folder of yours is reported
# KEPT, and one that also holds setup's files keeps them and their lock rows, with a WARN that the
# skill is no longer updated there.
free_real_skill_dir() {
    local dest="$KIRO_SKILLS_DIR/$1" prefix="~/.kiro/skills/$1/" w="$LOCK_WORK/free-$1" nlocked nother
    find "$dest" ! -type d -print 2>/dev/null > "$w.all" || true
    tr '\n' '\0' < "$w.all" > "$w.lst"
    sha_list "$w.lst" > "$w.h"
    # locked<TAB>other: files the lock names (edited or not), and every entry that is not such a file
    # left unchanged since setup wrote it
    awk -F'\t' -v hf="$w.h" -v allf="$w.all" -v pre="$prefix" -v home="$HOME" -v fold="$IS_MSYS" '
        function k(s) { return fold ? tolower(s) : s }
        FILENAME == hf { h[k($2)] = $1; next }
        FILENAME == allf { all[k($0)] = 1; next }
        ($1 == "copy-dir-recursive" || $1 == "merge-file") && index($2, pre) == 1 {
            p = k(home "/" substr($2, 3))
            if ((p in h) && !(p in named)) { named[p] = 1; nl++ }
            if ((p in h) && h[p] == $3) ok[p] = 1 }
        END { for (p in all) if (!(p in ok)) no++; print nl + 0 "\t" no + 0 }
    ' "$w.h" "$w.all" "$LOCK_WORK/old" > "$w.n"
    IFS=$'\t' read -r nlocked nother < "$w.n"
    if [ "$nother" -eq 0 ]; then
        lock_retire "$prefix"
        [ "$DRY_RUN" -eq 1 ] && return 1
        find "$dest" -type d -empty -delete 2>/dev/null || true
        [ ! -e "$dest" ] && return 0
    fi
    if [ "$nlocked" -gt 0 ]; then
        echo "  WARN: $dest holds files of yours beside files setup wrote; the playbook's $1 skill is no longer updated there (move your files out of it, then re-run setup)"
        awk -F'\t' -v pre="$prefix" '($1 == "copy-dir-recursive" || $1 == "merge-file") && index($2, pre) == 1' \
            "$LOCK_WORK/old" >> "$LOCK_WORK/new"
    else
        echo "  KEPT: $dest is your own folder; the playbook's $1 skill is not linked there (rename or remove it, then re-run setup, to get the playbook's)"
    fi
    return 1
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
        ov_name="${ov##*/}"
        [ "$ov_name" = "OVERLAY.md" ] && continue
        [ "$ov_name" = "SKILL.OVERLAY.md" ] && continue
        return 0
    done
    return 1
}

# kiro_default_agent: kiro-cli's global chat.defaultAgent as JSON on one line (its lines joined by a
# space, the ends trimmed; spaces inside a value are kept). Prints nothing and returns 1 when the
# read fails or prints nothing.
kiro_default_agent() {
    local v
    v="$(kiro-cli settings -f json --global chat.defaultAgent 2>/dev/null)" || return 1
    v="$(printf '%s' "$v" | tr -d '\r' | tr '\n' ' ' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
    [ -n "$v" ] || return 1
    printf '%s' "$v"
}

# --- Deploy, per provider ----------------------------------------------------

deploy_manifest_links() {
    local mode="$1" i dest source
    for i in "${!MANIFEST_KINDS[@]}"; do
        [ "${MANIFEST_MODES[$i]}" = "$mode" ] || continue
        dest="$(expand_dest "${MANIFEST_DESTS[$i]}")"
        source="$(expand_source "${MANIFEST_SOURCES[$i]}")"
        if memory_source_missing "${MANIFEST_SOURCES[$i]}" "$source" "$dest"; then continue; fi
        need_dir "$(dirname "$dest")"
        case "${MANIFEST_KINDS[$i]}" in
            symlink-file) deploy_instruction_file "${MANIFEST_DESTS[$i]}" "$source" "$dest" || link_file "$source" "$dest" ;;
            symlink-dir)  link_dir  "$source" "$dest" ;;
        esac
    done
}

deploy_claude() {
    echo "=== Claude Code ==="
    need_dir "$HOME/.claude"
    deploy_manifest_links claude
    echo "  Skills (individual):"
    link_skills "$HOME/.claude/skills"
}

deploy_codex() {
    # Codex keeps built-in skills in skills/.system/: one link per skill preserves them.
    echo "=== Codex ==="
    need_dir "$HOME/.codex"
    deploy_manifest_links codex
    echo "  Skills (individual):"
    link_skills "$HOME/.codex/skills"
}

deploy_gemini() {
    echo "=== Gemini CLI ==="
    need_dir "$HOME/.gemini"
    deploy_manifest_links gemini
    echo "  Skills (individual):"
    link_skills "$HOME/.gemini/skills"
}

deploy_kiro() {
    local i dest source dest_parent
    echo "=== Kiro CLI ==="
    KIRO_AGENTS_DIR="$HOME/.kiro/agents"
    KIRO_SETTINGS_DIR="$HOME/.kiro/settings"
    need_dir "$KIRO_AGENTS_DIR" "$KIRO_SETTINGS_DIR"

    # Deploy kiro-always entries from manifest
    for i in "${!MANIFEST_KINDS[@]}"; do
        [ "${MANIFEST_MODES[$i]}" = "kiro-always" ] || continue
        dest="$(expand_dest "${MANIFEST_DESTS[$i]}")"
        source="$(expand_source "${MANIFEST_SOURCES[$i]}")"
        dest_parent="$(dirname "$dest")"
        need_dir "$dest_parent"
        if [ -f "$source" ]; then
            if [ "${MANIFEST_KINDS[$i]}" = "template-file" ]; then
                copy_template "$source" "$dest"
            elif [ "${MANIFEST_KINDS[$i]}" = "seed-file" ]; then
                copy_seed "$source" "$dest"
            else
                own_write copy-file "$dest" "$source"
            fi
        fi
    done

    # chat.defaultAgent: set only when it is not kiro_default already, and recorded in the lock
    # (kind setting, with the value it replaced) so that uninstall reverts only what setup set.
    local old_setting prev
    old_setting="$(lock_get setting "$LOCK_SETTING_KEY")"
    if [ "${AGENT_PLAYBOOK_SKIP_KIRO_CLI:-}" = "1" ]; then
        echo "  SKIP: kiro-cli settings (AGENT_PLAYBOOK_SKIP_KIRO_CLI=1)"
        [ -z "$old_setting" ] || lock_add setting "$LOCK_SETTING_KEY" "$old_setting"
    elif command -v kiro-cli &>/dev/null; then
        prev="$(kiro_default_agent || true)"
        if [ -z "$prev" ]; then
            # a value setup cannot read is never replaced: uninstall could not put it back
            echo "  WARN: kiro-cli's chat.defaultAgent could not be read, so it is left as is"
            [ -z "$old_setting" ] || lock_add setting "$LOCK_SETTING_KEY" "$old_setting"
        elif [ "$prev" = '"kiro_default"' ]; then
            echo "  OK: chat.defaultAgent = kiro_default (global)"
            [ -z "$old_setting" ] || lock_add setting "$LOCK_SETTING_KEY" "$old_setting"
        elif [ "$DRY_RUN" -eq 1 ]; then
            echo "    DRY: kiro-cli settings --global chat.defaultAgent kiro_default"
        elif kiro-cli settings --global chat.defaultAgent kiro_default; then
            echo "  SET: chat.defaultAgent = kiro_default (global)"
            [ "$prev" != null ] || prev="-"
            lock_add setting "$LOCK_SETTING_KEY" "$prev"
        else
            echo "  WARN: Failed to set chat.defaultAgent" >&2
            [ -z "$old_setting" ] || lock_add setting "$LOCK_SETTING_KEY" "$old_setting"
        fi
    elif [ -n "$old_setting" ]; then
        lock_add setting "$LOCK_SETTING_KEY" "$old_setting"
    fi

    # --- Kiro IDE ---
    # Kiro IDE reads steering from ~/.kiro/steering/*.md (always-included context)
    # and skills from ~/.kiro/skills/<name>/SKILL.md (activated via / in chat).
    # Steering and plain skills are symlinks on every platform (Windows copy mode was
    # retired 2026-09-20); overlay-bearing skills are generated copies everywhere.
    echo "=== Kiro IDE ==="
    KIRO_STEERING_DIR="$HOME/.kiro/steering"
    KIRO_SKILLS_DIR="$HOME/.kiro/skills"
    need_dir "$KIRO_STEERING_DIR" "$KIRO_SKILLS_DIR"

    # Steering is flat: every deployed file sits directly in ~/.kiro/steering/.
    for i in "${!MANIFEST_KINDS[@]}"; do
        [ "${MANIFEST_MODES[$i]}" = "kiro" ] || continue
        dest="$(expand_dest "${MANIFEST_DESTS[$i]}")"
        source="$(expand_source "${MANIFEST_SOURCES[$i]}")"
        link_file "$source" "$dest"
    done

    # Shared skills (with overlay-merge support). Any overlay makes a generated copy (a
    # symlinked dir can't have a single file overwritten): deploy_generated_copy.
    echo "  Shared skills:"
    local skill_dir skill_name overlay_dir
    KIRO_OVERLAY_ROOT="$SCRIPT_DIR/providers/kiro/skills"
    MANAGED_SKILLS=""
    for skill_dir in "$SHARED_DIR/skills"/*/; do
        skill_name="${skill_dir%/}"; skill_name="${skill_name##*/}"   # basename, without a process
        [ -f "$skill_dir/SKILL.md" ] || continue
        overlay_dir="$KIRO_OVERLAY_ROOT/$skill_name"
        dest="$KIRO_SKILLS_DIR/$skill_name"
        if has_any_overlay "$overlay_dir"; then
            deploy_generated_copy "${skill_dir%/}" "$dest" "$overlay_dir" "$skill_name"
        else
            # a real folder here: a generated copy left by an older overlay, or yours
            if [ -d "$dest" ] && [ ! -L "$dest" ] && ! free_real_skill_dir "$skill_name"; then
                continue
            fi
            link_dir "${skill_dir%/}" "$dest"
        fi
        MANAGED_SKILLS="$MANAGED_SKILLS $skill_name"
    done

    # Kiro-specific skills
    local kiro_provider_skills="$SCRIPT_DIR/providers/kiro/skills"
    if [ -d "$kiro_provider_skills" ]; then
        echo "  Kiro-specific skills:"
        for skill_dir in "$kiro_provider_skills"/*/; do
            skill_name="${skill_dir%/}"; skill_name="${skill_name##*/}"
            if [ -f "$skill_dir/SKILL.md" ]; then
                # Skip if this dir is a shared-skill overlay (SKILL.md and/or aux overlays)
                # already merged above, rather than a standalone kiro-only skill.
                has_any_overlay "$KIRO_OVERLAY_ROOT/$skill_name" && continue
                dest="$KIRO_SKILLS_DIR/$skill_name"
                if [ -d "$dest" ] && [ ! -L "$dest" ] && ! free_real_skill_dir "$skill_name"; then
                    continue
                fi
                link_dir "${skill_dir%/}" "$dest"
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
        entry_name="${entry##*/}"
        case " $MANAGED_SKILLS " in *" $entry_name "*) continue ;; esac
        if is_engine_link "$entry"; then
            echo "  REMOVE: $entry (stale)"
            act rm "$entry"
        fi
    done

    # Files setup wrote whose source is gone (a deleted skill, a retired copy-file row): the deploy
    # lock names them. Each is removed when unchanged since setup wrote it, else backed up.
    echo "  Cleaning files whose source is gone:"
    lock_retire "~/.kiro/"

    # Cleanup stale files from previous deployments: names a previous deployment wrote
    # that the current manifest no longer owns. NEVER list a path the manifest currently
    # deploys (this runs after the steering loop and would delete the fresh link).
    # Frozen at these 7 entries: add no new ones. The deploy lock covers every later
    # retirement (lock_retire above). Entries are dated. Each goes through the ownership rule: a link
    # into this repo, or a file the lock names and unchanged since, is removed; anything else is
    # yours and goes to <path>.bak.
    echo "=== Cleanup stale files ==="
    local stale stale_dir lk
    for stale in "$KIRO_AGENTS_DIR/kiro_default.json" "$KIRO_STEERING_DIR/claude-code-local-data.md" "$KIRO_STEERING_DIR/v2-only/kiro-cli-local-data.md" "$KIRO_STEERING_DIR/v2-only/memory-sources.md" "$KIRO_STEERING_DIR/v2-only/session-resume-recovery-2.14.0.md" "$KIRO_STEERING_DIR/v3/kiro-cli-local-data.md" "$KIRO_STEERING_DIR/v3/memory-sources.md"; do   # kiro_default.json: 2026-08-18; the rest: 2026-09-20
        [ -e "$stale" ] || [ -L "$stale" ] || continue
        lk=""
        if [ -f "$stale" ] && [ ! -L "$stale" ]; then
            lk="$(awk -F'\t' -v k="$(lock_key "$stale")" '$2 == k && $1 != "backup" && $1 != "setting" { print $3; exit }' "$LOCK_WORK/old")"
        fi
        if is_engine_link "$stale" || { [ -n "$lk" ] && [ "$(sha_of "$stale")" = "$lk" ]; }; then
            act rm -f "$stale"
            echo "  REMOVED stale: $stale"
        else
            echo "  NOTE: $stale is a retired playbook name, but not a file setup wrote unchanged"
            backup_path "$stale" || true
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

# restore_backup <path>: put <path>.bak back when the deploy lock shows setup made that backup and,
# for a file, that it is unchanged since; a .bak setup did not make is never touched.
restore_backup() {
    local p="$1" val
    val="$(lock_get backup "$(lock_key "$p")")"
    [ -n "$val" ] || return 0
    if ! no_link_parent "$p" "$HOME"; then
        echo "  WARN: $p.bak is not restored: a folder above it is a link (restore it by hand if you need it)"
        return 0
    fi
    [ -e "$p.bak" ] || [ -L "$p.bak" ] || return 0
    if [ -e "$p" ] || [ -L "$p" ]; then
        echo "  KEPT: $p.bak ($p is still there)"
        return 0
    fi
    if [ "$val" != "-" ] && { [ -L "$p.bak" ] || [ ! -f "$p.bak" ] || [ "$(sha_of "$p.bak")" != "$val" ]; }; then
        echo "  KEPT: $p.bak (changed since setup made it)"
        return 0
    fi
    act mv "$p.bak" "$p"
    echo "  RESTORED: $p (from $p.bak)"
}

# unlink_engine <path>: remove a link into this repo, then restore <path>.bak if setup made one.
unlink_engine() {
    local p="$1"
    if is_engine_link "$p"; then
        act rm "$p"
        echo "  REMOVED: $p"
        restore_backup "$p"
    fi
}

unlink_skills() {
    local dir="$1" e
    [ -d "$dir" ] || return 0
    for e in "$dir"/*; do unlink_engine "$e"; done
}

# uninstall_owned_file <kind> <dest> <source>: a copy-file or template-file row. Removed when it is
# the file setup wrote, unchanged (by the lock; with no lock row, when it equals the source or the
# render); else kept.
uninstall_owned_file() {
    local kind="$1" dest="$2" source="$3" lk same=0
    if [ -f "$dest" ] && [ ! -L "$dest" ]; then
        lk="$(lock_get "$kind" "$(lock_key "$dest")")"
        if [ -n "$lk" ]; then
            [ "$(sha_of "$dest")" = "$lk" ] && same=1
        elif [ "$kind" = template-file ]; then
            render_template "$source" > "$LOCK_WORK/uninstall-render"
            cmp -s "$LOCK_WORK/uninstall-render" "$dest" && same=1
        else
            cmp -s "$source" "$dest" && same=1
        fi
        if [ "$same" -eq 1 ]; then
            act rm "$dest"; echo "  REMOVED: $dest"
        else
            echo "  KEPT: $dest (changed since setup wrote it)"
        fi
    fi
    restore_backup "$dest"
}

uninstall_mode() {
    local mode="$1" i dest source
    for i in "${!MANIFEST_KINDS[@]}"; do
        [ "${MANIFEST_MODES[$i]}" = "$mode" ] || continue
        dest="$(expand_dest "${MANIFEST_DESTS[$i]}")"
        source="$(expand_source "${MANIFEST_SOURCES[$i]}")"
        case "${MANIFEST_KINDS[$i]}" in
            symlink-file|symlink-dir) unlink_engine "$dest" ;;
            template-file|copy-file) uninstall_owned_file "${MANIFEST_KINDS[$i]}" "$dest" "$source" ;;
            seed-file) [ -e "$dest" ] && echo "  KEPT: $dest (the app owns it; setup only seeded it)" ;;
        esac
    done
}

# uninstall_generated_copies: the files of the generated Kiro copies the lock names. Each is removed
# when unchanged since setup wrote it, else kept; then the empty folders go and the backups setup
# made there are restored. With no readable lock, a file of a generated copy is removed only when it
# equals what setup would write there now.
uninstall_generated_copies() {
    local w="$LOCK_WORK/uninstall" h val p key d skill_dir name
    awk -F'\t' '($1 == "copy-dir-recursive" || $1 == "merge-file") && index($2, "~/.kiro/skills/") == 1' \
        "$LOCK_WORK/old" > "$w"
    if [ "$LOCK_READABLE" -eq 0 ]; then
        # rows built from what setup writes now: the hash a file must still have to be removed
        for skill_dir in "$SHARED_DIR/skills"/*/; do
            name="${skill_dir%/}"; name="${name##*/}"
            [ -f "$skill_dir/SKILL.md" ] && has_any_overlay "$SCRIPT_DIR/providers/kiro/skills/$name" || continue
            gen_expected "${skill_dir%/}" "$SCRIPT_DIR/providers/kiro/skills/$name" "$name" "$LOCK_WORK/unl-$name"
            awk -F'\t' -v eh="$LOCK_WORK/unl-$name/exp.h" -v pre="~/.kiro/skills/$name/" '
                FILENAME == eh { h[$2] = $1; next } { print $2 "\t" pre $1 "\t" h[$3] }
            ' "$LOCK_WORK/unl-$name/exp.h" "$LOCK_WORK/unl-$name/exp" >> "$w"
        done
    fi
    cut -f2 "$w" | awk -F/ '{ print $4 }' | LC_ALL=C sort -u > "$w.names"
    : > "$w.existed"
    while IFS= read -r d; do
        if [ -d "$HOME/.kiro/skills/$d" ] && [ ! -L "$HOME/.kiro/skills/$d" ]; then printf '%s\n' "$d" >> "$w.existed"; fi
    done < "$w.names"
    locked_files_present "$w" "$HOME/.kiro/skills" "$w.lst"
    sha_list "$w.lst" > "$w.h"
    awk -F'\t' -v hf="$w.h" -v home="$HOME" -v fold="$IS_MSYS" '
        function k(s) { return fold ? tolower(s) : s }
        FILENAME == hf { h[k($2)] = $1; real[k($2)] = $2; next }
        { p = k(home "/" substr($2, 3)); if (p in h) print h[p] "\t" $3 "\t" real[p] }
    ' "$w.h" "$w" > "$w.plan"
    : > "$w.rm"
    while IFS=$'\t' read -r h val p; do
        if [ "$h" = "$val" ]; then
            printf '%s\0' "$p" >> "$w.rm"
        else
            echo "  KEPT: $p (changed since setup wrote it)"
        fi
    done < "$w.plan"
    remove_listed "$w.rm"
    awk -F'\t' '$1 == "backup" && index($2, "~/.kiro/skills/") == 1 { print $2 }' "$LOCK_WORK/old" > "$w.bak"
    while IFS= read -r key; do restore_backup "$(lock_path "$key")"; done < "$w.bak"
    while IFS= read -r d; do
        if [ -d "$HOME/.kiro/skills/$d" ] && [ ! -L "$HOME/.kiro/skills/$d" ]; then
            echo "  KEPT: $HOME/.kiro/skills/$d (holds files that are not setup's unchanged ones)"
        else
            echo "  REMOVED: $HOME/.kiro/skills/$d (generated copy)"
        fi
    done < "$w.existed"
}

# uninstall_kiro_setting: revert chat.defaultAgent only when the lock shows setup set it and it
# still names kiro_default. When the revert cannot be tried (no kiro-cli, AGENT_PLAYBOOK_SKIP_KIRO_CLI,
# a value that cannot be read, a failed command), the lock keeps the row for a later uninstall.
uninstall_kiro_setting() {
    local val cur v
    val="$(lock_get setting "$LOCK_SETTING_KEY")"
    if ! command -v kiro-cli >/dev/null 2>&1; then
        [ -z "$val" ] || { echo "  NOTE: no kiro-cli here, so chat.defaultAgent is not reverted; the deploy lock keeps it for a later uninstall"; lock_add setting "$LOCK_SETTING_KEY" "$val"; }
        return 0
    fi
    if [ "${AGENT_PLAYBOOK_SKIP_KIRO_CLI:-}" = "1" ]; then
        echo "  SKIP: kiro-cli settings (AGENT_PLAYBOOK_SKIP_KIRO_CLI=1)"
        [ -z "$val" ] || lock_add setting "$LOCK_SETTING_KEY" "$val"
        return 0
    fi
    if [ -z "$val" ]; then
        echo "  NOTE: setup did not set kiro-cli's chat.defaultAgent, so it is left as is"
        return 0
    fi
    if ! cur="$(kiro_default_agent)"; then
        echo "  WARN: kiro-cli's chat.defaultAgent could not be read, so it is not reverted; the deploy lock keeps it for a later uninstall"
        lock_add setting "$LOCK_SETTING_KEY" "$val"
        return 0
    fi
    if [ "$cur" != '"kiro_default"' ]; then
        echo "  NOTE: kiro-cli's chat.defaultAgent changed since setup set it, so it is left as is"
        return 0
    fi
    if [ "$DRY_RUN" -eq 1 ]; then
        echo "    DRY: revert kiro-cli chat.defaultAgent to $val"
    elif [ "$val" = "-" ] && kiro-cli settings --global --delete chat.defaultAgent; then
        echo "  RESTORED: kiro-cli chat.defaultAgent (to ${val})"
    elif [ "$val" != "-" ] && { v="${val#\"}"; v="${v%\"}"; kiro-cli settings --global chat.defaultAgent "$v"; }; then
        echo "  RESTORED: kiro-cli chat.defaultAgent (to ${val})"
    else
        echo "  WARN: kiro-cli could not revert chat.defaultAgent; the deploy lock keeps it for a later uninstall"
        lock_add setting "$LOCK_SETTING_KEY" "$val"
    fi
}

# uninstall_lock_rows <file>: the rows of the previous lock that belong to providers not uninstalled.
uninstall_lock_rows() {
    awk -F'\t' -v gone=" $PROVIDERS " "$KEY_PROVIDER_AWK"'
        index(gone, " " key_provider($2) " ") == 0' "$LOCK_WORK/old" > "$1"
}

uninstall() {
    echo "=== Uninstall: ${PROVIDERS// /, } ==="
    if wants claude; then
        uninstall_mode claude; unlink_engine "$CLAUDE_SIDE_LINK"; unlink_skills "$HOME/.claude/skills"
        # the rules folder, once the playbook's links are gone and nothing else is in it
        if [ -d "$HOME/.claude/rules" ] && [ ! -L "$HOME/.claude/rules" ] && [ -z "$(ls -A "$HOME/.claude/rules")" ]; then
            act rmdir "$HOME/.claude/rules"; echo "  REMOVED: $HOME/.claude/rules (empty)"
        fi
        if [ -x "$(venv_python)" ]; then
            act "$(venv_python)" -I "$SCRIPT_DIR/providers/claude/settings-entries.py" remove --home "$(native_path "$HOME")" \
                || echo "  NOTE: the venv did not run, so remove the playbook's entries from ~/.claude/settings.json by hand"
        else
            echo "  NOTE: no venv, so remove the playbook's entries from ~/.claude/settings.json by hand"
        fi
    fi
    if wants codex; then uninstall_mode codex; unlink_skills "$HOME/.codex/skills"; fi
    if wants gemini; then
        uninstall_mode gemini; unlink_engine "$GEMINI_SIDE_LINK"; unlink_skills "$HOME/.gemini/skills"
        # the name setup added to context.fileName (the lock's setting row); the rest of the file stays
        old_gemini="$(lock_get setting "$LOCK_GEMINI_KEY")"
        [ -z "$old_gemini" ] || gemini_unset "$old_gemini"
    fi
    if wants kiro; then
        uninstall_mode kiro-always
        uninstall_mode kiro
        uninstall_generated_copies
        unlink_skills "$HOME/.kiro/skills"
        uninstall_kiro_setting
    fi
    uninstall_lock_rows "$LOCK_WORK/carry"
    lock_finish "$LOCK_WORK/carry" drop-empty
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
lock_load
trap 'rm -rf "$LOCK_WORK"' EXIT

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
echo "=== Deploy lock ==="
lock_carry_rows "$LOCK_WORK/carry"
lock_finish "$LOCK_WORK/carry"


echo ""
echo "Done (providers: ${PROVIDERS// /, }). Run '/qconfig-sync' from any agent to verify."
if wants claude; then
    # Only a person at a terminal may change settings.json: an agent-run setup never gets here.
    if [ "$DRY_RUN" -eq 1 ]; then
        echo "    DRY: offer the Claude Code entries in ~/.claude/settings.json"
    elif [ "$INTERACTIVE" -eq 1 ] && [ -x "$(venv_python)" ]; then
        "$(venv_python)" -I "$SCRIPT_DIR/providers/claude/settings-entries.py" offer --home "$(native_path "$HOME")" \
            || echo "NOTE: the venv did not run, so ~/.claude/settings.json was not changed"
    else
        echo "NOTE: ~/.claude/settings.json was not changed. '/qconfig-sync' reports which Claude Code"
        echo "      entries are set, and providers/claude/README.md says how to add them."
    fi
fi
if [ "$BACKUP_FAILED" -gt 0 ]; then
    echo "ERROR: $BACKUP_FAILED path(s) could not be backed up and were left unchanged (the ERROR lines above); close what holds them, then re-run setup" >&2
    exit 1
fi
