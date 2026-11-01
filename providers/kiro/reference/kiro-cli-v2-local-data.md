## Kiro-CLI v2 Local Data

> **Reference only — not deployed.** kiro-cli v2 is retired; this is the v2 session-store,
> agent-profile, hooks and ACP reference, kept for forensics on old sessions only. It loads on
> demand only — not in `inventory.tsv`, so it never reaches a session's context. **Read when**
> mining or recovering a v2 session store (`~/.kiro/sessions/cli/<id>.jsonl` + SQLite), or moving a
> workspace whose old v2 sessions must follow it (`§ Moving a workspace`). Indexed
> from `memory/topics/kiro-cli.md`.

> **Also read `memory/topics/kiro-cli.md` in the config repo** when *driving* kiro-cli rather than
> reading its files — ACP, agent definitions, CLI flags, v3 agent authoring. This file says where the
> data lives; that one records how the tool behaves, including three flags that accept invalid values
> in silence and a trust flag that is not the boundary its name implies.
>
> The pointer sits here rather than only in user memory's `## Topics` index because this file is what
> an agent is already reading when that knowledge becomes relevant. An index consulted at session
> start is a reminder the agent has to act on unprompted, later, about a task it did not yet have.

### Session files (primary conversation source)

`.jsonl` files at `~/.kiro/sessions/cli/`. These hold the vast majority of conversation content (measured 2026-05-22). Lines have `{"version":"v1","kind":"<kind>","data":{...}}` format. Known `kind` values:

- `"Prompt"` — user messages (text content in `data.content`)
- `"AssistantMessage"` — agent responses, including tool calls: `{"kind":"toolUse","data":{"name":"<tool-name>","input":{...}}}` in `data.content[]`
- `"ToolResults"` — tool execution output (verbose; skip when scanning for learnable signal)

Sub-agent dispatch names (e.g., `phase1_impl`, `senior_engineer_review`) appear as tool names but are not real tools — filter against the agent definition's `tools` list.

### Session metadata files

Each session has a co-located `.json` metadata file (same basename as the `.jsonl`). Schema:

| Field | Type | Description |
|---|---|---|
| session_id | string | Unique session identifier |
| cwd | string | Working directory at session start |
| created_at | string (ISO-8601) | Session creation timestamp |
| updated_at | string (ISO-8601) | Last activity timestamp |
| title | string | Session title. **Usually the raw first prompt, not a derived label** — see below. |
| parent_session_id | string or null | Non-null for true sub-agent sessions; null for user-initiated sessions. **Sole reliable sub-agent discriminator.** |
| session_created_reason | string or absent | Unreliable — sometimes `"subagent"` on user-initiated sessions that have no parent. Do NOT use for filtering. |

**On `title` — writable and stable.** The agent writes a label into this field via the `session-tab-title.md` snippet, and kiro-cli does **not** overwrite it. Measured 2026-08-18 on kiro-cli 2.18.x: file-watching a held ACP session over 10 s with the kiro-cli process confirmed live showed zero rewrites to the `title` field. The earlier finding (2026-07-31, kiro-cli 2.16.0, "exactly 1 of 11 kept its derived label") was measuring sessions whose first prompt became the title by default — not a rewrite, but a `title` field that was never populated by the agent in the first place. Use the atomic write pattern to set it reliably: write to a `.pa-renaming` temp file, then `Move-Item` rename onto the original. A direct `WriteAllText` (truncate-then-write) could race with PowerAtlas's directory scanner, which cached a failed parse at the new mtime/size; PowerAtlas stopped reading the v2 store on 2026-09-17 (its `docs/KNOWLEDGE.md`, kiro-cli v2 store), so that race no longer applies, but the atomic pattern is still the safe write.

### Secondary / legacy — conversation database

`%LOCALAPPDATA%\Kiro-Cli\data.sqlite3` (Windows) / `~/.local/share/kiro-cli/data.sqlite3` (Linux). Table: `conversations_v2` (key TEXT = working directory, conversation_id TEXT, value TEXT = full JSON, created_at INTEGER, updated_at INTEGER). This DB holds only a small fraction of data (specific agent configurations); prefer the session files above for conversation content. The `key` column stores Windows paths with mixed case — use COLLATE NOCASE for matching. Conversations can be 44KB+ each.

Its rows are **not** duplicated on disk: measured 2026-07-24, all 11 `conversations_v2` conversation ids had no `.json` and no `.jsonl` anywhere, and appeared in neither a filesystem scan nor the ACP session list. They surface only via `--list-sessions`, tagged `"source":"classic"`. Open it read-only (`file:...?mode=ro`) or against a copy — never lock the live DB.

### Session lock files — liveness and session identity

`~/.kiro/sessions/cli/<session-id>.lock`, content `{"pid":<int>,"started_at":"<RFC3339>"}`. This is the only local artifact that maps a **session id to a live process**; the session id is the filename stem and `cwd`/`title` come from the co-located `.json`.

