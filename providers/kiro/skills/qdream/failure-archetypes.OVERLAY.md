---

## Authoring & parser detail (kiro)

To add an archetype: copy an existing entry's structure under `## Archetypes`. Required fields: `### name` (underscore_separated_lowercase, no colons) + **Description** + **Session signals**. Append new entries at the end of the Archetypes section.

**Prefix-matching mechanics** (supplements `§ Output Routing`): match prefixes with exact start-of-field comparison — `observation.startsWith("CANDIDATE_ARCHETYPE:")` checked BEFORE `observation.startsWith("ARCHETYPE:")` so the longer prefix wins and the shorter never shadows it (substring collision). Skip prefix matching when `observation` is empty or absent.

## Example remediations (kiro reference)

Suggested remediation directions per archetype, for when a match promotes to a governance proposal. Treat as starting points, not mandates — prefer the lightest change that closes the gap; do not add scaffolding a frontier model already handles.

| Archetype | Example remediation |
|---|---|
| skill_not_fully_loaded | Strengthen mandatory skill-activation pattern or add mechanical loading. |
| step_skipped_with_rationalization | Remove autonomous skip gates; add no-self-sufficiency-bypass rules. |
| sub_agent_bypass | Add retry protocols; no-self-sufficiency-bypass rules. |
| repeated_same_question_corrections | Restated-context trigger; propose memory/governance entry. |
| fast_exit_exploitation | Remove autonomous skip gates; convert to user-confirmation gates. |
| intent_drift | Improve `/qexplore` probing depth; add intent-verification gates. |
| governance_rule_ignored | Strengthen rule wording; add enforcement mechanisms; consider mechanical loading. |
| over_scoped_change | Tighten scope confirmation before implementing; strengthen the Proportionality/Leanness standard at review. |
| delivered_broken_code | Strengthen the verification gate (`/qqa`, `/qtest`); require the change be exercised, not just inspected. |
| misread_request | Improve `/qexplore` intent capture; add a restate-the-ask confirmation before implementing. |

**Two axes, not one.** The first seven archetypes are **process** violations — the agent broke a rule or skipped a step. The last three are **outcome-quality** failures — the process may have been followed perfectly and the *artifact* is still over-scoped, broken, or aimed at the wrong target. Do not force an outcome failure into a process archetype; if the diff is wrong but no step was skipped, it is one of the last three.
