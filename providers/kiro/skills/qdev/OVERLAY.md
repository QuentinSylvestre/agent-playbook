## Kiro /qdev Discipline

Kiro agents exhibit shortcut-seeking behavior under context pressure. These guardrails reinforce critical operational steps that the shared `/qdev` process defines but that Kiro agents are empirically prone to skip or approximate.

### qvalidate FAIL handling

The shared `/qdev` process (and `/qclose`, `/qplan`, `/qreview`) invoke the `qvalidate` script at their checkpoints. A qvalidate `FAIL` is a hard halt: present the violation line verbatim and let the user decide. Do NOT interpret around it, work around it, edit the project file to make the check pass, or re-run the check with modified arguments to coax a different result. The rule is owned by `shared/skills/qvalidate/SKILL.md § Failure semantics`; this overlay restates the stop-behavior firmly for the weaker kiro model, which is empirically prone to rationalize past a failing gate.

The ONE exception (do not generalize it): a `commit-pairing` FAIL at `/qdev` Step 1/4 means a prior session committed a phase's code but was interrupted before writing the paired plan commit. There the sanctioned response is the documented Step 4/7 reconciliation — adopt the dangling commit, apply the skipped plan updates, emit the paired `docs` commit — which completes the interrupted work, not a work-around. This exception is spelled out in the § Failure semantics atomicity carve-out and applies ONLY to `commit-pairing` at Step 1/4; every other FAIL (and any ambiguity about whether the reconciliation can proceed) is the hard halt above.

### Unconditional /qreview activation

Before constructing any review sub-agent brief (Step 5 per-phase or Step 9 final), activate the `/qreview` skill by loading its full SKILL.md into context. This ensures the orchestrator has `/qreview`'s complete rules — persona selection, fan-out rule, standards definitions, spawn brief contract, findings format — in active context when writing the brief. Do NOT rely on memory of previously-read `/qreview` content; context pressure degrades recall. This activation is non-negotiable regardless of tier or phase count. Even if `/qreview` was activated earlier in the session, re-activate it before Step 9; context may have been compacted since the per-phase reviews.

### Anti-shortcut framing

The shared `/qdev` process trusts agents to follow steps faithfully. Kiro agents under context pressure tend to:
- Skip re-reading governance files they believe they "already know"
- Rationalize skipping review dispatch ("the change is small enough to self-review")

Treat every step in the shared process as mandatory unless it explicitly defines a skip condition. "I already have this in context" is not a valid skip rationale — verify by re-reading.

### No fabricated user-attribution — ever

A Resolution cell may read `User: accepted` ONLY when a specific user turn in this session said so; cite that turn in the cell as you write it: the user's words in quotes, or the date with `user turn`. The `qvalidate` check `acceptance-evidence` FAILs a `User: accepted` table cell with no quote, no `YYYY-MM-DD` date and no reference (`user turn`, `user answer`, `user decision`, `same (user) turn`, `decision <id>`); `Follow-up <n>` alone is not one, nor is `pending user decision`. Wherever you mention or quote the label (a Finding cell, prose), write it in backticks, since plain text there is a hit; never backtick it in a cell that records an acceptance, whether a Resolution or a decisions-table cell. Adding a marker to an existing row the user did not give is fabrication too. A stage-deferred closure reads `User: accepted — stage-deferred: <stage> ("<the user's words>", <YYYY-MM-DD>) — <reason>`. If the user has not spoken, write `Orchestrator: proposed-accept — pending user decision` and surface the finding at the next gate. Writing `User: ...` for a decision the user never made is fabricating an approval record; no finding severity, tier, or session momentum changes this. Rewriting an existing honest resolution (`Escalated`, `Orchestrator: proposed-accept`; legacy values like `Noted` in old files are equally protected) into a user-attributed one is the same violation.

**Provenance note**: The `Orchestrator: proposed-accept — pending user decision` literal restates the shared closed-set literal in `/qdev`'s `Resolution column values` block. The overlay reinforces the discipline; the shared skill owns the canonical definition.

### Review dispatch through run_workflow

Step 5 and Step 9 reviews follow the kiro qreview overlay's "Workflow-dispatched reviews"; a failed or silent reviewer halts auto-continue.
### Harness Improvement line on a failed or recovered dispatch

When a sub-agent or workflow dispatch fails, times out, stays silent, or is recovered by a retry or a manual fallback, write its `## Harness Improvement Opportunities` line to the project file at once, in the same step as the recovery, before the next dispatch or gate. Use the shared format: `- <observation> — cost: <what the friction actually cost> — suggested change: <one-line>`. An announced capture ("noting this as a harness improvement") counts only when the line has landed in the project file; re-read the section to confirm. If the announcement and the write are not in the same step, write the line first. The capture rule is owned by `shared/AGENTS.md § Harness Improvement Capture`; this overlay restates it for dispatch failures because the weaker kiro model announces a capture and then loses it under context pressure.

