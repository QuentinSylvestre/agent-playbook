---
name: qfewer-permission-prompts
description: Analyze session history and trust config to suggest, clean up, and apply permission rules for Kiro IDE or CLI (context-detected). Reduces repeated permission prompts.
argument-hint: "<optional: audit | cleanup>"
---

# Fewer Permission Prompts

## Your role

You reduce permission prompt fatigue by analyzing past session data and existing trust configuration, then suggesting smart, risk-classified permission rules for the user to approve. You detect whether you are running in Kiro IDE or kiro-cli and manage permissions for that context only. IDE mode manages trusted tools, trusted commands, and command denylist. CLI mode manages `~/.kiro/settings/permissions.yaml` rules (v3, current); for old sessions only, it can also manage agent definition `allowedTools`/`toolsSettings` (v2, retired 2026-09-20 — see `## CLI engine detection (v3 vs v2)`). You never auto-approve anything -- every change requires explicit user consent.

## Mode

$ARGUMENTS

Supported modes:
- **(no argument)**: Full analysis -- audit existing config, mine session history, suggest new rules, offer cleanup. This is the default.
- **audit**: Audit-only -- review existing trust config for high-risk patterns and cleanup opportunities. No session mining, no new suggestions.
- **cleanup**: Cleanup-only -- consolidate redundant trusted commands into wildcard patterns (IDE); review `permissions.yaml` rules for redundancy (CLI v3) or `allowedTools` for redundancy (CLI v2, retired — old store only). No new suggestions.

If the user passes `sync` as the argument, respond: "The `sync` mode has been removed. Use `(no argument)` for full analysis, `audit` for config review, or `cleanup` for consolidation."

## Platform detection

Detect the operating system to determine file paths:
- **Windows**: IDE settings at `%APPDATA%\Kiro\User\settings.json`, sessions at `%APPDATA%\Kiro\User\globalStorage\kiro.kiroagent\workspace-sessions\`
- **Linux/macOS**: IDE settings at `~/.config/Kiro/User/settings.json` (or `$XDG_CONFIG_HOME/Kiro/User/settings.json`), sessions at equivalent XDG path

CLI paths use `~` on all platforms (`%USERPROFILE%` on Windows, per `providers/kiro/steering/memory-sources.md § v3 session location`):
- **v3 (current)**: permission rules at `~/.kiro/settings/permissions.yaml`; session data at `~/.kiro/sessions/<workspace-hash>/sess_<uuid>/` (workspace-hash directories only — `~/.kiro/sessions/cli/` is the v2 store, see below)
- **v2 (retired, old store only)**: agent definitions at `~/.kiro/agents/`, sessions at `~/.kiro/sessions/cli/`. kiro-cli v2 was retired 2026-09-20 — see `## CLI engine detection (v3 vs v2)` below and the "v2 (retired) — old store only" subsections throughout this skill. Kept only for mining old sessions.

## Context detection

Determine whether the skill is running in Kiro IDE or kiro-cli:

1. **Primary signal**: Check the system context / context entry for runtime identifier. If it contains "kiro-cli", operate in CLI mode. If it indicates Kiro IDE (or is absent), operate in IDE mode.
2. **Fallback**: If the context entry is ambiguous, check available tools. If `shell` tool is available, tentatively assume CLI mode. If `executePwsh` is available, IDE mode.

**User confirmation gate (mandatory)**: Always confirm with the user before proceeding, regardless of detection confidence:
> "Detected: [kiro-cli | Kiro IDE] mode. Managing [CLI | IDE] permissions only. Proceed? (yes/no/switch)"

The user can override by saying "switch" or specifying the other context. This gate is never skipped. If the user says "switch", flip the detected mode and re-confirm with the new mode.

## CLI engine detection (v3 vs v2)

kiro-cli v2 was retired 2026-09-20; kiro-cli v3 is the only supported CLI. When context detection above selects CLI mode, determine the engine before Step 1:

1. **Filesystem signal**: `~/.kiro/settings/permissions.yaml` exists → v3. Only `~/.kiro/agents/*.json` with `allowedTools`/`toolsSettings` exists and no `permissions.yaml` → legacy v2 data (forensics only).
2. **Env-var signal** (when running inside a live kiro-cli session): `KIRO_SESSION_ID` set (bare UUID) → v2. `KIRO_SESSION_ID` not set and `KIRO_AGENT_ENGINE=kas` → v3 (`providers/kiro/steering/kiro-cli-local-data.md § Environment variables available to the agent`).

