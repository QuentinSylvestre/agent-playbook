# Claude Code provider config

Deployables specific to Claude Code. `setup.ps1` / `setup.sh` symlink everything
here per the rows in `inventory.tsv` with mode `claude`.

Topic memory: `memory/topics/claude-code.md` — read it when changing Claude Code's
MCP servers, hooks, permission modes or `settings.json`.

On-demand reference (not deployed): `providers/claude/reference/claude-code-local-data.md`
documents Claude Code's session store, hook payloads and status state machine for
`/qdream` sweeps and recovery work.

## Claude Code reads CLAUDE.md, not AGENTS.md

Project-level auto-discovery covers `CLAUDE.md`, `CLAUDE.local.md`, and
`.claude/rules/*.md` — **not** `AGENTS.md`. There is no setting to change it and
it does not vary between the CLI, desktop app, and IDE extensions
([docs](https://code.claude.com/docs/en/memory.md#agentsmd)).

So a repo whose project governance lives in `AGENTS.md` needs a `CLAUDE.md` that
imports it (`@AGENTS.md` on its own line), or that governance is silently absent
from every Claude Code session in the repo — no warning, no error. This repo's
root `CLAUDE.md` is exactly that bridge and holds no rules of its own.

Kiro has the same gap and a different fix: it needs a `.kiro/steering/` reference
with `inclusion: always`, written by `/qwire-governance`. Codex and Cursor read
`AGENTS.md` directly.

## Store repo on a new machine

Workspace memory, plans and artifacts, and your user memory (`user/memory/`), live in
a private git repo outside this one: the store repo, at the `stores=` path of
`~/.agent-playbook/config` (default `~/.agent-playbook/stores`). Setup offers to clone
yours from a URL or create a fresh one, and records the URL as `stores_url=`. Without
it the playbook's store resolver returns status `failed` with the message
"store repo missing — clone it (see providers/claude/README.md)". To do it by hand:

```
git clone <your store repo URL> ~/.agent-playbook/stores
```

then re-run setup, which links the config repo's `memory` to `user/memory/`.

`/qconfig-sync` pulls, lists pending changes and pushes it. If the folder is absent,
`/qconfig-sync` skips the store step and prints this clone command.

## Manual settings.json entries required

`~/.claude/settings.json` is deliberately **not** tracked by this repo. Claude Code
writes to it itself whenever you change model, theme, effort, TUI mode, or approve
a permission prompt, so tracking it would dirty the working tree on every
interactive toggle and would carry machine-local paths between machines.

The consequence: the scripts below are symlinked automatically, but the
`settings.json` entries that *point at* them are not. On a fresh environment they
sit inert until you add the stanzas by hand, and `verify-deployment` will still
report a clean result — it checks symlink targets, not `settings.json`.

Add all four stanzas after running setup on a new machine.

### statusLine

Renders the custom status line from `statusline-command.sh`. Requires `jq` on PATH.

```json
{
  "statusLine": {
    "type": "command",
    "command": "bash \"C:/Users/<you>/.claude/statusline-command.sh\""
  }
}
```

On macOS/Linux the command is `bash ~/.claude/statusline-command.sh`. Use the
explicit absolute path on Windows: the command may be run by a shell that does
not expand `~`.

The script also keeps the latest payload where PowerAtlas (the maintainer's desktop dashboard, optional;
nothing here needs it) can read it. Claude Code
hands its live 5-hour and weekly percentages (`rate_limits`) only to the statusline command, so the
script writes them to `%LOCALAPPDATA%\power-atlas\claude-statusline.json` for the dashboard's Quota
strip. It does so only when that folder exists (PowerAtlas has run on the machine), only for a payload
that carries `rate_limits`, and without starting a process. PowerAtlas never edits `settings.json` and
never reads the credentials file. The block is the same text as `STATUSLINE_SNIPPET` in PowerAtlas's
`src/power_atlas/quota.py`; change them together.

### Notification hooks

Plays a sound from `notify-command.ps1` when Claude needs attention, so you can
leave the terminal while it works. Two matchers, two different sounds — see the
script header for the sound map and the rationale.

```json
{
  "hooks": {
    "Notification": [
      {
        "matcher": "permission_prompt",
        "hooks": [
          {
            "type": "command",
            "command": "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"C:/Users/<you>/.claude/notify-command.ps1\" -Event permission"
          }
        ]
      },
      {
        "matcher": "idle_prompt",
        "hooks": [
          {
            "type": "command",
            "command": "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"C:/Users/<you>/.claude/notify-command.ps1\" -Event idle"
          }
        ]
      }
    ]
  }
}
```

On macOS/Linux, invoke the same script with `pwsh -NoProfile -File
~/.claude/notify-command.ps1 -Event permission`; it branches on platform and
plays the native equivalent. This path is unverified — only the Windows branch
has been exercised.

Do not also set `preferredNotifChannel` to `"terminal_bell"`. Hooks run alongside
the built-in notification channel rather than replacing it, so you would get the
terminal bell *and* the sound on every event.

### Stop hook

Plays the `done` sound (`chimes.wav`) when Claude finishes a turn. `Stop` has no
`matcher` concept — it fires unconditionally on every turn, unlike `Notification`
which branches on `permission_prompt`/`idle_prompt`. This is a sibling key under
the same top-level `"hooks"` object above, not a separate object — merge it in
rather than overwriting the `Notification` stanza.

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"C:/Users/<you>/.claude/notify-command.ps1\" -Event done"
          }
        ]
      }
    ]
  }
}
```

Since `idle_prompt` also fires at the end of every turn (see the script header),
this stacks a second sound (`chimes.wav` then `ding.wav`) on every response, not
just an occasional idle nudge. Unverified which is more annoying in practice —
drop the `idle_prompt` matcher if the double sound gets old.

Claude Code snapshots hooks at session start, so restart after editing, then run
`/hooks` and select `Notification`/`Stop` to confirm entries registered.

### SessionStart memory hook

`memory-load-hook.py` gives every session a memory floor without relying on the
agent to read files. At each start, resume, `/clear` and compaction it injects:

- a heading index of user `memory/MEMORY.md` and `memory/HIGHER_ORDER.md`, with
  ⚠ on an entry whose `Source` line cites a file that changed in git after its
  `Verified` date (a path named only in prose is not checked);
- the `## Topics` rows and each tier's absolute path;
- the project memory tier in full when it fits, otherwise its heading index.

