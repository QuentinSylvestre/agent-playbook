---
name: qmigrate-workspace
description: Move or rename a workspace folder (or a parent holding several) without losing agent history or playbook tracking. Copies the tree, rewrites the path-keyed stores of Claude Code, Codex, kiro-cli v3 and v2, Kiro IDE, Gemini, VS Code and PowerAtlas, the playbook's workspace store and dream state, rebuilds venvs, repairs git worktrees, symlinks and shortcuts, verifies, and archives the old tree. Windows only.
argument-hint: "<old-path> <new-path>"
---

# Migrate a workspace

## Your role

Move a folder so every agent still finds its sessions at the new path, and nothing is lost on the way. Behaviour that overrides your defaults:

- **First action: the read-only inventory** (`scripts/scan.py`), never a move. Do not `Move-Item`, do not move first and fix up later, and never leave a junction or symlink at the old path: the playbook does not follow reparse points when it keys a workspace (`shared/skills/qdream/memory-rules.md § Path normalization`), so a junction splits history into two workspaces.
- **Copy, rewrite, verify, and only then retire OLD.** Every step before the last is reversible; OLD is the rollback until the user has checked that sessions resume.
- **The cutover is the user's to run**, with every agent and editor closed, including you. Prepare it, dry-run it, hand it over. The one exception is agent-run mode (Step 4), and only when the user has authorized it in this session.

Scripts live in `<config-repo>/shared/skills/qmigrate-workspace/scripts/` (`<scripts>` below: resolve it to an absolute path; the user runs the cutover from another folder). Every script documents its usage in its header. The `.py` scripts run as `<python> <scripts>\<name>.py`, where `<python>` is `<config-repo>\.venv-agent-playbook\Scripts\python.exe -I` (`<config-repo>`: `shared/AGENTS.md § Config Repo Locations`), the playbook's one interpreter. It must be Python 3.11+ (`apply.py` imports `tomllib`). The `.ps1` scripts that run Python (`cutover.ps1`, `kiro-ide-migrate.ps1`) use the same venv. If the file is missing or fails to start, stop and tell the user "venv missing — run setup.ps1"; never use a Python from `PATH`. If it is older than 3.11, the user deletes the venv folder and runs `setup.ps1` with a 3.11+ system Python. `cutover.ps1` finds that venv itself from its own location and stops with the same message. Backups, logs, venv freezes and markers go to a work folder per OLD/NEW pair under `~/.agent-playbook/qmigrate-workspace/`, outside OneDrive.

**When NOT to use**: renaming files inside a repo (git handles it); a POSIX machine (not supported, see `## Limitations`); one agent's sessions only, with no folder move (resume them where they are).

## Process

### Step 1: Inventory and scope

1. Run `scan.py --old <OLD> --new <NEW>` in the background (minutes on large stores). Also list: real symlinks inside OLD (`Get-ChildItem -Recurse -Attributes ReparsePoint` with a `LinkType`), `pyvenv.cfg` files, git worktrees (`git worktree list` per repo), Startup and Desktop shortcuts, scheduled tasks and `Run` keys that name OLD, and processes whose command line names OLD.
2. If OLD is under OneDrive: count online-only files (attribute `0x400000`) per project, and note folders without `.git` — leaving the sync root deletes the cloud copy, and gitignored content has no other backup.
3. **Already moved?** If OLD is missing (or holds no file) and NEW holds the tree, something else did the move (OneDrive, Explorer). There is nothing to copy and nothing to compare with OLD: skip Step 2 and the venv freeze (`venvs.ps1 -Phase freeze` reads OLD; recreate venvs in NEW from their own requirements), run the rest, and use `-AlreadyMoved` in Step 4. Step 5.2 (compare with OLD) is skipped, and Step 6 shrinks to deleting the empty OLD tree if one is left, on the user's word (no `predelete`, no archive: nothing is left in OLD to lose). If OLD still holds files the move is unfinished: wait for it, and never run the cutover meanwhile.
4. Confirm OLD and NEW with the user, then ask, with these facts: must old sessions stay **resumable from NEW** (rewrite the stores) or only **not be destroyed** (nothing to rewrite)? Is losing the OneDrive copy of the non-git folders accepted?

