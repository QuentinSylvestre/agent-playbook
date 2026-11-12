#!/usr/bin/env bash
# test-parity.sh -- internal-consistency check between two filesystem-walk
# implementations of the agent-playbook deployment inventory, plus a
# cross-shell merge-equivalence guard for the overlay-merge model.
#
# What this script ACTUALLY does:
#   1. Inventory parity: runs `verify-deployment.py --list` (which enumerates
#      per-skill entries dynamically from <repo>/shared/skills and
#      <repo>/providers/kiro/skills) and compares it against an expected
#      inventory built INLINE here using the SAME dynamic enumeration logic.
#      Top-level entries come from `inventory.tsv` (see manifest at repo root);
#      dynamic entries (per-skill) are auto-discovered from the
#      filesystem. The two lists must match on (kind, dest, source). This covers
#      the full inventory the overlay system targets: claude/codex/gemini
#      symlinks, kiro (plain skills as symlink-dir, overlay-bearing skills as
#      copy-dir-recursive plus merge-file rows), and kiro-always.
#   1b. setup.sh / setup.ps1 parity: both deploy into sandbox HOMEs and the
#      two deployed TREES are compared (see its own block). No other script
#      pair remains: every guard is a single Python script with its own
#      --selftest.
#      FIVE assertions carry a *_SKIPPED variable and are therefore tallied:
#      the setup pair (SETUP-PARITY), its deploy-lock and ownership leg
#      (TWIN-OWNERSHIP), its co-existence leg (TWIN-COEXIST), merge-equivalence
#      and render-equivalence. The inventory assertion, SETUP-VERIFY,
#      NO-REWRITE, OWNERSHIP and COEXIST (§ below) are NOT among them -- none
#      has a *_SKIPPED variable and none can be
#      skipped, since all are bash-only and always run -- so do not count them
#      when updating the hardcoded denominator in the verdict block. Adding an
#      assertion means editing the tally, the verdict conditional, and that
#      number together.
#
#   2. Cross-shell merge-equivalence: for a sample overlay skill, asserts the
#      PowerShell `Merge-Overlay` output equals the bash `merge_overlay` output
#      byte-for-byte for the same (shared, overlay) inputs. This guards the
#      duplicated merge shape across BOTH shells (setup.{ps1,sh})
#      WITHOUT requiring a deploy -- it runs on a clean checkout. When no
#      PowerShell interpreter (pwsh/powershell) is present (the common
#      Linux/macOS profile), this assertion SKIPs with a printed notice and the
#      rest of the script still runs and passes.
#
# What this script does NOT do: parse `setup.{sh,ps1}` to extract their actual
# `link_file`/`link_dir`/`cp`/merge invocations. Static top-level entries are
# defined in `inventory.tsv` (the single source of truth). Adding or removing a
# top-level entry means editing `inventory.tsv` only — all consumers (setup,
# verify-deployment, and this script) read from the manifest automatically.
#
# Run after editing `verify-deployment.py`'s enumeration or merge logic,
# or after modifying `inventory.tsv`.
#
# Failure on a healthy repo means `verify-deployment.py --list` and this
# script's expected-inventory have drifted from each other, OR the PS and bash
# merge implementations produce different bytes.
#
# Cross-shell scope: the inventory parity covers the FULL inventory (including
# the copy-dir-recursive + merge-file rows every overlay-bearing skill produces
# on every platform), since the overlay-merge bug bit exactly that model.
# The merge-equivalence assertion guards both shells' duplicated merge shape.
#
# Output: prints `PARITY OK` and exits 0 on success; prints the diff and exits
# 1 on mismatch.

set -euo pipefail

# --- --list wire-protocol kind vocabulary ---------------------------------
#
# Named constants for the `kind` column of the inventory protocol. These values
# are the SHARED wire-protocol vocabulary across test-parity.sh,
# and verify-deployment.py -- the string VALUES must stay
# byte-identical across these files or this script's expected-inventory will
# not match `verify-deployment.py --list`.
readonly KIND_SYMLINK_FILE='symlink-file'
readonly KIND_SYMLINK_DIR='symlink-dir'
readonly KIND_COPY_FILE='copy-file'
readonly KIND_COPY_DIR_RECURSIVE='copy-dir-recursive'
readonly KIND_MERGE_FILE='merge-file'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"

VERIFY_SCRIPT="$SCRIPT_DIR/verify-deployment.py"
SETUP_SCRIPT="$REPO_ROOT/setup.sh"
SETUP_PS1_SCRIPT="$REPO_ROOT/setup.ps1"

# verify-deployment.py runs only under the playbook venv (its venv guard exits 2
# otherwise), so the venv's own interpreter is the one to call -- never a PATH
# python. On Windows (Git Bash/MSYS) the .py takes the .ps1's view: native
# paths, home from USERPROFILE. PARITY_ON_WINDOWS drives the two adaptations
# below: native-path env vars for a sandbox, and the --list path conversion.
case "$(uname -s 2>/dev/null || printf 'unknown')" in
    MINGW*|MSYS*|CYGWIN*) PARITY_ON_WINDOWS=1; VERIFY_PY="$REPO_ROOT/.venv-agent-playbook/Scripts/python.exe" ;;
    *) PARITY_ON_WINDOWS=0; VERIFY_PY="$REPO_ROOT/.venv-agent-playbook/bin/python" ;;
esac

if [ ! -f "$VERIFY_SCRIPT" ]; then
    echo "test-parity.sh: verify-deployment.py not found: $VERIFY_SCRIPT" >&2
    exit 2
fi
if [ ! -x "$VERIFY_PY" ]; then
    echo "test-parity.sh: FAIL: venv python not found: $VERIFY_PY -- run setup.ps1 to build .venv-agent-playbook" >&2
    exit 2
fi

# parity_native_path <path>: the platform-native spelling of a path, for the
# env vars the .py reads on Windows (USERPROFILE, APPDATA). Unchanged elsewhere.
parity_native_path() {
    if [ "$PARITY_ON_WINDOWS" -eq 1 ] && command -v cygpath >/dev/null 2>&1; then
        cygpath -w "$1"
    else
        printf '%s' "$1"
    fi
}

# parity_posix_list: rewrite the .py's Windows-form --list paths
# (C:\Users\x) to the Git Bash form (/c/Users/x) the setup-model view below is
# built in. A no-op on POSIX hosts, where the .py already prints $HOME paths.
parity_posix_list() {
    if [ "$PARITY_ON_WINDOWS" -eq 1 ]; then
        sed -e 's#\\#/#g' -e 's#\(^\|\t\)\([A-Za-z]\):/#\1/\L\2/#g'
    else
        cat
    fi
}

if [ ! -f "$SETUP_SCRIPT" ]; then
    echo "test-parity.sh: setup.sh not found: $SETUP_SCRIPT" >&2
    exit 2
fi

TMPDIR_PARITY="$(mktemp -d)"
# Kill any still-running section job (an interrupted run) before removing the
# folder the jobs write into.
trap 'for _p in $(jobs -p); do kill "$_p" 2>/dev/null; done; rm -rf "$TMPDIR_PARITY"' EXIT

VERIFY_LIST="$TMPDIR_PARITY/verify-list.tsv"
SETUP_LIST="$TMPDIR_PARITY/setup-list.tsv"

# --- Build the verify-deployment view ------------------------------------
#
# verify-deployment.py --list emits one inventory entry per line in:
#   <kind>\t<destination>\t<source>\t<mode>
# where kind ∈ {symlink-file, symlink-dir, copy-file, copy-dir-recursive,
# merge-file} and mode ∈ {claude, codex, gemini, kiro,
# kiro-always}. We key the comparison on (kind, dest, source) so a merged
# target (merge-file) is never conflated with the plain copy-dir-recursive row
# for the same dest.

# On Windows the .py resolves home from USERPROFILE, not $HOME; point it at the
# same home the setup-model view uses so the two lists name one home.
USERPROFILE="$(parity_native_path "$HOME")" "$VERIFY_PY" -I "$VERIFY_SCRIPT" --list \
    | parity_posix_list \
    | awk -F'\t' '{ print $1 "\t" $2 "\t" $3 }' \
    | sort -u \
    > "$VERIFY_LIST"

# --- Build the expected (setup-model) view -------------------------------
#
# We replicate the enumeration verify-deployment.py --list performs, from the
# same filesystem inputs setup.* reads. The top-level entries come from the
# manifest (inventory.tsv); dynamic entries are computed from the filesystem.
# Overlay detection / merge-target enumeration mirror setup.* (has_any_overlay /
# merge_overlay shape).

SHARED_SKILLS="$REPO_ROOT/shared/skills"
KIRO_PROVIDER_SKILLS="$REPO_ROOT/providers/kiro/skills"
KIRO_OVERLAY_ROOT="$KIRO_PROVIDER_SKILLS"

