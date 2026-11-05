# Glossary

Terms used across the governance, skills and scripts. Where a term has rejected synonyms, the
governance avoids them; so should contributions. The canonical list for the memory subsystem is
[AGENTS.md § Terminology](../AGENTS.md).

| Term | Meaning |
|---|---|
| **Config repo / engine** | This repository: governance, skills, setup and guard scripts. |
| **Pointer file** | `~/.agent-playbook/config`, written by setup: `root=`, `stores=`, `stores_url=`, `engine_branch=`, `providers=`. |
| **Engine branch** | `local-improvements`: where your clone's own engine commits land. `main` moves only by your merge. |
| **Store repo** | Your private git repository at `~/.agent-playbook/stores` holding every workspace store and your user memory. Not "stores repo". |
| **Workspace store** | A `<name>-<hex>` directory in the store repo holding one workspace's memory, plans and artifacts. |
| **Store scratch folder** | The gitignored `scratch/` in a workspace store, for temporary working files that must outlive a session. It cleans itself. Not "scratch space". |
| **Session scratchpad** | A harness's own per-session temporary folder, for files needed only in that session. |
| **STORE file** | A store's identity file: `remote <host/owner/name>` (plus optional `path <subpath>`), or `local <path>`. |
| **Store resolver** | `store-resolver.py`, whose `find` and `find_or_create` map a folder to its store. Not "store lookup". |
| **User memory** | Cross-project memory: `memory/MEMORY.md` and `memory/topics/*.md`, behind the engine's `memory` link to `user/memory/`. |
| **Topic memory** | A user-memory file that loads on demand when its trigger (a condition) matches, indexed in `MEMORY.md § Topics`. |
| **Higher-order memory** | `memory/HIGHER_ORDER.md`: abstractions the sweep induces from episodes and entries. Read-time advisory. |
| **Project memory** | `memory/MEMORY.md` in a workspace's store. |
| **Suspect memory entry** | An entry a deterministic check flagged for full re-verification. Never evidence of staleness by itself. |
| **Event-driven memory validity** | Re-verifying an entry only when something it depends on changed, plus a rotating backstop. |
| **Session-start memory context budget** | The ratcheted word limit over always-loaded user memory, pinned in a script. |
| **Improvement signal** | A recorded governance gap (friction, a missing rule, a skill idea) that the sweep turns into a proposal. |
| **Plan-less governance capture** | Recording improvement signals, and fixes to wrong memory, from a session with no project file. |
| **Sweep** | One `/qdream` run: Orient, Gather, Synthesize, Decide, Apply. |
| **Phase agent** | The fresh sub-agent that runs one sweep phase. Not "phase worker". |
| **Handoff file** | A work-folder file carrying sweep state between phases. Not "checkpoint". |
| **Drafter** | The read-only agent that prepares gate proposal text. Not "writer". |
| **Project file / plan** | The Markdown plan `/qplan` writes and `/qdev` executes, archived by `/qclose`. |
| **Overlay** | `providers/kiro/skills/<name>/OVERLAY.md` (or `<stem>.OVERLAY.md`): Kiro-only text appended to a shared skill file at deploy time. |
| **Guard script** | A stdlib-only Python check with its own `--selftest`, run by `run-checks.py` and CI. |