Default to **CLI mode — v3 (current)** (the primary subsection under each step below). Only use **CLI mode — v2 (retired) — old store only** when the user explicitly asks to mine or clean up an old workspace's leftover v2 data, or when no `permissions.yaml` exists and only `~/.kiro/agents/*.json` is present. Confirm with the user using the same gate as above: "Detected: kiro-cli [v3 | v2 (retired)]. Proceed? (yes/no/switch)"

## Process

### Step 1: Gather current state

**IDE mode** (when context detection selected IDE):

1. **Read IDE settings**: Read the user-level settings file. Extract:
   - `kiroAgent.trustedTools` (array of tool names)
   - `kiroAgent.trustedCommands` (array of command patterns)
   - `kiroAgent.commandDenylist` (array of deny patterns, may be absent)
   - `kiroAgent.agentIgnoreFiles` (array of ignore patterns, informational)

2. **Collect deny rules**: Merge all deny rules into an immutable deny set:
   - `kiroAgent.commandDenylist` entries (substring match)

   These are NEVER modified. Any suggestion that conflicts with a deny rule is marked as BLOCKED.

3. **Report** the current state summary to the user: counts of trusted tools, trusted commands, and deny rules.

**CLI mode — v3 (current)** (when CLI engine detection selected v3):

1. **Read the permissions file**: Read `~/.kiro/settings/permissions.yaml`. Parse the `rules:` list — each entry has the shape `- capability: <value>` / `effect: <value>` (confirmed shape: the deployed seed at `providers/kiro/settings/permissions.yaml` — "rules: - capability: all / effect: allow"). If the file does not exist, report "No `~/.kiro/settings/permissions.yaml` found — kiro-cli v3 has not deployed a permissions seed here yet" and exit.

2. **Classify what's there**:
   - If the rules list is exactly the seed (`capability: all`, `effect: allow`) and nothing else: everything is currently auto-approved. There is nothing generating prompts to reduce — see the v3 framing under Step 2.
   - If the rules list has been edited (extra entries, or the seed narrowed/removed): report each entry as-is (`capability`/`effect` pairs). Do not infer what a non-`all` `capability` value means or whether it is valid — the vocabulary beyond `all` is unconfirmed (see the REVISIT note under Step 4).

3. **Report** the current state: file path, whether the seed is present unmodified, and the rule count if edited.

