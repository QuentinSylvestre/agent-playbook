---
name: qreview
description: Review pending changes or a draft plan against the playbook's review personas and standards. Use as a shared library called by /qdev and /qplan, or invoke directly to review pending diffs.
argument-hint: "[<plan-path>]"
---

# Review

## Your role

Apply the playbook's canonical review personas, persona-selection rules, sub-agent fan-out rules, verdict rubrics, and review standards to a target artifact (a code diff or a draft plan). Return findings in the standard 4-column table format. This skill is the single source of truth for review behavior; `/qdev` and `/qplan` call into it as a library, and users may invoke it directly as a slash command.

> **Citation convention**: Citations name sections, never numbers: `shared/AGENTS.md § SKILL.md Authoring`.

## 1) Personas table

**Senior engineer** is the canonical fallback when no domain-specific persona dominates; **Maintainability reviewer** remains for explicitly chosen code-clarity reviews (refactors, naming-heavy changes). **Architect** evaluates structural fitness and whether abstractions earn their complexity; **Senior engineer** evaluates integration health, delivery completeness, and broad proportionality.

| Persona | Focus area |
|---|---|
| Security auditor | Authentication, authorization, input validation (injection surfaces), secrets, attack surface (CORS/CSP defaults, timing attacks, mass assignment) |
| Performance engineer | Latency, throughput, memory (leaks, cleanup), algorithmic complexity (N+1, redundant work), caching, missed concurrency (TOCTOU) |
| End-user advocate | Usability, error messages, edge cases from user perspective, accessibility |
| Reliability engineer | Failure modes, error handling (silent swallowing), recovery (timeouts, retries, circuit-breakers), observability, resource leaks |
| Maintainability reviewer | Code clarity, naming, coupling (leaky abstractions), test coverage, future extensibility (redundant state, reuse) |
| Domain expert | Business logic correctness, domain terminology, regulatory compliance |
| Senior engineer | Cross-cutting integration health, plan/intent compliance, code completeness (no dead code or dangling wiring, cleanup paths), test adequacy (failure-mode coverage), broad pragmatism |
| Architect | System structure, component boundaries (SRP), dependency direction, abstraction layering, interface contracts (caller coordination), scaling readiness, over-engineering detection (YAGNI), scope creep, wrapper/proxy delegation correctness |

Add project-specific personas as needed.

## 2) Persona-selection rules

Persona selection is keyed by call site. Use the rule that matches the invocation context:

| Call site | Rule (mandatory minimum) |
|---|---|
| `/qplan` Step 4 Standard/Major | **`Architect + Senior engineer + ≥1 domain-relevant persona`** (3 personas) |
| `/qplan` Step 4 Light | **`Senior engineer alone`** (1 persona) — Architect not used at Light tier. **The 1-persona floor applies only when the plan is ≤2 files AND contains no executable code** (prose-only edits to SKILL.md / AGENTS.md / TEMPLATES.md / docs). A Light-tier plan that touches executable code takes the Standard/Major row instead. |
| `/qdev` Step 5 (per-phase) | Pick the persona whose focus area best matches the phase's highest-risk aspect (e.g., auth middleware → Security auditor; refactor → Maintainability reviewer). When a phase spans multiple domains with comparable risk weight, assign multiple personas. **Fallback when no persona dominates: `Senior engineer`**. Vary persona selection across phases when reasonable. Count only personas explicitly assigned by these rules; do not pre-emptively pad the count to escalate fan-out. |
| `/qdev` Step 9 (final) | **`Senior engineer + ≥1 domain-relevant persona`** (broad/high-risk implementations may add more from the personas table) |
| `/qreview` user-invoked | **`Senior engineer + ≥1 domain-relevant persona`** (matches `/qdev` Step 9 for symmetry) |

For `/qplan` Step 4, additionally include **Security auditor** for security-sensitive changes and **Domain expert** (or a regulatory-compliance persona) when the plan implements a formal standard or compliance framework. Use judgment for the rest: pick personas whose focus overlaps the plan's risk profile; not every persona is needed for every plan.

**Full-effort override**: When effort is Full, the minimum persona count is 4 regardless of call-site rules above. **Check this override BEFORE reading the call-site table, not after** — it supersedes every row, including the Light-tier 1-persona floor, and an agent that applies the row first reads "1 persona" as settled. Apply the override, then add domain-relevant personas from the Personas table until the count reaches 4.

