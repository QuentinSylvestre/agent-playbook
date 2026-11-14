---
name: qplan
description: Write a phased implementation plan, scaling the template to match complexity. Use after /qexplore — explore first unless the user states they have already explored or supplies a complete intent file. Pass an existing plan path to review it.
argument-hint: "<work description or path to existing project file>"
requires: "qreview, qvalidate"
---

# Plan

## Your role

Write, revise, or review implementation plans. The plan format must scale with the complexity of the work item. Approach this from an architect's perspective -- balance design rigor, pragmatism, and risk mitigation.

## Input

$ARGUMENTS

## Mode detection

Determine the operating mode from `$ARGUMENTS`:

- **Review mode**: `$ARGUMENTS` is a path to an existing project file that **contains planning sections** (any of: `## Implementation Phases`, `## Design Decisions`, `## Risk Assessment`, or a `### Phase` heading).
- **Create mode**: `$ARGUMENTS` is a work description, a non-existent path, `from exploration`, or a path to an existing file that contains **only** an Intent section (Status: Exploring/Draft, no planning sections) — i.e., a `/qexplore` handoff file. In this case, treat as Create mode with the project file already started.

---

## Create mode

### Step 1: Assess complexity

Based on the scope, classify it:

| Scale | Criteria | Typical effort |
|---|---|---|
| **Trivial** | Unambiguous approach, fits in working memory, no irreversible changes | < 1 hour |
| **Light** | Single component, clear scope, few files | ~1-3 hours |
| **Standard** | Multi-file, design decisions needed | ~1-3 days |
| **Major** | Multi-phase, architectural impact, cross-cutting concerns | ~1+ week |

**Trivial gate**: *Could a senior engineer confidently implement and verify this in a single focused session without a written plan?* The approach must be unambiguous, the scope small enough to hold entirely in mind, with no irreversible changes, external dependencies, migrations, manual rollout steps, or breaking changes. When in doubt, classify one tier higher.

### Step 2: Analyze the codebase and check governance

If not preceded by `/qexplore`, thoroughly read relevant code areas first. Understand existing patterns, architecture, and conventions. Cite specific files by path, anchored by a heading or unique string rather than a line number (see Live-data & prose-phase discipline below).

**Intent gate**: If NOT preceded by `/qexplore` and the project file does not yet exist, gather intent before writing the plan by asking the user targeted questions about:
- What problem this solves and what success looks like
- Concrete success criteria
- What is explicitly in and out of scope

Populate the Intent section of the project file with their answers. This is a lightweight intent capture — ask one round of questions covering the three topics above, then proceed. For deeper exploration, suggest `/qexplore` instead. This ensures every project file has an intent section regardless of whether `/qexplore` was used. **Exception**: bugfix detection's invariants follow-up is exempt from this cap; see `shared/skills/qplan/TEMPLATES.md` `## Bugfix Invariants Format` `### Detection rule`.

**Bugfix detection**: see `shared/skills/qplan/TEMPLATES.md` `## Bugfix Invariants Format` `### Detection rule`. Apply verbatim if a bug fix is suspected.

**Preserve bugfix Invariants subsection (when `/qplan` runs after `/qexplore`)**: When `/qplan` reads an existing project file written by `/qexplore` and that file's Intent section contains an `### Invariants` subsection (Standard) or `Invariants:` bullet block (Light), preserve it verbatim. **Tier downgrade caveat**: If `/qexplore` wrote the Standard `### Invariants` H3 but this `/qplan` classifies the work as Light tier, convert to the Light-tier `Invariants:` bullet block per `TEMPLATES.md` `## Bugfix Invariants Format`.

**Governance gate**: Check the project's governance files (`AGENTS.md`, `CLAUDE.md`, or equivalent). Use whichever is available -- projects may have one or both. The plan must respect any conventions, constraints, or architectural guidelines defined there. If governance defines plan or archive locations, follow it over this skill's defaults. If the plan would conflict with governance rules, flag the conflict to the user before proceeding.

**Doc & Test Guidelines bootstrap**: If the project's `AGENTS.md` is missing entirely, or lacks a `## Doc & Test Guidelines` section, propose the canonical default (from `shared/skills/qplan/TEMPLATES.md`) and ask the user to confirm — see that section for the minimal-pointer-body alternative when the project's doc/test policy already lives elsewhere (e.g. a Kiro steering file). **Resolve the pointer's location using the same store-vs-workspace determination as project files** (`shared/skills/qdream/memory-rules.md § Resolution contract`) — the pointer goes at the resolved root (the workspace's store, except in a no-create folder or the config repo), not the project repo root; do not assume the project repo root by default. A waiver (heading present with a brief decline note) is a valid answer — do not re-prompt when the heading exists. Only the user answers the `Save / Skip` proposal. If the user moves on without answering, record the section as undecided in the project file and re-ask at the next planning step; never write the section as if accepted.

