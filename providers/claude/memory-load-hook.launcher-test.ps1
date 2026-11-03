# Test for the SessionStart hook launcher, memory-load-hook.ps1.
#
# Runs the launcher the way Claude Code does (`powershell.exe -NoProfile
# -ExecutionPolicy Bypass -File <launcher>`, hook JSON on stdin) under Windows
# PowerShell 5.1 and, when installed, PowerShell 7 (pwsh). Cases:
#   real-hook-matches-direct   venv present: the real hook, copied into a sandbox
#                              repo with fixed fixture memory, prints the same bytes
#                              through the launcher as when run directly under the venv
#                              python (an independent path); the output parses as
#                              SessionStart JSON and names the fixture memory. The
#                              hook's time-cap notes are the one tolerated difference:
#                              a busy runner can spend the cap in only one of the runs
#   stdin-and-stdout-passthrough  a sandbox hook echoes stdin: non-ASCII text, CRLF,
#                              quotes and backslashes arrive intact and come back
#                              without a BOM or extra output
#   venv-missing               sandbox without a venv: exact notice, exit 0, and NO
#                              fallback to the python on PATH (the sandbox hook would
#                              work if it ran)
#   venv-python-broken         venv python.exe present but its pyvenv.cfg points at no
#                              interpreter, so it cannot start: notice, exit 0
#   launcher-outside-repo      launcher copied where no repo surrounds it: the
#                              "could not locate the repo" notice, not "venv missing"
#   hook-exit-nonzero / hook-exit-nonzero-valid-json / hook-garbage-output /
#   hook-wrong-json-shape / hook-file-missing
#                              every failure mode prints the notice and exits 0
#   hook-timeout               a hook that sleeps is killed at the timeout; afterwards
#                              no process from the sandbox remains. This guards that the
#                              hook is killed at all, not the launcher's `taskkill /T`:
#                              the venv python.exe redirector's job object already ends
#                              the base interpreter it started (measured: the case passes
#                              with the taskkill line removed). `/T` only covers hook
#                              grandchildren such as git, which no case here starts.
#   hook-never-reads-stdin     4 MB of stdin to a hook that never reads it: the launcher
#                              still returns at the timeout (a synchronous write would
#                              block on the full pipe)
#   hook-exits-early-big-stdin 4 MB of stdin to a hook that exits 3 at once without reading:
#                              the write fails on a broken pipe, which the launcher
#                              ignores; the exit code decides ("hook failed (exit 3)")
#   launcher-stdin-never-closed  the parent writes the input but never closes the pipe:
#                              the launcher's own stdin read is bounded by the cap, so it
#                              exits 0 with the timeout notice (the hook is not started)
#   relative-symlink-launcher / symlinked-parent-dir
#                              the launcher invoked through a relative file symlink (as
#                              deployed) and through a symlinked directory finds its repo
#                              and venv; a case is SKIPped when symlinks cannot be made
# Sandbox cases copy the launcher and the venv's python.exe + pyvenv.cfg into a
# temporary folder, so the real venv is never renamed or touched and the test can
# run while other scripts use it. A literal "venv renamed away" run is not repeated
# here; the sandbox without a venv is the equivalent.
#
# Not testable here: a dangling deployed symlink makes PowerShell itself exit 1 before
# the launcher starts, so no notice can be printed (providers/claude/README.md).
#
# Usage: pwsh|powershell -File memory-load-hook.launcher-test.ps1 [-Launcher <path>]
#   -Launcher  launcher under test (default: the one beside this file; pass
#              ~/.claude/memory-load-hook.ps1 to test the deployed symlink)
# Exit: 0 all cases pass; 1 a case failed; 2 could not run (no venv, no sandbox).
# Kept ASCII-only: Windows PowerShell 5.1 reads a BOM-less file as ANSI.