**A lock file's presence does not mean the session is live.** Locks are not reliably removed — a clean ACP shutdown deletes its own, but a terminal that exits by another path leaves one behind. Measured 2026-07-24: **785 lock files, 21 with a currently-alive pid, exactly 1 genuine.** The other 20 were PID reuse, their pids belonging to `svchost.exe`, `firefox.exe`, `RuntimeBroker.exe`, `Kiro.exe`.

**Both clauses are required to determine liveness:**

1. the pid is alive, **and**
2. `|started_at − process.create_time()| < tolerance`.

Separation is wide enough to be unambiguous — the genuine lock was off by **1.2 s**, the closest impostor by **9,547 s**, most by millions. Any tolerance from ~30 s to an hour is correct.

Two further caveats: the pid in the lock is the `kiro-cli acp` **grandchild**, not the process the user launched (see Process model), so anything that wants to signal or focus "the session" must walk up the tree. And `kiro-cli chat --no-interactive` creates **no lock and no persisted session at all** — a one-shot leaves no trace in any store.

### Process model — `kiro-cli chat` is a wrapper

```
kiro-cli.exe chat -a                    <- what the user runs
└─ bun.exe tui.js chat -a               <- the TUI, JavaScript under bun
   └─ kiro-cli.exe acp --trust-all-tools <- the agent; holds the session lock
```

Consequences worth knowing before reasoning about kiro-cli behaviour:

- **An interactive terminal session IS an ACP session underneath.** There is one code path, so anything observed over `kiro-cli acp` applies to terminal sessions too.
- **The TUI passes `--trust-all-tools`**, so in normal interactive use the permission gate lives in the TUI layer, not the agent. A client that drives `kiro-cli acp` itself, without trust flags, receives `session/request_permission` and must answer it.
- **A session is owned by one process at a time.** Attempting `session/load` on a live session returns `-32603` with `"Failed to start session: Session is active in another process (PID <n>)"` in under a second. The lock is not stolen and no interleaving occurs. Stale locks are ignored, so a crashed session remains attachable.

### Finding a session id from inside a session

- **`/session-id`** — prints the session id and `Resume with: kiro-cli --resume-id <id>`. This is the command to use.
- **`/stats`** — prints per-request telemetry (Request ID, Duration, TTFC, In/Out, Status) and **does not show the session id**. Easy to reach for by mistake.

The id namespace is uniform: the same value appears in `/session-id`, the `.lock` filename, the `.json` metadata, `--list-sessions`, ACP `session/load`, and `kiro-cli chat --resume-id`.

### Session enumeration surfaces

| Surface | Covers | Cost | Scope |
|---|---|---|---|
| Filesystem glob of `sessions/cli/*.json` | v2 only | ~1.0 s for 5.6k sessions | global |
| `kiro-cli chat --list-sessions -f json` | **v2 + v3 + classic**, each tagged `source` | ~2.1 s, one process spawn per query | **one cwd only** |
| ACP `_kiro.dev/session/list` | v2 only — the same store re-derived | **~6.8 s** cold, ~5.9 s warm | global |

`--list-sessions` is the only surface that unifies all three stores. The ACP call works with no session created (so ~88 MB, no MCP children) and returns `{sessionId, cwd, title, updatedAt, messageCount}`, but it is several times slower than reading the files directly and its set difference against the raw metas is zero in both directions — it is not a separate index. An undocumented `{"cwd": "<path>"}` param **is** honoured (~1.45 s scoped); `limit`, `offset`, `cursor`, `includeSubagents` and `parentSessionId` are silently ignored. Unknown params raise no error, so absence of an error is never evidence a param exists.

### Agent profiles and the permission model

**Two profile shapes exist.** The flat form is `~/.kiro/agents/<name>.json` — what the playbook deployed before v2's retirement (`providers/kiro/agents/kiro_default.json`, deleted; git history has it) <!-- verify-links: skip providers/kiro/agents/kiro_default.json -->. Agents installed via AIM may instead exist **only** as a directory: `~/.kiro/agents/<name>/agent-spec.json`, with no sibling `.md`. `kiro-cli` resolves both natively, but any enumeration that globs `~/.kiro/agents/*.json`, or scans for `*.md`, misses the directory form entirely. A stub `.md` alongside is the documented workaround.

**`allowedTools` in the agent JSON is read and enforced by kiro-cli itself**, at install time — not by prompt discipline. The playbook's (now-deleted) `kiro_default.json` shipped `tools: ["*"]` with `allowedTools: []`. Whether an empty list means "nothing pre-approved, so every action prompts" or "no restriction" is **unverified — probe before building on it**. Either way this is the one *hard* lever available in a strategy that is otherwise soft by construction: an `OVERLAY.md` appends prose, which a weaker model can reason around; a natively-enforced field cannot be.

