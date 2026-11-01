## Kiro IDE Local Data

> **Reference only — not deployed.** Where Kiro IDE keeps chat history and workspace state on Windows.
> It loads on demand only — not in `inventory.tsv`. **Read when** recovering, mining or moving Kiro IDE
> history. Moving a workspace: `shared/skills/qmigrate-workspace/SKILL.md`;
> `shared/skills/qmigrate-workspace/scripts/kiro-ide-migrate.ps1` implements the legacy-store steps below.

### Two stores

Kiro IDE 1.0.x (measured on 1.0.437, 2026-09-24) saves **new** chats as kiro-cli v3 sessions under
`~/.kiro/sessions/<workspace-hash>/` — see `providers/kiro/reference/kiro-cli-v3-internals.md`. Opening a
workspace, or chatting in it, never creates the legacy folder below, which holds only older history.
Whether Kiro IDE 1.0.x still displays that legacy history at all was not established.

**Never "prime" a workspace by chatting in it.** When the workspace already has v3 sessions, Kiro IDE
resumes the most recent one instead of starting a new chat, so a throwaway message lands in a real session,
and deleting it as a throwaway deleted that session (2026-09-24, one session lost).

### Legacy workspace sessions

Location: `%APPDATA%\Kiro\User\globalStorage\kiro.kiroagent\workspace-sessions\<base64url-workspace>\`

- **Folder name**: base64url of the workspace path with only the **drive letter** lower-cased
  (`c:\Users\alice\...`); the rest keeps its case. The alphabet is standard base64 with
  `+` → `-`, `/` → `_`, and the padding kept but written as `_` (names end in `__` for two padding
  characters). Measured 2026-10-02: 25 of the 26 folders whose `sessions.json` records a
  `workspaceDirectory` re-encode from it byte for byte; the 26th was not investigated. No name contains
  `?` or `=`. To decode, read trailing `_` as padding and any other `_` as `/`.
- **`sessions.json`**: a JSON array of `{sessionId, title, dateCreated, workspaceDirectory, hidden?}`;
  `dateCreated` is a string of Unix milliseconds. It can start with a UTF-8 BOM (1 of 30 files, PowerAtlas
  2026-09-28): decode with `utf-8-sig`.
- **`<sessionId>.json`**: one file per chat, up to hundreds of KB, with a `history` array whose entries carry
  `message`, `contextItems` and a deeply nested `editorState.content` tree. **Never parse these with a
  depth-limited tool** (PowerShell's `ConvertFrom-Json` silently truncates them); rewrite paths as raw text.
- **Execution data is separate.** Assistant messages in the session file hold the placeholder `"On it."`;
  the real content is under `kiro.kiroagent\<32-hex storage hash>\<hash>\...`. Without it a session shows
  "Loading execution..." forever. The executionId-level link from a session to its storage directory was
  not traced end to end.

### Moving a workspace (legacy store)

Measured 2026-10-02, three workspaces (0, 21 and 35 legacy sessions), Kiro closed:

- The migrate script copies the session files into the new base64url folder, merges `sessions.json`
  (dedup by `sessionId`), rewrites `workspaceDirectory`/`workspacePath` as raw text, and removes the old
  folder at the end. **Back the old folder up first.** It keeps the old execution-data directory.
- Execution-data discovery resolved the old and the new workspace to the **same** storage hash, so no
  execution data was copied and none needed to be: the sessions still point at it. The log-based discovery
  never matches a freshly created target folder (also seen in six migrations on 2026-09-24).
- The source and target workspaces must not be open in Kiro while it runs.
- **Encoding**: the 2026-10-02 run used a version of the script that read with Windows PowerShell 5.1's
  `Get-Content -Raw` (ANSI for BOM-less UTF-8) and wrote with `Set-Content -Encoding UTF8` (adds a BOM).
  58 of the 59 migrated session files gained a BOM and every non-ASCII character in 41 of them was
  corrupted (`—` became `â€”`). The script now reads and writes BOM-free UTF-8 explicitly; the 59 files were
  rebuilt from the pre-migration backup.

### Other path-keyed IDE state

| Where | What | On a move |
|---|---|---|
| `globalStorage\storage.json` | recent and backup workspace lists | rewrite |
| `globalStorage\state.vscdb` (+ `.backup`), table `ItemTable` | recently-opened list and other values naming the path | update the cells |
| `workspaceStorage\<hash>\workspace.json` + its `state.vscdb` | per-folder UI state (open editors, layout); the hash cannot be recomputed | starts fresh at the new path |
| `kiro.kiroagent\<storage hash>\...` | execution logs; tool arguments mention paths | history, leave as is |

VS Code (`%APPDATA%\Code\User\globalStorage`) has the same `storage.json` and `state.vscdb` shape.