param([string]$Launcher)

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $Launcher) { $Launcher = Join-Path $here 'memory-load-hook.ps1' }
$repo = Split-Path -Parent (Split-Path -Parent $here)
$venvDir = Join-Path $repo '.venv-agent-playbook'
$venvPython = Join-Path $venvDir 'Scripts\python.exe'
$realHook = Join-Path $here 'memory-load-hook.py'
$helperDir = Join-Path $repo 'shared\skills\qdream\scripts'

function Stop-CouldNotRun([string]$Why) {
    [Console]::Error.WriteLine("COULD NOT RUN: $Why")
    exit 2
}
if (-not (Test-Path -LiteralPath $Launcher -PathType Leaf)) { Stop-CouldNotRun "launcher not found: $Launcher. Pass -Launcher <path>." }
if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) { Stop-CouldNotRun "venv missing at $venvDir. Run setup.ps1, then re-run this test." }

$dash = [string][char]0x2014
$utf8 = New-Object System.Text.UTF8Encoding($false)
$strictUtf8 = New-Object System.Text.UTF8Encoding($false, $true)

# Run an executable with raw stdin bytes; return exit code, raw stdout bytes, stderr text.
function Invoke-Exe {
    # -KeepStdinOpen: write the input but never close the pipe, as a parent that holds it
    # open would. Then a process still running after -WaitMs is killed and reported with
    # ExitCode -999 instead of aborting the whole test run.
    param([string]$Exe, [string]$Arguments, [byte[]]$Stdin, [hashtable]$EnvVars = @{}, [switch]$KeepStdinOpen, [int]$WaitMs = 120000)
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $Exe
    $psi.Arguments = $Arguments
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardInput = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    foreach ($k in $EnvVars.Keys) { $psi.EnvironmentVariables[$k] = [string]$EnvVars[$k] }
    $clock = [System.Diagnostics.Stopwatch]::StartNew()
    $p = [System.Diagnostics.Process]::Start($psi)
    $outBuf = New-Object System.IO.MemoryStream
    $errBuf = New-Object System.IO.MemoryStream
    $outTask = $p.StandardOutput.BaseStream.CopyToAsync($outBuf)
    $errTask = $p.StandardError.BaseStream.CopyToAsync($errBuf)
    try {
        $p.StandardInput.BaseStream.Write($Stdin, 0, $Stdin.Length)
        $p.StandardInput.BaseStream.Flush()
    } catch { } finally { if (-not $KeepStdinOpen) { try { $p.StandardInput.Close() } catch { } } }
    $hung = $false
    if (-not $p.WaitForExit($WaitMs)) {
        try { $p.Kill() } catch { }
        if (-not $KeepStdinOpen) { throw "timed out running $Exe" }
        $hung = $true
        [void]$p.WaitForExit(5000)
    }
    if ($KeepStdinOpen) { try { $p.StandardInput.Close() } catch { } }
    [void]$outTask.Wait(5000)
    [void]$errTask.Wait(5000)
    return [PSCustomObject]@{
        ExitCode = $(if ($hung) { -999 } else { $p.ExitCode })
        Out      = $outBuf.ToArray()
        Err      = $utf8.GetString($errBuf.ToArray())
        Seconds  = $clock.Elapsed.TotalSeconds
    }
}

function Invoke-Launcher {
    param([string]$Engine, [string]$LauncherPath, [byte[]]$Stdin, [hashtable]$EnvVars = @{}, [switch]$KeepStdinOpen, [int]$WaitMs = 120000)
    $args1 = '-NoProfile -ExecutionPolicy Bypass -File "' + $LauncherPath + '"'
    return Invoke-Exe -Exe $Engine -Arguments $args1 -Stdin $Stdin -EnvVars $EnvVars -KeepStdinOpen:$KeepStdinOpen -WaitMs $WaitMs
}

