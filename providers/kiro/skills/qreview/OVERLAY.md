## Kiro Review Discipline

Before constructing any review sub-agent brief, re-read `/qreview` SKILL.md in full, and `full-effort.md` beside it at Full effort — context pressure degrades recall. This ensures the Spawn brief contract, Persona-selection rules, and Sub-agent fan-out rules are in active context at dispatch time.

Do not abbreviate, shallow-review, or reduce scope regardless of change size or time pressure. Every review runs the full process with all applicable personas at full depth per the Effort tiers and Standards union sections. Step 5 per-phase reviews on Major-tier plans continue to auto-escalate to `effort: full` for Kiro sessions regardless of the shared `/qdev` SKILL.md default — this is a deliberate Kiro-specific delta (2026-08-10), not an oversight.

_This overlay cites shared `/qreview` SKILL.md sections by name (Spawn brief contract, Persona-selection rules, Sub-agent fan-out rules, Effort tiers, Standards union, Verdict rubrics), per `shared/AGENTS.md § SKILL.md Authoring` — never by section or step number (desync guard)._

### Verdict rubrics discipline

Re-read `shared/skills/qreview/SKILL.md § Scoring discipline` and `shared/skills/qreview/SKILL.md § Health derivation` before acting and apply them literally; do not skip it under time pressure.

### Workflow-dispatched reviews

When a review runs through `run_workflow` instead of the `subagent` tool, the generated workflow must encode the full contract: one reviewer per selected persona carrying the spawn brief, the cycle cap, and the verifier step. A single-agent recipe is not a review. A workflow-creator failure, or a reviewer that errors or returns nothing, is a failed sub-agent: stop and present Retry / Skip / Abort naming the persona and the coverage lost. Never classify, auto-fix or auto-continue on the surviving personas, and never take a failed response's prose as a verdict.
