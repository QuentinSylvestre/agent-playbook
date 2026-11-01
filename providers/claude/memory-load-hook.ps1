# Launcher for the Claude Code SessionStart memory hook (memory-load-hook.py).
#
# Runs <config-repo>\.venv-agent-playbook\Scripts\python.exe on memory-load-hook.py,
# passes the hook's stdin through unchanged and returns the hook's stdout unchanged.
# It ALWAYS exits 0. When the venv interpreter is missing, fails, times out or
# prints something that is not SessionStart hook JSON, it prints one hook JSON
# object whose additionalContext is a one-line notice instead. Reason (measured on
# Claude Code 2.1.302, `claude -p`): a failing hook never blocks the session, but
# its stderr is invisible to the model; a hook's stdout additionalContext is seen.
# The notice is therefore the only way the agent learns the memory floor is absent.
#
# There is no fallback to a Python on PATH: a missing venv is reported, not hidden.
#
# settings.json command (providers/claude/README.md, "SessionStart memory hook"):
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:/Users/<you>/.claude/memory-load-hook.ps1"
#
# The launcher's own cap is the only cap: AGENT_PLAYBOOK_HOOK_TIMEOUT_MS (default 15000)
# bounds the whole run: the launcher's own read of its stdin (a parent that never
# closes the pipe gets the timeout notice, and the hook is not started), the write of
# the hook's stdin and the hook itself. A hook that is still running at the cap is
# killed together with its child processes. Hooks block session start serially, so a
# hang costs at most this cap.
# Kept ASCII-only: Windows PowerShell 5.1 reads a BOM-less file as ANSI.

$ErrorActionPreference = 'Stop'

function Write-Stdout {
    param([byte[]]$Bytes)
    $out = [Console]::OpenStandardOutput()
    $out.Write($Bytes, 0, $Bytes.Length)
    $out.Flush()
}

function Write-Notice {
    param([string]$Reason)
    $text = 'Playbook memory hook did not run: ' + $Reason
    $obj = @{ hookSpecificOutput = @{ hookEventName = 'SessionStart'; additionalContext = $text } }
    $json = ConvertTo-Json -InputObject $obj -Compress -Depth 4
    Write-Stdout ((New-Object System.Text.UTF8Encoding($false)).GetBytes($json + "`n"))
}

# Follow symlinks and junctions in every component of the path: the deployed launcher
# is a symlink into the config repo, and a parent directory may be a link too.
function Resolve-RealPath {
    param([string]$Path)
    for ($i = 0; $i -lt 16; $i++) {
        try {
            $full = [IO.Path]::GetFullPath($Path)
            $root = [IO.Path]::GetPathRoot($full)
            $parts = @($full.Substring($root.Length).Split([char[]]@([char]92, [char]47),[StringSplitOptions]::RemoveEmptyEntries))
            $cur = $root
            $moved = $false
            for ($j = 0; $j -lt $parts.Count; $j++) {
                $next = Join-Path $cur $parts[$j]
                $item = Get-Item -LiteralPath $next -Force -ErrorAction SilentlyContinue
                if ($item -and (@('SymbolicLink', 'Junction') -contains [string]$item.LinkType)) {
                    $target = ([string]@($item.Target)[0]) -replace '^\\\\\?\\', ''
                    if (-not [IO.Path]::IsPathRooted($target)) { $target = Join-Path $cur $target }
                    $tail = @()
                    if ($j + 1 -lt $parts.Count) { $tail = @($parts[($j + 1)..($parts.Count - 1)]) }
                    $Path = $target
                    foreach ($t in $tail) { $Path = Join-Path $Path $t }
                    $moved = $true
                    break
                }
                $cur = $next
            }
            if (-not $moved) { return $full }
        } catch { return $Path }
    }
    return $Path
}

# Kill a process and its children (taskkill /T); fall back to Kill() on the process alone.
# The venv python.exe is a redirector whose job object already ends the base interpreter it
# starts when the redirector is killed (measured: the no-leftover test passes without the
# taskkill line). The /T is belt-and-braces for grandchildren a hook itself starts, such as git.
function Stop-ProcessTree {
    param([System.Diagnostics.Process]$P)
    try { & (Join-Path (Join-Path $env:SystemRoot 'System32') 'taskkill.exe') /T /F /PID $P.Id 2>&1 | Out-Null } catch { }
    try { $P.Kill() } catch { }
}

$dash = [string][char]0x2014
$sect = [string][char]0xA7
$readYourself = "read the memory tiers yourself per shared/AGENTS.md $sect Read-time behavior."