# Parse stdout as SessionStart hook JSON; returns additionalContext or $null.
function Get-Context([byte[]]$Bytes) {
    try {
        $obj = ConvertFrom-Json -InputObject $strictUtf8.GetString($Bytes)
        if ($obj.hookSpecificOutput.hookEventName -ne 'SessionStart') { return $null }
        $ctx = $obj.hookSpecificOutput.additionalContext
        if ($ctx -is [string]) { return $ctx }
    } catch { }
    return $null
}

# The hook's two timing notes: a busy machine can spend the hook's time cap in one of the two runs
# and not the other, so these are the only lines the launcher and direct outputs may differ by.
$capSkipNote = "Note: store repo check skipped (the hook's time cap was spent)."
function Remove-TimeCapNotes([string]$Ctx) {
    if ($null -eq $Ctx) { return $null }
    $kept = @($Ctx -split "`n" | Where-Object { $_ -cne $capSkipNote })
    return (($kept -join "`n") -replace ' \S+ marks omitted: the git check passed the [0-9.]+-second cap\.', '')
}

function Test-NoBom([byte[]]$Bytes) {
    return ($Bytes.Length -gt 0) -and ($Bytes[0] -eq 0x7B)
}

# Python processes whose command line names a path under $Needle (a sandbox folder).
function Get-SandboxPythons([string]$Needle) {
    $found = @(Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
        Where-Object { $_.CommandLine -and $_.CommandLine.IndexOf($Needle, [StringComparison]::OrdinalIgnoreCase) -ge 0 })
    return $found
}

# Wait up to $Seconds for no sandbox python to remain; returns the leftovers.
function Wait-NoSandboxPythons([string]$Needle, [int]$Seconds = 5) {
    $until = (Get-Date).AddSeconds($Seconds)
    do {
        $left = @(Get-SandboxPythons $Needle)
        if ($left.Count -eq 0) { return $left }
        Start-Sleep -Milliseconds 250
    } while ((Get-Date) -lt $until)
    return $left
}

# Sandbox: <tmp>\providers\claude\{launcher, hook.py} and optionally a venv.
$tmpRoot = Join-Path ([IO.Path]::GetTempPath()) ('launcher-test-' + [Guid]::NewGuid().ToString('N').Substring(0, 8))
$script:sandboxN = 0
$script:lastSandbox = ''
function New-Sandbox {
    param($HookSource, [bool]$WithVenv = $true)   # untyped: $null means "no hook file"
    $script:sandboxN++
    $sb = Join-Path $tmpRoot ("sb$($script:sandboxN)")
    $script:lastSandbox = $sb
    $claude = Join-Path $sb 'providers\claude'
    New-Item -ItemType Directory -Force -Path $claude | Out-Null
    Copy-Item -LiteralPath $Launcher -Destination (Join-Path $claude 'memory-load-hook.ps1')
    if ($null -ne $HookSource) {
        [IO.File]::WriteAllText((Join-Path $claude 'memory-load-hook.py'), $HookSource, $utf8)
    }
    if ($WithVenv) {
        $sbVenv = Join-Path $sb '.venv-agent-playbook'
        New-Item -ItemType Directory -Force -Path (Join-Path $sbVenv 'Scripts') | Out-Null
        Copy-Item -LiteralPath $venvPython -Destination (Join-Path $sbVenv 'Scripts\python.exe')
        Copy-Item -LiteralPath (Join-Path $venvDir 'pyvenv.cfg') -Destination (Join-Path $sbVenv 'pyvenv.cfg')
    }
    return (Join-Path $claude 'memory-load-hook.ps1')
}