**Terminology bootstrap**: When `/qexplore` recorded settled project-specific terms in Discovery item 6 (see `shared/AGENTS.md § Documentation Organization`), propose recording them via the `Save / Skip / Edit?` idiom — one or two sentences per term saying what it *is*, plus the synonyms the session rejected. Append to whichever form the project already uses: the `## Terminology` section, or the glossary file it points at. Creating a section or file where neither exists requires asking first (`shared/AGENTS.md § Documentation Organization` — do not create documentation files unprompted). Two suppressors, both silent: a heading whose body is a decline note (the waiver — do not propose, do not re-prompt), and general programming vocabulary, which never qualifies however often it appears. (A governance/doc-policy proposal — **its Skip writes no declination record**.)

**Durable update on contradictory request**: When the user makes a request during planning or implementation that contradicts the existing `## Doc & Test Guidelines` (e.g., "create the full project documentation" against a prototype-style block), apply the request for the current task **and** propose a durable AGENTS.md edit using the same `Save / Skip / Edit?` idiom. Never silent. The proposed edit must explicitly state which guideline changes and how. The user always confirms before the durable write happens — applying the requested task does not implicitly grant durable-edit consent. (This is a governance/doc-policy proposal, not a memory proposal — **its Skip writes no declination record**.)

**If preceded by `/qexplore`**: Use the exploration's output summary (the 9-item Intent/Discovery contract) as the foundation for the plan:

INTENT items (preserved in the project file's Intent section):
- **Problem statement & desired outcomes** (item 1) → Intent section (already written to file by `/qexplore`, or populate from the exploration summary if `/qexplore` skipped file creation)
- **Success criteria** (item 2) → Intent section (same). When the work answers a defect the user perceives or replaces an existing surface, apply `memory/topics/ui-replacement-and-user-perceived-defects.md` in the config repo; the same holds for criteria gathered by the Intent gate above
- **Scope boundaries & non-goals** (item 3) → Intent section (same)

DISCOVERY items (inform planning sections):
- **Existing patterns & constraints** (item 4) → guide implementation approach with file:line references
- **Risks & mitigations** (item 5) → Risk Assessment table
- **Resolved decisions** (item 6) → Design Decisions table
- **Open items** (item 7) → resolve before finalizing the plan, classifying each. **Deterministic items** (answerable by reading code or running a test — a factual matter) may be resolved with planner judgment and recorded in the Design Decisions table without re-prompting. **Decision items** (a product or technical judgment with ≥2 value-based options) MUST be surfaced to the user and resolved interactively — route via the **Council-Enriched Escalation** rule in `shared/AGENTS.md`; never silently resolve a decision-type item. A decision-type open item arriving here usually signals it should have been resolved during `/qexplore`, or that it is contingent on partial execution; either way it is the user's call, not the planner's. `/qexplore` contract item 7 labels its hand-off items **deterministic** or **execution-contingent** (undecidable until partial implementation), not decision-type: treat an **execution-contingent** item as one that cannot be settled at planning time. Do not resolve it with planner judgment. Surface it to the user, record it in the Risk Assessment table or the plan's open questions with the phase or probe that will settle it, and do not move it to Design Decisions until that phase has run. An item the plan chooses to postpone because it is out of scope is a different thing: it is deferred follow-up work and goes to `## Follow-up Work (Deferred)` (`shared/skills/qplan/TEMPLATES.md`), never to Design Decisions. Only a deterministic item, one whose answer a code read or a test run gives now, is recorded in Design Decisions on planner judgment. When the project file contains an `## Open Design Items` section (written by `/qexplore`), resolve each item per this classification and relocate the resulting decisions into the plan's Design Decisions table — do not leave the section dangling as an unresolved artifact. **Assumptions (unconfirmed)** entries (the labelled adjunct written by `/qexplore` below high depth) are routed through the same path as decision-type Open items — surfaced to the user, and where a trade-off is involved, via the **Council-Enriched Escalation** rule in `shared/AGENTS.md`. On confirmation fold the entry into the Design Decisions table; on veto re-open it as a question. Never silently accept an unconfirmed assumption into the plan. **Re-verify before escalating**: before routing an Assumptions (unconfirmed) entry or a seemingly-deterministic Open item to the user, re-check it against the codebase directly — `/qexplore`'s Step 1.5 trio may have settled it during codebase analysis without the entry being updated, or it may prove false on inspection. Escalate only the residue verification cannot resolve, and flag explicitly any entry that verification contradicts rather than passing it through unchanged.
- **Recommended approach** (item 8) → guides phasing strategy
- **QA environment** (item 9) → the Verification section (how to start and reach each runtime surface) and the QA annotation in Step 3; the plan must carry it, because `/qplan` removes the `## Exploration Discovery` section

**Resolved-decision consistency**: The plan (Design Decisions table, Success Criteria, phase descriptions — all plan content) must not contradict Resolved Decisions from `/qexplore` without explicit user approval. If the planner disagrees with a resolved decision (e.g., believes it creates a reliability or safety risk), it must surface the disagreement to the user and get approval before overriding. This includes safety or reliability additions that the user explicitly rejected during exploration. Silent overrides — where the plan quietly reverses a decision without flagging the contradiction — are a harness violation.

**Source-severity cross-check**: When Intent inherits a **severity** or **confidence** label from a cited source artifact (a `/qexplore` finding, a `/qtest` or test-drive report, an issue, a prior plan), do NOT propagate the label verbatim. Re-read the cited source and verify the claim it actually supports before writing it into Intent — an upstream "Medium / plausible / unverified" finding must not silently become a "verified High" in the plan. If the source's evidence is weaker than the label implies, downgrade the wording and record the uncertainty explicitly (e.g., "unverified — to be confirmed in Phase N"). Mis-inherited severity inflates scope and mis-prioritizes phases.

**Sequel-chain check**: When the new plan refines, fixes or extends a feature that earlier plans shipped, find those earlier plans in the project's `plans/` and `plans/done/` folders (grep the feature's name, paths and skill names). Order them by the `Date` header in each project file, never by archive filename: the filename prefix can invert the true order. In the new plan's Intent section, list the chain oldest first, one line per plan with its filename and Date. Add one sentence naming what the earlier plans missed (the scoping miss), quoting the earlier plan's own acceptance finding or review rating when it has one. Plans with no earlier plan of the same feature skip this check. A chain you cannot confirm from the plans' own text is recorded as unconfirmed; do not infer it from filename proximity alone.

