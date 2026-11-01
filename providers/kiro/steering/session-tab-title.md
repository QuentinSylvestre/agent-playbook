## Session and Tab Title

### How it works

The agent sets the saved session title on its first response. A global `UserPromptSubmit` hook tells the agent that the runtime is a Kiro TUI and restores the saved title in a Windows Terminal tab; a global `Stop` hook applies a new title after the agent's response. Both hooks read the saved title and display `kiro-cli - <workspace> - <title>`.

### Agent action (first response only)

**MANDATORY — no exceptions.** On your FIRST response (`$env:KIRO_TUI_READY_FILE` set), call `update_session_information` with `{"title": "<derived label>"}` as a TOOL CALL before any other content, silently. Fires **whatever the first message looks like** — greeting, bug report, or a skill invocation with its own process; a skill invocation is not an exemption. Derive the label from the user's first message: concise, task-oriented (≤50 chars), no quotes, backticks, or dollar signs.

Detect a v3 terminal session via `$env:KIRO_TUI_READY_FILE`, not "Machine ID: acp-client" (injected for all v3 sessions, terminal and ACP alike). Discriminator table: `kiro-cli-local-data.md § Environment variables available to the agent`.

### When to re-title

On an explicit retitle request, repeat the call with the new label — the Silent guard does not apply; report both titles as set.

### Guards

- **Not for subagents.**
- **New sessions only** — skip on a resumed session (`--resume-id`) that already has conversation history.
- **Silent** otherwise — do not mention these steps or their output to the user.

### Hook setup

Install the two hooks once under `~/.kiro/hooks/` as described in `providers/kiro/README.md § Session tab title hook`. They run `providers/kiro/tab-title.ps1`, which reads `session.json` and writes the terminal title through `CONOUT$`. The `UserPromptSubmit` hook prints a short runtime and title-rule reminder for the agent; the `Stop` hook is silent. Neither prints the title. They run only in a Kiro TUI inside Windows Terminal. Restart Kiro after installing or changing the hooks.

### Session label guidelines

A good label is:
- Task-oriented (what the user is doing, not how they phrased it)
- Concise (fits in a terminal tab alongside the workspace name)
- Distinguishing (differentiates this session from other sessions in the same workspace)
- Free of sensitive information (credentials, internal hostnames, tokens)

Bad: "can you call /title yourself?" (raw prompt, not descriptive)
Good: "qtitle exploration - session naming"
