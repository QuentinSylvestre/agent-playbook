# Kiro reference material

On-demand reference material for Kiro's kiro-cli and IDE surfaces. Nothing here is in
`inventory.tsv`, so nothing here is ever deployed into a session — a file is read only when a task
needs it. Indexed from `memory/topics/kiro-cli.md § Reference documents`, which names the condition
to read each one under.

Files:

- `kiro-cli-v2-local-data.md` — retired kiro-cli v2 session store, agent profiles, hooks, ACP.
- `kiro-cli-v2-memory-sources.md` — where v2 (and Kiro IDE) sessions live, for `/qdream` harvesting.
- `kiro-cli-v2-session-resume-recovery-2.14.0.md` — dirty-state resume workaround, v2/2.14.x only.
- `kiro-cli-v3-internals.md` — v3 ACP/protocol byte-level detail: handshake, notification catalogue, KAS bundle internals, workspace-hash derivation, and the stores keyed by that hash.
- `kiro-ide-local-data.md` — Kiro IDE chat history (v3 sessions and the legacy `workspace-sessions` store, execution data) and its path-keyed workspace state.
- `symlink-investigation-2026-08.md` — symlink and nested-folder support matrices for kiro-cli and the Kiro IDE, with method notes and open gaps.
