# agent-playbook

Cross-provider, self-improving governance for AI coding agents.

One set of agent instructions and one skill library, deployed to **Claude Code, Codex, Gemini CLI
and Kiro** (CLI and IDE). The skills give agents a deliberate lifecycle for every change, and a
memory system that learns from past sessions turns what went wrong into better rules.

- **One source of truth.** `shared/AGENTS.md` and `shared/skills/` are linked into each provider's
  config folder, so one edit reaches every agent. Provider-specific pieces live in `providers/`.
- **A lifecycle, not a prompt.** `/qexplore` → `/qplan` → `/qdev` (with `/qreview` after every
  phase) → `/qclose`. Each step has written exit criteria, review personas and guard scripts.
- **Memory that maintains itself.** Agents record what they learn as memory entries. The `/qdream`
  sweep reads past sessions, consolidates and re-verifies those entries, and proposes governance
  changes for you to approve.
- **Checked by scripts, not by trust.** Deployment, citations, memory format and plan files are
  verified by stdlib-only Python guards with their own self-tests.

> Status: 0.1, the first public release. The playbook has run one person's daily work for months;
> as a public project it is new. Expect rough edges, and see [ROADMAP.md](ROADMAP.md).

## Quickstart

Requirements: git, Python 3.8+, and permission to create symlinks (on Windows, Developer Mode
or an elevated shell). Node is optional.

```bash
git clone https://github.com/QuentinSylvestre/agent-playbook.git ~/src/agent-playbook
cd ~/src/agent-playbook
./setup.sh --dry-run      # see every change first; nothing is written
./setup.sh                # interactive: pick providers, set up your store repo
```

On Windows, clone with long paths on, or checkout fails with "Filename too long" (some test
fixture paths pass 260 characters): `git config --global core.longpaths true` before cloning, or
`git clone -c core.longpaths=true ...`. Then, in PowerShell: `.\setup.ps1 -DryRun`, then `.\setup.ps1`.

Interactive setup:

1. Detects which providers you have and asks which ones to deploy to.
2. Checks prerequisites.
3. Creates the playbook's Python venv.
4. Offers to clone your store repo or create a new one (see below).
5. Writes `~/.agent-playbook/config`.

Setup records every file it writes in `~/.agent-playbook/deploy-lock.tsv` (except the Kiro seed
files, which it writes only when absent), so a re-run changes only what changed.

Your own global instruction file stays where it is, and the playbook loads beside it. A file of
yours is a regular file, or a link to a file outside this repo (from your dotfiles, say):

- Claude Code: a `~/.claude/CLAUDE.md` of yours is kept, and the playbook is linked as
  `~/.claude/rules/agent-playbook.md`. Claude Code loads every file in that folder.
- Gemini CLI: a `~/.gemini/GEMINI.md` of yours is always kept, never backed up or replaced. The
  playbook is linked as `~/.gemini/AGENT-PLAYBOOK.md`, and that name is added to
  `context.fileName` in `~/.gemini/settings.json`, in every mode (`--yes` and a run with no
  terminal included). A `settings.json` that is a link is written through the link. This relies on
  a reading of Gemini CLI 0.28.2's source, not a runtime check. Setup leaves a `settings.json` it
  cannot edit as it is, such as one with comments, which Gemini CLI accepts. It then prints a
  `NOTE` with the line to add by hand, and `/qconfig-sync` reports that line `MISSING` until you do.
- Codex cannot load a second global file, so a `~/.codex/AGENTS.md` of yours is backed up and
  replaced, and setup says so.

Once your file is gone, the next run links the instruction file and removes the side link and the
`context.fileName` entry it added, so the playbook never loads twice. Uninstall removes only the
links and the setting entry setup added, the `settings.json` setup created when it is then empty,
and `~/.claude/rules/` when nothing else is left in it. For Claude Code, setup also links
`~/.claude/rules/playbook-user-memory.md` and `~/.claude/rules/playbook-higher-order.md` to your user
memory, so every session starts with both tiers in full (`providers/claude/README.md`).

