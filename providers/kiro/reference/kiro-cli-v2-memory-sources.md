## Memory Sources (Kiro, v2)

> **Reference only — not deployed.** kiro-cli v2 is retired; this file records where v2 (and Kiro
> IDE) sessions live for `/qdream` harvesting. It loads on demand only — not in `inventory.tsv`, so
> the live sweep glob no longer reaches it. **Read when** a `/qdream` sweep must harvest **v2**
> sessions; pass this file's path explicitly. Indexed from `memory/topics/kiro-cli.md`.

`/qdream` full mode scans ALL provider session sources for project discovery and session analysis. The orchestrator reads lightweight metadata for temporal filtering and project mapping; sub-agents read session content for signal extraction.

### Kiro IDE sessions
- Location (Windows): `%APPDATA%\Kiro\User\globalStorage\kiro.kiroagent\workspace-sessions\`
- Location (Linux/macOS): `~/.config/Kiro/User/globalStorage/kiro.kiroagent/workspace-sessions/`
- Format: One subfolder per workspace. Folder names are base64-encoded workspace paths with `+`→`-`, `/`→`_` and the padding written as `_` (to decode: trailing `_` → `=`, other `_` → `/`, `-` → `+`; measured 2026-10-02, encoding and layout in `providers/kiro/reference/kiro-ide-local-data.md`). Each folder contains:
  - `sessions.json` — array of session summaries: `{ sessionId, title, dateCreated (Unix ms), workspaceDirectory }`
  - `<sessionId>.json` — full session content: `{ history: [{ message: { role, content, id }, contextItems }] }`
- Session content structure: `history[].message.role` is `"user"` or `"assistant"`. Content is an array of `{ type: "text", text: "..." }` blocks. `contextItems` array contains skill/file context attached to that turn.
- Access: Read `sessions.json` for discovery (workspace path, creation date). Read individual session files for content analysis. No metadata fields for `session_created_reason` or `parent_session_id` — IDE sessions are always user-initiated.
- Limitation: No temporal metadata beyond `dateCreated` in `sessions.json`. Filter by `dateCreated` (Unix milliseconds) against `last_analyzed` timestamp.

### Kiro CLI conversations
- **Primary source — session files**: read `~/.kiro/sessions/cli/<id>.jsonl` for conversation content; see the "Session content filtering" section below for which `kind` lines to focus on / skip, and `kiro-cli-v2-local-data.md` (co-located reference file) for the full session-file + `.json` metadata schema.
- **Secondary / legacy — SQLite**: the `conversations_v2` table in `data.sqlite3` holds only a small fraction of data (specific agent configurations). Query only when needed: `sqlite3 <path> "SELECT value FROM conversations_v2 WHERE key = '<cwd>' COLLATE NOCASE ORDER BY updated_at DESC LIMIT 5"` (path/schema in `kiro-cli-v2-local-data.md`). Conversations can be 44KB+ each; grep narrowly within the JSON, don't load entire conversations into context.

### Metadata fields used by dream

The orchestrator reads session metadata (`.json` files) for these fields:

| Field | Purpose |
|---|---|
| cwd | Project discovery — unique values become the project list |
| created_at | Temporal filtering — skip sessions before last_analyzed |
| updated_at | Temporal filtering — identify most recent activity |
| parent_session_id | Sub-agent filtering — exclude sessions where this field is present (non-null). This is the SOLE reliable sub-agent discriminator. |

**Note on `session_created_reason`**: This field is unreliable for sub-agent detection. User-initiated sessions are sometimes tagged `"subagent"` despite having no `parent_session_id`. Do NOT use it for filtering — use `parent_session_id` only.

### Session content filtering

When sub-agents read `.jsonl` session files for signal extraction:

- **Skip**: lines with `"kind":"ToolResults"` (literal string, capital T, plural S) — these are verbose tool output that bloats context without adding learnable signal
- **Focus on**: `"kind":"Prompt"` (user messages) and `"kind":"AssistantMessage"` (agent responses) — these contain corrections, decisions, friction, and patterns