### Step 3: Write the plan

**Trivial tier**: Write the plan inline in the conversation (no file):

1. **Goal**: One sentence describing what changes and why
2. **Files to modify**: Table of files and planned changes
3. **Approach**: Numbered steps (3-7 steps typical)
4. **Verification**: How to confirm it works
5. **Documentation updates**: Which project docs need updating, or "None"

Ask the user to confirm, then skip the review step (Step 4). Suggest `/qdev` when ready.

**Light / Standard / Major tiers**: Write a project file.

**If a project file already exists** (written by `/qexplore`):

1. Read the existing file — it will contain an Intent section.
2. Preserve the Intent section as-is. Append the planning sections below the `---` separator after the Intent section.
3. Update the status from "Exploring" to "Draft".

Default to the project-governed plan location. If governance is silent, resolve the project-file root through `shared/skills/qdream/memory-rules.md § Resolution contract`, artifact class *project files*; archived project files go to `<resolved-root>/done/` via `/qclose`. The contract returns the `plans/` of the workspace's store, created by the first write without a prompt (step 2); the workspace's own `plans/` only in a no-create folder (step 3) -- do not ask, proceed with that default.

**Filename convention**: Use `{YYMMDD}_{UPPER_CASE_SELF_SUFFICIENT_PROJECT_NAME}.md`. If a project file already exists (written by `/qexplore`), use it as-is — do not rename. One exception: when its basename does not match `^[0-9]{6}_[A-Z0-9_]+\.md$` (the `filename-grammar` that `/qvalidate` enforces), for example because it carries the archived `YYMMDD-HHMM_` time-suffix prefix, rename it before planning: drop the `-HHMM` so the name reads `YYMMDD_<SAME_UPPER_CASE_NAME>.md`, move it in place (`git mv` when tracked), and tell the user the old and new names. Do not rename a file that already matches. The name must be self-sufficient — someone browsing the directory should understand the project from the filename alone. For example:
- `260402_ACME_GATEWAY_CONTROLLER_UDP_INTEGRATION.md` (good -- describes project, feature, and mechanism)
- `260402_GATEWAY_CONTROLLER.md` (too vague -- what about it?)
- `260402_ADD_MERAKI_SENSOR_CONNECT_MQTT_PARSER.md` (good -- action, vendor, transport, component)

Note: archived plans use a related but distinct convention with a time suffix — see `/qclose`'s Step 4 for the authoritative spec. Active plans use `YYMMDD_UPPER_CASE_NAME.md` (no time suffix).

Read `TEMPLATES.md` (co-located with this skill file) and use the appropriate template based on the complexity tier from Step 1. **If `TEMPLATES.md` cannot be found, STOP and ask the user for help locating it. Do NOT approximate the plan format from memory -- the templates contain required sections that must be used exactly.**

