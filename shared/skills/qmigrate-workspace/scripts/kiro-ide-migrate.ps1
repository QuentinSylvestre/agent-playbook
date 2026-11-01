# kiro-ide-migrate.ps1 — Migrate Kiro IDE legacy workspace-sessions history between workspace paths (Windows)
# Called by cutover.ps1 step 6 once per legacy folder under the old path; store layout:
# providers/kiro/reference/kiro-ide-local-data.md. Run it with Windows PowerShell (`powershell`), as cutover.ps1 does.
#
# Interpreter: the config repo venv (<config-repo>\.venv-agent-playbook\Scripts\python.exe), found from this script's real
# location; a missing, too-old (< 3.11) or broken venv stops with a message, never a fallback to a Python on PATH.
#
# Usage: kiro-ide-migrate.ps1 -OldPath <old> -NewPath <new> [-DryRun] [-SkipExecutionData] [-KiroAppData <path>]
# Both paths with a lower-case drive letter, as Kiro IDE encodes them. -DryRun still creates the target
# folder with an empty sessions.json when it is missing. Removes the old workspace-sessions folder at the end:
# back it up first (cutover.ps1 does). Keeps the old execution-data directory.
#
# CRITICAL: This script never parses session JSON files through ConvertFrom-Json.
# PowerShell's default JSON depth (2) silently truncates nested data.
# All modifications use raw string replacement.

param(
    [Parameter(Mandatory)][string]$OldPath,
    [Parameter(Mandatory)][string]$NewPath,
    [switch]$DryRun,
    [switch]$SkipExecutionData,
    [string]$KiroAppData = "$env:APPDATA\Kiro\User\globalStorage\kiro.kiroagent"
)

$ErrorActionPreference = "Stop"

# ── Helpers ──

function ConvertTo-KiroFolderName([string]$path) {
    $b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($path))
    return $b64 -replace '/', '_' -replace '\+', '-' -replace '=', '_'
}