### Step 2: Copy (agents may keep running)

1. Pilot one small folder: `robocopy <OLD>\<x> <NEW>\<x> /E /COPY:DAT /DCOPY:DAT /SL /R:2 /W:2 /MT:8`. Exit codes 0-7 are success. Check every file's SHA-256 (`verify.py copy`) — a size match proves nothing for a OneDrive stub, which reports its full length.
2. Copy the whole tree the same way, then `verify.py copy` at least on the projects that had online-only files. Leave OLD untouched.
3. Check free disk first: the copy plus targeted backups (about 1.7 GB for a 28 GB store set) must fit.

### Step 3: Prepare while agents run

1. `& <scripts>\venvs.ps1 -Phase freeze -Old <OLD> -New <NEW>`, then the same with `-Phase rebuild` (writes into NEW only). Invoke with `&`, never `pwsh -File`, which passes an array argument as one string.
2. Find project-local config that names OLD: `verify.py residue --old <OLD> --new <NEW>`. Each real config file goes to `apply.py --also <file>` in the dry run and to `cutover.ps1 -Also <file>,<file>` for the real run; leave caches, logs and archived plans.
3. Dry-run: `apply.py --old <OLD> --new <NEW> [--config-repo <checkout live after the move>] [--also <file>]` must end `No blockers.` A folder beside OLD whose name starts with OLD's name and a space (`Perso Old`) is a blocker: its paths would match too.
4. If the config repo itself moves: its location is the `root=` line of `~/.agent-playbook/config` (`shared/AGENTS.md § Config Repo Locations`), which `apply.py` rewrites with the other machine state. No governance text names it.

### Step 4: Cutover (the user runs it)

Hand over the exact commands: `& <scripts>\cutover.ps1 -Old <OLD> -New <NEW> [-ConfigRepo <path>] [-Also <files>] -PlanOnly`, then the same without `-PlanOnly`, from a plain PowerShell window outside both trees. Tell them what to close: every Claude Code, Codex, Kiro and VS Code window, and the processes Step 1 found inside OLD — tray apps from their own UI, because they respawn killed children; leftover services (`codex-windows-sandbox-service` and similar) in Task Manager. Every store is shared by all sessions, so a session in an unrelated project must close too.

On failure, read the step, fix the cause, and resume with `-FromStep <n>`; never re-run step 1 by hand after step 2 has run.

**Already moved**: add `-AlreadyMoved`. It needs OLD absent or free of files (an empty tree, `desktop.ini` and `Thumbs.db` are fine) and NEW present. It skips step 1 (no robocopy of any kind; no file under OLD is read or copied, and OLD is only listed to prove it holds no file; it is never created) and runs steps 2-7. A listing error in OLD (a folder you cannot read) refuses too.

