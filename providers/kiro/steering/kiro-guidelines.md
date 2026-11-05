# Kiro-Specific Guidelines

## Project-Level AGENTS.md Ingestion

When working in any project, check whether the workspace contains:

- `AGENTS.md` / `CLAUDE.md` at the workspace root or any subfolder
- `*.md` files under any nested `.kiro/steering/`
- `SKILL.md` files under any nested `.kiro/skills/<name>/`

Treat any such file's contents as strong guardrails — equivalent to how Claude Code and other AI harnesses automatically ingest them. This compensates for Kiro not auto-discovering these files and not loading nested `.kiro/` directories.

**Auto-suggest rule**: This rule fires **only when the agent is already reading or modifying files inside a subtree that contains an unwired source file**. It does not require a workspace-wide scan on every turn — observation is bounded by the files the current task already touches. Concretely: if the agent reads `frontend/components/foo.tsx` and notices `frontend/AGENTS.md` exists with no corresponding `inclusion: fileMatch` steering file under the workspace root's `.kiro/steering/`, the rule fires.

When fired, suggest running `/qwire-governance` before continuing. Trigger conditions (any of):

- A subfolder `AGENTS.md`/`CLAUDE.md` exists in the subtree, no fileMatch steering file at root references it.
- A subfolder `.kiro/steering/*.md` exists in the subtree, no wiring at root references it.
- A subfolder `.kiro/skills/<name>/SKILL.md` exists in the subtree, no wiring at root references it.

When suggesting, **name the specific unwired file you observed** (e.g., "I noticed `frontend/AGENTS.md` exists but is not yet wired into root-level `.kiro/steering/`"). The user needs to know the trigger to evaluate the suggestion.

The skill is non-destructive (creates new steering files; user content never modified per Phase 3 § Rules). Do not silently work around the missing wiring. If the user declines, proceed but flag in the response that subfolder governance is not loaded.

**Wiring schema** (set by `/qwire-governance`, documented here as reference):

- Workspace-root `AGENTS.md` / `CLAUDE.md` → `inclusion: always` steering file with `#[[file:...]]` transclusion.
- Subfolder governance and nested `.kiro/` content → `inclusion: fileMatch` steering file with `fileMatchPattern: '<subfolder>/**'`. Loaded only when work is scoped to that subfolder.
- A store-backed workspace → two reserved names. `__store__.md` is an `inclusion: always` file naming the store's absolute path in prose. `__store_memory__.md` is a **symlink** to the store's `memory/MEMORY.md` and carries no frontmatter, because it is that raw memory file. See `## Wiring a Store-Backed Workspace into kiro-cli` below.

See `/qwire-governance` Step 3 for canonical schema, naming convention, and the subfolder-conflict precedence rule for `## Doc & Test Guidelines`; Step 3b for the store wiring's two parts.

**`#[[file:...]]` does not load anything, on kiro-cli v2, v3 or the Kiro IDE.** Every occurrence in any bundle is producer prose in the system prompt describing the feature to the model — there is no resolver. A steering file that carries the directive reaches the model as literal text, with no file read and no warning. Use it only where the transclusion schema above already documents it as a convention. **Never use it as a loading mechanism.**

**To put a file's contents into a Kiro session, symlink it into `<workspace>/.kiro/steering/`** — the filesystem resolves the link before Kiro reads anything, so the content arrives through the ordinary steering glob, frontmatter or not. (This replaces the former advice to add the file to an agent definition's `resources` list: per-workspace store agents are **retired** — see `## Wiring a Store-Backed Workspace into kiro-cli` below.)

> **Word a verification probe so the session's own loaded governance cannot supply the answer** — ask for a neutral, nameless observation (e.g. a distinctive nonsense phrase) rather than a yes/no verdict on a mechanism this file already describes as settled.

## Agent Definition (v3)

The playbook deploys two agent definitions for `kiro-cli` v3: the working agent `kiro_default`, and `qdream_child`, the read-only child that `/qdream` phase agents launch.

| Source file | Deploy kind (`inventory.tsv`) | Token substitution |
|---|---|---|
| `providers/kiro/agents/kiro_default.md` (YAML frontmatter) | `template-file` | `{{PLAYBOOK_ROOT}}` |
| `providers/kiro/agents/qdream_child.md` (YAML frontmatter) | `copy-file` | none |