# Sandbox repo around the REAL hook, with fixed fixture memory, so the output is the
# same on every run whatever other sessions do to the live memory files.
function New-RealHookSandbox {
    param([string]$Cwd)
    $launcherPath = New-Sandbox -HookSource $null
    $sb = $script:lastSandbox
    Copy-Item -LiteralPath $realHook -Destination (Join-Path $sb 'providers\claude\memory-load-hook.py')
    $scripts = Join-Path $sb 'shared\skills\qdream\scripts'
    New-Item -ItemType Directory -Force -Path $scripts | Out-Null
    foreach ($h in @('qmemory-eval.py', 'dream-manifest.py', 'store-resolver.py', 'memory-entries.py')) {
        Copy-Item -LiteralPath (Join-Path $helperDir $h) -Destination (Join-Path $scripts $h)
    }
    $mem = Join-Path $sb 'memory'
    New-Item -ItemType Directory -Force -Path $mem | Out-Null
    $eAcute = [string][char]0xE9
    $userMemory = "# User Memory`n`n## Topics`n`n| Topic file | Read when | Also cited from |`n|---|---|---|`n| ``memory/topics/zeta.md`` | writing a zeta script | nowhere |`n`n## Feedback`n`n### Zeta fixture rule caf$eAcute`n`n**Why**: fixture.`n**How to apply**: fixture.`n**Source**: fixture | **Verified**: 2026-09-01`n"
    [IO.File]::WriteAllText((Join-Path $mem 'MEMORY.md'), $userMemory, $utf8)
    [IO.File]::WriteAllText((Join-Path $mem 'HIGHER_ORDER.md'), "# Higher-Order Memory`n`n## Pattern`n`n### Omega fixture pattern`n`n**Why**: fixture.`n", $utf8)
    $projMem = Join-Path $Cwd 'memory'
    New-Item -ItemType Directory -Force -Path $projMem | Out-Null
    [IO.File]::WriteAllText((Join-Path $projMem 'MEMORY.md'), "# Project Memory`n`n## Feedback`n`n### Kappa project entry`n`n**Why**: fixture.`n", $utf8)
    return $launcherPath
}

# Make a symlink with cmd's mklink (relative targets are stored as typed). $Dir for a
# directory link. Returns $true when the link exists afterwards.
function New-Link([string]$Link, [string]$Target, [bool]$Dir = $false) {
    $flag = if ($Dir) { '/D ' } else { '' }
    $null = & cmd.exe /c ('mklink ' + $flag + '"' + $Link + '" "' + $Target + '" 2>&1')
    return (Test-Path -LiteralPath $Link)
}

$failures = 0
$passes = 0
$skips = 0
function Assert-Case {
    param([string]$Name, [bool]$Ok, [string]$Detail)
    if ($Ok) { $script:passes++; Write-Host "PASS $Name" }
    else { $script:failures++; Write-Host "FAIL $Name -- $Detail" }
}
function Skip-Case([string]$Name, [string]$Why) { $script:skips++; Write-Host "SKIP $Name -- $Why" }

$engines = @(@{ Name = 'powershell'; Exe = (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe') })
$pwsh = Get-Command pwsh -ErrorAction SilentlyContinue
if ($pwsh) { $engines += @{ Name = 'pwsh'; Exe = $pwsh.Source } }
if (-not (Test-Path -LiteralPath $engines[0].Exe)) { Stop-CouldNotRun "Windows PowerShell not found at $($engines[0].Exe)" }

$missingNotice = 'Playbook memory hook did not run: venv missing ' + $dash + ' run setup.ps1'
$noticePrefix = 'Playbook memory hook did not run: '
$locateNotice = $noticePrefix + 'launcher could not locate the agent-playbook repo'

# A non-ASCII, quote and backslash bearing input with CRLF and no trailing newline.
$eAcute = [string][char]0xE9
$han = [string][char]0x4E2D
$emoji = [char]::ConvertFromUtf32(0x1F600)
$echoInput = '{"cwd": "C:\\caf' + $eAcute + '\\' + $han + '\\' + $emoji + '", "q": "say \"hi\"", "source": "startup"}' + "`r`n" + '{"second": "line"}'
$echoHook = @'
import sys, json
data = sys.stdin.buffer.read()
text = data.decode("utf-8")
out = json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}}, ensure_ascii=False)
sys.stdout.buffer.write(out.encode("utf-8"))
'@

