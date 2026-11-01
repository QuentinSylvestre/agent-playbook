# Kiro provider config

Deployables specific to Kiro. `setup.ps1` / `setup.sh` symlink everything
here per the rows in `inventory.tsv` with mode `kiro`, on every platform
(Windows copy mode was retired 2026-09-20; `setup.ps1` needs Developer Mode
or an elevated shell to link). Overlay-bearing skills are the one exception:
they deploy as generated `shared + overlay` copies. See
`providers/kiro/steering/kiro-guidelines.md § Symlinks and Folder Structure
in `.kiro/``.

On-demand reference material (never deployed) lives in `providers/kiro/reference/`
and is indexed from `memory/topics/kiro-cli.md`.

## Manual hooks entries required

`~/.kiro/hooks/` is deliberately **not** tracked by this repo, for the same
reason `~/.claude/settings.json` isn't (see `providers/claude/README.md`):
the hook's `command` field embeds an absolute, user-specific path, so
committing a literal deployed copy would carry one machine's path to every
machine. Create the file by hand after running setup on a new machine.

### Stop hook -- kiro-cli v3 only

Plays the `done` sound by calling the same `notify-command.ps1` that Claude
Code's `Stop` hook uses (`providers/claude/notify-command.ps1`, deployed to
`~/.claude/notify-command.ps1`) -- deliberately shared across both harnesses
rather than duplicated, since the script itself has no Claude-specific
logic.

**Confirmed working on kiro-cli v3**, via `~/.kiro/logs/<session>/kiro.log`:
`[KiroAgent] v2 hooks loaded 1 standalone hooks from .kiro/hooks/` at session
start, and one `ContextualHookInvoked` line per turn. (That log line's "v2"
refers to Kiro's internal hooks-schema/engine version, not the kiro-cli
product version -- coincidental naming, confirmed against a v3 CLI session.)

A hook placed at the user-global `~/.kiro/hooks/` path merges with any
project-local `<project>/.kiro/hooks/` -- confirmed by testing both a
project-local-only file (worked) and both scopes populated with the same
hook simultaneously (fired twice, once per registration). The global path
below needs no per-project file.

**Untested on kiro-cli v2** -- the hook did not fire in testing (unclear
whether v2 lacks the feature or has a different loader). **Untested on Kiro
IDE.**

Create `~/.kiro/hooks/stop-sound.json` (create the `hooks/` directory if it
doesn't already exist):

```json
{
  "version": "v1",
  "hooks": [
    {
      "name": "stop-sound",
      "trigger": "Stop",
      "action": {
        "type": "command",
        "command": "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"C:/Users/<you>/.claude/notify-command.ps1\" -Event done"
      }
    }
  ]
}
```

Hooks load once at session start ("hooks load at session start" per
`kiro.log`). After creating or editing this file, fully exit `kiro-cli` and
relaunch it -- a new message in an already-running session will not pick up
the change.

### Session tab title hook -- Windows Terminal and kiro-cli v3

The agent sets the saved session title with `update_session_information`.
This hook displays that same title as `kiro-cli - <workspace> - <title>` in
the Windows Terminal tab. `UserPromptSubmit` restores an existing title on
resume; `Stop` applies a title chosen or changed during the agent's turn.

Create `~/.kiro/hooks/session-tab-title.json` with the absolute path to this
repo substituted for `<repo>` in both commands:

```json
{
  "version": "v1",
  "hooks": [
    {
      "name": "restore-session-tab-title",
      "trigger": "UserPromptSubmit",
      "action": {
        "type": "command",
        "command": "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"<repo>/providers/kiro/tab-title.ps1\""
      }
    },
    {
      "name": "apply-session-tab-title",
      "trigger": "Stop",
      "action": {
        "type": "command",
        "command": "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"<repo>/providers/kiro/tab-title.ps1\""
      }
    }
  ]
}
```

The script requires an interactive Kiro TUI inside Windows Terminal. It reads
the v3 `session.json` named by the hook event, strips control characters
from the title, and writes the terminal control sequence to `CONOUT$`.
On `UserPromptSubmit`, it also sends a short TUI runtime and title-rule
reminder to the agent through hook stdout. The `Stop` hook stays silent.
Keep `chat.terminalTitle` off so Kiro does not overwrite the convention.
Fully exit and relaunch Kiro after changing the hook file or script.
