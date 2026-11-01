---
name: qcouncil
description: Multi-perspective decision support. Stakes-tiered advocate/prosecutor/juror panel for hard option choices — a Light tier runs advocate-then-juror, and a Full tier (high-stakes) runs advocate-then-prosecutor-then-juror plus assumption challenger and sensitivity analysis — with optional generative brainstorming when options aren't yet defined. Includes epistemic quality mechanisms (assumption challenger, conditional-vote detection, sensitivity analysis). Called automatically on trade-off escalations in /qexplore, /qexplore-other, /qdev, and /qplan; user-invokable standalone.
argument-hint: "<question with options OR problem statement>"
---

# Council

## Your role

Run a decision-support panel for a hard option choice. **Evaluative mode** (options provided): run the stakes-tiered pipeline — Light tier is advocate→juror; Full tier (high-stakes) adds prosecutor, assumption challenger, and sensitivity analysis (see § Stakes tier). **Generative mode** (no options): brainstorm solutions first, then evaluate. Before advocate dispatch, § Assumption challenger verifies differentiating claims. Phase 1 dispatches one advocate per option (strict advocacy). Prosecutor phase dispatches one prosecutor per option to rebut. Phase 2 dispatches N juror sub-agents (one per persona) that read all briefs and vote independently. After tallying, § Sensitivity analysis checks conditional premises when triggered. Tally juror votes only, surface per-juror reasoning verbatim, present to user for final decision. This skill is the single source of truth for council behavior; callers (`/qexplore`, `/qexplore-other`, `/qdev`, `/qplan`) invoke it per `shared/AGENTS.md § Council-Enriched Escalation`.

> **Citation convention**: Citations name sections, never numbers: `shared/AGENTS.md § SKILL.md Authoring`.
>
> **Verbatim-brief substitution convention**: verbatim sub-agent briefs use `{token}` curly-brace markers for runtime substitution. Never forward unfilled tokens to a sub-agent.

## Input

`$ARGUMENTS` carries the council payload. Library mode: structured payload (question + option list + pros/cons table + context). Standalone mode: free-form text (first line = question; subsequent lines = options). See § Mode detection.

## Mode detection

Two orthogonal discriminations:

**Library vs standalone**:
- **Library mode**: `$ARGUMENTS` parses as structured payload with question + pros/cons table + discussion context all present. Callers: `/qexplore`, `/qexplore-other`, `/qdev`, `/qplan` per `shared/AGENTS.md § Council-Enriched Escalation`.
- **Standalone mode**: `$ARGUMENTS` is free-form. See § Standalone mode for parsing rules.

If ambiguous, prefer library mode when pros/cons table and context block are both present; otherwise standalone.

**Generative vs evaluative**:
- **Evaluative**: input contains ≥2 options. Proceed to § Advocate dispatch.
- **Generative**: input contains <2 options. Proceed to § Brainstormer dispatch.

The generative/evaluative discrimination applies identically in both modes. Evaluative mode produces identical behavior to the pre-generative skill.

## Library mode contract

When called as a library for trade-off enrichment (callers: `/qexplore`, `/qexplore-other`, `/qdev`, `/qplan`):

**Evaluative mode inputs** (caller MUST pass): the question (one line), option list (≥2), pros/cons table, full discussion context.

**Generative mode inputs** (caller MUST pass): problem statement, full discussion context. **Optional**: round count override (integer, default 3), seed direction (string hint for first round).

**Returns (evaluative — success)**: markdown with:
- Per-juror reasoning verbatim, one subsection per juror named by persona.
- 2-column tally table (`| Option | Votes |`).
- One-line tie note (only when tie exists), per § Tally.
- Optional `### Sensitivity note` (only when triggered — see § Sensitivity analysis).
- **No overall recommendation** (exception: pre-escalation mode per Rules § Context-dependent recommendation rule).

**Returns (generative — success)**: same evaluative output shape, preceded by a mid-flow user interaction after § Consolidation step where consolidated options are presented for confirmation before advocate/prosecutor/juror phases run.

**Returns (refusal — too many options per § Sizing)**: structured refusal `{error: "too_many_options", count: N, max: 8}`. Council does not run.

