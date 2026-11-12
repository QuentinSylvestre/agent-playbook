---
name: qconfig-sync
description: Sync the shared AI agent config repo -- pull latest, verify and repair deployment, and push. Use after editing governance or skill files in the config repo, or to pull latest changes.
argument-hint: "<repo path> (optional)"
disable-model-invocation: true
---

# AI Config Sync

## Your role

Synchronize the shared AI agent configuration repository, keeping agent instructions and skills current across environments.

## Config repository path

$ARGUMENTS

If no path is provided, use the default location per `shared/AGENTS.md § Config Repo Locations`.

## Scope restriction

Only read and write files within the config repository, the store repo (`~/.agent-playbook/stores`, Step 2b) and the symlink targets in provider config directories (~/.claude/, ~/.codex/, ~/.gemini/, ~/.kiro/). The Claude settings check also reads `~/.claude/settings.json` and `settings.local.json`; nothing in this skill writes them. Do NOT read or modify any other files.

## Process

### Step 1: Check local state

Before pulling, understand the current state of the repo:

1. Run `git -C <repo> status --short` to detect uncommitted changes in the paths that deploy or load in every session: `shared/`, `providers/`, and the tracked root files (`AGENTS.md`, `CLAUDE.md`, `inventory.tsv`, `setup.sh`, `setup.ps1`, `.gitattributes`, `.gitignore`). Changes elsewhere (`plans/`, `.agents/`, `artifacts/`, untracked files outside the paths above) are other sessions' work in progress: they do not open the gate; list them in Step 7.
2. Check the branch: `git -C <repo> symbolic-ref --short HEAD` must print the engine branch (`engine_branch=` in `~/.agent-playbook/config`, default `local-improvements`). Engine commits never land on `main`: `main` moves only when the user merges `local-improvements` into it by hand. On any other branch, STOP and ask the user whether to switch (`git -C <repo> switch <engine branch>`). Then run `git -C <repo> log @{u}..HEAD --oneline` to detect unpushed local commits (with no upstream yet, count every commit not on `origin/main` as ahead).
3. If uncommitted changes are detected, **STOP** and present them to the user. Ask: "Uncommitted changes detected. Commit them now / Continue without them / Abort?" Do not proceed until the user decides. There is no stash option: stashing hides files another live session may still be editing (Step 2: never stash another session's files unprompted). "Continue without them" leaves every dirty file untouched. A file first dirtied after this gate, by a live session during the sync, does not re-open it: leave it untouched and list it in Step 7. Such a file stops the sync only where it blocks a rebase, through Step 2's question. The gate is unconditional: coherence, apparent authorship by a prior session, **authorship by the current session**, or plausible intent are not exemptions — in-scope uncommitted changes always go to the user. This list is illustrative, not exhaustive: a shape it does not name is not thereby permitted. When a dirty file is named in an active project file (a store's `plans/*.md`, not `plans/done/`), say which plan it belongs to: it is likely another session's work in progress.
4. Inform the user of any unpushed commits found.

### Step 2: Pull latest changes

Based on the local state from Step 1:

- **No local commits ahead**: Run `git -C <repo> pull --ff-only` (the engine branch's own upstream, `origin/<engine branch>`; skip when it has none yet).
- **Local commits ahead**: Run `git -C <repo> pull --rebase` to replay local commits on top of remote. If rebase conflicts, STOP and inform the user.
- **Then take `main`**: `git -C <repo> fetch origin main` and `git -C <repo> merge --no-edit origin/main`. A merge, never a rebase: the engine branch is pushed, and its commits must not be rewritten. Nothing to merge is the normal case. A merge conflict STOPs the sync like a rebase conflict.
- **Rebase blocked by out-of-scope dirty files** (another session's working files): STOP and ask: "Rebase blocked by <files>. Options: autostash (`git pull --rebase --autostash`, restores after) / wait / abort?" Never stash another session's files unprompted.
- **Coherence after a clean rebase**: a conflict-free `pull --rebase` does not guarantee semantic coherence. When replayed local commits and incoming remote commits both edited the same governance hooks, run a coherence review of the merged result before deploying — a clean textual merge can still leave two uncoordinated mechanisms in one hook.

### Step 2b: Sync the store repo

The store repo (`~/.agent-playbook/stores`, `shared/skills/qdream/memory-rules.md § Workspace Store`) holds every workspace store: its memory, plans and artifacts. `<store-repo>` below is that path.

- **Missing**: if `<store-repo>/.git` does not exist, report a skip, not a failure, and print the clone command from `providers/claude/README.md § Store repo on a new machine`. Go on to Step 3.
- **Index lock**: before any write (`add`, `commit`, `pull`, `rebase`, `push`), if `<store-repo>/.git/index.lock` exists, wait and retry for up to 30 s, then STOP the whole sync (Steps 3-5 do not run) and report it in Step 7. Never delete it: another session may hold it.
- **User memory**: the store repo's reserved `user/` holds user memory (the config repo's `memory` link points to `user/memory/`; it has no `STORE` line). A `/qdream` sweep leaves a memory file uncommitted when it was dirty at the sweep's start. List `user/` first, labelled "user memory", under the same rules as a store.
- **Pending changes**: run `git -C <store-repo> status --short -uall` and `git -C <store-repo> log origin/main..HEAD --oneline` (with no `origin/main` yet, count every commit as ahead). List every uncommitted path grouped by store (the top-level directory, with its `STORE` identity line), each with its age from the file's modification time ("deleted", or "renamed from <old>", for a `D` or `R` path), and the commits-ahead count. A path modified minutes ago, or a file under a store's `plans/` outside `plans/done/`, is likely another session's work in progress: say so. Ask which paths to commit. Commit only the confirmed paths, by pathspec: `git -C <store-repo> commit -m "<type>(<store-name>): <summary>" -- <paths>` (new files first need `git -C <store-repo> add -- <paths>`). Never `add -A` or `add .`, and never commit a path the user did not confirm.
- **Pull**: apply the Step 2 rules to the store repo (fast-forward, or rebase when commits are ahead; the autostash question for dirty files that block the rebase). With no `origin/main` yet, skip the pull and say the remote is still empty.
- **Conflict**: a store-repo rebase conflict stops the whole sync (Steps 3-5 do not run), as a config-repo conflict does in Step 2; report it in Step 7. Name the conflicting files (`git -C <store-repo> diff --name-only --diff-filter=U`) and resolve them with the user before any `/qdream` sweep or lifecycle commit: `dream-write.py` refuses to commit in a repo with a rebase in progress. After resolving, `git -C <store-repo> add -- <resolved files>`, then continue with `git -C <store-repo> rebase --continue` with `GIT_EDITOR=true` set for that command (PowerShell: `$env:GIT_EDITOR = "true"` first; `memory/topics/git.md`).
- **Scratch cleanup** (`shared/skills/qdream/memory-rules.md § Store scratch folder`): run `<python> shared/skills/qdream/scripts/store-resolver.py scratch-clean` (`<python>` as in the load-budget check below). It asks nothing. Report every `DELETED` line with its size, every `STALE-OPEN` line as a paused plan's folder, and every `FAILED` line as left in place. An improvised-folder `WARN` from the store-layout check is the user's to move or delete.

### Step 3: Verify deployment integrity

**Run every check of this step with the runner, and before Step 5.** `<python> shared/skills/qconfig-sync/scripts/run-checks.py <repo>` (`<python>` as in the load-budget check below) runs all the checks listed in this step, in parallel where safe, with the invocations given below. It prints one line per check (name, exit code, seconds, flagged-line count, verdict), then the folder holding each check's full output, then the wall time. Run it in the background with its output written to a file, and allow 20 minutes: it stops any check still running after 15 minutes, with every process under it, and reports `TIMEOUT`. Then apply each check's reporting rule below to every verdict other than `PASS`, reading that check's output in the work folder; the Claude settings check is reported on every verdict. `PARTIAL` (a parity run with skipped assertions, or a selftest with a `SKIP` case), `COULD-NOT-RUN` and `TIMEOUT` are never green. The runner reads each exit code from the process itself. The invocations below remain the reference for re-running one check by hand, under the exit-code rule in `## Rules`. Resolve every failure other than deployment drift (which Steps 4-5 repair) before Step 5, under that check's own reporting rule, which usually means stopping for the user: setup then runs once per sync, where a guard failure found after setup forces a second setup and verify. When the venv is missing the runner cannot start: run setup first (`setup.ps1` creates the venv), then the runner.

Run the deployment verification script -- it enumerates every expected symlink and Kiro copy and emits one tab-separated line per result.

**Invocation** (`<python>` as in the load-budget check below; its own `--selftest`, listed below, is its test): `<python> shared/skills/qconfig-sync/scripts/verify-deployment.py`

**Use `pwsh`, never `powershell`, from an agent harness** (for `setup.ps1` and the launcher test). Windows PowerShell 5.1 inherits `PSModulePath` from its pwsh-7 parent, so `powershell` resolves `Microsoft.PowerShell.Utility` to an incompatible copy and core cmdlets vanish. Diagnose with `powershell -NoProfile -Command '(Get-Module -ListAvailable Microsoft.PowerShell.Utility).Version'` (7.x under 5.1 is the tell); if only 5.1 exists, run from a non-pwsh-derived shell or clear `PSModulePath`.

**Bypass-flag fallback** (every PowerShell invocation in this skill): if a harness blocks `-ExecutionPolicy Bypass` (e.g. flagged as a security-disarm), invoke bare instead — `& .\setup.ps1` — which runs under RemoteSigned, since local unsigned scripts are permitted.

**Reporting rule**: surface any non-`OK` line. `SKIP` is surfaced once per provider: confirm it's intentional, or run setup to install. `ORPHAN` is report-only — delete a file only after confirming its source was removed deliberately; its last field, read from the deploy lock, says `owned-by-setup` (the next setup run removes it if unedited), `mixed` (a folder holding files setup wrote and files it did not: the next run removes only setup's unedited files and keeps the folder with yours) or `foreign` (yours, or a `.bak`: setup never removes it). `OK <path> user-folder-kept` passes, but surface it once: a folder of the user's own holds a playbook skill's name, so setup never deploys that skill there; to receive the playbook's skill, rename or remove the folder, then re-run setup. `MISSING <settings.json> context.fileName-lacks=AGENT-PLAYBOOK.md` beside a kept `GEMINI.md` means setup could not edit that file (comments in it, which Gemini CLI accepts): a re-run does not fix it, so tell the user to add `"AGENT-PLAYBOOK.md"` to `context.fileName` by hand. `DRIFTED <side link> leftover-side-link=` is a co-existence link left beside the playbook's own instruction-file link (a double load when its detail says so): the next setup run removes it. `AMBIGUOUS_SKILL` **fails the run on its own**: read the detail field — `SKILL.md` and an overlay in one directory (delete the `SKILL.md` if it's an overlay for a shared skill, else the overlay files), or an overlay with no `SKILL.md` and no shared skill to merge into (create the shared skill, rename the directory to match one, or promote the overlay to standalone).

**Exit codes / halt rule**: 0, continue. 1 with a `DRIFTED` line → Step 4. 1 with no `DRIFTED` line → resolve the reported status and re-run; `ORPHAN`/`AMBIGUOUS_SKILL` never route to Step 4 alone. 2 → halt: the guard did not run, which isn't the same as finding nothing. **Every check below halts the same way** on its own failing exit code: stop before Step 6 (no commit/push) and report the finding — none auto-repair except via Step 5's redeploy.

Output schema and rationale: the header docstring of `verify-deployment.py` (run it with `--help`).

#### Canonical-section citation check

After verify-deployment, run the citation-lockstep check — it confirms every cited site for each rename-guarded canonical section (enumerated in `scripts/citation-checks.tsv`, the table `verify-citations.py` reads) still contains a live reference to that section's heading or stable step-ID tag.

**Invocation** (`<python>` as in the load-budget check below; its own `--selftest`, listed below, is its test): `<python> shared/skills/qconfig-sync/scripts/verify-citations.py`

**Reporting rule**: surface any `MISSING` line (a rename-guard violation). On exit 1, report which cited sites lost their reference and reconcile by hand (extend the canonical section, restore the citation, or update `citation-checks.tsv` if a site was deliberately removed) — the script does not auto-repair. Exit 2: the guard did not run — treat it as a read failure, not a citations verdict.

Output schema and rationale: the header docstring of `verify-citations.py` (run it with `--help`).

#### Memory structure check

Beside the citation check, run the memory structure guard. It checks every memory file against `shared/skills/qdream/memory-rules.md § Memory File Format`: `memory/MEMORY.md`, `memory/HIGHER_ORDER.md`, `memory/topics/*.md`, and each store's `memory/MEMORY.md` in the store repo. Its `topic-citation` rule confirms, for each row of the `## Topics` table in `memory/MEMORY.md`, that at least one document in the "Also cited from" cell exists, contains the topic path, and is always loaded when it applies: a file `inventory.tsv` deploys as `~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md`, `~/.gemini/GEMINI.md` or under `~/.kiro/steering/`, a skill's `SKILL.md`, or the repo's root `AGENTS.md`. The repo-root argument is mandatory.

**Invocation** (`<python>` as in the load-budget check below): `<python> shared/skills/qconfig-sync/scripts/verify-memory.py <repo>`

**Reporting rule**: exit 1 is a `FAIL` line naming the file, line, rule and entry. Memory text is user-authored: propose each fix to the user and apply it only on their answer; the script does not auto-repair. A `topic-citation` FAIL is fixed by adding a one-line condition pointer to the topic in the most specific accepted document whose subject matches the topic's trigger, then naming that document in the row. Only when no accepted document fits, the row carries the waiver token `(no always-loaded home — index only)` with the reason. `WARN` lines (a missing field, an incomplete signal, a relative date) never change the exit code: surface them. A missing store repo prints one `SKIP` line (Step 2b's skip). Exit 2: the guard did not run (venv missing, an unreadable repo, a malformed `## Topics` table or a store repo scan failure), never a memory verdict.

**Parity note**: Python only, no `.sh`/`.ps1` twin, so it is outside `test-parity.sh`'s assertion tally. Its own `--selftest` (listed below) is the check.

Output schema and rationale: the header docstring of `verify-memory.py` (run it with `--help`).

#### Governance word-budget check

After the citation check, run the governance-mass brake — it measures every session-loaded governance file in `verify-mass.py`'s `BUDGETS` table against its absolute word ceiling, so governance word-mass cannot ratchet upward unnoticed. The repo-root argument is mandatory — never derived from the ambient cwd.

**Invocation** (`<python>` as in the load-budget check below; its own `--selftest`, listed below, is its test): `<python> shared/skills/qconfig-sync/scripts/verify-mass.py <repo>`

**Reporting rule**: surface any `OVER` line. On exit 1, report which file exceeded its budget and by how many words — the script does not auto-repair. **Override path**: first route the growth to the skill that owns the behaviour, which costs the ceiling nothing; or cut restatement to return under budget (per the conditional Proportionality/Leanness standard, `shared/skills/qreview/SKILL.md`). Raise a budget row only for a rule with no owning skill, and only on an explicit user decision recorded in the commit body (ratchet rule 2 in the header docstring of `verify-mass.py`), with the justification in the commit body. Exit 2: precondition failure.

Output schema and rationale: the header docstring of `verify-mass.py` (run it with `--help`).

#### Citation-link check

After the citation-lockstep check, run the link check — unlike `verify-citations`'s hand-maintained `CHECKS` list, this one **derives its whole workload from the prose**: every backticked repo-relative path citation in `shared/` and `providers/` must resolve, and every `§` anchor must still occur in its target.

**Invocation** (`<python>` as in the load-budget check below; its own `--selftest`, listed below, is its test): `<python> shared/skills/qconfig-sync/scripts/verify-links.py`

**Reporting rule**: on exit 1 (`MISSING_PATH` or `MISSING_ANCHOR`), report the broken citations — the script prints a `REMEDIATION` line naming the three repair options. Exit 2: the guard did not run — report it as "the guard could not read the tree", not a citations verdict or a repo-path problem.

**Scope and escapes**: `plans/` is excluded as source and target; `memory/` is excluded as a source but allowed as a target. Bare paths (no `§`) are checked only when they contain a slash *and* their first segment is `shared/`, `providers/` or `memory/`. For text that is not a real citation, annotate the line with `<!-- verify-links: skip <path> -->` (target-scoped) or `<!-- verify-links: skip -->` (whole line). **Never weaken the resolver to make a broken pointer pass.**

Output schema and rationale: the header docstring of `verify-links.py` (run it with `--help`).

After the link check, the leak scan: `<python> shared/skills/qconfig-sync/scripts/leak-scan.py <repo>` fails on a tracked file holding a home path with a real user name, an email address outside the documentation domains, or a credential shape (one `LEAK<TAB>kind<TAB>path:line` line each, never the matched text). User memory and plans live in the store repo, so a hit in the engine is something personal about to be published: move it to the store repo or replace it with a placeholder (`C:\Users\alice`, `example.com`). A deliberate test string carries `leak-scan: ignore` on its line.

#### Skill frontmatter check

After the leak scan, run the skill guard. It checks every `shared/skills/*/SKILL.md` and every standalone `providers/kiro/skills/*/SKILL.md` (a folder with no `OVERLAY.md`): the strict flat frontmatter grammar, the required `name` and `description`, a quoted `argument-hint`, a `name` equal to the folder name that starts with `q` and appears once, and the optional quoted `requires` list of skills this skill depends on. Every `requires` entry must name a checked skill and appear in the body, and every skill the body invokes by explicit phrasing must be listed. The call-versus-mention rule is in the script's header docstring.

**Invocation** (`<python>` as in the load-budget check below; its own `--selftest`, listed below, is its test): `<python> shared/skills/qconfig-sync/scripts/verify-skills.py <repo>`

**Reporting rule**: surface every `FAIL` line (file, then what is wrong); exit 1 fails the sync under the halt rule, and nothing auto-repairs. Exit 2: the guard did not run.

Output schema and rationale: the header docstring of `verify-skills.py` (run it with `--help`).

#### Client load check

After the skill guard, run the client load check. `verify-deployment` proves a skill is where setup put it; this check asks each client whether it lists the skill, with a read-only command that spends no model call. It reads `providers=` from `~/.agent-playbook/config` and checks each selected client whose binary is on `PATH`. For each skill setup deploys it prints `LOADED`, `INACTIVE` (deployed but absent from the client's listing, or listed disabled), `UNOBSERVABLE` (Claude Code and Kiro have no listing without a model call; one line per client) or `SKIP <reason>` (not selected, not installed, the command failed or timed out, or its output did not parse). Each line names the command, the client version and the date. The capability ledger, per client, is a table in the script.

**Invocation** (`<python>` as in the load-budget check below; its own `--selftest`, listed below, is its test): `<python> shared/skills/qconfig-sync/scripts/verify-client-load.py <repo>`

**Reporting rule**: never fails the sync: `INACTIVE` and `SKIP` exit 0. The `SUMMARY` line names every inactive skill as `client:skill`; put those names to the user as a question, since a report-only line goes unread. To act on one, re-run setup and Step 5, check the client's skill folder holds the skill with parseable frontmatter, then check the client's own disabled list. `gemini skills list` starts the user's configured MCP servers while it discovers skills. Exit 2: the check did not run.

Output schema and the ledger: the header docstring of `verify-client-load.py` (run it with `--help`).

#### Store-layout check

After the link check, run the store-layout guard. It checks the store repo (`~/.agent-playbook/stores`) against `shared/skills/qdream/memory-rules.md § Workspace Store`: every store directory holds a valid `STORE` file in the resolver's normalized form, no two share an identity, and the reserved folder names appear only as that section lists them. It also fails any tracked config-repo file, archived plans included, that holds a term from the store repo's `BLOCKLIST` file, naming the file and the `BLOCKLIST` line, never the term: client names go in that list, never in the config repo. It also warns on an in-workspace `memory/` or `plans/` left in a known workspace; a no-create folder (`shared/skills/qdream/memory-rules.md § Resolution contract`) is exempt, and so is a config repo's `memory/` (the user tier), never its `plans/`.

**Invocation** (`<python>` as in the load-budget check below): `<python> shared/skills/qconfig-sync/scripts/verify-stores.py <repo>`

**Reporting rule**: exit 1 is a `FAIL` line; each names the next action. `WARN` lines never change the exit code and nothing is deleted: surface them. A `WARN` is a store-repo path uncommitted, or commits unpushed, for over a day (Step 2b commits and pushes them), a rebase or merge stopped in the store repo (finish it in Step 2b first), a store-repo `origin` other than the URL in `providers/claude/README.md § Store repo on a new machine` (check where the push goes before Step 6), an orphaned store, an in-workspace `memory/` or `plans/` left in a known workspace (move it into the store), a Kiro `__store_memory__.md` that is not a symlink to its store's memory, or a wired workspace (a `.kiro/steering/__store__.md` pointer naming a store) whose store holds memory but has no `__store_memory__.md` link (the repair is to re-run `/qwire-governance` there). The repair of an orphaned store is a user decision. A `BLOCKLIST` FAIL is repaired by replacing the term with a neutral placeholder; never print the term in a report. A missing store repo prints one `SKIP` line (Step 2b's skip). Exit 2: the guard did not run (venv missing, unusable repo or store repo scan), never a layout verdict; report it as "store-layout check could not run" with the stderr line.

**Parity note**: Python only, no `.sh`/`.ps1` twin, so it is outside `test-parity.sh`'s assertion tally. Its own `--selftest` (listed below) is the check.

Output schema and rationale: the header docstring of `verify-stores.py` (run it with `--help`).

#### qdream load-budget check

After the store-layout check, run the qdream load-budget check — it measures the words the `/qdream` core and lightweight modes load against the pins in `shared/skills/qdream/scripts/dream-check.py` (`CORE_BUDGET_WORDS`, `LIGHTWEIGHT_BUDGET_WORDS`), so an edit to `shared/skills/qdream/SKILL.md` or to the `memory-rules.md` sections the lightweight mode extracts cannot exceed them unnoticed. It also prints a `memory` row: the always-loaded user memory's words against `MEMORY_BUDGET_WORDS` in `shared/skills/qdream/scripts/dream-manifest.py` (`shared/skills/qdream/memory-rules.md § Session-start memory context budget`), as `<words>/<pin>`, plus `OVER` when over.

**Invocation** (`<python>` is the interpreter of `<repo>/.venv-agent-playbook` with `-I` (`shared/AGENTS.md § Config Repo Locations`), the playbook's one interpreter, created by `setup.ps1` or `setup.sh`; never `python`, `python3` or `py` from `PATH`; this holds for every `<python>` line in this skill): `<python> shared/skills/qdream/scripts/dream-check.py budget --repo <repo>`

**Reporting rule**: the `memory` row never changes the exit code — report an `OVER` there as a warning that the next full `/qdream` sweep will propose routing and pruning, never as a sync failure. Exit 1 is an `OVER budget` line or a missing named section; report which load exceeded its pin and by how many words — the script does not auto-repair. **Override path**: raising a pin needs the user's approval, recorded in the commit message (the rule beside the constants); otherwise cut words to return under the pin. Exit 2: usage error, the guard did not run. Venv missing (the `<python>` file does not exist, or it fails to start): report "qdream load-budget check could not run: venv missing — run setup.ps1 or setup.sh" as exit 2, never a pass.

#### Claude settings check

Setup links the Claude Code scripts, but they only run once `~/.claude/settings.json` points at them. This check reports three groups: the memory hook, the status line and the sounds.

**Invocation** (`<python>` as in the load-budget check above): `<python> providers/claude/settings-entries.py check`

**Reporting rule**: the runner prints this check's lines under its table, whatever the verdict, and Step 7 reports them even on `PASS`. A `WARN` on `memory-hook` means sessions start without the memory index: tell the user to run setup at a terminal, where it asks before adding the entry. An `INFO` line is a personal choice, not a finding. `SKIP` means this home has no Claude Code deployment, or the platform is outside the merge. No line changes the exit code, so none fails the sync. Exit 2: the check did not run.

#### Memory-script selftests

After the load-budget check, run the twenty-seven selftests: the memory scripts' and the guards'. The Claude Code `SessionStart` hook imports internals of `dream-manifest.py`, `qmemory-eval.py`, `store-resolver.py` and `memory-entries.py`, and it fails open: a renamed helper would silently empty every session's memory index instead of failing loudly. `dream-sweep.py` and `dream-write.py` import `dream-manifest.py` too, and `dream-write.py` is the only script that writes memory files or the state file, or runs `git commit` and `git push`. The selftests catch a break at sync time. `dream-write.py --selftest` builds throwaway git repositories in the system temp directory and runs its cases in worker processes (four by default; the runner passes `--jobs 8`). It takes minutes: 252 s for 195 cases run alone with `--jobs 8` on the Windows development machine (2026-11-05, 22 cores), and up to 758 s while other work ran, because most of the time goes to launching `git`, about 69 times per case. A foreground call at a 120-300 second tool timeout is therefore killed before it finishes. Run by hand, run it in the background with its output written to a file, and allow a timeout of at least 15 minutes. A foreground timeout alone is not a hang or a deadlock: report one only after the background run has been observed to stall.

**Invocation** (`<python>` as above; if that file is missing, stop and report as below), from the repo root:

- `<python> shared/skills/qdream/scripts/dream-manifest.py --selftest`
- `<python> shared/skills/qdream/scripts/dream-check.py --selftest`
- `<python> shared/skills/qdream/scripts/dream-sweep.py --selftest`
- `<python> shared/skills/qdream/scripts/dream-write.py --selftest`
- `<python> shared/skills/qdream/scripts/qmemory-eval.py --selftest`
- `<python> shared/skills/qdream/scripts/store-resolver.py --selftest`
- `<python> shared/skills/qdream/scripts/memory-entries.py --selftest`
- `<python> shared/skills/qdream/scripts/venv-selfcheck.py --selftest`
- `<python> shared/skills/qconfig-sync/scripts/verify-stores.py --selftest`
- `<python> shared/skills/qconfig-sync/scripts/verify-memory.py --selftest`
- `<python> shared/skills/qconfig-sync/scripts/verify-citations.py --selftest`
- `<python> shared/skills/qconfig-sync/scripts/verify-mass.py --selftest`
- `<python> shared/skills/qconfig-sync/scripts/verify-links.py --selftest`
- `<python> shared/skills/qconfig-sync/scripts/verify-skills.py --selftest`
- `<python> shared/skills/qconfig-sync/scripts/verify-client-load.py --selftest`
- `<python> shared/skills/qconfig-sync/scripts/leak-scan.py --selftest`
- `<python> shared/skills/qdream/scripts/verify-dream-journal.py --selftest`
- `<python> shared/skills/qdream/scripts/verify-dream-state.py --selftest`
- `<python> shared/skills/qconfig-sync/scripts/verify-deployment.py --selftest`
- `<python> shared/skills/qvalidate/scripts/qvalidate.py --selftest`
- `<python> shared/skills/qclose/scripts/close-plan.py --selftest`
- `<python> providers/kiro/skills/qwire-governance/scripts/scan.py --selftest`
- `<python> shared/skills/qmigrate-workspace/scripts/test_store_rewrite.py`
- `<python> shared/skills/qvisualize/scripts/render.py --selftest`
- `<python> providers/claude/memory-load-hook.py --selftest`
- `<python> providers/gemini/context-filename.py --selftest`
- `<python> providers/claude/settings-entries.py --selftest`

**Reporting rule**: each exits 0 only when no case failed. Any non-zero exit fails the sync under the halt rule above: name the script and paste its failing-case lines; nothing auto-repairs. A case printed as `SKIP` (git could not build a fixture repository, or `render.py` found no browser) is reported, never counted as a pass. Venv missing (the `<python>` file does not exist, or it fails to start): report "memory-script selftests could not run: venv missing — run setup.ps1 or setup.sh" as exit 2, never a pass.

**Launcher test** (Windows): the hook runs through `providers/claude/memory-load-hook.ps1`, which must exit 0 and print a notice when the venv or the hook fails. Run `pwsh -ExecutionPolicy Bypass -File providers/claude/memory-load-hook.launcher-test.ps1`. Exit 0 passes, 1 fails the sync under the halt rule (paste the `FAIL` lines), 2 means it could not run (venv missing: report it, never a pass).

#### Cross-shell parity check

After the word-budget check, run the parity check unconditionally — it catches one-twin divergence (e.g. a step changed in only one `setup` twin) and takes minutes on the Windows development machine: 215 s inside the runner (2026-10-26), where every other check competes for the processor. Run by hand, run it in the background. If the working tree holds uncommitted files you did not write under `providers/` or `shared/`, a check can fail on them rather than on your change. Before attributing a failure to your own change, show which foreign file it comes from (the failing selftest case or fixture lives in it, or the drifted or diverging path is one of them), or re-run that check after the other session commits. Report the foreign files rather than editing them. Do not copy the repo to a temp folder to run the checks there: endpoint security can stop scripts run from the temp folder mid-run (observed 2026-10-23), which gives a result that means nothing. It confirms `verify-deployment` and `setup.sh` agree on the deployment inventory, and asserts cross-shell equivalence for the overlay-merge and template-render models; these SKIP with a notice when no PowerShell interpreter is present. It also covers the `setup.sh`/`setup.ps1` pair itself, the one script pair left: an always-on assertion deploys `setup.sh` into a sandbox `HOME` and checks the result verifies clean under `verify-deployment.py`, and a PowerShell-gated assertion compares that sandbox against a `setup.ps1`-deployed one as trees.

**Invocation** (bash-only, all platforms): `bash shared/skills/qconfig-sync/scripts/test-parity.sh`. On Windows, run it through Git Bash, never a bare `bash` typed from PowerShell or a kiro-cli shell tool: that `bash` is WSL's, it cannot see Windows `pwsh`, and every PowerShell assertion SKIPs.

**Reporting rule**: the script prints `PARITY OK` and exits 0 on success, even when assertions were skipped; a warning after that line marks the partial run. A run with any cross-shell assertion skipped is not a green. On a machine where `pwsh` is installed, treat any such skip as an invocation error: re-run through Git Bash, and never report the skipped run as clean or as `PARITY OK`. Report a skipped run as partial, with the skip count and the reason. On exit 1, report the diff — the script does not auto-repair; a mismatch means a twin pair (or the expected-inventory block) diverged and must be reconciled by hand.

Output schema and rationale: the header comment of `test-parity.sh` (no `--help` flag; read the file).

#### Reference: expected-state inventory

**`inventory.tsv` at the repo root is the single source of truth for top-level (hardcoded) entries; dynamic entries (per-skill symlinks/copies, v3 steering, overlay merges) are auto-discovered from the filesystem.** `setup.sh`/`setup.ps1` are authoritative for deployment, `verify-deployment.py` for verification — the parity check above confirms the two agree on every sync. Update `inventory.tsv` when adding a top-level entry.

For the full symlink/copy table, generated-file kinds, dest-token expansion, and the overlay-merge byte contract, read `verify-deployment.py`'s header docstring (`--help`) rather than this file.

### Step 4: Drift-direction analysis

If Step 3 reported any `DRIFTED` lines, determine whether each is "behind" the repo (safe to overwrite) or has local-specific edits (needs a user decision). Skip this step if none were reported.

For each `DRIFTED` line:

1. **Extract paths**: take the deployed path (field 2) and the source path (the value after `expected=` — don't rely on position; an optional `target=` field may precede it).
2. **Derive the repo-relative POSIX path**: strip the repo root from the `expected=` path and normalize backslashes to slashes (required for `git show`).
3. **Early-exit check**: compare the local file against the repo source with `git diff --no-index --quiet` before querying history. If identical (exit 0), it's not actually drifted — skip it.
4. **Query git history**: run `git -C <repo> log --format=%H --max-count=100 -- <repo-relative-source-path>`. Zero commits (e.g. newly added, never committed) → classify "local-specific" and note it has no history yet.
5. **Compare against history**: for each commit, write the historical version to a temp file byte for byte (`git -C <repo> show <sha>:<repo-relative-path> > <temp-file>`), compare with `git diff --no-index --quiet -- <local-path> <temp-file>`, and delete the temp file after each comparison. Use temp files on every platform — `git diff --no-index` can behave unexpectedly with process substitution. Run the `show` redirection in a shell whose `>` writes raw bytes: Git Bash, or `cmd /c "git -C <repo> show <sha>:<repo-relative-path> > <temp-file>"` from PowerShell. Never use `>` in Windows PowerShell 5.1: it re-encodes the output as UTF-16LE, so every comparison misses and every `DRIFTED` file is wrongly classed local-specific.
6. **Classify**:
   - **Match found** (exit 0): **"behind"** — the local copy matches an older repo version. Add to the auto-repair list, no prompt needed.
   - **No match after all commits** (or the 100-commit limit): **"local-specific"** — the file has edits not present in any checked version. Conservative: a >100-commit history can misclassify, but the prompt below prevents data loss.

**User prompt for local-specific files** — present the file path and offer:
- **Overwrite**: discard local changes; Step 5 overwrites with the current repo version.
- **Keep**: skip this file in Step 5; leave the local version in place.
- **Promote (merge)**: read both versions, produce a merged result, and present it for approval. On approval, write the merge to the repo source file and commit it (`git add <source-path> && git commit -m "feat(config-sync): promote local changes from <filename>" -- <source-path>`) — it then proceeds to Step 5 repair normally.

**Merged deployables.** An overlay-bearing kiro skill under `~/.kiro/skills/` is a generated `shared SKILL.md + OVERLAY.md` copy (an aux file is `<stem>.md` + `<stem>.OVERLAY.md`). Its `DRIFTED` line reads `expected=merge(<shared source>)`, and the deployed file never equals that source, so steps 3 and 5 above cannot compare against it directly: the deployed copy would always differ and always classify "local-specific". For such a line, compare against the recomputed merge instead. In step 3, build the expected merge from the working-tree shared source and its overlay (the shared body, a blank line, the overlay body, one trailing newline; the shared body alone plus one trailing newline when the overlay is empty; the byte contract is `_merged_bytes` in `verify-deployment.py`) into a temp file, and compare the deployed file with it. In step 5, rebuild the merge the same way at each historical commit, from the shared source and the overlay as they were at that commit, and compare each result with the deployed file. A match is "behind"; no match is "local-specific". Never Promote it whole into either source. Show which part the local edits fall in and ask which source file takes them. If the repo source of any drifted file has uncommitted edits, STOP: the drift is another session's unfinished work, not a deployment fault; report the file and do not Overwrite or Promote it.

**Guard**: if a drifted file is binary (not UTF-8 decodable, or has null bytes), skip Promote — offer only Overwrite or Keep.


### Step 5: Repair deployment issues

If Step 3 found any issues, repair by re-running the setup script. Run it only once every Step 3 check has returned and every failure other than deployment drift is resolved. **Drift-direction exceptions**: "Keep" files are excluded from repair; "Promote (merge)" files already have the correct content committed to the repo source, so repair syncs it; "behind" files repair normally.

1. Summarize the issues found (excluding kept files).
2. Run the setup script — **Windows**: `pwsh -ExecutionPolicy Bypass -File "<repo>/setup.ps1"`; **Linux/WSL/macOS**: `bash "<repo>/setup.sh"`.
3. Re-verify deployment integrity with `run-checks.py <repo> --only verify-deployment` (setup changes no other check's input) and report whether all issues are resolved.

If the user chose "Keep" for any files, tell them those files remain out of sync and will show `DRIFTED` on the next run. Skip this step if Step 3 found no issues.

### Step 6: Push unpushed commits

List every commit ahead of origin with its subject, and mark the ones this session did not create. Open the list with the repository it belongs to: its path and its `origin` URL (`git -C <repo> remote get-url origin`). Group the marked commits by their Conventional Commits scope, and name the plan when a project file with that slug exists (a store's `plans/` or `plans/done/`); keep every subject under its group, never a count alone. If any are marked, ask before pushing: "Push all / Wait / Abort?" (a subset cannot be pushed without rewriting history). Push only on the answer, and push the engine branch only: `git -C <repo> push -u origin <engine branch>` (the `-u` only the first time). A push refused for lack of rights means this clone is not the user's own (a contributor clone of the upstream repo): report it and point to `CONTRIBUTING.md` (fork, push the branch there, open a pull request). Skip if no commits are ahead. Do the same for the store repo, with the same rules and the index-lock rule of Step 2b; when it has no `origin/main` yet, the push is `git -C <store-repo> push -u origin main`.

### Step 7: Report

Summarize:
- Whether new changes were pulled
- Whether local changes exist (committed or not), listing the uncommitted paths outside the Step 1 gate
- Store repo: pulled, skipped (missing) or stopped (conflict, index lock); paths committed, left uncommitted, pushed
- Deployment status (all intact / repaired / issues remaining)
- Claude settings: the state of the memory hook, the status line and the sounds

**Actionable WARNs are questions, not report lines.** A `WARN` that names a repair the user can choose (an orphaned store, an in-workspace `memory/` or `plans/` to move, a Kiro workspace without its `__store_memory__.md` link, a store-repo `origin` that differs from the expected URL) is not listed in the summary above. Ask one question per such `WARN`: name the subject and the repair, then offer "Fix now / Leave?". On "Fix now", run the repair the reporting rule names (for an orphaned store, ask which store to delete and delete nothing unconfirmed). On "Leave", change nothing. A `WARN` with no user repair (the Claude settings `INFO` lines, a `SKIP`) stays a report line. A `FAIL` keeps its own next action.

## Rules

- Only read and write files within the config repository, the store repo and symlink targets; the Claude settings check only reads its two settings files
- Never force-push. Use rebase only via `git pull --rebase` to replay local-only commits on top of the engine branch's own remote; take `main` by merge (Step 2). Never push `main` and never merge into it: that is the user's manual step.
- Never modify files outside the config repo scope
- Proceed autonomously through all steps. Only stop and ask the user when: uncommitted changes are detected (Step 1), store-repo changes await confirmation (Step 2b), an unexpected failure occurs (rebase conflict in either repo, a lingering store `index.lock`, precondition failure, citation drift, word-budget overage, parity mismatch), Step 4 detects local-specific edits requiring a user decision, or an action would destroy local-only changes.
- **Read the true exit code on Windows.** Every halt rule in this skill keys on a script's exit code. Run each guard, selftest, `setup.ps1` and `git push` without `2>&1`, and print the code in the same call straight after it: PowerShell `<command>; "EXIT:$LASTEXITCODE"`, for a bash-run script `bash <script>; echo "EXIT:$?"`. Windows PowerShell 5.1 wraps a native command's stderr lines in `NativeCommandError` when `2>&1` is used and can report a false exit 1 for a clean run (`memory/topics/powershell.md`). Decide pass or fail from the printed `EXIT:` value, never from the wrapper's status or from stderr text.

