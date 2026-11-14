# Roadmap

Public roadmap for agent-playbook. Larger items get an issue for discussion before work starts;
comment there if one matters to you.

## Next

- **Compose with other governance.** Setup keeps your own global instructions beside the
  playbook's for Claude Code and Gemini CLI (Codex, which cannot load a second file, falls back to a
  backup), and links skills one by one beside your own. The goal is for the playbook to be one layer
  among several:
  - namespaced skills;
  - detection of conflicting rules between packs.
- **Plugin-style packaging for providers that support it.** Where a client has its own plugin
  mechanism, package the playbook for it. Claude Code namespaces plugin skills, so the playbook can
  then sit beside another catalog (a team's or a company's) without name collisions.
- **CI-verified Windows setup.** Setup runs on Windows runners through `setup.ps1` under pwsh 7;
  widen the matrix to Windows PowerShell 5.1.

## Later

- Lighter installs: deploy only the lifecycle skills, without the memory system.