Any other file of yours where the playbook puts a link is backed up to `<file>.bak` before it
is replaced: an interactive run asks first, while `--yes` and a run with no terminal back up without
asking. A file setup wrote and you then edited is backed up the same way, without asking. Setup keeps
one `.bak` per path, so a later backup replaces an earlier one. A `.bak` that setup did not make
is never replaced: setup leaves it and the file beside it alone, and says so. When a backup cannot
be made (another program holds the file open), setup leaves that path as it is, prints an `ERROR`,
and ends with a non-zero exit code; close the program and run setup again. A skill folder of yours
with a playbook skill's name is never replaced; rename or remove it to get the playbook's skill.

Non-interactive: `./setup.sh --yes --providers claude,codex`. Remove everything again with
`./setup.sh --uninstall` (add `--purge` to drop the pointer file too). See `./setup.sh --help`.

Then, in any project, ask your agent to `/qexplore` a change.

### Install with your agent

An agent can run setup for you. Ask it to run `./setup.sh --dry-run --providers <list>` (or
`.\setup.ps1 -DryRun -Providers <list>`) and show you the plan, then the same command without the
dry-run flag. Run with no terminal, setup never asks: it backs up a file of yours at a link path
without asking, and it never changes `~/.claude/settings.json`. Run setup yourself at a terminal
once to add the Claude Code hook and status line entries there. Then ask the agent to run
`/qconfig-sync`, which verifies the deployment.

### When something looks wrong

`/qconfig-sync` runs the checks below. To run one by hand, use the playbook's venv Python
(`.venv-agent-playbook/Scripts/python.exe` on Windows, `.venv-agent-playbook/bin/python` elsewhere)
from the repo root.

| Symptom | Check | Action |
|---|---|---|
| A skill is missing in one client | `shared/skills/qconfig-sync/scripts/verify-deployment.py` | `MISSING` or `WRONG_TARGET`: re-run setup. `DRIFTED` on a Kiro copy: re-run setup after a source edit. |
| A skill is deployed but the client does not offer it | `shared/skills/qconfig-sync/scripts/verify-client-load.py` | `INACTIVE`: re-run setup, check the client's skill folder holds the skill, then the client's own disabled list. |
| A file of yours changed after setup | `<file>.bak` beside it | Setup moved your version there. Copy back what you need. |
| `ORPHAN ... foreign` | verify-deployment | A file setup did not write. Delete it yourself if you no longer need it. |
| Claude sessions start without memory | `providers/claude/settings-entries.py check` | Run setup at a terminal and accept the memory hook entry. |

**Client load check.** `verify-deployment` proves a skill file is where setup put it.
`verify-client-load.py` asks each client whether it lists the skill, with a read-only command that
spends no model call. It reports `LOADED`, `INACTIVE`, `UNOBSERVABLE` or `SKIP <reason>`, and it only
warns. A ledger in the script records, per client, the command used and the version and date it was
measured on:

| Client | Listing command | Measured on |
|---|---|---|
| Gemini CLI | `gemini skills list` (also starts your configured MCP servers) | 0.28.2, 2026-11-12 |
| Codex | `codex debug prompt-input` | 0.162.0, 2026-11-12 |
| Claude Code | none without a model call, so `UNOBSERVABLE` | 2.1.322, 2026-11-11 |
| kiro-cli | none without a model call, so `UNOBSERVABLE` | 3.0.0, 2026-11-11 |

When the installed version differs from the ledger's, the line says so and the check still tries.

## The skills