providers/kiro/agents/kiro_default.json was the v2 agent definition. It is **deleted** (git history has it, commit `5416c25`) and **not deployed** — v2 is retired. Running `kiro-cli chat` without `--v3` falls back to the built-in `kiro_default` agent.

`template-file` substitutes `{{PLAYBOOK_ROOT}}` at deploy time, so the memory resource line carries the token directly: `"file://{{PLAYBOOK_ROOT}}/memory/*.md"`. The value is double-quoted YAML. Since `0d4e0df`, `setup.ps1` renders a Windows root with forward slashes (`C:/Users/X`), which need no escaping in YAML, JSON or a `file://` URI. No YAML comments belong in the frontmatter (a v3 parse failure falls back to `vibe` with no error). No machine-specific path is authored by hand — the deploy substitutes the real root every time; after moving the repo to a new location, re-run setup so the path is regenerated. The `model:` pin (currently `claude-sonnet-4.6`) is a separate, per-machine preference, edited directly in the repo source rather than templated.

**Measured on Windows** (kiro-cli 2.27.1, `kiro_default`, interactive `/context show`, 2026-10-06): the rendered config-repo glob loaded `MEMORY.md` and `HIGHER_ORDER.md` both at a workspace root and from a subfolder.

`kiro_default.md` loads playbook memory with a **non-recursive** glob, `memory/*.md`. Keep it non-recursive. A recursive glob also loads `memory/topics/*.md`, which defeats the on-demand topic tier described in `shared/AGENTS.md § Memory locations`.

**Which `resources:` line delivers which tier — Kiro's classification under `shared/AGENTS.md § Read-time behavior`.** Measured with interactive `/context show` and a headless sentinel probe (kiro-cli 2.27.1, `--v3`, 2026-10-06). A *root start* means the session's working directory is the workspace root (the directory holding `.kiro/` and, if any, `memory/`). Every workspace-relative `file://` line resolves against the working directory, so a subfolder start matches none of them; `/context show` reported "no matches" for `AGENTS.md`, `README.md`, `memory/*.md` and `.kiro/steering/**/*.md` from a subfolder. The workspace-relative `skill://` line was not probed.

- **Global tiers** (user `MEMORY.md` and `HIGHER_ORDER.md`): `"file://{{PLAYBOOK_ROOT}}/memory/*.md"`, from any working directory. A Kiro session does not re-read those two files. In the config repo itself, `file://memory/*.md` matches the same two files again.
- **Project tier, root-level `memory/`**: `file://memory/*.md`, on a root start only. It loaded the workspace's `memory/MEMORY.md` at the root and matched nothing from a subfolder.
- **Project tier, store-backed workspace**: `file://.kiro/steering/**/*.md`, through `<workspace>/.kiro/steering/__store_memory__.md`, a symlink to the store's `memory/MEMORY.md`. Measured by the user on 2026-10-08 (kiro-cli 2.28.0): `/context show` at the root of a store-backed workspace listed `.kiro/steering/__store_memory__.md` (0.4%) and `__store__.md` as loaded. The steering glob is root-only (the 2026-10-06 measurement), so the link and the `__store__.md` pointer beside it arrive on a root start only — see the section below.
- **Subfolder start, either layout**: no line delivers the project tier. This file still arrives, because it is global steering.

So: (a) on a root start the project memory is usually already in context (from a root `memory/`, or a present `__store_memory__.md` link); still read it. A Kiro session cannot confirm that the tier arrived in full (a resource that matches nothing loads silently), and `shared/AGENTS.md § Read-time behavior` skips only a tier delivered in full, so reading it is what guarantees the tier whichever case applies. A root start with neither a root `memory/` nor a `.kiro/steering/__store__.md` pointer may still be a store-backed workspace that `/qwire-governance` never wired, so nothing in context says a store exists: treat it as (b) and ask the resolver; on exit 0, also say the workspace is unwired and suggest running `/qwire-governance` there. (b) On a subfolder start, nothing delivers it. Ask the store resolver for the folder: `<config-repo>/.venv-agent-playbook/Scripts/python.exe -I <config-repo>/shared/skills/qdream/scripts/store-resolver.py find "<working directory>"` walks from the folder up to its git toplevel and, on exit 0, prints the store directory; the project tier is `memory/MEMORY.md` in it. Exit 3 means the folder has no store: only in a no-create folder (`shared/skills/qdream/memory-rules.md § Resolution contract`, the no-create step) read the nearest `memory/MEMORY.md` from the folder up to its git toplevel; anywhere else an in-workspace copy is a leftover, so proceed without project memory and say so. Exit 2 means the store repo could not be read: say so and read nothing. Never derive or guess a store directory instead. Full rules: `shared/skills/qdream/memory-rules.md § Resolution contract`. The same start also loses the workspace `AGENTS.md` and `.kiro/steering/` files, so read those you need.

