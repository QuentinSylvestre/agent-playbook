---
name: qexplore
description: Explore codebase and refine requirements through thorough analysis and targeted questions. Use when starting work to reach high confidence before planning.
argument-hint: "<work description>"
---

# Exploration

## Your role

You are a senior engineer helping finalize the design of changes to high confidence and reduce risk. You must thoroughly understand the codebase before asking questions so you ask relevant ones. Approach this with an analyst's perspective — focus on understanding the problem space and surfacing risks rather than jumping to solutions.

> **Mode**: This is the code-flow exploration. For non-code work (PRDs, infra debate, business plans, off-codebase decisions), use `/qexplore-other` for a grill-me-style stress-test.

## Work to explore

$ARGUMENTS

## Process

Before starting, read `shared/skills/qexplore/shared.md` (repo-relative path) for cross-mode question discipline, the convergence test, and the recommendation-oscillation gate (which invokes `/qcouncil` when the orchestrator changes its recommendation more than once). The rules there govern every question you ask.

### Process gate: no implementation

This skill never writes production code, never modifies code files, and never runs build or test fixes. It also never edits a governance file (`AGENTS.md`, `CLAUDE.md`) or a glossary file — governance content this skill settles is *recorded* for `/qplan` to propose, never written here. Writing the Intent section of a project file in Step 3 is allowed because it is a planning artifact, not a code change. **Exception — disposable verification tests**: a load-bearing claim that only runtime behavior can settle (not code-reading) may be checked with a throwaway test or script, deleted immediately after with `git status`/`git diff` confirmed clean, and the result recorded in Step 3's Discovery. Side-effecting probes still need the user's consent per the Probe gate below; a read-only, in-repo disposable test does not.

### Step 1: Understand

**Mode detection.** Assess whether the codebase has relevant existing code for the described work:

- **Brownfield** (relevant code exists — files that will be modified, extended, or depended upon): proceed to codebase analysis below.
- **Greenfield** (no relevant existing code — new project, new standalone capability, or no codebase to analyze): skip codebase analysis. Go directly to Step 2 (Interview). Note in the summary: "Greenfield — no existing codebase analysis performed."

**Heuristic**: if the work primarily involves creating new files/modules rather than modifying or extending existing ones, treat as greenfield. When in doubt (e.g., new feature in an existing project that will integrate with existing code), default to brownfield — unnecessary codebase analysis is cheaper than missed constraints.

**Codebase analysis** (brownfield only). Before asking any questions, thoroughly analyze the relevant parts of the codebase:

- Read files that will be affected by this feature
- Understand existing patterns, conventions, and architecture
- Identify constraints and dependencies
- Note existing tests and quality gates
- Identify the project's build, packaging, or distribution pipeline (e.g., PyInstaller .spec, webpack config, pyproject.toml `package_data`/`MANIFEST.in`, Cargo.toml, .nuspec, electron-builder config) and note what non-code artifacts are currently bundled. If the project uses CI/CD scripts (GitHub Actions, Jenkinsfile, Makefile), check whether they drive a bundling step that also controls artifact inclusion.
- Reference specific files and line numbers in your findings
- Check the project's governance files (`AGENTS.md`, `CLAUDE.md`, or equivalent) for architectural or product principles. If found, note them as constraints that will inform intent capture and design decisions.
- **Prior art scan**: search project documentation (`docs/`, the archive `done/` under the project-file root resolved per `shared/skills/qdream/memory-rules.md § Resolution contract`, gotchas/lessons-learned files) and surface any "we tried X and it didn't work because Y" evidence before converging on a design. When the work replaces or ports an existing user-facing surface, or answers a defect the user perceives, also read `memory/topics/ui-replacement-and-user-perceived-defects.md` in the config repo.

**Step 1 output (problem context summary)**: as you complete the codebase analysis, hold a working **problem context summary** in your working context (not written to any file). It contains:
- **Files identified**: files and directories relevant to the work
- **What was read**: for each file, the sections/ranges you actually read
- **Gaps**: sections you identified as existing but did NOT read (e.g., "runner.py exists, read lines 200-250 and 470-570, skipped 250-470")
- **Initial findings**: patterns, constraints, and hypotheses from your scan

For brownfield work, this summary is passed to Step 1.5's sub-agents as advisory context (not binding constraints).

**Mandatory dispatch gate** (brownfield only): After completing the problem context summary, stop. Do not continue reading files or perform further codebase analysis in the orchestrator context. Do not proceed to Step 2 without first completing Step 1.5's sub-agent dispatch (unless the user has directed inline exploration — see the **User-directed inline override** below). The orchestrator's role at this point is to package findings and dispatch — not to keep analyzing. Only the greenfield classification and explicit user override can bypass this gate.

**Non-bypasses**: scope size ("too large to run fully" — the user accepts large explorations); simplicity ("straightforward change" — Trivial classification happens at Step 2, *after* dispatch); task-type reclassification (an extraction/port/copy task that *reads* existing code is brownfield by definition, whatever it *writes*); **context sufficiency** ("the relevant code is already in my context" / "I already read the files" — Step 1.5's value is context isolation and adversarial re-reading by *fresh* agents, not first-time file access); and **prior-dispatch freshness** ("sub-agents I dispatched minutes ago already cover this ground" — a previous task's research was scoped to that task's question, not this exploration's). If you find yourself constructing a reason the dispatch is unnecessary, that is the signal to dispatch — this list is illustrative, not exhaustive, and a shape it does not name is not thereby permitted.

