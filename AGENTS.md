# agent-playbook — project instructions

Project-scoped governance for the agent-playbook repo itself. Everything here
describes how *this* repository is laid out and edited, so it applies only when
the working project is the config repo.

Deliberately **not** listed in `inventory.tsv` — `setup.sh` / `setup.ps1` are
manifest-driven, so this file is never deployed to any provider and never loads
during work on an unrelated project. Cross-project rules live in
`shared/AGENTS.md`, which is deployed globally; authoring-time conventions live
in `shared/AUTHORING.md`, which is deployed but lazily read.

**Topic memory for this repo**: before changing a skill, steering file, overlay, guard script or
the memory sweep, read `memory/topics/playbook-authoring.md` (on-demand user memory; the index row
is in `memory/MEMORY.md § Topics`).

## Repository Layout

The config repo has two content directories:

- **`shared/`** -- Cross-provider instructions (`AGENTS.md`) and skills (`skills/`). Everything here is symlinked identically to all providers. Keep it provider-agnostic.
- **`providers/<name>/`** -- Provider-specific config that requires templating, generated output, instruction overlays, or provider-specific deployables not suitable for `shared/` (which must stay provider-agnostic). `providers/kiro/` holds the agent definition template, Kiro-specific steering, and Kiro-specific skills in `providers/kiro/skills/`. `providers/claude/` holds Claude-Code-specific deployables such as `statusline-command.sh` (symlinked by `setup.ps1`/`setup.sh` to `~/.claude/statusline-command.sh`, the path `settings.json`'s `statusLine.command` references) and `memory-load-hook.py`, the `SessionStart` hook that injects the memory index and the project tier (symlinked to `~/.claude/memory-load-hook.py`; on Windows setup offers its `settings.json` entry, per `providers/claude/README.md`). Extend this for other providers when needed, not speculatively.
  - `providers/kiro/skills/<name>/OVERLAY.md` — kiro-only discipline fragments appended to shared `SKILL.md` at deploy time. If a shared skill has an `OVERLAY.md` under `providers/kiro/skills/<name>/`, the deploy merges shared `SKILL.md` + overlay; the overlay-merge path takes precedence, so a co-located standalone `SKILL.md` (if any) is skipped. If only a full `SKILL.md` is present (no `OVERLAY.md`), the skill is deployed as a standalone kiro skill (existing behavior).
  - **Auxiliary-file overlays**: a skill's non-`SKILL.md` aux file can also carry a kiro overlay via the `<stem>.OVERLAY.md` convention — `providers/kiro/skills/<name>/<stem>.OVERLAY.md` is appended at deploy time to the deployed `<stem>.md` aux file (e.g. `memory-rules.OVERLAY.md` → `memory-rules.md`, `RESEARCH_CONFIG_TEMPLATE.OVERLAY.md` → `RESEARCH_CONFIG_TEMPLATE.md`). `SKILL.md` keeps the bare `OVERLAY.md` convention; `SKILL.OVERLAY.md` is forbidden.

**Authoring boundary**: shared `SKILL.md` = lean, harness-neutral content (what frontier models need). `providers/kiro/skills/<name>/OVERLAY.md` = kiro-only discipline delta (what the kiro-cli model additionally needs). `providers/kiro/steering/` = kiro environment/host rules; it now also includes `kiro-governance-discipline.md`, which carries AGENTS.md-level anti-rationalization discipline demoted from shared (kept lean for frontier harnesses, restated firmly for the weaker kiro-cli model). Overlays cite shared anchors by **section name or stable step ID, not raw step number** (desync guard — shared may be reorganized without breaking overlays).
- **`memory/`** (config repo root) -- User memory: persistent cross-project learnings. Not tracked here: it is a gitignored link, made by setup, to the store repo's reserved `user/memory/`, so memory commits land in the store repo. See `shared/AGENTS.md § Memory Management` for format and rules. This repo's own project memory, like every workspace's, lives in its store in the store repo (`~/.agent-playbook/stores`, outside this repo; `shared/skills/qdream/memory-rules.md § Workspace Store`). There is no `workspaces/` directory and no `plans/` directory: this repo's project files (plans, `ROADMAP.md`, `ROADMAP-REJECTED.md`) live in its workspace store too, like every workspace's.
- **`templates/`**, **`docs/`** and the root contributor files (`README.md`, `CONTRIBUTING.md`, `ROADMAP.md`, `CHANGELOG.md`, `SECURITY.md`, `.github/`) -- setup's starting files (empty user memory) and the public documentation. A change to setup, the layout or the contribution flow updates them in the same commit.
- **Archived project files** -- `plans/done/` in this repo's workspace store. Pruned periodically: an archive older than about three months that no live governance file, `ROADMAP-REJECTED.md` entry, memory entry or `memory/.dream-state.json` record names is deleted. The store repo's git history keeps them; recover one with `git -C <store repo> log --all --diff-filter=D -- '<store>/plans/done/<name>.md'` then `git show <sha>^:<path>`. Never prune an archive that a live file cites.

## Symlink Safety

This instructions file and each skill directory may be symlinks from provider config directories (e.g. `~/.claude/`, `~/.codex/`, `~/.gemini/`, `~/.kiro/`) to a shared config repo (`agent-playbook`). Always edit these files in place -- never delete and recreate them. If you notice a symlink has been replaced by a regular file, alert the user immediately. **Exception**: overlay-bearing Kiro skills deploy as generated `shared + overlay` copies on every platform, because the merge overwrites one file inside the skill directory. Edit the shared `SKILL.md` and the overlay fragment in the config repo source, never the generated copy under `~/.kiro/skills/`; re-run setup to rebuild it. (Kiro on Windows deployed everything as copies until 2026-09-20; the IDE symlink limitation behind that no longer reproduces — see `providers/kiro/steering/kiro-guidelines.md`.)

## Doc & Test Guidelines

See `shared/AGENTS.md § Doc & Test Guidelines` — this repo holds that canonical text, so a local copy would only drift. Doc/test compliance is **in** scope here: follow the pointer and verify against the bullets it holds. The pointer-body form itself is defined in `shared/skills/qplan/TEMPLATES.md § Doc & Test Guidelines`.

## Terminology

Project-specific terms settled for the memory subsystem. Use them as written; the rejected synonyms below should not reappear in governance, skills or plans.

- **Session-start memory context budget** — the ratcheted word pin over always-loaded user memory (`memory/MEMORY.md` + `memory/HIGHER_ORDER.md`); the pin lives in a script and is cited by lookup, never as a number in prose. Rejected: "Size advisory", "memory tax".
- **Promotion** — moving a memory entry to a tier with more authority (user memory, or governance), removing the source, on the user's approval; named by its destination: "promotion to user memory", "promotion to governance". Building a higher-order node is induction, not promotion. "Cross-project" describes content, never a tier: name the tier ("user memory", "higher-order tier"). Rejected: "scope move".
- **Suspect memory entry** — a memory entry a deterministic check flagged for a full re-verification (cited path changed or missing, cited commit missing, expiry or version condition fired). Being a suspect is never evidence of staleness on its own.
- **Event-driven memory validity** — re-verifying a memory entry only when something it depends on changed (its own text, a cited anchor, the governance it is compared against), plus a rotating backstop. Rejected: "incremental Task 4", "classification cache".
- **Plan-less governance capture** — recording improvement signals (friction, skill ideas) and fixes to wrong memory from a session that has no project file.
- **Phase agent** — the fresh sub-agent that runs one sweep phase under the orchestrator's grant. Rejected: "phase worker", "sub-orchestrator".
- **Handoff file** — a work-folder file that carries sweep state between phases. Rejected: "checkpoint", "packet".
- **Drafter** — the read-only agent that prepares gate proposal text. Rejected: "writer", "proposer".
- **Store repo** — the private git repository at `~/.agent-playbook/stores` holding every workspace store. Rejected: "stores repo", "workspace store repo".
- **STORE file** — a store directory's identity file (`remote <host/owner/name>` plus optional `path <subpath>`, or `local <path>`); replaces the `WORKSPACE` file. Rejected: "identity file", "WORKSPACE".
- **Store resolver** — the shared Python module whose `find` and `find_or_create` map a folder to its store. Rejected: "store lookup", "resolution script".
- **Store scratch folder** — the gitignored `scratch/` in a workspace store, for temporary playbook working files that must outlive a session. Rejected: "scratch space".
- **Session scratchpad** — a harness's own per-session temporary folder, for files needed only in that session. **Work folder** stays reserved for a script-owned folder such as `dream-work`.
