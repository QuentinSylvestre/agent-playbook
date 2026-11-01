## Kiro discipline — qauto-research implementation detail

The shared SKILL.md states the lean instructions and the load-bearing guarantees; this overlay carries the concrete OS-primitive recipes, the labeled retry ladder, and the literal output formats that a weaker model needs spelled out. Section names below refer to anchors in the shared `shared/skills/qauto-research/SKILL.md`.

### Re-baseline atomic re-write recipe (§ Setup re-runnability → Re-baseline decision rule → Case A)

When Case A's atomic re-write executes, follow these steps precisely (this is the concrete realization of the shared "Atomicity guarantee"):

1. Write the new id=0 entry to `research-log.jsonl.tmp` **in the same directory as the target file** (so the rename stays on the same filesystem). Open with truncate-on-open semantics (Python `open(path, 'w')` or POSIX `O_WRONLY | O_CREAT | O_TRUNC`). A pre-existing temp file from a prior crashed attempt is harmlessly overwritten.
2. `fsync()` the temp file (or platform equivalent) to ensure on-disk durability before the rename commits — otherwise a power-loss between rename and durable write can leave a zero-byte file. **If fsync fails**: abort setup with the error. The temp file is harmless to leave on disk; the original `research-log.jsonl` is untouched.
3. Optional but recommended: after fsyncing the temp file, also fsync the parent directory file descriptor (`fsync(parent_dir)`) so the rename binding survives a power loss on some filesystems (notably ext4 with `data=ordered`).
4. **Atomically replace** `research-log.jsonl` using the platform's atomic-replace primitive: Python `os.replace`, Windows `MoveFileEx(MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH)`, or POSIX `rename(2)` on the same filesystem. Never delete-then-rename.
5. Re-commit the refreshed log. **If `git commit` fails after the atomic-replace succeeded**, abort with: `Baseline log overwritten on disk but commit failed: <git stderr>. The working tree is on the new baseline; commit manually with: git add research-log.jsonl && git commit -m 'docs(research): re-baseline experiment #0'`. Do NOT auto-rollback the file.

### Crash-handler retry ladder (Run mode § Step 4: Handle crashes)

The shared rule allows up to 3 retries, each a meaningfully different fix. Use this ladder:

- Retry 1: fix the most likely cause of the failure
- Retry 2: try an alternative approach to the same hypothesis
- Retry 3: simplify the change to its minimal form

### Literal progress formats (§ Step 9: Run baseline evaluation)

- Per pre_command, on completion: `pre_command 1/3 complete: make build`
- At evaluation start: `Running evaluation.command (timeout: <N>s)…`

### Hook installation on kiro-cli (§ Step 10: Create hook)

The shared SKILL.md table says Kiro hooks live in `~/.kiro/agents/<agent-name>.json`. That is the **v2** path. On kiro-cli, use the **v3 standalone file** instead — KAS loads `<workspace>/.kiro/hooks/*.json` at every `session/new`, so the hook is workspace-scoped and survives agent-definition updates without touching the global agent JSON.

**kiro-cli hook file** (place at `<workspace>/.kiro/hooks/qauto-research.json`):

```json
{
  "version": "v1",
  "hooks": [
    {
      "name": "qauto-research auto-continue",
      "trigger": "Stop",
      "action": {
        "type": "command",
        "command": "powershell -NoProfile -Command \"if (Test-Path research.md) { $branch = git branch --show-current 2>$null; if ($branch -match '^research/') { Write-Output 'AUTO-RESEARCH ACTIVE: Read research.md and the last 10 entries of research-log.jsonl, check stop conditions (max iterations, max time, objective thresholds, plateau, consecutive crashes), and if not met, continue with /qauto-research run. If stop conditions are met, remove .kiro/hooks/qauto-research.json and report final results.' } }\""
      }
    }
  ]
}
```

On Linux/macOS replace the `command` value with the bash equivalent:

```bash
bash -c 'if [ -f research.md ]; then branch=$(git branch --show-current 2>/dev/null); if [[ "$branch" == research/* ]]; then echo "AUTO-RESEARCH ACTIVE: Read research.md and the last 10 entries of research-log.jsonl, check stop conditions (max iterations, max time, objective thresholds, plateau, consecutive crashes), and if not met, continue with /qauto-research run. If stop conditions are met, remove .kiro/hooks/qauto-research.json and report final results."; fi; fi'
```

**Trigger name**: `Stop` (PascalCase) is the canonical form. The v2 alias `stop` also works via `TRIGGER_ALIAS_TABLE`, but always write `Stop` in new files.

**Hook disabling** (when stop conditions are met): delete `<workspace>/.kiro/hooks/qauto-research.json`. The hook file is workspace-local, so deletion is safe and scoped to this research run.

**Hook detection** (Step 1 and Step 5 of Setup § Setup re-runnability): check for `<workspace>/.kiro/hooks/qauto-research.json` existence. The v2 check against `~/.kiro/agents/<name>.json` is not applicable on kiro-cli v3.

**Hook recovery paths**: if installation failed, re-create the file at `<workspace>/.kiro/hooks/qauto-research.json` with the JSON above. Creating a directory with `New-Item -ItemType Directory -Force .kiro/hooks` first if absent.
