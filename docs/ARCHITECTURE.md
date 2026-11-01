# Architecture

How agent-playbook is deployed, where its state lives, and how it improves itself. For the
vocabulary, see [GLOSSARY.md](GLOSSARY.md); for the authoritative rules, follow the links into
`shared/`.

## Three places

| Place | What | Tracked by |
|---|---|---|
| The engine (this repo) | Governance (`shared/AGENTS.md`), skills, provider config, setup and guard scripts | this repo, public |
| The store repo (`~/.agent-playbook/stores`) | Your user memory (`user/memory/`), and one store per workspace: its memory, plans, artifacts | your own private git repo |
| Provider config folders (`~/.claude`, `~/.codex`, `~/.gemini`, `~/.kiro`, the Kiro IDE folder) | Links into the engine, plus files the apps own | not tracked |

The pointer file `~/.agent-playbook/config` ties them together. Setup writes it (`root=` the
engine, `stores=` the store repo, `stores_url=`, `engine_branch=`, `providers=`), and scripts read
it through the store resolver (`store-resolver.py paths`). Environment variables override it
(`shared/AGENTS.md § Config Repo Locations`).

## Deployment

`inventory.tsv` lists the top-level deployables: instruction files, hooks, agent definitions,
templates and seeds. Each row has a kind:

- `symlink-file` / `symlink-dir`: a link into the engine.
- `template-file`: rendered with `{{USER_HOME}}` / `{{PLAYBOOK_ROOT}}`.
- `seed-file`: written only when absent, because the app owns it afterwards.
- `copy-file`: copied.

Skills are dynamic. Each provider gets one link per shared skill inside its own `skills/` folder,
never a link of the whole folder, so its other skills stay. A Kiro skill with an overlay is a
generated copy: shared `SKILL.md` + `OVERLAY.md`.

Three scripts keep the deployment honest:

- `setup.sh` / `setup.ps1` are twins: they deploy the same tree on their platforms.
- `verify-deployment.py` checks a deployment against the manifest.
- `test-parity.sh` checks that the twins agree with each other and with the verifier.

`/qconfig-sync` runs all of them.

## The memory tiers

Memory sits below governance, never above it (`shared/AGENTS.md § Memory Management`):

1. **Governance**: `shared/AGENTS.md`, the skills, project `AGENTS.md` files.
2. **User memory**: `memory/MEMORY.md` (and on-demand `memory/topics/*.md`), cross-project. In the
   engine, `memory` is a gitignored link to the store repo's `user/memory/`, so the files are
   committed there.
3. **Higher-order memory**: `memory/HIGHER_ORDER.md`, abstractions the sweep induces. Read-time advisory.
4. **Project memory**: `<store>/memory/MEMORY.md` in the workspace's store.

Entries are typed (feedback, decision, pattern), carry a source and a `Verified` date, and pass
five write-time gates before they are saved
(`shared/skills/qdream/memory-rules.md § Memory File Format`).

At session start, Claude Code's `SessionStart` hook (`providers/claude/memory-load-hook.py`)
injects a heading index of the user and higher-order tiers plus the project tier. Kiro loads them
through steering resources.

## Stores and the resolver

A workspace's store is a directory `<name>-<hex>` in the store repo, identified by its `STORE`
file: the folder's normalized git remote (plus a subpath), or `local <path>`. The store resolver
(`shared/skills/qdream/scripts/store-resolver.py`) maps a folder to its store by reading `STORE`
files, never by deriving a name. The engine repo is a workspace like any other: its own plans live
in its store. The reserved `user/` directory holds user memory and is never a store.

## The self-improvement loop

1. During work, agents capture **improvement signals** (friction, missing rules) and propose memory
   entries. You approve each one.
2. `/qdream` runs the **sweep** in phases, each run by a fresh phase agent and connected by handoff
   files in a work folder:
   - Orient takes a snapshot.
   - Gather reads new sessions and plans.
   - Synthesize induces higher-order nodes.
   - Decide and Apply write memory edits and propose governance changes at a gate.
3. Guard scripts (`dream-sweep.py`, `dream-write.py`) bind every write to the snapshot, allow only
   known targets, refuse credentials, and commit by pathspec:
   - user and project memory in the store repo;
   - governance on the engine's `local-improvements` branch.
4. You push, and merge `local-improvements` to `main`, or open a pull request upstream, when you
   choose.

Memory health is measurable with `/qmemory-eval`. Entries are re-verified when something they
depend on changes ("event-driven validity"), and expire on their own dates or conditions.