list_skill_subdirs() {
    local root="$1"
    [ -d "$root" ] || return 0
    local d name
    for d in "$root"/*/; do
        [ -d "$d" ] || continue
        name="$(basename "$d")"
        # .system: Codex's own built-in skills dir. .trash / synced / .bucket-*:
        # the Claude Code app's own live skill-sync cache, which an older
        # whole-folder ~/.claude/skills link let it write into shared/skills/ --
        # untracked, regenerates on its own, never a real playbook skill.
        case "$name" in
            .system|.trash|synced|.bucket-*) continue ;;
        esac
        printf '%s\n' "$name"
    done
}

# has_any_overlay / overlay_merge_targets mirror setup.* (and the verify
# siblings). Kept inline so test-parity stays deploy-independent.
parity_has_any_overlay() {
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

parity_overlay_merge_targets() {
    local shared_skill_dir="$1" overlay_dir="$2" ov ov_name target_name
    [ -d "$overlay_dir" ] || return 0
    if [ -f "$overlay_dir/OVERLAY.md" ] && [ -f "$shared_skill_dir/SKILL.md" ]; then
        printf '%s\n' "SKILL.md"
    fi
    for ov in "$overlay_dir"/*.OVERLAY.md; do
        [ -f "$ov" ] || continue
        ov_name="$(basename "$ov")"
        [ "$ov_name" = "OVERLAY.md" ] && continue
        [ "$ov_name" = "SKILL.OVERLAY.md" ] && continue
        target_name="${ov_name%.OVERLAY.md}.md"
        [ -f "$shared_skill_dir/$target_name" ] && printf '%s\n' "$target_name"
    done
}

# --- Read manifest for expected-inventory ---------------------------------

PARITY_MANIFEST_KINDS=()
PARITY_MANIFEST_DESTS=()
PARITY_MANIFEST_SOURCES=()
PARITY_MANIFEST_MODES=()

parity_read_manifest() {
    local manifest_path="$1"
    if [ ! -f "$manifest_path" ]; then
        echo "test-parity.sh: manifest not found: $manifest_path" >&2
        exit 2
    fi
    local line_num=0
    while IFS= read -r line; do
        line_num=$((line_num + 1))
        [[ "$line" =~ ^[[:space:]]*# ]] && continue
        [[ "$line" =~ ^[[:space:]]*$ ]] && continue
        local kind dest source mode
        IFS=$'\t' read -r kind dest source mode <<< "$line"
        PARITY_MANIFEST_KINDS+=("$kind")
        PARITY_MANIFEST_DESTS+=("$dest")
        PARITY_MANIFEST_SOURCES+=("$source")
        PARITY_MANIFEST_MODES+=("$mode")
    done < "$manifest_path"
}

# LOCKSTEP with setup.sh expand_dest / verify-deployment.py expand_dest.
# Both `~/` and `<KIRO_IDE_USER>/` must resolve here identically, or the inventory
# comparison reports a spurious drift on the token rather than on real divergence.
if [ -n "${APPDATA:-}" ] && command -v cygpath >/dev/null 2>&1; then
    PARITY_KIRO_IDE_USER_DIR="$(cygpath -u "$APPDATA")/Kiro/User"
else
    PARITY_KIRO_IDE_USER_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/Kiro/User"
fi

parity_expand_dest() {
    local dest="$1"
    if [[ "$dest" == "<KIRO_IDE_USER>/"* ]]; then
        printf '%s' "$PARITY_KIRO_IDE_USER_DIR/${dest:16}"
    elif [[ "$dest" == "~/"* ]]; then
        printf '%s' "$HOME/${dest:2}"
    else
        printf '%s' "$dest"
    fi
}

parity_expand_source() {
    local source="$1"
    printf '%s' "$REPO_ROOT/$source"
}

parity_read_manifest "$REPO_ROOT/inventory.tsv"

{
    # Emit top-level entries from manifest
    for i in "${!PARITY_MANIFEST_KINDS[@]}"; do
        local_dest="$(parity_expand_dest "${PARITY_MANIFEST_DESTS[$i]}")"
        local_source="$(parity_expand_source "${PARITY_MANIFEST_SOURCES[$i]}")"
        printf '%s\t%s\t%s\n' "${PARITY_MANIFEST_KINDS[$i]}" "$local_dest" "$local_source"
    done

    # Dynamic: Claude Code, Codex and Gemini per-skill (one link per shared skill inside
    # the provider's own skills/ folder)
    for top in .claude .codex .gemini; do
        while IFS= read -r skill; do
            [ -z "$skill" ] && continue
            printf '%s\t%s\t%s\n' "$KIND_SYMLINK_DIR" "$HOME/$top/skills/$skill" "$SHARED_SKILLS/$skill"
        done < <(list_skill_subdirs "$SHARED_SKILLS")
    done

    # Dynamic: Kiro per-skill (shared + provider): plain skills symlink-dir,
    # overlay-bearing skills copy-dir-recursive plus merge-file rows.
    while IFS= read -r skill; do
        [ -z "$skill" ] && continue
        if parity_has_any_overlay "$KIRO_OVERLAY_ROOT/$skill"; then
            printf '%s\t%s\t%s\n' "$KIND_COPY_DIR_RECURSIVE" "$HOME/.kiro/skills/$skill" "$SHARED_SKILLS/$skill"
            while IFS= read -r target; do
                [ -z "$target" ] && continue
                printf '%s\t%s\t%s\n' "$KIND_MERGE_FILE" "$HOME/.kiro/skills/$skill/$target" "$SHARED_SKILLS/$skill/$target"
            done < <(parity_overlay_merge_targets "$SHARED_SKILLS/$skill" "$KIRO_OVERLAY_ROOT/$skill" | sort)
        else
            printf '%s\t%s\t%s\n' "$KIND_SYMLINK_DIR" "$HOME/.kiro/skills/$skill" "$SHARED_SKILLS/$skill"
        fi
    done < <(list_skill_subdirs "$SHARED_SKILLS")
    if [ -d "$KIRO_PROVIDER_SKILLS" ]; then
        while IFS= read -r skill; do
            [ -z "$skill" ] && continue
            parity_has_any_overlay "$KIRO_OVERLAY_ROOT/$skill" && continue
            printf '%s\t%s\t%s\n' "$KIND_SYMLINK_DIR" "$HOME/.kiro/skills/$skill" "$KIRO_PROVIDER_SKILLS/$skill"
        done < <(list_skill_subdirs "$KIRO_PROVIDER_SKILLS")
    fi
} | sort -u > "$SETUP_LIST"

# --- sh/ps1 text comparison (line-ending normalised) -----------------------
#
# PowerShell writes CRLF on Windows while bash writes LF, so a byte-for-byte
# `cmp` between an sh stdout capture and a ps1 stdout capture can NEVER match
# there. Every sh/ps1 parity assertion below was therefore failing
# unconditionally on Windows -- and because the failure looked like permanent
# background noise, nobody read the output. That is precisely how three real
# guard bugs survived: two in the former verify-dream-state.ps1 (a correct state file
# reported ok=6 fail=20 under pwsh 7; element-level FAIL messages swallowed and
# their section reported "ok:") and one in the former verify-citations.ps1
# (case-insensitive matching, so the guard could not see a case-only rename of
# a protected heading). A parity harness that is always red is not a harness.
#
# These assertions are about the TEXT the two implementations emit, not about
# which line terminator their host shell happens to use. Compare accordingly.
parity_same_text() {
    sed 's/\r$//' "$1" > "$1.lf"
    sed 's/\r$//' "$2" > "$2.lf"
    cmp -s "$1.lf" "$2.lf"
}

# --- Interpreters shared by every section ----------------------------------
#
# Resolved once here, before any section runs: the sections below run as
# parallel background jobs (see "Parallel sections"), so nothing one section
# defines is visible to another.

PS_BIN=""
if command -v pwsh >/dev/null 2>&1; then
    PS_BIN="pwsh"
elif command -v powershell >/dev/null 2>&1; then
    PS_BIN="powershell"
fi

# The playbook's one interpreter (plan 261016 SC-13): the venv's, in isolated mode, never one from PATH.
python_resolves() {
    [ -x "$VERIFY_PY" ]
}
# parity_python <args...> -- run the venv interpreter.
parity_python() {
    "$VERIFY_PY" -I "$@"
}

# --- Smoke test: expand_dest must not leave dest tokens in output ---------

PARITY_FAIL=0
smoke_result="$(parity_expand_dest '~/.test')"
if [[ "$smoke_result" == "~"* ]]; then
    echo "FAIL: parity_expand_dest left literal ~ in output: $smoke_result" >&2
    PARITY_FAIL=1
fi
smoke_ide="$(parity_expand_dest '<KIRO_IDE_USER>/mcp.json')"
if [[ "$smoke_ide" == *"<KIRO_IDE_USER>"* ]]; then
    echo "FAIL: parity_expand_dest left literal <KIRO_IDE_USER> in output: $smoke_ide" >&2
    PARITY_FAIL=1
fi

# --- Inventory diff -------------------------------------------------------

INVENTORY_OK=1
if ! diff -u "$SETUP_LIST" "$VERIFY_LIST" >/dev/null 2>&1; then
    INVENTORY_OK=0
    echo "PARITY DRIFT (inventory)" >&2
    echo "  Diff (- expected setup-model, + verify-deployment.py --list):" >&2
    diff -u "$SETUP_LIST" "$VERIFY_LIST" >&2
fi

parity_sec_setup_verify() {
# --- SETUP-VERIFY: sandboxed setup.sh deploy vs verify-deployment.py ------
#
# The inventory diff above compares two IN-MEMORY models; it never runs
# setup.sh for real. This assertion does: it deploys setup.sh into a sandbox
# HOME (never the real one) and then asks verify-deployment.py, pointed at
# that same sandbox, whether the result verifies clean. It is the only
# assertion here that proves setup.sh's actual filesystem output satisfies
# verify-deployment.py on this platform, rather than proving the two
# enumeration models agree on paper.
#
# Sandboxing: HOME, XDG_CONFIG_HOME and APPDATA are all redirected to a
# directory under TMPDIR_PARITY (removed by this script's EXIT trap);
# AGENT_PLAYBOOK_SKIP_KIRO_CLI=1 stops setup.sh from touching the real global
# kiro-cli setting. APPDATA matters on Git Bash/MSYS specifically: both
# setup.sh and verify-deployment.py resolve the Kiro IDE per-user dir from
# $APPDATA FIRST when it is set, falling back to $XDG_CONFIG_HOME/$HOME only
# when it is not (mirroring how the real Kiro IDE reads %APPDATA% on
# Windows) -- leaving $APPDATA unredirected here would let it fall through to
# the REAL inherited Windows env var, so the "sandboxed" run reads/writes the
# real user's live ~/AppData/Roaming/Kiro/User/mcp.json instead of the
# sandbox (masked on a machine where that file already exists, since the
# seed-file write is skipped when the destination is present -- but a live
# escape on a machine where it is not). With HOME, XDG_CONFIG_HOME and
# APPDATA all redirected, setup.sh resolves every destination from those
# three and every source from its own directory (SCRIPT_DIR, i.e. the repo
# root) -- read in full, it never reads or writes any other path, so this
# cannot escape the sandbox. Always runs (no PowerShell needed, no
# *_SKIPPED variable), like the inventory assertion above.
#
# The log and verify-deployment.py's own output are captured OUTSIDE the
# sandbox directory (siblings under TMPDIR_PARITY), never inside it -- a file
# written inside the sandbox would be picked up by SETUP-PARITY's tree walk
# below and could shadow a real deployment path.

SETUP_VERIFY_OK=1
SETUP_VERIFY_SANDBOX="$TMPDIR_PARITY/setup-verify-sandbox"
mkdir -p "$SETUP_VERIFY_SANDBOX"
SETUP_VERIFY_LOG="$TMPDIR_PARITY/setup-verify-sandbox.log"
SETUP_VERIFY_OUT="$TMPDIR_PARITY/setup-verify-verify.tsv"

if HOME="$SETUP_VERIFY_SANDBOX" XDG_CONFIG_HOME="$SETUP_VERIFY_SANDBOX/.config" \
    APPDATA="$SETUP_VERIFY_SANDBOX/AppData/Roaming" \
    AGENT_PLAYBOOK_SKIP_KIRO_CLI=1 bash "$SETUP_SCRIPT" > "$SETUP_VERIFY_LOG" 2>&1; then
    sv_setup_exit=0
else
    sv_setup_exit=$?
fi

# USERPROFILE and APPDATA in native form: on Windows the .py reads home from
# USERPROFILE first (as the .ps1 did), so without it this leg would verify the
# REAL home; on POSIX hosts the .py ignores USERPROFILE.
if HOME="$SETUP_VERIFY_SANDBOX" XDG_CONFIG_HOME="$SETUP_VERIFY_SANDBOX/.config" \
    USERPROFILE="$(parity_native_path "$SETUP_VERIFY_SANDBOX")" \
    APPDATA="$(parity_native_path "$SETUP_VERIFY_SANDBOX/AppData/Roaming")" \
    "$VERIFY_PY" -I "$VERIFY_SCRIPT" > "$SETUP_VERIFY_OUT" 2>&1; then
    sv_verify_exit=0
else
    sv_verify_exit=$?
fi

# ORPHAN and SKIP are allowed; only these five statuses fail the assertion
# (mirrors verify-deployment.py's own exit-code sum).
SETUP_VERIFY_BAD="$(grep -E $'^(MISSING|WRONG_TARGET|NOT_SYMLINK|DRIFTED|AMBIGUOUS_SKILL)\t' "$SETUP_VERIFY_OUT" || true)"

if [ "$sv_verify_exit" -eq 0 ] && [ -z "$SETUP_VERIFY_BAD" ]; then
    echo "SETUP-VERIFY OK: sandboxed setup.sh deploy verifies clean under verify-deployment.py (exit 0, no bad-status lines)"
else
    SETUP_VERIFY_OK=0
    echo "SETUP-VERIFY FAIL: sandboxed setup.sh deploy did not verify clean under verify-deployment.py" >&2
    echo "  setup.sh exit=$sv_setup_exit  verify-deployment.py exit=$sv_verify_exit" >&2
    if [ -n "$SETUP_VERIFY_BAD" ]; then
        echo "  offending verify-deployment.py lines:" >&2
        printf '%s\n' "$SETUP_VERIFY_BAD" >&2
    fi
    echo "  --- setup.sh log (tail) ---" >&2
    tail -n 40 "$SETUP_VERIFY_LOG" >&2 || true
fi

# --- NO-REWRITE: a second setup.sh run on an unchanged tree writes nothing --
#
# SC-1 of plan 261111_DEPLOYMENT_OWNERSHIP_AND_CLIENT_LOAD_VERIFICATION: the
# deploy lock and the per-file comparison make a re-run a no-op. Every entry
# under the sandbox HOME (files, links, folders) keeps its type, mtime and inode
# across run 2, the deploy lock included. Always runs. Under Git Bash run 2 starts setup.sh through
# the repo's 8.3 short path (cygpath -d) when it has one, so the playbook's links, made through the
# long path, must still read as its own (no .bak, no relink); a SKIP line says when there is none.
NO_REWRITE_OK=1
local nr_script="$SETUP_SCRIPT" nr_short
if [ "$PARITY_ON_WINDOWS" -eq 1 ] && nr_short="$(cygpath -u "$(cygpath -d "$REPO_ROOT" 2>/dev/null)" 2>/dev/null)" \
    && [ -n "$nr_short" ] && [ "$nr_short" != "$REPO_ROOT" ] && [ -f "$nr_short/setup.sh" ]; then
    nr_script="$nr_short/setup.sh"
    echo "NO-REWRITE: run 2 starts setup.sh through the repo's 8.3 short path $nr_short"
else
    echo "NO-REWRITE SKIP (short path): the repo has no 8.3 short path here; run 2 uses the long path"
fi
nr_snapshot "$SETUP_VERIFY_SANDBOX" > "$TMPDIR_PARITY/no-rewrite-1.tsv"
if HOME="$SETUP_VERIFY_SANDBOX" XDG_CONFIG_HOME="$SETUP_VERIFY_SANDBOX/.config" \
    APPDATA="$SETUP_VERIFY_SANDBOX/AppData/Roaming" \
    AGENT_PLAYBOOK_SKIP_KIRO_CLI=1 bash "$nr_script" < /dev/null > "$TMPDIR_PARITY/no-rewrite.log" 2>&1; then
    nr_exit=0
else
    nr_exit=$?
fi
nr_snapshot "$SETUP_VERIFY_SANDBOX" > "$TMPDIR_PARITY/no-rewrite-2.tsv"
if [ "$nr_exit" -eq 0 ] && [ -s "$TMPDIR_PARITY/no-rewrite-1.tsv" ] \
    && cmp -s "$TMPDIR_PARITY/no-rewrite-1.tsv" "$TMPDIR_PARITY/no-rewrite-2.tsv" \
    && [ -f "$SETUP_VERIFY_SANDBOX/.agent-playbook/deploy-lock.tsv" ]; then
    echo "NO-REWRITE OK: a second setup.sh run wrote nothing ($(wc -l < "$TMPDIR_PARITY/no-rewrite-1.tsv") entries kept their mtime and inode)"
else
    NO_REWRITE_OK=0
    echo "NO-REWRITE FAIL: the second setup.sh run changed the sandbox (exit=$nr_exit)" >&2
    diff "$TMPDIR_PARITY/no-rewrite-1.tsv" "$TMPDIR_PARITY/no-rewrite-2.tsv" | head -n 20 >&2 || true
fi
}

# nr_snapshot <dir>: "<relpath>\t<type>\t<mtime ns>\t<inode>" for every entry under dir, sorted.
NR_SNAPSHOT_PY='
import os, sys
root = sys.argv[1]
out = []
for d, dirs, files in os.walk(root):
    for n in dirs + files:
        p = os.path.join(d, n)
        st = os.lstat(p)
        kind = "link" if os.path.islink(p) else ("dir" if os.path.isdir(p) else "file")
        out.append("%s\t%s\t%d\t%d" % (os.path.relpath(p, root).replace(os.sep, "/"), kind, st.st_mtime_ns, st.st_ino))
sys.stdout.write("".join(l + "\n" for l in sorted(out)))
'
nr_snapshot() {
    local native="$1"
    command -v cygpath >/dev/null 2>&1 && native="$(cygpath -w "$1")"
    MSYS_NO_PATHCONV=1 parity_python -c "$NR_SNAPSHOT_PY" "$native" | tr -d '\r'
}

parity_sec_merge() {
# --- Cross-shell merge-equivalence assertion ------------------------------
#
# Guards the duplicated merge shape across BOTH shells: assert the PowerShell
# Merge-Overlay output == the bash merge_overlay output byte-for-byte for the
# same (shared, overlay) inputs. Deploy-independent (operates directly on repo
# source files). PowerShell-availability guard: SKIP with a notice when no
# pwsh/powershell is present; run+assert only when one is available.
# (PS_BIN is resolved once in the preamble.)

# bash merge_overlay (mirrors setup.sh / verify-deployment.py; LF seam/trailing,
# interior bytes preserved, no BOM).
parity_merge_overlay() {
    local shared_file="$1" overlay_file="$2"
    local shared_body overlay_body
    shared_body="$(cat "$shared_file")"
    overlay_body="$(cat "$overlay_file")"
    if [ -n "$(printf '%s' "$overlay_body" | tr -d '[:space:]')" ]; then
        printf '%s\n\n%s\n' "$shared_body" "$overlay_body"
    else
        printf '%s\n' "$shared_body"
    fi
}

# Pick a representative overlay skill: SKILL.md overlay (qreview) and, if present,
# an aux overlay (qdream/memory-rules) to exercise both merge paths.
MERGE_OK=1
MERGE_SKIPPED=0
MERGE_CASES=()
if [ -f "$KIRO_OVERLAY_ROOT/qreview/OVERLAY.md" ] && [ -f "$SHARED_SKILLS/qreview/SKILL.md" ]; then
    MERGE_CASES+=("$SHARED_SKILLS/qreview/SKILL.md|$KIRO_OVERLAY_ROOT/qreview/OVERLAY.md")
fi
if [ -f "$KIRO_OVERLAY_ROOT/qdream/memory-rules.OVERLAY.md" ] && [ -f "$SHARED_SKILLS/qdream/memory-rules.md" ]; then
    MERGE_CASES+=("$SHARED_SKILLS/qdream/memory-rules.md|$KIRO_OVERLAY_ROOT/qdream/memory-rules.OVERLAY.md")
fi
if [ -f "$KIRO_OVERLAY_ROOT/qdream/sweep-synthesize.OVERLAY.md" ] && [ -f "$SHARED_SKILLS/qdream/sweep-synthesize.md" ]; then
    MERGE_CASES+=("$SHARED_SKILLS/qdream/sweep-synthesize.md|$KIRO_OVERLAY_ROOT/qdream/sweep-synthesize.OVERLAY.md")
fi

if [ -z "$PS_BIN" ]; then
    MERGE_SKIPPED=1
    echo "MERGE-EQUIVALENCE SKIP: no PowerShell (pwsh/powershell) on PATH -- cross-shell merge assertion skipped (rest of test-parity still runs)."
elif [ "${#MERGE_CASES[@]}" -eq 0 ]; then
    MERGE_SKIPPED=1
    echo "MERGE-EQUIVALENCE SKIP: no representative overlay skill found in repo."
else
    # On Git Bash / MSYS / Cygwin, PowerShell needs Windows-form paths. Convert
    # via cygpath when present; otherwise pass through unchanged (native PS host).
    win_path() {
        if command -v cygpath >/dev/null 2>&1; then
            cygpath -w "$1"
        else
            printf '%s' "$1"
        fi
    }

    for case in "${MERGE_CASES[@]}"; do
        shared_f="${case%%|*}"
        overlay_f="${case##*|}"
        bash_out="$TMPDIR_PARITY/bash-merge.txt"
        ps_out="$TMPDIR_PARITY/ps-merge.txt"
        parity_merge_overlay "$shared_f" "$overlay_f" > "$bash_out"
        shared_w="$(win_path "$shared_f")"
        overlay_w="$(win_path "$overlay_f")"
        ps_out_w="$(win_path "$ps_out")"
        # LOCKSTEP with setup.ps1's Merge-Overlay (and verify-deployment.py's
        # _merged_bytes) -- this embedded PS here-string must stay byte-identical
        # to that merge shape; edit all copies together if the merge changes.
        # Invoke the PS Merge-Overlay shape directly (duplicated here to stay
        # deploy-independent; mirrors setup.ps1 Merge-Overlay byte-for-byte).
        # Windows-form paths are embedded as PS single-quoted literals (these
        # paths never contain single quotes), avoiding MSYS path mangling.
        "$PS_BIN" -NoProfile -NonInteractive -Command "
            \$ErrorActionPreference='Stop'
            \$sharedBody = [IO.File]::ReadAllText('$shared_w') -replace '[\r\n]+$',''
            \$overlayBody = [IO.File]::ReadAllText('$overlay_w')
            if (\$overlayBody.Trim().Length -gt 0) {
                \$merged = \$sharedBody + \"\`n\`n\" + (\$overlayBody -replace '[\r\n]+$','') + \"\`n\"
            } else {
                \$merged = \$sharedBody + \"\`n\"
            }
            \$utf8NoBom = New-Object System.Text.UTF8Encoding(\$false)
            [IO.File]::WriteAllText('$ps_out_w', \$merged, \$utf8NoBom)
        "
        if cmp -s "$bash_out" "$ps_out"; then
            echo "MERGE-EQUIVALENCE OK: $(basename "$shared_f") <- $(basename "$overlay_f") (PS == bash, byte-for-byte)"
        else
            MERGE_OK=0
            echo "MERGE-EQUIVALENCE DRIFT: $(basename "$shared_f") <- $(basename "$overlay_f")" >&2
            echo "  PS Merge-Overlay output differs from bash merge_overlay output:" >&2
            cmp "$bash_out" "$ps_out" >&2 || true
        fi
    done
fi
}

parity_sec_render() {
# --- Cross-shell render-equivalence assertion -----------------------------
#
# Guards the template-file model the same way the merge block guards overlays:
# setup.{ps1,sh} each duplicate the render shape, so the two must agree
# byte-for-byte (verify-deployment.py's render is covered end to end by SETUP-VERIFY). Deploy-independent -- both sides are fed
# identical token VALUES, isolating substitution logic from the real platform's
# $HOME/$REPO_ROOT.
#
# Both twins substitute the token value with its backslashes turned into forward
# slashes (no JSON escaping), so the fixture below feeds Windows-form values with
# backslashes and a space, and the two shapes must agree exactly.

RENDER_OK=1
RENDER_SKIPPED=0

# Mirror of setup.sh render_template with the token values passed in rather than
# read from the environment. LOCKSTEP with setup.sh render_template.
parity_render_template() {
    local src="$1" home_val="$2" root_val="$3"
    local body
    body="$(cat "$src")"
    # LOCKSTEP with setup.sh render_template: forward slashes, not backslashes.
    body="${body//\{\{USER_HOME\}\}/${home_val//\\//}}"
    body="${body//\{\{PLAYBOOK_ROOT\}\}/${root_val//\\//}}"
    printf '%s\n' "$body"
}

if [ -z "$PS_BIN" ]; then
    RENDER_SKIPPED=1
    echo "RENDER-EQUIVALENCE SKIP: no PowerShell (pwsh/powershell) on PATH -- cross-shell render assertion skipped (rest of test-parity still runs)."
else
    rn_win_path() {
        if command -v cygpath >/dev/null 2>&1; then
            cygpath -w "$1"
        else
            printf '%s' "$1"
        fi
    }

    RN_FIXDIR="$TMPDIR_PARITY/render-fixture"
    mkdir -p "$RN_FIXDIR"

    # Fixture exercises: both tokens, a token adjacent to non-path text, repeated
    # tokens, and forward slashes after the token (the authoring convention).
    cat > "$RN_FIXDIR/tmpl.json" <<'RNEOF'
{
  "resources": [
    "file://{{USER_HOME}}/.kiro/steering/**/*.md",
    "skill://{{USER_HOME}}/.kiro/skills/*/SKILL.md",
    "file://{{PLAYBOOK_ROOT}}/memory/**/*.md"
  ],
  "note": "adjacent:{{USER_HOME}}suffix and repeat {{PLAYBOOK_ROOT}}"
}
RNEOF

    # Windows-native backslash-form values: the shape setup.ps1 actually receives
    # from $env:USERPROFILE/$ScriptDir on a real deploy, and the shape that
    # exposed the original divergence (setup.ps1 doubled backslashes instead of
    # converting to forward slashes, breaking the file:// URIs and plain markdown
    # kiro_default.md/kiro-guidelines.md embed these tokens in). Both twins now
    # normalize backslash -> forward-slash, so they must agree byte for byte on
    # this shape too, not just the POSIX shape bash naturally receives. Includes
    # a space, to catch naive word-splitting in either shell.
    RN_HOME='C:\Users\test.user'
    RN_ROOT='C:\Users\test.user\One Drive\repo'

    rn_bash_out="$TMPDIR_PARITY/bash-render.txt"
    rn_ps_out="$TMPDIR_PARITY/ps-render.txt"
    parity_render_template "$RN_FIXDIR/tmpl.json" "$RN_HOME" "$RN_ROOT" > "$rn_bash_out"

    rn_tmpl_w="$(rn_win_path "$RN_FIXDIR/tmpl.json")"
    rn_ps_out_w="$(rn_win_path "$rn_ps_out")"

    # LOCKSTEP with setup.ps1 Render-Template and verify-deployment.py's
    # check_template_file -- this embedded shape must stay byte-identical to
    # those; edit all copies together if the render changes.
    "$PS_BIN" -NoProfile -NonInteractive -Command "
        \$ErrorActionPreference='Stop'
        \$body = [IO.File]::ReadAllText('$rn_tmpl_w') -replace '[\r\n]+$',''
        \$body = \$body.Replace('{{USER_HOME}}', '$RN_HOME'.Replace('\\', '/'))
        \$body = \$body.Replace('{{PLAYBOOK_ROOT}}', '$RN_ROOT'.Replace('\\', '/'))
        \$rendered = \$body + \"\`n\"
        \$utf8NoBom = New-Object System.Text.UTF8Encoding(\$false)
        [IO.File]::WriteAllText('$rn_ps_out_w', \$rendered, \$utf8NoBom)
    "
    if cmp -s "$rn_bash_out" "$rn_ps_out"; then
        echo "RENDER-EQUIVALENCE OK: template-file (PS Render-Template == bash render_template, byte-for-byte)"
    else
        RENDER_OK=0
        echo "RENDER-EQUIVALENCE DRIFT: template-file render shapes diverged" >&2
        echo "  PS Render-Template output differs from bash render_template output:" >&2
        cmp "$rn_bash_out" "$rn_ps_out" >&2 || true
        diff "$rn_bash_out" "$rn_ps_out" >&2 || true
    fi
fi
}

