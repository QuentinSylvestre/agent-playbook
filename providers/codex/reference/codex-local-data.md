## Codex Local Data

> **Reference only — not deployed.** What Codex (CLI, VS Code extension, desktop app) keeps on disk on
> Windows, and what of it is keyed by a workspace path. **Read when** reading Codex's session store or
> moving a workspace (`shared/skills/qmigrate-workspace/SKILL.md`).
>
> The measured record shapes, the writer lock, token records, process shape and read costs live in the
> PowerAtlas repository's `docs/KNOWLEDGE.md` (section "Codex sessions", codex 0.159.2, 2026-10-01 and
> 2026-10-02). This file does not repeat them; the layout summary below agrees with it.

### Layout

Root: `CODEX_HOME` when set and non-empty, else `~/.codex`.

| Path | Content |
|---|---|
| `sessions/YYYY/MM/DD/rollout-<local timestamp>-<uuid>.jsonl` | one thread per file, the canonical record; first line `session_meta` (its `payload.cwd` is the session's workspace), `turn_context` records repeat `cwd` |
| `archived_sessions/` | archived threads, same format |
| `state_5.sqlite`, table `threads` | catalogue projection of the rollouts: `cwd`, `sandbox_policy` (JSON naming writable roots), `title`, `first_user_message`, `preview`, among others |
| `thread_history_1.sqlite` | projection of rollout items (`item_json`), with byte offsets into the files |
| `session_index.jsonl` | `id`, `thread_name`, `updated_at`; no path |
| `sqlite\state_5.sqlite`, `sqlite\codex-dev.db` (`local_thread_catalog.cwd`) | a second catalogue pair seen on this machine; which client writes it was not established |
| `thread-writer-locks/` | per-thread writer locks (protocol: PowerAtlas `docs/KNOWLEDGE.md`, "Writer lock") |

`cwd` forms: plain backslash drive paths. The VS Code extension writes a lower-case drive letter and the
CLI an upper-case one, so any matching must ignore case.

### Path-keyed state (moving a workspace)

Measured 2026-10-02 (codex-cli 0.159.x-0.160.0, Windows) while moving a tree that held 363 top-level threads:

| Where | What holds the path | On a move |
|---|---|---|
| rollouts whose first `cwd` is inside the tree | `session_meta.payload.cwd`, `turn_context.cwd`, `workspace_roots` | rewrite the whole file |
| `threads` in both `state_5.sqlite` files | `cwd`, `sandbox_policy` | update those columns only |
| `sqlite\codex-dev.db` `local_thread_catalog` | `cwd` | update |
| `config.toml` | `[projects.'<path>']` trust entries | rewrite |
| `.codex-global-state.json` | workspace entries (5 occurrences here; the exact keys were not mapped) | rewrite |
| `process_manager\chat_processes.json`, `rules\default.rules` | paths in saved processes and approved command rules | rewrite |
| `threads.title`, `first_user_message`, `preview`; `thread_history_1.sqlite` item bodies; logs | user text and history | leave as is |

Every Codex process must be closed first, including the desktop app (it holds the writer lock of every
thread it opened until it exits) and helper services such as `codex-windows-sandbox-service`. After the move,
the threads listed under the new paths (user-confirmed). OpenAI publishes no stability guarantee for these
files: re-scan before trusting this table on a newer release.
