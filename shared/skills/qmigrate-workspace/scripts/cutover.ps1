<#
  qmigrate-workspace cutover. Normally the USER runs this from a plain PowerShell window outside both
  trees, with every agent and editor closed. An agent may run it only in agent-run mode
  (-IgnoreProcs, below), with the user's authorization in the session.

    & <skill>\scripts\cutover.ps1 -Old <path> -New <path> [-ConfigRepo <live checkout>] [-Also <file>,...] -PlanOnly
    & <skill>\scripts\cutover.ps1 -Old <path> -New <path> [-ConfigRepo <live checkout>] [-Also <file>,...]
    & <skill>\scripts\cutover.ps1 ... -FromStep 4      # resume after a failure in step 4 or later

  -ConfigRepo                the agent-playbook checkout that is live AFTER the move (under -New when it moves).
  -Also                      extra files for apply.py to rewrite whole (found by `verify.py residue`).
  -AlreadyMoved              the folder was moved by something else (OneDrive, Explorer): OLD is absent or
                             holds no file (an empty tree, desktop.ini and Thumbs.db are fine; any other
                             file, or a link at OLD, means the move is not finished and the script refuses).
                             NEW must exist and be non-empty. Step 1 is skipped entirely (no robocopy in any
                             form; no file under OLD is read or copied and OLD is never created, only listed to prove it
                             holds no file); steps 2-7 run as normal.
  -IgnoreProcs               agent-run mode. Relaxes ONLY the running-process check, and only for claude
                             processes (the agent driving this script is one). It still refuses while any
                             codex, kiro/kiro-cli, Code (VS Code), PowerAtlas or gemini process is alive (Gemini
                             CLI runs as node.exe: a node.exe whose command line names gemini counts), or any
                             process command line or exe is inside OLD (this process's own ancestors excepted). Passes --ignore-procs to apply.py,
                             which rewrites history.jsonl and .claude.json with a re-check, because the live
                             claude sessions keep appending to them, and refuses while a live claude session
                             has its cwd inside OLD or NEW. Run it from a folder outside both trees.
  Never deletes OLD. Step 1 is skipped on re-runs (marker in the per-migration work folder), because
  /MIR would undo later rewrites. Every change outside apply.py's manifest is logged to
  <work>\cutover-changes.log for the rollback described in SKILL.md.
#>
param(
  [Parameter(Mandatory)][string]$Old,
  [Parameter(Mandatory)][string]$New,
  [string]$ConfigRepo,
  [string[]]$Also = @(),
  [string]$Work,
  [switch]$PlanOnly,
  [switch]$AlreadyMoved,
  [switch]$IgnoreProcs,
  [double]$FromStep = 0
)
$ErrorActionPreference = 'Stop'
$Old = $Old.TrimEnd('\'); $New = $New.TrimEnd('\')
$Here = $PSScriptRoot
function Get-WorkDir($o, $n) {  # same name as pathmap.work_dir(): one folder per OLD|NEW pair
  $b = [Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($o.ToLower() + '|' + $n.ToLower()))
  Join-Path "$HOME\.agent-playbook\qmigrate-workspace" ((Split-Path $o -Leaf) + '-' + ([BitConverter]::ToString($b) -replace '-','').ToLower().Substring(0,8))
}
if (-not $Work) { $Work = Get-WorkDir $Old $New }
New-Item -ItemType Directory -Force $Work | Out-Null
$ChangeLog = Join-Path $Work 'cutover-changes.log'
function Step($n, $msg) { Write-Host "`n=== [$n] $msg" -ForegroundColor Cyan }
function Need-Ok($what) { if ($LASTEXITCODE -ne 0) { throw "$what failed (exit $LASTEXITCODE). Stopped. Resume with -FromStep after fixing." } }
function Note($s) { Add-Content $ChangeLog "$(Get-Date -Format o)`t$s"; "  $s" }
# Boundary-correct, case-insensitive path tests. `-like "$Old*"` would also match ...\Repos and treats [ ] as wildcards.
$OldRx = '(?i)' + [regex]::Escape($Old) + '(?=$|[\\/"''\s])'
function Test-UnderOld([string]$p) { $p = $p -replace '^\\\\\?\\',''; $p -match ('^' + $OldRx) }
function Convert-ToNew([string]$s) { [regex]::Replace($s, $OldRx, { param($m) $New }) }

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
$SkillRepo = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent (Split-Path -Parent (Resolve-RealPath $Here))))
$Python = Join-Path $SkillRepo '.venv-agent-playbook\Scripts\python.exe'
$dash = [string][char]0x2014
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw "venv missing $dash run setup.ps1 (expected $Python)" }
# apply.py imports tomllib, so the venv must be Python 3.11+. Exit 1 means older; any other failure means the venv python cannot start.
# A file that is not a program makes the call throw instead of setting an exit code; treat that as "cannot start".
try { & $Python -I -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" } catch { $global:LASTEXITCODE = 255 }
if ($LASTEXITCODE -eq 1) { throw "The venv Python is older than 3.11 (apply.py needs tomllib): delete $SkillRepo\.venv-agent-playbook and run setup.ps1 with a 3.11+ system Python." }
if ($LASTEXITCODE) { throw "The venv Python failed to start (exit $LASTEXITCODE) $dash run setup.ps1 (it rebuilds a broken venv)." }
$applyArgs = @('--old', $Old, '--new', $New, '--work', $Work) + $(if ($ConfigRepo) { @('--config-repo', $ConfigRepo) } else { @() }) + @($Also | ForEach-Object { '--also', $_ }) + $(if ($IgnoreProcs) { @('--ignore-procs') } else { @() })

if ($FromStep -le 3) {
# ------------------------------------------------------------------ 0 pre-flight
Step 0 'Pre-flight'
$cwd = (Get-Location).Path
if ((Test-UnderOld $cwd) -or $cwd -like "$New\*" -or $cwd -eq $New) { throw 'Run this from a folder outside both trees.' }
if ($Old -ieq $New -or $New.ToLower().StartsWith($Old.ToLower() + '\') -or $Old.ToLower().StartsWith($New.ToLower() + '\')) { throw 'OLD and NEW must not be equal or nested.' }
if ($AlreadyMoved) {
  # The move was done by something else. Ready only when OLD holds no file: an empty tree, or only
  # desktop.ini / Thumbs.db. Anything else (a file, a link at OLD) means the move is not finished.
  if (-not (Test-Path -LiteralPath $New -PathType Container)) { throw "NEW does not exist or is not a folder: $New. -AlreadyMoved needs the moved folder at NEW." }
  if (@(Get-ChildItem -LiteralPath $New -Force | Select-Object -First 1).Count -eq 0) { throw "NEW is empty: $New. -AlreadyMoved needs the moved folder at NEW." }
  if (Test-Path -LiteralPath $Old) {
    $oi = Get-Item -LiteralPath $Old -Force
    if (-not $oi.PSIsContainer -or $oi.LinkType) { throw "OLD is a file or a link, not a folder tree: $Old. The move is not finished; do not use -AlreadyMoved." }
    # A listing that hits an error (a folder this user cannot read) proves nothing about what it holds: refuse.
    $left = @(Get-ChildItem -LiteralPath $Old -Force -Recurse -ErrorAction SilentlyContinue -ErrorVariable listErr | Where-Object { -not ($_.PSIsContainer -and -not $_.LinkType) -and @('desktop.ini','Thumbs.db') -notcontains $_.Name })
    if ($listErr.Count) {
      $listErr | Select-Object -First 5 | ForEach-Object { "  cannot list: $($_.Exception.Message)" }
      throw "OLD could not be listed completely ($($listErr.Count) error(s)), so it may still hold files: the move may not be finished. Fix the access problem (or run the normal cutover). Nothing changed."
    }
    if ($left) {
      $left | Select-Object -First 5 | ForEach-Object { "  still in OLD: $($_.FullName)" }
      throw "OLD still holds $($left.Count) file(s)/link(s): the move is not finished. Wait for it to end (OneDrive: check sync status) or drop -AlreadyMoved and run the normal cutover. Nothing changed."
    }
  }
}
else {
  if (-not (Test-Path -LiteralPath $Old)) { throw "OLD does not exist: $Old. If something else already moved the folder to NEW, use -AlreadyMoved." }
  if (-not (Test-Path $New)) { throw 'NEW does not exist yet: make the bulk copy first (SKILL.md Step 2).' }
  if ((Get-ChildItem $Old -Force).Count -eq 0) { throw 'OLD is empty: refusing to mirror it (/MIR would purge NEW).' }
  $oldTop = @(Get-ChildItem $Old -Force | ForEach-Object Name)
  $foreign = @(Get-ChildItem $New -Force | Where-Object { $oldTop -notcontains $_.Name } | ForEach-Object Name)
  if ($foreign) { throw "NEW holds top-level entries OLD does not have ($($foreign -join ', ')); /MIR would delete them. Move them out or pick another NEW." }
}
$names = 'claude','codex','Kiro','kiro-cli','PowerAtlas','power-atlas','Code','gemini'
$live = @(Get-Process | Where-Object { $n = $_.ProcessName; $names | Where-Object { $n -like "$_*" } })
# -IgnoreProcs relaxes this one check for claude processes only; every other agent or editor still blocks.
if ($IgnoreProcs) { $live = @($live | Where-Object { $_.ProcessName -notlike 'claude*' }) }
# Gemini CLI runs as node.exe: count a node.exe whose command line names gemini. Never relaxed by -IgnoreProcs.
$procs = @(Get-CimInstance Win32_Process)
$live += @($procs | Where-Object { $_.Name -ieq 'node.exe' -and "$($_.CommandLine)" -match 'gemini' } | ForEach-Object { [pscustomobject]@{ ProcessName = 'node.exe (Gemini CLI)'; Id = $_.ProcessId } })
# This process's own ancestors (the shell that launched it, the agent above it) may name OLD on their command
# line without holding anything in OLD: they are not holders.
$anc = @{}; $cur = [int]$PID
for ($i = 0; $i -lt 32; $i++) {
  $anc[$cur] = $true
  $me = $procs | Where-Object { [int]$_.ProcessId -eq $cur } | Select-Object -First 1
  if (-not $me) { break }
  $pid2 = [int]$me.ParentProcessId
  if (-not $pid2 -or $anc.ContainsKey($pid2)) { break }
  $pp = $procs | Where-Object { [int]$_.ProcessId -eq $pid2 } | Select-Object -First 1
  if (-not $pp) { break }
  # A parent created AFTER its child is a reused pid, not the real parent: the chain ends here.
  if ($me.CreationDate -and $pp.CreationDate -and $pp.CreationDate -gt $me.CreationDate) { break }
  $cur = $pid2
}
$holders = @($procs | Where-Object { -not $anc.ContainsKey([int]$_.ProcessId) -and (("$($_.CommandLine)" -match $OldRx) -or ("$($_.ExecutablePath)" -match $OldRx)) })
if ($live -or $holders) {
  $live | ForEach-Object { "  running: $($_.ProcessName) (pid $($_.Id))" }
  $holders | ForEach-Object { "  pid $($_.ProcessId) $($_.Name): command line or exe is inside OLD" }
  if (-not $PlanOnly) { throw 'Close those (quit tray apps from their own UI; end leftover services in Task Manager), then re-run. Nothing changed.' }
}

# ------------------------------------------------------------------ 1 final sync
Step 1 'Final sync OLD -> NEW (delta only)'
if ($AlreadyMoved) { Write-Host '-AlreadyMoved: step 1 skipped (no robocopy of any kind; OLD was only listed to prove it holds no file)' -ForegroundColor Yellow }
else {
$venvXd = @()
$idx = Join-Path $Work 'freeze\index.json'
if (Test-Path $idx) { @((Get-Content $idx -Raw | ConvertFrom-Json).venvs | Where-Object { $_ }) | ForEach-Object { $venvXd += "$Old\$($_.rel)"; $venvXd += "$New\$($_.rel)" } }
# /SL and /SJ copy symlinks and junctions as links (step 3 relinks the ones that point into OLD)
$flags = @('/MIR','/COPY:DAT','/DCOPY:DAT','/SL','/SJ','/R:2','/W:2','/MT:8','/NP','/NDL') + $(if ($venvXd) { @('/XD') + $venvXd } else { @() })
$marker = Join-Path $Work 'step1-done'
if (Test-Path $marker) { Write-Host "already done on an earlier run of this migration ($(Get-Content $marker)); skipped" -ForegroundColor Yellow }
elseif ($PlanOnly) { robocopy $Old $New @flags '/L' '/NFL' '/NJH' | Out-Host }
else {
  robocopy $Old $New @flags "/LOG:$Work\robocopy-final.log" | Out-Null
  if ($LASTEXITCODE -ge 8) { throw "robocopy failed (exit $LASTEXITCODE): $Work\robocopy-final.log" }
  attrib -O -U "$New\*" /S /D 2>&1 | Out-Null   # OneDrive stubs leave Offline/Unpinned bits on copies
  robocopy $Old $New @flags '/L' '/NFL' '/NJH' '/NJS' | Out-Null
  if ($LASTEXITCODE -ne 0) { throw 'NEW is not identical to OLD after the sync.' }
  Set-Content $marker "$(Get-Date -Format o) $Old -> $New"
  Write-Host 'NEW verified identical to OLD (robocopy /L has nothing to do)'
}
} # end step 1 (skipped by -AlreadyMoved)

# ------------------------------------------------------------------ 2 agent stores
Step 2 'Rewrite path-keyed agent stores (apply.py)'
& $Python -I "$Here\apply.py" @applyArgs $(if (-not $PlanOnly) { '--apply' })
if ($LASTEXITCODE -ne 0) { throw "apply.py exit $LASTEXITCODE. If its output says the run is partly applied (BLOCKERS after changes began, e.g. a file a live session kept changing), fix the cause and re-run this same command: apply.py is idempotent and step 1 is skipped by its marker, so do not restore. To undo the whole migration instead: & `"$Python`" -I $Here\restore.py $Work --apply (undoes every run in the work folder)" }
if ($PlanOnly) { Write-Host "`nPlanOnly: steps 3-7 (symlinks, worktrees, setup, Kiro IDE, shortcuts, verify) not previewed. Nothing changed." -ForegroundColor Green; return }

# ------------------------------------------------------------------ 3 symlinks inside NEW
Step 3 'Relink symlinks and junctions under NEW that still target OLD'
Get-ChildItem $New -Recurse -Force -Attributes ReparsePoint -ErrorAction SilentlyContinue |
  Where-Object { $_.LinkType -in 'SymbolicLink','Junction' -and (Test-UnderOld ([string]($_.Target | Select-Object -First 1))) } |
  ForEach-Object {
    $t = ([string]($_.Target | Select-Object -First 1)) -replace '^\\\\\?\\',''
    $nt = Convert-ToNew $t; $p = $_.FullName; $type = $_.LinkType; $isDir = $_.PSIsContainer
    if ($isDir) { cmd /c rmdir "$p" | Out-Null } else { Remove-Item -LiteralPath $p -Force }
    try { New-Item -ItemType $type -Path $p -Target $nt -ErrorAction Stop | Out-Null; Note "relinked $p : $t -> $nt" }
    catch { New-Item -ItemType $type -Path $p -Target $t | Out-Null; throw "could not create $type $p -> $nt (developer mode or admin needed); restored the old link" }
  }
} # end steps 0-3

# ------------------------------------------------------------------ 4 git worktrees
Step 4 'Repair git worktree links (registered worktrees only)'
$repos = @(Get-ChildItem $New -Directory -Force -Recurse -Depth 3 -Filter .git -ErrorAction SilentlyContinue | ForEach-Object { $_.Parent.FullName })
if (Test-Path "$New\.git" -PathType Container) { $repos = @($New) + $repos }
foreach ($r in $repos | Sort-Object -Unique) {
  # `worktree list` still prints OLD paths in a copied repo: map them into NEW, keep the ones that exist.
  # A stray folder under .claude\worktrees with no .git is NOT a worktree; passing it makes repair exit 1.
  $wt = @(git -C $r worktree list --porcelain | Where-Object { $_ -like 'worktree *' } |
          ForEach-Object { Convert-ToNew (($_ -replace '^worktree ','') -replace '/','\') } |
          Where-Object { $_ -ne $r -and (Test-Path (Join-Path $_ '.git')) })
  if (-not $wt.Count) { continue }
  git -C $r worktree repair @wt; Need-Ok "git worktree repair in $r"
  $bad = @(git -C $r worktree list --porcelain | Where-Object { $_ -like 'worktree *' } | Where-Object { Test-UnderOld (($_ -replace '^worktree ','') -replace '/','\') })
  $pr = @(git -C $r worktree list --porcelain | Select-String 'prunable').Count
  if ($bad -or $pr) { throw "$r : worktrees still point into OLD ($($bad.Count)) or are prunable ($pr)" }
  "  $r : $($wt.Count) linked worktrees repaired"
}

# ------------------------------------------------------------------ 5 deployment
if ($ConfigRepo -and $ConfigRepo.ToLower().StartsWith($New.ToLower() + '\')) {
  Step 5 'Repoint provider deployments at the moved config repo (setup.ps1)'
  & "$ConfigRepo\setup.ps1"; Need-Ok 'setup.ps1'
  Note "setup.ps1 repointed deployments to $ConfigRepo; undo by running the OLD checkout's setup.ps1"
}

# ------------------------------------------------------------------ 6 Kiro IDE legacy history
Step 6 'Kiro IDE legacy workspace history'
if (Get-Process | Where-Object { $_.ProcessName -like 'Kiro*' -or $_.ProcessName -like 'kiro-cli*' }) { throw 'Kiro is running: close it, then re-run with -FromStep 6.' }
$wsRoot = "$env:APPDATA\Kiro\User\globalStorage\kiro.kiroagent\workspace-sessions"
$bk = Join-Path $Work 'kiro-ide-backup'; New-Item -ItemType Directory -Force $bk | Out-Null
foreach ($dir in Get-ChildItem $wsRoot -Directory -ErrorAction SilentlyContinue) {
  # Kiro's names: base64 with + -> -, / -> _, and padding = -> _ (kept). Trailing _ are padding, inner _ are /.
  $b64 = ($dir.Name -replace '-','+') -replace '_(?=_*$)','='
  try { $decoded = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String(($b64 -replace '_','/'))) } catch { Write-Host "  undecodable folder name, skipped: $($dir.Name)" -ForegroundColor Yellow; continue }
  if (-not (Test-UnderOld $decoded)) { continue }
  robocopy $dir.FullName (Join-Path $bk $dir.Name) /E /COPY:DAT /R:1 /W:1 /NP /NFL /NDL /NJH /NJS | Out-Null
  if ($LASTEXITCODE -ge 8) { throw "backup of $decoded failed" }
  $n = Convert-ToNew $decoded
  $n = $n.Substring(0,1).ToLower() + $n.Substring(1)   # Kiro IDE encodes the path with a lower-case drive letter
  & powershell -NoProfile -ExecutionPolicy Bypass -File "$Here\kiro-ide-migrate.ps1" -OldPath $decoded -NewPath $n -DryRun *> "$Work\kiro-ide-dryrun.log"
  Need-Ok "kiro-ide-migrate -DryRun $decoded"
  & powershell -NoProfile -ExecutionPolicy Bypass -File "$Here\kiro-ide-migrate.ps1" -OldPath $decoded -NewPath $n *> "$Work\kiro-ide-$($dir.Name.Substring(0,12)).log"
  Need-Ok "kiro-ide-migrate $decoded"
  Note "Kiro IDE legacy history $decoded -> $n (original folder backed up in $bk\$($dir.Name))"
}

# ------------------------------------------------------------------ 6b shortcuts
Step '6b' 'Retarget shortcuts that launch from OLD'
$sh = New-Object -ComObject WScript.Shell
$lb = Join-Path $Work 'shortcuts-backup'; New-Item -ItemType Directory -Force $lb | Out-Null
$dirs = @("$env:APPDATA\Microsoft\Windows\Start Menu\Programs", "$env:USERPROFILE\Desktop") + @(Get-ChildItem $env:USERPROFILE -Directory -Filter 'OneDrive*' | ForEach-Object { "$($_.FullName)\Desktop" })
foreach ($d in $dirs | Where-Object { Test-Path $_ }) {
  Get-ChildItem $d -Filter *.lnk -Recurse -Force -ErrorAction SilentlyContinue | ForEach-Object {
    $l = $sh.CreateShortcut($_.FullName)
    if ("$($l.TargetPath)|$($l.Arguments)|$($l.WorkingDirectory)|$($l.IconLocation)" -notmatch $OldRx) { return }
    $tag = ([BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($_.FullName.ToLower()))) -replace '-','').Substring(0,8)
    $bf = Join-Path $lb "$tag`__$($_.Name)"
    Copy-Item $_.FullName $bf -Force
    # read first: assigning TargetPath reset WorkingDirectory to C:\ on 2026-10-02
    $wd = $l.WorkingDirectory; $icon = $l.IconLocation
    $l.TargetPath = Convert-ToNew $l.TargetPath; $l.Arguments = Convert-ToNew $l.Arguments
    $l.WorkingDirectory = Convert-ToNew $wd; $l.IconLocation = Convert-ToNew $icon
    $l.Save(); Note "retargeted shortcut $($_.FullName) (original: $bf)"
  }
}

# ------------------------------------------------------------------ 7 verify
Step 7 'Verify'
if ($ConfigRepo -and -not (Test-Path "$ConfigRepo\.venv-agent-playbook\Scripts\python.exe")) { "verify-deployment could not run: no venv in $ConfigRepo (run setup.ps1 there)" }
elseif ($ConfigRepo) { & "$ConfigRepo\.venv-agent-playbook\Scripts\python.exe" -I "$ConfigRepo\shared\skills\qconfig-sync\scripts\verify-deployment.py" *> "$Work\verify-deployment.log"; "verify-deployment exit $LASTEXITCODE : $((Get-Content "$Work\verify-deployment.log")[-1])" }
& $Python -I "$Here\verify.py" pointers --old $Old
Write-Host "`nDONE. OLD is untouched$(if ($AlreadyMoved) { ' (and was never copied from or created)' }). Changes outside apply.py's manifest: $ChangeLog. Next: SKILL.md Step 5." -ForegroundColor Green
