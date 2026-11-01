## Kiro /qplan Discipline

### Mandatory skill activation before review dispatch

Before constructing any review sub-agent brief (Create-mode Step 4 or Review-mode Step 3), load `/qreview`'s full SKILL.md into context. This ensures persona selection, fan-out rules, standards definitions, spawn brief contract, and findings format are in active context — not recalled from degraded memory. Do NOT skip this step regardless of tier or perceived familiarity.

Anchors: `shared/skills/qplan/SKILL.md` § Step 4: Sub-agent review cycle, § Step 3: Per-persona sub-agent review.

### Anti-shortcut framing

The shared SKILL.md is written for cross-provider portability and assumes agents follow instructions literally. On Kiro CLI, context pressure and session length create incentives to abbreviate expensive steps (sub-agent dispatch, full-file reads, governance checks). Resist these shortcuts:

- Never skip the Doc & Test bootstrap check — a missing section is not the same as a waiver.
- Never summarize governance from memory — re-read the project's `AGENTS.md` each session.
- Never collapse the review cycle to a single pass — run all personas and iterate per the auto-fix loop.
- Never declare "ready state" without verifying zero unresolved High findings and zero auto-fixable Medium findings.