**Mid-session deep-dive dispatch**: When a new sub-problem surfaces during Q&A (Steps 2–3) that requires code-tracing or investigation beyond the initial trio's coverage — e.g., a newly-discovered data path, an unforeseen dependency, a scope expansion — confirm with the user before proceeding: "This sub-problem [X] wasn't covered by the initial exploration. Recommend dispatching a focused sub-agent (or scoped trio) before answering — proceed?" Do not attempt inline deep investigation for sub-problems outside the initial trio's coverage; the mandatory dispatch rationale (context isolation, thoroughness) applies equally to mid-session discoveries.

### Step 1.5: Deep research (brownfield only)

Skip the codebase trios in greenfield mode (no codebase to dispatch against). When skipping in greenfield mode, note "Step 1.5 skipped — greenfield mode" in Step 3's Discovery item 4, mirroring Step 1's existing greenfield-skip note convention.

**Greenfield web-research dispatch (user-requested only).** The skip above does not forbid research the user asks for. When the user explicitly asks for web or external research on a greenfield topic, dispatch one read-only `general-purpose` sub-agent (fresh context; web search and fetch tools only; no file writes; no further dispatch) instead of researching inline. Brief it with the Step 1 problem context summary as advisory input, the specific questions to answer, and the Sub-agent report contract block verbatim. It returns findings with a source URL for each claim; label any claim with no source `[unverified]`. Do not dispatch it unprompted, and do not use it to replace the trios in brownfield mode. Record it in Step 3's Discovery item 4 as "Greenfield web-research sub-agent dispatched at user request", and distil its report into the Discovery summary; the raw report is never written to the project file. A dispatch failure follows the Sub-agent unavailability gate below.

**Task-type inference (do this first).** Before selecting briefs, classify the task type from the in-scope signals in the Step 1 problem context summary — specifically the file extensions and paths of the files identified as relevant:

- **Code-tracing** — the in-scope files are predominantly source code (`.py`, `.ts`, `.js`, `.go`, `.rs`, `.java`, etc.). Use the **code-tracing trio** (directed / subsystem / mutation-finder).
- **Prose/governance** — the in-scope files are predominantly documentation, governance, or skill prose: `shared/skills/**`, `AGENTS.md` / `CLAUDE.md`, `providers/**`, and other `*.md` governance/prose. Use the **prose/governance trio** (directed / Consistency/Duplication-finder / Citation/Caller-impact).
- **Ambiguous** — the scope mixes both in a way that no set clearly fits (e.g. a skill directory that is BOTH `.md` governance AND ships an executable `.sh`/`.ps1` script — like the very plan that introduced this branch). Do not guess: ask the user which set to dispatch ("This scope mixes governance prose and executable code — run the code-tracing trio, the prose/governance trio, both, or one trio + orchestrator manual pass on the minority scope?"). The fourth option (selected trio + orchestrator manual pass) is appropriate when one surface dominates and the minority is small enough for the orchestrator to cover directly without sub-agent dispatch. **No-ask shortcut**: when the minority surface is a single known-shape edit already precedented in a prior wave or plan (e.g., a one-row addition to a script that the same project edited identically before), the orchestrator may select the dominant trio + cover the minority directly without asking — the precedent removes the ambiguity that warrants the question. Similarly, when no file in the minority surface appears in the plan's write scope (it is read for context or precedent but not modified), the orchestrator may select the dominant trio without asking — the trio choice does not change what the sub-agents would report about read-only context files. The same applies when the scope is prose-dominant and its only executable part is a new script that follows an existing script's shape (e.g. a twin of an existing guard): dispatch the prose trio and cover the script directly.

Dispatch the selected trio's three **parallel** sub-agents (`subagent_type: general-purpose`), fresh context each, in a single message with three concurrent tool calls. All sub-agents receive the problem context summary from Step 1 as advisory input (not binding constraints), and all return file:line-referenced findings with no solutions and no code. The trios differ only in their briefs, which cover complementary ground:

**Code-tracing trio** (predominantly source-code scope):

- **Directed sub-agent** (ticket-aware): goal-oriented tracing of code paths, callers, dependencies, and precedents the work will touch.
- **Subsystem sub-agent** (ticket-blind): factual inventory of the subsystem going deeper than Step 1's lightweight scan — full data-structure and invariant mapping.
- **Intermediary/Mutation Finder sub-agent** (ticket-aware): traces data transformations, runtime mutations, and intermediary logic between producers and consumers.

**Prose/governance trio** (predominantly governance/prose scope):

- **Directed sub-agent** (ticket-aware): goal-oriented tracing of the rules, citations, and anchors the change touches, plus precedents — which sections, headings, and cross-file references the work will modify and what already does something similar.
- **Consistency/Duplication-finder sub-agent** (ticket-blind): factual inventory of cross-file restatement and single-sourcing — where the same rule is duplicated rather than cited, single-sourcing violations, and orphaned or colliding citations (anchors referenced by name that no longer match, or two sources claiming to be canonical).
- **Citation/Caller-impact sub-agent** (ticket-aware): traces blast radius — which callers and anchors break if a section is renamed, moved, or removed; who cites the touched sections by name and would desync.