If the change affects persisted data layout, backfills or scrubs existing data, cloud infrastructure, IAM, CI/CD, or any operator-run rollout/cutover, the plan must include explicit tracked phases for that operational work. Do not leave migrations, environment cutovers, rollback-window cleanup, or manual verification only in narrative notes. Capture them as concrete phases with owners, per-environment order, exit criteria, and rollback/verification steps.

**Live-data & prose-phase discipline** (all tiers): when a phase edits a **live data file** (a git-tracked file the plan changes in place — `memory/*.md`, config, fixtures) or ships **agent-facing prose** (a `SKILL.md`/`AGENTS.md` rule, a prompt, or governance text an agent executes), author it under these rules:
- **Anchor live-data edit targets by heading or unique string, never by line number** — plan-body line numbers are stale by the time `/qdev` runs the phase. **The rule covers reference citations as well as edit targets**: a line number cited only to point the reader at evidence rots exactly the same way, and a stale one sends the implementer to the wrong place. Where a line number genuinely helps, write it beside a `section heading` or a unique string that survives the drift. This applies to any note a plan will be built from, not only the plan body — a roadmap seed note citing a manifest or table row cites it by content (e.g. the row's kind + destination), never by row or line number.
- **Confirm a claimed live-data defect with a byte-level check before authoring a repair phase** — an observation that a file needs fixing (mojibake, wrong encoding, a stray byte) is a read-time impression until an `od` / `grep -c` / hash / command-output check confirms it; do not write a phase that modifies live data on the impression alone.
- **Give every prose-deliverable phase at least one meaning-testing exit criterion** — a cold-read acceptance test (a fresh agent given the edited text plus a scenario, never the expected answer, must produce the correct behavior), not only mechanical guards (`verify-citations`, checkbox counts) that pass even when the prose means the wrong thing.
- **A rejected fix is recorded in one compact, greppable line, in the phase that would have used it** — `> **Rejected:** <approach> — <how it fails>. **Use instead:** <chosen approach>.` Keep it in the phase body, not in a central table: the reader who needs it is the implementer about to type the rejected approach, and locality is the whole value. Review cycles turn "the obvious fix is wrong" into a plan's highest-value content, and prose paragraphs bury it — one line per rejection stays scannable and survives the phase being skimmed.
- **A plan carries an artifact's contract, never its implementation** — if the artifact exists at a citable path, cite the path; if it does not yet exist, state what it must do, emit and gate on, and let the phase build it. Prose outranks any code sample on conflict; mark every sample as a delta or a sketch, never as the deliverable. A plan that inlines an implementation is using itself as a filesystem, and the inlined copy rots the moment the phase ships the real thing. (The durability worry that motivates inlining is answered by stating the reconstruction contract, which is prose — not by embedding the artifact.)

**An exit criterion must be reachable from inside its phase** (all tiers): every criterion has to be satisfiable by the operations the phase names and by the tool surface the phase is granted. Two failures recur. **The named operation cannot produce the stated end state** — `git rm -r <dir>` leaves the now-emptied directory in the worktree on Windows and OneDrive, so a criterion reading "`git rm` + commit, including the now-empty `memory/` directory" is unsatisfiable by the command written beside it; pair every `git rm -r <dir>` with an explicit `rmdir <dir>` and a `[ -e <dir> ]` absence assertion. **The repair tool is denied to the phase** — a criterion naming `verify-deployment` inside a phase whose tool surface denies `/qconfig-sync` and `setup.ps1` can only be left unticked and explained, and the drift it reports usually belongs to an earlier phase anyway. Grant the tool, or move the criterion to the phase that owns the repair.

**A deferred decision names the property, not only the options** (all tiers): when a phase leaves a choice to the implementer, state the property the choice must preserve alongside the candidate options. A bare binary — "re-root, or hard error; decide which" — reads as an exhaustive option set when it is only the options the planner could see, so the implementer picks the least-bad listed option instead of recognising a third that is correct. Write the options as candidates and the property as the test they must pass.

**Pre-flight / spike phase for premise-dependent designs**: If the plan's design premises depend on empirical state the planner has not yet observed — e.g., "add a gate / run every suite honestly", a broad migration whose surface is unknown until enumerated, or any scope where the design is only valid if an assumed current-state holds — the plan must sequence an early **pre-flight/spike phase** that establishes that state (run the full suite once and triage failures, enumerate the change sites, reproduce the assumed behavior) BEFORE the design-dependent phases, with a gate to revise the design if the pre-flight disproves a premise. Honest-run scopes routinely invalidate their own assumptions — an inert config, hidden pre-existing failures, a latent production bug — and surface in-scope-vs-defer decisions the user must make mid-execution; sequencing the spike first lets the design adapt to reality instead of committing to premises the pre-flight would have disproven. **Quote-drift check**: when a plan migrates live records that carry verbatim quotes of governance text (e.g., `Governance-conflict-quote` values), the pre-flight must diff each quoted span against its current cited section — a recent structural wave may have drifted them, and only the diff reveals which records will re-raise vs. stay silent after migration. **Baseline shape**: when a pre-flight records a guard or drift baseline for a later phase to compare against, record **which** entries were in the reported state, never only how many. Some deployed files change on their own between runs, so a bare count (`drifted=1`) goes stale with no plan activity at all, and the later comparison cannot separate plan-caused change from runtime churn. **Sample-based premises**: when a Discovery item or a Design Decisions row rests on a sample, write the sample size into the row. When the design is a rule over a store of records (an accounting rule, a parser rule, a classification), the spike runs the rule over the whole store and counts the records that break its invariants (a one-minute script) before the rule is written into a decision row. A rule written from 759 events in 60 sessions failed a full scan of the same store at review.

**Refactor-class plans — doc-impact and pre-flight coincide**: for a plan whose scope is a citation / anchor / record-model / governance-prose refactor, the mandatory doc-impact sub-agent and the pre-flight/spike enumeration are the **same work** — the set of citing sites *is* the documentation impact. Enumerate the citing-site set once and reuse it for both; do not run a separate doc-impact sub-agent and a separate enumeration spike over the identical surface. The mandatory-disposition requirement (step 4 above: every hit addressed or marked `false-positive`) still applies to the combined enumeration.

**Label user steps by capability**: when a step needs the user, label it by the capability it needs (an interactive session, a paid call, the user's account or hardware, a decision), never by the machine the planner runs on. A plan written in a container labelled its guard runs '(user, Windows)'; `/qdev` then ran on Windows, where the agent could run most of them itself.

**Parallel annotation** (Standard/Major only): After writing all phases, analyze inter-phase dependencies:
- For each pair of phases, check whether their file scopes overlap (any file modified by both)
- For each pair, check whether one phase's output is another's input (e.g., Phase 2 creates a module that Phase 3 imports)
- Phases with no file overlap AND no input/output dependency are eligible for parallel dispatch
- **Timing-sensitive exclusion**: a phase whose exit criteria depend on wall-clock timing or throughput measurement (a benchmark, an occupancy/latency capture) should NOT be annotated into a parallel group with implementation phases sharing the same machine, even when file-scope/dependency eligibility otherwise holds — contention from concurrent dispatches can skew the measurement by an order of magnitude. Recommend running the measurement phase solo (before or after the group) instead.
- Annotate eligible phases with `[P:N]` in their headings (symmetric — both annotate each other). See `shared/skills/qplan/TEMPLATES.md § Parallel Phase Annotation` for syntax and rules
- Include file-scope lists in each parallel phase's description (after `**Goal**:`) so `/qdev` can construct cross-phase briefs

This analysis is lightweight and advisory — it SHOULD fire when the planner identifies independent phases, not as a mandatory check on every invocation.

**QA annotation** (every tier that writes phases — Light/Standard/Major — mandatory): After writing all phases, analyze each phase for runtime surfaces:
- For each phase, check whether the phase produces executable code changes (scripts, functions, endpoints, UI components, CLI tools — any non-docs/non-types artifact).
- For each phase with executable code, check whether its runtime surface is self-contained — testable in isolation without requiring outputs from later phases.
- Phases with self-contained runtime surfaces: annotate with `[QA]` in the heading (combinable with `[P:N]`).
- Phases that are docs/types-only OR whose runtime surface depends on later phases: do NOT annotate.

This analysis is mandatory — every `/qplan` invocation that writes phases must perform it. Unlike `[P:N]` (advisory), `[QA]` annotation cannot be skipped. The detection rule is: "Does this phase produce executable code whose output is testable without later phases?" If yes, annotate `[QA]`. **Tiebreaker**: when in doubt whether a surface is self-contained, annotate `[QA]` — `/qqa` SKIPs only a phase with no runtime surface (`shared/skills/qqa/SKILL.md § Process`), and Step 9 catches everything regardless. Err toward annotation.

See `TEMPLATES.md § QA Phase Annotation` for the canonical annotation grammar (regex, rules, examples). Do not duplicate the grammar here — TEMPLATES.md is the single source of truth.

**Doc-impact sub-agent** (all tiers, mandatory): After writing the plan body (phases, files-to-modify), dispatch a sub-agent to identify documentation that references anything being changed or removed. The sub-agent:

1. **Derives search terms** from the plan's changes (identifiers visible in the diff, plus semantically inferred removals) across five categories:
   - *Code identifiers*: function/class/module names changed or deleted
   - *Runtime constants*: port numbers, URLs, file paths, protocol identifiers (e.g., `ws://`, `grpc://`)
   - *Operational identifiers*: entry point commands, CLI flags, environment variables, config keys removed or renamed
   - *Architectural concepts*: mode names, component names, service names being removed or renamed
   - *Plan/phase identifiers*: when the plan shares source files with a predecessor or sibling plan (a shared branch, a follow-up ticket), grep those shared files for in-code comments naming a phase number or plan identifier (e.g. "Phase 2", a predecessor's ticket slug) that could collide with this plan's own numbering — a fresh-context implementer or reviewer reading such a comment cannot tell which plan's phase it means without a qualifier
2. **Greps** all tracked `*.md` files (excluding `plans/done/` relative to project root), plus `docs/`, `README.md`, and any other project documentation in non-markdown formats, for each derived term
3. **Reports** every hit with file:line, grouped by search term
4. **Dispositions** each hit as either: (a) added to the Documentation Updates table with a phase assignment, or (b) marked `false-positive: <reason>`. No hit is silently dropped.

Integrate findings into the plan's Documentation Updates section before proceeding. For Trivial tier, the planner may perform this grep in-session instead of dispatching a sub-agent, but the check and disposition are still mandatory.

Note: the first four search-term categories above are aligned with `/qclose` Step 2 Pass 4's signal-derivation step (the fifth, plan/phase identifiers, has no `/qclose` counterpart) — `/qplan` names the categories for the planner to interpret; `/qclose` applies pattern-based heuristics against commit diffs to detect the same classes of identifier. Both target the same gap (stale doc references to changed/removed identifiers) from different vantage points: prediction here, verification there.

**Documentation update wiring**: After writing all phases, cross-reference the Documentation Updates section (Section 8 in Standard/Major, or the "Documentation updates" section in Light). For each doc update assigned to a phase:
- **Standard/Major**: Add an explicit exit criterion (`- [ ]`) in that phase's exit criteria list. The criterion must name the specific document and the update needed (e.g., `- [ ] Update nrf_tool/README.md with --scan-driven batch usage examples`). This ensures `/qdev` enforces doc updates through the same checkbox mechanism as code changes.
- **Light**: Add an explicit verification item in the Verification section naming the specific document and the update needed (e.g., "Confirm nrf_tool/README.md updated with --scan-driven batch usage examples"). This ensures doc updates are checked alongside other verification steps.

**Doc-table ↔ file-scope cross-check** (Standard/Major): The inverse of the wiring above. After writing all phases, walk the Documentation Updates table (Section 8). For each row whose `Phase` column names a specific phase, confirm the named document also appears in that phase's `**File scope**` line. On a mismatch — a doc-table file absent from the named phase's File scope — flag the omission to the author (e.g., "Documentation Updates assigns `foo/README.md` to Phase 2, but Phase 2's File scope does not list it — add it to File scope, or mark the row `doc-table-only` if the doc lives outside any phase's edited files"). This is **advisory** — surfaced for the author's decision, not a hard gate (the sibling doc-wiring bullet is likewise advisory). A row carrying an explicit `doc-table-only` marker (see ``TEMPLATES.md § `## 8) Documentation Updates` — `doc-table-only` annotation``) suppresses the flag, for documents that are legitimately updated outside any phase's File scope.

**If the project file already exists** -- switch to the revision sub-flow:

**Re-entry classification**: Before revising the existing plan, skim its Intent section and title to determine whether the user's current request is:
- **Same task, continuing** — modify the existing plan (clean up outdated sections, incorporate new information). Preserve the Intent section.
- **Same task, expanding** — preserve existing phases and append new ones. Confirm the expanded scope with the user before writing.
- **Different task** — inform the user the planning sections will be overwritten (Intent preserved if still relevant), get confirmation, then start fresh.

If unsure, ask: "The plan at `<path>` covers `<existing scope>`. Is this a continuation, scope expansion, or a new task?"

1. **Read the existing plan** in full.
2. **Fold in a re-plan handoff section** (if present): If the plan contains a `## Resolved Decisions (re-plan handoff)` section (written by `/qexplore`'s re-plan branch), relocate each of its decisions into the plan's Design Decisions table and then **remove the section** — mirroring how `## Open Design Items` is resolved-and-relocated by Step 2's `/qexplore`-handoff rule. For a Light-tier plan with no Design Decisions table, fold the decisions into the Context / Step-by-step where the rationale belongs. Do this before the review pass below so the folded-in decisions are reviewed as part of the plan; removing the section after folding keeps the operation idempotent (a later revision pass will not re-fold).
3. **Check the Review Log section** (if present).
   - For every finding listed in the review log, verify whether the plan body already addresses it (the resolution was applied in a previous edit, or the finding is no longer relevant given the current plan content).
   - Produce a checklist summary for the user:
     ```
     Review Log -- outstanding items
     - [x] #1 <finding> -- addressed (cite where)
     - [ ] #3 <finding> -- still open
     ```
   - Apply fixes for any items that are still open. For each fix, add a brief inline comment in the plan noting which review finding it resolves (e.g., `<!-- resolves review finding #3 -->`).
4. **Run a review pass** using the evaluation criteria from Step 4 below. Perform the review yourself within this session.
5. **Apply fixes directly** for every High and Medium severity finding. For Low severity findings, fix them if the fix is unambiguous; otherwise record them as `Escalated -- left for user review`.
6. **Append a new Review Log entry** with the current date, the findings table, and a note next to each finding indicating whether it was auto-resolved:
   ```markdown
   ### YYYY-MM-DD -- Plan Revision (via /qplan)

   N findings (X High, Y Medium, Z Low). M auto-resolved.

   | # | Severity | Finding (one line) | Resolution (one line) |
   |---|---|---|---|
   | 1 | High | <one-sentence description> | Fixed -- <one-sentence fix> |
   | 2 | Low | <one-sentence description> | Escalated -- left for user review |
   ```

   Each Finding/Resolution cell is one prose sentence, ≤25 words; if longer, move detail to the prose body below the table. Quote sub-agent prose only when its wording is essential.
7. **Present the summary** to the user, then proceed to Step 4 (sub-agent review) and Step 5, where the revised project file is validated with qvalidate (`filename-grammar`, `status-grammar`, `sc-coverage`; see `shared/skills/qvalidate/SKILL.md`) before the commit — handle a FAIL per `shared/skills/qvalidate/SKILL.md § Failure semantics`.

### Step 4: Sub-agent review cycle

After writing or revising the plan, run a review cycle using **one sub-agent per review persona** (fresh context, no assumptions carried over from creation).

#### Persona selection

Persona selection follows `/qreview`'s Persona-selection rules for the `/qplan Step 4` call sites, including the Light-tier persona-count exception and its scoping. A plan already in flight keeps its original persona set.

**Gap-critic lens** (Standard/Major, Architect persona): When constructing the Architect persona's spawn brief, append this lens instruction: "In addition to evaluating structural fitness, explicitly identify missing steps, uncovered risks, unaddressed edge cases, and mitigations the plan should include but doesn't. Focus on what's absent, not just what's present."

#### Review standards

Review standards: the subset declared in `/qreview`'s Subset declaration per call site for the `/qplan Step 4` call site, defined in its Standards union.

#### Sub-agent execution

Spawn brief follows `/qreview`'s Spawn brief contract. Pass: project file path + governance files (`AGENTS.md`, `CLAUDE.md`) + standards subset + persona name(s) + focus area(s) + lens instruction.

Dispatch and findings merging follow `/qreview`'s Sub-agent execution. The Review Log entry the orchestrator writes uses `/qreview`'s Findings table format — same shape as `/qdev` Step 7 (`# | Severity | Finding (one line) | Resolution (one line)`); each cell is one prose sentence and sub-agent prose is quoted verbatim only when its wording is essential.

#### Auto-fix loop

Run `### Auto-fix loop (both modes)` (below Review mode).

### Step 5: Report

Run `### Report (both modes)` (below Review mode). **Trivial-tier addendum**: inline plans have no file, so qvalidate does not run and there is no project-file commit — present "inline plan" in place of a file path.

---

## Review mode

Activated when `$ARGUMENTS` points to an existing project file.

### Step 1: Read the plan

Read the project file thoroughly. Understand the goal, phased approach, design decisions, risk mitigations, exit criteria, and test strategy.

### Step 2: Read the relevant codebase

For every file reference in the plan:
- Verify the file exists and the line references are accurate
- Check that the current state analysis matches reality
- Verify that proposed code changes are compatible with the actual codebase

Also read files that the plan SHOULD reference but doesn't (adjacent modules, tests, configs).

### Step 3: Per-persona sub-agent review

Select relevant personas and launch per-persona sub-agents following the same process as Create mode Step 4:

1. **Persona selection**: follows `/qreview`'s Persona-selection rules for the `/qplan Step 4` call sites. Mandatory minimum (Standard/Major) is **`Architect + Senior engineer + ≥1 domain-relevant persona`**; Light-tier exception is **`Senior engineer alone`**. Add Security auditor for security-sensitive changes; add Domain expert (or a regulatory-compliance persona) when the plan implements a formal standard or compliance framework.
2. **Launch sub-agents** per `/qreview`'s Sub-agent execution (including its Mutation-testing isolation): spawn brief follows `/qreview`'s Spawn brief contract. Pass: project file path + governance file paths (`AGENTS.md`, `CLAUDE.md`) + standards subset (per `/qreview`'s Subset declaration per call site) + persona name(s) + focus area(s) + lens instruction.
3. Each sub-agent returns: findings table (severity + recommended fix), confidence score (%), blocking issues, open questions.

### Step 4: Auto-fix and iterate

Run `### Auto-fix loop (both modes)` below.

### Step 5: Report

Run `### Report (both modes)` below. **Review-mode addendum**: additionally present ready/not-ready status, remaining findings by severity and reason, and a confidence score (%).

---

## Shared subsections (Create and Review modes)

### Auto-fix loop (both modes)

1. Merge findings from all sub-agents into a single list. Deduplicate findings that overlap across personas (keep the highest severity).
2. Classify findings: auto-fixable (clear, low-risk, no business-logic change) vs blocked (requires user decision). A fix that removes or weakens anything the user approved, or settles a judgment call, is blocked even when mechanical. A fix that settles a design trade-off, or adds scope the user did not ask for, is blocked too: escalate it under the **Council-Enriched Escalation** rule, never fold it into the plan.
3. Apply auto-fixable fixes to the plan.
4. Re-run sub-agent review on the updated plan per `/qreview`'s Sub-agent fan-out rules.
5. Max 3 cycles.

**Ready state**: No unresolved High findings, no auto-fixable Medium findings remaining. Any remaining findings require user decision or manual action. Stop cycling early if ready state is reached before max cycles.

If sub-agent dispatch fails, follow `/qreview`'s Sub-agent unavailability gate (hard stop, user decision required).

### Report (both modes)

Before committing, validate the project file with qvalidate (run `shared/skills/qvalidate/scripts/qvalidate.py` with the playbook venv, per `shared/skills/qvalidate/SKILL.md` — never re-implement the checks inline): the `filename-grammar`, `status-grammar`, and `sc-coverage` checks confirm the filename and status line are well-formed and that every `SC-n` is referenced by a phase `**Covers**:` line. Handle a FAIL per `shared/skills/qvalidate/SKILL.md § Failure semantics`.

Commit the project file using Conventional Commits format `docs(<plan-slug>): <brief description>` where `<plan-slug>` is the plan filename without `.md`. See `shared/AGENTS.md § Commit Conventions` for the canonical rule. Do not push.

Present to the user:
- Project file path
- Review summary: cycles run, findings resolved, remaining findings
- Blockers requiring user action
- Suggest `/qdev <plan-path>` when the plan is ready

---

## Rules

Rules that are not stated in a step above:

- Do NOT start implementation
- **A long session: suggest `/compact` before Step 1.** On Claude Code, run `<python> <config-repo>/shared/skills/qdream/scripts/dream-manifest.py context --orchestrator` first (`<python>` and `<config-repo>`: `shared/skills/qdream/SKILL.md § Interpreter` and `shared/AGENTS.md § Config Repo Locations`; its limit, `ORCHESTRATOR_CONTEXT_LIMIT`, is half of a 1M window, so judge by half of your own window when it differs). On `over limit: yes`, suggest that the user run `/compact` before you start, because every turn re-reads the whole context. When the command cannot run (kiro, no venv), skip the check.
- **Decision-complete before commit**: the plan is finished when the implementer needs to make no decisions of its own. This is not the same as being readable — `/qdev` dispatches each phase to a fresh-context sub-agent that never saw the exploration, so every unresolved choice becomes that agent guessing. Include detail that removes a decision; omit detail that does not.
- Preserve plan intent; ask before changing business logic or scope
- Include test changes alongside code changes in each phase
- Make exit criteria concrete and verifiable. A criterion about a budget pin or ceiling (a word pin, a size cap) cites the script that reports it, never the number: another session may raise the pin mid-plan, and a quoted number goes stale.
- Include backwards compatibility analysis when modifying existing behavior, at every tier (only the Major template has a section for it)
- Commit the project file after creation or revision per `shared/AGENTS.md § Commit Conventions`. Do not push.
- Apply the **Harness Improvement Capture** rule in `shared/AGENTS.md` — append friction observations (steps that didn't fit, ambiguous gates, missing categories, awkward conventions) to the project file's `## Harness Improvement Opportunities` section as you encounter them.
- Apply the **Council-Enriched Escalation** rule in `shared/AGENTS.md` when escalating design trade-offs to the user.
