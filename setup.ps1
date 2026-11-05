# agent-playbook setup script (Windows PowerShell). Twin: setup.sh.
# Deploys the playbook into the AI providers you choose by linking their config
# directories to this repo, and prepares what the playbook needs around it: the
# Python venv, the store repo, the pointer file and the engine branch.
# Requires: Developer Mode enabled OR run as Administrator (symlinks).
#
# Modes (see -Help):
#   interactive -- a console and no -Yes: detects installed providers, asks before
#                  replacing a file of yours, offers the store repo and engine branch.
#   -Yes        -- the same defaults with no questions (new local store repo when none).
#   neither     -- no console (redirected input/output, e.g. test-parity.sh): every
#                  provider, a file of yours is backed up and replaced, and the store
#                  repo, engine branch and memory link are only reported, never created.
#
# Kiro overlay merge: for a shared skill dir, kiro discipline deltas live under
# providers\kiro\skills\<name>\ and are APPENDED to the deployed copy at setup time:
#   - SKILL.md overlay : OVERLAY.md          -> appended to the deployed SKILL.md
#   - aux-file overlay  : <stem>.OVERLAY.md  -> appended to the deployed <stem>.md
#     (e.g. memory-rules.OVERLAY.md -> memory-rules.md)
# Any overlay forces a copy of the skill dir (a single file inside a symlinked dir
# cannot be overwritten); aux merges run AFTER the dir copy. SKILL.OVERLAY.md is
# reserved/forbidden (SKILL.md uses the bare OVERLAY.md) and an overlay whose target
# file is absent is skipped with a warning. See Merge-Overlay / Apply-AuxOverlays below.

