<#
  Python virtualenvs cannot be moved: console-script launchers, activate scripts and editable-install
  finders embed the old absolute path. Record them before the move, rebuild them in the new tree after.

    & .\venvs.ps1 -Phase freeze  -Old <path> -New <path>                 # reads OLD only
    & .\venvs.ps1 -Phase rebuild -Old <path> -New <path> [-Only 'a\.venv','b\.venv-x']

  Invoke with `&`, never `pwsh -File`: -File passes `-Only 'a','b'` as ONE comma-joined string, nothing
  matches the filter, and the run reports success having done nothing (2026-10-02).
  Rebuild touches only directories under -New. An editable install (`-e git+...` in a freeze) is
  re-pointed at the folder that contains the venv; a venv with more than one editable line is skipped
  and reported, because which project each belongs to cannot be inferred.
  A venv whose base interpreter (pyvenv.cfg `home`) no longer exists is reported and left as copied.
#>
param(
  [Parameter(Mandatory)][ValidateSet('freeze','rebuild')][string]$Phase,
  [Parameter(Mandatory)][string]$Old,
  [Parameter(Mandatory)][string]$New,
  [string]$Work,
  [string[]]$Only
)
$ErrorActionPreference = 'Stop'
$Old = $Old.TrimEnd('\'); $New = $New.TrimEnd('\')
function Get-WorkDir($o, $n) {  # same name as pathmap.work_dir(): one folder per OLD|NEW pair
  $b = [Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($o.ToLower() + '|' + $n.ToLower()))
  Join-Path "$HOME\.agent-playbook\qmigrate-workspace" ((Split-Path $o -Leaf) + '-' + ([BitConverter]::ToString($b) -replace '-','').ToLower().Substring(0,8))
}
if (-not $Work) { $Work = Get-WorkDir $Old $New }
$fz = Join-Path $Work 'freeze'; $index = Join-Path $fz 'index.json'

if ($Phase -eq 'freeze') {
  New-Item -ItemType Directory -Force $fz | Out-Null
  $found = Get-ChildItem $Old -Recurse -Force -Filter pyvenv.cfg -ErrorAction SilentlyContinue |
           Where-Object { $_.FullName -notmatch '\\node_modules\\' }
  $rows = foreach ($cfg in $found) {
    $dir = $cfg.Directory.FullName; $rel = $dir.Substring($Old.Length + 1)
    $home_ = ((Get-Content $cfg.FullName) | Where-Object { $_ -match '^\s*home\s*=' }) -replace '^\s*home\s*=\s*',''
    $base = Join-Path $home_.Trim() 'python.exe'
    $py = Join-Path $dir 'Scripts\python.exe'
    $file = Join-Path $fz (($rel -replace '[\\/]','__') + '.txt')
    $state = 'ok'
    if (-not (Test-Path $base)) { $state = "base interpreter missing: $base" }
    else { & $py -m pip freeze --disable-pip-version-check 2>$null | Set-Content $file -Encoding utf8; if ($LASTEXITCODE) { $state = 'pip freeze failed' } }
    $n = if (Test-Path $file) { @(Get-Content $file).Count } else { 0 }
    "{0,-45} {1,4} packages  {2}" -f $rel, $n, $state | Write-Host
    [pscustomobject]@{ rel = $rel; base = $base; freeze = $file; state = $state }
  }
  [pscustomobject]@{ old = $Old; new = $New; venvs = @($rows) } | ConvertTo-Json -Depth 4 | Set-Content $index -Encoding utf8
  Write-Host "index: $index ($(@($rows).Count) venvs)"
  return
}

# ---- rebuild
if (-not (Test-Path $index)) { throw "No freeze index for this migration ($index): run -Phase freeze first, against OLD." }
$ix = Get-Content $index -Raw | ConvertFrom-Json
if ($ix.old -ne $Old -or $ix.new -ne $New) { throw "The freeze index belongs to another migration ($($ix.old) -> $($ix.new))." }
$rows = @($ix.venvs | Where-Object { $_ })
foreach ($v in $rows) {
  if ($Only -and ($Only -notcontains $v.rel)) { continue }
  Write-Host "`n=== $($v.rel)" -ForegroundColor Cyan
  if ($v.state -ne 'ok') { Write-Host "  skipped: $($v.state) (left as copied)" -ForegroundColor Yellow; continue }
  $dir = Join-Path $New $v.rel
  if (-not $dir.StartsWith($New + '\')) { throw "refusing to touch $dir" }
  $lines = Get-Content $v.freeze
  $editable = @($lines | Where-Object { $_ -match '^-e ' })
  if ($editable.Count -gt 1) { Write-Host '  skipped: more than one editable install; rebuild by hand' -ForegroundColor Yellow; continue }
  $proj = Split-Path $dir -Parent
  $req = Join-Path $fz ('fixed_' + (Split-Path $v.freeze -Leaf))
  $lines | ForEach-Object { if ($_ -match '^-e ') { "-e `"$proj`"" } else { $_ } } | Set-Content $req -Encoding utf8
  # OneDrive copies carry read-only bits that make `venv --clear` fail with Access denied: delete explicitly.
  if (Test-Path $dir) { attrib -R "$dir\*" /S /D 2>&1 | Out-Null; attrib -R $dir 2>&1 | Out-Null; Remove-Item $dir -Recurse -Force }
  & $v.base -m venv $dir; if ($LASTEXITCODE) { throw "venv create failed: $dir" }
  $py = Join-Path $dir 'Scripts\python.exe'
  & $py -m pip install --disable-pip-version-check -q -r $req; if ($LASTEXITCODE) { throw "pip install failed: $dir" }
  $now  = (& $py -m pip freeze --disable-pip-version-check) | ForEach-Object { $_ -replace '^-e .*','-e <editable>' } | Sort-Object
  $then = $lines | ForEach-Object { $_ -replace '^-e .*','-e <editable>' } | Sort-Object
  $diff = Compare-Object $then $now
  if ($diff) { $diff | ForEach-Object { "  differs: $($_.SideIndicator) $($_.InputObject)" } } else { Write-Host '  identical package set' -ForegroundColor Green }
  & $py -m pip check --disable-pip-version-check
  if ($editable) { & $py -m pip list --editable --disable-pip-version-check }
}
