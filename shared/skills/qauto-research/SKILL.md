---
name: qauto-research
description: Autonomous iterative optimization experiments. Setup a research config, then run an experiment loop that proposes changes, evaluates metrics, and keeps or discards results.
argument-hint: "<setup | run | run --max-iterations N | run --max-time T>"
---

# Auto-Research

## Your role

Guide the user through setting up a research configuration, then autonomously execute iterative optimization experiments — proposing changes, evaluating metrics, and keeping or discarding results — until stop conditions are met.

## Input

$ARGUMENTS

## Mode detection

Determine mode from `$ARGUMENTS`:

1. If `$ARGUMENTS` contains both `setup` and `run` keywords → **Error**. Inform the user that only one mode can be active at a time.
2. If `$ARGUMENTS` contains `setup` → **Setup mode**
3. If `$ARGUMENTS` contains `run` → **Run mode** (parse optional flags: `--max-iterations N`, `--max-time T`)
4. If neither keyword is present:
   - Check if a `research.md` file exists at the workspace root (or at the configured path if a previous setup stored it elsewhere)
   - Exists → **Run mode**
   - Absent → **Setup mode**

---

## Setup mode

Interactive flow that creates a `research.md` configuration file for the current project. Reference the co-located `RESEARCH_CONFIG_TEMPLATE.md` for the target schema structure.

### Step 1: Discover workspace

Explore the project to build context for the research configuration:

1. Read the project structure (top-level directories, key files)
2. Identify build systems (Makefile, CMakeLists.txt, package.json, Cargo.toml, etc.)
3. Identify test scripts and evaluation harnesses (test runners, benchmark scripts, measurement tools)
4. Identify hardware interfaces if applicable (serial ports, debug probes, flashing tools)
5. Check for existing per-artifact state from any previous setup and prompt per artifact (see § Setup re-runnability below). The five artifacts are: (a) `research.md` at the workspace root, (b) the `research/<tag>` branch, (c) the dedicated worktree at the configured path, (d) the id=0 baseline entry in `research-log.jsonl`, (e) the stop hook in the user-level hook config (§ Step 10 names it per provider).

Present a brief summary of what you found and confirm with the user before proceeding.

### Setup re-runnability

Setup is idempotent across all of Steps 1-10: detect each artifact independently and run the appropriate sub-step on re-run. Default prompt for each "exists, reuse?" question is **Y**.

**Per-artifact detection order**: artifacts are checked in this fixed sequence, because later checks depend on earlier artifacts being resolved:

