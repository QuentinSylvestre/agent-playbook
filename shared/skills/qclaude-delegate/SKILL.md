---
name: qclaude-delegate
description: Delegate a hard, well-specified task or ask for a second opinion from a headless Claude Code session (`claude -p`, always in auto permission mode), from another harness such as Kiro or Codex, then verify the outcome yourself. A file-driven wrapper starts each turn, waits for it, records the events and reports refusals and an estimated usage. Use when the result is checkable and the task is worth a full session start; not for small tasks, tasks that need the user mid-run, or anything needing a secret in the prompt.
argument-hint: "<task to delegate>"
---

# Delegate to a headless Claude Code session

## Your role

Hand a task to a Claude Code session, keep its transcript out of your context, and stay responsible for what it does. Behaviour that overrides your defaults:

- **You own the outcome.** The delegate acts with the user's privileges. Delegate only what you would do yourself under the same rules, and check the result against the artifact of record (git state, a file, a guard's exit code), never against the delegate's report.
- **The delegate runs in `auto` mode, always.** The wrapper passes `--permission-mode auto` and fails the turn if the session's init event reports another mode. Claude Code's own permission check decides each tool call; you cannot widen or narrow it. A refused call comes back in `permission_denials` of `result-NNN.json` and in the waiter's `refused:` lines. Never re-issue the refused action yourself or tell the delegate to find another route: the check exists to stop that. (Measured on Claude Code 2.1.302, 2026-10-17: an ordinary file write was accepted and `rm -rf ../victim .` was refused by a built-in safety check.)
- **Usage is an estimate, never a spend.** `total_cost_usd` is Claude Code's API-price figure and a running total for the session; `result-NNN.json` and the waiter show both this turn's part and the session total. Report it as "estimated usage (API-price equivalent; not billed on a subscription)" when the waiter's note says `apiKeySource is none`; when the note says the account may be billed, say that instead. Never call it cost. `--max-budget-usd` is not wired and is not relied on.
- **Governance travels with the task.** A commit the delegate makes follows `## Commit Conventions` (no attribution of any kind); `/qconfig-sync` runs only on the user's request; client names and secrets stay out of the brief.

**When NOT to use**: a task smaller than writing its brief (a fresh session start costs about $0.17 estimated usage even for a one-sentence answer; a resumed turn adds much less, about $0.014 for one short turn; both measured on Claude Code 2.1.302, subscription, 2026-10-17); a task whose next step depends on the user's answer (the delegate cannot reach the user); a review or design call you would have to judge yourself; work needing a secret in the prompt.

`<python>` below is `<config-repo>\.venv-agent-playbook\Scripts\python.exe -I` (`shared/AGENTS.md § Config Repo Locations`); `<scripts>` is this skill's `scripts/` folder as an absolute path; `<work>` is a fresh folder in your scratch space, one per delegation; `<folder>` is the session working directory, the same on every turn.

## Process

1. **Write the brief** as a UTF-8 file. Include: the task; the facts you already checked, so the delegate does not stop to ask; files and paths out of scope, named, with "do not stage, stash, commit, restore or delete"; the conditions on which it must stop and report instead of acting (a guard FAIL, anything it wants to commit, any destructive step, a refused tool call); what to report at the end (shas, exit codes, the paths it changed). It reaches the delegate on stdin, so quoting and length do not matter.
2. **Start turn 1** in the background: `<python> <scripts>/claude-delegate.py run --work <work> --cwd <folder> --prompt-file <brief> [--model M] [--effort low|medium|high|xhigh|max] [--timeout S]`. A `--model` is checked against the init event (an alias such as `sonnet` must appear in the reported id as whole hyphen-separated words; effort cannot be checked). The default `--timeout` is 1800 s. When the turn fails (a failed check, a timeout, a nonzero exit, a missing init or result event) it writes `FAILED-NNN` ending in a `Next action:` line and exits 1; a bad argument or a busy folder exits 2 and writes nothing.
3. **Wait** with one command, always naming the turn: `<python> <scripts>/claude-delegate.py wait --work <work> --turn N [--timeout S]`. Exit 0 is a finished turn (read `reply-NNN.txt`; `result-NNN.json` holds the session id, `num_turns`, the estimate and the refusals); 1 a failed turn (read the printed `reason` and `next`; a result that is an error or exits nonzero is a failed turn, not a finished one); 2 your timeout (wait again); 3 a dead run (read the end of `events-NNN.jsonl` and `run-NNN.log`, start a new `<work>`); 5 no such work folder.
4. **Follow up** with a new brief file and `run --work <work> --cwd <folder> --prompt-file <brief2> --continue-work`: it resumes the session in `<work>/session.txt` as turn N+1 and fails if another session id comes back. Start a follow-up only after the previous turn finished; a busy folder is refused (exit 2). Relay to the user any question that is theirs to decide; never answer it for them.
5. **Verify** the claimed outcome yourself. Relay to the user the result, every refusal, the usage estimate as above, and anything the delegate reported but you could not confirm.

## Rules

- One task per work folder; its turns are `001`, `002`, ... and every file is kept (`events-NNN.jsonl`, `reply-NNN.txt`, `result-NNN.json`, `stderr-NNN.log`).
- The wrapper kills only the claude process tree it started, on timeout, signal or its own death. Never stop the delegate by killing processes by name. Coverage limit: the POSIX process-group kill (including the one after a normal exit) has been reviewed but not run; the selftest ran on Windows only.
- The wrapper redacts the values of environment variables named like a token, key, secret or password, bearer text and `sk-ant-` strings from every file it writes; do not paste a secret into a brief.
- After any change to the wrapper, run `<python> <scripts>/selftest.py` (a stand-in claude, no network; two to three minutes on Windows, because it ends by re-running groups against mutants of the wrapper). It ends with mutants of the wrapper that the suite must catch.