## 3) Sub-agent fan-out rules

Fan-out is determined solely by persona count:

| Trigger | Fan-out mode |
|---|---|
| Review has **2+ personas** assigned | Per-persona fan-out: one sub-agent per persona, fresh context; in parallel, except as Mutation-testing isolation (Sub-agent execution) requires |
| Review has **1 persona** assigned | One sub-agent (the inherent degenerate case of per-persona) |

Per-persona fan-out and context isolation are mandatory; isolation keeps each reviewer free of author bias.

## 4) Effort tiers

Effort scales both breadth (persona count) and depth (per-persona instructions, verification). Callers pass `effort` via the Library mode contract; default is `standard`.

| Effort | Personas | Technique guidance | Verification | Finding cap |
|---|---|---|---|---|
| Light | 1 (Senior engineer) | None | None | 4 |
| Standard | Per persona-selection rules (unchanged) | None | None | No cap |
| Full | 4+ (per rules + always add extra domain personas) | Yes (4 angles) | Three-state (separate verifier) | No cap |

All tiers include silent-drop prevention and low-count second look in the base brief.

**Explicit user effort binds.** When the user names an effort level for a review (for example "max /qreview effort", which maps to `full`), that level applies to every review in the run: all personas, the Verification phase, plan review and cycle-2 re-reviews. The orchestrator never lowers it on an inferred preference such as quick or approving replies; only the user can lower it.

## 5) Standards union

The full canonical union of review standards. Each call site declares which subset applies (see Subset declaration per call site below).

