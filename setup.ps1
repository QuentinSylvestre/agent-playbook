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
# In every mode, your own ~\.claude\CLAUDE.md or ~\.gemini\GEMINI.md stays where it is and
# the playbook loads beside it (see "Co-existence" below); Codex has no such mechanism.
#
# Kiro overlay merge: for a shared skill dir, kiro discipline deltas live under
# providers\kiro\skills\<name>\ and are APPENDED to the deployed copy at setup time:
#   - SKILL.md overlay : OVERLAY.md          -> appended to the deployed SKILL.md
#   - aux-file overlay  : <stem>.OVERLAY.md  -> appended to the deployed <stem>.md
#     (e.g. memory-rules.OVERLAY.md -> memory-rules.md)
# Any overlay makes the skill a generated copy (a single file inside a symlinked dir
# cannot be overwritten). SKILL.OVERLAY.md is reserved/forbidden (SKILL.md uses the
# bare OVERLAY.md) and an overlay whose target file is absent is skipped with a
# warning. See Merge-Overlay / Get-AuxOverlayTargets / Deploy-GeneratedCopy below.
#
# Ownership: every regular file setup writes is recorded in the deploy lock
# (~\.agent-playbook\deploy-lock.tsv, see "Deploy lock" below), seed files excepted. A re-run
# writes only what changed, removes what it wrote once the source is gone, and moves a file you
# edited or own to <path>.bak (one backup per path) before it writes there. A backup that cannot
# be made leaves that path unchanged and ends the run non-zero.

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
                    a file of yours that is in the way). Your own ~\.claude\CLAUDE.md
                    or ~\.gemini\GEMINI.md is never replaced: the playbook loads beside it.
  -StoresUrl URL    clone the store repo from URL when it is missing.
  -NoStores         do not set up a store repo (memory is disabled until you do).
  -Uninstall        remove what setup deployed for the chosen providers: links into
                    this repo, the files it wrote and you did not edit (by the deploy
                    lock), the Claude Code settings entries; restore each .bak setup
                    made, and kiro-cli's default agent when setup set it.
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