| Area | Skills |
|---|---|
| Lifecycle | `/qexplore` (requirements by interview), `/qplan` (phased plan), `/qdev` (execute phases with review), `/qreview` (persona review of a diff or plan), `/qvalidate` (plan-file grammar), `/qclose` (archive and capture learnings), `/qhandoff` (hand work to another session) |
| Thinking tools | `/qcouncil` (advocate/prosecutor/juror panel for hard choices), `/qexplore-other` (stress-test a non-code decision), `/qprototype` (throwaway prototype to answer a design question), `/qwait-what` (re-pitch the last message) |
| Verification | `/qqa` (verify a specific claim, PASS/FAIL/BLOCKED/SKIP), `/qtest` (test planning and runs), `/qbrowser-test` (drive a browser with Playwright) |
| Memory | `/qdream` (the consolidation sweep), `/qmemory-eval` (memory health metrics), `/qextract` (mine an article or repo for playbook improvements) |
| Delegation | `/qclaude-delegate`, `/qkiro-delegate` (hand a well-specified task to another agent and verify it), `/qauto-research` (autonomous experiment loop) |
| Output | `/qexplain` (HTML review brief of a diff: brief, optional walkthrough, D2 maps with tours, file summary, diff review), `/qvisualize` (interactive charts and diagrams), `/qdocument-interaction` (Word, PDF, PowerPoint, Excel), `/qicon-design` |
| Maintenance | `/qconfig-sync` (pull, verify the deployment, push), `/qmigrate-workspace` (move a workspace folder, Windows), `/qutilities-disk-cleanup` |

Kiro also gets `/qwire-governance`, `/qrecover-file`, `/qfewer-permission-prompts` and `/qslidedeck` (self-contained HTML slide decks with scripted layout checks).

## How it fits together

```
agent-playbook/ (this repo, public)         ~/.agent-playbook/
  shared/AGENTS.md  ──linked──► ~/.claude/CLAUDE.md, ~/.codex/AGENTS.md, ~/.gemini/GEMINI.md, ~/.kiro/...
  shared/skills/*   ──linked──► ~/.claude/skills/<skill>, ~/.codex/skills/<skill>, ...
  providers/<name>/ ──linked or rendered──► provider-specific config
  memory ───────────linked──► stores/user/memory/        stores/   (your private store repo)
                                                           user/memory/       your user memory
                                                           <workspace>-<id>/  per-project memory, plans,
                                                                              gitignored scratch/
                                                         config    (pointer file: root=, stores=)
```

- **Store repo.** Your memory, plans and artifacts never live in this repo. They live in a private
  git repo of your own at `~/.agent-playbook/stores`: one store per workspace, plus `user/` for
  your cross-project memory. Setup can create it locally; push it to a private remote to keep it
  across machines.
- **Engine branch.** Your clone's own improvements (from `/qconfig-sync` and `/qdream`) land on a
  `local-improvements` branch, never on `main`. Merge to `main`, or open a pull request upstream,
  when you choose.
- **Coexistence.** Each skill is linked individually, so your own skills and other skill packs
  in the same folder stay. Your own global instruction file stays too (see Quickstart).

More: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and the vocabulary in
[docs/GLOSSARY.md](docs/GLOSSARY.md).

## Supported providers

| Provider | Instructions | Skills | Extras |
|---|---|---|---|
| Claude Code | `~/.claude/CLAUDE.md` | `~/.claude/skills/` | statusline, sounds, SessionStart memory hook (setup offers the `settings.json` entries: [providers/claude/README.md](providers/claude/README.md)) |
| Codex | `~/.codex/AGENTS.md` | `~/.codex/skills/` | |
| Gemini CLI | `~/.gemini/GEMINI.md` | `~/.gemini/skills/` | |
| Kiro (CLI and IDE) | steering in `~/.kiro/steering/` | `~/.kiro/skills/` (with Kiro overlays) | `kiro_default` agent, settings seeds ([providers/kiro/README.md](providers/kiro/README.md)) |

Windows is the main platform and Linux is supported. The scripts and their selftests run on both in CI, but a full `/qdream` sweep has been exercised on Windows only. macOS is untested: `setup.sh` should work there, but expect rough edges. Kiro and Windows get the most day-to-day use.

## Contributing

Contributions are welcome: see [CONTRIBUTING.md](CONTRIBUTING.md). Every change goes through a
pull request with sign-off (DCO) and green CI. Security issues: [SECURITY.md](SECURITY.md).

## License

[Apache License 2.0](LICENSE). See [NOTICE](NOTICE).