All trios return file:line-referenced findings. **Record the selected set + the one-line rationale** (which signals drove the classification, or that the user was asked on an ambiguous scope) in Step 3's Discovery item 4, reusing the same note convention that already records the greenfield / inline-override Step 1.5 skips (e.g. "Step 1.5 dispatched the prose/governance trio — in-scope files were predominantly `shared/skills/**` governance prose"). Sub-agent prose is absorbed into the orchestrator's context and distilled into Step 3's 9-item Discovery summary (especially items 4 "Existing patterns & constraints" and 5 "Risks & mitigations"). **The raw sub-agent reports are never written to the project file** — only the distilled Discovery summary is persisted, via Step 3's `## Exploration Discovery` section; the `/qplan` handoff contract is unchanged. If any two sub-agent reports contradict on facts, surface the conflict explicitly in Discovery item 5 ("Risks & mitigations") or item 7 ("Open items") rather than silently reconciling or picking a winner.

**Model choice.** Before dispatch, state which model the trio runs on. Where the harness lets you choose, offer a cheaper model as an option, since the trio is read-only, and ask it together with the trio choice when you ask one. A memory entry recording the user's routing settles it without asking.

**Run the probe gate now, not after forming questions.** Execute every read-only item on each report's decidable-by-probe list before Step 2 drafts a single question; Step 2's **Probe gate** states the rule and its validity conditions.

If sub-agent dispatch fails, follow `shared/skills/qreview/SKILL.md`'s **Sub-agent unavailability gate** — hard stop, user decision required (Retry / Skip / Abort). Partial failure (any sub-agent errors or returns malformed output, even if the other two succeed) counts as dispatch failure for this purpose; do not proceed with incomplete findings — route to the gate. Do not unilaterally degrade to Step 1's in-context analysis alone; the gate's Skip option requires explicit user approval.

**User-directed inline override** (distinct from the unavailability gate): if the user explicitly instructs inline / no-subagent exploration, the orchestrator MAY degrade Step 1.5 to in-context analysis without routing through the Sub-agent unavailability gate above. This is a deliberate user choice, not a dispatch failure — record it in Step 3's Discovery item 4 as "Step 1.5 run inline at user request (no sub-agent dispatch)". The distinction: the unavailability gate governs the case where dispatch is *attempted and fails* (Skip requires explicit approval); this override governs the case where dispatch is *intentionally not attempted* per the user's instruction.

The bugfix-detection check in Step 2 fires after Step 1.5 completes — bugfix mode does not skip Step 1.5.

> **Citation convention**: curly-brace `{token}` markers in the briefs are runtime substitution placeholders filled by the orchestrator before dispatch. See `shared/AGENTS.md § SKILL.md Authoring` for the canonical marker convention.

### Sub-agent report contract

Every brief ends with this same reporting contract. Sub-agents cannot follow citations, so **when dispatching any brief, append the Sub-agent report contract block verbatim to the brief** rather than pointing at this section:

```
Distinguish claims grounded in the repo (cite file:line) from claims about external-system behavior (third-party APIs, services, host IDE) — label the latter `[unverified]` so the orchestrator does not treat a hedge as a fact.
Then split that set: return a short **decidable-by-probe** list naming the questions a single command or short script would settle, separately from the ones that stay genuinely open. You cannot execute anything; the orchestrator can, and it runs them before the interview. Without the split, a question worth ninety seconds of measurement arrives as a paragraph of hedging and is carried into the plan as an assumption.
```

#### Trio briefs

The briefs live beside this file, one file per trio. Read only the selected trio's file: `briefs-code.md` for the code-tracing trio, `briefs-prose.md` for the prose/governance trio. Send each brief verbatim with its placeholders filled (`{archive_root}`: the archive `done/` under the resolved project-file root) and the Sub-agent report contract block above appended.

### Step 2: Interview

**Governance check** (greenfield, or whenever Step 1 did not already do it): read the project's governance files (`AGENTS.md`, `CLAUDE.md`, or equivalent) for architectural or product principles that will inform intent capture and design decisions.

**Step 1.5 outputs**: if Step 1.5 ran, the selected trio's three reports are now in your context (what each covers is listed under Step 1.5). Cite specific sub-agent findings by `file:line` in your interview questions (e.g., for the code trio "the mutation-finder report identifies a runtime config transformation at `<file>:<line>` — is this intentional, or should the new feature bypass it?"; for the prose trio "the citation/caller-impact report shows `<file>:<line>` cites this section by name — should the rename carry a coordinated update there?") rather than re-deriving them. When a prior decision the directed report lists would be reversed by this work, say so with the plan's filename at the related question.

**Probe gate — run the decidable-by-probe list before asking anything.** Each Step 1.5 brief instructs its sub-agent to split its open questions into a **decidable-by-probe** list and a genuinely-open list, on the stated grounds that "the orchestrator can, and it runs them before the interview." Perform it here: before forming a single question, run every probe on those lists that is read-only and available, and fold the results into the interview.