**There is no workspace-trust dialog.** Where Claude Code asks once per folder, kiro-cli gates per action — `Allow this action? [y/n/t]:`. That is a structural difference in the permission model, and it determines whether a kiro agent can run unattended at all.

**`--legacy-ui`** forces the pre-TUI `[profile] >` prompt format — an escape hatch when a TUI change breaks something that reads terminal state.

**Re-verify when** a kiro-cli upgrade changes prompt or profile behaviour: check whether `~/.kiro/agents/` has gained directory-form profiles, and whether `allowedTools` semantics changed. Version-pin any behavioural claim added to this section.

### Hooks

Configured **per agent**, in the agent JSON's top-level `"hooks": {}` object (`~/.kiro/agents/<name>.json`). Not in `kiro-cli settings` — that command exposes no hook keys — and not in `~/.kiro/hooks/`, which exists but is unused.

Five triggers: `agentSpawn`, `userPromptSubmit`, `preToolUse`, `postToolUse`, `stop`. Unknown trigger names are a validation error. Per-hook fields: `command` (required), `matcher?`, `timeout_ms?` (default 10s), `max_output_size?` (default 10240), `cache_ttl_seconds?` (default 0).

```json
"hooks": { "agentSpawn": [ { "command": "& \"C:\\path\\python.exe\" \"C:\\path\\hook.py\" agentSpawn" } ] }
```

- **Hook commands run through PowerShell, not cmd.** A bare `"<exe>" "<script>" arg` form is a PowerShell parse error and the hook silently never runs — use the call operator `&`.
- **The payload carries no session id** (`agentSpawn` gives only `hook_event_name`, `cwd`, `prompt`). The session id is in the hook subprocess **environment** as `KIRO_SESSION_ID`, and matches `--list-sessions`.
- `stop` carries `assistant_response` — the final assistant text.
- `tool_name` is `execute_cmd`, not the `execute_bash` name in the agent config's `tools` array.
- Latency is ~1.2 s from tool completion to hook delivery (roughly 4× Claude Code's).
- There is **no** `sessionEnd`, notification, or permission trigger.

### ACP and `serve`

`kiro-cli acp` speaks JSON-RPC 2.0 over stdio with **newline-delimited JSON** framing (not LSP `Content-Length`), and requires no auth (`"authMethods":[]`). Slash commands are sent as ordinary **prompt text** — `/tools` returns in ~1 ms, proving agent-side interception before the model. The command catalogue arrives as an agent→client `_kiro.dev/commands/available` *notification*; calling it as a request returns `-32601`.

**Never send `_kiro.dev/commands/execute`** — it terminates the agent process with **exit code 0, no stderr, and no JSON-RPC error**, at any verbosity. Reproduced 3/3. More generally, a `kiro-cli acp` process writes nothing to stderr for an entire session, so neither exit code nor stderr is a usable health signal.

`kiro-cli serve` (WebSocket, v3-only) is **not usable for observing sessions** as of 2.14.1. It hardcodes `--auth=acp-callback`, where the agent requests its token *from* the client as a JSON-RPC request — and requests are role-gated to non-observers while no WebSocket client can ever be assigned a role other than `observer`, so `session/new` and `session/load` hang forever. Independently, it reads only the v3 store (never `sessions/cli/`), and its `activeAwareStatus` masks any `in_progress` it is not itself executing down to `idle`, so externally-owned sessions always read idle.


### Environment variables available to the agent

For the full table of env vars by session type (v2 TUI, v3 TUI, PowerAtlas terminal, ACP), see `providers/kiro/steering/kiro-cli-local-data.md § Environment variables available to the agent`.

In a v2 session specifically: `KIRO_SESSION_ID` is a bare UUID (no `sess_` prefix), `KIRO_TUI_READY_FILE` is set (interactive terminal), `KIRO_AGENT_ENGINE` is not set, `KIRO_KAS_NODE_PATH` is not set (v2 has no KAS node binary).

### Moving a workspace

v2 is retired but its store stays on disk, and `kiro-cli chat --list-sessions` still reads it. Measured
2026-10-02 (Windows, store last written 2026-09-24): of 6,980 `cli/*.json` files, 2,313 had a `cwd` inside
the moved tree. A v2 session follows a workspace move when:

- its `<id>.json` `cwd` and its `<id>.jsonl` are rewritten (whole file, raw bytes), and
- the `conversations_v2` rows whose `key` (and `value`) name the old path are updated in `data.sqlite3`.

**The `cwd` value is JSON-escaped on disk** (`C:\\Users\\...`). A search for the single-backslash form
finds nothing and reads as "no v2 sessions here"; that is exactly how these 2,313 were first missed.
Parse the `.json` (it is small and flat) or search the escaped form. Procedure and scripts:
`shared/skills/qmigrate-workspace/SKILL.md`.
