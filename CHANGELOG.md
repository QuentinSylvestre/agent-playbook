# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Store scratch folder: `store-resolver.py scratch` creates a gitignored `scratch/<name>` in the
  workspace store, or `~/.agent-playbook/scratch/<name>` for a folder with no store.
- Automatic cleanup: `/qclose` deletes a plan's scratch folder, and `/qconfig-sync` deletes
  plan-less scratch folders whose newest file is over 30 days old, without asking.
- `/qconfig-sync` warns about improvised folders directly under `~/.agent-playbook`.
- On Windows, setup at a terminal offers to add the Claude Code `settings.json` entries, and
  uninstall removes them. `/qconfig-sync` reports their state and warns when the memory hook is
  missing.
- `/qconfig-sync` and CI now run the `render.py` selftest, which the runner had left out.

### Changed

- Setup is one Python implementation, `setup/setup.py`, on every platform. `setup.sh` and
  `setup.ps1` keep their names and options; each now finds Python 3.8+ and runs it, and without
  Python it stops with what to install and how to remove a deployment by hand (README,
  Uninstall). A setup run takes about 1.5 s instead of 9 to 33 s. Setup now refuses a few
  destructive steps the shell versions took: it never replaces a `.bak` folder it made earlier, an
  existing `deploy-lock.tsv.bak` or your store `.gitignore`, never writes through a link, and a link
  it cannot make or remove ends the run with exit 1.
- `deploy_model.py` holds the deploy model setup writes from and `verify-deployment.py` checks
  against; golden files written by the old shell setup pin its merge and render bytes.
- `test-parity.sh` is gone: `setup/test_setup.py` deploys into sandbox homes and checks the same
  rules in about 10 s instead of about 7 minutes.

- A store's `artifacts/` holds only files the user asked to keep. The uncommitted warning for
  that folder now says to move the file to `scratch/` or ask the user.
- Kiro generated copies no longer include `fixtures/` folders (selftest data), which cuts a
  Kiro setup run and `/qconfig-sync`'s parity check by about half. The first setup run after
  the update removes the fixture files an older setup wrote, on one summary line, and moves an
  edited one to `.bak`. `verify-deployment` reports any fixture file left in a copy as
  `ORPHAN … not-deployed=fixtures`.
- `/qdream`'s sweep Report shows the share of weighted tokens its phase agents spent, recorded
  as `phase_weighted_tokens` in the state file's cost record.

### Fixed

- A store repo created by setup now ignores `scratch/`, and no longer reserves `visualizations/`.

## [0.1.0] - 2026-11-01

First public release.

### Added

- Cross-provider governance (`shared/AGENTS.md`) and skill library for Claude Code, Codex, Gemini
  CLI and Kiro.
- Interactive, non-destructive setup:
  - `setup.sh` / `setup.ps1` detect providers and check prerequisites.
  - `--providers`, `--dry-run`, `--yes` and `--uninstall` options.
  - Store repo bootstrap.
  - One link per skill.
- Pointer file `~/.agent-playbook/config`: no location is hardcoded.
- User memory and plans live in your private store repo, never in the engine.
- The engine branch `local-improvements` for your clone's own improvements.
- README, CONTRIBUTING (DCO), architecture and glossary docs, CI on Windows and Linux.