- **Plan compliance**: Does the implementation match what the plan specified? Are all tasks from the phase actually done? Were exit criteria genuinely met? Are there undocumented divergences?
- **Code quality**: Does the code follow the project's existing patterns and conventions? Are there bugs, logic errors, or unhandled edge cases? Is error handling appropriate? Are there security concerns? If the implementation introduces non-code runtime artifacts (data files, templates, static assets, native binaries), verify they are included in the project's build/packaging pipeline.
- **Test coverage**: Were the tests specified in the plan actually written? Do the tests cover the right scenarios? Are there missing test cases for edge cases or error paths? Where a test is claimed to pin a specific behaviour, verify by **mutating that behaviour and confirming the test fails**. A test that still passes against the mutation reports coverage that does not exist, and reading it cannot tell you which of the two it is. This is what catches a fixture that makes its own test vacuous, a harness handing out references into its own store, and a claim that some *other* test already covers the thing you are about to delete. When the implementer listed the guards it mutated, mutate first the guards missing from that list: an author's own mutants miss the guards it did not think to probe.
- **Backwards compatibility**: Were compatibility strategies from the plan implemented? Could any change silently break existing behavior?
- **Documentation**: Are implementation notes accurate? Are divergences documented? Were documentation updates listed in the plan completed? Does the implementation comply with the project's `## Doc & Test Guidelines` section in `AGENTS.md` (existing docs updated when relevant; no new doc files created unless the guidelines or the user explicitly authorize them; README updated only for user-visible changes)? If the project's AGENTS.md lacks this section and the plan flagged the absence, treat the plan's Open items entry as the authoritative policy for this review only. If the section is a waiver (the heading present with a single-line decline body, per `shared/skills/qplan/TEMPLATES.md § Doc & Test Guidelines`), treat doc/test compliance as out of scope for this review.
- **External dependencies** (post-impl lifecycle point — distinct from External readiness, which is the pre-impl variant of the same concern): Were external prerequisites provisioned and configured? Did unplanned external dependencies emerge? Are rollout/migration/cleanup phases still pending, and if so is the current status reported as pending rather than complete?
- **Correctness**: Are file references and line numbers accurate? Do proposed code changes work with the actual codebase? Are dependencies between phases correctly ordered? When the plan was preceded by `/qexplore`: does any plan content (Design Decisions, Success Criteria, phase descriptions) contradict a Resolved Decision from the exploration? Flag contradictions as High severity (severity floor; see Verdict rubrics). When a review fix edits `[P:N]` parallel annotations (adding, removing, or reassigning), run qvalidate's `parallel-symmetry` check on the plan as a post-fix verification — an asymmetric annotation surviving review is the failure mode this catches.
- **Completeness**: Are all affected files identified? Are test changes included for each phase? Are edge cases addressed? Are backwards compatibility implications covered? Are exit criteria concrete and verifiable? **Where a criterion names a gate — a bench, harness, suite or script — apply the same mutation test the Test coverage standard applies to a test: would that gate still pass if the phase's change were arbitrarily wrong?** A gate that cannot detect the change it is assigned to reports coverage that does not exist, and reading its name cannot tell you which of the two it is. Check that the gate's own code path actually reaches the phase's `**File scope**` — the common failure is a bench that models a component rather than exercising it. Does the plan identify which project documentation needs updating? If the change affects persisted data, cloud resources, or manual operator flows: does the plan include explicit migration/cutover/cleanup phases rather than burying them in notes? If the plan implements a formal standard or compliance framework: are all mandatory elements explicitly enumerated? Is external validation included as an exit criterion? Are documentation updates from the Documentation Updates section wired into each phase's exit criteria (Standard/Major) or verification items (Light)?
- **Feasibility**: Can each phase be implemented independently? Are effort estimates reasonable? Are there hidden dependencies?
- **Risk**: Are there security implications not addressed? Could any change silently break existing behavior? Are there race conditions or concurrency concerns?
- **External readiness** (pre-impl lifecycle point — distinct from External dependencies, which is the post-impl variant of the same concern): Are all infrastructure, CI/CD, IAM, third-party, and data-migration dependencies identified? Is there a cost impact assessment? Are required manual actions assigned an owner? Does the plan define environment order, backup/rollback expectations, validation after cutover, and deferred cleanup after the rollback window when applicable?
- **Cost impact**: Does the plan flag recurring or material one-off cost changes (hosting, compute, API calls, storage, licensing, sub-agent token cost)? Is explicit user approval secured when needed?
- **Exit-criteria integrity** (Standard/Major only): For each exit criterion ticked `- [x]` by the implementer, verify the criterion is actually met by the committed changes. Perform the **deterministic count check** by running qvalidate's `phase-count` check (`--phase N --expect-ticked <implementer's exit_criteria_ticked>`; see `shared/skills/qvalidate/SKILL.md`), which compares the ticked `- [x]` boxes inside the just-completed phase block against the implementer's reported count; handle a FAIL per `shared/skills/qvalidate/SKILL.md § Failure semantics`. On mismatch, flag as High-severity (severity floor; see Verdict rubrics) and diff the project-file checkbox deltas against the code-commit changes. Also flag any exit criterion clearly satisfied but not ticked. Light tier has no checkboxes and is exempt. (Caller-side gating — e.g., `/qdev` Step 8's auto-continue gate — is owned by callers, not by this standard.)
- **Proportionality / Leanness** (instruction/governance/prose targets only — skills, `AGENTS.md`, prompts, plans; NOT user runtime code): Does the artifact say more than it needs to? Flag over-specification (prescribing mechanics a capable reader already knows), redundant or cross-file restatement (content duplicated from a canonical owner instead of cited), and distrust-priming (anti-rationalization nags, intensifiers, "this framing is intentional" editor asides). **Carve-out — never flag as bloat**: safety/correctness gates, behavioral contracts, non-obvious procedures, data-integrity rules, or any guardrail whose removal would change behavior or weaken a protection. The goal is to stop the playbook re-accreting scaffolding, not to strip guardrails.

## 6) Verdict rubrics

Canonical definitions for the two verdict vocabularies this skill emits. Callers and
other skills cite this section by name; no other file may define these terms —
subordinate one-line domain glosses that cite this section and illustrate (never
re-level) are permitted.

### Severity anchors

Severity ∈ {High, Medium, Low} (closed set; an out-of-set or missing value is treated
as High and the labeling failure surfaced).

- **High** — breaks a core capability of the change's consumers, loses or corrupts
  data or state, creates a security exposure, or violates a stated plan decision,
  invariant, or governance contract.
- **Medium** — degrades a real path with a workaround; drifted or incomplete behavior
  that does not block core use; a gap that will predictably surface as a defect.
- **Low** — cosmetic, minor friction, or an improvement opportunity with no
  behavioral consequence.

### Scoring discipline

- **Worst instance, not the mean**: a finding's severity is that of the worst
  concrete instance it covers, not an average over its occurrences.
- **Tie-break upward (single-reviewer rule)**: when genuinely torn between two
  adjacent levels after assessing actual impact, assign the more severe. Distinct
  from the cross-persona merge rule (Sub-agent execution keeps the highest severity
  when deduplicating across reviewers) — that rule reconciles multiple scorers; this
  rule resolves one scorer's uncertainty.
- **Never re-score toward a preferred verdict**: severity is assigned once, from the
  anchors; it is never adjusted afterward because of the health rating, gate outcome,
  or workload it produces.
- **Class floors**: where governance maps a finding class to a fixed severity (e.g.
  /qqa FAIL findings entering /qdev's fix loop → Medium; invariant regression → High), that mapping is a
  floor — the anchors may escalate an instance above it, never below. High-mapped
  classes are unaffected (already maximal).

### Override discipline (justified overrides)

A finding may be closed other than by a fix only through a recorded, reasoned
decision: `User: accepted — <user's reason>` (see the `Resolution column values`
block in /qdev Step 7, project-file update) is the justified-override audit
category, greppable as such. The cell cites the user turn as it is written (a quote,
a `YYYY-MM-DD` date, or a turn or decision reference); `qvalidate`'s
`acceptance-evidence` check FAILs one without it, and no marker is added to an
existing row the user did not give. Wherever you mention or quote the label (a
Finding cell, prose), write it in backticks, since plain text there is a hit; never
backtick it in a cell that records an acceptance, whether a Resolution or a
decisions-table cell. A finding dismissed, downgraded, or waved through
without a justification string is itself a finding (Medium floor) in the next review
that observes it — reviewers carry this audit duty via the Spawn brief contract. The
same convention governs guard-script overrides — owned by the Guard-override
discipline paragraph in `shared/skills/qvalidate/SKILL.md § Failure semantics`.

