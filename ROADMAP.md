# Roadmap

Public roadmap for agent-playbook. Larger items get an issue for discussion before work starts;
comment there if one matters to you.

## Next

- **Compose with other governance.** Today setup links its instruction file in place of yours,
  backing yours up, and links skills one by one beside your own. The goal is for the playbook to be
  one layer among several:
  - your own global instructions plus the playbook's, without either replacing the other;
  - namespaced skills;
  - detection of conflicting rules between packs.
- **CI-verified Windows setup.** `setup.ps1` parity with `setup.sh` is checked on Windows runners;
  widen the matrix to Windows PowerShell 5.1.

## Later

- Plugin-style packaging for providers that support it. Out of scope for now, by decision.
- Lighter installs: deploy only the lifecycle skills, without the memory system.
