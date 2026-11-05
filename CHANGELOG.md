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

### Changed

- A store's `artifacts/` holds only files the user asked to keep. The uncommitted warning for
  that folder now says to move the file to `scratch/` or ask the user.

### Fixed

- A store repo created by setup now ignores `visualizations/` as well as `scratch/`.

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