param(
    [string]$Providers = "",
    [switch]$DryRun,
    [switch]$Yes,
    [string]$StoresUrl = "",
    [switch]$NoStores,
    [switch]$Uninstall,
    [switch]$Purge,
    [switch]$Help
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$SharedDir = Join-Path $ScriptDir "shared"
$AllProviders = @('claude', 'codex', 'gemini', 'kiro')

if ($Help) {
    Write-Host @"
Usage: setup.ps1 [options]

Deploys agent-playbook into the AI providers you choose. Safe to re-run.

  -Providers LIST   comma-separated subset of: claude,codex,gemini,kiro (or "all").
                    Default: interactive -- the detected ones, confirmed; otherwise all.
  -DryRun           print every change instead of making it; nothing is written.
  -Yes              accept every default without asking (create a local store repo
                    when none exists, create the engine branch, back up and replace
                    a file of yours that is in the way).
  -StoresUrl URL    clone the store repo from URL when it is missing.
  -NoStores         do not set up a store repo (memory is disabled until you do).
  -Uninstall        remove what setup deployed (links into this repo, generated
                    copies, restored .bak files) for the chosen providers.
  -Purge            with -Uninstall: also remove ~\.agent-playbook\config and the
                    repo's memory link. The store repo itself is never touched.
  -Help             this text.

Environment: AGENT_PLAYBOOK_STORES (store repo path), AGENT_PLAYBOOK_CONFIG (pointer
file path), AGENT_PLAYBOOK_SKIP_KIRO_CLI=1 (do not change kiro-cli's global settings).
"@
    exit 0
}
if ($Purge -and -not $Uninstall) { [Console]::Error.WriteLine("ERROR: -Purge only goes with -Uninstall"); exit 2 }

$Interactive = (-not $Yes) -and (-not [Console]::IsInputRedirected) -and (-not [Console]::IsOutputRedirected)

# --- Small helpers ---------------------------------------------------------

# Invoke-Act: run a filesystem-changing block, or print what it would do under -DryRun.
function Invoke-Act {
    param([string]$What, [scriptblock]$Block)
    if ($DryRun) { Write-Host "    DRY: $What" } else { & $Block }
}

function Write-TextFile {
    param([string]$Path, [string]$Text)
    Invoke-Act "write $Path" { [IO.File]::WriteAllText($Path, $Text, (New-Object System.Text.UTF8Encoding $false)) }
}

function Confirm-Step {
    param([string]$Question, [bool]$Default = $true)
    if (-not $Interactive) { return $Default }
    $hint = if ($Default) { "Y/n" } else { "y/N" }
    $ans = Read-Host "  $Question [$hint]"
    if ([string]::IsNullOrWhiteSpace($ans)) { return $Default }
    return ($ans -match '^(y|yes)$')
}

function New-DirIfMissing {
    param([string]$Path)
    if (-not (Test-Path $Path)) { Invoke-Act "mkdir $Path" { New-Item -ItemType Directory -Path $Path -Force | Out-Null } }
}

# A path in the pointer file's form: absolute, forward slashes (setup.sh writes the same bytes).
function ConvertTo-PointerPath { param([string]$Path) return $Path.Replace('\', '/') }

# Test-EngineLink: a reparse point (symlink or junction) whose target lies inside this repo.
function Test-EngineLink {
    param([string]$Path)
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
    if (-not $item -or -not ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) { return $false }
    $t = [string]($item.Target | Select-Object -First 1)
    $t = $t -replace '^\\\\\?\\', ''
    return ($t -eq $ScriptDir) -or $t.StartsWith($ScriptDir + '\', [StringComparison]::OrdinalIgnoreCase)
}

# Remove a directory link without following it (Remove-Item -Recurse can delete the target's files).
function Remove-DirLink { param([string]$Path) Invoke-Act "rmdir $Path" { cmd /c rmdir "$Path" 2>$null } }

# --- Linking ---------------------------------------------------------------

# Clear-WayFor: a non-link file or folder of the user's sits where a link goes.
# Returns $true when the path is free afterwards (backed up to .bak), $false to skip it.
function Clear-WayFor {
    param([string]$Path)
    if ($Interactive) {
        Write-Host "  $Path exists and is not a playbook link."
        if (-not (Confirm-Step "Back it up to ${Path}.bak and replace it with the playbook's?" $true)) {
            Write-Host "  SKIPPED: $Path (kept as is)"
            return $false
        }
    }
    Write-Host "  BACKUP: $Path -> ${Path}.bak"
    Invoke-Act "move $Path ${Path}.bak" { Move-Item $Path "${Path}.bak" -Force }
    return $true
}

function Link-File {
    param(
        [string]$Target,  # source file in repo
        [string]$Link     # symlink to create
    )

    if (Test-Path $Link) {
        $item = Get-Item $Link -Force
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            $currentTarget = $item.Target
            if ($currentTarget -eq $Target) {
                Write-Host "  OK: $Link -> $Target"
                return
            }
            Write-Host "  UPDATE: $Link (was -> $currentTarget)"
            Invoke-Act "remove $Link" { Remove-Item $Link -Force }
        } else {
            if (-not (Clear-WayFor $Link)) { return }
        }
    }

    # PowerShell 5's New-Item -ItemType SymbolicLink may require admin for files.
    # Fall back to cmd mklink which works with Developer Mode enabled.
    Invoke-Act "link $Link -> $Target" {
        try {
            New-Item -ItemType SymbolicLink -Path $Link -Target $Target -ErrorAction Stop | Out-Null
        } catch {
            cmd /c mklink "$Link" "$Target" | Out-Null
        }
    }
    Write-Host "  LINKED: $Link -> $Target"
}

function Link-Dir {
    param(
        [string]$Target,
        [string]$Link
    )

    if (Test-Path $Link) {
        $item = Get-Item $Link -Force
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            $currentTarget = $item.Target
            if ($currentTarget -eq $Target) {
                Write-Host "  OK: $Link -> $Target"
                return
            }
            Write-Host "  UPDATE: $Link (was -> $currentTarget)"
            Remove-DirLink $Link
        } else {
            if (-not (Clear-WayFor $Link)) { return }
        }
    }

    # PowerShell 5's New-Item -ItemType SymbolicLink requires admin for directories.
    # Fall back to cmd mklink /D which works with Developer Mode enabled.
    Invoke-Act "link $Link -> $Target" {
        try {
            New-Item -ItemType SymbolicLink -Path $Link -Target $Target -ErrorAction Stop | Out-Null
        } catch {
            cmd /c mklink /D "$Link" "$Target" | Out-Null
        }
    }
    Write-Host "  LINKED: $Link -> $Target"
}

# The shared skill folders. .trash / synced / .bucket-* are the Claude Code app's own
# skill-sync cache (it writes beside the skills it finds), never a playbook skill.
function Get-SharedSkills {
    Get-ChildItem (Join-Path $SharedDir "skills") -Directory | Where-Object {
        $_.Name -ne '.trash' -and $_.Name -ne 'synced' -and $_.Name -notlike '.bucket-*'
    }
}

# Link-Skills: one link per shared skill inside the provider's own skills folder, so the
# provider's other skills (built-in, the user's, another pack's) stay. A folder of the
# user's with a playbook skill's name is never replaced: it is reported.
function Link-Skills {
    param([string]$Dir)
    $item = Get-Item -LiteralPath $Dir -Force -ErrorAction SilentlyContinue
    if ($item -and ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        if (Test-EngineLink $Dir) {
            # the old layout linked the whole folder to shared\skills
            Write-Host "  CONVERT: $Dir (one link per skill instead of the whole folder)"
            Remove-DirLink $Dir
        } else {
            Write-Host "  SKIPPED: $Dir links to $($item.Target), not to this repo; link the skills by hand"
            return
        }
    }
    New-DirIfMissing $Dir
    foreach ($skill in (Get-SharedSkills)) {
        $dest = Join-Path $Dir $skill.Name
        $existing = Get-Item -LiteralPath $dest -Force -ErrorAction SilentlyContinue
        if ($existing -and -not ($existing.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            Write-Host "  KEPT: $dest is your own folder; the playbook's $($skill.Name) skill is not linked there"
            continue
        }
        Link-Dir -Target $skill.FullName -Link $dest
    }
    # a playbook link whose skill is gone from the repo
    if (Test-Path $Dir) {
        Get-ChildItem $Dir -Force -ErrorAction SilentlyContinue | Where-Object {
            ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -and -not (Test-Path $_.Target) -and (Test-EngineLink $_.FullName)
        } | ForEach-Object {
            Write-Host "  REMOVE: $($_.FullName) (dangling)"
            Remove-DirLink $_.FullName
        }
    }
}

# --- Copy helpers ---
# Copy-File: kiro-always manifest entries (copies by design, outside steering).
# Copy-Dir: overlay-bearing Kiro skills, which must be generated copies because
# the merge overwrites one file inside the skill directory. Everything else in
# ~/.kiro/ is a symlink (Windows copy mode was retired 2026-09-20).

function Copy-File {
    param(
        [string]$Source,  # source file in repo
        [string]$Dest     # destination to copy to
    )

    # Remove stale symlink if present (migration from symlink-based setup)
    if ((Test-Path $Dest) -and ((Get-Item $Dest -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        Write-Host "  REMOVE SYMLINK: $Dest"
        Invoke-Act "remove $Dest" { Remove-Item $Dest -Force }
    }

    # Skip copy if content is already identical
    if ((Test-Path $Dest) -and
        ([System.IO.File]::ReadAllText($Source) -eq [System.IO.File]::ReadAllText($Dest))) {
        Write-Host "  OK: $Dest (matches source)"
        return
    }

    Invoke-Act "copy $Source -> $Dest" { Copy-Item -Path $Source -Destination $Dest -Force }
    Write-Host "  COPIED: $Source -> $Dest"
}

function Copy-Dir {
    param(
        [string]$Source,
        [string]$Dest
    )

    # Remove stale symlink if present (migration from symlink-based setup).
    # Use cmd rmdir for directory symlinks -- PowerShell's Remove-Item can
    # throw NullReferenceException on directory junctions/symlinks.
    if ((Test-Path $Dest) -and ((Get-Item $Dest -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        Write-Host "  REMOVE SYMLINK: $Dest"
        Remove-DirLink $Dest
    }

    # Copies are always recoverable from the repo, so we delete-then-copy
    # rather than backing up (backup dirs confused Kiro IDE previously).
    Invoke-Act "copy $Source -> $Dest" {
        if (Test-Path $Dest) { Remove-Item $Dest -Recurse -Force }
        Copy-Item -Path $Source -Destination $Dest -Recurse -Force
        # Python bytecode caches are build output, not deployables (verify-deployment skips them too).
        Get-ChildItem -LiteralPath $Dest -Directory -Recurse -Force -Filter '__pycache__' -ErrorAction SilentlyContinue |
            Remove-Item -Recurse -Force
    }
    Write-Host "  COPIED: $Source -> $Dest"
}

# --- Manifest reader -------------------------------------------------------

function Read-Manifest {
    param([string]$ManifestPath)
    if (-not (Test-Path $ManifestPath)) {
        [Console]::Error.WriteLine("ERROR: manifest not found: $ManifestPath")
        exit 2
    }
    $entries = @()
    $lineNum = 0
    $validKinds = @('symlink-file','symlink-dir','copy-file','copy-dir-recursive','merge-file','template-file','seed-file')
    foreach ($line in (Get-Content -LiteralPath $ManifestPath)) {
        $lineNum++
        if ($line -match '^\s*#' -or $line -match '^\s*$') { continue }
        $cols = $line -split '\t'
        if ($cols.Count -ne 4) {
            [Console]::Error.WriteLine("ERROR: manifest line $lineNum has $($cols.Count) columns (expected 4): $line")
            exit 2
        }
        if ($cols[0] -notin $validKinds) {
            [Console]::Error.WriteLine("ERROR: manifest line $lineNum has unknown kind '$($cols[0])': $line")
            exit 2
        }
        $entries += [PSCustomObject]@{ kind=$cols[0]; dest=$cols[1]; source=$cols[2]; mode=$cols[3] }
    }
    Write-Host "  Manifest: $($entries.Count) entries loaded"
    return ,$entries
}

$ManifestEntries = Read-Manifest (Join-Path $ScriptDir 'inventory.tsv')
if ($DryRun) { Write-Host "  DRY RUN: nothing will be changed" }

# Kiro IDE per-user config dir. Platform-divergent, so each twin resolves its own:
# %APPDATA%\Kiro\User here; ${XDG_CONFIG_HOME:-~/.config}/Kiro/User in setup.sh.
$KiroIdeUserDir = Join-Path (Join-Path $env:APPDATA 'Kiro') 'User'

# Expand ~ in dest path to $env:USERPROFILE, and <KIRO_IDE_USER> to the IDE dir
function Expand-Dest {
    param([string]$Dest)
    if ($Dest.StartsWith('<KIRO_IDE_USER>/') -or $Dest.StartsWith('<KIRO_IDE_USER>\')) {
        return Join-Path $KiroIdeUserDir $Dest.Substring(16)
    }
    if ($Dest.StartsWith('~/') -or $Dest.StartsWith('~\')) {
        return Join-Path $env:USERPROFILE $Dest.Substring(2)
    }
    return $Dest
}

# Expand source to absolute repo-rooted path
function Expand-Source {
    param([string]$Source)
    return Join-Path $ScriptDir $Source
}

# --- Pointer file (shared/AGENTS.md, Config Repo Locations) ----------------

$ConfigFile = if ($env:AGENT_PLAYBOOK_CONFIG) { $env:AGENT_PLAYBOOK_CONFIG } else { Join-Path (Join-Path $env:USERPROFILE ".agent-playbook") "config" }

function Get-ConfigValue {
    param([string]$Key)
    if (-not (Test-Path -LiteralPath $ConfigFile)) { return "" }
    $value = ""
    foreach ($line in (Get-Content -LiteralPath $ConfigFile)) {
        if ($line -match "^\s*$Key\s*=\s*(.*?)\s*$") { $value = $Matches[1] }
    }
    return $value
}

$Stores = if ($env:AGENT_PLAYBOOK_STORES) { $env:AGENT_PLAYBOOK_STORES } else { Get-ConfigValue 'stores' }
if (-not $Stores) { $Stores = Join-Path (Join-Path $env:USERPROFILE ".agent-playbook") "stores" }
$Stores = $Stores.Replace('/', '\')

# --- Providers -------------------------------------------------------------

function Test-ProviderDetected {
    param([string]$Name)
    switch ($Name) {
        'claude' { return (Test-Path (Join-Path $env:USERPROFILE ".claude")) -or [bool](Get-Command claude -ErrorAction SilentlyContinue) }
        'codex'  { return (Test-Path (Join-Path $env:USERPROFILE ".codex")) -or [bool](Get-Command codex -ErrorAction SilentlyContinue) }
        'gemini' { return (Test-Path (Join-Path $env:USERPROFILE ".gemini")) -or [bool](Get-Command gemini -ErrorAction SilentlyContinue) }
        'kiro'   { return (Test-Path (Join-Path $env:USERPROFILE ".kiro")) -or (Test-Path $KiroIdeUserDir) -or [bool](Get-Command kiro-cli -ErrorAction SilentlyContinue) }
    }
    return $false
}

function ConvertTo-ProviderList {
    param([string]$List)
    if ($List.Trim() -eq 'all') { return $AllProviders }
    $out = @()
    foreach ($p in ($List -split '[,\s]+' | Where-Object { $_ })) {
        if ($p -notin $AllProviders) {
            [Console]::Error.WriteLine("ERROR: unknown provider '$p' (one of: $($AllProviders -join ', '))")
            exit 2
        }
        if ($p -notin $out) { $out += $p }
    }
    return $out
}

if ($Providers) {
    $Chosen = ConvertTo-ProviderList $Providers
} elseif ($Uninstall -and (Get-ConfigValue 'providers')) {
    $Chosen = ConvertTo-ProviderList (Get-ConfigValue 'providers')
} elseif (-not $Interactive) {
    $Chosen = $AllProviders
} else {
    $found = @($AllProviders | Where-Object { Test-ProviderDetected $_ })
    $shown = if ($found.Count) { $found -join ' ' } else { 'none' }
    Write-Host "  Detected: $shown"
    $default = if ($found.Count) { $found -join ',' } else { 'all' }
    $ans = Read-Host "  Deploy to which providers? (comma-separated; Enter for: $default)"
    if ([string]::IsNullOrWhiteSpace($ans)) { $ans = $default }
    $Chosen = ConvertTo-ProviderList $ans
}
function Test-Wants { param([string]$Name) return ($Name -in $Chosen) }

# --- Template rendering ----------------------------------------------------
# Byte contract (lockstep with setup.sh render_template and the template-aware
# comparison in verify-deployment.py): read the source preserving interior
# line endings, strip trailing newlines, substitute tokens, emit a single
# trailing LF. Deliberately the same shape as Merge-Overlay so both generated-
# file paths share one contract.
#
# Tokens expand to a JSON-escaped platform-native root (Windows: C:\\Users\\X;
# POSIX: /home/x -- the escape is a no-op there). Templates use forward slashes
# for everything AFTER the token, so Windows renders the mixed separator form
# Kiro already accepts and POSIX renders a clean native path.
function Render-Template {
    param([string]$Source)
    $body = [IO.File]::ReadAllText($Source) -replace '[\r\n]+$', ''
    # Forward slashes, not escaped backslashes: templates embed these tokens in file://
    # URIs and plain markdown (kiro_default.md, kiro-guidelines.md) as well as JSON
    # (mcp.json, ide-mcp.json). Forward slashes are valid in all three contexts on
    # Windows (Win32 APIs accept either separator) and need no JSON escaping, unlike
    # a raw or doubled backslash -- so a single substitution shape serves every
    # destination. This mirrors setup.sh/bash's render_template, whose $HOME and
    # $SCRIPT_DIR are already forward-slash on every platform bash runs on.
    $body = $body.Replace('{{USER_HOME}}', $env:USERPROFILE.Replace('\', '/'))
    $body = $body.Replace('{{PLAYBOOK_ROOT}}', $ScriptDir.Replace('\', '/'))
    return $body + "`n"
}

function Copy-Template {
    param(
        [string]$Source,  # template file in repo
        [string]$Dest     # destination to render to
    )

    $rendered = Render-Template $Source

    # Remove stale symlink if present (migration from symlink-based setup)
    if ((Test-Path $Dest) -and ((Get-Item $Dest -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        Write-Host "  REMOVE SYMLINK: $Dest"
        Invoke-Act "remove $Dest" { Remove-Item $Dest -Force }
    }

    if ((Test-Path $Dest) -and ([IO.File]::ReadAllText($Dest) -eq $rendered)) {
        Write-Host "  OK: $Dest (matches rendered source)"
        return
    }

    Write-TextFile $Dest $rendered
    Write-Host "  RENDERED: $Source -> $Dest"
}

# seed-file: render only when the destination is ABSENT. The app owns the live
# file (it rewrites mcp.json at runtime), so the repo copy is a restore seed --
# overwriting it would clobber in-app changes and, for secret-bearing configs,
# the user's live credentials. Refresh the repo copy deliberately, not by deploy.
function Copy-Seed {
    param(
        [string]$Source,  # template file in repo
        [string]$Dest     # destination to seed if absent
    )

    if (Test-Path $Dest) {
        Write-Host "  OK: $Dest (present; seed not overwritten)"
        return
    }

    Write-TextFile $Dest (Render-Template $Source)
    Write-Host "  SEEDED: $Source -> $Dest"
}

# --- Kiro overlay merge ----------------------------------------------------

# Write merged content as UTF-8 WITHOUT a BOM, with no trailing newline added.
# Windows PowerShell 5.1's Set-Content default encoding is NOT UTF-8 and corrupts
# multibyte characters (e.g. em-dashes) in merged skill content; bash writes plain
# UTF-8, so an explicit no-BOM UTF-8 write here keeps the two scripts byte-identical.
function Write-MergedFile {
    param([string]$Path, [string]$Content)
    Write-TextFile $Path $Content
}

# Merge a shared file body with a kiro overlay body using the canonical shape:
#   non-empty overlay -> shared (trailing newlines stripped) + "`n`n" + overlay (trailing
#                        newlines stripped) + single trailing "`n"
#   empty overlay     -> shared (trailing newlines stripped) + single trailing "`n"
# Returns the merged string (written via Write-MergedFile, no extra newline). Mirrors
# setup.sh byte-for-byte (modulo platform line endings) so the two scripts stay in parity.
function Merge-Overlay {
    param(
        [string]$SharedFile,   # path to the deployed/shared source file
        [string]$OverlayFile   # path to the *.OVERLAY.md / OVERLAY.md fragment
    )
    # Strip trailing CRLF/LF (regex avoids TrimEnd's per-char stripping)
    $sharedBody = [IO.File]::ReadAllText($SharedFile) -replace '[\r\n]+$', ''
    $overlayBody = [IO.File]::ReadAllText($OverlayFile)
    if ($overlayBody.Trim().Length -gt 0) {
        # shared body + one blank line + overlay (own trailing newlines stripped) + single trailing newline.
        # Mirrors setup.sh, where $(cat "$overlay") strips the overlay's trailing newline before printf re-adds one;
        # without the strip, ReadAllText preserves the overlay file's trailing newline and the output ends in \n\n.
        return $sharedBody + "`n`n" + ($overlayBody -replace '[\r\n]+$', '') + "`n"
    } else {
        # shared body + single trailing newline (matches setup.sh empty-overlay branch)
        return $sharedBody + "`n"
    }
}

# Apply auxiliary-file overlays inside an already-copied skill dir.
# For every providers\kiro\skills\<name>\<stem>.OVERLAY.md (except the reserved
# SKILL.OVERLAY.md), append the overlay to the deployed markdown target <stem>.md.
# Naming convention matches the consumers (e.g. memory-rules.OVERLAY.md -> memory-rules.md,
# RESEARCH_CONFIG_TEMPLATE.OVERLAY.md -> RESEARCH_CONFIG_TEMPLATE.md). SKILL.md keeps the
# bare OVERLAY.md convention (handled by the caller), so SKILL.OVERLAY.md is rejected to
# prevent two paths to the same target. Target-missing overlays are skipped with a warning
# (an overlay never creates a file on its own). The shared source file is merged, which is
# what the copy holds, so a dry run (no copy made) shows the same plan.
function Apply-AuxOverlays {
    param(
        [string]$OverlayDir,  # providers\kiro\skills\<name>
        [string]$Dest,        # ~/.kiro/skills/<name> (already copied)
        [string]$SourceDir    # shared\skills\<name>
    )
    if (-not (Test-Path $OverlayDir)) { return }
    Get-ChildItem $OverlayDir -File -Filter "*.OVERLAY.md" | ForEach-Object {
        if ($_.Name -eq "OVERLAY.md") { return }  # SKILL.md overlay, handled separately
        if ($_.Name -eq "SKILL.OVERLAY.md") {
            Write-Warning "  SKIPPED RESERVED: $($_.FullName) (SKILL.md uses bare OVERLAY.md; SKILL.OVERLAY.md is forbidden)"
            return
        }
        $targetName = ($_.Name -replace '\.OVERLAY\.md$', '') + ".md"
        $targetPath = Join-Path $Dest $targetName
        $sourcePath = Join-Path $SourceDir $targetName
        if (-not (Test-Path $sourcePath)) {
            Write-Warning "  SKIPPED AUX OVERLAY: $($_.FullName) (no shared target '$targetName')"
            return
        }
        $merged = Merge-Overlay -SharedFile $sourcePath -OverlayFile $_.FullName
        Write-MergedFile -Path $targetPath -Content $merged
        Write-Host "  MERGED AUX: $targetName (shared + kiro overlay)"
    }
}

# Does a kiro overlay dir carry ANY overlay (SKILL.md's OVERLAY.md or any aux
# <F>.OVERLAY.md)? Such a skill must be COPIED (not symlinked) because a single file
# inside a symlinked dir cannot be overwritten. SKILL.OVERLAY.md is reserved and does
# not count (it is rejected at merge time).
function Test-HasAnyOverlay {
    param([string]$OverlayDir)
    if (-not (Test-Path $OverlayDir)) { return $false }
    if (Test-Path (Join-Path $OverlayDir "OVERLAY.md")) { return $true }
    $aux = Get-ChildItem $OverlayDir -File -Filter "*.OVERLAY.md" -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -ne "OVERLAY.md" -and $_.Name -ne "SKILL.OVERLAY.md" }
    return ($aux.Count -gt 0)
}

# --- Uninstall -------------------------------------------------------------

# Remove a link into this repo, then restore <path>.bak if setup made one.
function Remove-EngineLink {
    param([string]$Path)
    if (-not (Test-EngineLink $Path)) { return }
    $item = Get-Item -LiteralPath $Path -Force
    if ($item.PSIsContainer) { Remove-DirLink $Path } else { Invoke-Act "remove $Path" { Remove-Item -LiteralPath $Path -Force } }
    Write-Host "  REMOVED: $Path"
    if (Test-Path -LiteralPath "$Path.bak") {
        Invoke-Act "restore $Path" { Move-Item -LiteralPath "$Path.bak" $Path -Force }
        Write-Host "  RESTORED: $Path (from $Path.bak)"
    }
}

function Remove-SkillLinks {
    param([string]$Dir)
    if (-not (Test-Path $Dir)) { return }
    Get-ChildItem $Dir -Force -ErrorAction SilentlyContinue | ForEach-Object { Remove-EngineLink $_.FullName }
}

function Uninstall-Mode {
    param([string]$Mode)
    foreach ($entry in ($ManifestEntries | Where-Object { $_.mode -eq $Mode })) {
        $dest = Expand-Dest $entry.dest
        $source = Expand-Source $entry.source
        switch ($entry.kind) {
            { $_ -in 'symlink-file', 'symlink-dir' } { Remove-EngineLink $dest }
            'template-file' {
                if ((Test-Path $dest) -and ([IO.File]::ReadAllText($dest) -eq (Render-Template $source))) {
                    Invoke-Act "remove $dest" { Remove-Item $dest -Force }; Write-Host "  REMOVED: $dest"
                } elseif (Test-Path $dest) { Write-Host "  KEPT: $dest (changed since setup rendered it)" }
            }
            'copy-file' {
                if ((Test-Path $dest) -and ([IO.File]::ReadAllText($dest) -eq [IO.File]::ReadAllText($source))) {
                    Invoke-Act "remove $dest" { Remove-Item $dest -Force }; Write-Host "  REMOVED: $dest"
                } elseif (Test-Path $dest) { Write-Host "  KEPT: $dest (changed since setup copied it)" }
            }
            'seed-file' { if (Test-Path $dest) { Write-Host "  KEPT: $dest (the app owns it; setup only seeded it)" } }
        }
    }
}

if ($Uninstall) {
    Write-Host "=== Uninstall: $($Chosen -join ', ') ==="
    if (Test-Wants 'claude') { Uninstall-Mode 'claude'; Remove-SkillLinks (Join-Path $env:USERPROFILE ".claude\skills") }
    if (Test-Wants 'codex') { Uninstall-Mode 'codex'; Remove-SkillLinks (Join-Path $env:USERPROFILE ".codex\skills") }
    if (Test-Wants 'gemini') { Uninstall-Mode 'gemini'; Remove-SkillLinks (Join-Path $env:USERPROFILE ".gemini\skills") }
    if (Test-Wants 'kiro') {
        Uninstall-Mode 'kiro-always'
        Uninstall-Mode 'kiro'
        $kiroSkills = Join-Path $env:USERPROFILE ".kiro\skills"
        foreach ($skill in (Get-SharedSkills)) {
            $dest = Join-Path $kiroSkills $skill.Name
            $item = Get-Item -LiteralPath $dest -Force -ErrorAction SilentlyContinue
            if ((Test-HasAnyOverlay (Join-Path $ScriptDir "providers\kiro\skills\$($skill.Name)")) -and $item -and
                -not ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
                Invoke-Act "remove $dest" { Remove-Item $dest -Recurse -Force }
                Write-Host "  REMOVED: $dest (generated copy)"
            }
        }
        Remove-SkillLinks $kiroSkills
        if (Get-Command kiro-cli -ErrorAction SilentlyContinue) {
            Write-Host "  NOTE: kiro-cli's chat.defaultAgent still names kiro_default; change it with: kiro-cli settings --global chat.defaultAgent <agent>"
        }
    }
    if ($Purge) {
        $memLink = Join-Path $ScriptDir "memory"
        $memItem = Get-Item -LiteralPath $memLink -Force -ErrorAction SilentlyContinue
        if ($memItem -and ($memItem.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            Remove-DirLink $memLink; Write-Host "  REMOVED: $memLink (link; the store repo is untouched)"
        }
        if (Test-Path -LiteralPath $ConfigFile) { Invoke-Act "remove $ConfigFile" { Remove-Item -LiteralPath $ConfigFile -Force }; Write-Host "  REMOVED: $ConfigFile" }
    } else {
        Write-Host "  KEPT: $ConfigFile, the memory link and the store repo (-Purge removes the first two)"
    }
    Write-Host ""
    Write-Host "Done."
    exit 0
}

# --- Prerequisites and Python venv -------------------------------------------
# One interpreter for every playbook Python script: <repo>\.venv-agent-playbook
# (gitignored), created from the system Python 3 (`py -3`, then `python`; 3.8+).
# It stays stdlib-only: created --without-pip, and nothing is ever installed
# into it. Setup never installs Python and stops here when none is found, so a
# machine without Python fails loudly instead of deploying a half-working
# playbook. Re-running is idempotent: a working venv is left alone; a broken one
# (for example the base Python was uninstalled) is rebuilt. setup.sh has the twin step.

$VenvDir = Join-Path $ScriptDir '.venv-agent-playbook'
$VenvPython = Join-Path $VenvDir 'Scripts\python.exe'

# Runs `<exe> <preArgs> -c ...` and returns @{Exe; Version} when it is a working
# Python 3.8+, else $null. Native stderr is discarded (the Windows Store `python`
# alias prints there and exits non-zero); $ErrorActionPreference is relaxed so
# Windows PowerShell 5.1 does not turn that into a terminating error.
function Get-PythonInfo {
    param([string]$Exe, [string[]]$PreArgs)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $code = "import sys; print(sys.executable); print('%d.%d.%d' % sys.version_info[:3]); sys.exit(0 if sys.version_info[:2] >= (3, 8) else 3)"
        $out = & $Exe @PreArgs -c $code 2>$null
        $exit = $LASTEXITCODE
    } catch {
        return $null
    } finally {
        $ErrorActionPreference = $prev
    }
    $lines = @($out)
    if ($exit -ne 0 -or $lines.Count -lt 2) { return $null }
    return [PSCustomObject]@{ Exe = [string]$lines[0]; Version = [string]$lines[1] }
}

Write-Host "=== Prerequisites ==="
$missing = $false
$systemPython = Get-PythonInfo 'py' @('-3')
if (-not $systemPython) { $systemPython = Get-PythonInfo 'python' @() }
if ($systemPython) { Write-Host "  OK: Python $($systemPython.Version) ($($systemPython.Exe))" }
else { Write-Host "  MISSING: Python 3.8+ (tried: py -3, python) -- install it (python.org or the Microsoft Store), then run setup.ps1 again"; $missing = $true }
if (Get-Command git -ErrorAction SilentlyContinue) { Write-Host "  OK: $(& git --version)" }
else { Write-Host "  MISSING: git -- install it (git-scm.com), then run setup.ps1 again"; $missing = $true }
$probe = Join-Path ([IO.Path]::GetTempPath()) ("apb-probe-" + [Guid]::NewGuid().ToString("N"))
try {
    New-Item -ItemType Directory -Path $probe | Out-Null
    New-Item -ItemType SymbolicLink -Path (Join-Path $probe "link") -Target $probe -ErrorAction Stop | Out-Null
    Write-Host "  OK: symlinks can be created"
} catch {
    Write-Host "  MISSING: symlink rights -- enable Developer Mode (Settings > System > For developers) or run elevated"
    $missing = $true
} finally {
    # [IO.Directory]::Delete removes a directory link without following it, on every OS (no cmd.exe off Windows)
    $probeLink = Join-Path $probe "link"
    if (Get-Item -LiteralPath $probeLink -Force -ErrorAction SilentlyContinue) { [IO.Directory]::Delete($probeLink) }
    Remove-Item $probe -Recurse -Force -ErrorAction SilentlyContinue
}
if (Get-Command node -ErrorAction SilentlyContinue) { Write-Host "  OK: Node $(& node --version) (optional: qdocument-interaction, Playwright)" }
else { Write-Host "  NOTE: Node not found (optional: only qdocument-interaction's creation libraries and the Playwright MCP need it)" }
if ($missing) {
    if ($DryRun) { Write-Host "  (dry run: continuing to show the plan)" }
    else { [Console]::Error.WriteLine("ERROR: a required prerequisite is missing (above); nothing was deployed."); exit 2 }
}

Write-Host "=== Python venv ==="
$venvInfo = $null
if (Test-Path -LiteralPath $VenvPython) { $venvInfo = Get-PythonInfo $VenvPython @() }
if ($venvInfo) {
    Write-Host "  OK: $VenvDir (Python $($venvInfo.Version))"
} elseif (-not $systemPython) {
    Write-Host "  SKIPPED: no Python 3.8+ to create $VenvDir"
} else {
    if ((Test-Path -LiteralPath $VenvDir) -and
        -not (Test-Path -LiteralPath (Join-Path $VenvDir 'pyvenv.cfg')) -and
        (Get-ChildItem -LiteralPath $VenvDir -Force | Select-Object -First 1)) {
        [Console]::Error.WriteLine("ERROR: $VenvDir exists, is not empty and is not a venv (no pyvenv.cfg). Move or delete it, then run setup.ps1 again.")
        exit 2
    }
    if ($DryRun) {
        Write-Host "    DRY: $($systemPython.Exe) -m venv --clear --without-pip $VenvDir"
    } else {
        & $systemPython.Exe -m venv --clear --without-pip $VenvDir
        if ($LASTEXITCODE -ne 0) {
            [Console]::Error.WriteLine("ERROR: '$($systemPython.Exe) -m venv' failed (exit $LASTEXITCODE) for $VenvDir. Fix the error above, then run setup.ps1 again.")
            exit 2
        }
        $venvInfo = Get-PythonInfo $VenvPython @()
        if (-not $venvInfo) {
            [Console]::Error.WriteLine("ERROR: $VenvPython does not run after creation. Delete $VenvDir and run setup.ps1 again.")
            exit 2
        }
        Write-Host "  CREATED: $VenvDir (Python $($venvInfo.Version), from $($systemPython.Exe))"
    }
}

# --- Store repo, memory link, engine branch --------------------------------

function Initialize-UserMemory {
    $mem = Join-Path $Stores "user\memory"
    if (Test-Path $mem) { return }
    $repoMem = Get-Item -LiteralPath (Join-Path $ScriptDir "memory") -Force -ErrorAction SilentlyContinue
    if ($repoMem -and -not ($repoMem.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        Write-Host "  NOTE: $($repoMem.FullName) is a real folder (the layout before the store repo held user memory);"
        Write-Host "        move it to $mem, then re-run setup to link it"
        return
    }
    Write-Host "  SEED: $mem (empty user memory from templates\memory\)"
    New-DirIfMissing $mem
    Get-ChildItem (Join-Path $ScriptDir "templates\memory") -File | ForEach-Object {
        $f = $_.FullName
        Invoke-Act "copy $f -> $mem" { Copy-Item $f $mem }
    }
}

function New-StoreRepo {
    Write-Host "  CREATE: $Stores (a new local store repo; add a remote and push it to keep it)"
    New-DirIfMissing $Stores
    Invoke-Act "git init $Stores" { & git -C $Stores init -q }
    Write-TextFile (Join-Path $Stores ".gitignore") "user/memory/.dream-journal.jsonl`n*/STORE.tmp-*`n*/scratch/`n"
}

function Copy-StoreRepo {
    param([string]$Url)
    Write-Host "  CLONE: $Url -> $Stores"
    Invoke-Act "git clone $Url $Stores" { & git clone -q $Url $Stores; if ($LASTEXITCODE -ne 0) { throw "git clone failed (exit $LASTEXITCODE)" } }
}

Write-Host "=== Store repo ==="
$storeReady = $true
if (Test-Path (Join-Path $Stores ".git")) {
    Write-Host "  OK: $Stores"
} elseif ($NoStores) {
    Write-Host "  SKIPPED: store repo (-NoStores); memory stays off until $Stores exists"; $storeReady = $false
} elseif ($StoresUrl) {
    Copy-StoreRepo $StoresUrl
} elseif ($Interactive) {
    Write-Host "  No store repo at $Stores. It holds your memory, plans and artifacts (private)."
    $ans = Read-Host "  [c]lone yours from a URL, create a [n]ew local one, or [s]kip? [n]"
    if ([string]::IsNullOrWhiteSpace($ans)) { $ans = 'n' }
    switch -Regex ($ans) {
        '^[cC]' {
            $StoresUrl = Read-Host "  Store repo URL"
            if ($StoresUrl) { Copy-StoreRepo $StoresUrl } else { Write-Host "  SKIPPED: no URL given"; $storeReady = $false }
        }
        '^[nN]' { New-StoreRepo }
        default { Write-Host "  SKIPPED: store repo; memory stays off until $Stores exists"; $storeReady = $false }
    }
} elseif ($Yes) {
    New-StoreRepo
} else {
    Write-Host "  NOTE: no store repo at $Stores; memory is off. Re-run with -StoresUrl URL or -Yes, or interactively."
    $storeReady = $false
}
if ($storeReady) { Initialize-UserMemory }

$MemLink = Join-Path $ScriptDir "memory"
$MemTarget = Join-Path $Stores "user\memory"
$memItem = Get-Item -LiteralPath $MemLink -Force -ErrorAction SilentlyContinue
$linkMemory = $true
if ($memItem -and ($memItem.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
    if ([string]($memItem.Target | Select-Object -First 1) -eq $MemTarget) {
        Write-Host "  OK: $MemLink -> $MemTarget"; $linkMemory = $false
    } elseif (-not $Interactive -and -not $Yes) {
        # never repoint the repo's link unasked: a sandboxed run (test-parity) would aim it at a store
        # that is deleted afterwards
        Write-Host "  NOTE: $MemLink points to $($memItem.Target), not $MemTarget; re-run with -Yes or interactively to repoint it"
        $linkMemory = $false
    } else {
        Write-Host "  UPDATE: $MemLink (was -> $($memItem.Target))"
        Remove-DirLink $MemLink
    }
} elseif ($memItem) {
    Write-Host "  NOTE: $MemLink is a real folder; memory stays there until you move it to $MemTarget"; $linkMemory = $false
}
if ($linkMemory) {
    if (-not (Test-Path $MemTarget) -and -not $DryRun) {
        Write-Host "  NOTE: no $MemTarget yet; the memory link is made once the store repo holds user memory"
    } elseif (-not $Interactive -and -not $Yes) {
        Write-Host "  NOTE: $MemLink is not linked yet; re-run with -Yes or interactively to link it to $MemTarget"
    } else {
        # a symlink, never a junction: dream-write refuses junctions on the memory path
        Invoke-Act "link $MemLink -> $MemTarget" {
            try {
                New-Item -ItemType SymbolicLink -Path $MemLink -Target $MemTarget -ErrorAction Stop | Out-Null
            } catch {
                cmd /c mklink /D "$MemLink" "$MemTarget" | Out-Null
            }
        }
        Write-Host "  LINKED: $MemLink -> $MemTarget"
    }
}

Write-Host "=== Engine branch ==="
$Branch = 'local-improvements'
# Native git writes to stderr ("not a git repository"); under Stop, Windows PowerShell 5.1 would
# turn that into a terminating error, so this section runs with Continue.
$prevEap = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
& git -C $ScriptDir rev-parse --git-dir 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "  SKIPPED: $ScriptDir is not a git checkout"
} else {
    $cur = (& git -C $ScriptDir symbolic-ref -q --short HEAD 2>$null)
    if ($cur -eq $Branch) {
        Write-Host "  OK: on $Branch"
    } elseif (-not $Interactive -and -not $Yes) {
        $shownCur = if ($cur) { $cur } else { 'a detached HEAD' }
        Write-Host "  NOTE: on $shownCur; engine commits (/qconfig-sync, /qdream) land on $Branch -- re-run with -Yes or interactively to set it up"
    } elseif (-not (Confirm-Step "Engine commits (/qconfig-sync, /qdream) land on '$Branch', never on main. Set it up and switch to it?" $true)) {
        Write-Host "  SKIPPED: engine branch"
    } else {
        & git -C $ScriptDir show-ref -q --verify "refs/heads/$Branch" 2>$null
        if ($LASTEXITCODE -ne 0) {
            Invoke-Act "git branch $Branch" { & git -C $ScriptDir branch -q $Branch }
            Write-Host "  CREATED: branch $Branch"
        }
        if (& git --no-optional-locks -C $ScriptDir status --porcelain --untracked-files=no 2>$null) {
            Write-Host "  NOTE: uncommitted changes in $ScriptDir; switch yourself when ready: git -C $ScriptDir switch $Branch"
        } else {
            Invoke-Act "git switch $Branch" { & git -C $ScriptDir switch -q $Branch }
            Write-Host "  SWITCHED: $ScriptDir is on $Branch"
        }
    }
}
$ErrorActionPreference = $prevEap

Write-Host "=== Pointer file ==="
$url = if ($StoresUrl) { $StoresUrl } else { Get-ConfigValue 'stores_url' }
$text = "# agent-playbook pointer file, written by setup (shared/AGENTS.md, Config Repo Locations).`n"
$text += "root=$(ConvertTo-PointerPath $ScriptDir)`n"
$text += "stores=$(ConvertTo-PointerPath $Stores)`n"
if ($url) { $text += "stores_url=$url`n" }
$text += "engine_branch=$Branch`n"
$text += "providers=$($Chosen -join ',')`n"
if ((Test-Path -LiteralPath $ConfigFile) -and ([IO.File]::ReadAllText($ConfigFile) -eq $text)) {
    Write-Host "  OK: $ConfigFile"
} else {
    New-DirIfMissing (Split-Path -Parent $ConfigFile)
    Write-TextFile $ConfigFile $text
    Write-Host "  WROTE: $ConfigFile"
}

function Deploy-ManifestLinks {
    param([string]$Mode)
    foreach ($entry in ($ManifestEntries | Where-Object { $_.mode -eq $Mode })) {
        $dest = Expand-Dest $entry.dest
        $source = Expand-Source $entry.source
        New-DirIfMissing (Split-Path -Parent $dest)
        switch ($entry.kind) {
            'symlink-file' { Link-File -Target $source -Link $dest }
            'symlink-dir'  { Link-Dir  -Target $source -Link $dest }
        }
    }
}

# --- Claude Code ---
if (Test-Wants 'claude') {
    Write-Host "=== Claude Code ==="
    New-DirIfMissing (Join-Path $env:USERPROFILE ".claude")
    Deploy-ManifestLinks 'claude'
    Write-Host "  Skills (individual):"
    Link-Skills (Join-Path $env:USERPROFILE ".claude\skills")
}

# --- Codex ---
# Codex keeps built-in skills in skills\.system\: one link per skill preserves them.
if (Test-Wants 'codex') {
    Write-Host "=== Codex ==="
    New-DirIfMissing (Join-Path $env:USERPROFILE ".codex")
    Deploy-ManifestLinks 'codex'
    Write-Host "  Skills (individual):"
    Link-Skills (Join-Path $env:USERPROFILE ".codex\skills")
}

# --- Gemini CLI ---
if (Test-Wants 'gemini') {
    Write-Host "=== Gemini CLI ==="
    New-DirIfMissing (Join-Path $env:USERPROFILE ".gemini")
    Deploy-ManifestLinks 'gemini'
    Write-Host "  Skills (individual):"
    Link-Skills (Join-Path $env:USERPROFILE ".gemini\skills")
}

if (Test-Wants 'kiro') {
    # --- Kiro CLI ---
    Write-Host "=== Kiro CLI ==="
    $KiroAgentsDir = Join-Path (Join-Path $env:USERPROFILE ".kiro") "agents"
    New-DirIfMissing $KiroAgentsDir
    $KiroSettingsDir = Join-Path (Join-Path $env:USERPROFILE ".kiro") "settings"
    New-DirIfMissing $KiroSettingsDir

    # Deploy kiro-always entries from manifest
    foreach ($entry in ($ManifestEntries | Where-Object { $_.mode -eq 'kiro-always' })) {
        $dest = Expand-Dest $entry.dest
        $source = Expand-Source $entry.source
        New-DirIfMissing (Split-Path -Parent $dest)
        if (Test-Path $source) {
            switch ($entry.kind) {
                'template-file' { Copy-Template -Source $source -Dest $dest }
                'seed-file'     { Copy-Seed -Source $source -Dest $dest }
                default         { Copy-File -Source $source -Dest $dest }
            }
        }
    }

    if ($env:AGENT_PLAYBOOK_SKIP_KIRO_CLI -eq '1') {
        Write-Host "  SKIP: kiro-cli settings (AGENT_PLAYBOOK_SKIP_KIRO_CLI=1)"
    } elseif (Get-Command kiro-cli -ErrorAction SilentlyContinue) {
        if ($DryRun) {
            Write-Host "    DRY: kiro-cli settings --global chat.defaultAgent kiro_default"
        } else {
            try {
                & kiro-cli settings --global chat.defaultAgent kiro_default
                Write-Host "  SET: chat.defaultAgent = kiro_default (global)"
            } catch {
                Write-Warning "  WARN: Failed to set chat.defaultAgent: $_"
            }
        }
    }

    # --- Kiro IDE ---
    # Steering and plain skills are SYMLINKS into the repo, like every other
    # provider (Link-File/Link-Dir above). The former copy mode rested on "Kiro IDE
    # does not follow symlinks on Windows", which was re-measured 2026-08-17 and
    # does not reproduce; copies were retired 2026-09-20. Overlay-bearing skills
    # stay generated copies on every platform: the merge overwrites one file inside
    # the skill dir, which a symlinked dir forbids. A regular file the old copy mode
    # left at a linked steering destination is a deploy artifact and is removed
    # before linking, never backed up: it is recoverable from the repo.
    Write-Host "=== Kiro IDE ==="
    $KiroSteeringDir = Join-Path (Join-Path $env:USERPROFILE ".kiro") "steering"
    $KiroSkillsDir = Join-Path (Join-Path $env:USERPROFILE ".kiro") "skills"
    New-DirIfMissing $KiroSteeringDir
    New-DirIfMissing $KiroSkillsDir

    # Remove a regular file or directory the old copy mode left at a destination
    # that is now linked. Reparse points are left alone: Link-File / Link-Dir
    # replace an outdated link and keep a correct one.
    function Remove-DeployedCopy {
        param([string]$Path)
        if (-not (Test-Path $Path)) { return }
        $item = Get-Item $Path -Force
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { return }
        Invoke-Act "remove $Path" { if ($item.PSIsContainer) { Remove-Item $Path -Recurse -Force } else { Remove-Item $Path -Force } }
        Write-Host "  REMOVED COPY: $Path (replaced by a link)"
    }

    # Steering files from manifest (mode kiro). Steering is flat: every deployed
    # file sits directly in ~/.kiro/steering/.
    foreach ($entry in ($ManifestEntries | Where-Object { $_.mode -eq 'kiro' })) {
        $dest = Expand-Dest $entry.dest
        $source = Expand-Source $entry.source
        New-DirIfMissing (Split-Path -Parent $dest)
        Remove-DeployedCopy $dest
        Link-File -Target $source -Link $dest
    }

    # Build list of managed skill names for cleanup pass
    $ManagedSkills = @()

    # Shared skills (with overlay-merge support). Any overlay forces a Copy-Dir (symlinked
    # dirs can't have a single file overwritten); a plain skill is a Link-Dir. Aux merges
    # run AFTER the dir copy so they overwrite the freshly-copied targets.
    Write-Host "  Shared skills:"
    $KiroOverlayRoot = Join-Path $ScriptDir "providers\kiro\skills"
    Get-ChildItem (Join-Path $SharedDir "skills") -Directory | ForEach-Object {
        $name = $_.Name
        if (-not (Test-Path (Join-Path $_.FullName "SKILL.md"))) { return }
        $overlayDir = Join-Path $KiroOverlayRoot $name
        $skillOverlay = Join-Path $overlayDir "OVERLAY.md"
        $dest = Join-Path $KiroSkillsDir $name
        if (Test-HasAnyOverlay $overlayDir) {
            Copy-Dir -Source $_.FullName -Dest $dest
            if (Test-Path $skillOverlay) {
                $merged = Merge-Overlay -SharedFile (Join-Path $_.FullName "SKILL.md") -OverlayFile $skillOverlay
                if (([IO.File]::ReadAllText($skillOverlay)).Trim().Length -eq 0) {
                    Write-Host "  SKIPPED EMPTY OVERLAY: $name"
                }
                Write-MergedFile -Path (Join-Path $dest "SKILL.md") -Content $merged
                Write-Host "  MERGED: $name (shared + kiro overlay)"
            }
            # Aux overlays run after the dir copy so they overwrite the copied targets.
            Apply-AuxOverlays -OverlayDir $overlayDir -Dest $dest -SourceDir $_.FullName
        } else {
            $existing = Get-Item -LiteralPath $dest -Force -ErrorAction SilentlyContinue
            if ($existing -and $existing.PSIsContainer -and
                -not ($existing.Attributes -band [IO.FileAttributes]::ReparsePoint) -and
                -not (Test-Path (Join-Path $dest "SKILL.md"))) {
                Write-Host "  KEPT: $dest is your own folder; the playbook's $name skill is not linked there"
                return
            }
            # a generated copy left by an older overlay, now a plain skill: regenerate as a link
            Remove-DeployedCopy $dest
            Link-Dir -Target $_.FullName -Link $dest
        }
        $ManagedSkills += $name
    }

    # Kiro-specific skills
    $KiroProviderSkills = Join-Path $ScriptDir "providers\kiro\skills"
    if (Test-Path $KiroProviderSkills) {
        Write-Host "  Kiro-specific skills:"
        Get-ChildItem $KiroProviderSkills -Directory | ForEach-Object {
            if (Test-Path (Join-Path $_.FullName "SKILL.md")) {
                # Skip if this dir is a shared-skill overlay (SKILL.md and/or aux overlays)
                # already merged above, rather than a standalone kiro-only skill.
                if (Test-HasAnyOverlay (Join-Path $KiroOverlayRoot $_.Name)) { return }
                Link-Dir -Target $_.FullName -Link (Join-Path $KiroSkillsDir $_.Name)
                $ManagedSkills += $_.Name
            }
        }
    }

    # A stale playbook skill is a link into this repo that no current skill owns. Any
    # other folder is the user's own (or another pack's) and is never removed. A
    # directory symlink is removed with rmdir, never Remove-Item -Recurse, which on
    # Windows PowerShell 5.1 can follow the link and delete the repo's files.
    Write-Host "  Cleaning stale skills:"
    if (Test-Path $KiroSkillsDir) {
        Get-ChildItem $KiroSkillsDir -Directory -Force | Where-Object {
            $_.Name -notin $ManagedSkills -and (Test-EngineLink $_.FullName)
        } | ForEach-Object {
            Remove-DirLink $_.FullName
            Write-Host "  REMOVED: $($_.Name) (stale, not in repo)"
        }
    }

    Write-Host ""
    Write-Host "=== Cleanup stale files ==="
    # Files: names a previous deployment wrote that the current manifest no longer
    # owns. NEVER list a path the manifest currently deploys (this runs after the
    # steering loop and would delete the fresh copy).
    # Entries are dated; drop one once every machine has certainly re-run setup
    # since (a few months), so the list does not grow forever.
    $StaleFiles = @(
        (Join-Path $KiroAgentsDir "kiro_default.json"),                 # 2026-08-18
        (Join-Path $KiroSteeringDir "claude-code-local-data.md"),       # 2026-09-20, and the rest
        (Join-Path $KiroSteeringDir "v2-only\kiro-cli-local-data.md"),
        (Join-Path $KiroSteeringDir "v2-only\memory-sources.md"),
        (Join-Path $KiroSteeringDir "v2-only\session-resume-recovery-2.14.0.md"),
        (Join-Path $KiroSteeringDir "v3\kiro-cli-local-data.md"),
        (Join-Path $KiroSteeringDir "v3\memory-sources.md")
    )
    foreach ($stale in $StaleFiles) {
        if (Test-Path $stale) {
            Invoke-Act "remove $stale" { Remove-Item $stale -Force }
            Write-Host "  REMOVED stale: $stale"
        }
    }
    # Directories: the retired v2-only\ and v3\ steering subdirectories (kiro-cli v2
    # retirement, 2026-09-20). Removed only when empty, so a user-placed file survives.
    foreach ($staleDir in @((Join-Path $KiroSteeringDir "v2-only"), (Join-Path $KiroSteeringDir "v3"))) {
        if ((Test-Path $staleDir -PathType Container) -and -not (Get-ChildItem $staleDir -Force | Select-Object -First 1)) {
            Invoke-Act "remove $staleDir" { Remove-Item $staleDir -Force }
            Write-Host "  REMOVED stale dir: $staleDir"
        }
    }

    Write-Host ""
    Write-Host "=== Verify v3 deployment ==="
    if (-not $DryRun) {
        $v3Expected = @(
            (Join-Path $KiroAgentsDir "kiro_default.md"),
            (Join-Path $KiroAgentsDir "qdream_child.md"),
            (Join-Path $KiroSettingsDir "permissions.yaml")
        )
        $v3Missing = $v3Expected | Where-Object { -not (Test-Path $_) }
        if ($v3Missing) { Write-Warning "v3 deployment incomplete: $($v3Missing -join ', ')" }
        else { Write-Host "  OK: v3 agent and permissions deployed" }
    }
}

Write-Host ""
Write-Host "Done (providers: $($Chosen -join ', ')). Run '/qconfig-sync' from any agent to verify."
if (Test-Wants 'claude') {
    Write-Host "NOTE: statusLine and notification hooks also need manual entries in"
    Write-Host "      ~/.claude/settings.json -- see providers/claude/README.md."
    Write-Host "      '/qconfig-sync' does not check these; it reports OK without them."
    Write-Host "      The SessionStart memory hook entry runs the launcher, memory-load-hook.ps1,"
    Write-Host "      not python.exe directly (README, 'SessionStart memory hook')."
}