**Re-verify when** kiro-cli changes minor version.

## Wiring a Store-Backed Workspace into `kiro-cli`

A workspace keeps its memory and its project files in the store repo (`~/.agent-playbook/stores`) instead of in the workspace; the store resolver finds it, or creates it, from the folder. The layout and the resolution contract are defined in `shared/skills/qdream/memory-rules.md § Workspace Store`. This section covers only how a Kiro session is told where that store is.

Kiro has no documented session scratchpad, so temporary files always go in the store scratch folder (`shared/skills/qdream/memory-rules.md § Store scratch folder`).

**The wiring is one mechanism in two parts**, both under `<workspace>/.kiro/steering/` and both written by `/qwire-governance` Step 3b. `kiro_default` loads `file://.kiro/steering/**/*.md` **workspace-relative**, so anything in that directory reaches the model on a **root start**, with no agent to select, no resource list to copy and nothing to keep in step with `kiro_default`. From a subfolder start nothing in it loads — see the tier paragraph under `## Agent Definition (v3)` above.

| Part | Artifact | Covers | Loading |
|---|---|---|---|
| Pointer | `__store__.md`, a generated steering file | The store's `plans/`, `plans/done/`, `plans/tests/`, plus the fallback instruction for memory | Its own text arrives mechanically; the reads it names are behavioural |
| Memory link | `__store_memory__.md`, a symlink to `<store>/memory/MEMORY.md` | The project memory tier | The memory file's contents arrive mechanically |

**Both are kept. Neither is redundant.** The symlink carries memory and nothing else; the project files are never loaded into context and still need prose telling you to open them. The pointer is written first and the symlink second, so a `__store_memory__.md` never sits in a steering directory without the pointer beside it explaining what it does not cover.

**Kiro follows symlinks in `.kiro/steering/`, frontmatter or not** — a target shaped exactly like a store `MEMORY.md` (opening `# Project Memory — <name>`, no `---` block) loads the same as any other steering file. Full matrix across v3 and the IDE, including the superseded IDE-symlink finding that is why `setup.ps1` copies on Windows: `## Symlinks and Folder Structure in `.kiro/`` below.

**Skills behave the same way, and so does the global `~/.kiro/` tier.** Do not infer one from the other — steering loads through `file://` resources and skills through `skill://`, a different resolver. Full matrix, including which folder layouts work: `## Symlinks and Folder Structure in `.kiro/`` below.

**Transclusion is still dead, and that is a different mechanism.** `#[[file:...]]` has no resolver on any surface (above), so a steering file that carries the directive reaches you as literal text. A symlink is not transclusion: it is resolved by the filesystem before Kiro reads anything, so what Kiro loads is an ordinary steering file that happens to live elsewhere. **The pointer's own reads remain behavioural** — it names the store's absolute path and instructs you to open the project files with your file-read tool.

**When the symlink is missing, the wiring degrades to the pointer — never to silence** (on a root start; from a subfolder neither part loads). Four things stop it being created, and all four leave the pointer working: the store has no `memory/MEMORY.md` yet; the machine cannot create symbolic links (on Windows they need Developer Mode or an elevated shell); the created link failed its `LinkType` check and was deleted; or a conflicting file already holds the name. A fifth case appears later — the store memory file is moved or deleted and the link goes dangling — and `/qwire-governance` removes the broken link on its next run rather than leaving something that reads as wired. **In every store-backed session, linked or not, read the store's `memory/MEMORY.md` yourself at the path the pointer names** (on a subfolder start the pointer is absent too; resolve the path per point (b) of the tier paragraph). A store-backed workspace where you cannot see memory content in your context is the normal, working, degraded state, not a fault to work around.