A finding closed this way that leaves a future action item — a fix not applied now
but worth tracking — must also get a one-line pointer in the project file's
`## Follow-up Work (Deferred)` section (`shared/skills/qplan/TEMPLATES.md § Follow-up
Work (Deferred)`; create the heading if absent). A closure with nothing left to act
on later (the design is intentional, no future action needed) does not require an
echo.

A delivery stage (for example a time-boxed pilot versus production) never changes a finding's severity and never removes a finding from the reviewer's return: severity comes from the Severity anchors alone, and Silent-drop prevention still applies. The stage changes only the disposition. When the project file or the user states a delivery stage, the caller puts it, with its source, in the Spawn brief, and the reviewer still reports every candidate. A finding that meets no Medium or High anchor and only hardens an edge the stage does not need (an improbable input, scale beyond the stated horizon) is rated Low, labeled `stage-deferred`, and closed as `User: accepted — stage-deferred: <stage> ("<the user's words>", <YYYY-MM-DD>) — <reason>`, whose quote and date cite the user turn it records, with a one-line pointer in `## Follow-up Work (Deferred)` as above. A finding that meets a Medium or High anchor stays at that severity whatever the stage. Findings inside behaviour that a user decision added during the same review cycle are reviewed like any other finding. They are not counted as regressions of the earlier cycle.

### Health derivation

Implementation/plan health ∈ {Green, Yellow, Red} is **derived, not rated**: Red if
any unresolved High finding exists; Yellow if any unresolved Medium; Green otherwise.
The resolved/unresolved test is a total partition over Resolution values:
**resolved** = a Resolution beginning `Fixed` or `User: accepted`;
**unresolved** = everything else — an empty cell,
`Escalated` (a cell still reading Escalated records no user response; it is
rewritten when the user responds), `Orchestrator: proposed-accept — pending user
decision`, and any out-of-set value. An out-of-set value is additionally surfaced
as a Medium-floor finding per Override discipline; pre-plan legacy vocabulary
(`Noted`, `Resolved --`, free text) is a re-label, not a governance-contract
violation — it never triggers the High anchor's contract clause. The resolved-arm
prefix is a literal, case-sensitive token match on `Fixed` / `User: accepted`;
only the separator punctuation after the token varies. Health is a recomputable
function of the current merged findings and their resolution states, evaluated
fresh at each consumption point (per-phase log write, auto-continue gate,
parallel-group joint gate, final synthesis, library-mode plan-review return
(informational)) — never frozen at merge time. The rule applies identically to per-phase,
final, and plan reviews. The orchestrator computes it; review sub-agents do not
return a health rating — there is no separate health channel, so a reviewer's
residual or systemic concern must be expressed as a finding with a severity, or it
does not exist for gating purposes.

## 7) Subset declaration per call site

Each call site declares which subset of the Standards union above applies.

