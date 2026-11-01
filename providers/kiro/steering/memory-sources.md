## Memory Sources — v3 Sessions

`/qdream` full mode discovers this file by globbing `providers/*/steering/memory-sources.md`; it documents kiro-cli v3 session discovery and extraction. kiro-cli v2 is retired: its session format is described in `providers/kiro/reference/kiro-cli-v2-memory-sources.md` (on demand, never deployed), which a sweep must be handed explicitly if old v2 sessions are to be harvested.

### v3 session location

- Windows: `%USERPROFILE%\.kiro\sessions\<workspace-hash>\`
- Linux/macOS: `~/.kiro/sessions/<workspace-hash>/`

Each workspace hash directory contains `sess_<uuid>/` subdirectories, one per session.

### Discovery (orchestrator)

1. Enumerate workspace-hash directories under `~/.kiro/sessions/` (exclude `cli/` which holds v2 sessions and v3 history files)
2. For each workspace dir, enumerate `sess_*/session.json` files, skipping sub-agent sessions (`rootConversationId` set and not the session's own id — `§ Sub-agent filtering`)
3. Read `session.json` for project mapping (`workspacePaths[0]`) and deferral (`status`, `lastModifiedAt`)
4. Read `messages.jsonl`: a session is new when a user or assistant record's `timestamp` is newer than the project's baseline, compared as instants. The baseline is the project's `last_analyzed`; for a project absent from the state file it is the state's `last_run` (user decision 2026-09-24) — its older sessions are counted (`older_sessions_not_read`), not read, unless the sweep passes `--full <project>`; with no state file (first run) it is the config repo's last commit time (read in full, with an error line, when git cannot give it)

A `session.json` without `workspacePaths`, or a `messages.jsonl` that cannot be read, is reported as an error, never skipped in silence. A session directory without `messages.jsonl` is an empty session (created, never used — 29 of the 56 errors of the first Windows run, 2026-09-24): counted in the project's `empty_sessions` (ids in its side file), not an error — unless `session.json` shows activity (`lastModifiedAt` more than 60 s after `createdAt`), which is reported as an error.

`shared/skills/qdream/scripts/dream-manifest.py` implements this discovery, selection and stripping; this file is the fact base it implements.

### Metadata fields used by dream

| Field | Purpose |
|---|---|
| `workspacePaths[0]` | Project discovery — maps session to workspace |
| `lastModifiedAt` | Last activity. With `status`, decides deferral (below). Not the new-turn test — per-record `timestamp` is |
| `createdAt` | Not a filter: a session created before `last_analyzed` can hold newer turns |
| `agentMode` | Filter by agent (e.g. skip `"vibe"` if only custom-agent sessions wanted) |
| `status` | `"in_progress"` is not a liveness signal (a crashed session keeps it). `in_progress` with `lastModifiedAt` under 24 h before the manifest snapshot → **deferred**: read up to now and record a watermark (`deferred_sessions`, last record id read); older → treated as closed |

### Sub-agent filtering

v3 has no `parent_session_id`, and a `sess_*/session.json` is **not always** a user session. Two shapes carry sub-agent work:
- **`sub-executions/<uuid>.jsonl` inside the parent's session dir** — the older shape; never a session of its own.
- **A full `sess_<uuid>/` folder beside the parent's** (workflow nodes and delegated sub-agents; first seen 2026-10-06 on kiro-cli 2.28.0). Its `session.json` carries `rootConversationId: "sess_<parent>"`; a top-level session has no such key. Measured that day: 67 of 376 stores were such children, all in the parent's hash dir and workspace, so they inflate every session count.

Therefore a session is a user session when it has no `rootConversationId`, or when that value equals its own `id`. `dream-manifest.py` skips every other one (`kiro_subagent`): it is not listed, counted or dispatched, and its parent is the session the sweep reads. Do not filter on `agentMode` — a top-level session can run a custom agent too. Sub-agent content is read through the parent's `messages.jsonl` (`sub_agent_start` / `sub_agent_complete`) and, for the older shape, `sub-executions/`.

### Session content extraction (sub-agents)

Read `sess_<uuid>/messages.jsonl`. Each line is `{"id", "timestamp", "payload": {"type": ...}}`.

**Focus on** (learnable signal):
- `payload.type == "user"` → user messages (corrections, decisions, friction)
- `payload.type == "assistant"` → agent responses (patterns, approaches)
- `payload.type == "sub_agent_start"` → subagent dispatch (prompts, delegation patterns)
- `payload.type == "sub_agent_complete"` → subagent results (success/failure patterns)

User payload keys are `_meta, content, documents, images, type`, with `content` a string (user machine, full scan of 274 `messages.jsonl` files, 2026-09-24).

Not every `payload.type == "user"` record was typed by the user. kiro-cli writes harness records with that type too: a record whose `_meta.kiro.notification` is set (workflow progress and system notifications, often with `source: "steer"`), and text that opens with `[WORKFLOW NOTIFICATION]`, `<original_user_request>` (a workflow child restating the request) or a `{"method":"_kiro/…"}` JSON-RPC body. The stripper renders these `[system]`. Live steering is the user's own and stays `[user]`: `[LIVE STEERING …]` blocks and plain `source: "steer"` text (full scan, 2026-10-09: 1,227 harness records among 3,519 `user`-typed ones).

**A skill invocation is persisted as the expanded skill body**, `$ARGUMENTS` substituted, with **no leading `/<skill>`** — 211 files contained `/qdream` text and no user message started with it (same scan). Detect an invocation by the skill body itself, never by a leading slash command. The manifest script replaces the body with `[skill body: <name>]` and keeps the substituted arguments and the user's own text around it.

**Skip** (verbose, low signal):
- `payload.type == "tool_result"` — tool output bloat
- `payload.type == "usage_summary"` — performance stats only; it carries **no token counts** (`promptTurnSummaries` empty in all 1,220 records, same scan), so a Kiro sweep records `tokens: null`
- `payload.type == "session_metadata"` — runtime internals
- `payload.type == "steering_inclusion"` (in sub-execution files) — loaded governance text

### Workspace hash resolution

The workspace hash is opaque (internal derivation). To map a hash to a workspace path, read `session.json` from any session inside that hash directory — the `workspacePaths` field contains the resolved path.

### Retention

**Measured on kiro-cli 2.26.1 (Windows), 2026-10-01.** kiro-cli has a `cleanup.periodDays` setting, a flat key in `~/.kiro/settings/cli.json` (`kiro-cli settings cleanup.periodDays <N>`). Its embedded help describes it as "Days after which old conversations, sessions, and knowledge bases are deleted" and does not state a default. On the measuring machine the key was unset and no v3 session had been deleted: the oldest `sess_*` dated from 2026-06-18, the day v3 was adopted, 105 days earlier, and v2 files under `cli/` had survived 169 days. `dream-manifest.py` therefore flags a Kiro session near deletion only when the key is set, at `max(1, cleanup.periodDays - 7)` days of `messages.jsonl` mtime, as for Claude Code. Re-probe when the version changes, or if a session younger than the configured age disappears.

### No conversation database

v3 does NOT use `data.sqlite3` or any database for session storage. All session data is file-based:
- Discovery: enumerate `sess_*/session.json` files in each workspace-hash dir
- Content: read `messages.jsonl` per session
- The v2 `conversations_v2` table in `%LOCALAPPDATA%\Kiro-Cli\data.sqlite3` is NOT written by v3 sessions

This means `/qdream` session scanning for v3 is a filesystem walk, not a DB query.