function Normalize-Path([string]$p) {
    $resolved = [System.IO.Path]::GetFullPath($p)
    # Kiro always uses lowercase drive letter
    if ($resolved.Length -ge 2 -and $resolved[1] -eq ':') {
        $resolved = $resolved.Substring(0,1).ToLower() + $resolved.Substring(1)
    }
    # Remove trailing backslash
    return $resolved.TrimEnd('\')
}

function Write-Step([string]$msg) {
    Write-Host $msg -ForegroundColor Green
}

function Write-Warn([string]$msg) {
    Write-Host "  WARNING: $msg" -ForegroundColor Yellow
}

function Write-Err([string]$msg) {
    Write-Host "  ERROR: $msg" -ForegroundColor Red
}

# ── Normalize paths ──

$OldPath = Normalize-Path $OldPath
$NewPath = Normalize-Path $NewPath

Write-Host ""
Write-Host "=== Kiro History Migration ===" -ForegroundColor Cyan
Write-Host "From: $OldPath"
Write-Host "  To: $NewPath"
if ($DryRun) { Write-Host "[DRY RUN]" -ForegroundColor Yellow }
Write-Host ""

# ── Pre-flight checks ──

Write-Step "[1/7] Pre-flight checks..."

$kiroProcs = Get-Process -Name "Kiro" -ErrorAction SilentlyContinue
if ($kiroProcs) {
    Write-Warn "Kiro is running. Ensure the source and target workspaces are NOT open in Kiro."
    Write-Warn "If they are, close those windows first. Other Kiro windows are safe."
}

# Interpreter: the playbook's one venv, <config-repo>\.venv-agent-playbook (setup.ps1 creates it), never a Python
# from PATH. The config repo is found from this script's real location (<repo>\shared\skills\qmigrate-workspace\scripts):
# every component of the path is followed, because the skill is usually reached through a symlinked skills folder.
function Resolve-RealPath([string]$Path) {
    for ($i = 0; $i -lt 16; $i++) {
        $full = [IO.Path]::GetFullPath($Path); $root = [IO.Path]::GetPathRoot($full)
        $parts = @($full.Substring($root.Length).Split([char[]]@([char]92, [char]47), [StringSplitOptions]::RemoveEmptyEntries))
        $cur = $root; $moved = $false
        for ($j = 0; $j -lt $parts.Count; $j++) {
            $next = Join-Path $cur $parts[$j]
            $item = Get-Item -LiteralPath $next -Force -ErrorAction SilentlyContinue
            if ($item -and (@('SymbolicLink', 'Junction') -contains [string]$item.LinkType)) {
                $target = ([string]@($item.Target)[0]) -replace '^\\\\\?\\', ''
                if (-not [IO.Path]::IsPathRooted($target)) { $target = Join-Path $cur $target }
                $Path = $target
                if ($j + 1 -lt $parts.Count) { foreach ($t in $parts[($j + 1)..($parts.Count - 1)]) { $Path = Join-Path $Path $t } }
                $moved = $true; break
            }
            $cur = $next
        }
        if (-not $moved) { return $full }
    }
    return $Path
}
$SkillRepo = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent (Split-Path -Parent (Resolve-RealPath $PSScriptRoot))))
$Python = Join-Path $SkillRepo '.venv-agent-playbook\Scripts\python.exe'
$dash = [string][char]0x2014
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    Write-Err "venv missing $dash run setup.ps1 (expected $Python)"
    exit 1
}
# The playbook venv must be Python 3.11+. Exit 1 means older; any other failure means the venv python cannot start.
# A file that is not a program makes the call throw instead of setting an exit code; treat that as "cannot start".
try { & $Python -I -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" } catch { $global:LASTEXITCODE = 255 }
if ($LASTEXITCODE -eq 1) {
    Write-Err "The venv Python is older than 3.11: delete $SkillRepo\.venv-agent-playbook and run setup.ps1 with a 3.11+ system Python."
    exit 1
}
if ($LASTEXITCODE) {
    Write-Err "The venv Python failed to start (exit $LASTEXITCODE) $dash run setup.ps1 (it rebuilds a broken venv)."
    exit 1
}

$sessionsBase = Join-Path $KiroAppData "workspace-sessions"
if (-not (Test-Path $sessionsBase)) {
    Write-Err "Kiro workspace-sessions directory not found at: $sessionsBase"
    exit 1
}

$oldFolderName = ConvertTo-KiroFolderName $OldPath
$newFolderName = ConvertTo-KiroFolderName $NewPath
$oldDir = Join-Path $sessionsBase $oldFolderName
$newDir = Join-Path $sessionsBase $newFolderName

Write-Host "  Old folder: $oldFolderName"
Write-Host "  New folder: $newFolderName"

if (-not (Test-Path $oldDir)) {
    Write-Err "Source session folder not found: $oldDir"
    Write-Err "No history to migrate for path: $OldPath"
    exit 1
}

if (-not (Test-Path $newDir)) {
    # Kiro IDE 1.0.x saves new chats as kiro-cli v3 sessions, so opening the new
    # workspace no longer creates this legacy folder. Create it the way Kiro used to --
    # also on a dry run, since every later step reads it and an empty one is inert.
    Write-Warn "Target session folder not found -- creating it with an empty sessions.json (also on dry run)."
    New-Item -ItemType Directory -Path $newDir | Out-Null
    [IO.File]::WriteAllText((Join-Path $newDir "sessions.json"), "[]")
}

$oldSessionCount = (Get-ChildItem $oldDir -Filter "*.json" | Where-Object { $_.Name -ne "sessions.json" }).Count
$newSessionCount = (Get-ChildItem $newDir -Filter "*.json" | Where-Object { $_.Name -ne "sessions.json" }).Count
Write-Host "  Source sessions: $oldSessionCount"
Write-Host "  Target sessions: $newSessionCount (existing)"

# ── Copy session files ──

Write-Step "[2/7] Copying session files..."

$sessionFiles = Get-ChildItem $oldDir -Filter "*.json" | Where-Object { $_.Name -ne "sessions.json" }
$copied = 0
$skipped = 0

foreach ($f in $sessionFiles) {
    $targetFile = Join-Path $newDir $f.Name
    if (Test-Path $targetFile) {
        $skipped++
    } else {
        if (-not $DryRun) {
            Copy-Item $f.FullName $targetFile
        }
        $copied++
    }
}
Write-Host "  Copied: $copied, Skipped (already exist): $skipped"

# ── Merge sessions.json ──

Write-Step "[3/7] Merging sessions.json..."

$oldSessionsJson = Join-Path $oldDir "sessions.json"
$newSessionsJson = Join-Path $newDir "sessions.json"

if (-not (Test-Path $oldSessionsJson)) {
    Write-Warn "No sessions.json in source folder. Skipping merge."
} elseif (-not $DryRun) {
    # Backup target sessions.json
    $backupPath = "$newSessionsJson.bak"
    Copy-Item $newSessionsJson $backupPath -Force
    Write-Host "  Backed up target sessions.json to sessions.json.bak"

    # Use Python for safe JSON merge (avoids PowerShell depth truncation)
    $pyMerge = @'
import json, sys
old_path, new_path = sys.argv[1], sys.argv[2]
with open(old_path, encoding='utf-8') as f:
    old = json.load(f)
with open(new_path, encoding='utf-8') as f:
    new = json.load(f)
seen = {s['sessionId'] for s in new}
merged = new + [s for s in old if s['sessionId'] not in seen]
with open(new_path, 'w', encoding='utf-8') as f:
    json.dump(merged, f, indent=2, ensure_ascii=False)
print(f"  Merged: {len(old)} old + {len(new)} existing = {len(merged)} total (deduped)")
'@
    $pyMerge | & $Python -I - $oldSessionsJson $newSessionsJson
    if ($LASTEXITCODE -ne 0) {
        Write-Err "Python merge failed. Restoring backup."
        Copy-Item $backupPath $newSessionsJson -Force
        exit 1
    }
} else {
    Write-Host "  [DRY RUN] Would merge sessions.json"
}

# ── Update workspaceDirectory/workspacePath in copied files ──

Write-Step "[4/7] Updating workspace paths in session files..."

# Build the JSON-escaped path strings (double backslashes for JSON)
# CRITICAL: use literal .Replace(), NOT -replace (regex). Regex escaping of
# backslash-heavy paths is unreliable and was the cause of a real bug.
$oldWsEscaped = $OldPath -replace '\\', '\\'
$newWsEscaped = $NewPath -replace '\\', '\\'

$updatedFiles = 0
$copiedFiles = Get-ChildItem $newDir -Filter "*.json"

# Explicit BOM-free UTF-8 on both sides. Under Windows PowerShell 5.1, `Get-Content -Raw` reads BOM-less
# UTF-8 as the ANSI code page and `Set-Content -Encoding UTF8` writes a BOM: on 2026-10-02 that corrupted
# every non-ASCII character in 41 of 59 migrated session files and BOM-prefixed 58 of them.
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
foreach ($f in $copiedFiles) {
    $content = [IO.File]::ReadAllText($f.FullName, $utf8NoBom)
    if ($content.Contains($oldWsEscaped)) {
        $updated = $content.Replace($oldWsEscaped, $newWsEscaped)
        if (-not $DryRun) {
            [IO.File]::WriteAllText($f.FullName, $updated, $utf8NoBom)
        }
        $updatedFiles++
    }
}
Write-Host "  Updated $updatedFiles files"

# ── Discover and copy execution data ──

if (-not $SkipExecutionData) {
    Write-Step "[5/7] Discovering execution data storage..."

    # Strategy: scan Kiro logs for "[storage] Initialized storage at" lines
    # Each log file corresponds to one Kiro window. Match the storage hash
    # to the workspace by checking if the SAME log file references the workspace path
    # in a non-conversation context (e.g. in the storage init line or workspace setup).
    $logDir = Join-Path (Split-Path $KiroAppData -Parent | Split-Path -Parent) "logs"
    $oldStorageHash = $null
    $newStorageHash = $null

    if (Test-Path $logDir) {
        $logDirs = Get-ChildItem $logDir -Directory | Sort-Object Name -Descending
        foreach ($ld in $logDirs) {
            $kiroLogs = Get-ChildItem $ld.FullName -Recurse -Filter "Kiro Logs.log" -ErrorAction SilentlyContinue
            foreach ($log in $kiroLogs) {
                $logContent = Get-Content $log.FullName -Raw -ErrorAction SilentlyContinue
                if (-not $logContent) { continue }

                # Extract storage hash
                if ($logContent -notmatch '\[storage\] Initialized storage at .+[/\\]([0-9a-f]{32})') { continue }
                $hash = $Matches[1]

                # Match workspace by checking for the base64url folder name in the log
                # (more reliable than path strings which appear in conversation content)
                if ($logContent.Contains($oldFolderName) -and -not $oldStorageHash) {
                    $oldStorageHash = $hash
                }
                if ($logContent.Contains($newFolderName) -and -not $newStorageHash) {
                    $newStorageHash = $hash
                }
            }
            if ($oldStorageHash -and $newStorageHash) { break }
        }
    }

    # Fallback: extract executionIds from session files, search index files
    if (-not $oldStorageHash -or -not $newStorageHash) {
        Write-Host "  Log-based discovery incomplete. Scanning hash directories..."
        $hashDirs = Get-ChildItem $KiroAppData -Directory | Where-Object { $_.Name -match '^[0-9a-f]{32}$' }

        # Extract executionIds from session files using Python
        $pyExtractExecIds = @'
import re, os, sys
exec_ids = set()
session_dir = sys.argv[1]
for fname in os.listdir(session_dir):
    if not fname.endswith('.json') or fname == 'sessions.json':
        continue
    with open(os.path.join(session_dir, fname), encoding='utf-8') as f:
        content = f.read()
    exec_ids.update(re.findall(r'"executionId"\s*:\s*"([^"]+)"', content))
for eid in sorted(exec_ids):
    print(eid)
'@

        if (-not $oldStorageHash) {
            $oldExecIds = ($pyExtractExecIds | & $Python -I - $oldDir) -split "`n" | ForEach-Object { $_.Trim() } | Where-Object { $_ }
            if ($oldExecIds) {
                $sampleExecId = $oldExecIds[0]
                foreach ($d in $hashDirs) {
                    $indexFile = Join-Path $d.FullName "f62de366d0006e17ea00a01f6624aabf"
                    if (-not (Test-Path $indexFile)) { continue }
                    $idxContent = Get-Content $indexFile -Raw
                    if ($idxContent.Contains($sampleExecId)) {
                        $oldStorageHash = $d.Name
                        break
                    }
                }
            } else {
                Write-Warn "No executionIds found in old session files. Execution data discovery skipped."
            }
        }

        if (-not $newStorageHash) {
            $newExecIds = ($pyExtractExecIds | & $Python -I - $newDir) -split "`n" | ForEach-Object { $_.Trim() } | Where-Object { $_ }
            if ($newExecIds) {
                $sampleNewExecId = $newExecIds[0]
                foreach ($d in $hashDirs) {
                    $indexFile = Join-Path $d.FullName "f62de366d0006e17ea00a01f6624aabf"
                    if (-not (Test-Path $indexFile)) { continue }
                    $idxContent = Get-Content $indexFile -Raw
                    if ($idxContent.Contains($sampleNewExecId)) {
                        $newStorageHash = $d.Name
                        break
                    }
                }
            } else {
                Write-Warn "No executionIds found in new session files. Execution data discovery skipped."
            }
        }
    }

    if ($oldStorageHash) {
        Write-Host "  Old storage hash: $oldStorageHash"
    } else {
        Write-Warn "Could not find old storage hash directory. Execution data will not be migrated."
        Write-Warn "Sessions will appear but may show 'Loading execution...' for agent responses."
    }

    if ($newStorageHash) {
        Write-Host "  New storage hash: $newStorageHash"
    } else {
        Write-Warn "Could not find new storage hash directory."
    }

    Write-Step "[6/7] Copying execution data..."

    if ($oldStorageHash -and $newStorageHash) {
        $oldStorageDir = Join-Path $KiroAppData $oldStorageHash
        $newStorageDir = Join-Path $KiroAppData $newStorageHash

        # Copy all subdirectories and their contents
        $subDirs = Get-ChildItem $oldStorageDir -Directory -ErrorAction SilentlyContinue
        $execCopied = 0
        foreach ($sd in $subDirs) {
            $targetSd = Join-Path $newStorageDir $sd.Name
            if (-not (Test-Path $targetSd)) {
                if (-not $DryRun) {
                    New-Item -ItemType Directory -Path $targetSd -Force | Out-Null
                }
            }
            $files = Get-ChildItem $sd.FullName -File -ErrorAction SilentlyContinue
            foreach ($f in $files) {
                $targetFile = Join-Path $targetSd $f.Name
                if (-not (Test-Path $targetFile)) {
                    if (-not $DryRun) {
                        Copy-Item $f.FullName $targetFile
                    }
                    $execCopied++
                }
            }
        }

        # Merge execution index (additive, dedup by executionId)
        $oldIndex = Join-Path $oldStorageDir "f62de366d0006e17ea00a01f6624aabf"
        $newIndex = Join-Path $newStorageDir "f62de366d0006e17ea00a01f6624aabf"
        if ((Test-Path $oldIndex) -and -not $DryRun) {
            if (Test-Path $newIndex) {
                # Backup before merge
                Copy-Item $newIndex "$newIndex.bak" -Force
                $pyMergeExec = @'
import json, sys
try:
    with open(sys.argv[1], encoding='utf-8') as f:
        old = json.load(f)
    with open(sys.argv[2], encoding='utf-8') as f:
        new = json.load(f)
    if 'executions' not in old or 'executions' not in new:
        print("  WARNING: Unexpected index format. Falling back to copy.", file=sys.stderr)
        sys.exit(1)
    seen = {e['executionId'] for e in new['executions']}
    added = [e for e in old['executions'] if e['executionId'] not in seen]
    new['executions'] += added
    with open(sys.argv[2], 'w', encoding='utf-8') as f:
        json.dump(new, f, indent=2, ensure_ascii=False)
    print(f"  Merged: {len(old['executions'])} old + {len(new['executions']) - len(added)} existing = {len(new['executions'])} total")
except Exception as e:
    print(f"  WARNING: Merge failed ({e}). Falling back to copy.", file=sys.stderr)
    sys.exit(1)
'@
                $pyMergeExec | & $Python -I - $oldIndex $newIndex
                if ($LASTEXITCODE -ne 0) {
                    Write-Warn "Execution index merge failed. Falling back to copy-overwrite."
                    Copy-Item "$newIndex.bak" $newIndex -Force  # Restore backup
                    Copy-Item $oldIndex $newIndex -Force         # Overwrite with old
                }
            } else {
                Copy-Item $oldIndex $newIndex
            }
        }

        Write-Host "  Copied $execCopied execution data files"
    } else {
        Write-Warn "Skipping execution data copy (storage hashes not found)"
    }
} else {
    Write-Host "[5/7] Skipping execution data (--SkipExecutionData)"
    Write-Host "[6/7] Skipping execution data copy"
}

# ── Cleanup and verify ──

Write-Step "[7/7] Verification and cleanup..."

$finalSessionCount = (Get-ChildItem $newDir -Filter "*.json" | Where-Object { $_.Name -ne "sessions.json" }).Count
Write-Host "  Sessions in target: $finalSessionCount"
Write-Host "  Sessions migrated: $($finalSessionCount - $newSessionCount)"

# Remove old workspace-sessions folder
if (-not $DryRun) {
    Remove-Item $oldDir -Recurse -Force
    Write-Host "  Removed old session folder"
} else {
    Write-Host "  [DRY RUN] Would remove old session folder"
}

# Summary
Write-Host ""
if ($DryRun) {
    Write-Host "=== DRY RUN COMPLETE ===" -ForegroundColor Yellow
} else {
    Write-Host "=== Migration complete ===" -ForegroundColor Green
}
Write-Host "Sessions: $oldSessionCount migrated, $finalSessionCount total in target"
if (-not $SkipExecutionData -and $oldStorageHash -and $newStorageHash) {
    Write-Host "Execution data: copied from $oldStorageHash to $newStorageHash"
    Write-Host "Old execution data preserved in: $oldStorageHash (safe to delete after verification)"
}
Write-Host ""
Write-Host "Next: Open Kiro in the new workspace and verify sessions load correctly."
