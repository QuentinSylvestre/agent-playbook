---
name: data-dir-large-file-edits
description: Check file size before Edit/Write under data/ — large single-line files must go through Bash instead, or the transcript diff breaks --resume
metadata:
  type: feedback
---

Before using Edit or Write on any file under `data/` in this project, check its size first (e.g. `ls -la` or `wc -c`). If it is large (multi-MB+) or single-line (a minified JSON blob), use Bash instead (`cp` to replace wholesale, `jq` to modify JSON in place, heredoc/redirection for a full rewrite) — never Edit/Write directly.

**Why:** During PSS-4089 Phase 8 soak-test setup (2026-08-12), `data/app.json` held the full production config (~37.5MB, single-line JSON, copied in for live debug-session validation). Overwriting it with the Write tool to build a small test-lab config generated a ~40MB diff stored in the conversation transcript, which broke `--resume`. The user repaired it manually. Root cause: Edit/Write appear to snapshot/diff the full before/after file content for the transcript — harmless for small files, but catastrophic for a large file with no line-based structure to shrink the diff.

**How to apply:** `data/app.json` (and likely other `data/` files) can hold either a large real production dump or a small hand-built test config depending on what was last placed there — the same path swings between the two within a single session (as it did here: 37.5MB → 349 bytes → back to a different small config). Always check current size before editing; never assume based on what it held earlier in the session.
