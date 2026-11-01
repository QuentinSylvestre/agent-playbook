# Claude Code reference material

On-demand reference material for Claude Code. Nothing here is in `inventory.tsv`, so nothing here
is ever deployed into a session — a Kiro session reads it only when a task needs it. Indexed from
`memory/topics/kiro-cli.md § Reference documents`, which names the condition to read it under.

Files:

- `claude-code-local-data.md` — Claude Code's own session store, hook behaviour, status state
  machine and the kiro-cli comparison table; read for a `/qdream` sweep or a recovery task that
  needs Claude Code's own session data.