try {
    foreach ($eng in $engines) {
        $tag = $eng.Name

        # --- real hook, fixed fixture memory: launcher bytes == direct venv bytes ---
        $fixtureCwd = Join-Path $tmpRoot ('proj-caf' + $eAcute + '-' + $han)
        $l = New-RealHookSandbox -Cwd $fixtureCwd
        $sbHook = Join-Path (Split-Path -Parent $l) 'memory-load-hook.py'
        $sbVenvPython = Join-Path $script:lastSandbox '.venv-agent-playbook\Scripts\python.exe'
        $hookJson = '{"cwd": ' + (ConvertTo-Json -InputObject $fixtureCwd) + ', "hook_event_name": "SessionStart", "source": "startup"}'
        $stdin = $utf8.GetBytes($hookJson)
        $via = Invoke-Launcher -Engine $eng.Exe -LauncherPath $l -Stdin $stdin
        $direct = Invoke-Exe -Exe $sbVenvPython -Arguments ('-I "' + $sbHook + '"') -Stdin $stdin
        $ctx = Get-Context $via.Out
        $same = ([Convert]::ToBase64String($via.Out) -eq [Convert]::ToBase64String($direct.Out))
        # Not byte-identical only because one run hit the time cap: same context once the timing notes go.
        $ctxDirect = Get-Context $direct.Out
        $capOnly = $false
        if ((-not $same) -and ($null -ne $ctx) -and ($null -ne $ctxDirect)) {
            $a = Remove-TimeCapNotes $ctx
            $b = Remove-TimeCapNotes $ctxDirect
            $capOnly = ($a -ceq $b) -and (($a -cne $ctx) -or ($b -cne $ctxDirect))
        }
        $names = ($null -ne $ctx) -and $ctx.Contains('Zeta fixture rule caf' + $eAcute) -and $ctx.Contains('Omega fixture pattern') -and $ctx.Contains('Kappa project entry')
        $ok = ($via.ExitCode -eq 0) -and ($direct.ExitCode -eq 0) -and ($same -or $capOnly) -and (Test-NoBom $via.Out) -and
              ($null -ne $ctx) -and (-not $ctx.StartsWith($noticePrefix)) -and $names
        Assert-Case "$tag real-hook-matches-direct" $ok ("launcher exit $($via.ExitCode), direct exit $($direct.ExitCode), byte-identical=$same, differs only by time-cap notes=$capOnly, launcher bytes=$($via.Out.Length), direct bytes=$($direct.Out.Length), first byte ok=$(Test-NoBom $via.Out), context parsed=$($null -ne $ctx), names all three fixture entries=$names. stderr: $($via.Err)")

        # --- stdin and stdout pass through intact ------------------------------
        $l = New-Sandbox -HookSource $echoHook
        $r = Invoke-Launcher -Engine $eng.Exe -LauncherPath $l -Stdin ($utf8.GetBytes($echoInput))
        $ctx = Get-Context $r.Out
        $ok = ($r.ExitCode -eq 0) -and (Test-NoBom $r.Out) -and ($null -ne $ctx) -and ($ctx -ceq $echoInput)
        Assert-Case "$tag stdin-and-stdout-passthrough" $ok ("exit $($r.ExitCode), no BOM=$(Test-NoBom $r.Out), context equals input=$($null -ne $ctx -and $ctx -ceq $echoInput), stderr: $($r.Err)")

        # --- venv missing: notice, exit 0, no PATH fallback --------------------
        $l = New-Sandbox -HookSource $echoHook -WithVenv $false
        $r = Invoke-Launcher -Engine $eng.Exe -LauncherPath $l -Stdin ($utf8.GetBytes($echoInput))
        $ctx = Get-Context $r.Out
        $ok = ($r.ExitCode -eq 0) -and (Test-NoBom $r.Out) -and ($ctx -ceq $missingNotice)
        Assert-Case "$tag venv-missing" $ok ("exit $($r.ExitCode), no BOM=$(Test-NoBom $r.Out), context=[$ctx], stderr: $($r.Err)")

        # --- venv python present but cannot start (pyvenv.cfg points nowhere) ----
        $l = New-Sandbox -HookSource $echoHook
        $badCfg = Join-Path $script:lastSandbox '.venv-agent-playbook\pyvenv.cfg'
        [IO.File]::WriteAllText($badCfg, "home = C:\no-such-python-home-" + [Guid]::NewGuid().ToString('N') + "`r`nversion = 3.13.0`r`n", $utf8)
        $r = Invoke-Launcher -Engine $eng.Exe -LauncherPath $l -Stdin ($utf8.GetBytes($echoInput))
        $ctx = Get-Context $r.Out
        $ok = ($r.ExitCode -eq 0) -and (Test-NoBom $r.Out) -and ($null -ne $ctx) -and $ctx.StartsWith($noticePrefix) -and (-not $ctx.StartsWith($missingNotice))
        Assert-Case "$tag venv-python-broken" $ok ("exit $($r.ExitCode), no BOM=$(Test-NoBom $r.Out), context=[$ctx], stderr: $($r.Err)")

        # --- launcher with no repo around it: its own notice -------------------
        $lonely = Join-Path $tmpRoot ("lonely-$tag")
        New-Item -ItemType Directory -Force -Path $lonely | Out-Null
        $l = Join-Path $lonely 'memory-load-hook.ps1'
        Copy-Item -LiteralPath $Launcher -Destination $l
        $r = Invoke-Launcher -Engine $eng.Exe -LauncherPath $l -Stdin ($utf8.GetBytes($echoInput))
        $ctx = Get-Context $r.Out
        $ok = ($r.ExitCode -eq 0) -and (Test-NoBom $r.Out) -and ($null -ne $ctx) -and $ctx.StartsWith($locateNotice) -and (-not $ctx.Contains('venv missing'))
        Assert-Case "$tag launcher-outside-repo" $ok ("exit $($r.ExitCode), no BOM=$(Test-NoBom $r.Out), context=[$ctx], stderr: $($r.Err)")

        # --- failure modes: notice, exit 0 -------------------------------------
        $modes = @(
            @{ Name = 'hook-exit-nonzero'; Src = "import sys`nsys.stderr.write('boom')`nsys.exit(3)"; Want = $noticePrefix + 'hook failed (exit 3)' },
            @{ Name = 'hook-exit-nonzero-valid-json'; Src = "import sys, json`nsys.stdout.write(json.dumps({'hookSpecificOutput': {'hookEventName': 'SessionStart', 'additionalContext': 'x'}}))`nsys.exit(1)"; Want = $noticePrefix + 'hook failed (exit 1)' },
            @{ Name = 'hook-garbage-output'; Src = "print('not json at all')"; Want = $noticePrefix + 'hook printed no valid SessionStart JSON' },
            @{ Name = 'hook-wrong-json-shape'; Src = "print('{`"a`": 1}')"; Want = $noticePrefix + 'hook printed no valid SessionStart JSON' },
            @{ Name = 'hook-file-missing'; Src = $null; Want = $noticePrefix + 'hook failed (exit 2)' }
        )
        foreach ($m in $modes) {
            $l = New-Sandbox -HookSource $m.Src
            $r = Invoke-Launcher -Engine $eng.Exe -LauncherPath $l -Stdin ($utf8.GetBytes($echoInput))
            $ctx = Get-Context $r.Out
            $ok = ($r.ExitCode -eq 0) -and (Test-NoBom $r.Out) -and ($null -ne $ctx) -and $ctx.StartsWith($m.Want)
            Assert-Case "$tag $($m.Name)" $ok ("exit $($r.ExitCode), no BOM=$(Test-NoBom $r.Out), want prefix [$($m.Want)], got [$ctx], stderr: $($r.Err)")
        }

        # --- hook hangs: killed at the timeout, notice, exit 0, nothing left ----
        $l = New-Sandbox -HookSource "import time`ntime.sleep(120)"
        $sbDir = $script:lastSandbox
        $r = Invoke-Launcher -Engine $eng.Exe -LauncherPath $l -Stdin ($utf8.GetBytes($echoInput)) -EnvVars @{ AGENT_PLAYBOOK_HOOK_TIMEOUT_MS = '2000' }
        $ctx = Get-Context $r.Out
        $left = @(Wait-NoSandboxPythons $sbDir)
        $ok = ($r.ExitCode -eq 0) -and ($null -ne $ctx) -and $ctx.StartsWith($noticePrefix + 'hook timed out after 2 seconds') -and ($r.Seconds -lt 30) -and ($left.Count -eq 0)
        Assert-Case "$tag hook-timeout" $ok ("exit $($r.ExitCode), took $([math]::Round($r.Seconds, 1)) s, got [$ctx], processes left=$($left.Count) [$(($left | ForEach-Object { $_.ProcessId }) -join ',')], stderr: $($r.Err)")
        foreach ($p in $left) { try { Stop-Process -Id $p.ProcessId -Force } catch { } }

        # --- hook never reads a large stdin: still returns at the timeout -------
        $bigInput = '{"pad": "' + ('a' * (4 * 1024 * 1024)) + '"}'
        $l = New-Sandbox -HookSource "import time`ntime.sleep(40)"
        $sbDir = $script:lastSandbox
        $r = Invoke-Launcher -Engine $eng.Exe -LauncherPath $l -Stdin ($utf8.GetBytes($bigInput)) -EnvVars @{ AGENT_PLAYBOOK_HOOK_TIMEOUT_MS = '2000' }
        $ctx = Get-Context $r.Out
        $left = @(Wait-NoSandboxPythons $sbDir)
        $ok = ($r.ExitCode -eq 0) -and ($null -ne $ctx) -and $ctx.StartsWith($noticePrefix + 'hook timed out after 2 seconds') -and ($r.Seconds -lt 15) -and ($left.Count -eq 0)
        Assert-Case "$tag hook-never-reads-stdin" $ok ("exit $($r.ExitCode), took $([math]::Round($r.Seconds, 1)) s (limit 15), got [$ctx], processes left=$($left.Count), stderr: $($r.Err)")
        foreach ($p in $left) { try { Stop-Process -Id $p.ProcessId -Force } catch { } }

        # --- hook exits at once while 4 MB of stdin is still being written ------
        # The write hits a broken pipe; the launcher ignores it and the exit code decides.
        $l = New-Sandbox -HookSource "import sys`nsys.exit(3)"
        $r = Invoke-Launcher -Engine $eng.Exe -LauncherPath $l -Stdin ($utf8.GetBytes($bigInput)) -EnvVars @{ AGENT_PLAYBOOK_HOOK_TIMEOUT_MS = '10000' }
        $ctx = Get-Context $r.Out
        $ok = ($r.ExitCode -eq 0) -and (Test-NoBom $r.Out) -and ($null -ne $ctx) -and $ctx.StartsWith($noticePrefix + 'hook failed (exit 3)') -and ($r.Seconds -lt 9)
        Assert-Case "$tag hook-exits-early-big-stdin" $ok ("exit $($r.ExitCode), took $([math]::Round($r.Seconds, 1)) s (limit 9), got [$ctx], stderr: $($r.Err)")

        # --- the parent keeps the launcher's stdin open and never closes it -----
        # The input is written but the pipe stays open: an unbounded read of the launcher's
        # own stdin would hang past the cap (the case would then be killed at 30 s, -999).
        $l = New-Sandbox -HookSource $echoHook
        $sbDir = $script:lastSandbox
        $r = Invoke-Launcher -Engine $eng.Exe -LauncherPath $l -Stdin ($utf8.GetBytes($echoInput)) -EnvVars @{ AGENT_PLAYBOOK_HOOK_TIMEOUT_MS = '2000' } -KeepStdinOpen -WaitMs 30000
        $ctx = Get-Context $r.Out
        $left = @(Wait-NoSandboxPythons $sbDir)
        $ok = ($r.ExitCode -eq 0) -and (Test-NoBom $r.Out) -and ($null -ne $ctx) -and $ctx.StartsWith($noticePrefix + 'hook timed out after 2 seconds') -and ($r.Seconds -ge 1.5) -and ($r.Seconds -lt 15) -and ($left.Count -eq 0)
        Assert-Case "$tag launcher-stdin-never-closed" $ok ("exit $($r.ExitCode) (-999 = still running at 30 s), took $([math]::Round($r.Seconds, 1)) s (want 1.5 to 15), got [$ctx], processes left=$($left.Count), stderr: $($r.Err)")
        foreach ($p in $left) { try { Stop-Process -Id $p.ProcessId -Force } catch { } }

        # --- launcher reached through a relative file symlink (as deployed) -----
        $l = New-Sandbox -HookSource $echoHook
        $sbDir = $script:lastSandbox
        $deploy = Join-Path $sbDir 'deploy'
        New-Item -ItemType Directory -Force -Path $deploy | Out-Null
        $link = Join-Path $deploy 'memory-load-hook.ps1'
        if (New-Link -Link $link -Target '..\providers\claude\memory-load-hook.ps1') {
            $r = Invoke-Launcher -Engine $eng.Exe -LauncherPath $link -Stdin ($utf8.GetBytes($echoInput))
            $ctx = Get-Context $r.Out
            $ok = ($r.ExitCode -eq 0) -and (Test-NoBom $r.Out) -and ($null -ne $ctx) -and ($ctx -ceq $echoInput)
            Assert-Case "$tag relative-symlink-launcher" $ok ("exit $($r.ExitCode), context=[$ctx], stderr: $($r.Err)")
        } else { Skip-Case "$tag relative-symlink-launcher" 'could not create a symlink (needs Developer Mode or elevation)' }

        # --- launcher reached through a symlinked parent directory --------------
        $l = New-Sandbox -HookSource $echoHook
        $sbDir = $script:lastSandbox
        $dirLink = Join-Path $sbDir 'dl'
        if (New-Link -Link $dirLink -Target 'providers\claude' -Dir $true) {
            $r = Invoke-Launcher -Engine $eng.Exe -LauncherPath (Join-Path $dirLink 'memory-load-hook.ps1') -Stdin ($utf8.GetBytes($echoInput))
            $ctx = Get-Context $r.Out
            $ok = ($r.ExitCode -eq 0) -and (Test-NoBom $r.Out) -and ($null -ne $ctx) -and ($ctx -ceq $echoInput)
            Assert-Case "$tag symlinked-parent-dir" $ok ("exit $($r.ExitCode), context=[$ctx], stderr: $($r.Err)")
        } else { Skip-Case "$tag symlinked-parent-dir" 'could not create a directory symlink (needs Developer Mode or elevation)' }
    }
} finally {
    # A directory link must be removed as a link: Remove-Item -Recurse on it can follow it.
    if (Test-Path -LiteralPath $tmpRoot) {
        Get-ChildItem -LiteralPath $tmpRoot -Recurse -Force -Directory -ErrorAction SilentlyContinue |
            Where-Object { [string]$_.LinkType -eq 'SymbolicLink' } |
            ForEach-Object { try { [IO.Directory]::Delete($_.FullName) } catch { } }
        Remove-Item -LiteralPath $tmpRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}

Write-Host "launcher-test: pass=$passes fail=$failures skip=$skips engines=$(($engines | ForEach-Object { $_.Name }) -join ',') launcher=$Launcher"
if ($failures -gt 0) { Write-Host 'FAIL: a launcher case failed. Fix memory-load-hook.ps1 (the case lines above name the difference); do not edit the expected values.'; exit 1 }
exit 0