This is the runtime analogue of the mandatory dispatch gate. Sub-agents read code; they cannot observe behaviour, so every runtime claim they return is necessarily `[unverified]`. **When the reported symptom is itself runtime-observable — a latency, a cadence, a throughput, a "feels wrong" — a static trio can produce a confident and entirely wrong lead hypothesis.** A probe that is side-effecting (starting a service, hitting a live feed, writing config) still requires the user's consent per `shared/AGENTS.md`; ask for it, naming what the measurement would settle and what it costs. Record falsified hypotheses explicitly in Step 3's Discovery — a hypothesis the probe killed is a finding, and the next session must not re-derive it.

**Probe validity — six conditions.** A probe that fails one of them returns a confident wrong answer, which is worse than running no probe at all.

- **State the measurement assumption beside the result.** A probe measures what its command measures, not what you meant. A format-specific `^### ` regex counted a native-format memory file as 0 entries and put that number in front of a user decision. Say what the number counts at the moment you report it.
- **A negative claim must exercise the live path.** "No change needed" has to come from running the code path the claim is about. A `--dry-run` is insufficient by construction for any behaviour that happens after the dry run exits; citing one produced a wrong load-bearing claim in a committed plan, which then propagated into a sub-agent's enumeration.
- **State the invocation mode, and control for it.** A harness can load a different context non-interactively than interactively — `kiro-cli --no-interactive` drops `memory/**` resources while keeping steering — so a probe of a harness's own context can measure a session the user will never have. Report the mode alongside the result, and run an interactive control before quoting a non-interactive result.
- **A claim from a sample states its sample.** A record shape, count or rule measured on a subset is recorded in Discovery with its label (`sampled (n=…)` or `full scan`) and the strata it covered (versions, eras, sources). When the data has versions or eras, sample each one before recording a shape. A store sampled on its newest versions gave three wrong assumptions that the user had already confirmed, and a five-file sample became a confirmed decision that a full scan of 509 files disproved.
- **Cross-check a count taken through a proxy.** When a count reaches its class through a proxy field (a filename pattern, a `source` value, one log), check it against the field that defines the class, or a second source, before you show it. A token share measured through a proxy read 2% when the true figure was 40%.
- **A history claim states whether the clone is shallow.** On a shallow clone (`git rev-parse --is-shallow-repository` prints `true`), `git log -S` and reachability probes return a wrong first appearance or call a reachable commit unreachable. Unshallow first, or report the clone depth beside the result. An 84-commit clone dated a field's origin wrong and reported a reachable commit as missing.