# Get-LongPath: Path with backslashes and every 8.3 short name (QSYLVE~1.POL) expanded to the long
# name on disk (setup.sh: long_path, cygpath -m -l). A part that does not exist is kept as written.
function Get-LongPath {
    param([string]$Path)
    $p = $Path.Replace('/', '\')
    if (-not $p.Contains('~')) { return $p }
    $parts = $p.Split('\')
    $out = $parts[0]
    for ($i = 1; $i -lt $parts.Count; $i++) {
        $n = $parts[$i]
        if ($n.Contains('~') -and $out) {
            $hit = @()
            try { $hit = @((New-Object IO.DirectoryInfo ($out + '\')).GetFileSystemInfos($n)) } catch { $hit = @() }
            if ($hit.Count -eq 1) { $n = $hit[0].Name }
        }
        $out = $out + '\' + $n
    }
    return $out
}

$EngineRootLong = Get-LongPath $ScriptDir

# Test-UnderRoot: Path is Root or lies inside it, letter case ignored (NTFS ignores it).
function Test-UnderRoot {
    param([string]$Path, [string]$Root)
    return ($Path -eq $Root) -or $Path.StartsWith($Root + '\', [StringComparison]::OrdinalIgnoreCase)
}

# Test-EngineLink: a reparse point (symlink or junction) whose target lies inside this repo. Both
# sides are compared in their long form, case ignored, so a link made through the repo's 8.3 short
# path is still the playbook's.
function Test-EngineLink {
    param([string]$Path)
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
    if (-not $item -or -not ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) { return $false }
    $t = [string]($item.Target | Select-Object -First 1)
    if (-not $t) { return $false }
    $t = ($t -replace '^\\\\\?\\', '').Replace('/', '\')
    if (-not [IO.Path]::IsPathRooted($t)) { $t = Join-Path (Split-Path -Parent $Path) $t }
    if (Test-UnderRoot $t $ScriptDir) { return $true }
    return (Test-UnderRoot (Get-LongPath $t) $EngineRootLong)
}

# Test-SameTarget: two link targets that name the same path.
function Test-SameTarget {
    param([string]$A, [string]$B)
    if ($A -eq $B) { return $true }
    return ((Get-LongPath ($A -replace '^\\\\\?\\', '')) -eq (Get-LongPath $B))
}

# Remove a directory link without following it (Remove-Item -Recurse can delete the target's files).
function Remove-DirLink { param([string]$Path) Invoke-Act "rmdir $Path" { cmd /c rmdir "$Path" 2>$null } }

# --- Deploy lock -----------------------------------------------------------
# ~\.agent-playbook\deploy-lock.tsv names the regular files setup wrote, so a re-run can tell its
# own unedited files from yours. The format, the kinds and the ownership rule are documented once,
# in setup.sh's "Deploy lock" section (the journal, the unreadable-lock .bak, and the rule for a
# .bak that is not setup's or a backup that fails included); this twin writes the same bytes on the
# same machine (rows sorted by ordinal order, LF, no BOM). The path is built from $env:USERPROFILE
# only: PowerShell's own $HOME and ~ name the real profile even when USERPROFILE points at a sandbox.
# Seed files are the ownership rule's one exception: written only when absent, never locked.

$LockHeader = "# agent-playbook deploy lock v1 (written by setup; kind<TAB>path<TAB>sha256)"
$LockFile = Join-Path (Join-Path $env:USERPROFILE ".agent-playbook") "deploy-lock.tsv"
$LockJournal = Join-Path (Join-Path $env:USERPROFILE ".agent-playbook") "deploy-lock.journal.tsv"
$script:LockReadable = $false
$script:LockUnreadable = $false
$script:BackupFailed = 0
# keys this run had to leave alone (a failed or refused backup): never retired
$LockHeld = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
$LockSettingKey = "kiro-cli/chat.defaultAgent"
$LockGeminiKey = "gemini/context.fileName"
$LockFileKinds = @('copy-dir-recursive', 'merge-file', 'copy-file', 'template-file')
$LockOld = New-Object 'System.Collections.Generic.List[string[]]'
$LockOldValue = @{}
$LockNew = New-Object 'System.Collections.Generic.List[string]'
$Utf8NoBom = New-Object System.Text.UTF8Encoding $false

function Get-FileSha {
    param([string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-BytesSha {
    param([byte[]]$Bytes)
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($sha.ComputeHash($Bytes)).Replace('-', '').ToLowerInvariant() } finally { $sha.Dispose() }
}

# Get-ShaMap: path -> lowercase sha256 for many files, keyed by the path exactly as given
# (Get-FileHash reports a resolved long path, which would not match a short-name USERPROFILE).
function Get-ShaMap {
    param([string[]]$Paths)
    $map = @{}
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        foreach ($p in $Paths) {
            if (-not $p) { continue }
            $fs = [IO.File]::OpenRead($p)
            try { $map[$p] = [BitConverter]::ToString($sha.ComputeHash($fs)).Replace('-', '').ToLowerInvariant() } finally { $fs.Dispose() }
        }
    } finally { $sha.Dispose() }
    return $map
}

function ConvertTo-LockKey {
    param([string]$Path)
    if ($Path.StartsWith($env:USERPROFILE + '\', [StringComparison]::OrdinalIgnoreCase)) {
        return '~/' + $Path.Substring($env:USERPROFILE.Length + 1).Replace('\', '/')
    }
    return ''   # outside home: no lock spelling, never recorded
}

# Test-LockRow: one row of the lock format (setup.sh LOCK_ROWS_AWK).
function Test-LockRow {
    param([string[]]$c)
    if ($c.Count -ne 3) { return $false }
    if ($c[0] -ceq 'setting') { return (($c[1] -ceq $LockSettingKey -or $c[1] -ceq $LockGeminiKey) -and $c[2] -ne '') }
    if (($LockFileKinds + 'backup') -cnotcontains $c[0]) { return $false }
    if (-not $c[1].StartsWith('~/') -or ("/" + $c[1] + "/").Contains('/../') -or $c[1].Contains('\') -or $c[1].Contains(':')) { return $false }
    if ($c[0] -ceq 'backup' -and $c[2] -ceq '-') { return $true }
    return ($c[2] -cmatch '^[0-9a-f]{64}$')
}

# Read-LockLines: a lock-format file's lines (LF, no BOM), without the empty last one.
function Read-LockLines {
    param([string]$Path)
    $text = $Utf8NoBom.GetString([IO.File]::ReadAllBytes($Path))
    if ($text.Length -eq 0) { return , @() }
    $lines = $text.Split("`n")
    if ($text.EndsWith("`n")) { $lines = @($lines[0..($lines.Count - 2)]) }
    return , $lines
}

function ConvertFrom-LockKey {
    param([string]$Key)
    return Join-Path $env:USERPROFILE ($Key.Substring(2).Replace('/', '\'))
}

function Get-KeyProvider {
    param([string]$Key)
    if ($Key.StartsWith('~/.kiro/') -or $Key -eq $LockSettingKey) { return 'kiro' }
    if ($Key -eq $LockGeminiKey) { return 'gemini' }
    foreach ($p in 'claude', 'codex', 'gemini') { if ($Key.StartsWith("~/.$p/")) { return $p } }
    return 'none'
}

# Get-PathAttributes: the entry's own attributes (a link is not followed), or $null when absent.
function Get-PathAttributes {
    param([string]$Path)
    try { return [IO.File]::GetAttributes($Path) } catch { return $null }
}

function Test-Reparse {
    param([string]$Path)
    $a = Get-PathAttributes $Path
    return [bool]($null -ne $a -and ($a -band [IO.FileAttributes]::ReparsePoint))
}

function Test-RegularFile {
    param([string]$Path)
    $a = Get-PathAttributes $Path
    return [bool]($null -ne $a -and -not ($a -band ([IO.FileAttributes]::Directory -bor [IO.FileAttributes]::ReparsePoint)))
}

# Read-DeployLock: the previous lock's rows, or none. The lock is untrusted input: another first
# line or one malformed row means no lock (the first-run case); only ~/ paths with no .. segment.
function Read-DeployLock {
    $LockOld.Clear(); $LockOldValue.Clear()
    $rows = @()
    if (Test-Path -LiteralPath $LockFile -PathType Leaf) {
        $lines = Read-LockLines $LockFile
        $ok = ($lines.Count -ge 1) -and ($lines[0] -ceq $LockHeader)
        $fileRows = @()
        for ($i = 1; $ok -and $i -lt $lines.Count; $i++) {
            $c = $lines[$i].Split("`t")
            if (-not (Test-LockRow $c)) { $ok = $false; break }
            $fileRows += , $c
        }
        if ($ok) {
            $script:LockReadable = $true
            $rows = $fileRows
        } else {
            $script:LockUnreadable = $true
            Write-Host "  NOTE: $LockFile is not a deploy lock this setup can read; treating this as a first run (it is kept as $LockFile.bak)"
        }
    }
    # backup rows of a run that stopped before writing its lock: newer than the lock's own rows
    if (Test-Path -LiteralPath $LockJournal -PathType Leaf) {
        $jrows = @(); $jok = $true
        foreach ($line in (Read-LockLines $LockJournal)) {
            $c = $line.Split("`t")
            if ($c[0] -cne 'backup' -or -not (Test-LockRow $c)) { $jok = $false; break }
            $jrows += , $c
        }
        if ($jok) {
            $rows = @($jrows) + @($rows)
            Write-Host "  NOTE: merged the backups an interrupted run recorded in $LockJournal"
        } else {
            Write-Host "  NOTE: $LockJournal is not a journal this setup can read; ignored"
        }
    }
    foreach ($c in $rows) {
        $LockOld.Add($c)
        $k = $c[0] + "`t" + $c[1]
        if (-not $LockOldValue.ContainsKey($k)) { $LockOldValue[$k] = $c[2] }
    }
}

# Add-LockRow: a row for the lock this run writes. A path outside home has no lock spelling: it is
# not recorded (setup.sh lock_add).
function Add-LockRow {
    param([string]$Kind, [string]$Key, [string]$Value)
    if ($Kind -ne 'setting') {
        if (-not $Key.StartsWith('~/')) { Write-Host "  NOTE: a path outside $env:USERPROFILE is not recorded in the deploy lock"; return }
        if ($Key.Contains('\') -or $Key.Contains(':')) { Write-Host "  NOTE: $Key is not recorded in the deploy lock (its name holds \ or :)"; return }
    }
    $LockNew.Add("$Kind`t$Key`t$Value")
}

function Get-LockValue {
    param([string]$Kind, [string]$Key)
    $k = "$Kind`t$Key"
    if ($LockOldValue.ContainsKey($k)) { return $LockOldValue[$k] }
    return ''
}

# Complete-DeployLock: write the new lock when its bytes differ (temp file, then replace). New rows
# win over carried rows for the same path and kind class. -DropEmpty (uninstall) deletes an empty lock.
function Complete-DeployLock {
    param([string[]]$Carry, [switch]$DropEmpty)
    if ($DryRun) { return }
    $seen = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::Ordinal)
    $rows = New-Object 'System.Collections.Generic.List[string]'
    foreach ($line in (@($LockNew) + @($Carry))) {
        if (-not $line) { continue }
        $c = $line.Split("`t")
        $cls = if ($c[0] -eq 'backup' -or $c[0] -eq 'setting') { $c[0] } else { 'file' }
        if ($seen.Add($cls + "`t" + $c[1])) { $rows.Add($line) }
    }
    $arr = $rows.ToArray()
    [Array]::Sort($arr, [StringComparer]::Ordinal)
    $exists = Test-Path -LiteralPath $LockFile -PathType Leaf
    if ($script:LockUnreadable -and $exists) {
        [IO.File]::Copy($LockFile, "$LockFile.bak", $true)
        [IO.File]::Delete($LockFile)
        $exists = $false
        Write-Host "  BACKUP: $LockFile -> $LockFile.bak (a deploy lock this setup cannot read)"
    }
    if ($arr.Count -eq 0) {
        if ($DropEmpty -and $exists) {
            Remove-Item -LiteralPath $LockFile -Force; Remove-Item -LiteralPath $LockJournal -Force -ErrorAction SilentlyContinue
            Write-Host "  REMOVED: $LockFile"; return
        }
        if (-not $exists) { Remove-Item -LiteralPath $LockJournal -Force -ErrorAction SilentlyContinue; return }
    }
    $text = $LockHeader + "`n"
    foreach ($r in $arr) { $text += $r + "`n" }
    $bytes = $Utf8NoBom.GetBytes($text)
    if ($exists -and ((Get-BytesSha $bytes) -eq (Get-FileSha $LockFile))) {
        Remove-Item -LiteralPath $LockJournal -Force -ErrorAction SilentlyContinue
        Write-Host "  OK: $LockFile"; return
    }
    New-DirIfMissing (Split-Path -Parent $LockFile)
    $tmp = "$LockFile.tmp-$PID"
    [IO.File]::WriteAllBytes($tmp, $bytes)
    if ($exists) { [IO.File]::Replace($tmp, $LockFile, [NullString]::Value) } else { [IO.File]::Move($tmp, $LockFile) }
    Remove-Item -LiteralPath $LockJournal -Force -ErrorAction SilentlyContinue
    Write-Host "  WROTE: $LockFile"
}

# Get-LockCarryRows: the previous lock's rows this run keeps: rows of a provider not deployed now,
# and backup rows whose .bak is still there.
function Get-LockCarryRows {
    $out = New-Object 'System.Collections.Generic.List[string]'
    foreach ($c in $LockOld) {
        if ($c[0] -eq 'backup') {
            $bp = ConvertFrom-LockKey $c[1]
            # a .bak reached through a linked folder is not looked at (it may lie outside the deployment)
            if ((Test-NoLinkParent $bp $env:USERPROFILE) -and $null -ne (Get-PathAttributes ($bp + '.bak'))) { $out.Add($c -join "`t") }
        } elseif (-not (Test-Wants (Get-KeyProvider $c[1]))) {
            $out.Add($c -join "`t")
        }
    }
    return , $out.ToArray()
}

# Get-OwnAction: the ownership rule, the one decision for every file setup writes (setup.sh own_rule).
function Get-OwnAction {
    param([string]$Want, [string]$Cur, [string]$Locked)
    if ($Cur -eq '-') { return 'write' }
    if ($Cur -eq $Want) { return 'keep' }
    if ($Locked -ne '-' -and $Cur -eq $Locked) { return 'replace' }
    return 'backup'
}

# Test-NoLinkParent: no folder between Top (exclusive) and Path is a link.
function Test-NoLinkParent {
    param([string]$Path, [string]$Top)
    $d = [IO.Path]::GetDirectoryName($Path)
    while ($d -and $d.Length -gt $Top.Length -and $d -ne $Top) {
        if (Test-Reparse $d) { return $false }
        $d = [IO.Path]::GetDirectoryName($d)
    }
    return $true
}

# Remove-EmptyDirs: remove every empty folder under Dir, Dir included, deepest first, never
# entering a link (setup.sh: find Dir -type d -empty -delete).
function Remove-EmptyDirs {
    param([string]$Dir)
    if ($DryRun -or -not (Test-Path -LiteralPath $Dir -PathType Container) -or (Test-Reparse $Dir)) { return }
    $dirs = New-Object 'System.Collections.Generic.List[string]'
    $stack = New-Object 'System.Collections.Generic.Stack[string]'
    $stack.Push($Dir)
    while ($stack.Count) {
        $d = $stack.Pop()
        $dirs.Add($d)
        foreach ($e in (New-Object IO.DirectoryInfo $d).GetDirectories()) {
            if (-not ($e.Attributes -band [IO.FileAttributes]::ReparsePoint)) { $stack.Push([IO.Path]::Combine($d, $e.Name)) }
        }
    }
    for ($i = $dirs.Count - 1; $i -ge 0; $i--) {
        if (-not [IO.Directory]::EnumerateFileSystemEntries($dirs[$i]).GetEnumerator().MoveNext()) { [IO.Directory]::Delete($dirs[$i]) }
    }
}

# Get-SkillDirOf: the ~\.kiro\skills\<name> folder a path lies in, or '' outside one.
function Get-SkillDirOf {
    param([string]$Path)
    $root = Join-Path $env:USERPROFILE ".kiro\skills"
    if (-not $Path.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase)) { return '' }
    $rest = $Path.Substring($root.Length + 1)
    $i = $rest.IndexOf('\')
    if ($i -lt 1) { return '' }
    return Join-Path $root $rest.Substring(0, $i)
}

# Remove-PathNoFollow: delete a file, a folder or a link without following any link inside it.
function Remove-PathNoFollow {
    param([string]$Path)
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
    if (-not $item) { return }
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        if ($item.PSIsContainer) { [IO.Directory]::Delete($Path) } else { [IO.File]::Delete($Path) }
    } elseif ($item.PSIsContainer) {
        [IO.Directory]::Delete($Path, $true)
    } else {
        [IO.File]::Delete($Path)
    }
}

# Move-PathNoFollow: rename a file, folder or link (a link is moved, never followed).
function Move-PathNoFollow {
    param([string]$From, [string]$To)
    $item = Get-Item -LiteralPath $From -Force
    if ($item.PSIsContainer) { [IO.Directory]::Move($From, $To) } else { [IO.File]::Move($From, $To) }
}

# Backup-Path: move a file, folder or link that is not setup's to <path>.bak, the single bounded
# backup, and record the backup in the lock and its journal at once (setup.sh backup_path). An
# existing <path>.bak is replaced only when the lock shows setup made it (and, for a file, that it is
# unchanged since); otherwise it is yours: nothing moves, a WARN says what to do, and it returns 2. A
# move that fails puts the older .bak back, prints an ERROR (the run then ends non-zero) and returns
# 1. Returns 0 when the path is free. On any other value the caller skips its write and lock row.
function Backup-Path {
    param([string]$Path)
    $key = ConvertTo-LockKey $Path
    $bak = "${Path}.bak"
    $h = if (Test-RegularFile $Path) { Get-FileSha $Path } else { '-' }
    if ($null -ne (Get-PathAttributes $bak)) {
        $old = Get-LockValue 'backup' $key
        if (-not $old -or ($old -ne '-' -and (-not (Test-RegularFile $bak) -or (Get-FileSha $bak) -ne $old))) {
            Write-Host "  WARN: $bak is not a backup setup made, so $Path is left unchanged; move $bak away, then re-run setup"
            [void]$LockHeld.Add($key)
            return 2
        }
    }
    Write-Host "  BACKUP: $Path -> $bak"
    if ($DryRun) { Write-Host "    DRY: move $Path $bak"; Add-LockRow 'backup' $key $h; return 0 }
    $aside = ''
    $failed = $false
    try {
        if ($null -ne (Get-PathAttributes $bak)) { $aside = "$bak.tmp-$PID"; Move-PathNoFollow $bak $aside }
        Move-PathNoFollow $Path $bak
    } catch {
        $failed = $true
        if ($aside -and $null -ne (Get-PathAttributes $aside) -and $null -eq (Get-PathAttributes $bak)) {
            try { Move-PathNoFollow $aside $bak } catch { }
        }
    }
    if ($failed) {
        [Console]::Error.WriteLine("ERROR: could not back up $Path; left unchanged")
        $script:BackupFailed++
        [void]$LockHeld.Add($key)
        return 1
    }
    if ($aside) { Remove-PathNoFollow $aside }
    Add-LockRow 'backup' $key $h
    if ($key.StartsWith('~/')) {
        New-DirIfMissing (Split-Path -Parent $LockJournal)
        [IO.File]::AppendAllText($LockJournal, "backup`t$key`t$h`n", $Utf8NoBom)
    }
    return 0
}

# --- Linking ---------------------------------------------------------------

# Clear-WayFor: a file, folder or link of the user's (a link that does not point into this repo)
# sits where a link goes. Returns $true when the path is free afterwards (backed up to .bak),
# $false to skip it. Only an interactive run asks; -Yes and a run with no console back up and replace.
function Clear-WayFor {
    param([string]$Path)
    if ($Interactive) {
        Write-Host "  $Path exists and is not a playbook link."
        if (-not (Confirm-Step "Back it up to ${Path}.bak and replace it with the playbook's?" $true)) {
            Write-Host "  SKIPPED: $Path (kept as is)"
            return $false
        }
    }
    return ((Backup-Path $Path) -eq 0)
}

# Clear-LinkWay: before a link is made at Link. 'free' when the path is free (an outdated link into
# this repo removed, anything else backed up), 'skip' to skip it, 'ok' when the right link is there.
function Clear-LinkWay {
    param([string]$Link, [string]$Target)
    $item = Get-Item -LiteralPath $Link -Force -ErrorAction SilentlyContinue
    if (-not $item) { return 'free' }
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        $currentTarget = $item.Target
        if (Test-SameTarget ([string]($currentTarget | Select-Object -First 1)) $Target) {
            Write-Host "  OK: $Link -> $Target"
            return 'ok'
        }
        if (Test-EngineLink $Link) {
            Write-Host "  UPDATE: $Link (was -> $currentTarget)"
            if ($item.PSIsContainer) { Remove-DirLink $Link } else { Invoke-Act "remove $Link" { Remove-Item -LiteralPath $Link -Force } }
            return 'free'
        }
    }
    if (Clear-WayFor $Link) { return 'free' }
    return 'skip'
}

function Link-File {
    param(
        [string]$Target,  # source file in repo
        [string]$Link     # symlink to create
    )
    if ((Clear-LinkWay $Link $Target) -ne 'free') { return }

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
    if ((Clear-LinkWay $Link $Target) -ne 'free') { return }

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
            Write-Host "  KEPT: $dest is your own folder; the playbook's $($skill.Name) skill is not linked there (rename or remove it, then re-run setup, to get the playbook's)"
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

# --- Co-existence with your own instruction file ------------------------------
# A regular file of yours at a client's global instruction path stays where it is, and the playbook
# loads beside it. The rules and each client's mechanism are documented once, in setup.sh's
# "Co-existence" section: Claude Code reads every ~\.claude\rules\*.md (measured, Claude Code 2.1.322,
# 2026-11-12); Gemini CLI reads every name in context.fileName from ~\.gemini\ (source-read, not
# runtime-verified: Gemini CLI 0.28.2 config.js:312, memoryDiscovery.js:93-100); Codex has none, so
# your file gets the single .bak.
$ClaudeSideLink = Join-Path $env:USERPROFILE ".claude\rules\agent-playbook.md"
$GeminiSideName = "AGENT-PLAYBOOK.md"
$GeminiSideLink = Join-Path $env:USERPROFILE ".gemini\$GeminiSideName"
$GeminiSettings = Join-Path $env:USERPROFILE ".gemini\settings.json"
$PlaybookPython = Join-Path $ScriptDir '.venv-agent-playbook\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $PlaybookPython)) { $PlaybookPython = Join-Path $ScriptDir '.venv-agent-playbook/bin/python' }

# Test-UserInstructionFile: Dest is a regular file of your own: not a link, not a file the deploy lock
# names, and not a byte copy of Source (a copy left where a link could not be made).
function Test-UserInstructionFile {
    param([string]$Dest, [string]$Source)
    if (-not (Test-RegularFile $Dest)) { return $false }
    $key = ConvertTo-LockKey $Dest
    foreach ($c in $LockOld) { if ($c[1] -ceq $key -and $c[0] -ne 'backup' -and $c[0] -ne 'setting') { return $false } }
    return ((Get-FileSha $Dest) -ne (Get-FileSha $Source))
}

# Remove-SideLink: remove a co-existence link into this repo (the instruction file is the link now).
function Remove-SideLink {
    param([string]$Path)
    if (Test-EngineLink $Path) {
        Write-Host "  REMOVE: $Path (the playbook loads through the instruction file itself now)"
        Invoke-Act "remove $Path" { Remove-Item -LiteralPath $Path -Force }
    }
}

# Invoke-GeminiContext: providers\gemini\context-filename.py on ~\.gemini\settings.json; its one line,
# or "unreadable <why>" when it cannot run. The prior value travels in the environment (the helper's
# docstring says why).
function Invoke-GeminiContext {
    param([string]$Action, [string]$Prior = '')
    if (-not (Test-Path -LiteralPath $PlaybookPython)) { return 'unreadable there is no playbook venv to edit it with' }
    $helperArgs = @($Action, '--settings', $GeminiSettings, '--name', $GeminiSideName)
    if ($DryRun) { $helperArgs += '--dry-run' }
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $env:CONTEXT_FILENAME_PRIOR = $Prior
    try {
        $out = @(& $PlaybookPython -I (Join-Path $ScriptDir 'providers\gemini\context-filename.py') @helperArgs 2>&1)
    } catch {
        $out = @("unreadable $($_.Exception.Message)")
    } finally {
        $ErrorActionPreference = $prevEap
        Remove-Item Env:\CONTEXT_FILENAME_PRIOR -ErrorAction SilentlyContinue
    }
    if ($out.Count -eq 0) { return 'unreadable the helper printed nothing' }
    return ([string]$out[0]).TrimEnd("`r")
}

# Remove-GeminiContextEntry: take the name setup added out of context.fileName again; the lock row stays
# when that cannot be done.
function Remove-GeminiContextEntry {
    param([string]$Prior)
    $res = Invoke-GeminiContext 'remove' $Prior
    if ($res -eq 'removed') {
        Write-Host "  REMOVED: $GeminiSideName from context.fileName in $GeminiSettings"
    } elseif ($res -ne 'absent') {
        Write-Host "  NOTE: $GeminiSettings cannot be edited ($($res -replace '^unreadable ', '')); remove $GeminiSideName from its context.fileName by hand"
        Add-LockRow 'setting' $LockGeminiKey $Prior
    }
}

function Deploy-ClaudeInstructions {
    param([string]$Source, [string]$Dest)
    if (Test-UserInstructionFile $Dest $Source) {
        Write-Host "  KEPT: $Dest is your own file; the playbook loads beside it from $ClaudeSideLink (Claude Code reads every ~/.claude/rules/*.md)"
        New-DirIfMissing (Split-Path -Parent $ClaudeSideLink)
        Link-File -Target $Source -Link $ClaudeSideLink
    } else {
        Link-File -Target $Source -Link $Dest
        Remove-SideLink $ClaudeSideLink
    }
}

function Deploy-GeminiInstructions {
    param([string]$Source, [string]$Dest)
    $old = Get-LockValue 'setting' $LockGeminiKey
    if (Test-UserInstructionFile $Dest $Source) {
        $res = Invoke-GeminiContext 'add'
        if ($res -eq 'present') {
            if ($old) { Add-LockRow 'setting' $LockGeminiKey $old }
        } elseif ($res.StartsWith('added ')) {
            Add-LockRow 'setting' $LockGeminiKey $res.Substring(6)
            if ($DryRun) { Write-Host "    DRY: add $GeminiSideName to context.fileName of $GeminiSettings" }
            else { Write-Host "  SET: $GeminiSideName in context.fileName of $GeminiSettings" }
        } else {
            Write-Host "  NOTE: $GeminiSettings cannot be edited ($($res -replace '^unreadable ', '')), so your $Dest cannot stay beside the playbook's: it is backed up and replaced"
            if ($old) { Add-LockRow 'setting' $LockGeminiKey $old }
            Link-File -Target $Source -Link $Dest
            return
        }
        Write-Host "  KEPT: $Dest is your own file; the playbook loads beside it from $GeminiSideLink (listed in context.fileName)"
        Link-File -Target $Source -Link $GeminiSideLink
        return
    }
    Link-File -Target $Source -Link $Dest
    Remove-SideLink $GeminiSideLink
    if ($old) { Remove-GeminiContextEntry $old }
}

function Deploy-CodexInstructions {
    param([string]$Source, [string]$Dest)
    $mine = Test-UserInstructionFile $Dest $Source
    Link-File -Target $Source -Link $Dest
    if ($mine -and ($DryRun -or (Test-EngineLink $Dest))) {
        Write-Host "  NOTE: Codex has no way to load a second global instructions file, so yours cannot stay beside the playbook's: it is kept as ${Dest}.bak"
    }
}

# Deploy-InstructionFile: $false when the row is no client's instruction file.
function Deploy-InstructionFile {
    param([string]$ManifestDest, [string]$Source, [string]$Dest)
    switch -CaseSensitive ($ManifestDest) {
        '~/.claude/CLAUDE.md' { $null = Deploy-ClaudeInstructions $Source $Dest; return $true }
        '~/.gemini/GEMINI.md' { $null = Deploy-GeminiInstructions $Source $Dest; return $true }
        '~/.codex/AGENTS.md' { $null = Deploy-CodexInstructions $Source $Dest; return $true }
    }
    return $false
}

# Test-MemorySourceMissing: a row whose source lies in the gitignored memory\ (user memory, behind the
# repo's memory link to the store repo) and is not there yet. No dangling link is made: setup says so,
# and a later run links it once the store repo holds user memory.
function Test-MemorySourceMissing {
    param([string]$ManifestSource, [string]$Source, [string]$Dest)
    if (-not $ManifestSource.StartsWith('memory/')) { return $false }
    if (Test-Path -LiteralPath $Source) { return $false }
    Write-Host "  NOTE: $Dest is not linked yet: there is no $Source (no user memory in the store repo yet)"
    return $true
}

# --- Owned files ---
# Write-OwnedFile: a copy-file or template-file row (kiro-always) under the ownership rule. A link
# at Dest is removed when it points into this repo (the layout before copies), else backed up.
function Write-OwnedFile {
    param(
        [string]$Kind,     # copy-file | template-file
        [string]$Dest,
        [byte[]]$Bytes     # what setup writes
    )
    $key = ConvertTo-LockKey $Dest
    $item = Get-Item -LiteralPath $Dest -Force -ErrorAction SilentlyContinue
    if ($item -and ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        if (Test-EngineLink $Dest) {
            Write-Host "  REMOVE SYMLINK: $Dest"
            Invoke-Act "remove $Dest" { Remove-Item -LiteralPath $Dest -Force }
        } elseif ((Backup-Path $Dest) -ne 0) {
            return
        }
    } elseif ($item -and $item.PSIsContainer) {
        if ((Backup-Path $Dest) -ne 0) { return }
    }
    $want = Get-BytesSha $Bytes
    $cur = if (Test-RegularFile $Dest) { Get-FileSha $Dest } else { '-' }
    $locked = Get-LockValue $Kind $key
    if (-not $locked) { $locked = '-' }
    switch (Get-OwnAction $want $cur $locked) {
        'keep' { Write-Host "  OK: $Dest (matches source)" }
        'backup' {
            if ((Backup-Path $Dest) -ne 0) { return }
            Invoke-Act "write $Dest" { [IO.File]::WriteAllBytes($Dest, $Bytes) }
            Write-Host "  WROTE: $Dest (yours kept as ${Dest}.bak)"
        }
        default {
            Invoke-Act "write $Dest" { [IO.File]::WriteAllBytes($Dest, $Bytes) }
            Write-Host "  WROTE: $Dest"
        }
    }
    Add-LockRow $Kind $key $want
}

# Get-FilesNoFollow: the regular files under Root, recursively, never entering a link or a
# __pycache__ folder (setup.sh: find -name __pycache__ -prune -o -type f). Paths are built from
# Root as given: FullName would expand a short (8.3) name and stop matching the lock's keys.
function Get-FilesNoFollow {
    param([string]$Root)
    $out = New-Object 'System.Collections.Generic.List[string]'
    $stack = New-Object 'System.Collections.Generic.Stack[string]'
    $stack.Push($Root)
    while ($stack.Count) {
        $d = $stack.Pop()
        foreach ($e in (New-Object IO.DirectoryInfo $d).GetFileSystemInfos()) {
            if ($e.Attributes -band [IO.FileAttributes]::ReparsePoint) { continue }
            $full = [IO.Path]::Combine($d, $e.Name)
            if ($e.Attributes -band [IO.FileAttributes]::Directory) {
                if ($e.Name -ne '__pycache__') { $stack.Push($full) }
            } else {
                $out.Add($full)
            }
        }
    }
    return , $out.ToArray()
}

# Invoke-LockRetire: rows of the previous lock under Prefix that this run did not record (their
# source is gone). A row for a current manifest destination, or for a path this run had to leave
# alone, is never retired, and a key that differs from a recorded one only in letter case is the same
# file. Each file is removed when unchanged since setup wrote it, else backed up; then the empty
# folders above it are removed, up to the Kiro skills folder.
function Invoke-LockRetire {
    param([string]$Prefix)
    $recorded = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
    foreach ($line in $LockNew) {
        $c = $line.Split("`t")
        if ($c[0] -ne 'backup' -and $c[0] -ne 'setting') { [void]$recorded.Add($c[1]) }
    }
    foreach ($k in $LockHeld) { [void]$recorded.Add($k) }
    foreach ($entry in $ManifestEntries) { $k = ConvertTo-LockKey (Expand-Dest $entry.dest); if ($k) { [void]$recorded.Add($k) } }
    $done = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::Ordinal)
    $todo = New-Object 'System.Collections.Generic.List[object]'
    foreach ($c in $LockOld) {
        if ($c[0] -eq 'backup' -or $c[0] -eq 'setting' -or -not $c[1].StartsWith($Prefix, [StringComparison]::Ordinal)) { continue }
        if ($recorded.Contains($c[1]) -or -not $done.Add($c[1])) { continue }
        $p = ConvertFrom-LockKey $c[1]
        if ((Test-RegularFile $p) -and (Test-NoLinkParent $p $env:USERPROFILE)) { $todo.Add(@($p, $c[2])) }
    }
    if (-not $todo.Count) { return }
    $hashes = Get-ShaMap ($todo | ForEach-Object { $_[0] })
    $touched = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
    foreach ($t in $todo) {
        $p = $t[0]
        if ($hashes[$p] -eq $t[1]) {
            Invoke-Act "remove $p" { [IO.File]::Delete($p) }
            Write-Host "  REMOVED: $p (its source is gone)"
        } else {
            Write-Host "  NOTE: $p changed since setup wrote it and its source is gone"
            [void](Backup-Path $p)
        }
        $sd = Get-SkillDirOf $p
        if ($sd) { [void]$touched.Add($sd) }
    }
    foreach ($sd in $touched) { Remove-EmptyDirs $sd }
}

# Deploy-GeneratedCopy: an overlay-bearing skill as a generated copy (setup.sh
# deploy_generated_copy). Every expected file's bytes are known first (the shared file, or the
# merge); then only the files that differ are written, each under the ownership rule. Files of the
# copy whose source is gone are left to Invoke-LockRetire. A folder at Dest that the lock names no
# file of is setup's (an older copy: an edited file goes to .bak) when every file in it sits at a
# path setup writes for the skill; any other such folder is yours: it is KEPT. Names match whatever
# the letter case. Returns $false when nothing was deployed.
function Deploy-GeneratedCopy {
    param([string]$SourceDir, [string]$Dest, [string]$OverlayDir, [string]$Name)
    $prefix = "~/.kiro/skills/$Name/"
    $exp = Get-GeneratedExpected $SourceDir $OverlayDir $Name
    Deploy-GeneratedCopyTo $Dest $Name $prefix $exp
}

# Get-GeneratedExpected: the files a generated copy holds: rel -> @{Kind; Src or Bytes; Hash}.
function Get-GeneratedExpected {
    param([string]$SourceDir, [string]$OverlayDir, [string]$Name)
    # 1. the expected files: rel -> @{kind; src or bytes; hash}
    $exp = [ordered]@{}
    foreach ($f in (Get-FilesNoFollow $SourceDir)) {
        $exp[$f.Substring($SourceDir.Length + 1).Replace('\', '/')] = @{ Kind = 'copy-dir-recursive'; Src = $f; Bytes = $null; Hash = '' }
    }
    $skillOverlay = Join-Path $OverlayDir "OVERLAY.md"
    if (Test-Path -LiteralPath $skillOverlay) {
        if (([IO.File]::ReadAllText($skillOverlay)).Trim().Length -eq 0) { Write-Host "  SKIPPED EMPTY OVERLAY: $Name" }
        $b = $Utf8NoBom.GetBytes((Merge-Overlay -SharedFile (Join-Path $SourceDir "SKILL.md") -OverlayFile $skillOverlay))
        $exp['SKILL.md'] = @{ Kind = 'merge-file'; Src = $null; Bytes = $b; Hash = (Get-BytesSha $b) }
    }
    foreach ($t in (Get-AuxOverlayTargets -OverlayDir $OverlayDir -SourceDir $SourceDir)) {
        $b = $Utf8NoBom.GetBytes((Merge-Overlay -SharedFile (Join-Path $SourceDir $t.Target) -OverlayFile $t.Overlay))
        $exp[$t.Target] = @{ Kind = 'merge-file'; Src = $null; Bytes = $b; Hash = (Get-BytesSha $b) }
    }
    $srcHashes = Get-ShaMap @($exp.Values | Where-Object { $_.Src } | ForEach-Object { $_.Src })
    foreach ($e in $exp.Values) { if ($e.Src) { $e.Hash = $srcHashes[$e.Src] } }
    return $exp
}

function Deploy-GeneratedCopyTo {
    param([string]$Dest, [string]$Name, [string]$Prefix, $exp)
    $prefix = $Prefix
    # 2. what is there now
    $cur = @{}
    $item = Get-Item -LiteralPath $Dest -Force -ErrorAction SilentlyContinue
    if ($item -and ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        if (Test-EngineLink $Dest) {
            Write-Host "  REMOVE SYMLINK: $Dest (now a generated copy)"
            Remove-DirLink $Dest
        } elseif (-not (Clear-WayFor $Dest)) { return $false }
    } elseif ($item -and -not $item.PSIsContainer) {
        if (-not (Clear-WayFor $Dest)) { return $false }
    } elseif ($item) {
        $curHashes = Get-ShaMap (Get-FilesNoFollow $Dest)
        foreach ($k in $curHashes.Keys) { $cur[$k.Substring($Dest.Length + 1).Replace('\', '/')] = $curHashes[$k] }
    }
    $locked = @{}
    foreach ($c in $LockOld) {
        if (($c[0] -eq 'copy-dir-recursive' -or $c[0] -eq 'merge-file') -and $c[1].StartsWith($prefix, [StringComparison]::Ordinal)) {
            $locked[$c[1].Substring($prefix.Length)] = $c[2]
        }
    }
    # 3. the decision per expected file
    $plan = New-Object 'System.Collections.Generic.List[object]'
    foreach ($rel in $exp.Keys) {
        $e = $exp[$rel]
        $c = if ($cur.ContainsKey($rel)) { $cur[$rel] } else { '-' }
        $l = if ($locked.ContainsKey($rel)) { $locked[$rel] } else { '-' }
        $plan.Add(@((Get-OwnAction $e.Hash $c $l), $rel))
    }
    $foreign = @($cur.Keys | Where-Object { -not $exp.Contains($_) }).Count
    if ($cur.Count -gt 0 -and $locked.Count -eq 0 -and $foreign -gt 0) {
        Write-Host "  KEPT: $Dest is your own folder; the playbook's $Name skill is not deployed there (rename or remove it, then re-run setup, to get the playbook's)"
        return $false
    }
    New-DirIfMissing $Dest
    # 4. write only the differences
    $nWrite = 0; $nBackup = 0; $nKeep = 0
    foreach ($step in $plan) {
        $action = $step[0]; $rel = $step[1]; $e = $exp[$rel]
        $full = Join-Path $Dest ($rel.Replace('/', '\'))
        if ($action -ne 'keep') {
            if (-not (Test-NoLinkParent $full $Dest)) { Write-Host "  SKIPPED: $full (a folder above it is a link)"; continue }
            if ($action -eq 'backup' -or ($action -eq 'write' -and $null -ne (Get-PathAttributes $full))) {
                if ((Backup-Path $full) -ne 0) { continue }
                $nBackup++
            }
            $parent = Split-Path -Parent $full
            Invoke-Act "write $full" {
                if (-not (Test-Path -LiteralPath $parent)) { [void][IO.Directory]::CreateDirectory($parent) }
                if ($e.Src) { [IO.File]::Copy($e.Src, $full, $true) } else { [IO.File]::WriteAllBytes($full, $e.Bytes) }
            }
            $nWrite++
        } else {
            $nKeep++
        }
        Add-LockRow $e.Kind ($prefix + $rel) $e.Hash
    }
    if ($nWrite -eq 0) { Write-Host "  OK: $Dest (generated copy, $nKeep files)" }
    else { Write-Host "  UPDATED: $Dest (generated copy: $nWrite written, $nBackup backed up, $nKeep unchanged)" }
    return $true
}

# Free-RealSkillDir: a real folder at a Kiro skill name where a link goes (a generated copy left by
# an older overlay, or a folder of yours). It decides first (setup.sh free_real_skill_dir): when every
# entry in it is a file setup wrote and left unchanged, those are removed (Invoke-LockRetire) and
# $true lets the link be made. Otherwise nothing there is touched and $false keeps the folder: a
# folder of yours is reported KEPT, and one that also holds setup's files keeps them and their lock
# rows, with a WARN that the skill is no longer updated there.
function Free-RealSkillDir {
    param([string]$Name)
    $dest = Join-Path (Join-Path $env:USERPROFILE ".kiro\skills") $Name
    $prefix = "~/.kiro/skills/$Name/"
    $rows = New-Object 'System.Collections.Generic.List[string[]]'
    foreach ($c in $LockOld) {
        if (($c[0] -eq 'copy-dir-recursive' -or $c[0] -eq 'merge-file') -and $c[1].StartsWith($prefix, [StringComparison]::Ordinal)) { $rows.Add($c) }
    }
    $want = @{}
    foreach ($c in $rows) { $want[(ConvertFrom-LockKey $c[1])] = $c[2] }
    # every entry that is not a folder, links included (setup.sh: find ! -type d)
    $all = New-Object 'System.Collections.Generic.List[string]'
    $stack = New-Object 'System.Collections.Generic.Stack[string]'
    $stack.Push($dest)
    while ($stack.Count) {
        $d = $stack.Pop()
        foreach ($e in (New-Object IO.DirectoryInfo $d).GetFileSystemInfos()) {
            $full = [IO.Path]::Combine($d, $e.Name)
            if (($e.Attributes -band [IO.FileAttributes]::Directory) -and -not ($e.Attributes -band [IO.FileAttributes]::ReparsePoint)) { $stack.Push($full) }
            else { $all.Add($full) }
        }
    }
    # files the lock names (edited or not), and every entry that is not such a file left unchanged
    $nLocked = 0; $nOther = 0
    foreach ($f in $all) {
        $named = $want.ContainsKey($f) -and (Test-RegularFile $f)
        if ($named) { $nLocked++ }
        if (-not ($named -and (Get-FileSha $f) -eq $want[$f])) { $nOther++ }
    }
    if ($nOther -eq 0) {
        Invoke-LockRetire $prefix
        if ($DryRun) { return $false }
        Remove-EmptyDirs $dest
        if (-not (Test-Path -LiteralPath $dest)) { return $true }
    }
    if ($nLocked -gt 0) {
        Write-Host "  WARN: $dest holds files of yours beside files setup wrote; the playbook's $Name skill is no longer updated there (move your files out of it, then re-run setup)"
        foreach ($c in $rows) { $LockNew.Add($c -join "`t") }
    } else {
        Write-Host "  KEPT: $dest is your own folder; the playbook's $Name skill is not linked there (rename or remove it, then re-run setup, to get the playbook's)"
    }
    return $false
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
# Tokens expand to the platform-native root with forward slashes (Windows:
# C:/Users/X; POSIX: /home/x, unchanged); {{PLAYBOOK_ROOT}} in its long form (no 8.3 names), as
# setup.sh renders it under Git Bash, so the two twins write the same bytes. Templates use forward slashes for
# everything AFTER the token too, so Windows renders the mixed separator form
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
    $body = $body.Replace('{{PLAYBOOK_ROOT}}', $EngineRootLong.Replace('\', '/'))
    return $body + "`n"
}

function Copy-Template {
    param(
        [string]$Source,  # template file in repo
        [string]$Dest     # destination to render to
    )

    Write-OwnedFile -Kind 'template-file' -Dest $Dest -Bytes $Utf8NoBom.GetBytes((Render-Template $Source))
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

# Merged content is written as UTF-8 WITHOUT a BOM ($Utf8NoBom), with no trailing newline added.
# Windows PowerShell 5.1's Set-Content default encoding is NOT UTF-8 and corrupts multibyte
# characters (e.g. em-dashes) in merged skill content; bash writes plain UTF-8, so the explicit
# no-BOM UTF-8 bytes keep the two scripts byte-identical.

# Merge a shared file body with a kiro overlay body using the canonical shape:
#   non-empty overlay -> shared (trailing newlines stripped) + "`n`n" + overlay (trailing
#                        newlines stripped) + single trailing "`n"
#   empty overlay     -> shared (trailing newlines stripped) + single trailing "`n"
# Returns the merged string (Deploy-GeneratedCopy writes its no-BOM UTF-8 bytes, no extra newline). Mirrors
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

# Get-AuxOverlayTargets: @{Target; Overlay} for every providers\kiro\skills\<name>\<stem>.OVERLAY.md
# (except the reserved SKILL.OVERLAY.md), whose overlay is appended to the deployed markdown target
# <stem>.md. Naming convention matches the consumers (e.g. memory-rules.OVERLAY.md -> memory-rules.md,
# RESEARCH_CONFIG_TEMPLATE.OVERLAY.md -> RESEARCH_CONFIG_TEMPLATE.md). SKILL.md keeps the bare
# OVERLAY.md convention (handled by the caller), so SKILL.OVERLAY.md is rejected to prevent two
# paths to the same target. Target-missing overlays are skipped with a warning (an overlay never
# creates a file on its own).
function Get-AuxOverlayTargets {
    param(
        [string]$OverlayDir,  # providers\kiro\skills\<name>
        [string]$SourceDir    # shared\skills\<name>
    )
    $out = @()
    if (-not (Test-Path $OverlayDir)) { return , $out }
    foreach ($ov in (Get-ChildItem $OverlayDir -File -Filter "*.OVERLAY.md")) {
        if ($ov.Name -eq "OVERLAY.md") { continue }  # SKILL.md overlay, handled separately
        if ($ov.Name -eq "SKILL.OVERLAY.md") {
            Write-Warning "  SKIPPED RESERVED: $($ov.FullName) (SKILL.md uses bare OVERLAY.md; SKILL.OVERLAY.md is forbidden)"
            continue
        }
        $targetName = ($ov.Name -replace '\.OVERLAY\.md$', '') + ".md"
        if (-not (Test-Path (Join-Path $SourceDir $targetName))) {
            Write-Warning "  SKIPPED AUX OVERLAY: $($ov.FullName) (no shared target '$targetName')"
            continue
        }
        $out += [PSCustomObject]@{ Target = $targetName; Overlay = $ov.FullName }
    }
    return , $out
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

# Restore-Backup: put <path>.bak back when the deploy lock shows setup made that backup and, for a
# file, that it is unchanged since; a .bak setup did not make is never touched.
function Restore-Backup {
    param([string]$Path)
    $val = Get-LockValue 'backup' (ConvertTo-LockKey $Path)
    if (-not $val) { return }
    $bak = "$Path.bak"
    if (-not (Test-NoLinkParent $Path $env:USERPROFILE)) {
        Write-Host "  WARN: $bak is not restored: a folder above it is a link (restore it by hand if you need it)"
        return
    }
    if (-not (Get-Item -LiteralPath $bak -Force -ErrorAction SilentlyContinue)) { return }
    if (Get-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue) { Write-Host "  KEPT: $bak ($Path is still there)"; return }
    if ($val -ne '-' -and (-not (Test-RegularFile $bak) -or (Get-FileSha $bak) -ne $val)) {
        Write-Host "  KEPT: $bak (changed since setup made it)"
        return
    }
    Invoke-Act "restore $Path" {
        $item = Get-Item -LiteralPath $bak -Force
        if ($item.PSIsContainer) { [IO.Directory]::Move($bak, $Path) } else { [IO.File]::Move($bak, $Path) }
    }
    Write-Host "  RESTORED: $Path (from $bak)"
}

# Remove a link into this repo, then restore <path>.bak if setup made one.
function Remove-EngineLink {
    param([string]$Path)
    if (-not (Test-EngineLink $Path)) { return }
    $item = Get-Item -LiteralPath $Path -Force
    if ($item.PSIsContainer) { Remove-DirLink $Path } else { Invoke-Act "remove $Path" { Remove-Item -LiteralPath $Path -Force } }
    Write-Host "  REMOVED: $Path"
    Restore-Backup $Path
}

function Remove-SkillLinks {
    param([string]$Dir)
    if (-not (Test-Path $Dir)) { return }
    # Join-Path, not FullName: FullName expands a short (8.3) name, and Restore-Backup keys by the path given.
    Get-ChildItem $Dir -Force -ErrorAction SilentlyContinue | ForEach-Object { Remove-EngineLink (Join-Path $Dir $_.Name) }
}

# Uninstall-OwnedFile: a copy-file or template-file row. Removed when it is the file setup wrote,
# unchanged (by the lock; with no lock row, when it equals the source or the render); else kept.
function Uninstall-OwnedFile {
    param([string]$Kind, [string]$Dest, [string]$Source)
    if (Test-RegularFile $Dest) {
        $locked = Get-LockValue $Kind (ConvertTo-LockKey $Dest)
        if ($locked) { $same = ((Get-FileSha $Dest) -eq $locked) }
        elseif ($Kind -eq 'template-file') { $same = ((Get-FileSha $Dest) -eq (Get-BytesSha $Utf8NoBom.GetBytes((Render-Template $Source)))) }
        else { $same = ((Get-FileSha $Dest) -eq (Get-FileSha $Source)) }
        if ($same) { Invoke-Act "remove $Dest" { Remove-Item -LiteralPath $Dest -Force }; Write-Host "  REMOVED: $Dest" }
        else { Write-Host "  KEPT: $Dest (changed since setup wrote it)" }
    }
    Restore-Backup $Dest
}

function Uninstall-Mode {
    param([string]$Mode)
    foreach ($entry in ($ManifestEntries | Where-Object { $_.mode -eq $Mode })) {
        $dest = Expand-Dest $entry.dest
        $source = Expand-Source $entry.source
        switch ($entry.kind) {
            { $_ -in 'symlink-file', 'symlink-dir' } { Remove-EngineLink $dest }
            { $_ -in 'template-file', 'copy-file' } { Uninstall-OwnedFile $entry.kind $dest $source }
            'seed-file' { if (Test-Path $dest) { Write-Host "  KEPT: $dest (the app owns it; setup only seeded it)" } }
        }
    }
}

# Uninstall-GeneratedCopies: the files of the generated Kiro copies the lock names. Each is removed
# when unchanged since setup wrote it, else kept; then the empty folders go and the backups setup
# made there are restored. With no readable lock, a file of a generated copy is removed only when it
# equals what setup would write there now.
function Uninstall-GeneratedCopies {
    $skillsRoot = Join-Path $env:USERPROFILE ".kiro\skills"
    $todo = New-Object 'System.Collections.Generic.List[object]'; $names = @()
    $want = New-Object 'System.Collections.Generic.List[object]'
    foreach ($c in $LockOld) {
        if (($c[0] -ne 'copy-dir-recursive' -and $c[0] -ne 'merge-file') -or -not $c[1].StartsWith('~/.kiro/skills/', [StringComparison]::Ordinal)) { continue }
        $want.Add(@($c[1], $c[2]))
    }
    if (-not $script:LockReadable) {
        # rows built from what setup writes now: the hash a file must still have to be removed
        $overlayRoot = Join-Path $ScriptDir "providers\kiro\skills"
        foreach ($skill in (Get-ChildItem (Join-Path $SharedDir "skills") -Directory)) {
            $ov = Join-Path $overlayRoot $skill.Name
            if (-not (Test-Path (Join-Path $skill.FullName "SKILL.md")) -or -not (Test-HasAnyOverlay $ov)) { continue }
            $exp = Get-GeneratedExpected $skill.FullName $ov $skill.Name
            foreach ($rel in $exp.Keys) { $want.Add(@("~/.kiro/skills/$($skill.Name)/$rel", $exp[$rel].Hash)) }
        }
    }
    foreach ($w in $want) {
        $n = $w[0].Split('/')[3]
        if ($names -notcontains $n) { $names += $n }
        $p = ConvertFrom-LockKey $w[0]
        if ((Test-RegularFile $p) -and (Test-NoLinkParent $p $env:USERPROFILE)) { $todo.Add(@($p, $w[1])) }
    }
    $existed = @($names | Sort-Object | Where-Object {
        $d = Join-Path $skillsRoot $_
        (Test-Path -LiteralPath $d -PathType Container) -and -not (Test-Reparse $d)
    })
    $hashes = Get-ShaMap ($todo | ForEach-Object { $_[0] })
    foreach ($t in $todo) {
        if ($hashes[$t[0]] -eq $t[1]) {
            Invoke-Act "remove $($t[0])" { [IO.File]::Delete($t[0]) }
        } else {
            Write-Host "  KEPT: $($t[0]) (changed since setup wrote it)"
        }
    }
    foreach ($n in $names) { Remove-EmptyDirs (Join-Path $skillsRoot $n) }
    foreach ($c in $LockOld) {
        if ($c[0] -eq 'backup' -and $c[1].StartsWith('~/.kiro/skills/', [StringComparison]::Ordinal)) { Restore-Backup (ConvertFrom-LockKey $c[1]) }
    }
    foreach ($n in $existed) {
        $d = Join-Path $skillsRoot $n
        if ((Test-Path -LiteralPath $d -PathType Container) -and -not (Test-Reparse $d)) {
            Write-Host "  KEPT: $d (holds files that are not setup's unchanged ones)"
        } else {
            Write-Host "  REMOVED: $d (generated copy)"
        }
    }
}

# Uninstall-KiroSetting: revert chat.defaultAgent only when the lock shows setup set it and it
# still names kiro_default. When the revert cannot be tried (no kiro-cli, AGENT_PLAYBOOK_SKIP_KIRO_CLI,
# a value that cannot be read, a failed command), the lock keeps the row for a later uninstall.
function Uninstall-KiroSetting {
    $val = Get-LockValue 'setting' $LockSettingKey
    if (-not (Get-Command kiro-cli -ErrorAction SilentlyContinue)) {
        if ($val) {
            Write-Host "  NOTE: no kiro-cli here, so chat.defaultAgent is not reverted; the deploy lock keeps it for a later uninstall"
            Add-LockRow 'setting' $LockSettingKey $val
        }
        return
    }
    if ($env:AGENT_PLAYBOOK_SKIP_KIRO_CLI -eq '1') {
        Write-Host "  SKIP: kiro-cli settings (AGENT_PLAYBOOK_SKIP_KIRO_CLI=1)"
        if ($val) { Add-LockRow 'setting' $LockSettingKey $val }
        return
    }
    if (-not $val) { Write-Host "  NOTE: setup did not set kiro-cli's chat.defaultAgent, so it is left as is"; return }
    $cur = Get-KiroDefaultAgent
    if (-not $cur) {
        Write-Host "  WARN: kiro-cli's chat.defaultAgent could not be read, so it is not reverted; the deploy lock keeps it for a later uninstall"
        Add-LockRow 'setting' $LockSettingKey $val
        return
    }
    if ($cur -ne '"kiro_default"') { Write-Host "  NOTE: kiro-cli's chat.defaultAgent changed since setup set it, so it is left as is"; return }
    if ($DryRun) { Write-Host "    DRY: revert kiro-cli chat.defaultAgent to $val"; return }
    $ok = $false
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        if ($val -eq '-') { & kiro-cli settings --global --delete chat.defaultAgent }
        else { & kiro-cli settings --global chat.defaultAgent ($val.Trim('"')) }
        $ok = ($LASTEXITCODE -eq 0)
    } catch { $ok = $false } finally { $ErrorActionPreference = $prev }
    if ($ok) { Write-Host "  RESTORED: kiro-cli chat.defaultAgent (to $val)" }
    else {
        Write-Host "  WARN: kiro-cli could not revert chat.defaultAgent; the deploy lock keeps it for a later uninstall"
        Add-LockRow 'setting' $LockSettingKey $val
    }
}

# Get-KiroDefaultAgent: kiro-cli's chat.defaultAgent as JSON on one line (its lines joined by a
# space, the ends trimmed; spaces inside a value are kept), or '' when the read fails or prints
# nothing (setup.sh kiro_default_agent).
function Get-KiroDefaultAgent {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $out = @(& kiro-cli settings -f json --global chat.defaultAgent 2>$null)
        if ($LASTEXITCODE -ne 0) { return '' }
        return (($out | ForEach-Object { ([string]$_).TrimEnd("`r") }) -join ' ').Trim()
    }
    catch { return '' }
    finally { $ErrorActionPreference = $prev }
}

Read-DeployLock

if ($Uninstall) {
    Write-Host "=== Uninstall: $($Chosen -join ', ') ==="
    if (Test-Wants 'claude') {
        Uninstall-Mode 'claude'; Remove-EngineLink $ClaudeSideLink; Remove-SkillLinks (Join-Path $env:USERPROFILE ".claude\skills")
        $uninstallPython = Join-Path $ScriptDir '.venv-agent-playbook\Scripts\python.exe'
        if (Test-Path -LiteralPath $uninstallPython) {
            Invoke-Act "remove the playbook's entries from ~\.claude\settings.json" {
                $removed = $false
                try {
                    & $uninstallPython -I (Join-Path $ScriptDir 'providers\claude\settings-entries.py') remove --home $env:USERPROFILE
                    $removed = ($LASTEXITCODE -eq 0)
                } catch { $removed = $false }
                if (-not $removed) { Write-Host "  NOTE: the venv did not run, so remove the playbook's entries from ~\.claude\settings.json by hand" }
            }
        } else {
            Write-Host "  NOTE: no venv, so remove the playbook's entries from ~\.claude\settings.json by hand"
        }
    }
    if (Test-Wants 'codex') { Uninstall-Mode 'codex'; Remove-SkillLinks (Join-Path $env:USERPROFILE ".codex\skills") }
    if (Test-Wants 'gemini') {
        Uninstall-Mode 'gemini'; Remove-EngineLink $GeminiSideLink; Remove-SkillLinks (Join-Path $env:USERPROFILE ".gemini\skills")
        # the name setup added to context.fileName (the lock's setting row); the rest of the file stays
        $oldGemini = Get-LockValue 'setting' $LockGeminiKey
        if ($oldGemini) { Remove-GeminiContextEntry $oldGemini }
    }
    if (Test-Wants 'kiro') {
        Uninstall-Mode 'kiro-always'
        Uninstall-Mode 'kiro'
        Uninstall-GeneratedCopies
        Remove-SkillLinks (Join-Path $env:USERPROFILE ".kiro\skills")
        Uninstall-KiroSetting
    }
    $keep = New-Object 'System.Collections.Generic.List[string]'
    foreach ($c in $LockOld) { if (-not (Test-Wants (Get-KeyProvider $c[1]))) { $keep.Add($c -join "`t") } }
    Complete-DeployLock -Carry $keep.ToArray() -DropEmpty
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
$text += "root=$(ConvertTo-PointerPath $EngineRootLong)`n"
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
        if (Test-MemorySourceMissing $entry.source $source $dest) { continue }
        New-DirIfMissing (Split-Path -Parent $dest)
        switch ($entry.kind) {
            'symlink-file' { if (-not (Deploy-InstructionFile $entry.dest $source $dest)) { Link-File -Target $source -Link $dest } }
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
                default         { Write-OwnedFile -Kind 'copy-file' -Dest $dest -Bytes ([IO.File]::ReadAllBytes($source)) }
            }
        }
    }

    # chat.defaultAgent: set only when it is not kiro_default already, and recorded in the lock
    # (kind setting, with the value it replaced) so that uninstall reverts only what setup set.
    $oldSetting = Get-LockValue 'setting' $LockSettingKey
    if ($env:AGENT_PLAYBOOK_SKIP_KIRO_CLI -eq '1') {
        Write-Host "  SKIP: kiro-cli settings (AGENT_PLAYBOOK_SKIP_KIRO_CLI=1)"
        if ($oldSetting) { Add-LockRow 'setting' $LockSettingKey $oldSetting }
    } elseif (Get-Command kiro-cli -ErrorAction SilentlyContinue) {
        $prevAgent = Get-KiroDefaultAgent
        if (-not $prevAgent) {
            # a value setup cannot read is never replaced: uninstall could not put it back
            Write-Host "  WARN: kiro-cli's chat.defaultAgent could not be read, so it is left as is"
            if ($oldSetting) { Add-LockRow 'setting' $LockSettingKey $oldSetting }
        } elseif ($prevAgent -eq '"kiro_default"') {
            Write-Host "  OK: chat.defaultAgent = kiro_default (global)"
            if ($oldSetting) { Add-LockRow 'setting' $LockSettingKey $oldSetting }
        } elseif ($DryRun) {
            Write-Host "    DRY: kiro-cli settings --global chat.defaultAgent kiro_default"
        } else {
            $setOk = $false
            try { & kiro-cli settings --global chat.defaultAgent kiro_default; $setOk = ($LASTEXITCODE -eq 0) } catch { $setOk = $false }
            if ($setOk) {
                Write-Host "  SET: chat.defaultAgent = kiro_default (global)"
                if ($prevAgent -eq 'null') { $prevAgent = '-' }
                Add-LockRow 'setting' $LockSettingKey $prevAgent
            } else {
                Write-Warning "  WARN: Failed to set chat.defaultAgent"
                if ($oldSetting) { Add-LockRow 'setting' $LockSettingKey $oldSetting }
            }
        }
    } elseif ($oldSetting) {
        Add-LockRow 'setting' $LockSettingKey $oldSetting
    }

    # --- Kiro IDE ---
    # Steering and plain skills are SYMLINKS into the repo, like every other
    # provider (Link-File/Link-Dir above). The former copy mode rested on "Kiro IDE
    # does not follow symlinks on Windows", which was re-measured 2026-08-17 and
    # does not reproduce; copies were retired 2026-09-20. Overlay-bearing skills
    # stay generated copies on every platform: the merge overwrites one file inside
    # the skill dir, which a symlinked dir forbids. A regular file at a linked
    # steering destination is backed up like any other (Link-File, Clear-WayFor).
    Write-Host "=== Kiro IDE ==="
    $KiroSteeringDir = Join-Path (Join-Path $env:USERPROFILE ".kiro") "steering"
    $KiroSkillsDir = Join-Path (Join-Path $env:USERPROFILE ".kiro") "skills"
    New-DirIfMissing $KiroSteeringDir
    New-DirIfMissing $KiroSkillsDir

    # Steering files from manifest (mode kiro). Steering is flat: every deployed
    # file sits directly in ~/.kiro/steering/.
    foreach ($entry in ($ManifestEntries | Where-Object { $_.mode -eq 'kiro' })) {
        $dest = Expand-Dest $entry.dest
        $source = Expand-Source $entry.source
        New-DirIfMissing (Split-Path -Parent $dest)
        Link-File -Target $source -Link $dest
    }

    # Build list of managed skill names for cleanup pass
    $ManagedSkills = @()

    # Shared skills (with overlay-merge support). Any overlay makes a generated copy (a
    # symlinked dir can't have a single file overwritten): Deploy-GeneratedCopy.
    Write-Host "  Shared skills:"
    $KiroOverlayRoot = Join-Path $ScriptDir "providers\kiro\skills"
    foreach ($skill in (Get-ChildItem (Join-Path $SharedDir "skills") -Directory)) {
        $name = $skill.Name
        if (-not (Test-Path (Join-Path $skill.FullName "SKILL.md"))) { continue }
        $overlayDir = Join-Path $KiroOverlayRoot $name
        $dest = Join-Path $KiroSkillsDir $name
        if (Test-HasAnyOverlay $overlayDir) {
            [void](Deploy-GeneratedCopy -SourceDir $skill.FullName -Dest $dest -OverlayDir $overlayDir -Name $name)
        } else {
            # a real folder here: a generated copy left by an older overlay, or yours
            $existing = Get-Item -LiteralPath $dest -Force -ErrorAction SilentlyContinue
            if ($existing -and $existing.PSIsContainer -and
                -not ($existing.Attributes -band [IO.FileAttributes]::ReparsePoint) -and -not (Free-RealSkillDir $name)) {
                continue
            }
            Link-Dir -Target $skill.FullName -Link $dest
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
                $dest = Join-Path $KiroSkillsDir $_.Name
                $existing = Get-Item -LiteralPath $dest -Force -ErrorAction SilentlyContinue
                if ($existing -and $existing.PSIsContainer -and
                    -not ($existing.Attributes -band [IO.FileAttributes]::ReparsePoint) -and -not (Free-RealSkillDir $_.Name)) {
                    return
                }
                Link-Dir -Target $_.FullName -Link $dest
                $script:ManagedSkills += $_.Name
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

    # Files setup wrote whose source is gone (a deleted skill, a retired copy-file row): the deploy
    # lock names them. Each is removed when unchanged since setup wrote it, else backed up.
    Write-Host "  Cleaning files whose source is gone:"
    Invoke-LockRetire "~/.kiro/"

    Write-Host ""
    Write-Host "=== Cleanup stale files ==="
    # Files: names a previous deployment wrote that the current manifest no longer
    # owns. NEVER list a path the manifest currently deploys (this runs after the
    # steering loop and would delete the fresh copy).
    # Frozen at these 7 entries: add no new ones. The deploy lock covers every later
    # retirement (Invoke-LockRetire above). Entries are dated.
    $StaleFiles = @(
        (Join-Path $KiroAgentsDir "kiro_default.json"),                 # 2026-08-18
        (Join-Path $KiroSteeringDir "claude-code-local-data.md"),       # 2026-09-20, and the rest
        (Join-Path $KiroSteeringDir "v2-only\kiro-cli-local-data.md"),
        (Join-Path $KiroSteeringDir "v2-only\memory-sources.md"),
        (Join-Path $KiroSteeringDir "v2-only\session-resume-recovery-2.14.0.md"),
        (Join-Path $KiroSteeringDir "v3\kiro-cli-local-data.md"),
        (Join-Path $KiroSteeringDir "v3\memory-sources.md")
    )
    # Each goes through the ownership rule: a link into this repo, or a file the lock names and
    # unchanged since, is removed; anything else is yours and goes to <path>.bak.
    foreach ($stale in $StaleFiles) {
        if ($null -eq (Get-PathAttributes $stale)) { continue }
        $lk = ''
        if (Test-RegularFile $stale) {
            $sk = ConvertTo-LockKey $stale
            foreach ($c in $LockOld) { if ($c[1] -ceq $sk -and $c[0] -ne 'backup' -and $c[0] -ne 'setting') { $lk = $c[2]; break } }
        }
        if ((Test-EngineLink $stale) -or ($lk -and (Get-FileSha $stale) -eq $lk)) {
            Invoke-Act "remove $stale" { Remove-Item -LiteralPath $stale -Force }
            Write-Host "  REMOVED stale: $stale"
        } else {
            Write-Host "  NOTE: $stale is a retired playbook name, but not a file setup wrote unchanged"
            [void](Backup-Path $stale)
        }
    }
    # Directories: the retired v2-only\ and v3\ steering subdirectories (kiro-cli v2
    # retirement, 2026-09-20). Removed only when empty, so a user-placed file survives.
    foreach ($staleDir in @((Join-Path $KiroSteeringDir "v2-only"), (Join-Path $KiroSteeringDir "v3"))) {
        if ((Test-Path -LiteralPath $staleDir -PathType Container) -and -not (Get-ChildItem -LiteralPath $staleDir -Force | Select-Object -First 1)) {
            Invoke-Act "remove $staleDir" { Remove-Item -LiteralPath $staleDir -Force }
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

Write-Host "=== Deploy lock ==="
Complete-DeployLock -Carry (Get-LockCarryRows)
$DeployFailed = $script:BackupFailed

Write-Host ""
Write-Host "Done (providers: $($Chosen -join ', ')). Run '/qconfig-sync' from any agent to verify."
if (Test-Wants 'claude') {
    # Only a person at a terminal may change settings.json: an agent-run setup never gets here.
    if ($DryRun) {
        Write-Host "    DRY: offer the Claude Code entries in ~/.claude/settings.json"
    } elseif ($Interactive -and (Test-Path -LiteralPath $VenvPython)) {
        & $VenvPython -I (Join-Path $ScriptDir 'providers\claude\settings-entries.py') offer --home $env:USERPROFILE
    } else {
        Write-Host "NOTE: ~/.claude/settings.json was not changed. '/qconfig-sync' reports which Claude Code"
        Write-Host "      entries are set, and providers/claude/README.md says how to add them."
    }
}
if ($DeployFailed -gt 0) {
    [Console]::Error.WriteLine("ERROR: $DeployFailed path(s) could not be backed up and were left unchanged (the ERROR lines above); close what holds them, then re-run setup")
    exit 1
}