**Expected response size**: per-juror reasoning bounded by juror brief ("3-7 sentences"). 3-juror panel ≈ 21 sentences + table. 5-juror panel ≈ 35 sentences + table. Generative mode adds brainstormer + consolidation overhead. Sensitivity adds 1-3 sentences when triggered. Prosecutor output is internal (consumed by jurors, not returned).

**`/qcouncil` does NOT own**: the trigger (stays in caller), pros/cons table production (stays in caller for evaluative; orchestrator constructs for generative), user opt-in prompt (oscillation mode only — stays in caller), final-decision arbitration (defers to user).

## Standalone mode

`/qcouncil` is also user-invokable: `/qcouncil <free-form text>`.

**Context auto-detection** (fires when `$ARGUMENTS` is empty or has no bulleted options):

1. Scan conversation for a decision point with ≥2 identifiable options.
2. If found: present extracted question + options for confirmation. On confirm → evaluative mode. On reject → fall through.
3. If 1 option found: ask for alternative or offer brainstorm.
4. If none found: fall through to input parsing below.

Confirmation is mandatory before running the pipeline.

**Input parsing** (fallback):
- Empty `$ARGUMENTS` with no auto-detection: prompt for question.
- First line starting with `-` or numeric prefix: malformed — prompt for question first.
- First non-blank line = question/problem statement.
- Subsequent bulleted/numbered lines = options.
- <2 options → generative mode. ≥2 options → evaluative mode.
- >8 options: ask user to consolidate per § Sizing.
- Without caller pros/cons table, orchestrator constructs one inline before advocate dispatch.

**Standalone generative interaction**: after each brainstorm round, present solutions. User says "explore more" (optionally with direction) for another round, or "proceed" for consolidation. After consolidation, user confirms before advocacy begins.

## Persona selection

Single source of truth for persona selection (both modes). Juror persona library: `shared/skills/qreview/SKILL.md § Personas table` (8 personas). Selection mirrors `shared/skills/qreview/SKILL.md § Persona-selection rules` (context-driven, `Senior engineer` as fallback).

Selection by context:
- **Code-flow** (from `/qexplore`, or standalone code question): 3 context-relevant personas. `Senior engineer` always included.
- **Non-code** (from `/qexplore-other`, or standalone non-code question): default subset = {Senior engineer, End-user advocate, Architect, Domain expert}; pick 3 of 4 (all 4 for high-stakes). Code-leaning personas remain selectable when relevant.
- **Ambiguous**: default to Senior engineer + Maintainability reviewer + Architect. May substitute domain-specific persona later.

Orchestrator may scale to 4-5 jurors per § Sizing high-stakes criteria.

## Sizing

- **Advocates**: one per option, capped at 8. Library mode >8 options → structured refusal. Standalone >8 → ask user to consolidate.
- **Prosecutors**: one per option, capped at 8 (symmetric). Dispatched after all advocates return.
- **Brainstormers**: fixed 3 per round. Each proposes 1-3 solutions.
- **Jurors**: 3 default. Scale to 4-5 for **high-stakes** decisions per these criteria:
  - **Irreversible at tier** — cannot be cheaply walked back (public API shape, data-schema choice, wire-format pick).
  - **Large blast radius** — affects ≥3 files or multiple downstream consumers.
  - **Persistent persona disagreement** — ≥2 personas materially diverge after Phase 1.
- These same criteria also drive the § Stakes tier (Light vs Full pipeline).
- Final juror count: orchestrator's call within {3, 4, 5}.
- **Consolidated output cap**: after § Consolidation step, distinct option list MUST contain ≤8 options.

## Stakes tier

The council runs in one of two tiers based on the high-stakes criteria in § Sizing:

| Tier | Condition | Pipeline |
|---|---|---|
| **Light** | No high-stakes criterion met | Advocate → Juror (skip prosecutor, assumption challenger, sensitivity analysis) |
| **Full** | Any high-stakes criterion met | Assumption challenger → Advocate → Prosecutor → Juror → Sensitivity analysis |

The orchestrator evaluates stakes before dispatch. The **Irreversible** and **Large blast radius** criteria are knowable pre-dispatch; **Persistent persona disagreement** only surfaces after Phase 1, so a Light run that develops material juror divergence is promoted to Full mid-flow — run the skipped assumption challenger, prosecutor, and sensitivity phases before the juror verdict. When uncertain, default to Full.

Default per plan tier: `shared/AGENTS.md § Workflow` (One effort vocabulary).

