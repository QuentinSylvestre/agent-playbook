## Kiro Test Discipline

Re-read `/qtest` SKILL.md in full before each mode — context pressure degrades recall of Plan mode, Run mode, artifact schemas, and the Findings report format.

### On black-box-first observation

The black-box-first principle is structurally enforced in `/qtest`'s architecture: execution agents in Run mode receive only the test plan and docs — never source access. The refuter in `full` mode is the only agent with source access, and it runs after observation is complete.

The normative ordering still matters for the orchestrator: mode detection and sub-agent brief construction must preserve the separation. Do not collapse the execution and refuter phases, and do not leak source paths into execution agent briefs. Once an execution agent has seen source, it cannot un-know it — structural naivety is the guarantee that observation is genuine.

### On the "missing / not implemented" gate

Re-read `shared/skills/qtest/run-process.md § Step 6 — Refuter pass (full only)` and `shared/skills/qqa/SKILL.md § Evidence-grade gate` before acting and apply them literally; do not skip it under time pressure.

### Citation inventory

This overlay cites shared `/qtest` SKILL.md sections by name only (never by step number — desync guard per `shared/AGENTS.md § SKILL.md Authoring`):

- Modes
- Plan mode
- Run mode
- Surface-specific guidance
- Reference blocks
- Artifacts
  - Test plan schema
  - Harness doc schema
- Findings report format
- Approaches
- This skill composes