**Create such a symlink with PowerShell `New-Item -ItemType SymbolicLink` and verify `LinkType` afterwards. Never with Git Bash `ln -s`** — on Windows it writes a plain **copy** instead: `LinkType` empty, and later edits to the store file do not propagate. A copy in a steering directory is the exact drift the store was built to remove, and it is indistinguishable from a link in a directory listing.

**Per-workspace store agent definitions are RETIRED. Do not create one.** They were wired through a `<workspace>/.kiro/agents/<name>.md` definition carrying a `file://` store resource — it worked, and was withdrawn anyway, for three reasons that the pointer removes rather than mitigates:

- **It duplicated `kiro_default`.** Registration is by `name` and never merges two definitions, so each workspace agent had to carry a **full copy** of `kiro_default`'s resource list plus one store line. Every copy went stale the next time the playbook's own `kiro_default` changed. One agent definition per workspace is one drift site per workspace.
- **Nothing could see the drift.** `verify-deployment`'s destination-side scan is scoped to containers the playbook owns exclusively, and provider roots are not among them — the duplication sat in a blind spot, not merely an unguarded one.
- **Selection was manual and easy to forget** — an in-session agent switch, not a `--agent` flag on the command line — and a `.md` agent was invisible to v2 entirely, whose `agent` subcommand family was JSON-only.

**Inheritance does not rescue a custom agent.** A minimal agent declaring exactly one resource still receives the workspace's `AGENTS.md`, the workspace's `.kiro/steering/**/*.md`, and every globally-registered skill — but not the `~`-rooted resources only `kiro_default` declares. So Kiro's own default workspace context is inherited and `kiro_default`'s `resources` list is not, which is why the full-copy rule existed. The same fact is the direct evidence for the pointer: a workspace-local `.kiro/steering/` file arrives **without any agent declaring it**.

**Wire neither part when the workspace root is the user's home directory.** There, `<workspace>/.kiro/steering/` **is** `~/.kiro/steering/`, which `kiro_default` loads in *every* workspace through `file://~/.kiro/steering/*.md`. A pointer there would tell every session to read one workspace's memory — wrong project memory in every other project — and a symlink there would be worse still, putting that memory into every session's context mechanically. Both would also land in a playbook deploy target, where `verify-deployment` reports them as orphans. That workspace gets **no mechanical wiring at all**: read its store by instruction, at the path resolution returns. `/qwire-governance` Step 3b refuses this case and says so.

**Both artifacts are derived, never authoritative.** The store directory's `STORE` file is the single source of truth for which workspace a store directory serves. The pointer and the symlink are generated from the resolver's answer and can be regenerated at any time — deleting either and re-running `/qwire-governance` is always safe. When they disagree with `STORE`, `STORE` wins.

**Find the store with the resolver, never by deriving a directory name** from a basename and a hash: it scans the `STORE` files and compares identities, so a renamed or moved checkout of the same remote still finds its store.

**In a repository the user does not own, exclude both artifacts in `.git/info/exclude`, not in the tracked `.gitignore`.** `.gitignore` is a tracked file, so editing it changes another team's repository. `.git/info/exclude` is local to the clone and changes nothing they see.

## Symlinks and Folder Structure in `.kiro/`

Symlinks work on the Kiro IDE, and on kiro-cli v3, for files, directories and containers (a symlinked skill or steering directory itself), at both the project and user tiers. Create links with PowerShell `New-Item -ItemType SymbolicLink`, never Git Bash `ln -s`, which writes a plain copy on Windows.

The IDE rejects nested skill directories (`skills/<category>/<name>/SKILL.md`) at both tiers, with no setting to change it — its scanner is a flat, non-recursive `readdir`. Keep every skill the IDE must see at flat `skills/<name>/SKILL.md`.

Copies on Windows are a **deployment choice**, not a symlink limitation — the deploy still writes copies; edit the repo source, never `~/.kiro/`.

Method, matrices and open gaps: `providers/kiro/reference/symlink-investigation-2026-08.md`.

**Re-verify when** the IDE or CLI minor version changes.

## Skill Invocation

(Reinforces `shared/AGENTS.md § Workflow`.) Kiro-specific delta: the skill catalogue delivered into context exposes only the frontmatter `description` — the body is not injected until the skill is invoked. On invocation (e.g. `/qexplore`, `/qplan`, `/qdev`), read the skill's `SKILL.md` in full plus any files its preamble or process references (e.g. `shared.md`, `TEMPLATES.md`) before executing Step 1 of its `## Process`. The one-line description is NOT sufficient to execute the skill.