## Brainstormer dispatch

**Generative mode only.** Spawn 3 brainstormers in parallel. Each receives: problem statement, discussion context, optional constraint lens (orchestrator picks lenses at judgment — may leave some unconstrained for diversity).

**Brainstormer brief (verbatim)**:

> You are a solution brainstormer. Problem: {problem_statement}. Context: {discussion_context}. {constraint_lens_instruction} Propose 1-3 distinct solutions to this problem. For each solution, provide: a short name, a 2-3 sentence description, and the key trade-off. Do not evaluate or rank — just generate diverse options.

Where `{constraint_lens_instruction}` is either `Constraint lens: {lens_description}. Let this lens guide (but not limit) your thinking.` or empty when unconstrained.

Wait for ALL brainstormers. Any failure → § Sub-agent unavailability gate.

## Gap critic

**Generative mode only.** After each brainstorm round, dispatch one gap-critic sub-agent. Receives: problem statement, discussion context, all solutions so far, round number and max.

**Gap critic brief (verbatim)**:

> You are a gap critic. Problem: {problem_statement}. Below are all solutions proposed so far: {all_solutions_summary}. Identify unexplored areas of the solution space — approaches, paradigms, or trade-off combinations that no brainstormer has covered. If you identify meaningful gaps, describe 1-2 suggested directions for the next brainstorm round. If the solution space is adequately covered, respond with exactly: "NO_GAPS_IDENTIFIED". Do not propose full solutions — only identify directions.

**Loop logic**: `NO_GAPS_IDENTIFIED` → stop, proceed to § Consolidation step. Gaps found AND round < max → another round (gaps become seed lenses). Round = max → stop regardless. Failure → § Sub-agent unavailability gate.

## Consolidation step

**Generative mode only.** Orchestrator-driven (no sub-agent):

1. **Merge near-duplicates** into single representative options.
2. **Produce distinct option list** (≤8 per § Sizing).
3. **Construct pros/cons table**.
4. **Present to user**: user may confirm, object, add, or remove options.

After confirmation → § Advocate dispatch. Pipeline runs identically to evaluative mode from there.

## Assumption challenger

**Runs**: before § Advocate dispatch (after mode detection in evaluative; after § Consolidation in generative). **Skipped in Light tier** per § Stakes tier.

Dispatch one sub-agent. Receives: question, option list, pros/cons table, discussion context.

**Challenger brief (verbatim)**:

> You are an assumption challenger. Below is the context for an upcoming decision panel. Your job: identify claims that DIFFERENTIATE between the options (i.e., if the claim were false, it would change which option is preferred). For each such claim, classify it as:
> - `[verified]` — confirmed by code reading, user statement, data evidence, or physical law
> - `[unverified]` — inferred, speculated, or assumed without direct evidence
>
> Question: {question}
> Options: {option_list}
> Pros/cons: {pros_cons_table}
> Context: {discussion_context}
>
> Return ONLY claims that differentiate between options. For each: state the claim, its classification, and which option(s) it favors. If all differentiating claims are verified, respond with exactly: "ALL_VERIFIED".

**Flow after return**:
- `ALL_VERIFIED` → proceed to § Advocate dispatch.
- Unverified claims → present to user: "These differentiating claims are unverified. Confirm, correct, or remove before proceeding?" Apply corrections, then proceed.
- Unparseable output → § Sub-agent unavailability gate.
- **Pre-escalation mode** (`/qdev`, `/qplan`): unverified claims included in council return alongside tally (no mid-flow block). Sensitivity note surfaces them post-hoc.
- Failure to return → § Sub-agent unavailability gate.

## Advocate dispatch

Spawn one sub-agent per option in parallel. Each receives: question, assigned option (non-negotiable), full option list, pros/cons table, discussion context.

**Advocate brief (verbatim)**:

> You are assigned option X. Build the strongest case for option X. Surface its real strengths, address its weaknesses directly, and explain why it serves the project given the constraints. Do not recommend a different option.

Wait for ALL advocates. Any failure → § Sub-agent unavailability gate.

## Prosecutor dispatch

**Skipped in Light tier** per § Stakes tier.

Spawn one sub-agent per option in parallel, **after** all advocates return. Each receives: question, assigned option (to argue against), full option list, pros/cons table, advocate brief for their assigned option, discussion context.

