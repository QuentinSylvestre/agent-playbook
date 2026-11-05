---
name: qkiro-delegate
description: Delegate a well-specified, token-heavy task (for example a skill run such as /qconfig-sync) to a kiro-cli agent over ACP, then verify its outcome yourself. A file-driven driver starts the session, sends prompts, waits for each turn and logs every permission request. Use when the work is mechanical and its result can be checked; not for tasks that need the user's approval mid-run or judgment you must make yourself.
argument-hint: "<task to delegate>"
---

# Delegate to a kiro-cli agent

## Your role

Hand a task to a kiro-cli agent, keep its transcript out of your context, and stay responsible for what it does. Behaviour that overrides your defaults:

- **You own the outcome.** The delegate acts with the user's privileges. Delegate only what you would do yourself under the same rules, and check the result against the artifact of record (git state, a file, a guard's exit code), never against the delegate's report.
- **All tools are trusted by default**, as in PowerAtlas (user decision, 2026-10-17). Every permission request and decision is still logged. Write `<work>/policy.json` only to tighten: a `deny` rule wins, and `"default": "reject"` switches to allowlist mode. The format is in the driver's header (`scripts/acp-driver.py`). Command rules (`command_prefix`, `command_contains`) are best-effort: there is no shell parser, so `pwsh -Command`, `git -C`, `cmd /c`, an env prefix or quoting get past them; prefer `capability`, `resource` and `path_under` rules, and put what the delegate must not do in its brief. On a machine whose `~/.kiro/settings/permissions.yaml` is `all: allow`, kiro-cli sends no permission request at all (observed 2026-10-17, kiro-cli 2.32.0, in two delegated runs), so a policy has no effect there until you bind a mode that asks (`--mode`).
- **Governance travels with the task.** A commit the delegate makes follows `## Commit Conventions` (no attribution of any kind); `/qconfig-sync` runs only on the user's request; client names and secrets stay out of the brief.

**When NOT to use**: a task whose next step depends on the user's answer (the delegate cannot reach the user); a review, design call or anything else you would have to judge yourself; work needing a secret in the prompt; a task smaller than writing its brief.

`<python>` below is `<config-repo>\.venv-agent-playbook\Scripts\python.exe -I` (`shared/AGENTS.md § Config Repo Locations`); `<scripts>` is this skill's `scripts/` folder as an absolute path; `<work>` is a fresh folder in the session scratchpad or the store scratch folder (`shared/skills/qdream/memory-rules.md § Store scratch folder`), one per delegation.

## Process

1. **Write the brief** as `<work>/in/001.txt`, written to `001.tmp` first and renamed to `001.txt`; never write `in/NNN.txt` directly (a half-written prompt would be sent, and the driver ignores any stem that is not three digits). Include: the task (a skill invocation such as `/qconfig-sync` is passed as typed); the facts you already checked, so the delegate does not stop to ask (for example "0 behind, 38 ahead, no pull needed"); files and paths out of scope, named, with "do not stage, stash, commit, restore or delete"; the conditions on which it must stop and report instead of acting (a guard FAIL, anything it wants to commit, any destructive step); what to report at the end (shas, exit codes).
2. **Start the driver** in the background: `<python> <scripts>/acp-driver.py run --work <work> --cwd <session-folder> [--model <model-id>] [--effort <level>]`. Use the executable directly, without a shell or process-replacing wrapper. The driver binds mode `kiro_default`, selects requested model/effort through ACP session configuration, and verifies readback before sending a prompt. Omitted values keep the session defaults. Pass `--effort max` when maximum effort was requested: the terminal's effort default need not carry into ACP. Unsupported values, missing or mismatched readback, later configuration drift and timeouts produce `FAILED` and exit 1 (`--turn-timeout`, default 1800 s; `--total-timeout`, default 7200 s). On a host that ends detached children with the launching shell, keep `run` in a managed background command session; use the separate `wait` command for progress.
3. **Wait** with one command: `<python> <scripts>/acp-driver.py wait --work <work> [--turn N] [--timeout S]`. Exit 0 is a finished turn (read `out/NNN.txt`); 1 a failed run (read `FAILED`: it ends with a `Next action:` line; a JSON-RPC error reply to a prompt is a failed run, not a finished turn); 2 your timeout (wait again); 3 a dead driver (read the end of `events.log`, start a new `<work>`); 4 the run was stopped (`in/stop`) before that turn finished; 5 nothing to wait for (no `in/NNN.txt` yet).
4. **Answer** by writing the next `in/NNN.txt` the same way, then wait for that turn. Relay to the user any question that is theirs to decide; never answer it on their behalf.
5. **Verify** the claimed outcome yourself, then **stop**: write an empty `<work>/in/stop`. Relay to the user the result, any permission refusal logged in `events.log` or appended to the out files, and anything the delegate reported but you could not confirm.

## Rules

- One delegate per work folder; a second task gets a new `<work>`.
- The driver kills only the kiro-cli process tree it started. Never stop the delegate by killing processes by name. POSIX runs require a standalone main-thread CLI, with no concurrent child reaper. The driver resets inherited SIGCHLD auto-reaping and uses waitid/WNOWAIT or BSD/macOS kqueue; failed observation or lost child ownership stops the run.
- The driver redacts the KAS token and profile ARN from every file it writes; do not paste either into a brief.
- After any change to the driver, run `<python> <scripts>/selftest.py` (a stand-in kiro-cli; seconds, no network).
- Measured on Kiro CLI 2.33.1 with the v3 engine: model and effort CLI flags are rejected. Measured on kiro-cli 2.16.0 (`memory/topics/kiro-cli.md`): `--model` is accepted for the first session of a process only, then silently reverts to `chat.defaultModel` on every later `session/new`. Neither version's flag behaviour is relied on. The driver uses `session/set_config_option`, as in PowerAtlas's ACP implementation, and retains the agent's advertised options as the authority. Do not modify global settings or silently lower effort to repair a failed launch.
