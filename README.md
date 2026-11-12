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

Setup records every file it writes in `~/.agent-playbook/deploy-lock.tsv`, so a re-run changes
only what changed.

Your own global instruction file stays where it is, and the playbook loads beside it:

- Claude Code: a `~/.claude/CLAUDE.md` of yours is kept, and the playbook is linked as
  `~/.claude/rules/agent-playbook.md`. Claude Code loads every file in that folder.
- Gemini CLI: a `~/.gemini/GEMINI.md` of yours is kept. The playbook is linked as
  `~/.gemini/AGENT-PLAYBOOK.md`, and that name is added to `context.fileName` in
  `~/.gemini/settings.json`. This relies on a reading of Gemini CLI 0.28.2's source, not a runtime
  check. A `settings.json` setup cannot parse is left alone, and your file is backed up instead.
- Codex cannot load a second global file, so a `~/.codex/AGENTS.md` of yours is backed up and
  replaced, and setup says so.

Uninstall removes only the links and the setting entry setup added. For Claude Code, setup also links
`~/.claude/rules/playbook-user-memory.md` and `~/.claude/rules/playbook-higher-order.md` to your user
memory, so every session starts with both tiers in full (`providers/claude/README.md`).

Any other file of yours where the playbook puts a link is backed up to `<file>.bak` before it
is replaced: an interactive run asks first, while `--yes` and a run with no terminal back up without
asking. A file setup wrote and you then edited is backed up the same way, without asking. Setup keeps
one `.bak` per path, so a later backup replaces an earlier one. A skill folder of yours with a
playbook skill's name is never replaced.

Non-interactive: `./setup.sh --yes --providers claude,codex`. Remove everything again with
`./setup.sh --uninstall` (add `--purge` to drop the pointer file too). See `./setup.sh --help`.

Then, in any project, ask your agent to `/qexplore` a change.

## The skills

| Area | Skills |
|---|---|
| Lifecycle | `/qexplore` (requirements by interview), `/qplan` (phased plan), `/qdev` (execute phases with review), `/qreview` (persona review of a diff or plan), `/qvalidate` (plan-file grammar), `/qclose` (archive and capture learnings), `/qhandoff` (hand work to another session) |
| Thinking tools | `/qcouncil` (advocate/prosecutor/juror panel for hard choices), `/qexplore-other` (stress-test a non-code decision), `/qprototype` (throwaway prototype to answer a design question), `/qwait-what` (re-pitch the last message) |
| Verification | `/qqa` (verify a specific claim, PASS/FAIL/BLOCKED/SKIP), `/qtest` (test planning and runs), `/qbrowser-test` (drive a browser with Playwright) |
| Memory | `/qdream` (the consolidation sweep), `/qmemory-eval` (memory health metrics), `/qextract` (mine an article or repo for playbook improvements) |
| Delegation | `/qclaude-delegate`, `/qkiro-delegate` (hand a well-specified task to another agent and verify it), `/qauto-research` (autonomous experiment loop) |
| Output | `/qexplain` (HTML walkthrough of a diff), `/qvisualize` (interactive charts and diagrams), `/qdocument-interaction` (Word, PDF, PowerPoint, Excel), `/qicon-design` |
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
  in the same folder stay. Composing the playbook with your own global instructions is on the
  [roadmap](ROADMAP.md).

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
