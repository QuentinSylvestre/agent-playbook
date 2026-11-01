# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

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
- README, CONTRIBUTING (DCO), architecture and glossary docs, CI on Linux, macOS and Windows.