**Exploration depth**: Establish the depth level before interviewing — see
`shared/skills/qexplore/shared.md § Exploration depth`. Default to **medium**
(today's behavior); honor any level the user specified; otherwise recommend one
from stakes and state it. The level governs how the pre-summary self-audit below
is run and how many assumptions land in the Step 3 ledger; it does NOT affect
the mandatory dispatch gate or Step 1.5 research.

**Bugfix detection**: see `shared/skills/qplan/TEMPLATES.md` `## Bugfix Invariants Format` `### Detection rule`. Apply verbatim if a bug fix is suspected.

**Probing order**: depth-first within each thread, but choose the next thread by impact:

1. Decisions that change the fundamental approach (Design space, Data model, Migration & rollout)
2. Decisions that affect scope (Functional scope, Domain concepts, Integration points)
3. Decisions that affect details (UX flow, Edge cases, Quality attributes)
4. Decisions that affect process (External dependencies, Build & distribution, Testing strategy, Cost impact, Constraints, Terminology, Completion signals)

Do not ask about edge cases or quality attributes until the fundamental approach is settled.

**Per-question discipline**: follow `shared/skills/qexplore/shared.md` throughout. The shared file governs question shape, answer recommendations, disagreement triggers, and convergence.

**Question numbering**: see `shared/skills/qexplore/shared.md` `## Question numbering`. Reference questions by the walk's decision-unit label (default `Q`-number) in summaries and decisions.

**Quality bar**: each question must change the implementation approach if answered differently. Purely informational items (terminology clarifications, naming preferences) belong in a single batched verification list at the end, not as standalone questions.

**Evidence scaffolding** (opening question of each thread only — follow-ups within a thread don't need this):

- **Codebase evidence**: "I see [pattern] in [file:line]. This suggests [implication]. Is that correct, or should the new feature handle this differently?"
- **Absence evidence**: "I looked for [concept] in [files] and didn't find it. Does this mean [assumption], or is it handled elsewhere?"

When multiple valid approaches exist, present options with trade-offs (in addition to the recommended resolution per `shared.md`).

**Follow-up behavior**:

- When the user gives a vague or one-line answer, ask a specific follow-up that probes for concrete details (e.g., "You said 'standard auth' — do you mean session-based, JWT, or OAuth? Which provider?")
- Do not accept "TBD" or "we'll figure it out later" for categories that would affect the implementation approach. Push back with: "This will affect [X]. Can we decide now, or should we flag it as a risk?"
- Challenge stated assumptions that conflict with codebase evidence. If the user says "this is simple" but the code shows complexity, say so with file:line references.
- When codebase evidence from Step 1/1.5 shows that a user-stated requirement is already satisfied by existing code, surface the existing mechanism with file:line references and treat the covered behavior as a preservation constraint (it must not regress). If only partially satisfied, narrow the scope to the uncovered gap and treat the covered portion as a preservation constraint.
- When a feature involves building a system with its own internal design (DSL, plugin architecture, rule engine, workflow engine, template system), decompose it into sub-decisions and ask about each one separately. Do not accept a single high-level answer for a feature that contains multiple orthogonal design choices.
- When the user's answer to one question implies a follow-up trade-off, ask about it immediately rather than moving to the next thread.
- If the user says "proceed", "enough", or "just plan it", summarize what's been covered and flag remaining gaps as Open Items. Do not push for more rounds.

Iterate until the conversation reaches convergence per `shared.md`'s convergence test.

#### Pre-summary self-audit

Before producing the summary in Step 3, audit your conversation against the categories below. How thoroughly each category is resolved depends on the active depth level
(`shared/skills/qexplore/shared.md § Exploration depth`): at **high**, every category is confirmed with
the user; at **medium**, ask the approach-changing gaps and default the rest; at
**minimal**, ask only categories caught by the safety floor and resolve the rest
by stated assumption recorded in the Step 3 ledger. The safety-floor predicate,
ledger, and convergence/oscillation behavior are defined in
`shared/skills/qexplore/shared.md § Exploration depth` — do not restate them here.

For each category: (a) confirm it's resolved by the discussion or codebase analysis, (b) ask one final question if a gap remains, or (c) at depths below high, record a stated assumption in the Step 3 ledger (per `shared/skills/qexplore/shared.md` § Exploration depth).

| Category | What to check |
|---|---|
| **Design space** | Are there fundamental architectural choices (e.g., language design, storage format, execution model, framework selection) where multiple valid approaches exist? For each, identify at least 2 options with concrete trade-offs before asking the user to choose. |
| **Data model** | Are entities, relationships, and storage needs clear? Any schema changes? |
| **Migration & rollout** | Does this feature replace or change existing behavior? If so, what is the migration strategy (big bang, incremental, shadow/parallel)? Is backward compatibility required? What is the rollback plan? |
| **Functional scope** | Are inputs, outputs, and core behaviors fully defined? What is explicitly out of scope? |
| **Domain concepts** | What domain-specific concepts does this feature introduce or formalize? Are there implicit concepts in the current code that should become explicit (e.g., lookup tables, state machines, evaluation pipelines, entity lifecycles)? |
| **Integration points** | Are external APIs, services, or internal module boundaries identified? |
| **Pre-existing assumptions** | Does this feature depend on anything already in the system — config fields, UI inputs, validation rules, route guards, data defaults — being present *and sufficient* for the new behavior? For each implicit dependency outside this feature's scope, verify it is actually guaranteed by the system, not just assumed to exist. **Provider/IDE-level constraints**: when the work touches a provider-specific skill or steering file (e.g., `providers/kiro/`, `providers/<other>/`), explicitly verify the host IDE's documented capabilities before designing — does the IDE auto-load the file? does it support nested directories? does it expose the hooks/events the design assumes? Do not infer capabilities from analogous IDEs. **External-system contracts**: apply the same verify-or-flag discipline to assumptions about how an external system behaves, including the documented size and format limits on any payload it carries (a hook's output, a loaded resource, an import), per `shared/skills/qexplore/shared.md` § Convergence test (item 3) — verify with a read-only probe or treat as unverified; never assert from documentation, analogy, or a sub-agent's hedged claim. |
| **UX flow** | Are user-facing interactions and state transitions specified? |
| **Edge cases** | Are boundary conditions, empty states, and failure modes covered? |
| **Quality attributes** | Are performance, security, accessibility, and reliability requirements stated? |
| **Build & distribution** | Does this feature introduce or depend on non-code runtime artifacts (data files, templates, static assets, native binaries) that must be included in the project's build or distribution pipeline? First: identify whether such artifacts exist. Then: identify the project's bundling mechanism (e.g., PyInstaller .spec, webpack config, pyproject.toml `package_data`/`MANIFEST.in`, Cargo.toml, .nuspec, electron-builder config) and confirm whether it has been updated to include the new artifacts. Containerized builds (Docker) use explicit COPY/ADD and are lower-risk but still worth confirming. |
| **Testing strategy** | How will this feature be verified during `/qdev`? Identify: (a) what test types apply (unit, integration, end-to-end, browser, manual), (b) whether the live/production environment can or should be used for verification, (c) what test infrastructure or fixtures are needed (environment access belongs to item 9, QA environment). The answers inform `/qplan`'s per-phase exit criteria and Verification section, and `/qdev`'s per-phase test execution. If the testing approach is fully unknown (e.g., greenfield with no test infra), record as an Open Item for `/qplan` to resolve — do not block exploration convergence on this category. |
| **External dependencies** | Does this feature require infrastructure, CI/CD, IAM, cloud resource, DNS, or third-party service changes? What manual actions must someone perform outside the codebase? |
| **Cost impact** | Does this feature change hosting, compute, API call volume, storage, or licensing costs? What is the estimated magnitude? |
| **Constraints** | Are technology, compatibility, and regulatory constraints explicit? If the feature implements a formal standard or compliance framework (e.g., e-invoicing profiles, WCAG, GDPR, OAuth specs), enumerate every mandatory element by name or code — referencing the standard by profile name alone is insufficient. |
| **Hardware/physical constraints** | Does this feature interact with hardware, radio, or physical-layer resources (BLE radio scheduling, GPIO, DMA, shared buses)? Are there single-resource contention issues, timing constraints, or vendor-SDK limitations that constrain the design space? For embedded/IoT projects, this often dominates architectural decisions. |
| **Terminology** | Are domain terms used consistently and unambiguously? If the project's `AGENTS.md`/`CLAUDE.md` defines a `## Terminology` section, verify session terms against it and flag mismatches as Open Items — following the pointer first when the section names a glossary file, and skipping this audit when the section's body is a decline note (that is a waiver, not a term list). Independently of whether a section exists: whenever the interview settles a term specific enough to this project that a future session would otherwise re-litigate it, record it with its rejected synonyms in Discovery item 6 (resolved decisions) for `/qplan`'s Terminology bootstrap. General programming vocabulary does not qualify. This skill records only — it never writes the section or glossary file itself (see the Process gate). |
| **Completion signals** | How will we know this feature is "done"? What are the acceptance criteria? If regulatory compliance is in scope, acceptance criteria must include an external validation step (e.g., running a validator tool against the output). |
| **Scenario coverage** | Does the recommended approach handle every concrete scenario or concern the user raised during the conversation? List each user-raised scenario, confirm it's addressed by the design, or flag it as an open gap. Pay special attention to scenarios that were reframed into more abstract terms — verify the abstraction covers the original concrete case. |

**Assumptions checkpoint (before handoff).** This is the end-of-interview disclosure mandated by `shared/skills/qexplore/shared.md` § Convergence test (item 3), and it is the single in-chat veto surface — the consequence-significant assumptions lead; the depth-driven Assumptions (unconfirmed) ledger (`shared/skills/qexplore/shared.md` § Exploration depth), if any, follows here rather than as a separate surfacing. It fires at every exploration depth level — minimal depth reduces interview questions, not this disclosure gate. Present it, then **end your turn and wait for the user's response — do not write any summary or take any persistence path (Step 3 write, Trivial exit, greenfield summary, re-plan-in-place Intent update, decomposition writes) in the same message.**

- Lead with the **consequence-significant** assumptions, each with its falsification result (survived / reopened). Derive them from the design: for each data structure, contract/module boundary, and pipeline stage the work touches (or the non-code equivalents in item 3), state the assumption you are making about it. Compress minor assumptions into a single batched line (or "none").
- Fold the surfaced convergence top-3 uncertainties in here rather than as a separate message. Present codebase-vs-intent tensions and open ambiguities inline here (the checkpoint runs before Step 3, so there is nothing yet to point at); they will then be recorded in Step 3's Risks (item 5) and Open items (item 7) — no need to re-derive them there. On the Trivial exit, which skips Step 3, this checkpoint is their only in-chat home.
- Note anything intentionally deferred and the trigger that would reopen it.
- If the user challenges an assumption, reopen the relevant Step 2 thread and re-run its falsification before proceeding.
- **User-stop precedence**: if the user has said "proceed / enough / just plan it," surface this checkpoint once as a non-blocking disclosure (treat the stop as implicit acceptance) — do not trap them in another round.

**Post-interview Trivial convergence**: If the pre-summary self-audit confirms the converged scope meets the Trivial-tier criteria of `/qplan` Step 1, terminate exploration here and tell the user:

> Interview complete. Scope has converged to Trivial. Run `/qplan <description>` to produce an inline plan directly.

Skip Step 3 entirely. **Ledger carry-over**: if the active exploration depth left a non-empty Assumptions (unconfirmed) ledger (see `shared/skills/qexplore/shared.md § Exploration depth`), the assumptions checkpoint above already surfaced it for veto; carry the un-vetoed assumptions into the inline `/qplan` handoff — Trivial convergence skips Step 3, so the ledger has no project file to land in and must travel with the verbal handoff instead of being dropped.

### Step 3: Capture

**Re-test the tier first.** Before announcing that you will write the project file, state in one line whether the file and `/qplan` are still warranted for the scope that converged in Step 2, name the deciding factor (uncommitted work in the tree, file count, whether a separate `/qdev` session is actually happening), and offer the skip. The Post-interview Trivial convergence exit runs before the assumptions checkpoint, so this is the only re-test at the point scope has actually settled. When the file is skipped, still park deferred items wherever the project keeps follow-ons.

Produce a structured summary with two sections:

**INTENT** (refined by discovery, presented as a clean reviewable section):

1. **Problem statement & desired outcomes** — what problem this solves and what success looks like
2. **Success criteria** — concrete, verifiable conditions for "done"
3. **Scope boundaries & non-goals** — what is explicitly in and out of scope

**DISCOVERY** (evidence from codebase and clarification):

4. **Existing patterns & constraints** — conventions to follow, hard limits (with file:line references where applicable)
5. **Risks & mitigations** — identified risks and proposed mitigations
6. **Resolved decisions** — design questions answered during exploration. Every entry MUST include: the underlying question text (referenced by the walk's decision-unit label `<unit>` — default `Q<n>`; see `shared/skills/qexplore/shared.md` `## Question numbering`), the user's answer (`A`), and the resulting decision (`Decision`). Format per line: `<unit>: <question> — A: <answer> — Decision: <decision>` (e.g. `Q1: …` by default, or `Change-1: …` when the walk is framed around changes). When a later decision supersedes an earlier one, append `Superseded by: <unit>` to the original entry rather than deleting it — this preserves the decision evolution trail. Do not collapse this into a narrative paragraph; the Q→A→Decision provenance must be preserved for `/qplan` to consume downstream.
7. **Open items** — anything still unresolved (if any). Genuine product or technical **decisions** belong in the interview (Step 2), not here — Open Items handed to `/qplan` should be **deterministic** (resolvable by reading code or running a test) or **execution-contingent** (undecidable until partial implementation). `/qplan` resolves the former with judgment but must surface the latter to the user.

**Assumptions (unconfirmed)** *(labelled adjunct — not one of the 9 numbered
sections)* — design points the model resolved by its own assumption (rather
than a user answer) because the active exploration depth was below `high`.
Surface this list in chat for veto AND record it here, kept distinct from Open
Items (assumptions = resolved-by-fiat and vetoable; open items = genuinely
undecided). Empty at high depth. Format per line: the assumed resolution + the
category it covers. `/qplan` consumes it per its Step 2 rule.

8. **Recommended approach** — proposed implementation strategy
9. **QA environment** — what runtime surfaces are testable and how to reach them (startable commands, URLs, test data sources, network access, required hardware/credentials). Start from the project's `### Verification Setup` (`shared/skills/qqa/SKILL.md § Recipe persistence`) when present, and propose adding it when this exploration finds a surface it does not cover.

This summary structure is the **output contract** of the explore skill. Downstream skills (`/qplan`) depend on it. Always produce all 9 numbered sections. Additionally, when the depth level left assumptions unconfirmed (below high), **and at any depth whenever the assumptions checkpoint listed defaults the user did not explicitly confirm**, append the **Assumptions (unconfirmed)** labelled adjunct after Open Items — it is an adjunct, not a 10th section, so the '9-item contract' framing elsewhere stays accurate.

#### Persist intent file (tier-gated)

Write the exploration output — the Intent section, then the transient Discovery section — to a project file. The Post-interview Trivial convergence (Step 2) skips Step 3 entirely, so no file is created in that case. **Light always writes**.

**Re-plan branch (existing-plan target) — evaluate first.** Before the new-file path below, check whether this exploration is re-planning an **existing** plan rather than starting a new one. The branch fires only when BOTH hold: (a) the user framed the work as re-planning a specific existing plan — they named or pointed at a target plan path — AND (b) that target exists and is a full plan (it already contains planning sections, not an Intent-only `/qexplore` handoff — see `/qplan`'s Mode detection for the exact planning-sections test). A user who wants a brand-new plan that supersedes an old one does NOT satisfy (a); do not misroute them. When the branch fires:

1. **Do NOT create a new project file.** Skip the Decomposition check and the new-file steps 1-7 below.
2. **Update the existing Intent in place** if exploration refined the problem statement, success criteria, or scope — edit the target file's `## Intent` section directly. (Intent edits are within this skill's remit; planning-section edits are not — those belong to `/qplan`'s revision sub-flow.)
3. **Persist the resolved decisions** into the target file under a transient section named exactly `## Resolved Decisions (re-plan handoff)`, one line per decision in the `Decisions format` (see `shared/skills/qexplore/shared.md`). This is exploration output, not a planning section — it mirrors the `## Open Design Items` hand-off precedent. `/qplan`'s revision sub-flow folds it into the Design Decisions table and removes it, so it is transient by design. If the section already exists from a prior re-plan pass, **replace its contents** rather than appending a second copy. After writing the resolved decisions, commit the updated file: `docs(<plan-slug>): intent update (re-plan)` (using the existing file's slug). Do not push. If the commit fails, warn the user the updated file remains uncommitted and proceed to step 4.
4. **Report** the existing file path and suggest `/qplan <existing-plan-path>` to continue — `/qplan` detects the existing planning sections and enters its revision sub-flow.

When the branch does NOT fire, proceed with the new-file path below.

**Decomposition check** (before writing): if the Discovery summary contains 3+ Success Criteria with **largely independent file scopes** (no SC's affected files overlap with another SC's affected files), surface the option to the user: "I count N largely-independent SCs. Write one combined project file (single lifecycle, phased plan) or N child files (one per SC, parallel `/qdev` possible), or one project file for the non-trivial SCs only, with the mechanical ones handled directly?" Default to one combined file when in doubt; the user explicitly opts into decomposition. When the user opts for decomposition, write N project files in steps 1-6 below — each carries one SC's intent narrowed to its own scope; do not write a parent file unless the user explicitly asks for an index. **If a later scope deferral (during the same interview) removes or changes an SC the decomposition answer counted**, re-state the answer's status against the revised SC set — confirm it still holds or re-ask — rather than leaving a stale answer standing on a premise that no longer exists.

**Multi-domain priority rule**: when the scope spans 3+ independent domains (distinct subsystems with disjoint file sets), fire the decomposition check as the FIRST question in Step 2's interview — before any other probing. All subsequent questions depend on whether the scope will be split into child files or remain combined. Do not defer decomposition to Step 3 in this case; surface it at the top of Step 2 and record the user's decision before proceeding with the interview.

1. **Path**: governance-driven, then resolved. Read the project's `AGENTS.md` / `CLAUDE.md` for a configured plans path. If governance is silent, resolve the project-file root through `shared/skills/qdream/memory-rules.md § Resolution contract`, artifact class *project files*. The store resolver returns the workspace's store in the store repo; the workspace's own `plans/` is the root only for the config repo and for a folder the resolver creates no store for. Write the file under the resolved root; do not assume a literal `plans/`.

   **No store question.** A new project file goes to the store that `store-resolver.py find-or-create` returns. The first write creates that store at the session folder, **without a prompt**. Pass `--at <folder>` only when the user names another folder. When the answer is none, the file stays in the workspace's own `plans/`; when it fails, write nothing and report the reason.
2. **Filename**: `{YYMMDD}_{UPPER_CASE_SELF_SUFFICIENT_PROJECT_NAME}.md` where `YYMMDD` is today's date. The name must be self-sufficient — someone browsing the directory should understand the project from the filename alone.
3. **Write the intent section** to the file:

   ```markdown
   # <Project Title>

   > **Date**: YYYY-MM-DD
   > **Status**: Exploring  <!-- Status grammar: shared/skills/qplan/TEMPLATES.md § Status Grammar -->
   > **Scope**: <one-line scope>

   ---

   ## Intent

   ### Problem statement & desired outcomes
   <from contract item 1>

   ### Success criteria
   <from contract item 2>

   ### Scope boundaries & non-goals
   <from contract item 3>
   ```

4. **Bugfix invariants** (when bugfix detection ran in Step 2): write the `### Invariants` H3 (Standard tier) or `Invariants:` bullet block (Light tier) in the Intent section per `shared/skills/qplan/TEMPLATES.md` `## Bugfix Invariants Format`. Default to the Standard format (H3 heading + bullets); a downstream `/qplan` invocation that downgrades to Light tier is responsible for converting per `/qplan`'s Preserve-bugfix-Invariants-subsection rule.

5. **Persist the Discovery half**: append a `## Exploration Discovery` section after the Intent section, carrying contract items 4-9 (existing patterns & constraints, risks & mitigations, resolved decisions, open items, recommended approach, QA environment) plus the **Assumptions (unconfirmed)** adjunct when non-empty. Open the section with the literal line `<!-- Transient: /qplan folds these into the planning sections and removes this section. -->` so the contract travels with the artifact rather than living only in this skill file. This is exploration output, not a planning section — it mirrors the `## Resolved Decisions (re-plan handoff)` precedent above and is transient by the same rule. Without it the Discovery half — the more expensive output of a long exploration — survives only in the chat transcript, and only until `/qplan` runs in the same session. (New-file path only; the re-plan branch's `## Resolved Decisions (re-plan handoff)` already carries its exploration output.)

6. **Commit the intent file**: stage the project file and commit using Conventional Commits format `docs(<plan-slug>): intent capture` where `<plan-slug>` is derived from the filename (without `.md`). See `shared/AGENTS.md § Commit Conventions` for the canonical rule. Do not push. This commit is intentionally unpaired (no corresponding `feat` commit) and does not trigger qvalidate's commit-pairing check. If the commit fails (git lock, permissions), warn the user the file remains uncommitted and proceed to the report step. `/qplan` will append planning sections and re-commit regardless. (The previous stop-hook exception is subsumed — always-commit is now the default.)

7. **Report** the file path and suggest `/qplan <file-path>` to continue.

## Rules

Rules that are not stated in a step above:

- **A long session: suggest `/compact` before Step 1.** On Claude Code, run `<python> <config-repo>/shared/skills/qdream/scripts/dream-manifest.py context --orchestrator` first (`<python>` and `<config-repo>`: `shared/skills/qdream/SKILL.md § Interpreter` and `shared/AGENTS.md § Config Repo Locations`; its limit, `ORCHESTRATOR_CONTEXT_LIMIT`, is half of a 1M window, so judge by half of your own window when it differs). On `over limit: yes`, suggest that the user run `/compact` before you start, because every turn re-reads the whole context. When the command cannot run (kiro, no venv), skip the check.
- Do NOT write planning sections to a project file — that is `/qplan`'s responsibility. Writing the Intent section and the transient `## Exploration Discovery` section (Step 3) is allowed.
- Apply the **Harness Improvement Capture** rule in `shared/AGENTS.md` — append friction observations (steps that didn't fit, ambiguous gates, missing categories, awkward conventions) to the project file's `## Harness Improvement Opportunities` section as you encounter them.
- Apply the **Council-Enriched Escalation** rule in `shared/AGENTS.md` when escalating design trade-offs to the user.