**CLI mode — v2 (retired) — old store only** (kiro-cli v2 was retired 2026-09-20; use only when CLI engine detection selected v2, i.e. mining or cleaning up an old workspace's leftover data):

1. **Detect CLI agent**: List `~/.kiro/agents/*.json`. If exactly one file exists, use it and echo the agent name to the user (e.g., "Using agent: kiro_default"). If multiple exist, ask the user which to manage. If none exist, report "No CLI agent definition found at ~/.kiro/agents/. Create one with `/qconfig-sync` or copy from `providers/kiro/agents/`." and exit.

2. **Read CLI agent definition**: Extract `tools` (full tool list), `allowedTools` (auto-approved tools), and `toolsSettings` (deny rules). **This `allowedTools` mechanism is retired** — v3 does not read it from the agent definition; it is preserved here only for auditing or mining old v2 agent definitions.

3. **Collect deny rules**: Extract all `deniedPaths` and `deniedCommands` entries from `toolsSettings`. These are NEVER modified.

4. **Report** the current state: count of tools, count of allowedTools, count of deny rules, agent name.

### Step 2: Audit existing trust config

Analyze the current trusted commands and tools for issues:

**High-risk pattern detection** -- flag any existing entry matching these patterns:
- `*` alone (universal wildcard) -- Critical risk
- `rm *`, `del *`, `Remove-Item *` -- High risk (destructive)
- `sudo *` -- High risk (privilege escalation)
- `curl *`, `wget *`, `Invoke-WebRequest *` -- High risk (network exfiltration)
- `eval *`, `exec *` -- High risk (arbitrary execution)
- `chmod *`, `chown *` -- High risk (permission changes)
- `docker *` -- High risk (container escape potential)
- `python *`, `node *`, `python3 *` -- High risk (arbitrary code execution via interpreter)
- `powershell *`, `pwsh *`, `cmd /c *` -- High risk (arbitrary shell execution)
- `ssh *`, `scp *`, `rsync *` -- High risk (remote access / data exfiltration)
- `nc *`, `ncat *`, `netcat *` -- High risk (network backdoor)
- `pip install *`, `npm install *` -- High risk (arbitrary code via install hooks)
- `git push *`, `git remote *` -- High risk (code exfiltration)
- `reg *`, `regedit *`, `sc *`, `net *` -- High risk (Windows system modification)
- `crontab *`, `schtasks *` -- High risk (persistence via scheduled tasks)
- `iptables *`, `ufw *` -- High risk (firewall modification)
- Commands containing `| sh`, `| bash`, `| powershell` -- High risk (pipe to shell)
- Commands with `> /qdev/` or `>> /qdev/` -- High risk (device writes)
- `mkfs *`, `dd *` -- High risk (disk operations)

**Consolidation opportunities** -- identify groups of specific commands that share a common prefix AND the same risk level, then suggest replacing them with a single wildcard pattern. Never consolidate across risk levels. For example:
- `git status`, `git log *`, `git diff *`, `git show *` (all Low risk) -> suggest keeping as individual Low-risk entries, or consolidate read-only git commands
- `npm run *`, `npm test *` (both Medium risk) -> suggest `npm run *` and `npm test *` individually (do NOT suggest `npm *` because `npm install *` is High risk)
- Multiple `.venv/Scripts/python -m pytest *` variants (Medium risk) -> suggest `.venv/Scripts/python -m pytest *`
- Multiple `Get-Content "specific-path"` entries (Low risk) -> suggest `Get-Content *` (Low risk)

**Redundancy detection** -- find entries that are already covered by a broader pattern. For example, if `git *` is trusted, then `git status` is redundant.

Present findings in a table:

```
## Audit Findings

### High-Risk Patterns (review recommended)
| # | Pattern | Risk | Reason |
|---|---|---|---|

### Consolidation Opportunities
| # | Current entries | Suggested replacement | Risk | Entries removed |
|---|---|---|---|---|

### Redundant Entries (safe to remove)
| # | Entry | Covered by | Action |
|---|---|---|---|
```

**CLI mode audit — v3 (current)**:

Because the seed rule (`capability: all` / `effect: allow`) auto-approves everything, "audit" in v3 means reviewing how permissive `~/.kiro/settings/permissions.yaml` currently is, not finding prompted tools:

- If the rules list is exactly the seed: flag it as **Critical risk (by design)** — equivalent to v2/IDE's standalone `*` wildcard, since it allows every capability unconditionally. This is the deployed default (`providers/kiro/settings/permissions.yaml`), not a misconfiguration, so present it as "expected default, review recommended" rather than "error."
- For any other `capability` value present in the rules list: report it, but do **not** assign it a risk tier — the vocabulary of `capability:` values beyond `all` is unconfirmed in the files this skill can read. Mark each such entry `**UNVERIFIED**` in the audit table and point at the REVISIT note under Step 4.
- `effect: allow` is the only confirmed effect value (the seed). Whether `effect: deny` is honoured by v3 at all is unconfirmed; treat any existing `effect: deny` entry the same way — report it, do not assume it works as a v2-style deny rule.

Present findings in the same `## Audit Findings` table format as IDE mode, substituting "Rule (`capability`/`effect`)" for "Pattern".

**Consolidation/redundancy** in CLI v3 mode: not attempted until the `capability:` vocabulary is confirmed — consolidating a specific value into a broader one requires knowing which values are more specific than others.

**CLI mode audit — v2 (retired) — old store only**:

Classify each tool in `allowedTools` by risk:

| Risk | CLI tools |
|---|---|
| Low | `read`, `grep`, `glob`, `code`, `knowledge`, `web_fetch`, `web_search`, `introspect`, `todo_list` |
| Medium | `write`, `subagent` |
| High | `shell`, `use_aws`, any tool starting with `browser_` (MCP tools with arbitrary web interaction — treat as High due to MCP trust boundary) |

Flag any High-risk tool in `allowedTools` for user awareness. Present the same audit table format as IDE mode.

**Consolidation/redundancy** in CLI mode: `allowedTools` is a flat list with no wildcards, so consolidation opportunities are limited to detecting tools listed in `allowedTools` that are not in `tools` (stale entries).

If mode is `audit`, STOP here after presenting findings. Ask the user which cleanup/removal actions to approve, then skip to Step 5.

### Step 3: Mine session history

**Scope**: Read the most recent sessions (up to 20 session files per workspace, or sessions from the last 30 days, whichever is smaller).

**IDE mode**:

1. List workspace subdirectories under `%APPDATA%\Kiro\User\globalStorage\kiro.kiroagent\workspace-sessions\`
2. For each workspace, list session `.json` files sorted by modification date (most recent first)
3. For each session file, extract tool calls and shell commands using string/regex search:
   - Tool names: search for `"name":"<toolName>"` patterns in tool_use blocks
   - Shell commands: search for `"command":"<cmd>"` patterns in executePwsh/execute_bash tool inputs
4. Collect unique tool names and command prefixes (normalize by stripping arguments to get the base command pattern)

**CLI mode — v3 (current)**:

Locate and mine v3 session data per `providers/kiro/steering/memory-sources.md § Discovery (orchestrator)`:

1. Enumerate workspace-hash directories under `~/.kiro/sessions/` (exclude `cli/`, which is the v2 store)
2. For each workspace-hash dir, enumerate `sess_*/session.json` files; read `workspacePaths[0]` to confirm the directory matches the current project (`providers/kiro/steering/kiro-cli-local-data.md § Session metadata`)
3. Sort by `lastModifiedAt`, cap at 20 most recent sessions or last 30 days, whichever is smaller (same cap as v2/IDE)
4. For each session, read `sess_<uuid>/messages.jsonl`. Each line is `{"id","timestamp","payload":{"type":...}}` (`providers/kiro/reference/kiro-cli-v3-internals.md § Message format`)
5. Extract tool calls from lines where `payload.type == "tool_call"`: read `.toolName`, `.kind`, `.status`. Confirmed v3 tool names: `execute_pwsh`, `read_file`, `fs_write`, `list_directory`, `grep_search`, `file_search`, `delete_file`, `orchestrate_subagent`, `update_session_information` (`providers/kiro/reference/kiro-cli-v3-internals.md § Tool naming (v3)`)
6. Compute frequency of each tool name across all sessions
7. **Surface friction, not "untrusted" tools**: with the seeded `capability: all` / `effect: allow` rule, nothing gets prompted or denied by default, so v3 has no direct analog of v2's "tool appears in sessions but not in allowedTools." Instead, report `tool_call` entries whose `.status` is `"denied"` — these are the cases where something actually was refused (e.g., a narrowed permissions.yaml rule, or an ACP-level `session/request_permission` rejection). This is the closest v3 equivalent of "prompted tools."
8. Sort the frequency table by count (most-used first). This is descriptive context for Step 4, not a list of tools to auto-approve — see the REVISIT note there before proposing any `capability:` value.

**CLI mode — v2 (retired) — old store only**:

1. List `.jsonl` files in `~/.kiro/sessions/cli/` sorted by modification date (most recent first)
2. Cap at 20 most recent files or last 30 days, whichever is smaller
3. For each `.jsonl` file, read lines and parse each as JSON. The canonical schema is:
   - Tool calls: `{"version":"v1","kind":"AssistantMessage","data":{"content":[{"kind":"toolUse","data":{"name":"<tool-name>","input":{...}}}]}}`
   - Tool results: `{"version":"v1","kind":"ToolResults","data":{"content":[{"kind":"toolResult","data":{"toolUseId":"...","content":[...],"status":"success"}}]}}`
4. Extract tool names from `AssistantMessage` lines: parse `data.content[]` where `kind` is `"toolUse"`, read `data.name`
5. **Filter**: Only keep tool names that appear in the agent definition's `tools` list. Discard sub-agent dispatch names (anything not in `tools`)
6. Compute frequency of each tool name across all sessions
7. Identify tools that appear in sessions but are NOT in `allowedTools` — these are tools that were prompted
8. Sort by frequency (most prompted first)

**Normalization** (IDE mode only): For each extracted command, derive a suggested trust pattern:
- Strip absolute paths to get the base command (e.g., `C:\...\python.exe -m pytest tests/` -> `python *` or `.venv/Scripts/python *`)
- Group similar commands by their base prefix
- Count frequency (how many times each pattern appeared across sessions)

**Output**: A frequency-sorted list of untrusted tool/command patterns (not already in the trust config).

If mode is `cleanup`, skip this step.

### Step 4: Generate suggestions

**IDE mode**:

For each untrusted pattern from Step 3, classify risk:

| Risk | Criteria | Examples |
|---|---|---|
| Low | Read-only operations, no side effects, information display | `cat *`, `type *`, `Get-Content *`, `ls *`, `dir *`, `git status`, `git log *`, `wc *`, `head *` |
| Medium | Scoped writes, common dev tools with limited blast radius, build/test commands | `npm run *`, `npm test *`, `pip show *`, `make *`, `cargo build *`, `ruff *`, `git add *`, `git commit *`, `git diff *`, `.venv/Scripts/python -m pytest *` |
| High | System-wide writes, network access, destructive operations, privilege escalation, bare interpreter wildcards | `rm *`, `sudo *`, `curl *`, `docker *`, `Start-Process *`, `python *`, `node *`, `pip install *`, `npm install *`, `git push *`, `ssh *` |

For each suggestion, check against the deny set:
- If the suggestion matches a deny rule, mark it as **BLOCKED** and include the reason (which deny rule it conflicts with)
- BLOCKED suggestions are shown to the user for information but cannot be approved

**For tools** (IDE `trustedTools` and CLI `allowedTools`):
- Tools like `executePwsh`, `controlPwshProcess` are Medium risk (shell execution)
- Tools like `deleteFile`, `smartRelocate` are Medium risk (destructive file operations)
- Tools like `semanticRename`, `createHook` are Low risk (code refactoring, automation)
- Tools like `invokeSubAgent`, `webFetch`, `remote_web_search` are Low risk (read/analysis)

Present suggestions grouped by risk:

```
## New Permission Suggestions

### Low Risk (read-only, no side effects)
| # | Type | Pattern | Frequency | Approve? |
|---|---|---|---|---|

### Medium Risk (project writes, dev tools)
| # | Type | Pattern | Frequency | Approve? |
|---|---|---|---|---|

### High Risk (system writes, network, destructive)
| # | Type | Pattern | Frequency | Approve? |
|---|---|---|---|---|

### Blocked (conflicts with deny rules)
| # | Type | Pattern | Deny rule | Reason |
|---|---|---|---|---|
```

Ask the user to approve:
- Per-group: "Approve all Low risk?" / "Approve all Medium risk?"
- Per-item: reference by number, e.g., "Approve #3, #5, #7"
- Or mixed: "Approve all Low, plus #12 and #15 from Medium"

**CLI mode suggestions — v3 (current)**:

If the rules list is still exactly the seed, first re-state the Step 1/Step 2 framing to the user: nothing is currently prompting, so this step is about *tightening*, not *reducing prompts* — ask whether they want to proceed before suggesting anything.

Verified on Windows 2026-09-21 (kiro-cli-chat 2.22.1, KAS bundle `node_modules/@kiro/agent/dist/server/acp-server.js`, source-searched — no `kiro-cli permissions` subcommand exists, so this was read from the shipped, minified rule-parser/policy-eval code, not exercised live):
- **`capability:` vocabulary is closed and confirmed** — exactly 15 values: `all`, `builtin`, `filesystem`, `fs_read`, `fs_write`, `shell`, `web_fetch`, `web_search`, `mcp`, `subagent`, `skill`, `power`, `context`, `diagnostics`, `sandbox_network`. The rule parser validates each rule's `capability` against this fixed set and drops (with a warning) any rule naming a value outside it — `Skipping rule ${n} in ${r}: unknown capability "${o.capability}"`.
- **`effect:` has three values, not two** — `allow`, `deny`, `ask` (the parser rejects anything else with `Invalid effect "..."`).
- **`effect: deny` is genuinely enforced, not merely parsed.** The policy-evaluation path (`acp.policy-eval.deny` debug event) converts `effect: deny` directly into `{decision: "reject", ...}`, and the "most restrictive result" resolver always prefers a `deny` match over `ask` or `allow` when multiple rules match the same call. Rules are also compiled into Cedar policy syntax under the hood (`effect==="allow" ? "permit" : "forbid"`), consistent with the bundle shipping `@cedar-policy/cedar-wasm`.
- **No per-tool capability values exist.** The vocabulary above is subsystem/category-level (e.g. `fs_read` covers all read-type file tools, `shell` covers all shell execution) — there is no `read_file`-specific or `execute_pwsh`-specific capability. A rule's `capability` also accepts optional `match`/`exclude` fields (string arrays) for narrowing within a category, per the same parser.

With the vocabulary now confirmed, the skill MAY propose rules using the confirmed shape — `- capability: <value from the 15 above>` / `effect: <allow|deny|ask>` — appended to or replacing entries in the same `rules:` list as the seed. Still always show the diff (Step 5) and get explicit approval before applying; the tool-usage frequency table from Step 3 (v3) names v3 **tool** names (`execute_pwsh`, `read_file`, etc.), which map to a `capability` category (e.g. both to `fs_read`/`shell`) but are not themselves `capability` values — translate before proposing a rule, don't paste the tool name in directly.

**CLI mode suggestions — v2 (retired) — old store only**:

For each prompted tool (from Step 3, v2), classify risk using the CLI risk table from Step 2 (v2). Present suggestions grouped by risk, same format as IDE mode but with "Tool" type only (no "Command" type in CLI).

Check each suggestion against deny rules (`toolsSettings.*.deniedPaths` etc.) — if a tool is in the deny set, mark as BLOCKED.

### Step 5: Show diff and apply

For each approved change:

1. **Back up** each file before modification: use timestamped backups (e.g., `settings.json.bak.20260421-1430`). Retain the last 3 backups; clean up older ones.

2. **Compute the diff** for each file. Show the user a clear before/after for each config key being modified:

   IDE mode example:
   ```
   ## Proposed Changes

   ### IDE Settings (%APPDATA%\Kiro\User\settings.json)

   kiroAgent.trustedTools:
     + "executePwsh"          (Medium risk -- approved)
     + "controlPwshProcess"   (Medium risk -- approved)

   kiroAgent.trustedCommands:
     + "npm run *"            (Medium risk -- approved)
     + "npm test *"           (Medium risk -- approved)
     + "Get-Content *"        (Low risk -- replaces 4 specific entries)
     - "Get-Content \"C:\\specific\\path\""  (redundant, covered by "Get-Content *")
   ```

   CLI mode example (v3, current):
   ```
   ## Proposed Changes

   ### CLI Permissions (~/.kiro/settings/permissions.yaml)

   rules:
     - capability: all
       effect: allow          (unchanged — kept as a catch-all, per user choice)
     + - capability: <approved value>
         effect: <approved value>   (approved — capability value supplied by the user; see REVISIT under Step 4)
   ```

   CLI mode example (v2, retired — old store only):
   ```
   ## Proposed Changes

   ### CLI Agent (~/.kiro/agents/kiro_default.json)

   allowedTools:
     + "write"                (Medium risk -- approved)
     + "web_fetch"            (Low risk -- approved)
   ```

3. **Ask for final confirmation**: "Apply these changes? (yes/no)"

4. **Apply**: Read each file, parse it in its native format (JSON for IDE settings and v2 agent definitions; YAML for v3's `permissions.yaml`), modify the relevant keys, serialize back with consistent formatting (2-space indent), write.

5. **Report**: Summarize what was changed, where backups are stored, and remind the user to run `/qconfig-sync` if the CLI agent definition source lives in the agent-playbook repo (since `~/.kiro/agents/` is a deployed copy).

**CLI mode apply — v3 (current)**:

1. Back up `~/.kiro/settings/permissions.yaml` with a timestamped backup (same pattern as IDE, e.g. `permissions.yaml.bak.YYYYMMDD-HHMM`).
2. Show diff: which `rules:` entries will be added, changed, or removed, in the seed's `capability`/`effect` shape.
3. Ask for final confirmation.
4. Read the file, modify the `rules:` list, write back preserving 2-space YAML list indentation matching the seed's style (`providers/kiro/settings/permissions.yaml`).
5. **Source file update offer**: `providers/kiro/settings/permissions.yaml` is a **seed file — setup.sh/setup.ps1 write it only when the deployed copy is absent** (per its own header comment). Updating `~/.kiro/settings/permissions.yaml` here does not change what future fresh deployments seed. Ask: "The permissions file at `~/.kiro/settings/permissions.yaml` is a one-time deployment seed. Would you like me to also update the source at `providers/kiro/settings/permissions.yaml` so new machines/workspaces get the tightened rule too?" If yes, apply the same change to the source file.

**CLI mode apply — v2 (retired) — old store only**:

1. Back up `~/.kiro/agents/<name>.json` with timestamped backup (same pattern as IDE).
2. Show diff: which tools will be added to `allowedTools`.
3. Ask for final confirmation.
4. Read the agent JSON, add approved tools to `allowedTools` array, write back with consistent formatting.
5. **Source file update offer**: "The CLI agent definition at `~/.kiro/agents/<name>.json` is a deployed copy. Would you like me to also update the source at `providers/kiro/agents/<name>.json` in the config repo?" If yes, apply the same change to the source file. **This `allowedTools` mechanism itself is retired in v3** — this apply path only makes sense when CLI engine detection selected v2 (old store only).

### Step 6: Report

Summarize the full session:
- Audit findings (high-risk patterns found, consolidations applied)
- New rules added (count by risk level)
- Backup file locations
- Reminder (v3): if `~/.kiro/settings/permissions.yaml` was modified, mention it is a one-time deployment seed — the source lives at `providers/kiro/settings/permissions.yaml` if the user wants future deployments to pick up the tighter rule too.
- Reminder (v2, retired — old store only): if CLI agent definition was modified at `~/.kiro/agents/<name>.json`, this is a deployed copy. To make the change permanent, also update the source at `providers/kiro/agents/<name>.json` in the agent-playbook repo and run `/qconfig-sync`. This `allowedTools` mechanism itself is retired — only relevant when mining/cleaning up old v2 data.

## Risk Classification Reference

| Risk | Criteria | Shell examples | Tool examples |
|---|---|---|---|
| Low | Read-only, no side effects | `cat *`, `ls *`, `git status`, `git log *`, `git diff *`, `wc *`, `head *`, `type *`, `Get-Content *` | `readFile`, `readCode`, `listDirectory`, `grepSearch`, `fileSearch`, `getProcessOutput`, `listProcesses` |
| Medium | Scoped writes, common dev tools with limited blast radius | `npm run *`, `npm test *`, `make *`, `cargo build *`, `git add *`, `git commit *`, `ruff *`, `.venv/Scripts/python -m pytest *` | `fsWrite`, `fsAppend`, `strReplace`, `executePwsh`, `controlPwshProcess`, `deleteFile`, `semanticRename`, `smartRelocate`, `createHook` |
| High | System-wide, network, destructive, privilege escalation, bare interpreter wildcards | `rm *`, `sudo *`, `curl *`, `docker *`, `python *`, `node *`, `pip install *`, `npm install *`, `git push *`, `ssh *`, `powershell *`, `Start-Process *` | (none built-in; MCP tools may qualify) |
| Critical | Universal access, known attack vector | `*` (standalone) | (trusting all tools) |

**v3 CLI note**: this table's "CLI tools" examples (here and in Step 2's CLI risk table) describe v2's `allowedTools` tool names — confirmed vocabulary for the retired v2 mechanism only. v3's `permissions.yaml` `capability:` vocabulary is a separate, unconfirmed set (see the REVISIT note under Step 4's "CLI mode suggestions — v3 (current)"). Do not read this table as covering v3 capability values.

## Rules

- NEVER add `*` as a standalone trusted command. If it already exists, flag it as Critical risk and recommend removal.
- NEVER modify deny rules (`kiroAgent.commandDenylist`, `toolsSettings.*.deniedPaths`, `toolsSettings.execute_bash.deniedCommands`). If a suggestion conflicts with a deny rule, mark it BLOCKED and explain why.
- NEVER apply changes without explicit user approval. Always show the diff first.
- ALWAYS back up files before modification. Use timestamped backups (e.g., `settings.json.bak.YYYYMMDD-HHMM`). Retain the last 3 backups; clean up older ones.
- ALWAYS preserve existing structure and formatting (JSON or, for v3's `permissions.yaml`, YAML) when modifying settings files. Only modify the specific keys being changed.
- ALWAYS re-read deny rules from the original file immediately before writing any modified config. If any deny rule is missing, modified, or reordered in the proposed output compared to the original, ABORT the write and report a safety violation. This is a defense-in-depth check.
- When consolidating commands into wildcard patterns, NEVER consolidate a command group into a single wildcard if the group contains sub-commands spanning multiple risk levels. For example, do not suggest `git *` -- instead suggest granular wildcards like `git log *` (Low), `git add *` (Medium), `git push *` (High).
- When suggesting tool trust, consider that trusting `executePwsh` or `execute_bash` without trusted command patterns means ALL shell commands are auto-approved -- flag this as High risk.
- If the CLI agent definition at `~/.kiro/agents/` was modified, immediately ask the user: "The CLI agent definition is a deployed copy. Would you like me to also update the source at `providers/kiro/agents/<name>.json`?" Do not bury this as a passive reminder. **This is a v2 (retired) mechanism** — only relevant when CLI engine detection selected v2 (old store only); v3 does not read `allowedTools` from the agent definition at all.
- If `~/.kiro/settings/permissions.yaml` was modified, immediately ask the user whether to also update the source seed at `providers/kiro/settings/permissions.yaml` (it is written only when the deployed copy is absent, so this is the only way a change reaches future deployments). Do not bury this as a passive reminder.
- NEVER propose a `permissions.yaml` `capability:` value that is not either `all` (the only confirmed value) or supplied directly by the user with a source they can point to. The full vocabulary is unconfirmed in this repo's read-only files — see the REVISIT note under Step 4's "CLI mode suggestions — v3 (current)." Guessing a value risks a silent no-op or a broken permissions file, since v3 is known to fail silently on malformed config shapes.
- When operating in CLI mode — v3 (current), always state plainly that a seeded `capability: all` / `effect: allow` rule means there is nothing currently being prompted — frame the work as tightening/hardening, not as "reducing permission prompts," so the user is not surprised when a narrower rule reintroduces prompts for anything it does not cover.
- Limit session analysis to recent sessions (last 20 per workspace, max 10 workspaces, or last 30 days) to keep execution time reasonable. Cap total session files at 100.
- Degrade gracefully if session files cannot be parsed (format changed, file corrupted, etc.). Report the count of failed files and continue with available data: "Could not parse N of M session files. Suggestions are based on M-N successfully parsed sessions."
- If the IDE settings file does not exist, create it with `{}`. If it exists but lacks `kiroAgent.*` keys, treat them as empty arrays. Report: "No existing trust configuration found -- starting fresh."
- If a config file cannot be read or written (permission denied, file locked), report the error with the specific path and show the intended changes as a copyable block the user can apply manually.
- After the user states their approvals, echo back the interpreted list for confirmation before proceeding to the diff: "I understood: approve items #1-#11 (all Low), #12, #15 (Medium). Correct?"
- When no argument is provided, briefly list available modes before proceeding: "Running full analysis. Tip: you can also run `/qfewer-permission-prompts audit` or `cleanup`."
- When a step produces no findings or suggestions, report it explicitly: "No high-risk patterns found", "All frequently-used tools are already trusted", "No redundant entries found."
- Session-mined commands must be validated before becoming suggestions: reject any extracted command matching the High-risk pattern list, reject commands containing pipe-to-shell patterns or encoded payloads, and default any unrecognized command to High risk. Only commands matching a known-safe prefix allowlist (git, npm, python, cargo, make, pip, ruff, node, etc.) may be suggested at Low or Medium risk.
- Only suggest commands that were actually executed (successful tool results), not commands that were rejected by the user or failed. If the session format does not distinguish executed from rejected, note this limitation.
- Detect the operating system by checking environment variables or running `uname -s` (Linux/macOS) or checking `$env:OS` (Windows).
- Linux/macOS IDE settings path (`~/.config/Kiro/User/settings.json`) is provisional. If the file is not found, check `~/.kiro/` and common Electron app data locations. Report if the settings file cannot be located.