try {
    $script = Resolve-RealPath $PSCommandPath
    $claudeDir = Split-Path -Parent $script
    $repo = Split-Path -Parent (Split-Path -Parent $claudeDir)
    $venvPython = Join-Path $repo '.venv-agent-playbook\Scripts\python.exe'
    $hook = Join-Path $claudeDir 'memory-load-hook.py'

    # The repo counts as located only when the resolved launcher sits at
    # <repo>\providers\claude\: a copy outside the repo, or a link the resolver
    # could not follow, must not be reported as a missing venv.
    $located = Test-Path -LiteralPath (Join-Path $claudeDir 'memory-load-hook.ps1') -PathType Leaf
    if ($located) {
        $located = ((Split-Path -Leaf $claudeDir) -eq 'claude') -and
                   ((Split-Path -Leaf (Split-Path -Parent $claudeDir)) -eq 'providers')
    }

    if (-not $located) {
        Write-Notice "launcher could not locate the agent-playbook repo (is memory-load-hook.ps1 a symlink into it?) $dash run setup.ps1"
    } elseif (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        Write-Notice "venv missing $dash run setup.ps1"
    } else {
        $timeoutMs = 15000
        $override = 0
        if ([int]::TryParse([string]$env:AGENT_PLAYBOOK_HOOK_TIMEOUT_MS, [ref]$override) -and $override -gt 0) {
            $timeoutMs = $override
        }

        # One clock for the whole run: reading our own stdin, writing the hook's stdin and
        # waiting for the hook all draw on the same cap.
        $clock = [System.Diagnostics.Stopwatch]::StartNew()

        # Raw bytes in, raw bytes out: no line splitting, no console code page. The read is
        # asynchronous and bounded by the cap: a parent that keeps the pipe open and never
        # closes it must not hang the launcher. On that timeout the hook is not started
        # (the cap is spent) and the timeout notice is printed, so the exit stays 0 and
        # stdout stays valid SessionStart JSON.
        $stdinBytes = New-Object byte[] 0
        $stdinTimedOut = $false
        if ([Console]::IsInputRedirected) {
            $buf = New-Object System.IO.MemoryStream
            $copyTask = [Console]::OpenStandardInput().CopyToAsync($buf)
            if ($copyTask.Wait($timeoutMs)) {
                $stdinBytes = $buf.ToArray()
            } else {
                $stdinTimedOut = $true
            }
        }

        if ($stdinTimedOut) {
            Write-Notice "hook timed out after $([int]($timeoutMs / 1000)) seconds (launcher stdin was never closed) $dash $readYourself"
        } else {
            $psi = New-Object System.Diagnostics.ProcessStartInfo
            $psi.FileName = $venvPython
            $psi.Arguments = '-I "' + $hook + '"'
            $psi.UseShellExecute = $false
            $psi.CreateNoWindow = $true
            $psi.RedirectStandardInput = $true
            $psi.RedirectStandardOutput = $true

            $proc = [System.Diagnostics.Process]::Start($psi)
            $outBuf = New-Object System.IO.MemoryStream
            $outTask = $proc.StandardOutput.BaseStream.CopyToAsync($outBuf)
            $timedOut = $false
            $stdinStream = $proc.StandardInput.BaseStream
            # The write is asynchronous and bounded by the same timeout: a hook that never
            # reads its stdin must not block the launcher on a full pipe. A failed write
            # (the hook exited before reading) is ignored; the exit code decides.
            try {
                $writeTask = $stdinStream.WriteAsync($stdinBytes, 0, $stdinBytes.Length)
                if (-not $writeTask.Wait([int][Math]::Max(0, $timeoutMs - $clock.ElapsedMilliseconds))) {
                    $timedOut = $true
                } else {
                    $flushTask = $stdinStream.FlushAsync()
                    if (-not $flushTask.Wait([int][Math]::Max(0, $timeoutMs - $clock.ElapsedMilliseconds))) {
                        $timedOut = $true
                    }
                }
            } catch {
                # The write or flush failed: the hook closed its stdin early.
            }
            if (-not $timedOut) {
                try { $proc.StandardInput.Close() } catch { }
                if (-not $proc.WaitForExit([int][Math]::Max(0, $timeoutMs - $clock.ElapsedMilliseconds))) {
                    $timedOut = $true
                }
            }

            if ($timedOut) {
                Stop-ProcessTree $proc
                Write-Notice "hook timed out after $([int]($timeoutMs / 1000)) seconds $dash $readYourself"
            } else {
                [void]$outTask.Wait(5000)
                $exitCode = $proc.ExitCode
                $outBytes = $outBuf.ToArray()
                $valid = $false
                if ($exitCode -eq 0 -and $outBytes.Length -gt 0) {
                    try {
                        $strict = New-Object System.Text.UTF8Encoding($false, $true)
                        $parsed = ConvertFrom-Json -InputObject $strict.GetString($outBytes)
                        $valid = ($parsed.hookSpecificOutput.hookEventName -eq 'SessionStart') -and
                                 ($parsed.hookSpecificOutput.additionalContext -is [string])
                    } catch { $valid = $false }
                }
                if ($valid) {
                    Write-Stdout $outBytes
                } elseif ($exitCode -ne 0) {
                    Write-Notice "hook failed (exit $exitCode) $dash run setup.ps1 if the venv is broken, otherwise $readYourself"
                } else {
                    Write-Notice "hook printed no valid SessionStart JSON $dash $readYourself"
                }
            }
        }
    }
} catch {
    $detail = ([string]$_.Exception.Message) -replace '\s+', ' '
    if ($detail.Length -gt 160) { $detail = $detail.Substring(0, 160) }
    try { Write-Notice ("launcher error ($($_.Exception.GetType().Name): $detail) $dash $readYourself") } catch { }
}
exit 0
