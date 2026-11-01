## Kiro-CLI v3 Internals

> **Reference only — not deployed.** ACP handshake sequencing, JSON-RPC id quirks, the notification
> method catalogue, KAS bundle internals and the workspace-hash derivation proof for kiro-cli v3.
> It loads on demand only — not in `inventory.tsv`, so it never reaches a session's context.
> **Read when** building or debugging an ACP client against kiro-cli v3, or reading KAS bundle
> internals (handshake sequencing, JSON-RPC quirks, notification catalogue, workspace-hash
> derivation), or moving a workspace (the hash-keyed stores). Indexed from `memory/topics/kiro-cli.md`.

The session-store layout, the env-var table and session metadata basics an ordinary session needs
are in `providers/kiro/steering/kiro-cli-local-data.md`. This file holds the byte-level material
that trimmed out of it.

### Workspace-hash derivation proof

Workspace hash: first 16 hex chars of SHA-256 over the normalized workspace path set. Derivation (verified against shipped `acp-server.js`, kiro-cli 2.16.0):

1. For each path in `workspacePaths`: replace `\` with `/`, run `posix.normalize`, lowercase (on Windows).
2. Sort the normalized paths lexicographically, join with a null byte (`\0`).
3. SHA-256 the UTF-8 encoded result, take the first 16 hex characters.

Special case: empty `workspacePaths` → hash is the literal string `"_global"`.

For the common single-workspace case this is `sha256(posix.normalize(path.replace('\\', '/')).lower())[0:16]` **on Windows only** — `normalizePath2` in `workspace-hash.ts` lowercases with `process.platform === "win32" ? canonical.toLowerCase() : canonical`, so a Linux/macOS client hashes case-sensitively. Multi-workspace sessions sort-and-null-join before hashing, so the hash is path-set-stable regardless of argument order.

Python reference implementation (defaults to Windows semantics; pass `lowercase=False` to reproduce a Linux/macOS client):
```python
import hashlib, posixpath, sys

def workspace_hash(paths, lowercase=(sys.platform == "win32")):
    if not paths:
        return "_global"
    def normalize(p):
        p = posixpath.normpath(p.replace('\\', '/'))
        return p.lower() if lowercase else p
    key = '\0'.join(sorted(normalize(p) for p in paths))
    return hashlib.sha256(key.encode('utf-8')).hexdigest()[:16]
