# Plan Templates

Templates used by the `/qplan` skill. Select based on the complexity tier:

- **Light**: Single component, clear scope, few files (~1-3 hours)
- **Standard**: Multi-file, design decisions needed (~1-3 days)
- **Major**: Multi-phase, architectural impact, cross-cutting concerns (~1+ week)

## Contents

- [Light Plan Template](#light-plan-template)
- [Standard Plan Template](#standard-plan-template)
- [Major Plan Template](#major-plan-template)
- [Status Grammar](#status-grammar)
- [Success-Criteria IDs and Coverage](#success-criteria-ids-and-coverage-optional)
- [Parallel Phase Annotation](#parallel-phase-annotation)
- [QA Phase Annotation](#qa-phase-annotation)
- [Bugfix Invariants Format](#bugfix-invariants-format)
- [Doc & Test Guidelines](#doc--test-guidelines)

---

## Light Plan Template

```markdown
# <Title>

> **Date**: YYYY-MM-DD
> **Status**: Draft  <!-- Status grammar: shared/skills/qplan/TEMPLATES.md § Status Grammar -->
> **Last Updated**: <set by /qclose at archival>
> **Scope**: <one-line scope>
> **Memory relied on**: none

---

## Intent
<3-5 lines: problem being solved, desired outcome, what's out of scope. For bug fixes, add an `Invariants:` labelled bullet block under `## Intent` — see `## Bugfix Invariants Format` below.>

## Context
<Brief description and motivation>

## Files to modify

| File | Change |
|---|---|

## External Dependencies
<List any infrastructure, CI/CD, IAM, cloud resources, or third-party service changes required, with cost impact if any. "None" if this is a code-only change.>

## Rollout / Migration / Cleanup
<If the change affects persisted data, infra, or any manual operator workflow, list the required migration or cutover steps, validation, rollback expectation, and post-rollback cleanup. Otherwise write "None".>

## Step-by-step

### 1. <Step>
<Details with code snippets where helpful>

## Verification
<Commands to run and manual checks>

## Documentation updates
<List project docs to review and update, or "None" if no doc changes needed.>
```

---

## Standard Plan Template

```markdown
# <Title>

> **Date**: YYYY-MM-DD
> **Status**: Draft  <!-- Status grammar: shared/skills/qplan/TEMPLATES.md § Status Grammar -->
> **Last Updated**: <set by /qclose at archival>
> **Scope**: <one-line scope>
> **Memory relied on**: none
> **Estimated effort**: <range>

---

## Intent

### Problem statement & desired outcomes
<what problem this solves and what success looks like>

### Success criteria
<concrete, verifiable conditions for "done">

<For bug fixes, insert `### Invariants` here — see `## Bugfix Invariants Format`.>

### Scope boundaries & non-goals
<what is explicitly in and out of scope>

## 1) Current State
<Analysis of relevant code with file:line references. For a premise established by *running* something rather than reading it — a probe, a guard script, a live check — name the command and the date alongside the claim. A `file:line` citation is self-verifying (the next reader goes and looks); a runtime observation is not, and carries an expiry a static citation does not. The reader needs to know which premises they can confirm by reading and which they must re-run.>

## 2) Goal
<1-2 sentence solution summary: what the implementation achieves>

## 3) Design Decisions

| Decision | Choice | Alternatives considered | Rationale |
|---|---|---|---|

## 4) External Dependencies & Costs

### Required external changes

| Category | Change needed | Owner | Status |
|---|---|---|---|
| CI/CD | | | Pending |
| IAM / Permissions | | | Pending |
| Cloud resources | | | Pending |
| Data migration / backfill | | | Pending |
| Rollout / cutover | | | Pending |
| Cleanup after rollback window | | | Pending |
| Secrets / Env vars | | | Pending |
| DNS / Networking | | | Pending |
| Third-party services | | | Pending |

Remove rows that do not apply. Add custom rows as needed.

If the implementation introduces non-code runtime artifacts (data files, templates, static assets, native binaries), add a dedicated phase or exit criterion covering build/packaging pipeline updates.

If a phase relocates or moves content (a section, block, or file from one location to another), add an exit criterion that the **destination exists**, not only that the source was removed — e.g., `- [ ] new ## Foo section created and all references to it resolve`. A relocation done as deletion-only leaves dangling references that a source-side check alone will not catch.

If a phase **deletes** content outright — no destination, nothing moved — add the symmetric exit criterion: that no references survive. E.g. `- [ ] grep for "§ Foo" returns no hits outside this plan file`. A pure deletion leaves exactly the dangling citations a botched relocation does, and this repo's cross-references are prose `§` citations and backtick repo-relative paths, so no compiler, linker, or existing guard will notice them.

If any row above involves data migration, backfill, scrubbing, infra rollout, or manual operator action, represent that work as one or more dedicated implementation phases below. Do not leave it only in this section.

### Cost impact

<"None" or describe: what changes, estimated magnitude, and whether user approval is needed before proceeding. If non-trivial, the agent must obtain explicit user approval before implementation begins.>

## 5) Implementation Phases

**Vertical phasing rule**: Phases SHOULD be vertical feature slices — one
capability end-to-end per phase (e.g., data + service + API + UI for a
single feature), so each phase produces an integration-testable checkpoint.
A phase MAY be horizontal (single-layer) only when no vertical slice is
yet possible — pure infrastructure setup, dependency upgrade, or a shared
foundation that multiple later vertical slices will build on. Horizontal
phases must include a "Why horizontal" entry in the phase description
naming (a) which later vertical-slice phases depend on this foundation
and (b) why combining the foundation into the first dependent vertical
phase would block progress on the others. Generic justifications ("this
is infrastructure", "needed before features") are insufficient — `/qplan`
Step 4 reviewers should flag them as findings (Medium severity floor).

**Parallel phase annotation**: When phases have non-overlapping file scopes and no dependency ordering, annotate with `[P:N]` in the phase heading. See `## Parallel Phase Annotation` for syntax and rules.

### Phase 1: <Name>
**Goal**: <phase goal>

<Detailed changes: what each artifact must do, by contract; mark any code sample as a sketch (see SKILL.md § Live-data & prose-phase discipline)>

**Exit criteria**:
- [ ] <criterion>

### Phase 2: <Name>
...

Include explicit rollout, migration/backfill, validation, and post-rollback cleanup phases whenever the change affects existing persisted data or external operator-managed systems.

## 6) Risk Assessment

| Risk | Impact | Mitigation |
|---|---|---|

A risk whose Mitigation is anything other than "addressed within this plan" (accepted, deferred, out of scope) must also get a one-line pointer in `## Follow-up Work (Deferred)` — create the heading if absent.

## 7) Verification
<Automated commands and manual checks>

## 8) Documentation Updates

| Document | Update needed | Phase |
|---|---|---|

## Progress Tracker

| # | Phase | Status | Notes |
|---|---|---|---|
<Reserved — /qplan fills one row per implementation phase.>

Mark tasks that can run in parallel with `[P]`:
- Tasks sharing the same `[P]` marker within a phase may be executed concurrently
- Unlabeled tasks are sequential by default

## 9) Implementation Divergences from Plan
<Reserved -- filled during implementation>

## Follow-up Work (Deferred)
<Reserved -- appended during /qplan (a Risk Assessment entry whose Disposition
defers rather than fixes) and during /qdev/qreview (a review finding closed via
Override discipline that leaves a future action item) when a deferred/accepted/
out-of-scope item is worth tracking past this plan's closure.
Format: N. **<one-line title>.** <what it is, why deferred, source citation
(risk ID, review finding #, or phase)>.
Leave the heading even if empty: /qclose reads it and surfaces its contents to
the user, non-empty or not, so a plan with nothing deferred says so explicitly.>

## Review Log
<Reserved -- filled by review cycles>

## Harness Improvement Opportunities
<Reserved -- appended during /qexplore, /qplan and /qdev when harness friction is felt.
Format: - <observation> — cost: <what the friction actually cost> — suggested change: <one-line>
Leave the heading even if empty: /qclose Pass 2 and /qdream GAT-PLANS both read it, and an
absent heading is indistinguishable from a frictionless run.>
```

`/qplan` Step 4's persona review is mandatory at Standard tier, so a Standard plan always produces a Review Log entry; the section gives it a canonical home instead of a per-plan invented placement.

### `## 8) Documentation Updates` — `doc-table-only` annotation

The `Phase` column assigns each documentation update to a phase. `/qplan` Step 3's **Doc-table ↔ file-scope cross-check** confirms that any document named here also appears in that phase's `**File scope**` line, flagging omissions to the author (advisory).

Some documents are legitimately updated outside any phase's edited files — e.g. an external wiki, a doc maintained in another repo, or a file touched as a side-effect that is not in scope for code review. For those rows, append the literal marker `doc-table-only` to the `Phase` cell (e.g. `2 (doc-table-only)`, or just `doc-table-only` when no phase owns the edit). The marker suppresses the cross-check flag for that row.

| Document | Update needed | Phase |
|---|---|---|
| `nrf_tool/README.md` | Add `--scan-driven` batch usage examples | 2 |
| External onboarding wiki | Note the new CLI flag | 2 (doc-table-only) |

---

## Major Plan Template

Includes all Standard sections (with Intent section and renumbered §1-§9), plus these additional sections inserted after the Progress Tracker (inherited from Standard), after "Documentation Updates" (§8) and before "Implementation Divergences from Plan" (§9). The Standard Progress Tracker uses a simple phase table; Major extends it with the `[P]` intra-phase parallel marker (already present in the Standard template) and adds:

**Parallel phase annotation**: When phases have non-overlapping file scopes and no dependency ordering, annotate with `[P:N]` in the phase heading. See `## Parallel Phase Annotation` for syntax and rules.

```markdown
## Dependency Graph
<ASCII visualization of phase ordering>

## Backwards Compatibility

| Item | Strategy | Safety effect |
|---|---|---|

## File Change Summary

### Created
### Modified
### Deleted
### Unchanged
```

`## Review Log` is inherited from the Standard template (it sits after §9) — do not restate it here.

---

## Status Grammar

`> **Status**: <State>` or `> **Status**: <State> — <detail>` where `<State>` ∈
`Exploring | Draft | In Progress | Complete` (closed set; machine-checked by
/qvalidate's `status-grammar` check) and `<detail>` is freeform. Archived is
encoded by location (`plans/done/`), not a State. `Complete` means complete —
work with pending rollout/deploy states `In Progress — <what remains>`.
`Last Updated` (set by /qclose at archival) is a defined header field.
`Memory relied on` is an optional header field on every tier with a project file
(Major inherits it from Standard): the headings of memory entries the plan's
sessions actually applied (quoted or acted on), never everything that loaded.
Value: `none`, or headings separated by ` | ` (a heading may contain `;`). The templates preset `none`
(never a `<…>` placeholder, which the manifest would split into headings);
/qdev Step 7 replaces it, /qclose Step 3 writes `none` when the line is
absent, and /qdream's manifest reads it as the `Usage` feeder.

---

## Success-Criteria IDs and Coverage (optional)

Success criteria in the Intent MAY carry stable `SC-n` identifiers (e.g.
`- SC-1: <criterion>`), and each implementation phase MAY declare which criteria
it satisfies with a per-phase `**Covers**: SC-…` line (the bold `**Covers**`
form is canonical). This grammar is optional — there is no mandate to add IDs;
a mandate is reconsidered only after real usage.

**Validated when present**: when `SC-n` IDs appear in the Success criteria,
/qvalidate's `sc-coverage` check verifies every `SC-n` is referenced by at least
one phase `**Covers**:` line (IDs present but zero `**Covers**:` lines anywhere →
WARN adoption nudge; an `SC-n` referenced by no phase → FAIL). When no `SC-n` IDs
are present, the check does not fire.

---

## Parallel Phase Annotation

Phases that are eligible for parallel dispatch by `/qdev` are annotated with `[P:N]` in the phase heading. For groups of 3+ phases, use transitive pairwise annotations.

Example (2 phases):
```
### Phase 3: Build auth middleware [P:4]
### Phase 4: Build export API [P:3]
```

Example (3 phases):
```
### Phase 3: Build auth middleware [P:4,5]
### Phase 4: Build export API [P:3,5]
### Phase 5: Build notification service [P:3,4]
```

**Rules**:
- Symmetric: every phase in a parallel group annotates all its partners
- Eligibility, not requirement: if a partner phase is already complete, the remaining phase executes solo (normal sequential)
- Phases in a parallel group MUST have non-overlapping file scopes (no file appears in more than one group member's changes)
- **Compiled languages**: file-scope disjointness is not sufficient — parallel phases must also target different compilation units (Go packages, Python modules/packages, Java modules, Rust crates). Two files in the same Go package or Rust crate may have disjoint file lists but share a compilation dependency; a broken intermediate state in one phase will break the other agent's build or test run.
- **Runtime resources**: phases that share runtime resources (a DuckDB lock, the git index, a bound socket, the npm cache) are ineligible for `[P:N]` even when file scopes are disjoint.
- `/qplan` SHOULD annotate phases as `[P:N]` when dependency analysis confirms independence (advisory, not mandatory on every invocation)
- `/qdev` detects the annotation and forms parallel dispatch groups (see `/qdev` Step 1)
- Light/inline plans do not use this annotation (no sub-agent spawn)
- Detection regex: `\[P:[\d,]+\]` (colon and closing bracket required; the same match as the extraction regex, so free text such as `[P:3 note ...]` in a heading is not an annotation). Extraction regex: `\[P:([\d,]+)\]`

**Relationship to the Progress Tracker's `[P]` marker**: The Progress Tracker's `[P]` marks tasks *within* a phase as concurrent. The heading-level `[P:N]` marks *phases* as concurrent with each other. They are orthogonal and may coexist. The colon in `[P:` disambiguates from the intra-phase `[P]` marker.

---

## QA Phase Annotation

Phases with self-contained runtime surfaces are annotated with `[QA]` in the phase heading. This signals `/qdev` to run a light QA verification after the phase completes.

- Detection regex: `\[QA\]` (case-sensitive, literal)
- Placement: anywhere in the phase heading, combinable with `[P:N]`
- Annotation rule (mandatory, all tiers): annotate `[QA]` when the phase (a) produces executable code AND (b) its runtime surface is testable in isolation (without outputs from later phases)
- Omit when: docs/types-only phase, OR the surface depends on later phases for meaningful testing
- "Runtime surface" is deliberately general — a REST endpoint, a CLI tool, a headless service's test/replay harness, a library package boundary, or a browser UI all qualify; `[QA]` is never scoped to browser-accessible surfaces only
- Step 9b exhaustive QA runs unconditionally on all runtime surfaces — `[QA]` adds per-phase early detection, it does not replace Step 9b

Example headings:
- `### Phase 1: Add REST endpoint [QA]` — standalone API, testable via curl
- `### Phase 2: Build CLI tool [QA] [P:3]` — standalone CLI, parallel with Phase 3
- `### Phase 3: Integrate UI with Phase 1 API` — depends on Phase 1, no `[QA]`

---

## Bugfix Invariants Format

When a project is a bug fix, the Intent section MUST capture invariants — concrete behaviors that must remain unchanged after the fix. Bugfix is currently the only category that mandates an extra Intent block; if future categories require similar mandates, extend this section with their format specs and detection rules.

### Detection rule (used by `/qexplore` Step 2 and `/qplan` Step 2)

If the user's phrasing or codebase analysis suggests a bug fix (triggers: "fix", "broken", "regression", "incorrect"), ask the user verbatim:

> "This sounds like a bug fix in `<area>`. Bugfix projects require an `### Invariants` subsection in the Intent capturing concrete behaviors that must remain unchanged. Confirm bugfix? Y/n"

If confirmed, immediately ask one follow-up: "What concrete behaviors must remain unchanged after this fix? List one bullet per invariant; the codebase suggests `<list of likely invariants from analysis>` — confirm or extend." Hold the gathered invariants in working memory; write them per the format below when populating the Intent section. **Bugfix is exempted from `/qplan` Step 2's "ask one round of questions" cap** because the follow-up is structural (always one extra question), not exploratory.

### Format

**Standard tier** — between `### Success criteria` and `### Scope boundaries & non-goals`:

    ### Invariants
    - <concrete behavior that must continue unchanged>
    - <another invariant>

**Light tier** — under `## Intent`, after the freeform paragraph:

    Invariants:
    - <concrete behavior that must continue unchanged>
    - <another invariant>

Each bullet states one concrete behavior. Freeform prose — no EARS notation.

---

## Doc & Test Guidelines

This section is the **canonical source of truth** for the per-project `## Doc & Test Guidelines` *schema* — detection, bootstrap, waiver, and subfolder scoping. The **guideline text itself is owned by `shared/AGENTS.md § Doc & Test Guidelines`**, which this section cites rather than restates; governance holds policy, the template holds mechanism. **Renaming this heading breaks those citations** — search for the literal heading string `Doc & Test Guidelines` across `shared/`, `providers/` **and the repository root** before renaming; a pointer body may sit in a root `AGENTS.md`, outside both directories. Rename rule mirrors `shared/AGENTS.md § Harness Improvement Capture` for grep-discoverability via the shared phrase "Renaming this heading breaks those citations".

Each project's `AGENTS.md` should carry a `## Doc & Test Guidelines` section defining per-project doc/test policy. The section is consulted by `/qplan` Step 2 (governance gate), `/qdev` Step 9 (final review), and `/qreview`'s Documentation standard. Consumers treat the section as present when the `## Doc & Test Guidelines` heading exists — presence is by heading, not by a separate detection mechanism.

When a project's AGENTS.md is missing this section, `/qplan` Step 2 proposes the canonical default text below (optionally tailoring one or two bullets after a brief codebase glance — e.g., omit the test bullet if the project has no test directory), presents it to the user via the `Save / Skip / Edit?` idiom from `shared/AGENTS.md § Memory Management`, and writes the section on Save. **When the project has no `AGENTS.md` at all, and its doc/test policy is already codified elsewhere** (e.g. a Kiro steering file's own test-execution section), `/qplan` Step 2 instead proposes creating a **minimal** `AGENTS.md` whose `## Doc & Test Guidelines` section is a one-line **pointer body** (see the pointer-body form below) to that existing location, rather than the full canonical default — this keeps `AGENTS.md` the single place every consumer checks without duplicating policy that already lives elsewhere. If no such policy exists anywhere, propose the canonical default as before. On Skip, planning proceeds without the section but the plan flags that doc/test policy is uncodified. (This is a Doc & Test Guidelines proposal, not a memory proposal — **its Skip writes no declination record**; declinations record only Skips of agent-initiated *memory* proposals.)

When the user makes a request that contradicts the existing guidelines (e.g., "create the full project documentation" against a prototype-style block), the agent applies the request **and** proposes a durable update to the AGENTS.md section using the same `Save / Skip / Edit?` idiom. Never silent. The proposed update names which guideline changes and how. (A governance/doc-policy proposal — **its Skip writes no declination record**.)

**Subfolder conflict resolution**: When a subfolder also carries an AGENTS.md with its own `## Doc & Test Guidelines`, the subfolder's guidelines win for work scoped to that subfolder. Root guidelines apply elsewhere. Kiro's `inclusion: fileMatch` mechanism (used by `/qwire-governance`) handles scope detection automatically.

A waiver is a valid body for this section — a heading present with a single-line decline note means doc/test policy is out of scope for this project. The heading alone satisfies `/qplan` Step 2's bootstrap check and suppresses re-prompting; the waiver body tells `/qdev` Step 9 and `/qreview` to treat doc/test compliance as out of scope. Users may convert from waiver to active guidelines at any time.

A **pointer body** is the third valid body — a heading present with a one-line pointer to the canonical guidelines, for example a single line reading *See `shared/AGENTS.md § Doc & Test Guidelines`*. Use it when the project's policy is exactly the canonical policy, so a local copy would only drift; the config repo itself is the case this form was written for. Like the waiver, the heading alone satisfies `/qplan` Step 2's bootstrap check and suppresses re-prompting. **Unlike the waiver, doc/test compliance stays in scope**: `/qdev` Step 9 and `/qreview` follow the pointer and verify against the cited text. A pointer body may also point at a different in-repo section when a project genuinely has its own policy written elsewhere; what it must never do is restate the bullets, since two copies drift. Because a pointer body cites the canonical heading by name, the rename guard above extends to it — a rename must repoint every pointer body, including ones outside `shared/` and `providers/`, such as this repo's own root `AGENTS.md`.

**Canonical default text** (used by `/qplan` Step 2 when bootstrapping): the five bullets under `shared/AGENTS.md § Doc & Test Guidelines`. Copy them from there — they are not reproduced here, because two copies drift and the governance copy is the one consumers already load.

Citation sites and the rename guard: `shared/AUTHORING.md § Doc & Test Guidelines citation sites`.
