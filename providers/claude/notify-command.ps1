#requires -Version 5.1
<#
.SYNOPSIS
  Claude Code Notification-hook sound player.

.DESCRIPTION
  Plays a short sound so you can leave the terminal while Claude works.
  Wired up as a `Notification` hook in ~/.claude/settings.json, one entry per
  matcher, so different events get different sounds:

      "hooks": {
        "Notification": [
          { "matcher": "permission_prompt",
            "hooks": [{ "type": "command",
              "command": "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"C:/Users/<you>/.claude/notify-command.ps1\" -Event permission" }] },
          { "matcher": "idle_prompt",
            "hooks": [{ "type": "command",
              "command": "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"C:/Users/<you>/.claude/notify-command.ps1\" -Event idle" }] }
        ]
      }

  Claude Code pipes the hook's JSON payload on stdin. We ignore it -- the
  matcher already tells us which event fired, which is all the sound depends
  on -- but we must not leave stdin unread on a blocking pipe, so the caller
  is expected to use -File (Claude Code closes stdin for us).

  Deployed by setup.ps1/setup.sh as a symlink at ~/.claude/notify-command.ps1
  (see inventory.tsv). Edit this file in the repo, never the deployed link.

.NOTES
  Windows Terminal, VS Code, and Warp are NOT among the terminals Claude Code
  sends a native desktop notification to (only Ghostty, Kitty, iTerm2 are), so
  on Windows a hook like this is the only way to get an audible cue short of
  setting preferredNotifChannel to "terminal_bell".
#>
[CmdletBinding()]
param(
    # Which cue to play. Maps to a Notification matcher, not to a file name, so
    # the sound choice below can change without touching settings.json.
    [ValidateSet('permission', 'idle', 'done', 'test')]
    [string]$Event = 'permission'
)

# --- Sound map -------------------------------------------------------------
# Keep `idle` SHORT. idle_prompt fires at the end of every single turn, so a
# long or celebratory clip (tada.wav) becomes intolerable within an hour.
# `permission` is rarer and genuinely blocking, so it gets the distinctive one.
$WindowsSounds = @{
    permission = 'C:\Windows\Media\Windows Notify System Generic.wav'
    idle       = 'C:\Windows\Media\ding.wav'
    done       = 'C:\Windows\Media\chimes.wav'
}

# macOS/Linux equivalents, so the one deployed file works wherever the repo is
# checked out. Windows is the only platform verified in this setup.
$MacSounds = @{
    permission = '/System/Library/Sounds/Glass.aiff'
    idle       = '/System/Library/Sounds/Pop.aiff'
    done       = '/System/Library/Sounds/Hero.aiff'
}

if ($Event -eq 'test') { $Event = 'permission' }

# --- Play ------------------------------------------------------------------
# Every failure path is swallowed. A hook that throws writes noise into the
# transcript on every turn, and a missing sound file is never worth that.
try {
    if ($IsMacOS) {
        $snd = $MacSounds[$Event]
        if (Test-Path -LiteralPath $snd) { & afplay $snd }
    }
    elseif ($IsLinux) {
        # No canonical system sound path on Linux; use the freedesktop event
        # sounds if a player is present, otherwise fall through to the bell.
        $player = Get-Command paplay, aplay, canberra-gtk-play -ErrorAction SilentlyContinue |
                  Select-Object -First 1
        $snd = "/usr/share/sounds/freedesktop/stereo/$(
            if ($Event -eq 'permission') { 'dialog-warning' } else { 'complete' }).oga"
        if ($player -and (Test-Path -LiteralPath $snd)) { & $player.Source $snd }
        else { [Console]::Out.Write("`a") }
    }
    else {
        # Windows. PlaySync, not Play: this process exits the instant the
        # script ends, and an async Play() is cut off before it makes a sound.
        $snd = $WindowsSounds[$Event]
        if (Test-Path -LiteralPath $snd) {
            (New-Object System.Media.SoundPlayer $snd).PlaySync()
        } else {
            [Console]::Beep(880, 180)   # wav missing (trimmed Windows install)
        }
    }
}
catch {
    # Last resort: the console bell needs no assemblies and no audio device.
    try { [Console]::Out.Write("`a") } catch { }
}

exit 0