The injection is capped at 9,500 characters; Claude Code saves larger hook
output to a file instead of injecting it. A heading index is not delivery, so
the agent still reads the user and higher-order files
(`shared/AGENTS.md § Memory Management`, Read-time behavior). The hook
resolves the project tier through the store resolver, so it also works for a
project with no `CLAUDE.md` and for a session opened in a subfolder. It writes
nothing, and on any error it injects a one-line notice and exits 0. The script
header has the full contract. Its fixtures under
`providers/claude/fixtures/memory-load-hook/` run with
`.venv-agent-playbook\Scripts\python.exe -I providers\claude\memory-load-hook.py --selftest`.

#### Interpreter and launcher

Every playbook Python script runs one interpreter: `.venv-agent-playbook` at the
config repo root (gitignored, stdlib only). `setup.ps1` creates it from the system
Python 3.8+ (`py -3`, then `python`) and stops with a message when it finds none;
it never installs Python. Running `setup.ps1` again leaves a working venv alone and
rebuilds a broken one. A missing venv is reported as "guard did not run", never
replaced by a Python found on `PATH`.

The `settings.json` entry therefore runs the launcher `memory-load-hook.ps1`, not
`python.exe`. The launcher runs the venv interpreter (with `-I`) on `memory-load-hook.py`,
passes the hook's stdin and stdout through byte for byte, and always exits 0. When
the venv is missing, or the hook fails, times out (15 seconds) or prints something
that is not SessionStart JSON, it prints a one-line `additionalContext` notice
instead, for example `Playbook memory hook did not run: venv missing — run
setup.ps1`. A failing hook never blocks a session, but its stderr never reaches
the model (measured on Claude Code 2.1.302 in `-p` mode); the notice does. The
15 seconds cover the whole run, including the launcher's own read of its stdin
(a parent that never closes the pipe gets the timeout notice and the hook is not
started) and the write of the hook's stdin, and the hook is killed with its child
processes at the cap. The launcher's cap is the only
cap: the `settings.json` entry below sets no `timeout`, and hooks block session
start one after another, so a hung hook costs at most those 15 seconds (a normal
run takes about 1.2 seconds). The launcher follows every symlink on its own path
into the config repo to find the venv; when it cannot find the repo it prints a
separate notice, `launcher could not locate the agent-playbook repo`, instead of
reporting a missing venv. A deployed symlink whose target is gone (a dangling
link) cannot be reported at all: PowerShell fails before the launcher starts, so
no notice is printed. Run `setup.ps1` to restore the link.
`providers/claude/memory-load-hook.launcher-test.ps1` tests it under Windows
PowerShell 5.1 and PowerShell 7 (exit 0 pass, 1 fail, 2 could not run).

Use the same quoted `command` string as the notification hooks above:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup|resume|clear|compact",
        "hooks": [
          {
            "type": "command",
            "command": "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"C:/Users/<you>/.claude/memory-load-hook.ps1\""
          }
        ]
      }
    ]
  }
}
```

An older entry that runs `python.exe` on `memory-load-hook.py` works until the venv
self-check lands, but it has no launcher notice and no venv: switch to the form
above (a manual step, since `settings.json` is not tracked).

Linux and macOS are unsupported for the venv rule: `setup.sh` has no venv step
yet, and the launcher needs PowerShell. A plain `python3` `command` + `args` entry
on the absolute path of `memory-load-hook.py` (`args` runs no shell, so `~` is not
expanded) still runs the hook there, outside the venv rule and without the
notice.

`SessionStart` is another sibling key under the same top-level `"hooks"`
object; merge it in. The four matchers cover every way a session's context
starts empty. After restarting, run `/hooks`, select `SessionStart` and confirm
the entry is listed. Then open a new session in a project with memory and ask
for one of its memory entry headings; the agent should quote it without reading
a file.

## Why not automate this

Merging a tracked fragment into the live `settings.json` at deploy time was
considered and rejected: it needs an idempotent JSON deep-merge implemented twice
(`setup.ps1` and `setup.sh`), a matching kind in `verify-deployment.py`,
and a `test-parity.sh` guard — substantial machinery to save a one-time paste on
the rare occasion a machine is rebuilt. Revisit if the number of manual stanzas
grows well beyond the four here.