## Skills and Steering are Copies

Plain skills and steering files in `~/.kiro/` are **symlinks** into the `agent-playbook` config repository on every platform (since 2026-09-20; Windows needs Developer Mode or an elevated shell for `setup.ps1` to link). Overlay-bearing skills are the one exception: the deploy must overwrite one file inside the skill directory, which a symlinked directory forbids, so those are **generated copies** (`shared + overlay`) rewritten on every setup run. Either way the rule is the same: edit the repo source, never `~/.kiro/`.

When the user asks to modify a skill or steering file:
1. Make the edit in the agent-playbook repo (shared skills in `shared/skills/`, Kiro-specific skills in `providers/kiro/skills/`, steering in `providers/kiro/steering/` or `shared/AGENTS.md`).
2. Commit the edit by pathspec. Never run `/qconfig-sync` yourself; at the end of the task, ask the user to run it to verify and push the edit.
3. For an overlay-bearing skill, re-run `setup.ps1` (Windows) or `setup.sh` (Linux/WSL/macOS) so the generated copy is rebuilt; symlinked files pick the edit up immediately.

Auxiliary skill files (not just `SKILL.md`) can also carry kiro overlays: a `<stem>.OVERLAY.md` is appended at deploy time to the deployed `<stem>.md` aux file (e.g. `memory-rules.OVERLAY.md` -> `memory-rules.md`). The steering file `kiro-governance-discipline.md` carries AGENTS.md-level discipline demoted from shared; edit it (like all steering) in the config repo source.

## Co-located Skill File Resolution

When a skill instruction references a file as "co-located with this skill file" or "in the same directory as this SKILL.md", the file lives in the skill's directory under `~/.kiro/skills/<skill-name>/`.

Do NOT use `fileSearch` for these files -- it only searches the workspace. Instead, construct the path directly: if the current skill is `/qplan` and it references `TEMPLATES.md`, read `~/.kiro/skills/qplan/TEMPLATES.md` using `fs_read` or `listDirectory`.

General pattern: `~/.kiro/skills/{skill-name}/{referenced-file}`

## File Writing Resilience

The `fsWrite` and `fsAppend` tools have no fixed line or byte limit, but the model's output token budget per tool call is finite and varies with conversation length, line complexity, and context pressure. Writes that succeed early in a session may fail or truncate later.

When a write fails or produces truncated output, apply progressive chunk reduction:

1. **First attempt**: write the full content in one `fsWrite` call.
2. **On failure**: split into 2 chunks -- `fsWrite` for the first half, `fsAppend` for the second.
3. **On repeated failure**: halve the chunk size again and continue splitting until writes succeed.
4. **After each write/append**: verify the file has the expected line count before moving on. A quick `wc -l` or equivalent check is sufficient.

Do not preemptively chunk small files. Only escalate to smaller chunks when a write actually fails.


## File Verification Thoroughness

When asked to check whether a file is up-to-date, has changed, or matches another source, always read the full file body — not just frontmatter, headers, or metadata fields. The description/title fields do not reflect body changes. Never short-circuit a verification by reading only the first few lines.

The same applies to reading a skill file before running it. When `fs_read` returns a notice that the content was truncated (for example "to fit the available context"), the skill has loaded only in part. Before executing the skill's first step, re-read the file in parts (by line range or offset) until every line has been seen. Do not run a skill on a partial load.

## Review Effort

All `/qreview` skill executions MUST use full effort. No abbreviated, shallow, or reduced-scope reviews. Every review runs the full process with all applicable personas at full depth, regardless of change size, time pressure, or perceived simplicity. No exceptions.

## Council Tier

All `/qcouncil` invocations run the Full pipeline (advocate-prosecutor-juror + assumption challenger + sensitivity analysis). The Light council tier does not apply to kiro.

Default per plan tier: `shared/AGENTS.md § Workflow` (One effort vocabulary).

## Disposable Work Separation

Code with a known expiry (one-time migrations, data repairs, temporary workarounds, diagnostic tools) must not be integrated into the product's permanent surface area (CLI flags, modules, API endpoints, test suites). Implement it as throwaway infrastructure that can be deleted without touching the product. Examples: standalone scripts, temporary files, one-off notebooks.
