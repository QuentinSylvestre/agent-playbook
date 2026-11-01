param([switch] $Worker)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-KiroTabTitle {
    param(
        [Parameter(Mandatory)] $Event,
        [Parameter(Mandatory)] [string] $KiroHome
    )

    $sessionId = [string] $Event.session_id
    $cwd = [string] $Event.cwd
    if ($sessionId -notmatch '^sess_[0-9a-fA-F-]{36}$' -or -not [IO.Path]::IsPathRooted($cwd)) {
        return $null
    }

    $workspace = [IO.Path]::GetFileName($cwd.TrimEnd('\', '/'))
    if (-not $workspace) { return $null }

    $normalizedCwd = $cwd.Replace('\', '/').ToLowerInvariant()
    $sha256 = [Security.Cryptography.SHA256]::Create()
    try {
        $hashBytes = $sha256.ComputeHash([Text.Encoding]::UTF8.GetBytes($normalizedCwd))
    } finally {
        $sha256.Dispose()
    }
    $workspaceHash = [BitConverter]::ToString($hashBytes).Replace('-', '').ToLowerInvariant().Substring(0, 16)
    $sessionFile = Join-Path (Join-Path (Join-Path $KiroHome 'sessions') $workspaceHash) (Join-Path $sessionId 'session.json')
    if (-not (Test-Path -LiteralPath $sessionFile -PathType Leaf)) { return $null }

    $metadata = Get-Content -LiteralPath $sessionFile -Raw | ConvertFrom-Json
    $title = [string] $metadata.title
    if (-not $title -or $title -eq $sessionId -or $title -eq 'New Session') { return $null }

    $safeWorkspace = [regex]::Replace($workspace, '[\x00-\x1f\x7f]', '').Trim()
    $safeTitle = [regex]::Replace($title, '[\x00-\x1f\x7f]', '').Trim()
    if (-not $safeWorkspace -or -not $safeTitle) { return $null }
    return "kiro-cli - $safeWorkspace - $safeTitle"
}

function Initialize-KiroTabConsole {
    if (-not ('KiroTabConsole' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;

public static class KiroTabConsole {
    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern bool FreeConsole();

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern bool AttachConsole(uint processId);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern SafeFileHandle CreateFile(string name, uint access, uint share,
        IntPtr security, uint creation, uint flags, IntPtr templateFile);

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern bool WriteFile(SafeFileHandle handle, byte[] buffer, uint count,
        out uint written, IntPtr overlapped);
}
'@
    }
}

function Write-KiroTabTitle {
    param([Parameter(Mandatory)] [string] $Title)

    Initialize-KiroTabConsole

    $handle = [KiroTabConsole]::CreateFile('\\.\CONOUT$', 0x40000000, 3, [IntPtr]::Zero, 3, 0, [IntPtr]::Zero)
    if ($handle.IsInvalid) {
        $errorCode = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
        $handle.Dispose()
        throw "CONOUT unavailable (Win32 $errorCode)"
    }

    try {
        $sequence = ([string] [char] 27) + ']0;' + $Title + ([string] [char] 7)
        $bytes = [Text.Encoding]::UTF8.GetBytes($sequence)
        $written = [uint32] 0
        $ok = [KiroTabConsole]::WriteFile($handle, $bytes, [uint32] $bytes.Length, [ref] $written, [IntPtr]::Zero)
        if (-not $ok -or $written -ne $bytes.Length) {
            $errorCode = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
            throw "Console title write failed (Win32 $errorCode)"
        }
    } finally {
        $handle.Dispose()
    }
}

function Get-KiroTerminalProcessId {
    $processes = Get-CimInstance Win32_Process -Property Name, ProcessId, ParentProcessId -ErrorAction Stop
    $byId = @{}
    foreach ($process in $processes) { $byId[[uint32] $process.ProcessId] = $process }

    $currentId = [uint32] $PID
    $kiroId = [uint32] 0
    for ($depth = 0; $depth -lt 16 -and $currentId; $depth++) {
        if (-not $byId.ContainsKey($currentId)) { break }
        $process = $byId[$currentId]
        $name = [string] $process.Name
        if ($name -eq 'kiro-cli.exe') {
            $kiroId = $currentId
        } elseif ($kiroId -and $name -in @('pwsh.exe', 'powershell.exe', 'cmd.exe')) {
            return $currentId
        }
        $currentId = [uint32] $process.ParentProcessId
    }
    if ($kiroId) { return $kiroId }
    throw 'Kiro terminal process not found in hook ancestry'
}

function Start-KiroTabTitleWorker {
    param(
        [Parameter(Mandatory)] [string] $Title,
        [Parameter(Mandatory)] [uint32] $TerminalProcessId
    )

    $processInfo = New-Object Diagnostics.ProcessStartInfo
    $executableName = if ($PSVersionTable.PSVersion.Major -ge 7) { 'pwsh.exe' } else { 'powershell.exe' }
    $processInfo.FileName = Join-Path $PSHOME $executableName
    $processInfo.Arguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + $PSCommandPath + '" -Worker'
    $processInfo.UseShellExecute = $false
    $processInfo.CreateNoWindow = $false
    $processInfo.WindowStyle = [Diagnostics.ProcessWindowStyle]::Hidden
    $processInfo.RedirectStandardInput = $true
    $processInfo.RedirectStandardOutput = $true
    $processInfo.RedirectStandardError = $true
    $process = [Diagnostics.Process]::Start($processInfo)
    if (-not $process) { throw 'Could not start tab title worker' }
    try {
        $encodedTitle = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($Title))
        $process.StandardInput.WriteLine($TerminalProcessId)
        $process.StandardInput.WriteLine($encodedTitle)
        $process.StandardInput.Close()
    } finally {
        $process.Dispose()
    }
}

function Invoke-KiroTabTitleWorker {
    $terminalProcessId = [uint32] [Console]::In.ReadLine()
    $encodedTitle = [Console]::In.ReadLine()
    if (-not $terminalProcessId -or -not $encodedTitle) { return }
    $title = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($encodedTitle))
    Start-Sleep -Milliseconds 900
    Initialize-KiroTabConsole
    [void] [KiroTabConsole]::FreeConsole()
    if (-not [KiroTabConsole]::AttachConsole($terminalProcessId)) {
        $errorCode = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
        throw "Could not attach to terminal console (Win32 $errorCode)"
    }
    Write-KiroTabTitle -Title $title
}

function Invoke-KiroTabTitle {
    if (-not $env:WT_SESSION -or -not $env:KIRO_TUI_READY_FILE) { return }

    try {
        $eventText = [Console]::In.ReadToEnd()
        if (-not $eventText) { return }
        $event = $eventText | ConvertFrom-Json
        if ([string] $event.hook_event_name -eq 'userPromptSubmit') {
            [Console]::Out.WriteLine('Kiro CLI TUI runtime: KIRO_TUI_READY_FILE is set. On the first response of a new session, call update_session_information with a task-focused title of at most 50 characters. Machine ID: acp-client does not mean this is an ACP session. On later responses, change the title only when asked.')
        }
        $kiroHome = if ($env:KIRO_HOME) { $env:KIRO_HOME } else { Join-Path $env:USERPROFILE '.kiro' }
        $title = Get-KiroTabTitle -Event $event -KiroHome $kiroHome
        if ($title) {
            $terminalProcessId = Get-KiroTerminalProcessId
            Start-KiroTabTitleWorker -Title $title -TerminalProcessId $terminalProcessId
        }
    } catch {
        [Console]::Error.WriteLine("Tab title hook failed: $($_.Exception.Message)")
    }
}

if ($MyInvocation.InvocationName -ne '.') {
    if ($Worker) { Invoke-KiroTabTitleWorker } else { Invoke-KiroTabTitle }
}
