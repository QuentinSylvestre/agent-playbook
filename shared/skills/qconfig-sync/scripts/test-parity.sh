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
#      THREE assertions carry a *_SKIPPED variable and are therefore tallied:
#      the setup pair plus merge-equivalence and render-equivalence. The
#      inventory assertion and SETUP-VERIFY (§ below) are NOT among them --
#      neither has a *_SKIPPED variable and neither can be skipped, since both
#      are bash-only and always run -- so do not count either when updating
#      the hardcoded denominator in the verdict block. Adding an assertion
#      means editing the tally, the verdict conditional, and that number
#      together.
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
# The contract being asserted is NOT "identical for arbitrary input" -- it is
# "identical for every value either twin can encounter on its own platform".
# setup.ps1 escapes backslashes (a Windows root needs it for JSON); setup.sh does
# not (a POSIX root has none, and bash cannot express the escape -- see
# setup.sh render_template). So the fixture uses POSIX-form values, where the PS
# escape is a no-op and the two shapes must agree exactly.

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
            or "/__pycache__/" in rel or rel == "AppData/Local" or rel.startswith("AppData/Local/"):
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
            local native_root="$sroot" repo_m="" repo_w=""
            if command -v cygpath >/dev/null 2>&1; then
                native_root="$(cygpath -w "$sroot")"
                repo_m="$(cygpath -m "$REPO_ROOT")"
                repo_w="$(cygpath -m "$SP_REPO_ROOT_W")"
            fi
            # Masks in the same order as sp_tree_listing_sh's sp_mask_script.
            # MSYS path conversion is disabled for this call: Git Bash would
            # otherwise rewrite POSIX-looking needles (/c/Users/..., /tmp/...)
            # into Windows form before Python sees them, and those needles
            # would never match the files. native_root is converted above.
            MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*' \
            parity_python -c "$SP_TREE_PY" "$native_root" "$ide_prefix" 7 \
                "$home_raw" '<USER_HOME>' \
                "${home_raw//\\//}" '<USER_HOME>' \
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
            mask="$(sp_mask_script \
                "$home_raw" '<USER_HOME>' \
                "${home_raw//\\//}" '<USER_HOME>' \
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

PARITY_JOBS_DIR="$TMPDIR_PARITY/jobs"
mkdir -p "$PARITY_JOBS_DIR"

# parity_step <name> <function> <flag vars...>
parity_step() {
    local name="$1" fn="$2"; shift 2
    "$fn" > "$PARITY_JOBS_DIR/$name.out" 2> "$PARITY_JOBS_DIR/$name.err"
    declare -p "$@" > "$PARITY_JOBS_DIR/$name.status"
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
  if [ -n "$PS_BIN" ] && [ -f "$SETUP_PS1_SCRIPT" ]; then
      parity_setup_ps1_deploy 2> "$TMPDIR_PARITY/setup-parity-deploy.err" &
      SP_DEPLOY_PID="$!"
      trap 'wait "$SP_DEPLOY_PID" 2>/dev/null || true' EXIT
  fi
  parity_step setup_verify parity_sec_setup_verify SETUP_VERIFY_OK
  parity_step setup_parity parity_sec_setup_parity SETUP_PARITY_OK SETUP_PARITY_SKIPPED ) &
PARITY_PIDS+=("$!")
( parity_step merge parity_sec_merge MERGE_OK MERGE_SKIPPED ) & PARITY_PIDS+=("$!")
( parity_step render parity_sec_render RENDER_OK RENDER_SKIPPED ) & PARITY_PIDS+=("$!")

for pid in "${PARITY_PIDS[@]}"; do
    wait "$pid" || true
done

# Replay in the original section order, then load each section's flags.
for name in setup_verify merge render setup_parity; do
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

# --- Verdict --------------------------------------------------------------

if [ "$PARITY_FAIL" -eq 0 ] && [ "$INVENTORY_OK" -eq 1 ] && [ "$SETUP_VERIFY_OK" -eq 1 ] && [ "$MERGE_OK" -eq 1 ] && [ "$RENDER_OK" -eq 1 ] && [ "$SETUP_PARITY_OK" -eq 1 ]; then
    echo "PARITY OK"

    # Loud warning when assertions were skipped (SKIPPED leaves *_OK=1, so
    # the run is non-failing but NOT a full green)
    SKIPPED_COUNT=0
    [ "$MERGE_SKIPPED" -eq 1 ] && SKIPPED_COUNT=$((SKIPPED_COUNT + 1))
    [ "$RENDER_SKIPPED" -eq 1 ] && SKIPPED_COUNT=$((SKIPPED_COUNT + 1))
    [ "$SETUP_PARITY_SKIPPED" -eq 1 ] && SKIPPED_COUNT=$((SKIPPED_COUNT + 1))

    # Count kept in step with the tally above by hand -- there is no derived
    # total, so a new assertion means editing both.
    if [ "$SKIPPED_COUNT" -gt 0 ]; then
        echo ""
        echo "WARNING: $SKIPPED_COUNT of 3 parity assertions SKIPPED (see SKIP notices above for reasons)."
        echo "         This is NOT a full green — only deployment-inventory agreement was verified."
        echo ""
    fi

    echo "  verify-deployment.py --list ↔ setup-model expected inventory: $(wc -l < "$VERIFY_LIST") entries match (overlay copy-dir + merge-file rows covered)"
    echo "  setup.sh sandboxed deploy ↔ verify-deployment.py: PASS (clean deploy under a sandbox HOME)"
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
    exit 0
fi

echo "PARITY FAILED" >&2
exit 1