1. `research.md` (independent — read to discover the configured `git.tag`, worktree path, and hook settings)
2. `research/<tag>` branch (depends on `research.md` being read so the tag is known)
3. Worktree at the configured path (depends on `research.md`; worktree existence is also relevant to Step 8's branch-aware decision)
4. Baseline entry in `research-log.jsonl` (depends on the worktree existing — the log file lives inside the worktree)
5. Stop hook in the hook config (independent of the above; can be checked last)

**Per-artifact decisions**:

- **`research.md` exists** → ask the user whether to overwrite or use a different path (legacy behavior preserved).
  - **Tag-change confirmation gate**: if the user chooses overwrite AND the new `research.md`'s `git.tag` differs from the prior file's `git.tag`, Setup MUST surface the orphan implication and ask for explicit confirmation BEFORE proceeding: `"Overwriting research.md changes git.tag from <old-tag> to <new-tag>. The prior research/<old-tag> branch and its worktree at <old-worktree-path> will remain in place and become orphaned. Continue with the new tag? [y/N] (To abort and clean up the old worktree first: decline this prompt, then run: git worktree remove <old-worktree-path> && git branch -D research/<old-tag>, then re-invoke /qauto-research setup.)"` (default N). On confirmation, proceed with the new tag and fall through to the orphaned-worktree informational note at end of setup. On decline, abort setup with no changes.
  - **Tag-change orphans**: if the user confirms the tag change above, the prior `git.tag`'s branch and worktree remain in place and become orphaned. The user is responsible for cleaning up the old `research/<old-tag>` branch and its worktree (`git worktree remove` + `git branch -D`) if they are no longer needed.
- **`research/<tag>` branch exists** → "branch `research/<tag>` exists. Reuse? [Y/n]". Decline = abort setup with instructions to choose a different `git.tag`.
- **Worktree at configured path exists** → "worktree at `<path>` exists. Reuse? [Y/n]". Decline = abort setup with instructions to remove the worktree manually.
- **Baseline-entry detection** in `research-log.jsonl`: detection requires a parseable JSON line at file start with `id: 0` AND `status: "baseline"`. Treatment:
  - File present, first line parses, matches → baseline exists. See § Re-baseline decision rule below.
  - File present but unparseable, OR first line does not match the id=0/status=baseline shape → treat as **baseline absent (corrupted)**. Prompt the user: "`research-log.jsonl` exists at `<path>` but does not contain a valid id=0 baseline entry. Overwrite and re-run baseline eval? [y/N]" (default **N**). On accept, proceed to re-run Step 9. On decline, **before aborting**, print the partial-setup summary (the same per-artifact summary defined at the end of § Setup re-runnability — research.md, branch, worktree, baseline-entry, hook, with whatever status applies to each from this invocation) with the header label changed to `Setup aborted.` (the per-row statuses stay correct for this invocation) so the user knows the current state of the project, then abort setup with a manual-cleanup pointer.
  - File absent → treat as **baseline absent**. Proceed to Step 9 with no prompt.
- **Partial state** — worktree exists BUT no baseline entry (e.g., a previous setup aborted between Step 8 and Step 9): detect discretely and re-attempt Step 9 automatically with no prompt (baseline never existed, so re-running is non-destructive). **Worktree cleanliness note**: when Step 9 retries via this partial-state path, the worktree may contain build artifacts or untracked files from the prior failed attempt's pre_commands. Print a one-line note before retrying: "Re-running baseline eval in a worktree that may contain prior-run artifacts. If your pre_commands are not idempotent, clean the worktree manually first." The user is responsible for worktree cleanliness if their pre_commands are not idempotent.
- **Stop hook exists** in the hook config → "stop hook present. Reuse? [Y/n]".

**Re-baseline decision rule**: when the baseline entry already exists, diff the hard-invalidating eval fields in the current `research.md` against the fields the baseline was measured under. If any of `evaluation.command`, `evaluation.pre_commands`, `evaluation.output_format`, `evaluation.patterns` changed:

- **Case A (clean re-baseline)** — log contains ONLY the id=0 baseline entry and no subsequent `keep`/`discard`/`crash` entries → prompt: "`evaluation.<field>` changed since baseline was measured. Re-run baseline eval and refresh experiment #0? [y/N]" (default **N**). If accepted, rewrite the log entry to a temp file, durably flush it, then **atomically replace** `research-log.jsonl` with it, then re-commit. **Atomicity guarantee** (load-bearing — preserve exactly): use the platform's atomic-replace primitive (never delete-then-rename, which has a window where neither file exists); ensure the new file is durable on disk BEFORE the rename commits (so a power-loss cannot leave a zero-byte log); and if `git commit` fails after the replace succeeds, **abort with a manual-commit pointer — do NOT auto-rollback the file** (rollback would re-introduce a write race). If the eval or write fails before the atomic-replace, the original `research-log.jsonl` is untouched and setup can be re-run safely.
- **Case B (refuse with manual-cleanup guidance)** — log contains experiments beyond id=0 → refuse to re-baseline automatically. Print the following block (the agent substitutes the actual `git.tag` value from `research.md` at print time; `<YYMMDD>` stays as a placeholder for the user because it is the date-of-action, not config-driven):

  > `evaluation.<field>` changed since baseline was measured, but `research-log.jsonl` contains N experiments past the baseline whose `keep`/`discard` decisions were made against the OLD baseline. Their semantics are no longer comparable to a new baseline. To re-baseline, manually archive or delete `research-log.jsonl` and re-run `/qauto-research setup`.
  >
  > Suggested archive command template (substitute today's date in YYMMDD format for `<YYMMDD>`):
  >
  >     git mv research-log.jsonl research-log.<git.tag-value>-prerebaseline.<YYMMDD>.jsonl && git commit -m 'docs(research): archive log before re-baseline'
  >
  > Worked example (today: 260517, your tag: `<git.tag-value>`):
  >
  >     git mv research-log.jsonl research-log.<git.tag-value>-prerebaseline.260517.jsonl && git commit -m 'docs(research): archive log before re-baseline'

  Setup proceeds with the existing baseline (no re-measurement). The user has unambiguous data-stewardship responsibility.

If none of the hard-invalidating fields changed, skip Step 9 (baseline preserved).

`evaluation.timeout_seconds` is intentionally **not** a re-baseline trigger: timeout changes do not invalidate already-measured metrics; they only widen or tighten the timeout-failure threshold. The metric values from a successful eval do not change when timeout changes; excluding it avoids re-baseline prompts when users widen timeouts to accommodate slower CI.

At the end of setup, report a per-artifact status summary (one line per artifact) so the user can see what changed. The allowed status set is row-specific (e.g., `re-baselined` only applies to the baseline-entry row):

```
Setup complete.
  research.md: <created | reused | skipped>
  branch: <created | reused | skipped>
  worktree: <created | reused | skipped>
  baseline entry: <created | reused | re-baselined (Case A) | skipped>
  hook: <created | reused | skipped | failed (install error: <one-line>)>
```

Use `re-baselined` for the baseline entry only when Case A's atomic re-write executed; otherwise use `reused` (Case B or no hard-invalidating change) or `created` (first-time setup). Use `failed` for the hook row when Step 10's soft-fail warning fired (hook installation rejected but setup otherwise complete) — this distinct status loudly signals the degraded state so it does not get lost in a sea of `created`/`reused` lines.

**Orphaned-worktree informational note** (optional, post-summary): print a one-line informational note for each `research/*` worktree from `git worktree list --porcelain` whose branch suffix does NOT match the current `git.tag`, OR whose path does NOT match the configured `git.worktree_path` for the current tag — "Orphaned research worktree at `<path>` on `research/<old-tag>` — clean up (`git worktree remove <path>` + `git branch -D research/<old-tag>`) if no longer needed." The user is responsible for cleanup. This helps surface the tag-change-overwrite case from § Per-artifact decisions where the prior tag's branch+worktree linger without warning, and also catches the same-tag-different-path case where a previous setup placed the worktree at a path the user has since reconfigured.

### Step 2: Define objectives

Ask the user what they are optimizing. Capture metrics in three tiers:

**Optimize** — metrics the agent actively tries to improve:
- Name, direction (`lower` or `higher` is better), optional target threshold, optional unit
- At least one Optimize metric is required

**Guard** — metrics that must not regress beyond a hard threshold:
- Name, direction (the "good" direction), threshold value, optional unit
- Violation of any Guard metric causes an experiment to be discarded

**Track** — metrics logged for visibility but not acted upon:
- Name, optional unit
- Informational only; no decision logic

Help the user identify appropriate metrics from the evaluation harness discovered in Step 1. Suggest metrics if the user is unsure, based on the project type (e.g., latency, throughput, code size, accuracy, power consumption).

### Step 3: Define evaluation harness

Determine how metrics are measured. Capture:

1. **Pre-evaluation commands** — commands to run before measurement (build, flash firmware, deploy, warm up, etc.). May be empty for interpreted languages or pre-built artifacts.
2. **Evaluation command** — the main command that produces metric output. Must be a single command or script invocation.
3. **Output parsing** — how to extract metric values from the command output:
   - `structured`: command outputs JSON with metric names as keys
   - `regex`: define one regex pattern per metric (each with one capture group)
4. **Timeout** — maximum seconds for the evaluation command. If exceeded, the experiment is treated as a crash.

Validate the harness by asking the user to confirm the command works (or offer to do a dry-run if safe). The evaluation command must be deterministic enough that metric differences reflect actual changes, not noise.

### Step 4: Define modification scope

Define what the agent is allowed to modify during experiments.

**V1: file-level only.** Capture a list of file paths the agent may edit. The agent must not modify files outside this list during the experiment loop.

Guidelines for scope definition:
- Include only files where changes could plausibly affect the Optimize metrics
- Exclude test files, evaluation scripts, and build configuration (changing these would invalidate measurements)
- Exclude generated files (they will be regenerated by pre-evaluation commands)

### Step 5: Define stop conditions

Determine when the experiment loop should halt. Capture:

| Condition | Description | Required? |
|---|---|---|
| `max_iterations` | Maximum number of experiments to run | Yes (default: 50) |
| `max_time_minutes` | Maximum wall-clock time in minutes | Yes (default: 120) |
| Objective thresholds | Stop when all Optimize metrics reach their target values | Only if targets defined in Step 2 |
| `plateau_window` | Stop after K consecutive experiments with no Optimize improvement | Yes (default: 10) |
| `consecutive_crash_limit` | Stop after N consecutive crashes | Yes (default: 5) |

All conditions are evaluated after each experiment. The loop stops when ANY condition triggers.

### Step 6: Define git strategy

Configure the git branch and worktree for the research run:

1. **Tag** — ask the user for a short identifier (e.g., `may12`, `v2-ota-speed`, `param-sweep`). This becomes the branch suffix.
2. **Source branch** — capture the branch the user is on right now via `git rev-parse --abbrev-ref HEAD`. Record it as `git.source_branch` in `research.md`'s frontmatter alongside `git.tag`. `/qclose research` reads this field to know which branch to squash-merge the research run's last-known-good back onto. Capture happens automatically — no user prompt unless detection fails (e.g., detached HEAD, in which case ask the user explicitly which branch to record).
3. **Branch** — `research/<tag>` (prefix is hardcoded, not configurable). Inform the user that this branch will be created if it does not exist (see Step 8 for the conditional create-or-attach logic).
4. **Worktree** — the skill will create a dedicated git worktree to isolate research from the main working tree. Default location: `../<project-name>-research`. Confirm with the user or let them choose a different path.

Example command the skill will run (illustrative only — see Step 8 for the actual conditional form that uses `-b` when the branch does not yet exist):
```
git worktree add ../<project>-research research/<tag>
```

Explain to the user:
- All experiment commits happen on the research branch in the dedicated worktree
- The main working tree is never modified during a research run
- Failed experiments are discarded via `git reset --hard` in the worktree (scoped exception to the absolute git bans — see `## Git Exception` below, which defines it canonically)
- The experiment log (`research-log.jsonl`) lives on the research branch and is never merged to main

### Step 7: Write research.md

Generate the `research.md` configuration file from the information gathered in Steps 1-6.

1. **Path selection** — default: workspace root. If a file already exists at that path (detected in Step 1), ask the user for an alternative path or confirmation to overwrite.
2. **Schema version** — always include `schema_version: 1` in the frontmatter.
3. **Structure** — use the schema defined in `RESEARCH_CONFIG_TEMPLATE.md` (co-located with this skill file). The file has:
   - YAML frontmatter with all machine-parseable fields (metrics, evaluation, scope, stop conditions, git config)
   - Markdown body with freeform context (strategy notes, domain context, seeded hypotheses)
4. **Body content** — ask the user if they want to add:
   - Strategy notes (approaches to try or avoid)
   - Domain context (background knowledge relevant to the optimization)
   - Seeded hypotheses (specific ideas to test first)
   - Prior results (links or summaries of previous work)
5. **Write the file** and confirm to the user.

### Step 8: Create research branch and worktree

**Skip condition**: if Step 1 confirmed reuse for both the branch (`research/<tag>`) and the worktree at the configured path, skip Step 8 entirely. Otherwise: proceed with the branch-existence detection and `git worktree add` form selection below.

Detect whether the `research/<tag>` ref already exists. Two complementary checks are required because neither alone covers every case:

1. **Ref-existence check** — `git rev-parse --verify research/<tag>` exits non-zero iff no local branch head, tag, or remote-tracking ref of that bare name is found.
2. **Worktree-held check** — `git worktree list --porcelain` enumerates each worktree's branch attachment. Parse the porcelain output line by line and string-equality-match the `branch` field against `refs/heads/research/<tag>` (shell equivalent: `grep -F "branch refs/heads/research/<tag>$"`). This finds the branch even when it is checked out in another worktree (`git worktree add` will refuse to attach it). If a match is found, abort setup immediately: "Branch `research/<tag>` is already checked out at `<path-from-worktree-list>`. Either reuse that worktree (update `git.worktree_path` in research.md) or pick a different `git.tag`. After editing research.md, re-run `/qauto-research setup` for the new path or tag to take effect." Extract `<path-from-worktree-list>` from the `worktree <path>` line preceding the matching `branch` line.

- **Ref does NOT exist** (rev-parse non-zero exit AND worktree-held check empty): create branch and worktree atomically:
  ```
  git worktree add -b research/<tag> <worktree-path>
  ```
- **Ref DOES exist but not worktree-held** (rev-parse exit code 0, worktree-held check empty): attach the worktree to the existing branch:
  ```
  git worktree add <worktree-path> research/<tag>
  ```
- **Worktree-held** (worktree-held check matches): abort with the specific message above; do not invoke `git worktree add`.

`<worktree-name>` (used in the lock-file path below and in Run mode's worktree-lock check) is the basename of the configured worktree path, OR can be derived from `git worktree list --porcelain` output by matching the `worktree <path>` line and taking the basename of that path. Either source is acceptable.

**TOCTOU fallback** (narrow race window remaining after the combined detection above): the branch could still be created (by a concurrent agent, another worktree, or a CI process) between the detection checks and the `git worktree add -b` call. If `git worktree add -b` fails, inspect its stderr for branch-already-exists patterns specifically — either `fatal: a branch named 'research/<tag>' already exists` OR `fatal: 'research/<tag>' is already checked out at`. Only on those exact stderr patterns, retry **once** with the non-`-b` form: `git worktree add <worktree-path> research/<tag>`. Any other `git worktree add -b` failure (disk-full, permissions, invalid worktree path, etc.) passes through immediately with the original error message — do not retry, do not swallow the error.

If the non-`-b` retry also fails, abort setup with a clear error that includes both the original and retry error messages, and instruct the user to remove any stale worktree (`git worktree remove`) or branch (`git branch -D`) before re-running setup.

Abort setup with a clear error if `git worktree add` fails for any other reason (for example, the worktree path is already used by another worktree). No post-verify is needed — `git worktree add` succeeds if and only if the worktree exists at the expected branch.

Re-run behavior is governed by § Setup re-runnability: if Step 1 detected an existing branch and/or worktree and the user accepted reuse, skip the corresponding `git worktree add` invocation per the skip condition above.

### Step 9: Run baseline evaluation and log experiment #0

Enter the worktree and measure the baseline:

1. Run `evaluation.pre_commands` sequentially, printing a progress line per command as it completes (these can take many minutes for hardware harnesses). If any fails, abort setup with a clear error pointing at the failing command.
2. Run `evaluation.command` with `evaluation.timeout_seconds`, printing a start-of-eval progress line. Non-zero exit or timeout = abort setup with a clear harness-pointing error.
3. Parse metrics per `output_format`:
   - `structured`: parse JSON, extract values by metric name.
   - `regex`: apply each pattern in `evaluation.patterns` and parse the first capture group as a number.
4. Validate that every declared metric name in `metrics.optimize`, `metrics.guard`, and `metrics.track` appears in the parsed output. Missing names = abort setup with a clear harness-pointing error.

Guard threshold checking is intentionally NOT done at baseline — guards are threshold-based in run-mode Step 5, not baseline-relative. A baseline that violates its own guards still functions as a reference, and the run-mode keep/discard logic handles it correctly.

If validation passes, append the baseline entry to `research-log.jsonl`:

```json
{"id": 0, "commit": "<baseline-sha>", "status": "baseline", "description": "baseline eval at setup", "metrics": {"metric_name": value, ...}, "timestamp": "<ISO-8601 UTC>"}
```

Commit the log:

```
feat(research): baseline experiment #0
```

If baseline eval fails (non-zero exit, timeout, missing metric names), abort setup with a clear error pointing at the harness; **leave the worktree in place**. § Setup re-runnability's per-artifact detection recognises "worktree exists but baseline absent" as a discrete state and re-attempts Step 9 automatically on re-run. Do NOT install the hook (Step 10) until baseline succeeds.

Report the measured baseline metric values to the user before continuing.

**Forward reference**: the first-experiment-after-setup case (where the harness has silently drifted between Setup's baseline measurement and the first Run-mode experiment) is handled by Run mode § Step 4's crash handler, which surfaces "harness likely drifted since setup" as a probable cause when the log still contains only the id=0 baseline entry.

### Step 10: Create hook

**Conditional**: only create the hook if `hook.enabled` is `true` in the generated `research.md`. If `hook.enabled` is `false` (e.g., user prefers manual control), skip hook creation and inform the user they must manually re-invoke `/qauto-research run` after each experiment.

When `hook.enabled` is `true`, add a stop hook to the provider's **user-level** hook configuration. The location and the continuation mechanism differ by provider:

| Provider | Hook config | How the hook keeps the session going |
|---|---|---|
| Kiro | `hooks.stop` in `~/.kiro/agents/<agent-name>.json` | Text the hook prints becomes the next prompt |
| Claude Code | `hooks.Stop` in `~/.claude/settings.json` | Exit code `2`: Claude Code blocks the stop and feeds stderr back to the model. Printing to stdout alone does **not** continue the session |

Both hooks fire only when on a `research/*` branch with a `research.md` present.

**Kiro** — add a `stop` hook entry:

```json
{
  "hooks": {
    "stop": [
      {
        "command": "powershell -NoProfile -Command \"if (Test-Path research.md) { $branch = git branch --show-current 2>$null; if ($branch -match '^research/') { Write-Output 'AUTO-RESEARCH ACTIVE: Read research.md and the last 10 entries of research-log.jsonl, check stop conditions (max iterations, max time, objective thresholds, plateau, consecutive crashes), and if not met, continue with /qauto-research run. If stop conditions are met, remove the auto-research stop hook from the agent config and report final results.' } }\""
      }
    ]
  }
}
```

On Linux/macOS, use the bash equivalent:

```json
{
  "hooks": {
    "stop": [
      {
        "command": "bash -c 'if [ -f research.md ]; then branch=$(git branch --show-current 2>/dev/null); if [[ \"$branch\" == research/* ]]; then echo \"AUTO-RESEARCH ACTIVE: Read research.md and the last 10 entries of research-log.jsonl, check stop conditions (max iterations, max time, objective thresholds, plateau, consecutive crashes), and if not met, continue with /qauto-research run. If stop conditions are met, remove the auto-research stop hook from the agent config and report final results.\"; fi; fi'"
      }
    ]
  }
}
```

**Claude Code** — add a `Stop` entry. Claude Code runs hook commands through bash, using Git Bash on Windows, so one form covers every platform. On a Windows machine without Git Bash, Claude Code falls back to PowerShell; there, adapt the Kiro PowerShell command to write the message to stderr and `exit 2`:

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "bash -c 'if [ -f research.md ]; then branch=$(git branch --show-current 2>/dev/null); if [[ \"$branch\" == research/* ]]; then echo \"AUTO-RESEARCH ACTIVE: Read research.md and the last 10 entries of research-log.jsonl, check stop conditions (max iterations, max time, objective thresholds, plateau, consecutive crashes), and if not met, continue with /qauto-research run. If stop conditions are met, remove the auto-research Stop hook from ~/.claude/settings.json and report final results.\" >&2; exit 2; fi; fi'"
          }
        ]
      }
    ]
  }
}
```

The hook blocks every stop until it is removed, so removing it (Run mode § Step 8) is what ends the loop. Claude Code also lets a stop through after 8 blocks in a row with no tool call in between, which caps a run that has stopped doing work. If a run goes wrong, the user interrupts the session and deletes the entry.

**Hook lifecycle**:
- The hook is **self-gating**: it only produces output (and thus triggers continuation) when both `research.md` exists in the cwd AND the current branch matches `research/*`. Outside research contexts, the hook is a no-op.
- **Disabling**: the skill removes the hook entry from the hook config when stop conditions are met. The user can also remove it manually or simply switch off the research branch.
- The hook lives in the **user-level** hook config (not project-local), so it works across all projects without per-project setup.

**If the hook config already has a stop-hook array** (`hooks.stop` on Kiro, `hooks.Stop` on Claude Code): append the new entry. Do not overwrite existing stop hooks.

**Hook installation failure semantics**: if hook installation fails (e.g., the hook config file is read-only, its JSON/TOML syntax is already invalid, the provider's config directory is missing, or the write is otherwise rejected): print a loud warning that **includes the underlying error verbatim**, e.g., `"Stop hook installation FAILED — <underlying error message verbatim>. Setup is otherwise complete (research.md, branch, worktree, baseline entry are all in place), but auto-continuation will not work. Either install the hook manually or re-run /qauto-research setup after fixing the hook config."` — and continue. Setup does NOT abort on hook installation failure: the user can still run `/qauto-research run` and complete experiments manually, just without hook-driven auto-continuation. The verbatim-error inclusion is mandatory so the user can diagnose whether the failure is transient (e.g., temporary file-lock) or systemic (e.g., malformed JSON).

**Hook recovery paths**: subsequent `/qauto-research setup` invocations will detect the missing hook via Step 1's per-artifact hook detection and re-attempt installation automatically. The user may also install manually by appending the hook entry (the JSON snippet shown above for their provider and platform) to the hook config named in the table above; if a stop-hook array already exists, append the new entry rather than overwriting.

After creating the hook (or skipping it if `hook.enabled: false`, or after the failure warning above), confirm setup is complete. The user must manually invoke `/qauto-research run` to start the first experiment. Subsequent iterations are hook-driven (if enabled) or require manual re-invocation.

---

## Run mode

The autonomous experiment loop. On invocation, parse optional CLI flags:
- `--max-iterations N` — overrides `stop.max_iterations` from `research.md`
- `--max-time T` — overrides `stop.max_time_minutes` from `research.md`

CLI flags take precedence over values in `research.md`.

**Single-session contract**: Run mode is designed for **single-session sequential use** — the hook mechanism (see Setup Step 10) auto-resumes after session boundaries, but only one Run-mode invocation per worktree at a time. Concurrent `/qauto-research run` invocations on the same worktree may race on `research-log.jsonl` writes, git commit interleaving, and `git reset --hard` operations; the skill does not acquire an advisory lock. Users running multiple research tags should use separate worktrees (one per `git.tag`).

### Step 1: Initialize

1. **Read configuration** — locate and parse `research.md` (workspace root or configured path). Validate all required frontmatter fields are present and well-formed. Abort with a clear error if validation fails. Note the `hook.enabled` value — if `false`, the agent will not rely on hook-based re-invocation and must complete as many experiments as possible within the current session.
2. **Enter worktree** — locate and validate the dedicated worktree at the configured path (default: `../<project>-research`). Run mode never creates worktrees; that is Setup-mode behavior. The checks below run in a specific order because some preconditions (e.g., lock state) are ill-defined to evaluate from inside a `cd`'d worktree:

   - **(a) Worktree path exists**: if the worktree path is absent on disk, abort with: "No worktree found at `<path>`. Run /qauto-research setup first."
   - **(b) Worktree lock check** (BEFORE `cd`): confirm the worktree is not locked. A locked worktree means a `locked` file exists under `<git-common-dir>/worktrees/<worktree-name>/locked` in the main repo's git directory (where `<worktree-name>` is the basename of the configured worktree path, OR derived from `git worktree list --porcelain` output by matching the `worktree <path>` line and taking its basename). To resolve the main repo's git common directory from the worktree's path, run `git --git-dir=<worktree-path>/.git rev-parse --git-common-dir` (this returns the main repo's git directory, even when invoked from inside a worktree). Equivalently — and often more robust — `git worktree list --porcelain` enumerates each worktree with a `locked` line if present; parse the porcelain output for that field as an alternative. If locked, abort with: "Worktree at `<path>` is locked. Remove the lock (`git worktree unlock <path>`) or re-create the worktree via /qauto-research setup." Checking the lock first avoids `cd`-ing into an ill-defined locked-worktree state.
   - **(c) Enter the worktree** (`cd` to it).
   - **(d) HEAD ref check**: confirm the worktree HEAD is on `research/<tag>` (the tag from `research.md`). If not, abort with: "Worktree at `<path>` exists but HEAD is `<branch>`, expected `research/<tag>`. Re-create the worktree via /qauto-research setup or fix manually (`git -C <path> checkout research/<tag>`)."
   - **(e) Baseline log defensive check**: validate that `research-log.jsonl` exists inside the worktree, is parseable JSONL, and contains at minimum an id=0 entry with `status: "baseline"` at file start:
     - If the log file is missing: abort with "Baseline log missing or corrupted at `<path>/research-log.jsonl`. Re-run /qauto-research setup."
     - If the log file exists but is not parseable JSONL: abort with the same message: "Baseline log missing or corrupted at `<path>/research-log.jsonl`. Re-run /qauto-research setup."
     - If the log file exists and parses but the first line does not have `id: 0` and `status: "baseline"`: abort with "Baseline log missing id=0 entry at `<path>/research-log.jsonl`. Re-run /qauto-research setup."
3. **Determine state** — read `research-log.jsonl` (which exists and was validated in the previous sub-step). Read the last 10 entries to rebuild context. Identify the last-known-good commit (the most recent entry with `status: keep` or `status: baseline`). Verify the worktree HEAD matches that commit. If it does not, reset to it only when no tracked file has uncommitted changes (`git status --porcelain --untracked-files=no` is empty) and every commit between last-known-good and HEAD is an unlogged `experiment(research):` commit (an experiment interrupted before Step 6). Otherwise stop and show the user `git status` and `git log <last-good-sha>..HEAD`: the work there was not made by this loop and a reset would destroy it.
4. **Verify hook** — if `hook.enabled` is `true`, confirm the stop hook is present in the user-level hook config (§ Step 10). If missing (e.g., user removed it manually, or Setup's Step 10 install failed and the user did not re-install), print a multi-line WARNING block and proceed in single-session mode:

   ```
   WARNING: Auto-continuation hook is missing from the hook config.
   This research run will not auto-resume across sessions.
   To fix: re-run `/qauto-research setup` (will detect missing hook and reinstall).
   Or set hook.enabled: false in research.md to suppress this warning.
   Proceeding in single-session mode.
   ```
5. **Record start time** — for the `max_time_minutes` clock, which must survive session boundaries. On a hook re-entry (the turn carries the `AUTO-RESEARCH ACTIVE` message), the start time is the `run_started` value of the last log entry that has one. On a manual `/qauto-research run`, or when no entry has one, the start time is now. Every entry Step 6 writes carries it as `run_started`.

### Step 2: Propose experiment

Generate a hypothesis for the next experiment:

1. **Review history** — read the experiment log (last 10 entries minimum) to understand:
   - What changes were kept (successful directions)
   - What was discarded (dead ends to avoid)
   - What crashed (fragile areas)
2. **Check seeded hypotheses** — read the markdown body of `research.md` for any seeded hypotheses the user provided. Use these as inspiration (not obligation) — the agent decides whether a seeded hypothesis is worth testing given current context.
3. **Respect scope** — only propose modifications to files listed in `scope.files`. Never propose changes to evaluation scripts, test harnesses, or build configuration.
4. **Formulate** — produce a specific, testable hypothesis:
   - What will be changed (which file(s), what modification)
   - Why it might improve the Optimize metrics
   - What risk it poses to Guard metrics

### Step 3: Execute experiment

1. **Apply modifications** — edit only files within the declared `scope.files`. Make the changes described in the hypothesis.
2. **Commit changes** — commit with message: `experiment(research): <one-line description of the change>`
3. **Run pre-evaluation commands** — execute each command in `evaluation.pre_commands` sequentially. If any fails, treat as a crash (go to Step 4).
4. **Run evaluation** — execute `evaluation.command` with a timeout of `evaluation.timeout_seconds`:
   - If the command exits with code 0: proceed to parse output
   - If the command exits non-zero or exceeds timeout: treat as a crash (go to Step 4)
5. **Parse metrics** — extract metric values from the command output:
   - If `output_format: structured`: parse JSON output, extract values by metric name
   - If `output_format: regex`: apply each pattern in `evaluation.patterns` to the output, extract capture groups
   - If parsing fails (missing metrics, malformed output): treat as a crash (go to Step 4)

### Step 4: Handle crashes

A crash occurs when the evaluation command fails (non-zero exit), times out, or produces unparseable output.

1. **Attempt fix** — analyze the error and try a different approach. Up to **3 retries** are allowed per experiment, each with a meaningfully different fix (not the same change repeated).

   **First-experiment-after-setup special case**: when the crashing experiment is the first one of the run, the most probable cause is that the harness drifted since setup measured the baseline (e.g., a dependency moved, environment changed, or the build no longer reproduces). **Heuristic (precise definition)**: this case fires when `research-log.jsonl` length == 1 at Step 4 entry — i.e., only the id=0 baseline entry exists and no `keep`/`discard`/`crash` entries have been written yet — regardless of retry count within the current experiment. Surface this hypothesis explicitly in the diagnosis: "harness likely drifted since setup — re-run /qauto-research setup". Retry attempts should consider re-baseline as a possible resolution path before exhausting all 3 retries on the experiment's own code change.
2. **If fixed** — a retry that produces parseable metrics exits the crash handler. Proceed to Step 5 (decide keep/discard) with the successful retry's metrics.
3. **If unfixable** (all 3 retries exhausted or error is clearly unrecoverable):
   - Log the experiment with `status: crash`, including the error message/context and the description of the attempted change
   - Reset to last-known-good: `git reset --hard <last-good-sha>` (scoped exception — see Git Exception section)
   - Proceed to Step 6 (log) then Step 7 (check stop conditions)
   - Crashed experiments do NOT count toward the plateau window, but DO count toward the consecutive crash limit

### Step 5: Decide keep or discard

Apply the multi-metric decision logic in this exact order:

1. **Check Guard metrics** — for each Guard metric, compare the measured value against its threshold (respecting direction). If ANY Guard metric is violated (value is worse than threshold), the experiment is **discarded**. No further checks needed.

2. **Check Optimize metrics (strict Pareto-improvement)** — compare each Optimize metric against the last-known-good values:

   > **Strict Pareto-improvement definition**: An experiment is kept if and only if:
   > - **No regression**: every Optimize metric is equal to or better than its last-known-good value (respecting each metric's direction), AND
   > - **At least one improvement**: at least one Optimize metric is strictly better than its last-known-good value.
   >
   > If ANY Optimize metric regresses (is worse than last-known-good), the experiment is discarded — even if other Optimize metrics improved significantly. There is no trade-off between Optimize metrics.

3. **Apply decision**:
   - **Keep**: update the last-known-good pointer to the current commit SHA. The worktree stays at this commit.
   - **Discard**: reset to last-known-good: `git reset --hard <last-good-sha>` (scoped exception). The experiment commit is abandoned.

Track metrics are logged but never influence the keep/discard decision.

### Step 6: Log experiment

Append one line to `research-log.jsonl` in the worktree:

```json
{"id": N, "commit": "<sha>", "status": "keep|discard|crash|baseline", "description": "one-line description of the change", "metrics": {"metric_name": value, ...}, "timestamp": "2025-05-12T14:30:00Z", "run_started": "2025-05-12T13:05:00Z", "error": "error message if crash, omitted otherwise"}
```

Field definitions:
- `id`: sequential integer starting at 0 (baseline)
- `commit`: the short SHA of the experiment commit (or baseline commit for id 0)
- `status`: one of `baseline`, `keep`, `discard`, `crash`
- `description`: human-readable one-line summary of what was attempted
- `metrics`: object with all measured metric values (Optimize + Guard + Track). Omitted for crashes where no metrics were obtained.
- `timestamp`: ISO 8601 UTC timestamp of when the experiment completed
- `error`: error context string (present only for `status: crash`)
- `run_started`: ISO 8601 UTC start time of the current run, from Step 1 (omitted on the baseline entry)

After appending, commit the log file: `docs(research): log experiment #N`

### Step 7: Check stop conditions

Evaluate ALL stop conditions after every experiment. The loop stops when ANY condition triggers:

| Condition | Trigger | Source |
|---|---|---|
| Max iterations | Total experiments (excluding baseline) >= `stop.max_iterations` | `research.md` or `--max-iterations` CLI flag |
| Max time | Wall-clock time since the start time recorded in Step 1 >= `stop.max_time_minutes` | `research.md` or `--max-time` CLI flag |
| Objectives reached | Every Optimize metric with a defined `target` has met or exceeded that target | `research.md` metrics config |
| Plateau | The last `stop.plateau_window` consecutive non-crash experiments all have `status: discard` (no improvement in K attempts) | `research.md` |
| Consecutive crashes | The last `stop.consecutive_crash_limit` experiments all have `status: crash` | `research.md` |

Notes:
- Crashed experiments are excluded from the plateau window count (only `keep`/`discard` experiments count)
- The consecutive crash limit counts only uninterrupted crash streaks — a single non-crash experiment resets the counter
- If no stop condition is triggered, continue to Step 8

### Step 8: Loop or halt

**If no stop condition triggered**:
- If within the same session and context budget allows: return to Step 2 (propose next experiment)
- If the session is ending (context pressure, agent stop event) and `hook.enabled` is `true`: the stop hook will re-trigger the skill on the next turn. On re-entry, the agent re-reads `research.md` and the last 10 entries of `research-log.jsonl` to rebuild context: context is rebuilt from disk, never from a previous session's memory.
- If the session is ending and `hook.enabled` is `false`: print a pause summary (experiments completed so far, current best metrics) and exit. The user must manually re-invoke `/qauto-research run` to continue.

**If a stop condition triggered**:
1. If `hook.enabled` is `true`: remove the auto-research stop hook entry from the user-level hook config to prevent further re-invocations. If the stop-hook array becomes empty after removal, remove it; remove the `hooks` key only if nothing else is left under it.
2. Print the summary report (see below)
3. Exit

### Summary report

When the loop ends (any stop condition met), print a structured summary:

```
--- Auto-Research Complete ---

Stop reason: <which condition triggered>
Total experiments: <N> (excluding baseline)
  Kept: <count>
  Discarded: <count>
  Crashed: <count>
Time elapsed: <HH:MM:SS>

Best metrics achieved (last-known-good):
  <metric_name>: <value> <unit> (direction: <lower|higher>)
  <metric_name>: <value> <unit> (direction: <lower|higher>)
  ...

Baseline metrics (experiment #0):
  <metric_name>: <value> <unit>
  ...

Improvement from baseline:
  <metric_name>: <baseline> -> <best> (<delta> <unit>, <percentage>%)
  ...

Research branch: research/<tag>
Last-known-good commit: <sha>
Log file: research-log.jsonl (on research/<tag> branch)
```

If the stop reason is "consecutive crashes", additionally print:
```
ROADBLOCK: <consecutive_crash_limit> consecutive crashes detected.
Last error: <error from most recent crash>
Manual investigation recommended before resuming.
```

---

## Git Exception

**This section is the canonical definition of the exception.** `shared/AGENTS.md § Commit Safety` bans `git commit --amend`, `git reset`, and `git revert` absolutely, "except where a documented exception exists" — this is that document, and it is the only one.

The `/qauto-research` skill operates in a dedicated git worktree on `research/*` branches. A scoped exception to the git-safety bans applies in this worktree — but ONLY for the specific operations enumerated below, and ONLY when invoked by the `/qauto-research` skill. The exception applies ONLY:

- On branches matching `research/*` (hardcoded prefix)
- In the dedicated worktree created by the skill (not the main working tree)
- When invoked by the `/qauto-research` skill (Setup or Run mode)

**Allowed operations by mode**:

- **Setup mode**:
  - `git worktree add` (with or without `-b`) — for creating the research worktree (Step 8); the `-b` form is used when the `research/<tag>` ref does not yet exist
  - `git commit` on the `research/<tag>` branch — for the baseline log entry written in Step 9
- **Run mode**:
  - `git reset --hard <sha>` — for reverting to a known-good commit after a failed or discarded experiment
  - `git commit` on the `research/<tag>` branch — for experiment commits and per-experiment log entries
- **Both modes** (rare, user-driven cleanup only):
  - `git worktree remove` — only when the user explicitly requests cleanup of the research worktree

All other git safety rules remain in force within the research worktree.

## Rules

Rules that are not stated in a step above:

- Never run `git reset` outside the dedicated research worktree or on non-`research/*` branches
- Log access from main branch: `git log research/<tag> -- research-log.jsonl` or check out the research branch
- Apply the **Harness Improvement Capture** rule in `shared/AGENTS.md`