```

### Stores keyed by the workspace hash

Measured 2026-10-02 on Windows (kiro-cli 2.27.0) while moving seven workspace-hash folders with
`shared/skills/qmigrate-workspace/SKILL.md`: the formula above reproduced all seven existing folder
names before anything moved, and the moved sessions listed and resumed from the new path (user-confirmed).
Three folders are named by the same hash (`sessions/<hash>/`, which also holds `.index/`, plus `session-index/` and `workspace-roots/`), so a workspace move touches every row below:

| Path | Content | On a move |
|---|---|---|
| `~/.kiro/sessions/<hash>/sess_<uuid>/` | the sessions; `session.json` `workspacePaths` holds the path | rewrite `session.json`, `messages.jsonl` and `sub-executions/` (not `snapshots/`: captured file content), then move each `sess_*` into `<new-hash>/` |
| `~/.kiro/sessions/<hash>/.index/` | `.lock` and `index.json`, a session-list cache: `{schemaVersion: 2, walkedAtMs, dirMtimeMs, dirNamesHash, entries: [{id, title, agentMode, createdAt, lastModifiedAt, workspacePaths, ...}]}` | shared by every session of the workspace, so never delete it with one session; once the old folder holds no `sess_*` it is orphaned, and kiro-cli built a fresh `.index/` in each new folder on its next listing |
| `~/.kiro/session-index/<hash>.jsonl` | one `{"op":"add","sessionPath":"<hash>/sess_<uuid>","at":<ms>}` line per session; a `.migration-v3` marker beside it | rename to `<new-hash>.jsonl` and rewrite the hash inside |
| `~/.kiro/workspace-roots/<hash>/` | `.trust-migration.json` `{version, root, completedAt, rulesWritten}` and, when set, the workspace-scope `permissions.yaml` | rename the folder; rewrite `root` |

PowerAtlas's v3 reader treats `.index/` the same way (shared per-workspace state, never removed with a
session). Most `workspace-roots/` folders on this machine belonged to scratch directories of earlier
probes, not to real workspaces.

**From an earlier manual move (2026-09-24, kiro-cli 2.22.x)**: never write a session file with Windows
PowerShell 5's `Set-Content -Encoding UTF8` — its BOM made strict readers reject 31 files across 15
sessions, which silently vanished from listings. That move also lower-cased `C:` to `c:` inside
`messages.jsonl`, so an identity check after a copy must ignore the rewritten path, a BOM and the
drive-letter case, and compare `*.jsonl` content only (`session.json` and `publish.cursor` legitimately
differ).

### Message format (`messages.jsonl`)

Each line: `{"id": "...", "timestamp": "ISO-8601", "payload": {"type": "...", ...}}`

Message types:

| `payload.type` | Content | Signal value |
|---|---|---|
| `user` | `.content`, `.images[]`, `.documents[]` | User messages, corrections, decisions |
| `assistant` | `.content` | Agent responses, patterns |
| `tool_call` | `.toolName`, `.args`, `.status`, `.kind` | What tools were invoked |
| `tool_result` | `.content`, `.success` | Tool outputs (verbose — skip for signal extraction) |
| `turn_start` | `.executionId` | Turn delimiter |
| `turn_end` | `.stopReason`, `.executionId` | Turn boundary |
| `usage_summary` | `.elapsedTime`, `.status` | Performance data |
| `session_metadata` | `.key`, `.value` | Runtime metadata (e.g. contextUsage) |
| `session_event` | `.category`, `.context` | Lifecycle events (session_pause) |
| `session_start` | `.agentType`, `.content`, `.steeringDocuments[]` | Full agent init (system prompt + all loaded steering) |
| `sub_agent_start` | `.subSessionId`, `.subAgentName`, `.prompt` | Subagent dispatch |
| `sub_agent_complete` | `.subSessionId`, `.response`, `.status`, `.errorMessage` | Subagent return |
| `pending_interaction` | | Awaiting user input |
| `interaction_resolved` | | User responded |

### Tool naming (v3)

v3 uses different tool names from v2:

| v3 tool name | Purpose |
|---|---|
| `execute_pwsh` | Shell command execution (Windows) |
| `read_file` | File reading |
| `fs_write` | File writing/editing |
| `list_directory` | Directory listing |
| `grep_search` | Content search |
| `file_search` | File name search |
| `delete_file` | File deletion |
| `orchestrate_subagent` | Subagent dispatch |
| `update_session_information` | Session metadata updates |

Tool call `.status` values: `completed`, `failed`, `denied`, `approved`.
Tool call `.kind` values: `execute`, `read`, `edit`, `delete`, `search`, `other`.

### Subagent identification

v3 does NOT use `parent_session_id`. Subagents are identified by:
1. `sub-executions/<uuid>.jsonl` files inside the parent session directory
2. `sub_agent_start` / `sub_agent_complete` messages in the parent's `messages.jsonl`
3. The `subSessionId` field links the parent message to the `sub-executions/` file
4. **Since kiro-cli 2.28.0 (first seen 2026-10-06):** a workflow node or delegated sub-agent is also written as a full `sess_<uuid>/` folder beside the parent's, with `rootConversationId: "sess_<parent>"` in its `session.json`, `workflowsEnabled: true`, and its own `messages.jsonl` (no `sub-executions/`). The parent's `messages.jsonl` names the child's id (66 of 67 children measured). Which release introduced it was not separated from the workflow feature's first use that day. Do not treat these folders as user sessions.

Sub-execution `.jsonl` files contain: `steering_inclusion`, `assistant`, `tool_call`, `tool_result` types.

### Session history (CLI picker)

`~/.kiro/sessions/cli/sess_<uuid>.history` — plain-text user input history used by the `/chat` session picker UI. NOT conversation content. One user message per line.

### Differences from v2

| Aspect | v2 | v3 |
|---|---|---|
| Storage | `~/.kiro/sessions/cli/<uuid>.{json,jsonl}` | `~/.kiro/sessions/<hash>/sess_<uuid>/` |
| ID format | bare UUID | `sess_<uuid>` |
| Envelope | `{"version":"v1","kind":"...","data":{}}` | `{"id":"...","timestamp":"...","payload":{"type":"..."}}` |
| User message kind | `Prompt` | `user` |
| Agent message kind | `AssistantMessage` | `assistant` |
| Tool output kind | `ToolResults` | `tool_result` |
| Subagent detection | `parent_session_id` in metadata | `sub-executions/` dir + `sub_agent_start` messages; from 2.28.0 also a sibling session folder with `rootConversationId` |
| Workspace scoping | All in `cli/` flat | Hashed workspace subdirs |
| Conversation DB | `%LOCALAPPDATA%\Kiro-Cli\data.sqlite3` | None — file-based only (session.json + messages.jsonl) |
| Session listing | DB query + `.json` metadata files | Read `sess_*/session.json` per workspace-hash dir |
| Live-session lock | `sessions/cli/<id>.lock` with `{pid, started_at}` | **None** — no lock artifact exists for v3 sessions |

Note that the two stores are **disjoint and separately enumerated**: `kiro-cli chat` without engine flags writes to the v2 `sessions/cli/` layout. `kiro-cli chat --v3` or `kiro-cli chat --agent-engine v3` route to the KAS v3 engine, which writes to the hashed `sess_<uuid>/` dirs. Neither a `sessions/cli/*.json` glob nor ACP's `_kiro.dev/session/list` sees the v3 store. `kiro-cli chat --list-sessions -f json` is the only surface that returns both, tagging each entry `"source": "v2" | "v3" | "classic"`.

### Session-directory extra files

Two files appear alongside `session.json` and `messages.jsonl` in sessions where the activity-log publisher ran:

| File | Purpose |
|---|---|
| `publish.cursor` | `<byteOffset>:<seq>` string (e.g. `277037:44`) — cursor into `messages.jsonl` for cloud telemetry publisher. Verified against real session files and `writeCursor()`/`readCursor()` in `ActivityLogPublisher`; not a bare byte offset. |
| `publish-sub.cursor` | JSON map of `{subExecutionId: {byteOffset, seq}}` for sub-execution telemetry |

These are telemetry cursors, not liveness markers. Their presence just means the cloud publisher ran at some point during the session.

### ACP v3 — differences from v2

`kiro-cli acp --agent-engine v3` speaks the same JSON-RPC 2.0 / newline-delimited framing as v2, but the method surface and auth model differ materially.

**session/new params**: v3 requires `cwd` (string) and `mcpServers` (array) in addition to the v2 fields. Sending only `workspacePaths` returns `-32602 Invalid params`.

```json
{
  "jsonrpc": "2.0", "id": 1, "method": "session/new",
  "params": {
    "cwd": "/path/to/workspace",
    "mcpServers": [],
    "workspacePaths": ["/path/to/workspace"]
  }
}
```

The result's session metadata is nested under `result._meta` (not `result` directly).

**session/prompt params**: takes an array of content blocks, not a string.
```json
{"sessionId": "sess_...", "prompt": [{"type": "text", "text": "your message"}]}
```

**Available commands**: delivered via `session/update` notification with `sessionUpdate: "available_commands_update"` (not `_kiro.dev/commands/available` as in v2).

**Auth gate**: `session/prompt` and all execution methods require `KiroAgent.initialize()` to complete first, which means the client must respond to the agent's auth-callback request (`AcpCallbackAuthProvider`). Without this handshake, any prompt returns `-32000 Authentication token is invalid`. This is the same gate that blocks `kiro-cli serve` — v3 requires the client to supply a token before execution can proceed.

The `initialize` sequence (two independent live ACP probes against kiro-cli 2.16.2):

1. Client sends `initialize` with `protocolVersion: 1` (uint16, not a string) and `clientCapabilities`. This is distinct from `session/new` — `initialize` must come first.
2. Somewhere during `initialize()`'s setup (source: `this.authProvider.setConnection(this.connection)` is a pure setter with no I/O — the actual token fetch is fired by an unrelated, non-blocking step further down, e.g. remote-tools discovery), the agent sends `_kiro/auth/getAccessToken` to the client with empty params `{}`. **This request uses the connection's own independent outbound-id counter — not the `initialize` call's id.** Proven live: sending `initialize` with `id:777` still produced a `getAccessToken` request with `id:0` (its own counter, which happens to start at 0).
3. The client must respond with its OIDC token as an object: `{"jsonrpc":"2.0","id":<the getAccessToken request's own id>,"result":{"accessToken":"<token>","expiresAt":"<ISO-8601>"}}`. The agent validates both fields — `accessToken` must be non-empty, `expiresAt` must be parseable as a timestamp (confirmed via `doRefresh()` source: `if (!response.accessToken) throw ...`, `parseExpiresAt(response.expiresAt)`). `get-kas-token` returns `{"kind":"getKasToken","data":{"accessToken":"...","expiresAt":"...","profileArn":"...","provider":"..."}}` — extract `data.accessToken` and `data.expiresAt`. **For Enterprise accounts, also pass `profileArn` and `provider` from the token response** — without them the agent selects the model using only the access token and the Enterprise backend rejects the request with `-32000 profileArn is required for this request`. The response with all four fields: `{"jsonrpc":"2.0","id":<id>,"result":{"accessToken":"<token>","expiresAt":"<ISO-8601>","profileArn":"<arn>","provider":"Enterprise"}}`.
4. **The `initialize` result does NOT wait for step 3.** Proven live, twice: in both probes the `initialize` result arrived within milliseconds of the `getAccessToken` request, with no token response ever sent. `initialize()` returns its capabilities result unconditionally; the token exchange is fire-and-forget from the client's perspective at this stage. `session/new` also does not require a completed token exchange — it succeeded live with no token ever supplied. The auth gate only blocks actual model/tool execution (see **Auth gate** above), not `initialize` or `session/new`.
5. `session/prompt` and other execution methods are where a missing/invalid token actually surfaces, as `-32000 Authentication token is invalid`.

The `kiro-cli` binary resolves its token via the internal subcommand `kiro-cli chat _ get-kas-token`. A third-party client must obtain and supply a valid KAS OIDC token through its own means.

```json
// Client sends (id is caller's choice, e.g. 0):
{"jsonrpc":"2.0","id":0,"method":"initialize","params":{"protocolVersion":1,"clientCapabilities":{"auth":{"terminal":false},"fs":{"readTextFile":false,"writeTextFile":false},"terminal":false},"clientInfo":{"name":"my-client","version":"1.0"}}}

// Agent sends, on its own independent id sequence (observed as id:0 on a fresh
// connection regardless of the initialize call's id) — and does NOT wait for a reply:
{"jsonrpc":"2.0","id":0,"method":"_kiro/auth/getAccessToken","params":{}}

// Agent returns the initialize result almost immediately, unconditionally:
{"jsonrpc":"2.0","id":0,"result":{"protocolVersion":1,"agentCapabilities":{...}}}

// Client MAY respond to the getAccessToken request whenever ready — needed before
// any actual model/tool call, not before the initialize result:
{"jsonrpc":"2.0","id":0,"result":{"accessToken":"<OIDC_ACCESS_TOKEN>","expiresAt":"<ISO-8601>"}}
```

**Permission model**: `session/request_permission` **does exist in v3** — confirmed directly from the generic ACP-SDK schemas already bundled in kiro-cli's own shipped `acp-server.js` (`zRequestPermissionRequest`, `zRequestPermissionResponse`, `zPermissionOption`); no external source needed. It works identically to v2: a JSON-RPC *request* from agent to client (has both `method` and `id`), not a notification. Payload: `params.toolCall.{title, kind, toolCallId, ...}` + `params.options[].{optionId, name, kind}`. The client approves by responding `{"result": {"outcome": {"outcome": "selected", "optionId": "allow_once"}}}`. Kiro-cli's own code constructs a `reject_once` option (and sometimes `reject_always`) at essentially every real `requestPermission()` call site (e.g. `{optionId:"reject", name:"Deny", kind:"reject_once"}`), alongside `allow_once`/`allow_always`. All four `zPermissionOptionKind` values (`allow_once`, `allow_always`, `reject_once`, `reject_always`) are in active use by kiro-cli itself. The live probe session never triggered an actual `session/request_permission` round-trip because the session failed before any tool was dispatched — the protocol shape is confirmed from source, not from a live tool-execution probe.

**`--trust-all-tools` incompatible with v3**: passing `-a` / `--trust-all-tools` alongside `--agent-engine v3` exits with error code 2. v3 uses a different permission model; do not combine these flags.

**Model ID format uses dots, not hyphens**: the model IDs available to v3 sessions use dot separators (e.g. `claude-sonnet-4.6`, `claude-opus-4.5`), not hyphens (`claude-sonnet-4-5`). The available set is delivered per-session via `config_option_update` on `session/new` — capture it from the wire, not from inference. On Enterprise accounts, the available models depend on the IAM profile; `session/prompt` returns `-32000 InvalidModelError` with the model name if the requested model isn't available. `get-kas-token` returns the `profileArn` for the active profile, which determines the available model set.

**Notification methods emitted by v3** (each entry below was traced to an actual outbound push call, not just a type reference; the surface is large enough that this list may still not be exhaustive):

Core session/tooling: `_kiro/mcp/status`, `_kiro/mcp/elicitation`, `_kiro/powers/items_changed`, `_kiro/progressive_context/items_changed`, `_kiro/sessions/changed`, `_kiro/steering/documents_changed`, `_kiro/tools/didChange`, `_kiro/governance/state`, `_kiro/policy/changed`, `_kiro/policy/error`, `_kiro/safety/statusChanged`

Session/system: `_kiro/session/notify`, `_kiro/system/notify`, `_kiro/openExternalUrl`, `_kiro/hooks/sessionStart`, `_kiro/error/rate_limit`, `_kiro/userInput`, `_kiro/code_references`

Spec workflow: `_kiro/spec/taskStatusChanged`, `_kiro/spec/phaseCheckpoint`

Workflow runner (`_kiro/workflow/*`): `run_start`, `node_start`, `node_complete`, `node_paused`, `loop_iteration`, `watch_poll`, `paused`, `run_complete`, `steps_queued`

Generic session updates: `session/update` (with `sessionUpdate` subtypes: `available_commands_update`, `session_info_update`)

v2 methods `_kiro.dev/commands/available`, `_kiro.dev/metadata`, and `_kiro.dev/session/list` are **not present** in v3. Calling them returns `-32603 Internal error: no persistence classification`.

### kiro-cli serve

`kiro-cli serve --port <N>` starts a persistent v3 agent server over WebSocket (v3-only; the Rust CLI wrapper spawns KAS with `--transport=ws --auth=acp-callback`). It uses the same `AcpCallbackAuthProvider` auth-callback pattern as `kiro-cli acp --agent-engine v3` (which spawns KAS with `--transport=stdio --auth=acp-callback`) — the server requests its token from the connecting client via `_kiro/auth/getAccessToken`, with no timeout wrapper visible on that call, so a client that never answers it hangs.

`kiro-cli` itself is the intended client, and the handshake works: the server's own startup log reads `Connect with: kiro-cli --remote ws://<host>:<port>`, and `kiro-cli.exe` contains a working handler for `_kiro/auth/getAccessToken` that resolves the callback by shelling out to an internal subcommand, `kiro-cli chat _ get-kas-token` ("Resolve and refresh-if-expired the active OIDC access token for KAS"). `serve` + `kiro-cli --remote` is a documented, working path. A *third-party* client (something other than `kiro-cli` itself) would need to reimplement this OIDC callback to talk to `serve`.

### Native memory store (2.29.1)

Read 2026-10-12 from the 2.29.1 KAS bundle (`acp-server.js`); earlier versions were not checked, and the store did not exist on the reading machine.

- **Store**: SQLite at `~/.kiro/memories/memories.db` (WAL), tables `memories` (`id, memory_type, scopes, title, summary, content, why, how_to_apply, session_id, metadata, created_at, updated_at`) and `memory_scopes`. `why` and `how_to_apply` are legacy read-only; new writes take title, description and content. At most 1,000 memories.
- **Types and scopes**: `USER_PREFERENCE` or `SEMANTIC`; scope `Global` or `repo:<provider>/<owner>/<name>` from the git origin remote. `SEMANTIC` cannot be Global.
- **Gate**: on only when the server-side experiment value is `true`/`"all"`, or `"insider"` on an insider or nightly build (or with the `memoryEnable` setting). `userMemoryOptIn: false` can only switch it off, and only for legacy config. The gate decision is logged at debug level, so default logs do not show it.
- **Writers**: the agent's `memory` tool (`list/get/add/update/delete/import`, no per-write approval), a background `memory-extraction` sub-agent (45 s idle debounce, forced at 30 unprocessed messages, 4 model turns, only `memory` runnable, progress mark `memoryExtractionWatermark` appended to the session's `messages.jsonl`), and the `/memories` TUI panel over `_kiro/memory/*` JSON-RPC.
- **Session start**: a `# Memory Index` inside `<memories>`, 24,000-character budget with a one-third ceiling for preferences, `N shown / M total` per scope, other repositories as counts.
- **Write guards**: gitleaks v8.24.3 secret scan, field length caps, 100 writes per run.
- **Playbook relation**: the playbook does not read or write this store; harvesting it is a parked item in the playbook roadmap.

### Unverified v3 behaviors

Re-verify when investigating these.

**Permission model during tool execution**: The `session/request_permission` method was not emitted during a live ACP probe (full handshake, turn executed to model-backend failure before tool calls). Whether it fires at the point of an actual tool call is still unconfirmed — completing verification requires a working model-backend session (a KAS token with a valid `profileArn`/Amazon Q profile). See the `**Permission model**` note in `### ACP v3 — differences from v2`.

**Hook system**: see `memory/topics/kiro-cli.md`, "v3 standalone hooks use `.kiro/hooks/*.json` with PascalCase triggers — same format as v2".

**KiroCrew's hook handling (third-party, not kiro-cli itself)**: checked directly against the `kirodotdev/KiroCrew` source (`src/kiro_crew/hooks.py`). `hooks.json` at `~/.kiro/crew/hooks.json` is the persistence store for a *different* feature — inbound webhook registrations owned by a `register_hook` MCP tool (see KiroCrew's own `docs/inbound-webhooks.md`) — not a hook-payload session-id source. The five ACP hook event names (`AgentSpawn`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `Stop`) do match kiro-cli's, but that dispatch is driven by `config.json` per the module's own docstring ("Config-driven hook system... based on rules in config.json"), not `hooks.json`. `session_key`/`parent_session_key` are parameters to KiroCrew's own PreToolUse *governance gate* (`on_tool_call` → `_governance_denial` → `_audit_governance`) for scope/audit resolution — not something written to `hooks.json`, and the file never references `KIRO_SESSION_ID` at all. See `providers/kiro/reference/kiro-cli-v2-local-data.md § Hooks` for the v2 reference.

**`forceAuth` and MCP OAuth in v3**: verified via KiroCrew source and a live ACP probe. OAuth works the same in v3: kiro-cli emits `_kiro/mcp/status` notifications with `failedAuthorization: true` and an `authorizationUrl`. The client captures the URL and presents it to the user; kiro-cli's local callback handles the rest of the OAuth flow. In one ACP probe, the Atlassian MCP server attempted OAuth during `session/new` and delivered an `authorizationUrl` — confirming the flow is identical to v2. The `forceAuth: true` config in `mcp.json` is honoured in v3 sessions.

**Re-verify when** kiro-cli changes minor version.