**Prosecutor brief (verbatim)**:

> You are assigned to argue against option {option_name}. Read the advocate's case for option {option_name} below. The advocate has already acknowledged some weaknesses and argued they are manageable. Your job is to: (1) identify weaknesses the advocate failed to mention entirely, (2) challenge the advocate's mitigation arguments for acknowledged weaknesses — are they realistic? understated? incomplete?, (3) find logical gaps and unsubstantiated claims in the advocate's positive case. Do not repeat weaknesses the advocate conceded without attempting to mitigate — focus on claims where the advocate actively argues a weakness is manageable or irrelevant. Structure your rebuttal as numbered points. For each point: name the weakness category, quote or paraphrase the advocate's claim, and explain why it fails or is insufficient. Do not recommend an alternative option.

Wait for ALL prosecutors. Any failure → § Sub-agent unavailability gate.

## Juror dispatch

Select N personas per § Persona selection and § Sizing. Spawn one sub-agent per persona in parallel. Each receives: question, option list, pros/cons table, interleaved advocate and prosecutor briefs per option (Light tier: advocate briefs only), discussion context, persona name + focus area.

**Juror brief (verbatim)**:

> You are {persona_name}. Your focus area is {focus_area}. For each option below, read the advocate's case and the prosecutor's rebuttal. First, assess each option independently — state what it does well and what it does poorly under your persona's lens. Then, recommend exactly one option and explain why in 3-7 sentences. Do not hedge or qualify your recommendation after stating it — your vote is final. If your recommendation depends on a factual premise that you cannot verify from the evidence provided, state: "CONDITIONAL on: [premise]" before your recommendation.

Wait for ALL jurors. Any failure → § Sub-agent unavailability gate.

## Tally

- Count **juror votes only**. Advocates and prosecutors do not vote.
- Surface each juror's reasoning **verbatim**, one subsection per juror named by persona (e.g., `### Senior engineer`).
- 2-column tally table (`| Option | Votes |`).
- **On split**: identify the axis of disagreement — what criterion or assumption separates the majority from the minority. Surface this in the summary (e.g., "dissent is on operational complexity, not correctness").
- **On tie**: surface tied options explicitly; add `Tie — defer to user`; no tiebreaker.
- **No orchestrator recommendation** (see Rules § Context-dependent recommendation rule for pre-escalation exception).

## Sensitivity analysis

**Skipped in Light tier** per § Stakes tier.

**Trigger**: at least one juror `CONDITIONAL on:` statement, OR winning margin = 1, OR § Assumption challenger identified unverified claims. Trigger uses exact prefix match `CONDITIONAL on:` (case-sensitive).

**Process**: orchestrator reviews juror reasoning, identifies load-bearing premises for winning option, checks each against challenger output / user confirmation / code evidence.

**Output** (appended when triggered):

```
### Sensitivity note

The winning option depends on: [premise]. This premise was [verified by challenger / confirmed by user / unverified — flagged for user awareness].
```

Not triggered → no output.

## Sub-agent unavailability gate

References `shared/skills/qreview/SKILL.md § Sub-agent unavailability gate` for Retry / Skip / Abort options.

**Partial failure = full dispatch failure.** One missing advocate/prosecutor/juror/brainstormer = full phase failure (asymmetric information distorts output).

**Diagnostic content (mandatory)**: before presenting Retry/Skip/Abort, include (a) failed sub-agent's role (for advocates/prosecutors: the assigned option; for jurors: the persona; for brainstormers: the constraint lens or "unconstrained") and (b) harness error message verbatim.

The orchestrator MUST NOT proceed with incomplete returns or substitute its own reasoning.

## Rules

- Do NOT speak for the user. The tally surfaces reasoning; user decides.
- Do NOT add orchestrator recommendation outside tally — **except** in pre-escalation mode (§ Context-dependent recommendation rule below).
- **Context-dependent recommendation rule**: pre-escalation mode (`/qdev`, `/qplan`) — orchestrator MAY add recommendation per `shared/skills/qcouncil/SKILL.md § Council-Enriched Escalation (canonical body)` → Presentation format. Oscillation mode (`/qexplore`, `/qexplore-other`) — no recommendation (orchestrator already demonstrated uncertainty).
- Do NOT modify code. `/qcouncil` is advisory; output is verbal markdown. No project file, no commits.
- `/qcouncil` is **git-context-agnostic** — produces no commits, assumes nothing about working tree or branch.
- All cross-file references use repo-relative paths per `shared/AGENTS.md § SKILL.md Authoring`.
- **Announce tier**: At the start of every council run, state which stakes tier (Light or Full) is being used and why. Example: "Running Full council (irreversible architectural decision)."