| Call site | Standards subset | Default effort |
|---|---|---|
| `/qdev` Step 5/9 (per-phase + final) | Plan compliance, Code quality, Test coverage, Backwards compatibility, Documentation, External dependencies, Exit-criteria integrity + Proportionality/Leanness (conditional: only when the reviewed diff touches a skill, `AGENTS.md` or prompt file; steering excluded, see below) | Standard, at every plan tier; the user may escalate a phase to Full |
| `/qplan` Step 4 (Standard/Major + Light) | Correctness, Completeness, Feasibility, Risk, External readiness, Cost impact + Proportionality/Leanness (conditional: only when the plan changes a skill, `AGENTS.md` or prompt file; steering excluded, see below) | Standard |
| `/qreview` user-invoked | Full union (all 14 standards) for completeness | Standard |

Default per plan tier: `shared/AGENTS.md § Workflow` (One effort vocabulary).

`/qreview <plan-path>` reuses `/qplan Step 4 Standard/Major`'s subset (it is a plan review by another name); it is not a separate declaration. The conditional Leanness clause deliberately excludes steering diffs — steering restatement of shared content is sanctioned by the authoring boundary (`shared/AGENTS.md § Repository Layout`).

> **If this list changes, update the call site to match.** Subset declarations live in this single place — no duplication. Drift between caller prose and this table is a review finding.

## 8) Spawn brief contract

Callers populate the spawn brief; `/qreview` library mode receives it and returns findings. The brief specifies:

