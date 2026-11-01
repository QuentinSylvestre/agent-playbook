## Kiro-CLI Local Data

> **Also read `memory/topics/kiro-cli.md` in the config repo** when *driving* kiro-cli rather than
> reading its files — ACP, agent definitions, CLI flags, v3 agent authoring. This file says where the
> data lives; that one records how the tool behaves, including three flags that accept invalid values
> in silence and a trust flag (`--trust-tools`) that is not the boundary its name implies.
>
> Byte-level protocol material — ACP handshake sequencing, JSON-RPC id quirks, the notification
> method catalogue, KAS bundle internals, the workspace-hash derivation proof — lives in
> `providers/kiro/reference/kiro-cli-v3-internals.md`, read on demand only.

### Session files

Location: `~/.kiro/sessions/<workspace-hash>/sess_<uuid>/`

Each session is a directory containing:

| File | Purpose |
|---|---|
| `session.json` | Metadata (agent, model, timestamps, status) |
| `messages.jsonl` | Conversation content (user/assistant/tools) |
| `snapshots/<hash>/` | File snapshots created during session |
| `sub-executions/<uuid>.jsonl` | Subagent conversation content (older shape; see `rootConversationId` below for the newer one) |

The workspace hash is the first 16 hex chars of a SHA-256 over the normalized, sorted workspace path set (case-sensitive on Linux/macOS, lowercased on Windows); empty `workspacePaths` hashes to `"_global"`. Full derivation and a Python reference implementation: `providers/kiro/reference/kiro-cli-v3-internals.md § Workspace-hash derivation proof`.

The same hash also names `~/.kiro/session-index/<hash>.jsonl` and `~/.kiro/workspace-roots/<hash>/`, and each hash folder holds a shared `.index/` cache: moving or renaming a workspace touches all of them (`providers/kiro/reference/kiro-cli-v3-internals.md § Stores keyed by the workspace hash`; procedure: `shared/skills/qmigrate-workspace/SKILL.md`).

`kiro-cli chat` with no engine flag writes to the retired v2 layout instead — see `providers/kiro/reference/kiro-cli-v2-local-data.md`. The two stores are disjoint and separately enumerated; `kiro-cli chat --list-sessions -f json` is the only surface that reads both, tagging each entry `"source": "v2" | "v3" | "classic"`.

### Session metadata (`session.json`)

```json
{
  "schemaVersion": "1.0.0",
  "dataModelVersion": 1,
  "id": "sess_<uuid>",
  "title": "...",
  "agentMode": "kiro_default",
  "workspacePaths": ["C:\\..."],
  "createdAt": "ISO-8601",
  "lastModifiedAt": "ISO-8601",
  "modelId": "claude-opus-4.6",
  "autopilot": true,
  "semanticReviewEnabled": true,
  "ftaEnabled": false,
  "description": "Auto-generated session summary",
  "status": "idle"
}
```

Key fields for filtering:
- `createdAt` / `lastModifiedAt` — ISO-8601 strings. `/qdream` dates new turns by each `messages.jsonl` record's `timestamp`, not by these (`providers/kiro/steering/memory-sources.md § Metadata fields used by dream`)
- `workspacePaths` — project discovery (array; first entry is the primary workspace)
- `rootConversationId` — present only on a **sub-agent or workflow-node session**, which kiro-cli 2.28.0 writes as a full `sess_<uuid>/` folder beside its parent's (same hash dir, same `workspacePaths`; first seen 2026-10-06, 67 of 376 stores). It names the user-facing parent session. Absent on a top-level session, so "set and not equal to `id`" means child. A child is not a user session: skip it when listing or counting sessions (`providers/kiro/steering/memory-sources.md § Sub-agent filtering`). `agentMode` does not tell them apart.
- `agentMode` — which agent was used. Set via `_meta.kiro.modeId` on `session/new`, not a top-level `agentName` param — a request that sets `agentName` is silently dropped, since the params schema has no such field.
- `status` — enum `"in_progress"`, `"waiting_on_user"`, `"completed"`, `"idle"`, `"failed"`. System-written by KAS at every turn boundary, not model narration — but **do not trust it as a liveness signal**: v3 has no lock file, pid file or heartbeat, so a process that dies mid-turn leaves `status` stuck at `"in_progress"` forever. The only way to determine whether a v3 session is running is process enumeration external to the session store. `/qdream`'s rule for it — `in_progress` under 24 h old is deferred with a watermark, older is treated as closed — is in `providers/kiro/steering/memory-sources.md § Metadata fields used by dream`, implemented by `shared/skills/qdream/scripts/dream-manifest.py`.
- `title` — writable and stable via `update_session_information`. **Unlike `status`, it is not reset at turn boundaries** — once set it persists until explicitly changed again. `KIRO_SESSION_ID` is not set in ACP client sessions (`kiro-cli acp`); where it is set, detect the version by the `sess_` prefix.

### Hooks

v3 hooks are standalone files at `<workspace>/.kiro/hooks/*.json`, same PascalCase-trigger schema as v2 — see `memory/topics/kiro-cli.md`, "v3 standalone hooks use `.kiro/hooks/*.json` with PascalCase triggers — same format as v2".

### Environment variables available to the agent

These are set by the Rust CLI wrapper or PowerAtlas before the KAS process starts.

| Variable | v2 TUI | v3 TUI | v3 PowerAtlas terminal | `kiro-cli acp` |
|---|---|---|---|---|
| `KIRO_SESSION_ID` | bare UUID | `sess_<uuid>` (2.31.1) | not verified | not set |
| `KIRO_TUI_READY_FILE` | set | set | set | not set |
| `KIRO_AGENT_ENGINE` | not set | `kas` | `kas` | `kas` |
| `KIRO_KAS_NODE_PATH` | not set | set | set | set |
| `POWER_ATLAS_SESSION` | not set | not set | `1` | not set |
| `WT_SESSION` | set (if in WT) | set (if in WT) | set (if in WT) | not set |

On kiro-cli 2.31.1, both the interactive v3 TUI and `kiro-cli chat --no-interactive` set `KIRO_SESSION_ID` to the top-level session id (`sess_<uuid>`, the session folder's name), and `kiro-cli chat --no-interactive` passes the same value to every sub-agent's shell (probes 2026-10-16). Earlier v3 builds did not set it.

**Key discriminators:**

- **Interactive terminal session** (has a tab title to set): `$env:KIRO_TUI_READY_FILE` is set. This is the only reliable check — present for both v2 and v3 TUI, absent for `kiro-cli acp`. Do NOT use `KIRO_AGENT_ENGINE`, `POWER_ATLAS_SESSION`, or "Machine ID: acp-client" in the system prompt — none of these discriminate terminal from ACP sessions reliably (`KIRO_AGENT_ENGINE=kas` is set in both v3 TUI and ACP; "Machine ID: acp-client" is injected by KAS for ALL v3 sessions regardless of launch method).
- **v2 vs v3**: `KIRO_SESSION_ID` a bare UUID → v2; starting with `sess_` → v3. Not set + `KIRO_AGENT_ENGINE=kas` → v3 (older v3 builds and `kiro-cli acp`).
- **PowerAtlas-launched**: `POWER_ATLAS_SESSION=1`. Orthogonal to v2/v3 — a PowerAtlas terminal launch is still a full interactive TUI session.
- **Node binary**: `KIRO_KAS_NODE_PATH` — available in v3 (TUI and ACP), not in v2. The Windows Terminal title hook uses `providers/kiro/tab-title.ps1` instead.

**Re-verify when** a kiro-cli upgrade changes session-store, status or env-var behaviour.