**Agent-run mode** (`-IgnoreProcs`, which passes `apply.py --ignore-procs`): only a Claude Code agent uses it (the flag tolerates Claude processes alone); in any other harness the run is handed to the user. The agent may run the cutover itself only when all of these hold.
- The user authorized it in this session, after a dry run that ended `No blockers.`.
- Only Claude processes are alive. The flag relaxes the process check for them alone: the scripts still refuse while any codex, kiro, Code, PowerAtlas or gemini process runs (Gemini CLI is a `node.exe` whose command line names gemini) or a process command line is inside OLD (the agent's own ancestor shells excepted). Never kill a process to satisfy the check.
- The agent runs from a cwd outside both trees. `apply.py` refuses while a live Claude session (`~/.claude/sessions/<pid>.json` with a running pid) has its cwd in OLD or NEW.

The live sessions keep appending to `~/.claude/history.jsonl` and `~/.claude.json`. `apply.py` re-checks those two files just before replacing them and recomputes if they changed, and looks again a few seconds after the run, because a session can write its own copy back; `verify.py pointers` checks both. A file that keeps changing is left as it was and reported as a blocker; the run is then partly applied, so fix the cause and re-run the same command (it is idempotent) rather than restoring.

**A command handed to the user for a shell prompt that runs Bash** (Claude Code's `!`) must be Bash syntax, not PowerShell. Put a long or quoted command in a script file and give the user one short line that runs it.

### Step 5: Verify

1. `verify.py pointers --old <OLD>` must report 0 on every line, and `verify.py residue` must list only accepted prose.
2. `git status --porcelain` per repo must match between OLD and NEW, apart from intended edits (skipped when the folder was already moved).
3. The user checks, per tool, that an old session resumes from NEW: `/resume` in Claude Code started in NEW, the Codex thread list, `kiro-cli chat --list-sessions -f json`, the Kiro IDE history sidebar, and any app launched from a retargeted shortcut. Only the user can prove this.
4. If the config repo moved, commit its machine-state changes (pathspec) when the user agrees, then `/qconfig-sync`.

### Step 6: Retire OLD (only on the user's word)

`verify.py predelete` (with `--exclude` for each rebuilt venv) must list nothing only in OLD or newer there. Then `archive.py build` and `archive.py verify` (must print PASS), and only then delete OLD: `Remove-Item -LiteralPath "\\?\<OLD>" -Recurse -Force`, after confirming that no process and no deployment symlink still points into it.

## Rollback

Until OLD is deleted, everything is reversible. Close every agent first.

| Step | Undo |
|---|---|
| Copy (Step 2), venv rebuild | delete NEW; OLD was never touched |
| `apply.py` (cutover step 2) | `<python> <scripts>\restore.py <work> --apply`, with the per-migration work folder: it undoes every `backup-<stamp>` run in it, newest first (an `apply.py` re-run makes a second one), and a file backed up twice in one run comes back from its first, pre-run copy. Passing a single `<work>\backup-<stamp>` undoes only that run. Run order comes from the UTC start time in each manifest, a damaged manifest falls back to its journal, and a dry run (no `--apply`) already counts missing backup copies; any problem makes it exit 1. A run that died mid-way is rebuilt from `manifest.jsonl`. It also moves back a Claude project folder holding only a session index that `apply.py` parked in `backup-<stamp>\claude-projects-parked\`. Lines a live session appended to `history.jsonl` or `.claude.json` after the run are overwritten by the restore. |
| governance lines (2b) | `git checkout -- shared/AGENTS.md shared/skills/qdream/sweep-orient.md` in the config repo |
| relinked symlinks (3), shortcuts (6b), Kiro IDE history (6) | `<work>\cutover-changes.log` names each change and its backup (`shortcuts-backup\`, `kiro-ide-backup\`) |
| deployment repoint (5) | run `setup.ps1` from the OLD checkout |
| worktree repair (4) | `git worktree repair` from the OLD repo |

## Rules

- **Search JSON stores for the escaped form.** A path inside JSON has doubled backslashes; a single-backslash search finds nothing and reads as "no sessions here". That is how 2,313 kiro-cli v2 sessions were missed on 2026-10-02 until a session-level check found them.
- **Rewrite raw bytes**: no JSON round trip (depth limits truncate session files), no BOM (a BOM written by PowerShell 5's `Set-Content -Encoding UTF8` hid 15 Kiro sessions on 2026-09-24), mtimes preserved. `apply.py` does all three; do not hand-edit a store instead.
- **Rewrite only sessions that belong to OLD.** A transcript of another workspace that mentions OLD is history; leave it byte-identical.
- **Never trust a hash formula unverified.** `apply.py` refuses unless the kiro-cli v3 formula reproduces every existing folder name it is about to move.
- **`.index/` is shared per-workspace state** in a kiro-cli v3 hash folder: never delete it with one session. Park it only once the folder holds no `sess_*` (`apply.py` does).
- **Kiro IDE**: never JSON-parse its session files, never read or write them with Windows PowerShell 5.1's `Get-Content`/`Set-Content` defaults (on 2026-10-02 that BOM-prefixed 58 of 59 migrated files and corrupted every non-ASCII character in 41), and never "prime" a workspace by chatting in it — when the workspace already has v3 sessions, Kiro IDE resumes the latest one, and deleting the throwaway message deleted a real session (2026-09-24). Keep the old execution-data directory until the user has opened a migrated chat.
- **Long or mutating commands**: run them in the background and never pipe them through `Select-Object -First`, which stops the upstream script mid-step. Re-read the real outcome after any "failed" status: robocopy exit 1 means files were copied.
- **Report a gap you created** as soon as you find it, with its scope, before fixing it.

## Limitations

- **Windows only.** Paths, robocopy, shortcuts, `\\?\` long paths, Kiro's lower-cased hash input and the scripts are all Windows-specific. POSIX is not supported: case-sensitive paths, the kiro-cli case-sensitive hash, `~/.local/share/kiro-cli`, and symlink semantics would all need their own handling and were never measured.
- **Undocumented stores.** Every store layout here was measured on one machine (2026-10-02: Claude Code 2.1.281-2.1.288, codex-cli 0.160.0, kiro-cli 2.27.0; Kiro IDE 1.0.437 as of 2026-09-24). Re-run `scan.py` before trusting a script after an upgrade, and re-check the store notes below.
- **Hash-keyed state that cannot be recomputed** starts fresh: VS Code and Kiro IDE `workspaceStorage/<hash>` (open editors, layout).

## Store notes

What is keyed by path, per provider, and what was measured:

- Claude Code: `providers/claude/reference/claude-code-local-data.md § Path-keyed state (moving a workspace)`
- Codex: `providers/codex/reference/codex-local-data.md`
- kiro-cli v3: `providers/kiro/reference/kiro-cli-v3-internals.md § Stores keyed by the workspace hash`
- kiro-cli v2: `providers/kiro/reference/kiro-cli-v2-local-data.md § Moving a workspace`
- Kiro IDE: `providers/kiro/reference/kiro-ide-local-data.md`
- Gemini CLI (no reference file; measured 2026-10-02): `~/.gemini/projects.json` maps paths to project names, and each `~/.gemini/tmp/<name>/.project_root` and `~/.gemini/history/<name>/.project_root` holds the path; both are rewritten. Chat logs under `tmp/` are history.
- PowerAtlas: `config.toml` `pinned_folders` and `workspace_settings` keys (its own `docs/KNOWLEDGE.md`, "Workspace moves")
- Playbook store repo: `shared/skills/qdream/memory-rules.md § Workspace Store`. `apply.py` re-keys every store whose `STORE` file reads `local <path>` with a path equal to or inside OLD: the line moves to the same place under NEW, in the store resolver's normalized form (`shared/skills/qdream/memory-rules.md § Path normalization`). The write is atomic, backed up and restorable; a dry run changes nothing. Directory names never change. Another store that already holds the new line is a blocker and stops the run. A `remote` store needs no change. This step runs whether or not `--config-repo` is given. The rewritten `STORE` files are uncommitted changes in the store repo: commit them there by pathspec, or leave them for `/qconfig-sync`.
- **A changed remote** (a rename, a new host) is re-keyed by hand. Find the store with `store-resolver.py list`, or the `STORE` file that holds the old `remote` line. Edit line 1 to `remote <host/owner/name>` and keep any `path` line. Do not rename the directory. Commit the change in the store repo, then confirm with `store-resolver.py find <checkout>`.