- The project file path and the completed phase number (or, for `/qplan` Step 4, the plan path under review)
- When the Exit-criteria integrity standard is in the review's standards subset (`/qdev` Step 5/9), the implementer's reported `exit_criteria_ticked` count for the completed phase, so the reviewer can run qvalidate's `phase-count` check (`--phase N --expect-ticked <that count>`; see `shared/skills/qvalidate/SKILL.md`)
- Paths to governance files (`AGENTS.md`, `CLAUDE.md`) -- instruct the sub-agent to read these before reviewing
- The review standards above
- The Severity anchors and Scoring discipline text from Verdict rubrics (carried verbatim — the sub-agent scores using this text directly); when the brief includes a project file path, the Override discipline text is carried verbatim too — it defines the reason-less-closure audit the sub-agent performs
- The assigned persona name(s) and focus area(s) (from the Personas table)
- Instruction: evaluate the implementation through your persona's lens, applying the review standards with emphasis on your focus area
- **Reviewer stance: assume the implementer was under time pressure and cut corners where it was easy to get away with. Hunt for corner-cutting patterns — omitted validation, placeholder logic left in, untested branches.**
- **Treat the plan's empirical claims as hypotheses to test, not as context to trust.** A brief that quotes the plan as ground truth turns a false premise into a confident false-negative: a doc-impact agent dispositioned nine real hits as `false-positive` on one inherited wrong claim. Check any plan claim your findings would depend on, and report a claim you cannot confirm as a finding in its own right.
- **Tool surface: read the diff and the enclosing code yourself before running anything.** Read-only commands (`git diff`, grep, file reads) are always allowed. Read the commit under review with `git show <sha>` or `git diff <base>..<sha>`, never by checking it out in the shared working copy: a checkout leaves it on a detached HEAD. Run code only where a check in this brief or its standards requires it — e.g. the Test coverage mutation test, qvalidate checks, an exit criterion's named command. Write only the temporary mutation such a check needs and your findings file if the brief names a scratch path (otherwise return findings as text); restore a mutated file's exact pre-mutation content before you return, never via `git checkout` or `git restore`. Do not dispatch further sub-agents.
- The expected commit under review. A reviewer in an isolated worktree checks that commit out before reading (worktree isolation starts from `origin/main`; the commit is reachable because worktrees share the repository), then confirms HEAD matches. The orchestrator removes any review worktree and its branch as the review's last step.
- If the Intent section contains an `### Invariants` H3 (Standard tier) or an `Invariants:` bullet block (Light tier) — see `shared/skills/qplan/TEMPLATES.md` `## Bugfix Invariants Format` — verify each entry is preserved by the change. Flag any apparent regression as a High-severity finding (severity floor; see Verdict rubrics). Otherwise skip this check.
- **Enclosing function scope**: bugs in unchanged lines of a touched function are in-scope — the change re-exposes or fails to fix them. Reviewers must read the full enclosing function/method, not just the diff hunk.
- Severity assignment follows the Verdict rubrics carried in this brief; rate severity on actual impact, not on suspicion level. Also, when the brief includes a project file path, flag reason-less finding closures observed in its review log (Override discipline, Medium floor).
- **Silent-drop prevention**: Pass every candidate with a nameable failure scenario through to your findings. Silently dropping half-believed candidates is the dominant cause of review misses. When uncertain whether something is a real issue, surface it — let severity sorting and dedup handle prioritization.
- **Low-count second look**: If your findings count is below the number of files under review (the diff's files, or the files a plan changes), do one additional pass over the largest changed files and any removed code blocks before concluding. If genuine findings still don't surface, report what you have — never manufacture findings to hit a target.
**Effort-conditional additions to the brief** (see § Effort tiers):

- **At Light effort**: append to the brief: "Report at most your 4 highest-severity findings: for a diff, what would break at runtime; for a plan, what would make a phase fail. Skip style, naming and performance. If you had more candidates than the cap allows, say so in one line."
- **At Standard effort**: no additions (current brief text is complete as-is).
- **At Full effort**: append the technique guidance, Plausible-by-default rule and language-pitfall catalog from `full-effort.md` (alongside this file) to the brief.

**Sub-agent returns**: findings with severity and recommendation, in Findings table format (confidence, when given, goes in the prose below the table), plus the exit criteria audit where applicable. Where the harness refuses sub-agent report files, these come back as text and the orchestrator writes them to scratch (`shared/AGENTS.md § Multi-Agent Coordination`).

## 9) Sub-agent execution

**Announce effort**: At the start of every review, state the effort level (light/standard/full) and persona count being used. Example: "Running full-effort review (4 personas: Senior engineer, Security auditor, Architect, Reliability engineer)."

This subsection is the sole owner of fan-out dispatch and findings merging. Launch one sub-agent per assigned persona, in parallel unless Mutation-testing isolation below applies; each receives the Spawn brief contract above with a single persona name in the persona slot. The 1-persona case is the natural degenerate (just one parallel branch — no merging needed). For 2+ personas, merge their returned findings: deduplicate identical findings across personas (keep highest severity); when a finding came from multiple personas, record them comma-separated, per Findings table format. The merged findings list (or the single sub-agent's table, for 1 persona) is what callers (e.g., `/qdev` Step 6 auto-fix and Step 7 review log) consume.

**Mutation-testing isolation**: a review whose subset includes Test coverage or Completeness invites live mutation testing (temporarily editing production code to verify a test's or gate's protective power, then reverting). Two reviewers mutating the same working copy at overlapping moments can silently corrupt each other's "before" baseline. So when such a review has 2+ personas, give each reviewer its own isolated worktree and run them in parallel, or, where the harness cannot isolate them, dispatch them **sequentially**.

## 10) Verification phase

**Full-effort only.** After persona sub-agents return, one refuting verifier per single-source finding keeps or drops it. The procedure, verifier brief and refutation evidence gate are in `full-effort.md` alongside this file. At Standard and Light effort, findings pass directly from Sub-agent execution to Findings table format.

**Plan-review variant.** When the review target is a plan (no diff, and the code the plan describes does not exist yet), the verifier keeps the same stance and the same three verdicts, and the evidence gate changes only in what it quotes. Give the verifier the finding, the plan text, and the existing repository files the plan touches or cites. REFUTED requires a quote of one of: the plan text or existing repository text that contradicts the finding (a cited path, symbol or interface that is different from what the finding assumes); an existing type, constant or invariant that makes the failure unreachable under the plan's design; a plan step, phase or exit criterion that already handles the concern (cite its heading); or pure style with no effect on the plan's outcome. "The code does not exist yet", "the plan does not show the implementation" and "this will be decided during implementation" are not refutation grounds, because the plan is the artifact under review: a design gap the plan leaves open is PLAUSIBLE. A finding that asks for detail the plan deliberately defers is refuted only if the plan says where the detail is decided (cite it). Disposition is unchanged: keep confirmed and plausible, drop refuted.

## 11) Completeness critic

**Full-effort only.** After the Verification phase, one critic sub-agent lists coverage gaps as an advisory section below the findings table; see `full-effort.md`. Skipped at Standard and Light effort.

## 12) Findings table format

The standard findings table is 4 columns:

| # | Severity | Finding | Resolution |
|---|---|---|---|

Each Finding cell is one prose sentence, ≤25 words; each Resolution cell is one prose sentence, ≤25 words. If a finding needs more, move detail to the prose body below the table. Quote sub-agent prose only when the finding's wording is essential.

When 2+ personas surface findings, an optional **Persona** column may be added to attribute findings after merge (per Sub-agent execution above). Identical findings raised by multiple personas are merged into one row; record the contributing personas in the prose body below the table if it matters for traceability. 1-persona reviews omit the Persona column — attribution lives in the heading line.

## 13) Sub-agent unavailability gate

**The orchestrator never evaluates its own output.** All review passes through a sub-agent dispatch. There is no self-review fallback.

If sub-agent dispatch fails (the harness's sub-agent tool — Agent/Task on Claude Code, `invokeSubAgent` on Kiro — returns an error, is unavailable, or the environment cannot spawn sub-agents), the orchestrator MUST **stop immediately** and present the user with three options:

1. **Retry** — attempt sub-agent dispatch again (transient failures, context limits).
2. **Skip review for this phase** (not recommended) — no review is recorded for this phase. The orchestrator logs `Review skipped (sub-agent unavailable, user approved) -- persona(s): [planned list].` in the review log. This is an informed user decision, not an agent fallback.
3. **Abort** — halt `/qdev` or `/qplan` execution entirely. The user resumes later when sub-agents are available.

The orchestrator MUST NOT:
- Self-review using the same standards
- Adopt persona perspectives and evaluate its own work
- Infer that sub-agents are "unavailable" based on tier, file type, change size, or time pressure — the only valid signal is an actual dispatch failure
- Write `REVISIT WHEN SUB-AGENTS AVAILABLE` markers (this mechanism is retired; see Legacy REVISIT markers below)

Legacy `REVISIT WHEN SUB-AGENTS AVAILABLE` markers in older project files are resolved by `/qdev` Step 9 and `/qclose` Step 2 Pass 3.

## 14) Library mode contract

**Mandatory activation requirement**: Callers must ensure `/qreview` rules are in active context before constructing review briefs. How this is achieved (re-read, mechanical loading, persistent context) is caller-determined.

When `/qreview` is called as a library by `/qdev` Step 5/9 or `/qplan` Step 4, the caller passes:

- The persona set (per Persona-selection rules for that call site)
- The standards subset (per Subset declaration per call site for that call site)
- The effort level: `light`, `standard`, or `full` (default: `standard`; see § Effort tiers)
- The target artifact: a code diff (with completed phase number, for `/qdev`) or a plan path (for `/qplan`)
- Governance file paths (`AGENTS.md`, `CLAUDE.md`)

`/qreview` returns:

- The merged findings table (4-column format per Findings table format)
- An overall implementation/plan health rating (Green / Yellow / Red), derived by the orchestrator per Verdict rubrics (consumed by /qdev's gates; informational for plan reviews)
- An exit-criteria audit (when Exit-criteria integrity is in the standards subset)

**`/qreview` does NOT own**:

- **Auto-fix loop or cycle caps** — these stay in callers (`/qdev` Step 6: max 2 cycles, regression-revert; `/qplan` Step 4: max 3 cycles).
- **Review-log writing into the project file** — orchestrator-owned in `/qdev` Step 7.
- **Per-phase Skip rule** — stays in `/qdev` Step 5.

## 15) User-invokable mode

`/qreview` is also a user-invokable slash command. Three input forms are supported:

- **`/qreview`** (no args) — review the pending diff on the current branch against its merge base.
- **`/qreview <plan-path>`** — review a draft plan at the given path. Uses the `/qplan Step 4 Standard/Major` standards subset and persona rule.
- **`/qreview --scope <path>`** — restrict review to a subtree of the working tree (used with `/qreview` no-args mode to scope down a large diff).

Personas follow the `/qreview` user-invoked row of Persona-selection rules; pick the domain-relevant persona from the diff's (or plan's) highest-risk aspect, the way `/qdev` Step 5 does.

User-invoked mode emits **findings only** — no auto-fix, no code edits. The user reviews the findings table and decides what to do. On a clean working tree with no merge-base divergence (no diff to review), `/qreview` exits with a clear "no changes to review" message; it does not error.

The user-invoked dispatch constructs its sub-agent brief per the Spawn brief contract — including the reviewer-stance bullet — and follows the Sub-agent fan-out rules and Sub-agent execution like any other call site.