parity_sec_setup_parity() {
# --- setup sh/ps1 sandboxed tree-equivalence parity ------------------------
#
# The ninth sh/ps1 pair, and unlike the others it compares FILESYSTEM TREES,
# not stdout. Two sandboxes: SETUP_VERIFY_SANDBOX above (populated by
# setup.sh, HOME/XDG_CONFIG_HOME-redirected) and a second one here (populated
# by setup.ps1, USERPROFILE/APPDATA-redirected -- the env vars setup.ps1
# actually reads, mirroring the merge/qvalidate blocks' win_path helper for
# Git Bash/MSYS/Cygwin). Reuses the PowerShell-availability guard above: SKIP
# with a notice when no pwsh/powershell is present.
#
# Two divergences between the trees are EXPECTED, not drift, and are
# normalised before comparing:
#   - the two sandboxes are different directories, so every occurrence of a
#     sandbox's own root (its {{USER_HOME}}) or of setup.ps1's own view of the
#     repo root (its {{PLAYBOOK_ROOT}}, which is only string-different from
#     $REPO_ROOT under Git Bash's cygpath translation) inside a FILE'S CONTENT
#     is replaced with a common placeholder before hashing -- this is the same
#     token-substitution setup.{sh,ps1} themselves perform, run in reverse;
#   - the Kiro IDE per-user dir resolves from $APPDATA when set (both
#     sandboxes redirect it, per SETUP-VERIFY's own sandboxing above, so both
#     land at AppData/Roaming/Kiro/User here even though a real POSIX
#     deployment with no $APPDATA at all would fall back to
#     .config/Kiro/User -- see setup.sh/setup.ps1's own KIRO_IDE_USER_DIR
#     comments) and is remapped to <KIRO_IDE_USER> on both sides; the
#     platform-specific ancestor scaffolding dirs that only exist to hold it
#     (.config, .config/Kiro / AppData, AppData/Roaming, AppData/Roaming/Kiro)
#     are excluded from both trees rather than compared against each other.
# CRLF is normalised the way parity_same_text already does for stdout
# captures, applied here to file content before hashing.
#
# verify-deployment.py is also run against the ps1 sandbox and held to the
# same zero-bad-status bar as SETUP-VERIFY above. It resolves home from
# $env:USERPROFILE first, as setup.ps1 does, then the known-folder API, then
# $env:HOME; HOME is set as well for pwsh on Unix. Measured on Windows
# (2026-09-25): `[Environment]::GetFolderPath('UserProfile')` ignores an
# overridden USERPROFILE and returns the real profile, so before the
# USERPROFILE-first order this leg verified the real ~/.kiro, not the sandbox.

SETUP_PARITY_OK=1
SETUP_PARITY_SKIPPED=0
if [ -z "$PS_BIN" ]; then
    SETUP_PARITY_SKIPPED=1
    echo "SETUP-PARITY SKIP: no PowerShell (pwsh/powershell) on PATH -- setup.sh/setup.ps1 sandboxed tree-equivalence assertion skipped (rest of test-parity still runs)."
elif [ ! -f "$SETUP_PS1_SCRIPT" ]; then
    SETUP_PARITY_SKIPPED=1
    echo "SETUP-PARITY SKIP: setup.ps1 not found at repo root."
elif [ "$(uname -o 2>/dev/null)" != "Msys" ]; then
    # setup.ps1 is the Windows twin (Windows paths, the Scripts\ venv layout, cmd.exe for links);
    # Linux and macOS deploy with setup.sh. The tree comparison runs where both twins deploy:
    # Windows under Git Bash. The merge and render equivalence above still run here.
    SETUP_PARITY_SKIPPED=1
    echo "SETUP-PARITY SKIP: not Windows -- setup.ps1 deploys on Windows only; the tree comparison runs under Git Bash there."
else
    sp_win_path() {
        if command -v cygpath >/dev/null 2>&1; then
            cygpath -w "$1"
        else
            printf '%s' "$1"
        fi
    }

    # Content normalisation below needs a LITERAL (non-pattern) substring
    # replace, all occurrences, on multi-line content. Bash's own
    # ${var//$needle/$repl} looks like the obvious tool but is NOT literal:
    # whatever backslashes happen to be inside $needle's expanded value are
    # re-interpreted as glob/pattern escape sequences at match time, so a
    # needle containing backslashes (the raw Windows-form roots used for the
    # ps1 sandbox) would silently fail to match even though its STRING VALUE
    # is byte-correct. sed has no such ambiguity once both the search and
    # replacement sides are escaped for sed's own BRE/replacement syntax.
    sp_sed_escape_pattern() {
        printf '%s' "$1" | sed -e 's/[][\.*^$/]/\\&/g'
    }
    sp_sed_escape_replacement() {
        printf '%s' "$1" | sed -e 's/[\&/]/\\&/g'
    }
    # sp_mask_script <needle> <replacement> [<needle> <replacement> ...]
    # Builds ONE sed script that strips CR and literal-replaces every needle,
    # in argument order; empty needles are dropped. The needles are constant
    # for a whole sandbox, so this runs once per tree walk rather than once
    # per file: escaping and replacing per file used to fork ~50 processes
    # per deployed file, which on Git Bash made each walk take minutes.
    sp_mask_script() {
        local script='s/\r$//'
        while [ "$#" -ge 2 ]; do
            if [ -n "$1" ]; then
                script="$script"$'\n'"s/$(sp_sed_escape_pattern "$1")/$(sp_sed_escape_replacement "$2")/g"
            fi
            shift 2
        done
        printf '%s' "$script"
    }

    sp_sha256() {
        if command -v sha256sum >/dev/null 2>&1; then
            sha256sum | awk '{print $1}'
        elif command -v shasum >/dev/null 2>&1; then
            shasum -a 256 | awk '{print $1}'
        else
            cksum | awk '{print $1"-"$2}'
        fi
    }

    SP_SANDBOX2="$TMPDIR_PARITY/setup-parity-sandbox2"
    SP_LOG2="$TMPDIR_PARITY/setup-parity-sandbox2.log"

    SP_USERPROFILE_W="$(sp_win_path "$SP_SANDBOX2")"
    SP_APPDATA_W="$(sp_win_path "$SP_SANDBOX2/AppData/Roaming")"
    SP_REPO_ROOT_W="$(sp_win_path "$REPO_ROOT")"

    # The deploy itself ran in the background from the start of this job
    # (parity_setup_ps1_deploy); wait for it and read its exit code.
    if [ -n "${SP_DEPLOY_PID:-}" ]; then
        wait "$SP_DEPLOY_PID" || true
    fi
    if [ -f "$SP_SANDBOX2.rc" ]; then
        sp_setup_exit="$(cat "$SP_SANDBOX2.rc")"
    else
        sp_setup_exit=none
        cat "$TMPDIR_PARITY/setup-parity-deploy.err" >&2 2>/dev/null || true
    fi

    if [ "$sp_setup_exit" != 0 ]; then
        SETUP_PARITY_OK=0
        echo "SETUP-PARITY DRIFT: setup.ps1 exited $sp_setup_exit against the sandbox" >&2
        echo "  --- setup.ps1 log (tail) ---" >&2
        tail -n 40 "$SP_LOG2" >&2 || true
    else
        # sp_tree_listing <sandbox_root> <home_raw> <repo_raw> <ide_user_relprefix>
        # Emits "<relpath>\t<kind>" for every entry under sandbox_root.
        # sp_tree_listing: the Python walker below when an interpreter resolves
        # (one process per sandbox), else this bash loop, which forks sed and a
        # hasher per file (~0.15 s each on Git Bash, minutes per walk).
        # PARITY_TREE_IMPL=sh forces the bash loop; the two produce identical
        # listings (checked against each other on real sandboxes, 2026-09-25).
        sp_tree_listing() {
            if [ "${PARITY_TREE_IMPL:-}" != "sh" ] && python_resolves; then
                sp_tree_listing_py "$@"
            else
                sp_tree_listing_sh "$@"
            fi
        }

        # Python twin of sp_tree_listing_sh -- same entries, kinds, masks and
        # hash input. Paths go to Python in native form (cygpath -w on Git
        # Bash); link targets are matched against every form of the repo root
        # the two shells can report (POSIX /c/..., C:/..., C:\...).
        SP_TREE_PY='
import hashlib, os, sys
root, ide_prefix = sys.argv[1], sys.argv[2]
n_masks = int(sys.argv[3])
masks = [(sys.argv[4 + 2*i].encode(), sys.argv[5 + 2*i].encode()) for i in range(n_masks)]
masks = [(a, b) for a, b in masks if a]
roots = [r.replace("\\", "/").rstrip("/") for r in sys.argv[4 + 2*n_masks:] if r]
out = []
def is_link(p):
    if os.path.islink(p):
        return True
    j = getattr(os.path, "isjunction", None)
    return bool(j and j(p))
def walk(d, prefix):
    for e in sorted(os.scandir(d), key=lambda e: e.name):
        rel = prefix + e.name
        full = e.path
        # Ancestors of the Kiro IDE per-user dir are scaffolding, not compared.
        if not ide_prefix.startswith(rel + "/"):
            emit(rel, full)
        if not is_link(full) and e.is_dir(follow_symlinks=False):
            walk(full, rel + "/")
def emit(rel, full):
    if rel in ("__pycache__",) or rel.endswith("/__pycache__") or rel.startswith("__pycache__/") \
            or "/__pycache__/" in rel or rel == "AppData/Local" or rel.startswith("AppData/Local/") \
            or rel == ".agent-playbook/deploy-lock.tsv":
        return
    shown = rel
    if rel == ide_prefix:
        shown = "<KIRO_IDE_USER>"
    elif rel.startswith(ide_prefix + "/"):
        shown = "<KIRO_IDE_USER>/" + rel[len(ide_prefix) + 1:]
    if is_link(full):
        t = os.readlink(full)
        if t.startswith("\\\\?\\"):
            t = t[4:]
        t = t.replace("\\", "/")
        rel_t = t
        for r in roots:
            if t.startswith(r + "/"):
                rel_t = t[len(r) + 1:]
                break
        kind = "link -> " + rel_t
    elif os.path.isdir(full):
        kind = "dir"
    elif os.path.isfile(full):
        with open(full, "rb") as f:
            data = f.read()
        lines = data.split(b"\n")
        for i, line in enumerate(lines):
            if line.endswith(b"\r"):
                line = line[:-1]
            for a, b in masks:
                line = line.replace(a, b)
            lines[i] = line
        # As $(sed ...) in bash: NUL bytes dropped, then trailing newlines.
        data = b"\n".join(lines).replace(b"\x00", b"").rstrip(b"\n")
        kind = "file " + hashlib.sha256(data).hexdigest()
    else:
        kind = "other"
    out.append(shown + "\t" + kind)
walk(root, "")
sys.stdout.write("".join(l + "\n" for l in out))
'
        sp_tree_listing_py() {
            local sroot="$1" home_raw="$2" repo_raw="$3" ide_prefix="$4"
            local native_root="$sroot" repo_m="" repo_w="" home_m="$home_raw"
            if command -v cygpath >/dev/null 2>&1; then
                native_root="$(cygpath -w "$sroot")"
                # the home in mixed form (C:/Users/...): setup.sh writes the pointer file's paths so
                home_m="$(cygpath -m "$home_raw")"
                repo_m="$(cygpath -m "$REPO_ROOT")"
                repo_w="$(cygpath -m "$SP_REPO_ROOT_W")"
            fi
            # Masks in the same order as sp_tree_listing_sh's sp_mask_script.
            # MSYS path conversion is disabled for this call: Git Bash would
            # otherwise rewrite POSIX-looking needles (/c/Users/..., /tmp/...)
            # into Windows form before Python sees them, and those needles
            # would never match the files. native_root is converted above.
            MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*' \
            parity_python -c "$SP_TREE_PY" "$native_root" "$ide_prefix" 8 \
                "$home_raw" '<USER_HOME>' \
                "${home_raw//\\//}" '<USER_HOME>' \
                "$home_m" '<USER_HOME>' \
                "$repo_raw" '<PLAYBOOK_ROOT>' \
                "${repo_raw//\\//}" '<PLAYBOOK_ROOT>' \
                "$REPO_ROOT" '<PLAYBOOK_ROOT>' \
                "$SP_REPO_ROOT_W" '<PLAYBOOK_ROOT>' \
                "${SP_REPO_ROOT_W//\\//}" '<PLAYBOOK_ROOT>' \
                "$repo_raw" "${repo_raw//\\//}" "$REPO_ROOT" "$repo_m" "$repo_w" \
                | tr -d '\r'
        }

        sp_tree_listing_sh() {
            local sroot="$1" home_raw="$2" repo_raw="$3" ide_prefix="$4"
            local full rel kind target target_rel content mask
            # Content masks: this sandbox's own roots in raw form and in the
            # forward-slash form setup.{sh,ps1} render {{USER_HOME}} and
            # {{PLAYBOOK_ROOT}} as (a no-op on a POSIX root). The ps1 sandbox's
            # roots arrive as cygpath -w backslash form, so without the
            # forward-slash needle its rendered kiro_default.md and MCP seed
            # files never masked and SETUP-PARITY drifted on exactly those.
            # $REPO_ROOT and $SP_REPO_ROOT_W are masked on BOTH calls: real
            # prose can cite the repo root in the OTHER platform's form too
            # (e.g. shared/AGENTS.md's own "Config Repo Locations" documents
            # both a Windows and a POSIX path as worked examples) -- on a
            # machine where that example equals the real repo root, masking
            # only this sandbox's native form would produce a spurious
            # cross-sandbox hash mismatch on content that never differed.
            local home_m="$home_raw"
            command -v cygpath >/dev/null 2>&1 && home_m="$(cygpath -m "$home_raw")"
            mask="$(sp_mask_script \
                "$home_raw" '<USER_HOME>' \
                "${home_raw//\\//}" '<USER_HOME>' \
                "$home_m" '<USER_HOME>' \
                "$repo_raw" '<PLAYBOOK_ROOT>' \
                "${repo_raw//\\//}" '<PLAYBOOK_ROOT>' \
                "$REPO_ROOT" '<PLAYBOOK_ROOT>' \
                "$SP_REPO_ROOT_W" '<PLAYBOOK_ROOT>' \
                "${SP_REPO_ROOT_W//\\//}" '<PLAYBOOK_ROOT>')"
            # readlink on this MSYS build returns POSIX-mount form
            # (/c/Users/...) even for a reparse point .NET/PowerShell wrote
            # with a Windows drive-letter target -- so for the ps1 sandbox
            # call, repo_raw (cygpath -w -> C:\Users\...) can never match
            # target after a bare backslash-to-slash flip (that only yields
            # C:/Users/..., not /c/Users/...). $REPO_ROOT (set once near the
            # top of this script via `pwd`) is always the correct POSIX form
            # of the repo root regardless of which form repo_raw arrived in
            # -- match against that too, or every ps1-sandbox symlink target
            # fails the repo_raw forms and never gets stripped to its
            # repo-relative form.
            while IFS= read -r full; do
                rel="${full#"$sroot"/}"
                # Ancestor scaffolding dirs that exist only to hold the
                # platform-specific Kiro IDE per-user dir (.config/Kiro on the
                # sh side; AppData/Roaming on the ps1 side) -- excluded on
                # both sides rather than compared against each other.
                case "$ide_prefix" in
                    "$rel"/*) continue ;;
                esac
                # Neither the deployment nor the comparison itself: __pycache__
                # is a Python bytecode cache created as a side effect of an
                # earlier assertion importing qmemory-eval.py (embeds the
                # sandbox's own absolute path in its bytecode, so it never
                # matches across two independently-created sandboxes even
                # though the deployment IS correct). AppData/Local exists only
                # because invoking pwsh against a redirected $env:USERPROFILE
                # makes PowerShell itself write its own startup-profile cache
                # and telemetry UUID there -- setup.ps1 never deploys anything
                # under it, so it has no sh-sandbox counterpart to compare
                # against.
                case "$rel" in
                    __pycache__|*/__pycache__|__pycache__/*|*/__pycache__/*) continue ;;
                    AppData/Local|AppData/Local/*) continue ;;
                    # byte-compared on its own (TWIN-OWNERSHIP)
                    .agent-playbook/deploy-lock.tsv) continue ;;
                esac
                case "$rel" in
                    "$ide_prefix") rel="<KIRO_IDE_USER>" ;;
                    "$ide_prefix"/*) rel="<KIRO_IDE_USER>/${rel#"$ide_prefix"/}" ;;
                esac
                if [ -L "$full" ]; then
                    target="$(readlink "$full" 2>/dev/null || true)"
                    target="${target//\\//}"
                    case "$target" in
                        "$repo_raw"/*) target_rel="${target#"$repo_raw"/}" ;;
                        "${repo_raw//\\//}"/*) target_rel="${target#"${repo_raw//\\//}"/}" ;;
                        "$REPO_ROOT"/*) target_rel="${target#"$REPO_ROOT"/}" ;;
                        *) target_rel="$target" ;;
                    esac
                    kind="link -> $target_rel"
                elif [ -d "$full" ]; then
                    kind="dir"
                elif [ -f "$full" ]; then
                    # $(...) strips trailing newlines before hashing, as the
                    # per-file cat pipeline this replaced did.
                    content="$(sed -e "$mask" "$full")"
                    kind="file $(printf '%s' "$content" | sp_sha256)"
                else
                    kind="other"
                fi
                printf '%s\t%s\n' "$rel" "$kind"
            done < <(find "$sroot" -mindepth 1 | LC_ALL=C sort)
        }

        SP_LIST_SH="$TMPDIR_PARITY/setup-parity-tree-sh.tsv"
        SP_LIST_PS="$TMPDIR_PARITY/setup-parity-tree-ps.tsv"
        sp_tree_listing "$SETUP_VERIFY_SANDBOX" "$SETUP_VERIFY_SANDBOX" "$REPO_ROOT" \
            "AppData/Roaming/Kiro/User" | LC_ALL=C sort > "$SP_LIST_SH"
        sp_tree_listing "$SP_SANDBOX2" "$SP_USERPROFILE_W" "$SP_REPO_ROOT_W" \
            "AppData/Roaming/Kiro/User" | LC_ALL=C sort > "$SP_LIST_PS"

        if diff -u "$SP_LIST_SH" "$SP_LIST_PS" >/dev/null 2>&1; then
            echo "SETUP-PARITY OK: sandboxed setup.sh/setup.ps1 deploy trees agree ($(wc -l < "$SP_LIST_SH") entries)"
        else
            SETUP_PARITY_OK=0
            echo "SETUP-PARITY DRIFT: sandboxed setup.sh/setup.ps1 deploy trees diverge" >&2
            echo "  Diff (- sh sandbox, + ps1 sandbox):" >&2
            diff -u "$SP_LIST_SH" "$SP_LIST_PS" >&2 || true
        fi
    fi

    # verify-deployment.py against the ps1 sandbox: same zero-bad-status bar
    # as SETUP-VERIFY. HOME is set alongside USERPROFILE/APPDATA -- see the
    # NOTE above (the .py reads USERPROFILE on Windows, HOME elsewhere).
    SP_VERIFY_OUT="$TMPDIR_PARITY/setup-parity-verify.tsv"
    if HOME="$SP_USERPROFILE_W" USERPROFILE="$SP_USERPROFILE_W" APPDATA="$SP_APPDATA_W" \
        AGENT_PLAYBOOK_SKIP_KIRO_CLI=1 \
        "$VERIFY_PY" -I "$VERIFY_SCRIPT" > "$SP_VERIFY_OUT" 2>&1; then
        sp_verify_exit=0
    else
        sp_verify_exit=$?
    fi
    SP_VERIFY_BAD="$(grep -E $'^(MISSING|WRONG_TARGET|NOT_SYMLINK|DRIFTED|AMBIGUOUS_SKILL)\t' "$SP_VERIFY_OUT" || true)"
    if [ "$sp_verify_exit" -eq 0 ] && [ -z "$SP_VERIFY_BAD" ]; then
        echo "SETUP-PARITY OK: sandboxed setup.ps1 deploy verifies clean under verify-deployment.py (exit 0, no bad-status lines)"
    else
        SETUP_PARITY_OK=0
        echo "SETUP-PARITY DRIFT: sandboxed setup.ps1 deploy did not verify clean under verify-deployment.py" >&2
        echo "  verify-deployment.py exit=$sp_verify_exit" >&2
        if [ -n "$SP_VERIFY_BAD" ]; then
            echo "  offending verify-deployment.py lines:" >&2
            printf '%s\n' "$SP_VERIFY_BAD" >&2
        fi
        echo "  --- verify-deployment.py output (tail) ---" >&2
        tail -n 20 "$SP_VERIFY_OUT" >&2 || true
        echo "  --- setup.ps1 log (tail) ---" >&2
        tail -n 40 "$SP_LOG2" >&2 || true
    fi
fi
}

parity_sec_ownership() {
# --- OWNERSHIP and TWIN-OWNERSHIP: the deploy lock's rules, on both twins ----
#
# Runs after SETUP-PARITY (it changes the sandboxes that section compares).
# TWIN-OWNERSHIP first compares the two twins' deploy locks: they must be byte-equal (both twins
# render the template tokens in the same C:/... form), and a second setup.ps1 run must write nothing
# (as NO-REWRITE does for setup.sh). Then, on the setup.sh sandbox (OWNERSHIP, always runs) and,
# where SETUP-PARITY ran, the setup.ps1 one (TWIN-OWNERSHIP), the same steps run with a stub
# kiro-cli on PATH (see own_stub; never the real one) and each outcome is checked:
#   1. one collision per ownership rule is planted; setup runs for Kiro; it sets chat.defaultAgent;
#   2. a re-run writes nothing (no .bak growth) and keeps chat.defaultAgent as it is;
#   3. a file held open by another process cannot be backed up (the run ends non-zero, the path is
#      left alone), a .bak that is not setup's is left alone, a later backup replaces an earlier
#      one, and a chat.defaultAgent that cannot be read is not set;
#   4. a Kiro uninstall (the setting unreadable: its lock row is kept), with a journal row an
#      interrupted run left; 5. a second uninstall reverts the setting;
#   6. an uninstall with an unreadable lock: the lock goes to .bak, and only files equal to what
#      setup writes now are removed.
# Every run's exit code is checked. The fixtures forge lock rows and plant files; they never touch
# the repo.
OWNERSHIP_OK=1
TWIN_OWNERSHIP_OK=1
TWIN_OWNERSHIP_SKIPPED=0
local sh_sb="$SETUP_VERIFY_SANDBOX" ps_sb="$TMPDIR_PARITY/setup-parity-sandbox2" twin=1 sh_pid
if [ -z "$PS_BIN" ] || [ ! -f "$SETUP_PS1_SCRIPT" ] || [ "$(uname -o 2>/dev/null)" != "Msys" ] \
    || [ "$(cat "$ps_sb.rc" 2>/dev/null)" != 0 ]; then
    twin=0
    TWIN_OWNERSHIP_SKIPPED=1
    echo "TWIN-OWNERSHIP SKIP: no setup.ps1 sandbox (SETUP-PARITY did not deploy one here) -- the setup.ps1 lock and ownership checks are skipped."
fi
if [ "$twin" -eq 1 ]; then
    if [ -s "$sh_sb/.agent-playbook/deploy-lock.tsv" ] && cmp -s "$sh_sb/.agent-playbook/deploy-lock.tsv" "$ps_sb/.agent-playbook/deploy-lock.tsv"; then
        echo "TWIN-OWNERSHIP OK: the setup.sh and setup.ps1 deploy locks are byte-equal ($(wc -l < "$sh_sb/.agent-playbook/deploy-lock.tsv") lines)"
    else
        TWIN_OWNERSHIP_OK=0
        echo "TWIN-OWNERSHIP DRIFT: the two deploy locks differ (- setup.sh, + setup.ps1):" >&2
        diff "$sh_sb/.agent-playbook/deploy-lock.tsv" "$ps_sb/.agent-playbook/deploy-lock.tsv" | head -n 20 >&2 || true
    fi
    cx_snapshot "$ps_sb" > "$TMPDIR_PARITY/nr-ps-1.tsv"
    own_run_ps "$ps_sb" nr-ps
    cx_snapshot "$ps_sb" > "$TMPDIR_PARITY/nr-ps-2.tsv"
    if own_rc nr-ps 0 && cmp -s "$TMPDIR_PARITY/nr-ps-1.tsv" "$TMPDIR_PARITY/nr-ps-2.tsv"; then
        echo "TWIN-OWNERSHIP OK: a second setup.ps1 run wrote nothing ($(wc -l < "$TMPDIR_PARITY/nr-ps-1.tsv") entries kept their mtime and inode)"
    else
        TWIN_OWNERSHIP_OK=0
        echo "TWIN-OWNERSHIP FAIL: the second setup.ps1 run changed the sandbox (exit=$(cat "$TMPDIR_PARITY/nr-ps.rc"))" >&2
        diff "$TMPDIR_PARITY/nr-ps-1.tsv" "$TMPDIR_PARITY/nr-ps-2.tsv" | head -n 20 >&2 || true
    fi
fi

# the stub kiro-cli, one per twin; a twin whose shell would not resolve it runs with
# AGENT_PLAYBOOK_SKIP_KIRO_CLI=1 instead and its setting checks are skipped
own_stub "$sh_sb" sh
[ "$twin" -eq 1 ] && own_stub "$ps_sb" ps
own_stub_state "$sh_sb" '"my_agent"' ok
[ "$twin" -eq 1 ] && own_stub_state "$ps_sb" '"my_agent"' ok

# 1. collisions, and chat.defaultAgent set
own_plant "$sh_sb"
[ "$twin" -eq 1 ] && own_plant "$ps_sb"
own_run_sh "$sh_sb" own-sh-1 --providers kiro &
sh_pid=$!
[ "$twin" -eq 1 ] && own_run_ps "$ps_sb" own-ps-1 -Providers kiro
wait "$sh_pid" || true
own_check_deploy "$sh_sb" "$TMPDIR_PARITY/own-sh-1.log" "setup.sh" own-sh-1
[ "$twin" -eq 1 ] && own_check_deploy "$ps_sb" "$TMPDIR_PARITY/own-ps-1.log" "setup.ps1" own-ps-1

# 2. a re-run writes nothing
own_stub_state "$sh_sb" '' ok
[ "$twin" -eq 1 ] && own_stub_state "$ps_sb" '' ok
nr_snapshot "$sh_sb" > "$TMPDIR_PARITY/own-rerun-sh-1.tsv"
[ "$twin" -eq 1 ] && cx_snapshot "$ps_sb" > "$TMPDIR_PARITY/own-rerun-ps-1.tsv"
own_run_sh "$sh_sb" own-sh-2 --providers kiro &
sh_pid=$!
[ "$twin" -eq 1 ] && own_run_ps "$ps_sb" own-ps-2 -Providers kiro
wait "$sh_pid" || true
nr_snapshot "$sh_sb" > "$TMPDIR_PARITY/own-rerun-sh-2.tsv"
[ "$twin" -eq 1 ] && cx_snapshot "$ps_sb" > "$TMPDIR_PARITY/own-rerun-ps-2.tsv"
own_check_rerun "$sh_sb" setup.sh own-sh-2 sh
[ "$twin" -eq 1 ] && own_check_rerun "$ps_sb" setup.ps1 own-ps-2 ps

# 3. a backup that cannot be made, a .bak that is not setup's, a later backup, an unreadable setting
own_plant_hold "$sh_sb"
[ "$twin" -eq 1 ] && own_plant_hold "$ps_sb"
own_stub_state "$sh_sb" '' fail-read
[ "$twin" -eq 1 ] && own_stub_state "$ps_sb" '' fail-read
own_run_sh "$sh_sb" own-sh-3 --providers kiro &
sh_pid=$!
[ "$twin" -eq 1 ] && own_run_ps "$ps_sb" own-ps-3 -Providers kiro
wait "$sh_pid" || true
own_release "$sh_sb"
[ "$twin" -eq 1 ] && own_release "$ps_sb"
own_check_hold "$sh_sb" setup.sh own-sh-3
[ "$twin" -eq 1 ] && own_check_hold "$ps_sb" setup.ps1 own-ps-3

# 4. uninstall, the setting unreadable; 5. uninstall again, the setting reverted
own_plant_uninstall "$sh_sb"
[ "$twin" -eq 1 ] && own_plant_uninstall "$ps_sb"
own_run_sh "$sh_sb" own-sh-4 --uninstall --providers kiro &
sh_pid=$!
[ "$twin" -eq 1 ] && own_run_ps "$ps_sb" own-ps-4 -Uninstall -Providers kiro
wait "$sh_pid" || true
own_check_uninstall "$sh_sb" "setup.sh" own-sh-4
[ "$twin" -eq 1 ] && own_check_uninstall "$ps_sb" "setup.ps1" own-ps-4
own_stub_state "$sh_sb" '' ok
[ "$twin" -eq 1 ] && own_stub_state "$ps_sb" '' ok
own_run_sh "$sh_sb" own-sh-5 --uninstall --providers kiro &
sh_pid=$!
[ "$twin" -eq 1 ] && own_run_ps "$ps_sb" own-ps-5 -Uninstall -Providers kiro
wait "$sh_pid" || true
own_check_revert "$sh_sb" setup.sh own-sh-5
[ "$twin" -eq 1 ] && own_check_revert "$ps_sb" setup.ps1 own-ps-5

# 6. uninstall with an unreadable lock
own_plant_nolock "$sh_sb"
[ "$twin" -eq 1 ] && own_plant_nolock "$ps_sb"
own_run_sh "$sh_sb" own-sh-6 --uninstall --providers kiro &
sh_pid=$!
[ "$twin" -eq 1 ] && own_run_ps "$ps_sb" own-ps-6 -Uninstall -Providers kiro
wait "$sh_pid" || true
own_check_nolock "$sh_sb" setup.sh own-sh-6
[ "$twin" -eq 1 ] && own_check_nolock "$ps_sb" setup.ps1 own-ps-6

# 7. a sandboxed HOME never writes the repo's memory link (it lives in the shared working copy). A
# --yes dry run: the SKIPPED line names the link, and neither LINKED nor UPDATE names it.
own_check_memlink() {   # own_check_memlink <setup.sh|setup.ps1> <log name>
    local log="$TMPDIR_PARITY/$2.log" lp
    lp="$(tr -d '\r' < "$log" | sed -n 's/^  SKIPPED: \(.*\) (HOME is sandboxed; the repo.s memory link is never written from a sandbox)$/\1/p' | head -n 1)"
    if own_rc "$2" 0 && [ -n "$lp" ] && ! grep -qF -e "LINKED: $lp " -e "UPDATE: $lp " "$log"; then
        echo "OWNERSHIP OK: $1 with a sandboxed HOME skips the repo's memory link"
    else
        own_fail "$1" "a sandboxed --yes run must print the memory link SKIPPED line and must not link or repoint it (link: ${lp:-none}, exit=$(cat "$TMPDIR_PARITY/$2.rc" 2>/dev/null))"
    fi
}
own_run_sh "$sh_sb" own-sh-7 --dry-run --yes
own_check_memlink setup.sh own-sh-7
if [ "$twin" -eq 1 ]; then
    own_run_ps "$ps_sb" own-ps-7 -DryRun -Yes
    own_check_memlink setup.ps1 own-ps-7
fi

if [ "$OWNERSHIP_OK" -eq 1 ]; then
    echo "OWNERSHIP OK: setup.sh keeps, backs up, replaces, retires and uninstalls each planted collision by the deploy lock, fails loudly on a backup it cannot make, and sets and reverts chat.defaultAgent through a stub kiro-cli"
else
    echo "  --- setup.sh logs (tail) ---" >&2
    tail -n 15 "$TMPDIR_PARITY/own-sh-1.log" "$TMPDIR_PARITY/own-sh-3.log" "$TMPDIR_PARITY/own-sh-4.log" >&2 || true
fi
if [ "$twin" -eq 1 ] && [ "$TWIN_OWNERSHIP_OK" -eq 1 ]; then
    echo "TWIN-OWNERSHIP OK: setup.ps1 meets the same ownership checks"
elif [ "$twin" -eq 1 ]; then
    echo "  --- setup.ps1 logs (tail) ---" >&2
    tail -n 15 "$TMPDIR_PARITY/own-ps-1.log" "$TMPDIR_PARITY/own-ps-3.log" "$TMPDIR_PARITY/own-ps-4.log" >&2 || true
fi
}

# own_run_sh <sandbox> <log name> <args...> / own_run_ps: a sandboxed setup run, with no terminal
# and never --yes (which would repoint the repo's memory link into the sandbox). The exit code goes
# to <log name>.rc. With a stub kiro-cli made for the sandbox (own_stub), PATH starts with the stub
# and holds no folder with another kiro-cli, and AGENT_PLAYBOOK_SKIP_KIRO_CLI is unset; otherwise
# AGENT_PLAYBOOK_SKIP_KIRO_CLI=1, so the real kiro-cli is never run.
own_run_sh() {
    local sb="$1" log="$2" rc=0; shift 2
    if [ -f "$sb.stub/use" ]; then
        env -u AGENT_PLAYBOOK_SKIP_KIRO_CLI HOME="$sb" XDG_CONFIG_HOME="$sb/.config" APPDATA="$sb/AppData/Roaming" \
            KIRO_STUB_DIR="$(parity_native_path "$sb.stub")" PATH="$sb.stub/bin-sh:$(own_path_without_kiro)" \
            bash "$SETUP_SCRIPT" "$@" < /dev/null > "$TMPDIR_PARITY/$log.log" 2>&1 || rc=$?
    else
        HOME="$sb" XDG_CONFIG_HOME="$sb/.config" APPDATA="$sb/AppData/Roaming" AGENT_PLAYBOOK_SKIP_KIRO_CLI=1 \
            bash "$SETUP_SCRIPT" "$@" < /dev/null > "$TMPDIR_PARITY/$log.log" 2>&1 || rc=$?
    fi
    echo "$rc" > "$TMPDIR_PARITY/$log.rc"
}
own_run_ps() {
    local sb="$1" log="$2" rc=0; shift 2
    if [ -f "$sb.stub/use" ]; then
        env -u AGENT_PLAYBOOK_SKIP_KIRO_CLI USERPROFILE="$(cygpath -w "$sb")" APPDATA="$(cygpath -w "$sb/AppData/Roaming")" \
            KIRO_STUB_DIR="$(cygpath -w "$sb.stub")" PATH="$sb.stub/bin-ps:$(own_path_without_kiro)" \
            "$PS_BIN" -NoProfile -NonInteractive -File "$(cygpath -w "$SETUP_PS1_SCRIPT")" "$@" \
            < /dev/null > "$TMPDIR_PARITY/$log.log" 2>&1 || rc=$?
    else
        USERPROFILE="$(cygpath -w "$sb")" APPDATA="$(cygpath -w "$sb/AppData/Roaming")" AGENT_PLAYBOOK_SKIP_KIRO_CLI=1 \
            "$PS_BIN" -NoProfile -NonInteractive -File "$(cygpath -w "$SETUP_PS1_SCRIPT")" "$@" \
            < /dev/null > "$TMPDIR_PARITY/$log.log" 2>&1 || rc=$?
    fi
    echo "$rc" > "$TMPDIR_PARITY/$log.rc"
}

# own_rc <log name> <0|nonzero>: the run's exit code was 0, or was not.
own_rc() {
    local rc
    rc="$(cat "$TMPDIR_PARITY/$1.rc" 2>/dev/null || echo missing)"
    if [ "$2" = 0 ]; then [ "$rc" = 0 ]; else [ "$rc" != 0 ] && [ "$rc" != missing ]; fi
}

# own_path_without_kiro: PATH minus every folder that holds a kiro-cli (the real one included).
own_path_without_kiro() {
    local IFS=: d out=""
    for d in $PATH; do
        [ -n "$d" ] || continue
        if [ -e "$d/kiro-cli" ] || [ -e "$d/kiro-cli.exe" ] || [ -e "$d/kiro-cli.cmd" ]; then continue; fi
        out="${out:+$out:}$d"
    done
    printf '%s' "$out"
}

# own_stub <sandbox> <sh|ps>: a stub kiro-cli beside the sandbox (never inside it, so the snapshot
# compares do not see it): <sandbox>.stub/{bin-sh/kiro-cli, bin-ps/kiro-cli.cmd} run stub.py, which
# logs each call to calls.log, answers `settings -f json --global chat.defaultAgent` from value.json
# (null when absent; exit 1 in mode fail-read) and sets or deletes the value. Used only when the
# twin's own shell resolves kiro-cli to the stub (else <sandbox>.stub/use is not made).
OWN_STUB_PY='import json, os, sys
d = os.environ["KIRO_STUB_DIR"]
a = sys.argv[1:]
with open(os.path.join(d, "calls.log"), "a", encoding="utf-8") as f:
    f.write(" ".join(a) + "\n")
mode = open(os.path.join(d, "mode"), encoding="utf-8").read().strip()
val = os.path.join(d, "value.json")
if a == ["settings", "-f", "json", "--global", "chat.defaultAgent"]:
    if mode == "fail-read":
        sys.exit(1)
    print(open(val, encoding="utf-8").read().strip() if os.path.exists(val) else "null")
elif a == ["settings", "--global", "--delete", "chat.defaultAgent"]:
    if os.path.exists(val):
        os.remove(val)
elif len(a) == 4 and a[:3] == ["settings", "--global", "chat.defaultAgent"]:
    open(val, "w", encoding="utf-8").write(json.dumps(a[3]))
else:
    sys.exit(2)
'
own_stub() {
    local sb="$1" t="$2" st="$1.stub" py_w got
    mkdir -p "$st/bin-sh" "$st/bin-ps"
    printf '%s' "$OWN_STUB_PY" > "$st/stub.py"
    py_w="$(parity_native_path "$VERIFY_PY")"
    printf '#!/usr/bin/env bash\nexec "%s" -I "%s" "$@"\n' "$VERIFY_PY" "$(parity_native_path "$st/stub.py")" > "$st/bin-sh/kiro-cli"
    chmod +x "$st/bin-sh/kiro-cli"
    printf '@"%s" -I "%s" %%*\r\n' "$py_w" "$(parity_native_path "$st/stub.py")" > "$st/bin-ps/kiro-cli.cmd"
    if [ "$t" = sh ]; then
        got="$(PATH="$st/bin-sh:$(own_path_without_kiro)" command -v kiro-cli || true)"
        [ "$got" = "$st/bin-sh/kiro-cli" ] && : > "$st/use"
    else
        got="$(PATH="$st/bin-ps:$(own_path_without_kiro)" "$PS_BIN" -NoProfile -NonInteractive -Command '(Get-Command kiro-cli -ErrorAction SilentlyContinue).Source' < /dev/null 2>/dev/null | tr -d '\r' || true)"
        [ "$(printf '%s' "$got" | tr '\\' '/' | tr 'A-Z' 'a-z')" = "$(cygpath -m "$st/bin-ps/kiro-cli.cmd" | tr 'A-Z' 'a-z')" ] && : > "$st/use"
    fi
    [ -f "$st/use" ] || echo "OWNERSHIP SKIP ($t): kiro-cli does not resolve to the stub here (got '$got'); its chat.defaultAgent checks are skipped"
}

# own_stub_state <sandbox> <value json, or '' to keep it> <ok|fail-read>: the stub's mode, and its
# value when one is given; the call log starts empty.
own_stub_state() {
    [ -z "$2" ] || printf '%s' "$2" > "$1.stub/value.json"
    printf '%s\n' "$3" > "$1.stub/mode"
    : > "$1.stub/calls.log"
}

# own_stub_used <sandbox>: the stub runs for this twin.
own_stub_used() { [ -f "$1.stub/use" ]; }

# Ownership fixtures. own_plant <sandbox>: one collision per ownership rule in a deployed sandbox
# that has a lock. Each own_check_* asserts outcomes; a failed check prints a line and sets the
# twin's flag to 0.

own_sha() { sha256sum < "$1" | cut -c1-64; }

own_lock_add() {   # own_lock_add <sandbox> <kind> <key> <value>
    printf '%s\t%s\t%s\n' "$2" "$3" "$4" >> "$1/.agent-playbook/deploy-lock.tsv"
}

own_lock_drop() {   # own_lock_drop <sandbox> <key prefix>: remove the lock's rows under the prefix
    local lock="$1/.agent-playbook/deploy-lock.tsv"
    awk -F'\t' -v pre="$2" 'index($2, pre) != 1' "$lock" > "$lock.tmp" && mv "$lock.tmp" "$lock"
}

own_plant() {
    local sb="$1" k="$1/.kiro" lock="$1/.agent-playbook/deploy-lock.tsv" f
    # 1. a file of yours inside a generated copy
    printf 'mine\n' > "$k/skills/qdev/my-notes.md"
    # 2. a file of a generated copy, edited
    cp "$k/skills/qdev/SKILL.md" "$sb.qdev-skill.orig"
    printf 'edited qdev\n' >> "$k/skills/qdev/SKILL.md"
    cp "$k/skills/qdev/SKILL.md" "$sb.qdev-skill.edited"
    # 3. a folder of yours at an overlay-bearing skill's name, with no lock rows: a file setup does
    #    not write there, and one byte-identical to setup's (that alone never makes it setup's)
    rm -rf "$k/skills/qreview"
    mkdir -p "$k/skills/qreview"
    printf 'user qreview\n' > "$k/skills/qreview/SKILL.md"
    printf 'my own\n' > "$k/skills/qreview/my-own.md"
    cp "$REPO_ROOT/shared/skills/qreview/full-effort.md" "$k/skills/qreview/full-effort.md"
    own_lock_drop "$sb" "~/.kiro/skills/qreview/"
    # 4. a copy-file row, edited
    printf 'edited authoring\n' > "$k/AUTHORING.md"
    # 5. a foreign symlink at a link path
    printf 'foreign\n' > "$sb/foreign-target.md"
    rm -f "$k/steering/agents.md"
    MSYS=winsymlinks:nativestrict ln -s "$sb/foreign-target.md" "$k/steering/agents.md"
    # 6. a locked, unedited file whose source is gone (a deleted skill)
    mkdir -p "$k/skills/qgone"
    printf 'gone\n' > "$k/skills/qgone/SKILL.md"
    own_lock_add "$sb" copy-dir-recursive "~/.kiro/skills/qgone/SKILL.md" "$(own_sha "$k/skills/qgone/SKILL.md")"
    # 7. a locked file whose source is gone, edited since setup wrote it
    mkdir -p "$k/skills/qgone2"
    printf 'edited gone\n' > "$k/skills/qgone2/SKILL.md"
    own_lock_add "$sb" merge-file "~/.kiro/skills/qgone2/SKILL.md" "$(own_sha "$k/skills/qgone/SKILL.md")"
    # 8. a locked file setup wrote in an older version, unedited: replaced, no backup
    cp "$k/skills/qexplore/SKILL.md" "$sb.qexplore-skill.orig"
    printf 'an older merge\n' > "$k/skills/qexplore/SKILL.md"
    grep -v $'\t~/.kiro/skills/qexplore/SKILL.md\t' "$lock" > "$lock.tmp" && mv "$lock.tmp" "$lock"
    own_lock_add "$sb" merge-file "~/.kiro/skills/qexplore/SKILL.md" "$(own_sha "$k/skills/qexplore/SKILL.md")"
    # 9. a folder of yours with a SKILL.md at a plain skill's name (a link there before)
    rm -f "$k/skills/qcouncil" 2>/dev/null || rmdir "$k/skills/qcouncil"
    mkdir -p "$k/skills/qcouncil"
    printf 'user qcouncil\n' > "$k/skills/qcouncil/SKILL.md"
    # 10. an older generated copy the lock names no file of, every file at a path setup writes, one
    #     edited: it is setup's, so the edited file goes to .bak
    cp "$k/skills/qplan/SKILL.md" "$sb.qplan-skill.orig"
    printf 'an older qplan\n' > "$k/skills/qplan/SKILL.md"
    own_lock_drop "$sb" "~/.kiro/skills/qplan/"
    # 11. a plain skill's folder holding a file setup wrote, unchanged, beside a file of yours: kept
    #     whole, setup's file and its lock row included, with a warning
    rm -f "$k/skills/qhandoff" 2>/dev/null || rmdir "$k/skills/qhandoff"
    mkdir -p "$k/skills/qhandoff"
    cp "$REPO_ROOT/shared/skills/qhandoff/SKILL.md" "$k/skills/qhandoff/SKILL.md"
    printf 'mine\n' > "$k/skills/qhandoff/mine.md"
    own_lock_add "$sb" copy-dir-recursive "~/.kiro/skills/qhandoff/SKILL.md" "$(own_sha "$k/skills/qhandoff/SKILL.md")"
    #     the same with the file setup wrote edited since: kept too, never backed up
    rm -f "$k/skills/qclose" 2>/dev/null || rmdir "$k/skills/qclose"
    mkdir -p "$k/skills/qclose"
    { cat "$REPO_ROOT/shared/skills/qclose/SKILL.md"; printf 'edited qclose\n'; } > "$k/skills/qclose/SKILL.md"
    cp "$k/skills/qclose/SKILL.md" "$sb.qclose-skill.edited"
    printf 'mine\n' > "$k/skills/qclose/mine.md"
    own_lock_add "$sb" copy-dir-recursive "~/.kiro/skills/qclose/SKILL.md" "$(own_sha "$REPO_ROOT/shared/skills/qclose/SKILL.md")"
    # 12. a file of a generated copy whose name and lock row differ from the source only in letter
    #     case (NTFS keeps either): the same file, neither backed up nor retired
    if [ "$(uname -o 2>/dev/null)" = Msys ]; then   # NTFS only: elsewhere letter case makes another file
    f="$k/skills/qtest/plan-process.md"
    mv "$f" "$k/skills/qtest/x.tmp" && mv "$k/skills/qtest/x.tmp" "$k/skills/qtest/PLAN-process.md"
    grep -v $'\t~/.kiro/skills/qtest/plan-process.md\t' "$lock" > "$lock.tmp" && mv "$lock.tmp" "$lock"
    own_lock_add "$sb" copy-dir-recursive "~/.kiro/skills/qtest/PLAN-process.md" "$(own_sha "$k/skills/qtest/PLAN-process.md")"
    fi
    # 13. an edited template-file row
    cp "$k/agents/kiro_default.md" "$sb.kiro-default.orig"
    printf 'edited template\n' >> "$k/agents/kiro_default.md"
    cp "$k/agents/kiro_default.md" "$sb.kiro-default.edited"
    # 14. a folder above a generated copy's file is a link: that file is skipped
    mkdir -p "$sb.linked-refs"
    rm -rf "$k/skills/qextract/references"
    MSYS=winsymlinks:nativestrict ln -s "$sb.linked-refs" "$k/skills/qextract/references"
    # 15. a lock row for a seed file (setup never writes one): never retired
    own_lock_add "$sb" copy-file "~/.kiro/settings/mcp.json" "$(own_sha "$k/settings/mcp.json")"
    # 16. a retired playbook name (the frozen stale list) holding a file of yours: backed up
    printf 'my json\n' > "$k/agents/kiro_default.json"
}

own_fail() {   # own_fail <setup.sh|setup.ps1> <what>
    echo "OWNERSHIP FAIL ($1): $2" >&2
    if [ "$1" = setup.sh ]; then OWNERSHIP_OK=0; else TWIN_OWNERSHIP_OK=0; fi
}

own_is() {   # own_is <file> <text>: the file holds exactly text plus a newline
    [ -f "$1" ] && [ ! -L "$1" ] && [ "$(cat "$1")" = "$2" ]
}

own_check_deploy() {   # own_check_deploy <sandbox> <log> <label> <log name>
    local sb="$1" log="$2" l="$3" k="$1/.kiro" lock="$1/.agent-playbook/deploy-lock.tsv"
    own_rc "$4" 0 || own_fail "$l" "the collision run exits 0 (got $(cat "$TMPDIR_PARITY/$4.rc"))"
    own_is "$k/skills/qdev/my-notes.md" mine && [ ! -e "$k/skills/qdev/my-notes.md.bak" ] \
        || own_fail "$l" "a file of yours inside a generated copy is left in place"
    cmp -s "$k/skills/qdev/SKILL.md.bak" "$sb.qdev-skill.edited" && cmp -s "$k/skills/qdev/SKILL.md" "$sb.qdev-skill.orig" \
        || own_fail "$l" "an edited file of a generated copy goes to .bak and is rewritten"
    own_is "$k/skills/qreview/SKILL.md" "user qreview" && own_is "$k/skills/qreview/my-own.md" "my own" \
        && [ "$(find "$k/skills/qreview" | wc -l)" -eq 4 ] && grep -q 'KEPT: .*qreview' "$log" \
        || own_fail "$l" "a folder of yours at an overlay skill's name is KEPT, untouched, though one file equals setup's"
    own_is "$k/AUTHORING.md.bak" "edited authoring" && cmp -s "$k/AUTHORING.md" "$REPO_ROOT/shared/AUTHORING.md" \
        || own_fail "$l" "an edited copy-file row goes to .bak and is rewritten"
    [ -L "$k/steering/agents.md.bak" ] && case "$(readlink "$k/steering/agents.md.bak")" in *foreign-target.md) true ;; *) false ;; esac \
        && [ -L "$k/steering/agents.md" ] && case "$(readlink "$k/steering/agents.md")" in *shared/AGENTS.md|*shared\\AGENTS.md) true ;; *) false ;; esac \
        || own_fail "$l" "a foreign symlink goes to .bak before the link is made"
    [ ! -e "$k/skills/qgone" ] || own_fail "$l" "a locked unedited file whose source is gone is removed, with its folder"
    [ ! -e "$k/skills/qgone2/SKILL.md" ] && own_is "$k/skills/qgone2/SKILL.md.bak" "edited gone" \
        || own_fail "$l" "an edited file whose source is gone goes to .bak"
    cmp -s "$k/skills/qexplore/SKILL.md" "$sb.qexplore-skill.orig" && [ ! -e "$k/skills/qexplore/SKILL.md.bak" ] \
        || own_fail "$l" "a locked unedited file is replaced with no backup"
    [ -d "$k/skills/qcouncil" ] && [ ! -L "$k/skills/qcouncil" ] && own_is "$k/skills/qcouncil/SKILL.md" "user qcouncil" \
        && grep -q 'KEPT: .*qcouncil' "$log" \
        || own_fail "$l" "a Kiro skill folder of yours with a SKILL.md is KEPT"
    own_is "$k/skills/qplan/SKILL.md.bak" "an older qplan" && cmp -s "$k/skills/qplan/SKILL.md" "$sb.qplan-skill.orig" \
        && grep -q $'^merge-file\t~/.kiro/skills/qplan/SKILL.md\t' "$lock" \
        || own_fail "$l" "an older copy with no lock rows and only setup's paths is setup's: the edited file goes to .bak"
    cmp -s "$k/skills/qhandoff/SKILL.md" "$REPO_ROOT/shared/skills/qhandoff/SKILL.md" && own_is "$k/skills/qhandoff/mine.md" mine \
        && [ ! -L "$k/skills/qhandoff" ] && grep -q 'WARN: .*qhandoff.*no longer updated there' "$log" \
        && grep -q $'^copy-dir-recursive\t~/.kiro/skills/qhandoff/SKILL.md\t' "$lock" \
        || own_fail "$l" "a plain skill's folder with setup's file beside yours is kept whole, with a warning and its lock row"
    cmp -s "$k/skills/qclose/SKILL.md" "$sb.qclose-skill.edited" && [ ! -e "$k/skills/qclose/SKILL.md.bak" ] \
        && own_is "$k/skills/qclose/mine.md" mine && grep -q 'WARN: .*qclose.*no longer updated there' "$log" \
        || own_fail "$l" "a plain skill's folder with an edited file of setup's beside yours is kept whole, nothing backed up"
    if [ "$(uname -o 2>/dev/null)" = Msys ]; then
    [ -f "$k/skills/qtest/PLAN-process.md" ] && cmp -s "$k/skills/qtest/PLAN-process.md" "$REPO_ROOT/shared/skills/qtest/plan-process.md" \
        && [ ! -e "$k/skills/qtest/plan-process.md.bak" ] && [ ! -e "$k/skills/qtest/PLAN-process.md.bak" ] \
        || own_fail "$l" "a file whose name differs from its source only in letter case is neither backed up nor retired"
    fi
    cmp -s "$k/agents/kiro_default.md.bak" "$sb.kiro-default.edited" && cmp -s "$k/agents/kiro_default.md" "$sb.kiro-default.orig" \
        || own_fail "$l" "an edited template-file row goes to .bak and is rendered again"
    [ -z "$(ls -A "$sb.linked-refs")" ] && grep -q 'SKIPPED: .*references.*a folder above it is a link' "$log" \
        || own_fail "$l" "a file under a linked folder of a generated copy is skipped, never written through the link"
    [ -f "$k/settings/mcp.json" ] && ! grep -q 'settings/mcp.json' "$lock" \
        || own_fail "$l" "a lock row for a seed file never retires the seed (and is not kept)"
    own_is "$k/agents/kiro_default.json.bak" "my json" && [ ! -e "$k/agents/kiro_default.json" ] \
        && grep -q $'^backup\t~/.kiro/agents/kiro_default.json\t' "$lock" \
        || own_fail "$l" "a retired playbook name holding a file of yours goes to .bak"
    grep -q $'^backup\t~/.kiro/AUTHORING.md\t' "$lock" && grep -q $'^backup\t~/.kiro/steering/agents.md\t-$' "$lock" \
        && ! grep -q 'qgone/' "$lock" && ! grep -q $'\t~/.kiro/skills/qreview/' "$lock" \
        && [ ! -e "$sb/.agent-playbook/deploy-lock.journal.tsv" ] \
        || own_fail "$l" "the lock records the backups and drops the retired and KEPT paths, and the journal is gone"
    if own_stub_used "$sb"; then
        grep -q '^settings --global chat.defaultAgent kiro_default$' "$sb.stub/calls.log" \
            && grep -q $'^setting\tkiro-cli/chat.defaultAgent\t"my_agent"$' "$lock" \
            || own_fail "$l" "chat.defaultAgent is set to kiro_default and the value it replaced is recorded"
    fi
}

own_check_rerun() {   # own_check_rerun <sandbox> <label> <log name> <sh|ps>
    own_rc "$3" 0 || own_fail "$2" "the re-run exits 0 (got $(cat "$TMPDIR_PARITY/$3.rc"))"
    cmp -s "$TMPDIR_PARITY/own-rerun-$4-1.tsv" "$TMPDIR_PARITY/own-rerun-$4-2.tsv" \
        || { own_fail "$2" "a re-run after the collisions writes nothing (no .bak growth)"
             diff "$TMPDIR_PARITY/own-rerun-$4-1.tsv" "$TMPDIR_PARITY/own-rerun-$4-2.tsv" | head -n 10 >&2 || true; }
    if own_stub_used "$1"; then
        ! grep -q 'chat.defaultAgent kiro_default' "$1.stub/calls.log" \
            && grep -q $'^setting\tkiro-cli/chat.defaultAgent\t"my_agent"$' "$1/.agent-playbook/deploy-lock.tsv" \
            || own_fail "$2" "a chat.defaultAgent that is kiro_default already is not set again, and its row is kept"
    fi
}

# own_plant_hold <sandbox>: a file held open (no delete sharing) by another process, a .bak of yours
# beside an edited file, and a second edit of a file setup backed up already.
own_plant_hold() {
    local sb="$1" k="$1/.kiro" f
    printf 'edited held\n' >> "$k/skills/qexplore-other/SKILL.md"
    cp "$k/skills/qexplore-other/SKILL.md" "$sb.held.edited"
    printf 'edited browser\n' >> "$k/skills/qbrowser-test/SKILL.md"
    cp "$k/skills/qbrowser-test/SKILL.md" "$sb.browser.edited"
    printf 'my own backup\n' > "$k/skills/qbrowser-test/SKILL.md.bak"
    printf 'edited2 authoring\n' > "$k/AUTHORING.md"
    rm -f "$sb.hold-ready" "$sb.hold-stop" "$sb.hold-skip" "$sb.hold-pid"
    if [ "$(uname -o 2>/dev/null)" = "Msys" ] && [ -n "$PS_BIN" ]; then
        # Windows: another process holds the file open without delete sharing, so it cannot move.
        # The holder gives up after five minutes, so a killed run never leaves it holding the file.
        f="$(parity_native_path "$k/skills/qexplore-other/SKILL.md")"
        "$PS_BIN" -NoProfile -NonInteractive -Command "\$f = [IO.File]::Open('$f', 'Open', 'Read', 'Read'); [IO.File]::WriteAllText('$(parity_native_path "$sb.hold-ready")', 'x'); \$n = 0; while (-not (Test-Path -LiteralPath '$(parity_native_path "$sb.hold-stop")') -and \$n -lt 3000) { Start-Sleep -Milliseconds 100; \$n++ }; \$f.Close()" < /dev/null > /dev/null 2>&1 &
        echo "$!" > "$sb.hold-pid"
        local i=0
        while [ ! -f "$sb.hold-ready" ] && [ "$i" -lt 300 ]; do sleep 0.1; i=$((i + 1)); done
    else
        # POSIX: an open file can always be renamed, so the folder is made read-only instead
        chmod a-w "$k/skills/qexplore-other"
        if : 2>/dev/null > "$k/skills/qexplore-other/.probe"; then
            rm -f "$k/skills/qexplore-other/.probe"
            chmod u+w "$k/skills/qexplore-other"
            : > "$sb.hold-skip"
        else
            : > "$sb.hold-ready"
        fi
    fi
}

own_release() {
    : > "$1.hold-stop"
    if [ -f "$1.hold-pid" ]; then wait "$(cat "$1.hold-pid")" 2>/dev/null || true; fi
    [ "$(uname -o 2>/dev/null)" = "Msys" ] || chmod u+w "$1/.kiro/skills/qexplore-other" 2>/dev/null || true
}

own_check_hold() {   # own_check_hold <sandbox> <label> <log name>
    local sb="$1" l="$2" k="$1/.kiro" lock="$1/.agent-playbook/deploy-lock.tsv" log="$TMPDIR_PARITY/$3.log"
    if [ -f "$sb.hold-skip" ]; then
        echo "OWNERSHIP SKIP ($l): a file cannot be made unmovable here (a read-only folder is still writable: root?); the failed-backup checks are skipped"
    elif [ ! -f "$sb.hold-ready" ]; then
        own_fail "$l" "the file holder did not start"
    else
    own_rc "$3" nonzero && grep -q "ERROR: could not back up .*qexplore-other.SKILL.md; left unchanged" "$log" \
        || own_fail "$l" "a backup that cannot be made prints an ERROR and the run ends non-zero (got $(cat "$TMPDIR_PARITY/$3.rc"))"
    cmp -s "$k/skills/qexplore-other/SKILL.md" "$sb.held.edited" && [ ! -e "$k/skills/qexplore-other/SKILL.md.bak" ] \
        && ! grep -q $'\t~/.kiro/skills/qexplore-other/SKILL.md\t' "$lock" \
        || own_fail "$l" "a file that cannot be backed up is left unchanged, with no .bak and no lock row"
    fi
    cmp -s "$k/skills/qbrowser-test/SKILL.md" "$sb.browser.edited" && own_is "$k/skills/qbrowser-test/SKILL.md.bak" "my own backup" \
        && grep -q 'WARN: .*qbrowser-test.SKILL.md.bak is not a backup setup made' "$log" \
        && ! grep -q $'\t~/.kiro/skills/qbrowser-test/SKILL.md\t' "$lock" \
        || own_fail "$l" "a .bak that is not setup's is left alone, and so is the file beside it"
    own_is "$k/AUTHORING.md.bak" "edited2 authoring" && cmp -s "$k/AUTHORING.md" "$REPO_ROOT/shared/AUTHORING.md" \
        || own_fail "$l" "a later backup replaces the earlier one setup made"
    [ ! -e "$sb/.agent-playbook/deploy-lock.journal.tsv" ] || own_fail "$l" "the journal is gone once the lock is written"
    if own_stub_used "$sb"; then
        ! grep -q 'chat.defaultAgent kiro_default' "$sb.stub/calls.log" \
            && grep -q $'^setting\tkiro-cli/chat.defaultAgent\t"my_agent"$' "$lock" \
            || own_fail "$l" "a chat.defaultAgent that cannot be read is not set, and the row is not replaced by -"
    fi
}

# own_plant_uninstall <sandbox>: an edited generated file, a .bak setup did not make, an edited .bak
# setup made, and a journal row left by an interrupted run.
own_plant_uninstall() {
    local sb="$1" k="$1/.kiro"
    printf 'edited qtest\n' >> "$k/skills/qtest/SKILL.md"
    cp "$k/skills/qtest/SKILL.md" "$1.qtest-skill.edited"
    printf 'stray\n' > "$k/steering/kiro-guidelines.md.bak"
    printf 'edited bak\n' >> "$k/agents/kiro_default.md.bak"
    printf 'my child\n' > "$k/agents/qdream_child.md.bak"
    printf 'backup\t~/.kiro/agents/qdream_child.md\t%s\n' "$(own_sha "$k/agents/qdream_child.md.bak")" \
        > "$sb/.agent-playbook/deploy-lock.journal.tsv"
    own_stub_state "$sb" '' fail-read
}

own_check_uninstall() {   # own_check_uninstall <sandbox> <label> <log name>
    local sb="$1" l="$2" k="$1/.kiro" lock="$1/.agent-playbook/deploy-lock.tsv"
    own_rc "$3" 0 || own_fail "$l" "uninstall exits 0 (got $(cat "$TMPDIR_PARITY/$3.rc"))"
    cmp -s "$k/skills/qtest/SKILL.md" "$sb.qtest-skill.edited" || own_fail "$l" "uninstall keeps an edited generated file"
    cmp -s "$k/skills/qdev/SKILL.md" "$sb.qdev-skill.edited" && [ ! -e "$k/skills/qdev/SKILL.md.bak" ] \
        && own_is "$k/skills/qdev/my-notes.md" mine && [ "$(find "$k/skills/qdev" -type f | wc -l)" -eq 2 ] \
        || own_fail "$l" "uninstall removes unedited generated files and restores the .bak setup made"
    [ ! -e "$k/skills/qexplore" ] || own_fail "$l" "uninstall removes a generated copy left unedited, folder included"
    own_is "$k/AUTHORING.md" "edited2 authoring" && [ ! -e "$k/AUTHORING.md.bak" ] \
        || own_fail "$l" "uninstall removes an unedited copy-file row and restores its .bak"
    [ -L "$k/steering/agents.md" ] && case "$(readlink "$k/steering/agents.md")" in *foreign-target.md) true ;; *) false ;; esac \
        && [ ! -e "$k/steering/agents.md.bak" ] && [ ! -L "$k/steering/agents.md.bak" ] \
        || own_fail "$l" "uninstall restores a backed-up foreign symlink"
    own_is "$k/steering/kiro-guidelines.md.bak" stray && [ ! -e "$k/steering/kiro-guidelines.md" ] \
        || own_fail "$l" "uninstall never restores a .bak setup did not make"
    [ ! -e "$k/agents/kiro_default.md" ] && [ -f "$k/agents/kiro_default.md.bak" ] \
        && grep -q 'KEPT: .*kiro_default.md.bak (changed since setup made it)' "$TMPDIR_PARITY/$3.log" \
        || own_fail "$l" "uninstall keeps a .bak edited since setup made it"
    own_is "$k/agents/qdream_child.md" "my child" && [ ! -e "$k/agents/qdream_child.md.bak" ] \
        || own_fail "$l" "uninstall restores a backup an interrupted run recorded only in the journal"
    own_is "$k/skills/qreview/SKILL.md" "user qreview" && own_is "$k/skills/qcouncil/SKILL.md" "user qcouncil" \
        && own_is "$k/skills/qhandoff/mine.md" mine && [ ! -e "$k/skills/qhandoff/SKILL.md" ] \
        || own_fail "$l" "uninstall leaves your own skill folders alone, and takes setup's file out of a mixed one"
    { [ ! -f "$lock" ] || ! grep -q $'\t~/.kiro/' "$lock"; } && [ ! -e "$sb/.agent-playbook/deploy-lock.journal.tsv" ] \
        || own_fail "$l" "uninstall drops the Kiro rows from the lock, and the journal"
    if own_stub_used "$sb"; then
        grep -q $'^setting\tkiro-cli/chat.defaultAgent\t"my_agent"$' "$lock" && ! grep -q 'chat.defaultAgent my_agent' "$sb.stub/calls.log" \
            || own_fail "$l" "an uninstall that cannot read chat.defaultAgent does not revert it and keeps its lock row"
    fi
}

own_check_revert() {   # own_check_revert <sandbox> <label> <log name>
    local sb="$1" lock="$1/.agent-playbook/deploy-lock.tsv"
    own_rc "$3" 0 || own_fail "$2" "the second uninstall exits 0"
    if own_stub_used "$sb"; then
        grep -q '^settings --global chat.defaultAgent my_agent$' "$sb.stub/calls.log" \
            && [ "$(cat "$sb.stub/value.json")" = '"my_agent"' ] && [ ! -f "$lock" ] \
            || own_fail "$2" "a later uninstall reverts chat.defaultAgent to the value setup replaced, and the lock goes"
    fi
}

# own_plant_nolock <sandbox>: a lock with a row setup never writes (a backslash key), files of a
# generated copy equal to what setup writes (and one that is not), and copy-file rows (one equal to
# its source only when letter case is ignored).
own_plant_nolock() {
    local sb="$1" k="$1/.kiro" lock="$1/.agent-playbook/deploy-lock.tsv"
    mkdir -p "$sb/.agent-playbook"
    printf '%s\n%s\t%s\t%s\n' "# agent-playbook deploy lock v1 (written by setup; kind<TAB>path<TAB>sha256)" \
        copy-file '~/.kiro/..\..\Documents\x' "$(printf '0%.0s' $(seq 64))" > "$lock"
    cp "$lock" "$sb.bad-lock"
    cp "$REPO_ROOT/shared/skills/qtest/plan-process.md" "$REPO_ROOT/shared/skills/qtest/run-process.md" "$k/skills/qtest/"
    cp "$REPO_ROOT/providers/kiro/agents/qdream_child.md" "$k/agents/qdream_child.md"
    tr 'a-z' 'A-Z' < "$REPO_ROOT/shared/AUTHORING.md" > "$k/AUTHORING.md"
    cp "$k/AUTHORING.md" "$sb.authoring.upper"
}

own_check_nolock() {   # own_check_nolock <sandbox> <label> <log name>
    local sb="$1" l="$2" k="$1/.kiro" lock="$1/.agent-playbook/deploy-lock.tsv"
    own_rc "$3" 0 || own_fail "$l" "the no-lock uninstall exits 0"
    [ ! -e "$lock" ] && cmp -s "$lock.bak" "$sb.bad-lock" \
        || own_fail "$l" "a lock with a backslash key is no lock, and it is moved to deploy-lock.tsv.bak"
    [ ! -e "$k/skills/qtest/plan-process.md" ] && [ ! -e "$k/skills/qtest/run-process.md" ] \
        && cmp -s "$k/skills/qtest/SKILL.md" "$sb.qtest-skill.edited" \
        || own_fail "$l" "with no lock, uninstall removes a generated copy's files equal to setup's output and keeps the rest"
    [ ! -e "$k/agents/qdream_child.md" ] && cmp -s "$k/AUTHORING.md" "$sb.authoring.upper" \
        || own_fail "$l" "with no lock, uninstall removes a copy-file equal to its source byte for byte, and only then"
    own_is "$k/skills/qreview/SKILL.md" "user qreview" && own_is "$k/skills/qreview/my-own.md" "my own" \
        || own_fail "$l" "with no lock, uninstall leaves your own files alone"
}

parity_sec_coexist() {
# --- COEXIST and TWIN-COEXIST: your own instruction files, on both twins --------
#
# Area E of plan 261111_DEPLOYMENT_OWNERSHIP_AND_CLIENT_LOAD_VERIFICATION (SC-2, SC-7). A fresh
# sandbox per fixture, deployed for Claude Code, Codex and Gemini CLI only (no Kiro, so it is quick):
#   a: your own ~/.claude/CLAUDE.md, ~/.codex/AGENTS.md, and ~/.gemini/GEMINI.md with a
#      settings.json that names it as a string beside another key;
#   b: your own ~/.gemini/GEMINI.md and no settings.json (and nothing at ~/.claude/CLAUDE.md); before
#      the uninstall, the lock's context.fileName row is moved to the lock journal, as a run that
#      stopped after the settings edit leaves it;
#   c: your own CLAUDE.md and GEMINI.md, both removed after run 1: run 2 links them and removes the
#      co-existence links and the context.fileName entry (the transition); its prior context.fileName
#      is a non-ASCII name, so the twins' byte-equal locks pin how each reads the helper's UTF-8; a
#      dry run before run 2 prints DRY lines only;
#   d: a settings.json with a comment (JSONC, which Gemini CLI accepts and the helper cannot keep):
#      your GEMINI.md stays, the side link is made, settings.json is untouched, a NOTE gives the line
#      to add, and verify-deployment.py reports the settings line MISSING (no double load);
#   e: a context.fileName list that already holds AGENT-PLAYBOOK.md: no setting row, nothing written;
#   f: settings.json is a link to a file of yours elsewhere: written through the link, the link kept;
#      CLAUDE.md is a link of yours to a file outside the repo (dotfiles): kept, the rules link beside;
#   g: a first run with no venv (AGENT_PLAYBOOK_TEST_VENV_DIR names a folder that does not exist yet,
#      outside the sandbox): setup makes the venv, then edits settings.json in that same run; a dry
#      run before it says the venv comes first and writes nothing;
#   h: (Gemini CLI only) a folder at the deploy lock path stops the run before any change; a file at
#      ~/.gemini/skills stops it after the settings edit, keeps the file, leaves no lock temp file
#      and leaves the setting row in the lock journal; the next run, once the cause is gone, records
#      it in the lock. Both twins get the same triggers and the same ERROR lines.
#   i: (Gemini CLI only) a helper that prints a success line and then exits 1
#      (AGENT_PLAYBOOK_TEST_GEMINI_HELPER names a stub): setup does not trust its output, keeps your
#      GEMINI.md, makes the side link, writes no setting row and prints the NOTE with the exit code.
# setup.sh deploys each (COEXIST, always runs) and, where PowerShell and Git Bash are both present,
# setup.ps1 deploys a twin of each (TWIN-COEXIST). Checked per sandbox: the outcomes below and the
# Claude memory rules links, verify-deployment.py, a second run writes nothing (mtime and inode, as
# NO-REWRITE; c excepted), the two twins' deploy locks and settings.json byte-equal, and an
# uninstall that gives every file of yours back and removes only what setup added. Never --yes (it
# would repoint the repo's memory link into the sandbox).
COEXIST_OK=1
TWIN_COEXIST_OK=1
TWIN_COEXIST_SKIPPED=0
local twin=1 fx t sb
local fixtures="a b c d e f g"
if [ -z "$PS_BIN" ] || [ ! -f "$SETUP_PS1_SCRIPT" ] || [ "$(uname -o 2>/dev/null)" != "Msys" ]; then
    twin=0
    TWIN_COEXIST_SKIPPED=1
    echo "TWIN-COEXIST SKIP: no PowerShell with Git Bash here -- the setup.ps1 co-existence checks are skipped."
fi
local twins="sh"
[ "$twin" -eq 1 ] && twins="sh ps"
for fx in $fixtures; do
    for t in $twins; do cx_plant "$TMPDIR_PARITY/cx-$t-$fx" "$fx"; done
done
# step <log suffix> <setup.sh args> -- <setup.ps1 args>: every sandbox, setup.sh in the background
# cx_run <fixture> <log suffix> <setup.sh args> <setup.ps1 args>: that fixture's twins, in the
# background (each sandbox is its own home); cx_wait waits for them.
CX_PIDS=()
cx_run() {
    local fx2="$1" suffix="$2" sh_args="$3" ps_args="$4" vsh="" vps=""
    if [ "$fx2" = g ]; then
        vsh="$TMPDIR_PARITY/cx-sh-g.venv"
        [ "$twin" -eq 0 ] || vps="$(cygpath -w "$TMPDIR_PARITY/cx-ps-g.venv")"
    fi
    # shellcheck disable=SC2086
    AGENT_PLAYBOOK_TEST_VENV_DIR="$vsh" own_run_sh "$TMPDIR_PARITY/cx-sh-$fx2" "cx-sh-$fx2-$suffix" $sh_args &
    CX_PIDS+=("$!")
    if [ "$twin" -eq 1 ]; then
        # shellcheck disable=SC2086
        AGENT_PLAYBOOK_TEST_VENV_DIR="$vps" own_run_ps "$TMPDIR_PARITY/cx-ps-$fx2" "cx-ps-$fx2-$suffix" $ps_args &
        CX_PIDS+=("$!")
    fi
}
cx_wait() {
    local pid
    for pid in "${CX_PIDS[@]}"; do wait "$pid" || true; done
    CX_PIDS=()
}
# cx_rc <fixture> <log suffix> <0|nonzero>: both twins' exit codes
cx_rc() {
    own_rc "cx-sh-$1-$2" "$3" || cx_fail sh "fixture $1: run $2 exits $3 (got $(cat "$TMPDIR_PARITY/cx-sh-$1-$2.rc"))"
    [ "$twin" -eq 0 ] || own_rc "cx-ps-$1-$2" "$3" \
        || cx_fail ps "fixture $1: run $2 exits $3 (got $(cat "$TMPDIR_PARITY/cx-ps-$1-$2.rc"))"
}
cx_all() {
    local suffix="$1" sh_args="$2" ps_args="$3" fx2
    for fx2 in $fixtures; do cx_run "$fx2" "$suffix" "$sh_args" "$ps_args"; done
    cx_wait
    for fx2 in $fixtures; do cx_rc "$fx2" "$suffix" 0; done
}
# a dry run on fixture g before its first run: no venv yet, so setup says the venv comes first
for t in $twins; do cx_snapshot "$TMPDIR_PARITY/cx-$t-g" > "$TMPDIR_PARITY/cx-$t-g.snap0"; done
cx_run g dry "--dry-run --providers claude,codex,gemini" "-DryRun -Providers claude,codex,gemini"
cx_wait
cx_rc g dry 0
for t in $twins; do cx_check_dry_g "$t"; done
cx_fixture_h
cx_fixture_i
cx_all 1 "--providers claude,codex,gemini" "-Providers claude,codex,gemini"
for fx in $fixtures; do
    for t in $twins; do
        sb="$TMPDIR_PARITY/cx-$t-$fx"
        cx_check_deploy "$sb" "$fx" "$t" "$TMPDIR_PARITY/cx-$t-$fx-1.log"
        cx_verify "$sb" "$t" "$fx"
        cx_snapshot "$sb" > "$sb.snap1"
    done
done
if [ "$twin" -eq 1 ]; then
    for fx in $fixtures; do
        cx_same "$TMPDIR_PARITY/cx-sh-$fx/.agent-playbook/deploy-lock.tsv" "$TMPDIR_PARITY/cx-ps-$fx/.agent-playbook/deploy-lock.tsv" \
            || { cx_fail ps "fixture $fx: the setup.sh and setup.ps1 deploy locks differ"
                 diff "$TMPDIR_PARITY/cx-sh-$fx/.agent-playbook/deploy-lock.tsv" "$TMPDIR_PARITY/cx-ps-$fx/.agent-playbook/deploy-lock.tsv" | head -n 10 >&2 || true; }
        cx_same "$(cx_settings_file "$TMPDIR_PARITY/cx-sh-$fx" "$fx")" "$(cx_settings_file "$TMPDIR_PARITY/cx-ps-$fx" "$fx")" \
            || cx_fail ps "fixture $fx: the setup.sh and setup.ps1 settings.json bytes differ"
    done
fi
# the transition: your own files go away before run 2
for t in $twins; do rm -f "$TMPDIR_PARITY/cx-$t-c/.gemini/GEMINI.md" "$TMPDIR_PARITY/cx-$t-c/.claude/CLAUDE.md"; done
# a dry run first: the cleanup is only printed
for t in $twins; do cx_snapshot "$TMPDIR_PARITY/cx-$t-c" > "$TMPDIR_PARITY/cx-$t-c.snap-dry"; done
cx_run c dry "--dry-run --providers claude,codex,gemini" "-DryRun -Providers claude,codex,gemini"
cx_wait
cx_rc c dry 0
for t in $twins; do cx_check_dry_c "$t"; done
cx_all 2 "--providers claude,codex,gemini" "-Providers claude,codex,gemini"
for fx in $fixtures; do
    for t in $twins; do
        sb="$TMPDIR_PARITY/cx-$t-$fx"
        if [ "$fx" = c ]; then cx_check_transition "$sb" "$t"; continue; fi
        cx_snapshot "$sb" > "$sb.snap2"
        cmp -s "$sb.snap1" "$sb.snap2" || { cx_fail "$t" "fixture $fx: a second run with co-existence active wrote something"
                                            diff "$sb.snap1" "$sb.snap2" | head -n 10 >&2 || true; }
    done
done
# fixture b: a run that stopped after editing settings.json, before writing its lock
for t in $twins; do cx_interrupt "$TMPDIR_PARITY/cx-$t-b" "$t"; done
cx_all 3 "--uninstall --providers claude,codex,gemini" "-Uninstall -Providers claude,codex,gemini"
for fx in $fixtures; do
    for t in $twins; do cx_check_uninstall "$TMPDIR_PARITY/cx-$t-$fx" "$fx" "$t"; done
done
if [ "$COEXIST_OK" -eq 1 ]; then
    echo "COEXIST OK: setup.sh keeps your CLAUDE.md and GEMINI.md beside the playbook (JSONC, listed, linked settings and a first run with no venv included), backs up Codex's, links the memory rules, re-runs without writing, cleans up once your file is gone, and uninstalls to your files"
else
    echo "  --- setup.sh logs (tail) ---" >&2
    tail -n 12 "$TMPDIR_PARITY/cx-sh-a-1.log" "$TMPDIR_PARITY/cx-sh-a-3.log" >&2 || true
fi
if [ "$twin" -eq 1 ] && [ "$TWIN_COEXIST_OK" -eq 1 ]; then
    echo "TWIN-COEXIST OK: setup.ps1 meets the same co-existence checks, with byte-equal deploy locks and settings.json"
elif [ "$twin" -eq 1 ]; then
    echo "  --- setup.ps1 logs (tail) ---" >&2
    tail -n 12 "$TMPDIR_PARITY/cx-ps-a-1.log" "$TMPDIR_PARITY/cx-ps-a-3.log" >&2 || true
fi
}

# Co-existence fixtures for parity_sec_coexist. cx_fail <sh|ps> <what>: one failed check.
cx_fail() {
    echo "COEXIST FAIL (setup.$1): $2" >&2
    if [ "$1" = sh ]; then COEXIST_OK=0; else TWIN_COEXIST_OK=0; fi
}

# cx_same <a> <b>: the same bytes, or both absent.
cx_same() {
    if [ ! -e "$1" ] && [ ! -e "$2" ]; then return 0; fi
    cmp -s "$1" "$2"
}

# The non-ASCII context.fileName fixture c starts from, and the list setup makes of it.
CX_C_PRIOR='{"context": {"fileName": "Ünï-名前.md"}}'
CX_C_ADDED='{"context": {"fileName": ["Ünï-名前.md", "AGENT-PLAYBOOK.md"]}}'

CX_JSONC='{
  // my own Gemini settings
  "theme": "dark"
}'

cx_plant() {   # cx_plant <sandbox> <fixture>
    local sb="$1"
    mkdir -p "$sb/.gemini"
    printf 'my gemini\n' > "$sb/.gemini/GEMINI.md"
    case "$2" in
        a) mkdir -p "$sb/.claude" "$sb/.codex"
           printf 'my claude\n' > "$sb/.claude/CLAUDE.md"
           printf 'my codex\n' > "$sb/.codex/AGENTS.md"
           printf '{\n    "context": {"fileName": "GEMINI.md"},\n    "keep": 1\n}\n' > "$sb/.gemini/settings.json" ;;
        b) if [ ! -e "$REPO_ROOT/memory/MEMORY.md" ]; then
               # no user memory (CI): a memory rules link an earlier run made, dangling now
               mkdir -p "$sb/.claude/rules"
               ln -s "$REPO_ROOT/memory/MEMORY.md" "$sb/.claude/rules/playbook-user-memory.md" 2>/dev/null || true
           fi ;;
        c) mkdir -p "$sb/.claude"
           printf 'my claude\n' > "$sb/.claude/CLAUDE.md"
           printf '%s\n' "$CX_C_PRIOR" > "$sb/.gemini/settings.json" ;;
        d) printf '%s\n' "$CX_JSONC" > "$sb/.gemini/settings.json" ;;
        e) printf '{"context": {"fileName": ["GEMINI.md", "AGENT-PLAYBOOK.md"]}}\n' > "$sb/.gemini/settings.json" ;;
        f) mkdir -p "$sb/dotfiles" "$sb/.claude"
           printf 'my dotfiles claude\n' > "$sb/dotfiles/claude.md"
           MSYS=winsymlinks:nativestrict ln -s "$sb/dotfiles/claude.md" "$sb/.claude/CLAUDE.md"
           printf '{"keep": 1}\n' > "$sb/dotfiles/gemini-settings.json"
           MSYS=winsymlinks:nativestrict ln -s "$sb/dotfiles/gemini-settings.json" "$sb/.gemini/settings.json" ;;
    esac
}

# cx_settings_file <sandbox> <fixture>: the file that holds the settings (f: the link's target).
cx_settings_file() {
    if [ "$2" = f ]; then printf '%s' "$1/dotfiles/gemini-settings.json"; else printf '%s' "$1/.gemini/settings.json"; fi
}

# cx_link_to <link> <repo-relative target>: a link whose text ends with that target (either slash).
cx_link_to() {
    [ -L "$1" ] || return 1
    case "$(readlink "$1" | tr '\\' '/')" in *"$2") return 0 ;; *) return 1 ;; esac
}

cx_absent() { [ ! -e "$1" ] && [ ! -L "$1" ]; }

# cx_snapshot <sandbox>: nr_snapshot without PowerShell's own startup cache, which pwsh rewrites under a
# sandbox USERPROFILE on every start (AppData/Local/Microsoft/PowerShell, and the folders above it,
# which its first start makes); setup.ps1 never writes there.
cx_snapshot() {
    nr_snapshot "$1" | grep -Ev $'^AppData(/Local(/Microsoft(/PowerShell(/.*)?)?)?)?\t' || true
}

# cx_json <file> <python expression over d>: the file parses as JSON and the expression holds.
cx_json() {
    MSYS_NO_PATHCONV=1 parity_python -c 'import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
sys.exit(0 if eval(sys.argv[2]) else 1)' "$(parity_native_path "$1")" "$2" 2>/dev/null
}

cx_check_deploy() {   # cx_check_deploy <sandbox> <fixture> <sh|ps> <log>
    local sb="$1" fx="$2" t="$3" log="$4" lock="$1/.agent-playbook/deploy-lock.tsv" n want=1
    local names='d["context"]["fileName"] == ["GEMINI.md", "AGENT-PLAYBOOK.md"]'
    if [ -e "$REPO_ROOT/memory/MEMORY.md" ] && [ -e "$REPO_ROOT/memory/HIGHER_ORDER.md" ]; then
        cx_link_to "$sb/.claude/rules/playbook-user-memory.md" memory/MEMORY.md \
            && cx_link_to "$sb/.claude/rules/playbook-higher-order.md" memory/HIGHER_ORDER.md \
            || cx_fail "$t" "fixture $fx: the Claude memory rules links point to memory/MEMORY.md and memory/HIGHER_ORDER.md"
    else
        cx_absent "$sb/.claude/rules/playbook-user-memory.md" && grep -q 'playbook-user-memory.md is not linked yet' "$log" \
            || cx_fail "$t" "fixture $fx: with no user memory, no dangling memory rules link is made, and setup says so"
        if [ "$fx" = b ] && [ "$t" = sh ]; then
            grep -q 'playbook-user-memory.md (dangling: there is no' "$log" \
                || cx_fail "$t" "fixture b: a dangling memory rules link an earlier run made is removed, and setup says so"
        fi
    fi
    # in every fixture your GEMINI.md stays and the side link is made; the settings edit varies
    own_is "$sb/.gemini/GEMINI.md" "my gemini" && cx_link_to "$sb/.gemini/AGENT-PLAYBOOK.md" shared/AGENTS.md \
        && cx_absent "$sb/.gemini/GEMINI.md.bak" \
        || cx_fail "$t" "fixture $fx: your GEMINI.md stays (no .bak) and AGENT-PLAYBOOK.md links beside it"
    cx_absent "$sb/.agent-playbook/deploy-lock.journal.tsv" || cx_fail "$t" "fixture $fx: the lock write removes the journal"
    case "$fx" in
        a) cx_json "$sb/.gemini/settings.json" "$names" || cx_fail "$t" "fixture a: AGENT-PLAYBOOK.md joins context.fileName"
           own_is "$sb/.claude/CLAUDE.md" "my claude" && cx_link_to "$sb/.claude/rules/agent-playbook.md" shared/AGENTS.md \
               && grep -q 'CLAUDE.md is your own file' "$log" \
               || cx_fail "$t" "your CLAUDE.md stays and ~/.claude/rules/agent-playbook.md links beside it, said once"
           cx_link_to "$sb/.codex/AGENTS.md" shared/AGENTS.md && own_is "$sb/.codex/AGENTS.md.bak" "my codex" \
               && grep -q 'Codex has no way to load a second global instructions file' "$log" \
               || cx_fail "$t" "Codex has no co-existence: your AGENTS.md goes to .bak, the link is made, and setup says so"
           cx_json "$sb/.gemini/settings.json" 'd["keep"] == 1 and len(d) == 2' \
               || cx_fail "$t" "the settings.json edit keeps every other key"
           grep -q $'^setting\tgemini/context.fileName\t"GEMINI.md"$' "$lock" && grep -q $'^backup\t~/.codex/AGENTS.md\t' "$lock" \
               || cx_fail "$t" "the lock records the prior context.fileName and the Codex backup" ;;
        b|g) cx_json "$sb/.gemini/settings.json" "$names" || cx_fail "$t" "fixture $fx: AGENT-PLAYBOOK.md joins context.fileName"
           cx_link_to "$sb/.claude/CLAUDE.md" shared/AGENTS.md && cx_absent "$sb/.claude/rules/agent-playbook.md" \
               || cx_fail "$t" "fixture $fx: an empty CLAUDE.md path is linked as before, with no rules link beside it"
           grep -q $'^setting\tgemini/context.fileName\t+$' "$lock" \
               || cx_fail "$t" "fixture $fx: with no settings.json, the lock records + (setup created it)"
           if [ "$fx" = g ]; then
               grep -q 'CREATED: ' "$log" && [ -d "$TMPDIR_PARITY/cx-$t-g.venv" ] \
                   || cx_fail "$t" "fixture g: the first run with no venv creates it (in the test folder)"
           fi ;;
        c) [ "$(cat "$sb/.gemini/settings.json")" = "$CX_C_ADDED" ] \
               || cx_fail "$t" "fixture c: AGENT-PLAYBOOK.md joins a non-ASCII context.fileName (got $(cat "$sb/.gemini/settings.json"))"
           grep -qF "$(printf 'setting\tgemini/context.fileName\t"Ünï-名前.md"')" "$lock" \
               || cx_fail "$t" "fixture c: the lock records the non-ASCII prior as UTF-8 JSON"
           cx_link_to "$sb/.claude/rules/agent-playbook.md" shared/AGENTS.md \
               || cx_fail "$t" "fixture c: the Claude rules link is made beside your CLAUDE.md" ;;
        d) [ "$(cat "$sb/.gemini/settings.json")" = "$CX_JSONC" ] \
               || cx_fail "$t" "fixture d: a settings.json with comments is left as it was"
           grep -qF "add \"AGENT-PLAYBOOK.md\" to context.fileName in ~/.gemini/settings.json by hand" "$log" \
               || cx_fail "$t" "fixture d: a NOTE gives the exact line to add by hand"
           want=0 ;;
        e) [ "$(cat "$sb/.gemini/settings.json")" = '{"context": {"fileName": ["GEMINI.md", "AGENT-PLAYBOOK.md"]}}' ] \
               || cx_fail "$t" "fixture e: a list that already holds the name is not written"
           want=0 ;;
        f) [ -L "$sb/.gemini/settings.json" ] && cx_json "$sb/dotfiles/gemini-settings.json" "$names" \
               && cx_json "$sb/dotfiles/gemini-settings.json" 'd["keep"] == 1' \
               || cx_fail "$t" "fixture f: a linked settings.json is written through the link, and the link stays"
           cx_link_to "$sb/.claude/CLAUDE.md" dotfiles/claude.md && [ "$(cat "$sb/.claude/CLAUDE.md")" = "my dotfiles claude" ] \
               && cx_absent "$sb/.claude/CLAUDE.md.bak" && cx_link_to "$sb/.claude/rules/agent-playbook.md" shared/AGENTS.md \
               || cx_fail "$t" "fixture f: your CLAUDE.md linked from your dotfiles stays (no .bak), the rules link beside it"
           grep -q $'^setting\tgemini/context.fileName\t-$' "$lock" \
               || cx_fail "$t" "fixture f: the lock records - (the file held no value)" ;;
    esac
    n="$(grep -c $'^setting\t' "$lock" 2>/dev/null || true)"
    [ "${n:-0}" = "$want" ] || cx_fail "$t" "fixture $fx: $want setting row(s) in the lock (got ${n:-0})"
}

cx_verify() {   # cx_verify <sandbox> <sh|ps> <fixture>: verify-deployment.py on the co-existence sandbox
    local sb="$1" rc=0
    HOME="$sb" XDG_CONFIG_HOME="$sb/.config" USERPROFILE="$(parity_native_path "$sb")" \
        APPDATA="$(parity_native_path "$sb/AppData/Roaming")" "$VERIFY_PY" -I "$VERIFY_SCRIPT" > "$sb.verify" 2>&1 || rc=$?
    if [ "$3" = d ]; then
        # JSONC: setup could not add the name, so verify asks for it; the playbook does not load twice
        [ "$rc" -eq 1 ] && grep -q $'^MISSING\t.*settings.json\tcontext.fileName-lacks=AGENT-PLAYBOOK.md' "$sb.verify" \
            && grep -q $'^NOT_SYMLINK\t.*GEMINI.md\tuser-file-kept-without-the-playbook' "$sb.verify" \
            && ! grep -q $'^DRIFTED\t' "$sb.verify" \
            || { cx_fail "$2" "fixture d: verify-deployment.py reports the settings line MISSING, and no double load"
                 grep -E $'^(MISSING|WRONG_TARGET|NOT_SYMLINK|DRIFTED)\t' "$sb.verify" | head -n 5 >&2 || true; }
        return 0
    fi
    if [ "$3" = c2 ] && [ "$rc" -eq 0 ]; then return 0; fi
    if [ "$3" != c2 ] && [ "$rc" -eq 0 ] && grep -q $'^OK\t.*GEMINI.md\tuser-file-kept' "$sb.verify"; then
        return 0
    fi
    cx_fail "$2" "verify-deployment.py is clean on the co-existence sandbox $(basename "$sb")"
    grep -E $'^(MISSING|WRONG_TARGET|NOT_SYMLINK|DRIFTED)\t' "$sb.verify" | head -n 5 >&2 || true
}

# cx_check_transition <sandbox> <sh|ps>: fixture c after run 2, your files gone: the instruction files
# are the links, the co-existence links and the context.fileName entry are gone, the lock row too.
cx_check_transition() {
    local sb="$1" t="$2" lock="$1/.agent-playbook/deploy-lock.tsv"
    own_rc "cx-$t-c-2" 0 || return 0
    cx_link_to "$sb/.gemini/GEMINI.md" shared/AGENTS.md && cx_absent "$sb/.gemini/AGENT-PLAYBOOK.md" \
        || cx_fail "$t" "fixture c: with your GEMINI.md gone, GEMINI.md is linked and the side link removed"
    cx_link_to "$sb/.claude/CLAUDE.md" shared/AGENTS.md && cx_absent "$sb/.claude/rules/agent-playbook.md" \
        || cx_fail "$t" "fixture c: with your CLAUDE.md gone, CLAUDE.md is linked and the rules link removed"
    [ "$(cat "$sb/.gemini/settings.json")" = "$CX_C_PRIOR" ] \
        || cx_fail "$t" "fixture c: the context.fileName entry setup added is taken out again (got $(cat "$sb/.gemini/settings.json"))"
    ! grep -q 'gemini/context.fileName' "$lock" || cx_fail "$t" "fixture c: the lock drops the context.fileName row"
    cx_verify "$sb" "$t" c2
}

# cx_interrupt <sandbox> <sh|ps>: the lock as a run leaves it that stopped after the settings edit:
# the setting row in the journal only.
cx_interrupt() {
    local lock="$1/.agent-playbook/deploy-lock.tsv"
    grep $'^setting\tgemini/context.fileName\t' "$lock" > "$1/.agent-playbook/deploy-lock.journal.tsv" \
        || cx_fail "$2" "fixture b: the lock holds the context.fileName row before the interruption"
    grep -v $'^setting\tgemini/context.fileName\t' "$lock" > "$lock.tmp" || true
    mv -f "$lock.tmp" "$lock"
}

# cx_check_dry_g <sh|ps>: the dry run on fixture g wrote nothing (no venv either) and said the venv
# comes first.
cx_check_dry_g() {
    local t="$1" sb="$TMPDIR_PARITY/cx-$1-g" log="$TMPDIR_PARITY/cx-$1-g-dry.log"
    cx_snapshot "$sb" > "$sb.snap-dry0"
    cmp -s "$sb.snap0" "$sb.snap-dry0" && cx_absent "$TMPDIR_PARITY/cx-$t-g.venv" \
        && grep -q 'DRY: the venv is created first; then AGENT-PLAYBOOK.md is added to context.fileName' "$log" \
        || cx_fail "$t" "fixture g: a dry run with no venv writes nothing and says the venv is created first"
}

# cx_check_dry_c <sh|ps>: the dry run of the transition prints the cleanup and changes nothing.
cx_check_dry_c() {
    local t="$1" sb="$TMPDIR_PARITY/cx-$1-c" log="$TMPDIR_PARITY/cx-$1-c-dry.log"
    cx_snapshot "$sb" > "$sb.snap-dry1"
    cmp -s "$sb.snap-dry" "$sb.snap-dry1" && grep -q 'DRY: remove AGENT-PLAYBOOK.md from context.fileName' "$log" \
        && ! grep -q '^  REMOVED: ' "$log" \
        || cx_fail "$t" "fixture c: a dry run prints DRY for the context.fileName cleanup and writes nothing"
}

# cx_fixture_h: a run that stops after the settings edit, then the run after it (Gemini CLI only).
cx_fixture_h() {
    local t sb j
    for t in $twins; do
        sb="$TMPDIR_PARITY/cx-$t-h"
        mkdir -p "$sb/.gemini" "$sb/.agent-playbook"
        printf 'my gemini\n' > "$sb/.gemini/GEMINI.md"
        mkdir -p "$sb/.agent-playbook/deploy-lock.tsv"
    done
    # run 0: a folder at the lock path stops both twins before any change
    cx_run h 0 "--providers gemini" "-Providers gemini"
    cx_wait
    cx_rc h 0 nonzero
    for t in $twins; do
        sb="$TMPDIR_PARITY/cx-$t-h"
        cx_absent "$sb/.gemini/settings.json" && cx_absent "$sb/.gemini/AGENT-PLAYBOOK.md" \
            && [ -z "$(ls -A "$sb/.agent-playbook/deploy-lock.tsv")" ] \
            && grep -q 'deploy-lock.tsv is not a file; setup stopped before any change' "$TMPDIR_PARITY/cx-$t-h-0.log" \
            || cx_fail "$t" "fixture h: a folder at the lock path stops the run before any change, with an ERROR"
        rmdir "$sb/.agent-playbook/deploy-lock.tsv"
        printf 'not a folder\n' > "$sb/.gemini/skills"
    done
    # run 1: a file at ~/.gemini/skills stops both twins after the settings edit
    cx_run h 1 "--providers gemini" "-Providers gemini"
    cx_wait
    cx_rc h 1 nonzero
    for t in $twins; do
        sb="$TMPDIR_PARITY/cx-$t-h"; j="$sb/.agent-playbook/deploy-lock.journal.tsv"
        grep -q $'^setting\tgemini/context.fileName\t+$' "$j" 2>/dev/null \
            && cx_json "$sb/.gemini/settings.json" 'd["context"]["fileName"] == ["GEMINI.md", "AGENT-PLAYBOOK.md"]' \
            && grep -q 'skills is a file, not a folder; setup stopped here' "$TMPDIR_PARITY/cx-$t-h-1.log" \
            && [ "$(cat "$sb/.gemini/skills")" = "not a folder" ] \
            && [ -z "$(find "$sb/.agent-playbook" -name 'deploy-lock.tsv.tmp-*')" ] \
            || cx_fail "$t" "fixture h: a file at ~/.gemini/skills stops the run with an ERROR, keeps the file and leaves the setting row in the lock journal"
        rm -f "$sb/.gemini/skills"
    done
    cx_run h 2 "--providers gemini" "-Providers gemini"
    cx_wait
    cx_rc h 2 0
    for t in $twins; do
        sb="$TMPDIR_PARITY/cx-$t-h"
        grep -q $'^setting\tgemini/context.fileName\t+$' "$sb/.agent-playbook/deploy-lock.tsv" 2>/dev/null \
            && cx_absent "$sb/.agent-playbook/deploy-lock.journal.tsv" \
            || cx_fail "$t" "fixture h: the next run records the journalled setting row in the lock"
    done
}

# cx_fixture_i: a helper that crashes after printing a success line (Gemini CLI only).
cx_fixture_i() {
    local t sb stub="$TMPDIR_PARITY/cx-crash-helper.py"
    printf 'import sys\nprint("added prior=-")\nsys.exit(1)\n' > "$stub"
    for t in $twins; do
        sb="$TMPDIR_PARITY/cx-$t-i"
        mkdir -p "$sb/.gemini" "$sb/.agent-playbook"
        printf 'my gemini\n' > "$sb/.gemini/GEMINI.md"
    done
    AGENT_PLAYBOOK_TEST_GEMINI_HELPER="$(parity_native_path "$stub")"
    export AGENT_PLAYBOOK_TEST_GEMINI_HELPER
    cx_run i 1 "--providers gemini" "-Providers gemini"
    cx_wait
    unset AGENT_PLAYBOOK_TEST_GEMINI_HELPER
    cx_rc i 1 0
    for t in $twins; do
        sb="$TMPDIR_PARITY/cx-$t-i"
        [ "$(cat "$sb/.gemini/GEMINI.md")" = "my gemini" ] && [ ! -L "$sb/.gemini/GEMINI.md" ] \
            && cx_link_to "$sb/.gemini/AGENT-PLAYBOOK.md" shared/AGENTS.md \
            && cx_absent "$sb/.gemini/settings.json" \
            && ! grep -qs $'^setting\t' "$sb/.agent-playbook/deploy-lock.tsv" "$sb/.agent-playbook/deploy-lock.journal.tsv" \
            && grep -qF 'cannot be edited (the helper failed (exit 1)); add "AGENT-PLAYBOOK.md" to context.fileName' "$TMPDIR_PARITY/cx-$t-i-1.log" \
            || cx_fail "$t" "fixture i: a helper that exits 1 is not trusted: GEMINI.md kept, side link made, no setting row, the NOTE names the exit code"
    done
}

cx_check_uninstall() {   # cx_check_uninstall <sandbox> <fixture> <sh|ps>
    local sb="$1" fx="$2" t="$3" lock="$1/.agent-playbook/deploy-lock.tsv"
    cx_absent "$sb/.gemini/AGENT-PLAYBOOK.md" \
        && cx_absent "$sb/.claude/rules/playbook-user-memory.md" && cx_absent "$sb/.claude/rules/playbook-higher-order.md" \
        && cx_absent "$sb/.claude/rules" \
        || cx_fail "$t" "fixture $fx: uninstall removes the side and memory rules links, and the rules folder left empty"
    [ "$fx" = c ] || own_is "$sb/.gemini/GEMINI.md" "my gemini" || cx_fail "$t" "fixture $fx: uninstall keeps your GEMINI.md"
    { [ ! -f "$lock" ] || ! grep -q 'gemini/context.fileName' "$lock"; } && cx_absent "$sb/.agent-playbook/deploy-lock.journal.tsv" \
        || cx_fail "$t" "fixture $fx: uninstall drops the context.fileName row from the lock and the journal"
    case "$fx" in
        a) own_is "$sb/.claude/CLAUDE.md" "my claude" || cx_fail "$t" "uninstall never touches your CLAUDE.md"
           own_is "$sb/.codex/AGENTS.md" "my codex" && cx_absent "$sb/.codex/AGENTS.md.bak" \
               || cx_fail "$t" "uninstall restores your Codex AGENTS.md from its .bak"
           cx_json "$sb/.gemini/settings.json" 'd == {"context": {"fileName": "GEMINI.md"}, "keep": 1}' \
               || cx_fail "$t" "uninstall takes the playbook's name out of context.fileName and restores the string" ;;
        b|g) cx_absent "$sb/.claude/CLAUDE.md" || cx_fail "$t" "fixture $fx: uninstall removes the CLAUDE.md link"
           cx_absent "$sb/.gemini/settings.json" \
               || cx_fail "$t" "fixture $fx: uninstall deletes the settings.json setup created (b: from the journal row)" ;;
        c) cx_absent "$sb/.claude/CLAUDE.md" && cx_absent "$sb/.gemini/GEMINI.md" \
               || cx_fail "$t" "fixture c: uninstall removes the CLAUDE.md and GEMINI.md links"
           [ "$(cat "$sb/.gemini/settings.json")" = "$CX_C_PRIOR" ] \
               || cx_fail "$t" "fixture c: uninstall leaves settings.json as it was" ;;
        d) [ "$(cat "$sb/.gemini/settings.json")" = "$CX_JSONC" ] || cx_fail "$t" "fixture d: uninstall leaves settings.json as it was" ;;
        e) [ "$(cat "$sb/.gemini/settings.json")" = '{"context": {"fileName": ["GEMINI.md", "AGENT-PLAYBOOK.md"]}}' ] \
               || cx_fail "$t" "fixture e: uninstall leaves a name setup did not add" ;;
        f) [ -L "$sb/.gemini/settings.json" ] && [ "$(cat "$sb/dotfiles/gemini-settings.json")" = '{"keep": 1}' ] \
               || cx_fail "$t" "fixture f: uninstall restores the linked file and keeps the link"
           cx_link_to "$sb/.claude/CLAUDE.md" dotfiles/claude.md || cx_fail "$t" "fixture f: uninstall keeps your linked CLAUDE.md" ;;
    esac
}

# --- Parallel sections -----------------------------------------------------
#
# Every section above is a function. They share nothing but the preamble
# (PS_BIN, python_resolves, TMPDIR_PARITY -- each writes only its own
# distinctly named files there), so they run as parallel background jobs;
# SETUP-PARITY needs SETUP-VERIFY's sandbox, so those two run in one job, in
# order. Each job keeps `set -e` and writes its stdout, stderr and its flags
# (declare -p) to its own files; the parent replays the output in the original
# section order and loads the flags. A job that dies before writing its flags
# fails its section explicitly -- the flags default to 0, never to a pass.

MERGE_OK=0; MERGE_SKIPPED=0; RENDER_OK=0; RENDER_SKIPPED=0
SETUP_VERIFY_OK=0; SETUP_PARITY_OK=0; SETUP_PARITY_SKIPPED=0
NO_REWRITE_OK=0; OWNERSHIP_OK=0; TWIN_OWNERSHIP_OK=0; TWIN_OWNERSHIP_SKIPPED=0
COEXIST_OK=0; TWIN_COEXIST_OK=0; TWIN_COEXIST_SKIPPED=0

PARITY_JOBS_DIR="$TMPDIR_PARITY/jobs"
mkdir -p "$PARITY_JOBS_DIR"

# parity_step <name> <function> <flag vars...>
parity_step() {
    local name="$1" fn="$2" start="$SECONDS"; shift 2
    "$fn" > "$PARITY_JOBS_DIR/$name.out" 2> "$PARITY_JOBS_DIR/$name.err"
    declare -p "$@" > "$PARITY_JOBS_DIR/$name.status"
    # start and end, in seconds since this script began: what to profile next
    echo "$start $SECONDS" > "$PARITY_JOBS_DIR/$name.secs"
}

# parity_setup_ps1_deploy: SETUP-PARITY's setup.ps1 deploy into its own
# sandbox. It reads nothing SETUP-VERIFY writes (only the tree comparison
# afterwards does), so the job below starts it first, in the background, and
# SETUP-PARITY waits for it: the setup.sh and setup.ps1 deploys overlap instead
# of running back to back, the longest chain of this script. Records the exit
# code in setup-parity-sandbox2.rc beside its log. Runs only when SETUP-PARITY
# will (PowerShell and setup.ps1 present); the section's own SKIP lines cover
# the rest.
parity_setup_ps1_deploy() {
    local sb="$TMPDIR_PARITY/setup-parity-sandbox2" code
    local profile_w="$sb" appdata_w="$sb/AppData/Roaming" ps1_w="$SETUP_PS1_SCRIPT"
    mkdir -p "$sb"
    if command -v cygpath >/dev/null 2>&1; then
        profile_w="$(cygpath -w "$profile_w")"
        appdata_w="$(cygpath -w "$appdata_w")"
        ps1_w="$(cygpath -w "$ps1_w")"
    fi
    if USERPROFILE="$profile_w" APPDATA="$appdata_w" AGENT_PLAYBOOK_SKIP_KIRO_CLI=1 \
        "$PS_BIN" -NoProfile -NonInteractive -File "$ps1_w" > "$sb.log" 2>&1; then
        code=0
    else
        code=$?
    fi
    echo "$code" > "$sb.rc"
}

PARITY_PIDS=()
# The EXIT trap makes the job wait for the deploy even when a section aborts
# under set -e, so the deploy is never left writing into TMPDIR_PARITY while the
# script's own EXIT trap removes it. The deploy's own errors (mkdir, cygpath) go
# to a file SETUP-PARITY prints when the deploy recorded no exit code.
( SP_DEPLOY_PID=""
  if [ -n "$PS_BIN" ] && [ -f "$SETUP_PS1_SCRIPT" ] && [ "$(uname -o 2>/dev/null)" = "Msys" ]; then
      parity_setup_ps1_deploy 2> "$TMPDIR_PARITY/setup-parity-deploy.err" &
      SP_DEPLOY_PID="$!"
      trap 'wait "$SP_DEPLOY_PID" 2>/dev/null || true' EXIT
  fi
  parity_step setup_verify parity_sec_setup_verify SETUP_VERIFY_OK NO_REWRITE_OK
  parity_step setup_parity parity_sec_setup_parity SETUP_PARITY_OK SETUP_PARITY_SKIPPED
  parity_step ownership parity_sec_ownership OWNERSHIP_OK TWIN_OWNERSHIP_OK TWIN_OWNERSHIP_SKIPPED ) &
PARITY_PIDS+=("$!")
( parity_step merge parity_sec_merge MERGE_OK MERGE_SKIPPED ) & PARITY_PIDS+=("$!")
( parity_step render parity_sec_render RENDER_OK RENDER_SKIPPED ) & PARITY_PIDS+=("$!")
( parity_step coexist parity_sec_coexist COEXIST_OK TWIN_COEXIST_OK TWIN_COEXIST_SKIPPED ) & PARITY_PIDS+=("$!")

for pid in "${PARITY_PIDS[@]}"; do
    wait "$pid" || true
done

# Replay in the original section order, then load each section's flags.
for name in setup_verify merge render setup_parity ownership coexist; do
    [ -f "$PARITY_JOBS_DIR/$name.out" ] && cat "$PARITY_JOBS_DIR/$name.out"
    [ -f "$PARITY_JOBS_DIR/$name.err" ] && cat "$PARITY_JOBS_DIR/$name.err" >&2
    if [ -f "$PARITY_JOBS_DIR/$name.status" ]; then
        # shellcheck disable=SC1090
        . "$PARITY_JOBS_DIR/$name.status"
    else
        echo "PARITY-HARNESS FAIL: section '$name' aborted before reporting (see its output above); counted as failed" >&2
        PARITY_FAIL=1
    fi
done
# Section timings (seconds since start; sections run in four parallel jobs, see above)
for name in setup_verify setup_parity ownership merge render coexist; do
    if [ -f "$PARITY_JOBS_DIR/$name.secs" ]; then
        read -r t0 t1 < "$PARITY_JOBS_DIR/$name.secs"
        echo "TIMING: $name ran from ${t0} s to ${t1} s ($((t1 - t0)) s)"
    fi
done
echo "TIMING: total ${SECONDS} s"

# --- Verdict --------------------------------------------------------------

if [ "$PARITY_FAIL" -eq 0 ] && [ "$INVENTORY_OK" -eq 1 ] && [ "$SETUP_VERIFY_OK" -eq 1 ] && [ "$NO_REWRITE_OK" -eq 1 ] \
    && [ "$OWNERSHIP_OK" -eq 1 ] && [ "$MERGE_OK" -eq 1 ] && [ "$RENDER_OK" -eq 1 ] && [ "$SETUP_PARITY_OK" -eq 1 ] \
    && [ "$TWIN_OWNERSHIP_OK" -eq 1 ] && [ "$COEXIST_OK" -eq 1 ] && [ "$TWIN_COEXIST_OK" -eq 1 ]; then
    echo "PARITY OK"

    # Loud warning when assertions were skipped (SKIPPED leaves *_OK=1, so
    # the run is non-failing but NOT a full green)
    SKIPPED_COUNT=0
    [ "$MERGE_SKIPPED" -eq 1 ] && SKIPPED_COUNT=$((SKIPPED_COUNT + 1))
    [ "$RENDER_SKIPPED" -eq 1 ] && SKIPPED_COUNT=$((SKIPPED_COUNT + 1))
    [ "$SETUP_PARITY_SKIPPED" -eq 1 ] && SKIPPED_COUNT=$((SKIPPED_COUNT + 1))
    [ "$TWIN_OWNERSHIP_SKIPPED" -eq 1 ] && SKIPPED_COUNT=$((SKIPPED_COUNT + 1))
    [ "$TWIN_COEXIST_SKIPPED" -eq 1 ] && SKIPPED_COUNT=$((SKIPPED_COUNT + 1))

    # Count kept in step with the tally above by hand -- there is no derived
    # total, so a new assertion means editing both.
    if [ "$SKIPPED_COUNT" -gt 0 ]; then
        echo ""
        echo "WARNING: $SKIPPED_COUNT of 5 parity assertions SKIPPED (see SKIP notices above for reasons)."
        echo "         This is NOT a full green — only deployment-inventory agreement was verified."
        echo ""
    fi

    echo "  verify-deployment.py --list ↔ setup-model expected inventory: $(wc -l < "$VERIFY_LIST") entries match (overlay copy-dir + merge-file rows covered)"
    echo "  setup.sh sandboxed deploy ↔ verify-deployment.py: PASS (clean deploy under a sandbox HOME)"
    echo "  setup.sh re-run on an unchanged tree: PASS (nothing written)"
    echo "  setup.sh ownership rules (deploy lock): PASS (planted collisions kept, backed up, replaced, retired, uninstalled)"
    echo "  setup.sh co-existence with your own instruction files: PASS (kept beside the playbook, Codex backed up, re-run writes nothing, uninstalled)"
    if [ "$MERGE_SKIPPED" -eq 1 ]; then
        echo "  cross-shell merge-equivalence: SKIPPED (see notice above)"
    else
        echo "  cross-shell merge-equivalence: PASS (PS Merge-Overlay == bash merge_overlay)"
    fi
    if [ "$RENDER_SKIPPED" -eq 1 ]; then
        echo "  cross-shell render-equivalence: SKIPPED (see notice above)"
    else
        echo "  cross-shell render-equivalence: PASS (PS Render-Template == bash render_template)"
    fi
    if [ "$SETUP_PARITY_SKIPPED" -eq 1 ]; then
        echo "  setup sh/ps1 sandboxed tree-parity: SKIPPED (see notice above)"
    else
        echo "  setup sh/ps1 sandboxed tree-parity: PASS (ps1 sandbox == sh sandbox, tree + verify-deployment.py clean)"
    fi
    if [ "$TWIN_OWNERSHIP_SKIPPED" -eq 1 ]; then
        echo "  setup.ps1 deploy lock and ownership rules: SKIPPED (see notice above)"
    else
        echo "  setup.ps1 deploy lock and ownership rules: PASS (locks agree; the same collisions checked)"
    fi
    if [ "$TWIN_COEXIST_SKIPPED" -eq 1 ]; then
        echo "  setup.ps1 co-existence: SKIPPED (see notice above)"
    else
        echo "  setup.ps1 co-existence: PASS (the same checks; deploy locks byte-equal)"
    fi
    exit 0
fi

echo "PARITY FAILED" >&2
exit 1