## Versioning

Caller-coupled sections (breaking to rename or reshape): `§ Library mode contract`, `§ Sizing`, `§ Sub-agent unavailability gate`, `§ Brainstormer dispatch`, `§ Gap critic`, `§ Consolidation step`, `§ Assumption challenger`, `§ Sensitivity analysis`, `§ Persona selection`, `§ Stakes tier`. To find callers: grep `` `/qcouncil` `` across `shared/skills/`. Non-breaking: `§ Prosecutor dispatch` (internal pipeline phase, output not surfaced to callers).

## Council-Enriched Escalation (canonical body)

Full detail for `shared/AGENTS.md § Council-Enriched Escalation`, which keeps the operative rule and eligibility test resident and points here for the procedure. Callers arriving from a lifecycle skill's `## Rules` bullet should read this section.

### Trigger conditions

The rule fires when ALL of:
1. The agent is about to escalate a question to the user, AND
2. The question is **council-eligible** (see Discrimination rule below).

Three named triggers (non-exhaustive — the discrimination rule is the authority, not this list):
- **Recommendation oscillation** — the agent changes its recommendation on the same question more than once. Detection logic lives in `shared/skills/qexplore/shared.md § Recommendation oscillation gate`.
- **Multiple valid approaches** — the agent identifies >=2 concrete options with comparable trade-offs and cannot confidently recommend one.
- **Uncertainty at escalation** — the agent hits a blocker in `/qdev` or `/qplan` where the blocker is a design trade-off rather than a factual/permission gate.

### Discrimination rule

**Council-eligible**: The escalation involves >=2 concrete options where each has identifiable pros and cons, and the choice depends on priorities or values rather than facts.

**Not council-eligible** (escalate directly without council):
- Yes/no factual confirmations ("is this dependency deployed?")
- Permission gates ("may I modify business logic?")
- Requests for missing information the agent cannot infer ("what's the target latency?")
- Blockers requiring external action ("deploy the IAM role before I continue")

When borderline, bias toward running council (low cost of an unnecessary run vs. high cost of a raw question that could have been enriched).

**A user's explicit /qcouncil invocation is binding.** The discrimination rule gates agent-initiated escalation enrichment only; when the user names /qcouncil (even hedged — "qcouncil maybe?"), run it. Do not pre-state your own recommendation before a user-requested council — the orchestrator's view is confined to the presentation stage its mode permits.

### Opt-in parameter

| Context | Opt-in behavior |
|---|---|
| Engaged conversation (oscillation in `/qexplore`/`/qexplore-other`) | Explicit user opt-in before dispatch (the user is already in dialog) |
| Pre-escalation (`/qdev`, `/qplan` — agent hasn't surfaced the question yet) | Silent — council runs as part of the agent's reasoning before presenting to the user |

### Dispatch

Invoke `/qcouncil` in library mode per `shared/skills/qcouncil/SKILL.md § Library mode contract`. Pass: the question, the option list (>=2), a pros/cons table (constructed by the agent), and the full discussion context.

### Presentation format

After council returns, present to the user in this order:
1. **Summary** — one paragraph synthesizing the council's lean (e.g., "Council favors Option B (2-1), primarily on maintainability grounds").
2. **Agent recommendation** (pre-escalation mode only) — the agent's own recommendation informed by the council output, prefixed with "**Recommendation:**" on its own line. Omitted in oscillation mode per `/qcouncil`'s no-orchestrator-recommendation rule for that context.
3. **Full council output** — per-juror reasoning verbatim (one subsection per persona) + tally table, as returned by `/qcouncil`. (This shape holds in both stakes tiers — composition per `§ Stakes tier`.)
4. **Decision prompt** — ask the user to decide.

The summary must lead with and faithfully represent the juror tally direction, regardless of the orchestrator's prior lean. The orchestrator's own view is confined to the "Agent recommendation" line (where permitted), never the summary framing.

The agent does NOT auto-decide based on council output. Final decision is always the user's.
