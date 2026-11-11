---
name: qdev
description: Execute implementation phases from a plan with built-in review after each phase. Auto-continues through phases when healthy, stops on blockers. Supports file-based and inline plans. Dispatches parallel sub-agents for [P:N] phases. Use after /qplan produces a plan, or to resume execution of an in-progress plan.
argument-hint: "<path to project file> [optional: phase numbers, e.g. 1 or 1 to 3]"
---

# Development

## Your role

Execute implementation phases from a plan, review after each phase, and auto-continue through phases when healthy. Stop at blockers that require user decisions or manual actions.

## Input

$ARGUMENTS

## Process

### Step 1: Read the plan

Read the project file thoroughly. If the project file contains an Intent section, read it to understand the problem being solved, success criteria, and scope boundaries. Use this context to inform implementation decisions — especially when encountering ambiguity or undocumented edge cases where understanding the original intent helps choose the right approach. Do not modify the Intent section. If the Intent section appears to conflict with the plan's phases or design decisions, STOP and flag the inconsistency to the user. Wait for resolution before beginning implementation.

**Compute `<plan-slug>` at session start**: Derive `<plan-slug>` from the plan path immediately — it is the plan filename in `plans/<filename>.md` (or `plans/done/<filename>.md`) without the `.md` extension (e.g., `260514_REVIEW_LAZY_AGENT_ASSUMPTION`). Pass this literal slug value into every sub-agent brief (Step 4 implementation, Step 6 auto-fix re-spawn) and use it as the Conventional Commits scope in every plan-context commit message (sub-agent code commits, orchestrator plan commits, Step 9 final-fix commit). qvalidate's `commit-pairing` check derives the same slug from the plan filename to pair `feat`/`docs` phase commits, so keep these commit scopes consistent with it. The canonical rule lives in `shared/AGENTS.md § Commit Conventions`. **For inline plans (no project file at all)**, `<plan-slug>` is undefined — use the inline-only format `feat(phase-N): ...` instead. **Resolve the project-file root before deriving the slug** — `shared/skills/qdream/memory-rules.md § Resolution contract`, artifact class *project files*. The root may be the workspace's own `plans/` or the `plans/` of its store in the store repo. The slug is derived from the **filename** either way, so a store-backed project file produces the same slug as an in-workspace one.

If `$ARGUMENTS` refers to an inline plan from a Trivial-tier `/qplan` session (no file), use the inline plan from the conversation context. Identify:
- Which phases to execute (default: next incomplete phase)
- Exit criteria for each phase
- Dependencies between phases

**All-phases-complete fast path**: If every phase in the plan is already marked complete (all tasks `[x]`), skip Steps 2-8 and go directly to **Step 9 (Final review)**. This is the primary use case for invoking `/qdev` on a finished plan — the user wants a thorough holistic review. A previous review log entry does not exempt from a fresh Step 9 run.

**Handoff ingestion**: If the project file contains a `## Handoff` section, **or** a standalone `.handoff-*.md` file exists directly under the resolved project-file root (`shared/skills/qdream/memory-rules.md § Resolution contract`; the workspace's own `plans/` only in a no-create folder) — see `shared/skills/qhandoff/SKILL.md § Step 5` standalone mode; if more than one matches, use the most recent by filename date:

**Precedence when both exist**: process the in-plan `## Handoff` section per the steps below; a standalone file **that passes the plan-affinity check below** is superseded — delete it (Step 4) without separately ingesting it (Steps 1-3), to avoid double-processing the same carried-over state. A standalone file naming a *different* plan is outside this precedence rule entirely — the affinity check governs it: left untouched, never deleted as superseded.

**Plan-affinity check (standalone file only)**: before ingesting a standalone file, confirm it belongs to this plan — its header (`# Handoff — <plan title or "ad-hoc session">`) or its `### Current` "Suggested next" line names this plan's filename or title, or the header says "ad-hoc session" and no other in-progress plan is a closer match. If it clearly names a *different* plan, do NOT ingest or delete it — inform the user: "Found `<path>` — appears to belong to `<other plan>`, not this plan; left untouched." and skip the remaining steps for that file.

1. Read it first — use it to orient on current state, parked threads, and suggested next steps.
2. Compare the handoff timestamp (`> Handoff written: <ISO-8601>`) against the most recent implementation log entry timestamp (the `Implementation (YYYY-MM-DD, code: ...)` heading in the last completed phase). If the log entry is newer, the handoff is stale — treat as background context only (the implementation log is the source of truth for current state). **Same-day tie**: if the two dates are equal, compare times instead of dates. The log heading carries a date only, so take the log entry's time from the committer time (ISO-8601) of the commit that added that heading (`git log --format=%cI -S"<heading>" --reverse -- <project-file>`, first line). If the handoff's `Handoff written` time is later than that, the handoff was written after the last logged work: treat it as current (a handoff written just before a user-requested `/compact` is the case this covers). If the handoff's time is equal or earlier, or either time cannot be determined (no commit, no time component), treat the handoff as stale (tie goes to stale) and orient from the project file's implementation log instead.
3. Before removing the section or file, carry forward any `### Parked` items not being actioned this session: append them as a `Carried forward from handoff:` bullet list into the project file's implementation log — this session's next implementation notes entry (Step 7 item 2), or, if no further phase executes this session, directly under the plan's most recent existing implementation log heading. The log is the declared source of truth; the removal below would otherwise be the only place these items were recorded. **Duplicate guard**: if a `Carried forward from handoff:` block already exists in this session's implementation log entry (e.g., from a prior failed removal retry), do not append a second one — the existing block already covers this handoff's Parked items.
4. Remove the `## Handoff` section from the project file atomically (delete the entire section from `## Handoff` through the next `##` heading or EOF); for a standalone `.handoff-*.md` file under the resolved project-file root, delete the file instead. If removal fails, warn the user and continue — do not block execution.
5. Emit a one-line confirmation: "Handoff ingested and removed" (or "Handoff stale — treated as background context, removed").

**Stale-plan check**: After reading the plan, spot-check 2-3 concrete codebase references (file paths, function/class names, or file:line refs) from the plan's Current State or phase descriptions against the actual codebase. If the referenced code has materially changed (logic, signature, or structure — not formatting or comment-only edits), inform the user and suggest re-running `/qplan <path>` to revise before continuing. Do not silently execute a plan whose assumptions no longer hold. Skip this check if the project file's last commit is less than 2 hours old (verify via `git log -1 --format=%ct -- <plan-path>`).

**Remote-divergence check**: After the stale-plan check, `git fetch` and check whether any file in the plan's scope was modified on `origin` since the plan's base commit (`git diff --stat <plan-base>..origin/<branch> -- <plan-scope-files>`). If so, warn the user that the remote has diverged on files this plan edits — a rebase plus a **coherence review** (a conflict-free merge does not guarantee semantic coherence when two efforts edit the same hooks) may be needed before execution, and is especially important before a deploy-terminal phase, where late discovery forces a mid-deploy reconciliation. Skip when there is no remote or the plan-scope files are untouched on `origin`.

**Parallel group detection**: After identifying pending phases, scan phase headings for `[P:N]` annotations (detection regex: `\[P:[\d,]+\]`; extraction regex: `\[P:([\d,]+)\]`). Form parallel groups:
- A parallel group is the maximal set of phases that mutually reference each other via `[P:N]` annotations
- Validation: run qvalidate's `parallel-symmetry` check against the plan (run `shared/skills/qvalidate/scripts/qvalidate.py` with the playbook venv, per `shared/skills/qvalidate/SKILL.md` — never re-implement the checks inline) — it FAILs when any phase in a `[P:N]` group does not reciprocally annotate all its partners, or names a partner phase that does not exist. Handle a FAIL per `shared/skills/qvalidate/SKILL.md § Failure semantics`.
- If all partners in a group are already complete except one, that one executes solo (no parallel dispatch). On session resume, re-detect group membership — completed partners are excluded; remaining phases execute solo or as a smaller parallel group
- If the user specified particular phase numbers (`/qdev plan.md 3`), execute only those — ignore `[P:N]` for phases not in the user's request
- For parallel groups, the atomicity guard checks for MULTIPLE unpaired code commits: run qvalidate's `commit-pairing` check (`--check-commits`; see `shared/skills/qvalidate/SKILL.md`), which flags any phase **code** commit — `feat`, `fix`, `refactor` or another permitted type, per `shared/skills/qvalidate/SKILL.md` — that has no paired `docs(<slug>): …phase N` commit across every phase (the script derives the slug from the plan filename). If any phase has a code commit without a paired plan commit, apply Step 7 for all such orphaned phases in phase-number order before proceeding — this reconciliation is the sanctioned response to `commit-pairing`'s FAIL at this site (see the atomicity carve-out in `shared/skills/qvalidate/SKILL.md § Failure semantics`), not the halt-and-user-decide default; fall back to that default only if the reconciliation cannot proceed cleanly.

**Interruption and recovery**: before starting a phase (candidate orphaned work) and after every sub-agent return (a dirty tree mid-execution) — see `### Interruption and recovery reference`.

### Interruption and recovery reference

Two checks run every time; the full scenario table, with what to do in each case, is in `recovery.md` alongside this file. Read it whenever either check fires or Step 4 points to it.

- **Before starting a phase**: run `git status --short`. Uncommitted changes in a pending phase's file scope are candidate orphaned work from an interrupted session: never commit them, and never assume the phase is done because its edits are present.
- **After every sub-agent return** (implementation, review, QA or doc-impact): run `git status --short`. Changes to files outside the current phase's file scope mean STOP and show the user the file list. Never discard, stage, or treat them as noise; they may be another agent's work.

### Step 2: Analyze prior review findings

Check the plan's review log section for entries from previously completed phases. If review entries exist:

1. Read every finding regardless of severity
2. For each finding, decide whether it is **valid** (should be addressed) or **not applicable** (incorrect, outdated, or irrelevant to the current state of the code)
3. Update the review log table inline -- fill in the **Resolution** column for each finding with a brief note: for valid findings, whether and when it will be addressed; for not-applicable findings, a short explanation of why
4. Summarize to the user: which findings you will address and which you are dismissing with rationale

Address valid findings during the implementation step (Step 4) alongside the phase's planned work. Skip this step for inline plans with no review log.

### Step 3: Verify prerequisites

Before starting a phase:
- Check that all prerequisite phases are marked complete
- Verify the codebase matches the plan's current-state assumptions
- Check the plan's "External Dependencies & Costs" section. If the current phase depends on any external prerequisite (cloud resources, IAM, CI/CD, secrets, DNS, third-party services), ask the user to confirm each is in place before proceeding. Do NOT assume they are done.
- If the work changes persisted data layout, cloud resources, or operator-managed rollout steps, verify the plan includes explicit migration/cutover/cleanup phases. If that operational work exists only in notes or assumptions, STOP and revise the plan before continuing.
- If prerequisites are not met, STOP and inform the user

**Partial execution (agent half, user half)**: a pre-flight phase is routinely part agent-runnable and part user-run, and the gate above is all-or-nothing. When the unmet prerequisites belong only to the user's half, do not stop the whole phase. Run the agent-side items, tick only their exit criteria, record a progress entry naming the user-side items still outstanding, and stop there — do not enter Steps 5-8 for a phase that is not finished. Commit the plan update as `docs(<plan-slug>): partial progress, user half pending`, naming the phase in the commit body and **not** in the subject line — `commit-pairing` reads `phase N` out of any `docs(<slug>)` subject, so a subject that names the phase would pair the phase early and disarm the atomicity guard for the real code commit that lands later. Re-enter the phase at this step when the user reports their half done.

**Parallel group prerequisites**: When a parallel group is next, verify prerequisites for ALL phases in the group. If any phase's prerequisites are unmet, the entire group waits.

### Step 4: Implement the phase

**Orchestrator defined**: throughout this step and subsequent steps, "orchestrator" means the `/qdev` session invoked by the user — the outer context that reads the plan, dispatches sub-agents, updates the project file, and commits project-file-only changes. "Implementation sub-agent" means the fresh-context agent spawned in Step 4 (or re-spawned in Step 6) to execute one phase's code changes. "Review sub-agent" means the persona-scoped review agents from Step 5.

**For Light tier plans and inline plans**: Implement in-session — execute the plan's instructions directly, write/update tests alongside the changes (applying the Test-writing nudges below), run verification commands, and document divergences inline. No sub-agent is spawned.

**For Standard and Major tier plans**: Delegate implementation to a **fresh-context sub-agent** (`subagent_type: general-purpose`). The sub-agent has no conversation history and no assumptions carried from this orchestrator session — this isolates implementation context so later phases do not inherit rot from earlier ones.

Spawn the sub-agent with this brief (all required):
- The project file path and the target phase number
- Paths to governance files (`AGENTS.md`, `CLAUDE.md`) with instruction to read them before starting, including any `## Doc & Test Guidelines` subsection that defines per-project doc/test policy
- The Test-writing nudges below, verbatim, when the phase adds or changes executable code
- Authority to: (a) make the code changes, (b) run tests/verification, (c) tick exit criteria in the project file as work completes (per the Step 4 "Exit-criteria ticking" rule) — this ticking edits the project file, but the sub-agent does NOT stage or commit the project file; the orchestrator commits project-file changes separately in Step 7, (d) stage and commit the implementation using Conventional Commits format `feat(<plan-slug>): phase N — <description>` (or another appropriate type such as `fix`/`refactor`) using the `<plan-slug>` computed at Step 1; see `shared/AGENTS.md § Commit Conventions` for the canonical rule and the inline-only carve-out, (e) return control with a structured status report. **Standard/Major commit shape (mandatory)**: stage ONLY the implementation files in this commit (the project-file ticks from grant (c) are committed separately by the orchestrator per Step 7.8). **Light tier with a project file**: same two-commit shape as Standard/Major (sub-agent code commit + orchestrator plan commit, both using `<plan-slug>` as scope). **Truly inline plans (no project file at all)**: commit implementation + plan together in a single commit using the inline-only format `feat(phase-N): ...`. Instruct the sub-agent to NOT push. **Brief-wording hazard**: when writing a "Commit mechanics" section elsewhere in the same brief, do not use colloquial shorthand like "do not touch the plan/project file" — it reads as contradicting grant (c)'s edit authority and can lead a sub-agent to withhold edits entirely, deferring exit-criteria ticks to the orchestrator instead. State precisely what grant (c) already says: the sub-agent may edit the project file to tick criteria, but must not stage or commit it. If a sub-agent's return discloses it read an ambiguous brief this way and deferred edits (e.g., returning a tick-list for transcription instead of ticking directly), treat that transcription as an immediate, same-turn Step 7 action — not a deferred one.

**Label every fact in the brief with how it was measured** — `sampled (n=1)`, `full scan`, `read from docs`, `assumed`. A brief that states a measured fact flat invites the sub-agent to build on it without re-checking. The label tells the sub-agent which facts to re-check and which it may trust.

**Test-writing nudges** (phases that add or change executable code — applied in-session on the Light/inline path, carried verbatim in the Standard/Major brief):
- Before implementing, name the one to three places a subtle bug is most likely. For each, write a check that fails on a plausible wrong implementation: asymmetric inputs (never identical or palindromic ones) and both sides of each boundary.
- Take expected values from the spec or an independent derivation, never from running the code under test.
- **List the guards you mutated.** When you mutation-test your own checks, name in `tests.detail` each guard you mutated and whether its test failed. A summary such as "all mutants caught" is not coverage: the Step 5 reviewer mutates the guards your list leaves out.
- When randomizing, generate valid, structured inputs that reach deep code paths, and assert properties of the output. A no-crash check is not a correctness check.
- **Justify every changed test expectation.** When a failing test is made to pass by editing its expected value rather than the code, cite the spec or source that proves the old expectation wrong. Without one, leave the test unchanged and record it as a `divergences` entry (in-session: in the implementation notes); the orchestrator escalates it. Agents iterating until their own tests passed wrote more tests enforcing incorrect behaviour (danluu.com/agentic-testing, codex GPT-5.6, Rust Zstd eval, 160 runs per condition, 2026-09).
- **Never reach green by attrition.** Do not add a retry, raise a timeout or skip a test just to make it pass. A raised timeout needs a cited measurement or spec. A flaky test is fixed at its cause; deleting it instead is a `divergences` entry naming the coverage lost. A legitimate skip names the missing capability, never only a platform ("Windows" is no reason; "no execute bit to set" is).
- **Make negative and acceptance checks able to fail.** A "nothing happens" assertion needs a seeded control that would trigger it. A check for new or changed behaviour must fail on the code before the change, and an import or compile error does not count as that failure.

**Sub-agent return transport format**: the sub-agent MUST return a single response containing two clearly-delimited surfaces in order:

1. A fenced JSON block (`` ```json ... ``` ``) holding the structured fields below. This is machine-parsed by the orchestrator.
2. A prose section under the heading `## Change description` containing the free-form `change_description` paragraph. This is pasted verbatim by the orchestrator into implementation notes (see Step 7).

Any content outside these two surfaces is ignored. If the JSON block is missing, malformed, or missing required fields, the orchestrator halts and treats it as a blocked phase pending re-spawn. A missing optional field never halts.

**Sub-agent structured fields** (all required in the JSON block, except the one marked optional):
- `status`: `completed` | `blocked`
- `exit_criteria_ticked`: integer count of `- [x]` boxes the sub-agent ticked during this phase
- `exit_criteria_deferred`: list of `{criterion, target_phase, reason}` (empty if none)
- `divergences`: list of `{summary, rationale}` (empty if none)
- `tests`: `pass` | `fail` | `not_run`, with a `detail` string (brief). `not_run` is valid only when no test applies or the environment cannot be started from the workspace; a startable environment is started, not skipped (`shared/skills/qqa/SKILL.md § BLOCKED handling`).
- `commit_sha`: SHA of the code commit produced (empty string if no commit, e.g. on blocked status)
- `memory_relied_on` (**optional**; missing = `[]`): headings of the memory entries this phase actually applied — quoted or acted on — never every entry that loaded. Feeds Step 7 item 3's `Memory relied on` header line.

**Orchestrator hands-off policy**: the orchestrator does NOT silently edit, rewrite, or selectively amend the sub-agent's code commit. Permitted responses to a problematic code commit are limited to: (a) re-spawning the sub-agent with findings (Step 6 auto-fix), (b) halting the phase and presenting the commit to the user, who decides how it is undone (`git revert` is banned by `shared/AGENTS.md § Commit Safety`), or (c) accepting the commit as-is and proceeding. Direct silent edits to sub-agent-authored code are forbidden because they break the two-commit authorship model and corrupt the git trail.

**A sub-agent that discloses it authored rather than transcribed triggers execution before acceptance.** When a return says it wrote a recipe, command, or snippet fresh instead of copying it from a cited source, run that artifact before accepting the return. The citation and link guards cannot see inside a code block, so a self-authored and broken inlined recipe passes every mechanical check. The disclosure is the only signal that reaches it.

**Interruption and recovery**: a dangling code commit with no paired plan commit, a results-based phase's dangling commit, and a sub-agent interrupted before committing, or one that committed but never returned — see rows 3-6 of the table in `recovery.md` (pointer under `### Interruption and recovery reference`).

Proceed to Step 5 with the code-commit SHA in context.

**Results-only phase** (probes, a spike, or docs-only work with no code commit): the sub-agent returns `commit_sha: ""` and the orchestrator's Step 7 commit `docs(<plan-slug>): phase N progress (code: none)` is the phase's only commit; `commit-pairing` has nothing to pair and passes.

**Exit-criteria ticking (Standard/Major only)**: As you complete each exit criterion in the current phase, edit the project file to change `- [ ]` to `- [x]` for that item. Tick each box the moment its work is done and verified — do not batch-tick at end of phase. A `User acceptance:` box is ticked only with the user's turn cited (qvalidate `acceptance-evidence`). A criterion that names a push is met only when that branch's CI pipeline has finished green, or when the progress entry names each failing job and its cause. A test criterion is met by the repo's CI test command over the full suite, not by the changed test files alone or by a run outside the CI environment. Where the project's governance gives its own test execution instructions, those take precedence (`shared/AGENTS.md § Doc & Test Guidelines`). Light tier retains the narrative Verification section unchanged and does NOT use checkbox ticking. If a Light plan nonetheless contains `- [ ]` items (e.g., copied from a Standard template), tick them at the agent's judgment but do NOT apply the Step 8 hard gate — the gate fires for Standard/Major only.

**Exception for parallel dispatch**: When a phase is executed as part of a parallel group (see the `## Multi-agent execution reference` section), sub-agents do NOT tick exit criteria in the project file. They report satisfied criteria via the `exit_criteria_ticked` return field only. The orchestrator applies all ticks in Step 7.

**Parallel execution flow**: When the next phase(s) form a parallel group, follow the `## Multi-agent execution reference` section below.

### Step 5: Sub-agent review

After completing a phase, delegate review to a **separate sub-agent** with fresh context (no assumptions carried over from implementation).

Before constructing the first review sub-agent brief, load `/qreview`'s SKILL.md, so persona selection, fan-out, standards and the spawn brief contract are in active context. Later reviews in the same session reuse it; load it again only after a context compaction, or if you can no longer quote the Spawn brief contract.

Reviewers must not flag the Progress Tracker, Status line, or Implementation Divergences section as "not updated for this phase" — that update is Step 7's job, which always runs after this review for the same phase. This is mechanically guaranteed by process order, not a property of the implementation under review.

#### Effort declaration

Default effort: standard — including Major-tier plans. The user may still escalate individual higher-risk phases to `effort: full` via inline instruction. Kiro sessions keep the prior full-depth default — see `providers/kiro/skills/qreview/OVERLAY.md`.

#### Persona selection

Persona selection follows `/qreview`'s Persona-selection rules for the `/qdev Step 5 (per-phase)` call site.

#### Sub-agent fan-out

Fan-out mode follows `/qreview`'s Sub-agent fan-out rules, including its Mutation-testing isolation.

#### Review standards

Review standards: the subset declared in `/qreview`'s Subset declaration per call site for the `/qdev Step 5/9` call site, defined in its Standards union.

#### Sub-agent execution

**Skip rule (per-phase only — Step 9 final review is never skipped)**: Per-phase review may be deferred to Step 9 when the phase meets BOTH of:

- Mechanical parity to a previously-reviewed sibling phase (e.g., `.ps1` mirror of an already-reviewed `.sh`), OR single-file prose edit ≤30 LOC, OR a single SKILL.md/AGENTS.md/TEMPLATES.md section update with no logic change. (LOC = non-blank, non-comment lines added or modified; for markdown, count rendered content lines including table rows.)
- No new executable code (scripts, functions, or test fixtures).

This Skip rule is **independent of the Light-tier persona-count exception for `/qplan` Step 4 in `/qreview`'s Persona-selection rules**: that rule scopes whole-plan persona breadth (1 sub-agent vs min-3 personas); this rule scopes per-phase deferral. They compose: a Light-tier prose-only plan whose phases meet the Skip rule still runs its single-sub-agent Step 9 holistic review at the end.

When deferring, the orchestrator records `Per-phase review deferred to Step 9: <one-line reason>` in the phase's implementation notes. Step 9's holistic review covers the deferred phases as part of the full implementation scan. Deferral means the sub-agent review runs at Step 9 instead of now — it does NOT mean no review occurs. (No "previous phase had no unresolved High" guard is needed — Step 8 already blocks auto-continue on any unresolved High, so by the time we reach Phase N+1's skip decision, no High from Phase N can be outstanding.)

Otherwise:

Spawn brief follows `/qreview`'s Spawn brief contract. Pass: plan path + completed phase number + governance files + standards subset + assigned persona name(s) + focus area(s) + lens instruction + the implementation sub-agent's reported `exit_criteria_ticked` count (so the reviewer can run qvalidate's `phase-count` check per the Exit-criteria integrity standard). Before dispatching, the orchestrator must independently verify this count against the plan file's own `- [x]` boxes in the just-completed phase's exit-criteria block (e.g. `grep -c '^- \[x\]'` scoped to that block) — do not relay the sub-agent's self-reported count unverified. A mismatch caught here costs one correction; propagated to N reviewers, it costs N redundant qvalidate-FAIL investigations.

Dispatch and findings merging follow `/qreview`'s Sub-agent execution. The merged findings list is what Step 6 (auto-fix) and Step 7 (review log) consume. The orchestrator derives per-phase health per `/qreview`'s Verdict rubrics from the current findings and their resolution states, re-evaluated at the Step 7 log write and the Step 8 gate (not frozen at merge time).

If sub-agent dispatch fails, follow `/qreview`'s Sub-agent unavailability gate (hard stop, user decision required).

A review persona that returns no output (an empty or missing final message) counts as a dispatch failure for its persona. Before merging, check that every dispatched persona returned findings or an explicit no-findings statement. If one did not, stop and present `Retry / Skip / Abort` through the same gate, naming the persona and the coverage lost (its lens and focus area). Do not merge the partial findings, and do not compute per-phase health, until the user decides. Skip is recorded in the review log as `Review skipped (persona returned no output, user approved) -- persona(s): [names].`

**Parallel groups**: see `parallel-execution.md`, item 5.

### Step 5b: QA verification

> **Structural independence**: This step fires regardless of Step 5's outcome. Whether Step 5 dispatched a review sub-agent or deferred via the Skip rule, Step 5b executes next. Per-phase QA verifies surfaces in isolation; Step 9b re-verifies them integrated — a per-phase PASS does not exempt from Step 9b.

**Trigger**: The phase heading contains a `[QA]` annotation (case-sensitive, detection regex: `\[QA\]`). If present → auto-invoke `/qqa` without user prompt (this is a deliberate design choice — the planner already decided QA is warranted at `/qplan` time). If absent → run fallback detection:

**Fallback detection** (when no `[QA]` annotation):
1. Run `git show --stat <commit-sha>` to get the list of modified files. (For Light/inline where no commit exists yet, use `git diff --stat` against HEAD or inspect the working-tree changes instead.)
2. Cross-reference with the phase description and exit criteria from the plan. If the modified files OR the phase content (description, exit criteria) indicate a non-SKIP surface type (per `/qqa` § Surface taxonomy — CLI scripts, HTTP endpoints/handlers, UI components, library exports, agent/prompt files), prompt the user: "This phase modifies [files] / describes [surface]. Run /qqa to verify runtime behavior?" The user confirms or declines.
3. If all signals (file list + phase content) point to docs/types-only (markdown, `.d.ts`, comments, config schema), do not prompt — no runtime surface.

**Scope narrowing (per-phase = light QA)**: When invoking `/qqa` per-phase, pass a narrow claim: "Verify Phase N's [surface type] responds correctly: happy-path behavior as specified in exit criteria, plus one error-handling probe." This scopes `/qqa` to light verification — not the full probe mandate or topology enumeration (those run at Step 9). For phases with multiple surface types, issue one claim per surface type. Pass the plan's Verification section with the claim; `/qqa` starts the environment from it and the project's `### Verification Setup`.

**Tier coverage**: This step applies to all tiers:
- **Standard/Major**: fires after implementation sub-agent returns (same position as current Step 5b).
- **Light/inline**: the orchestrator invokes `/qqa` inline (no sub-agent) after implementing the phase. If the phase has no runtime surface, record SKIP and continue.

**Verdict handling** (unchanged from current):
- **PASS**: No impact on auto-continue. Record in implementation notes.
- **FAIL**: Hard-stop auto-continue. Findings enter Step 6 auto-fix loop as at least Medium severity (severity floor — anchors may escalate; see `/qreview`'s Verdict rubrics).
- **BLOCKED**: Escalate to user. If user resolves the blocker, re-run /qqa. If user declines, continue with the phase recorded as BLOCKED (user declined) in implementation notes, with the closing check `/qqa` named; SKIP means only that no runtime surface exists.
- **SKIP**: No impact. Record in implementation notes. (A SKIP on a `[QA]`-annotated phase indicates an annotation mismatch — record in implementation notes: "QA annotation mismatch: /qqa returned SKIP on [QA]-annotated phase — consider removing [QA] in future plan revisions." Treat as PASS for auto-continue.)
- **Unrecognized**: Treat as BLOCKED and escalate.

### Step 6: Auto-fix and iterate

This step applies only to per-phase reviews. The final review in Step 9 has its own auto-fix loop. Findings from Step 5b /qqa FAIL verdicts enter this loop alongside review findings (at least Medium severity — severity floor; anchors may escalate; see `/qreview`'s Verdict rubrics).

1. Classify Step 5 findings into exactly two categories — there is no third:

   **Auto-fix**: the fix is clear, mechanical, and requires no business-logic judgment. Apply it regardless of severity. A Low finding that takes 2 minutes to fix is auto-fixed, not deferred.

   **Escalate**: the fix requires a trade-off, a design choice, or information the orchestrator does not have. Present to the user with a recommendation. Write each option as the behaviour the user will observe after it lands, not the mechanism, and make the escalation self-contained (the finding, the file, what each option changes) for a user who did not follow the session. A fix that would change a test expectation without a citable source is always Escalate. A fix that removes or weakens anything the user approved (a success criterion, a resolved decision, a scope line), or that settles a judgment call the plan left open, is always Escalate, even when it is mechanical.

   The orchestrator cannot "Accept", "Note", or dismiss a finding on its own authority. "Not worth fixing" is a user decision. If the orchestrator believes a finding is incorrect or contradicts an explicit plan decision, it must still present it to the user with its reasoning rather than silently closing it.

   **Effort test**: before classifying any finding as Escalate, ask: "Can I fix this in under 5 minutes without changing behavior or making a judgment call?" If yes, auto-fix it. The bias is toward fixing.

   **Security/validation-gate escalation**: when a finding's fix touches code whose job is a security, leakage-detection, or input-validation gate (as opposed to ordinary application logic), route the cycle-2 re-review through `/qreview`'s Full effort tier (`shared/skills/qreview/SKILL.md § Effort tiers`) regardless of the finding's own severity — that class of code carries disproportionate regression risk from even a small, well-scoped fix, and the fix's blast radius is what matters, not the size of the diff.

   Classify the findings list returned by Step 5's Sub-agent execution subsection (merged across personas for 2+ persona reviews) — never per-sub-agent.
2. **Standard/Major**: re-spawn the Step 4 implementation sub-agent with the same contract (fresh context, governance files, plan path, phase number) plus the findings list (merged across personas for 2+ persona reviews) and the instruction "apply these auto-fixes and re-commit." The re-spawn returns the same structured payload with a new `commit_sha`. The re-spawn is required whatever the fix size: the orchestrator does not apply a Standard/Major auto-fix itself because the fix looks small or the scope narrow. **Light/inline**: the orchestrator applies auto-fixes in-session.

   Three requirements on the fixing agent, whichever path applies:

   **Name every consumer when the fix changes a shared value.** If an auto-fix changes a protocol response, an error code, or any value another component branches on, the agent must enumerate the consumers of that value and state whether each still behaves correctly. A fix can be correct on its own side and leave a consumer worse off — and the resulting defect sits in a file outside the fixing agent's declared scope, where neither its own tests nor the cycle-2 diff will surface it.

   **Re-derive a named target from the symptom.** When a finding or brief names a specific target — a logger, a call site, a file — for a symptom that was *measured*, re-derive that target from the symptom before acting, and report the attribution either way. The named target is the reviewer's or orchestrator's hypothesis, not part of the measurement; complying with a wrong one produces a green, wrong fix that closes the finding on paper while leaving most of the problem in place.

   **Justify every changed test expectation**, per Step 4's Test-writing nudges. Deciding the old expectation was wrong is a spec judgment: an uncited change surfaces as a `divergences` entry, which the orchestrator escalates.
3. Re-run Step 5's sub-agent review on the updated code with the **same persona(s)** as the initial review — same per-persona fan-out and merge sequence. If sub-agent dispatch fails, follow `/qreview`'s Sub-agent unavailability gate (hard stop, user decision required).

   **Low-only short-circuit**: If cycle 1's findings are all Low severity AND every auto-fix applied was purely mechanical (formatting, citation paths, typos, whitespace — no content additions, no removals beyond strict cleanup, no behavior changes), the orchestrator MAY skip the cycle-2 re-review. Record the skip in the phase's review log entry prose body: "Cycle 2 skipped — cycle 1 findings all Low + auto-fixes purely mechanical." This short-circuit does NOT apply when any auto-fix involved a design choice, content addition, behavior change, or non-trivial reformatting; in those cases cycle 2 remains mandatory.

   **Governance/prose-only carve-out**: when the phase's implementation contains no executable code (only `SKILL.md` / `AGENTS.md` / other markdown edits), the "content addition" exclusion is relaxed — additive prose that introduces no new rule, logic, or behavior (e.g., a citation, a clarifying clause, an example) does NOT by itself force cycle 2; the short-circuit MAY apply if all cycle-1 findings are Low and no auto-fix made a design, logic, or behavior change. Design, logic, or behavior changes to governance prose (e.g., altering a rule's semantics or a gate's condition) still require cycle 2. Record the basis in the review log prose ("Cycle 2 skipped — governance/prose-only, all Low, additive-clarity fixes only").

4. **Cycle cap and regression escape**: Max 2 cycles per phase. If cycle 2's review surfaces *new* High-severity findings that did not exist before cycle 1 (i.e., the auto-fix introduced a regression — compared against cycle-1's findings list, merged for 2+ persona reviews), the orchestrator MUST stop the auto-fix loop, keep the cycle-1 commit as the accepted implementation, and present the regression finding and the cycle-2 commit to the user as a blocker. Do NOT enter a third cycle; do NOT silently edit the sub-agent's code.

4a. **User cycle-cap override** ("N qreview cycle(s) per phase"): a user cap replaces the automated cycle count in item 4 and in Step 9's loop. A user may state, in the same message, the effort of the Step 9 final review (Step 9's Effort declaration); that effort replaces the default there. The cap and the effort override change nothing else, with one exception: once a cap is in force, a re-review round that returns only Low findings ends the loop. Auto-fix those Lows without a further review round and without item 5's cleanup prompt; continue only when the round returns a Medium or High finding. A project may declare a standing cap in its `AGENTS.md` `## Doc & Test Guidelines` (for example `Review cycle cap: 1 per phase (Claude Code)`); /qdev applies it as if the user had typed it, scoped to the harness named, and says so at Step 1 — an explicit cap in the invocation still wins. Step 5's per-phase review still runs for every phase, including a phase a gate interrupted mid-phase (run it when the phase resumes, before Step 7). Record the (default, override) pair once per plan in the project file, per `shared/AGENTS.md § Continuous Improvement`. A cap does not cover unreviewed code: when QA or a later fix changes an already-reviewed phase, or a fix applied in the cap's last cycle leaves a behavior change unreviewed, review that change before Step 7 even if the cap is spent. For substantial new code (a redesign, not a small fix), run the phase's usual Step 5 review. For a behavior-changing fix, dispatch one read-only sub-agent scoped to that fix commit's diff plus enough surrounding file context to judge it, and treat its findings as Step 6 findings. A purely mechanical fix (formatting, citation paths, typos) needs no review.

5. **Post-cycle-cap user-directed cleanup**: when the cycle cap is reached and auto-fixable findings remain (Mediums or Lows that survived two cycles), present each remaining finding to the user with the standard action set — **Fix now** / **Accept and note** / **Open follow-up plan** — with **Fix now** listed first by default and marked as the recommendation. A recommendation of **Accept and note** or **Open follow-up plan** is allowed only when it states its reason (for example: the finding lies outside this phase's task, or the fix needs a design choice the plan left open). A finding outside the phase's task is reported, never fixed uninvited (`shared/AGENTS.md § Core Principles`, "Bugs outside the task are not yours to fix"); the Fix now default applies to findings inside the phase's task, including bugs in unchanged lines of a function the phase touched. **Head the prompt with the convergence signal**: the reviewers' standing verdict from the latest cycle, quoted (e.g. "both personas returned no unresolved High — safe to commit"), and the round-over-round findings-by-severity counts. Without it the user is answering an open-ended offer to keep fixing rather than choosing against evidence that review has converged — the failure mode is a long tail of fresh Lows on a phase two reviewers already cleared. "Fix now" re-spawns the implementation sub-agent (Step 4 contract) with the user-selected findings; the cycle cap applies to orchestrator-automated cycles, not to user-directed cleanup passes. Apply the user's "Fix now" decisions in a single follow-up sub-agent re-spawn, then return to the auto-fix flow (re-review at Step 5). "Accept and note" or "Open follow-up plan" decisions update the Resolution column in the review log via Step 7, per the post-response rewrite mapping in Step 7's `Resolution column values` block.

**Parallel groups**: see `parallel-execution.md`, item 6.

### Step 7: Update the project file (orchestrator-owned)

This step is always performed by the orchestrator, never by the implementation sub-agent. The sub-agent's code commit is already in git history; the orchestrator now updates the project file to reflect what happened and commits those project-file updates separately.

1. **Mark tasks and exit criteria as complete** -- change `- [ ]` to `- [x]` for every completed item. For Standard/Major, run the **deterministic count check** via qvalidate: `qvalidate --phase N --expect-ticked <sub-agent's exit_criteria_ticked>` (run `shared/skills/qvalidate/scripts/qvalidate.py` with the playbook venv, per `shared/skills/qvalidate/SKILL.md` — never re-implement the checks inline) runs the `phase-count` check, comparing the ticked `- [x]` boxes inside the just-completed phase's block against the sub-agent's reported count. On a FAIL, diff the checkbox deltas against the code-commit changes and either re-spawn via Step 6 or escalate to the user before committing plan updates; handle the FAIL per `shared/skills/qvalidate/SKILL.md § Failure semantics`. Light tier has no checkboxes to tick.
2. **Add implementation notes** -- under the completed phase, append an implementation notes sub-section. Prefix format: a line `Implementation (YYYY-MM-DD, code: <sha-short>)` followed by the sub-agent's `change_description` pasted **verbatim** on the next line (no edits, no summarization, no reformatting). The prefix is an orchestrator-added header; the paragraph body is the sub-agent's voice. For Light/inline, the orchestrator writes the notes directly — there is no sub-agent voice to preserve.
3. **Update the status field** in the header blockquote (set to "In Progress" when first phase starts; keep "In Progress" during execution)
   - **`Memory relied on` header line** (every tier with a project file; inline plans record nothing): merge the sub-agent's `memory_relied_on` (missing = `[]`) and the orchestrator's own list — entries it applied this phase, never those merely loaded — into `> **Memory relied on**: <heading> | <heading>` (`shared/skills/qplan/TEMPLATES.md § Status Grammar`). Keep existing headings, add new ones, skip exact duplicates. Copy each heading from the memory entry's actual `### ` line, never a paraphrase of a sub-agent's return; a heading you cannot find is written as returned, and the sweep reports it unresolved. Absent line and a non-empty union: insert it after `> **Scope**:`; replace a `none` value. An empty union writes nothing. Light tier: the orchestrator's list alone.

   **Deferred exit criteria (Standard/Major only, orchestrator-owned)**: If an exit criterion cannot be met within the current phase, the implementation sub-agent **records** the deferral in its `exit_criteria_deferred` return field (see Step 4) — it does NOT edit the project file's future phases itself. The orchestrator, in this Step 7, **applies** each recorded deferral by appending a bullet to the target phase's exit criteria list: `- [ ] (deferred from Phase N) <criterion text>`. Before appending, confirm the target phase's `**File scope**` covers the file the item needs. If it does not, add that file to the target phase's scope and say so in the bullet. If no remaining phase can take it, surface it to the user. Route a review finding whose fix needs a file outside the just-completed phase's scope the same way. Also record the deferral in the current phase's implementation notes. This single-ownership rule prevents double-appends.

   **Deferral cap (one hop maximum)**: An exit criterion may be deferred at most **once**. If Phase N+1's sub-agent again cannot satisfy a criterion deferred from Phase N, the orchestrator MUST surface this as a High-severity finding, halt auto-continue, and present two options to the user: (a) convert to a follow-up plan (accept the item as out-of-scope for the current plan), or (b) treat as a blocker and resolve interactively before continuing.

   The orchestrator should first attempt reasonable auto-resolution (fix a flaky test at its cause, apply unambiguous one-line fixes in-session) and only defer when resolution is genuinely too complex to do now or when the cross-phase home is a better fit.

4. **Document divergences** -- for Standard/Major, copy each entry from the sub-agent's `divergences` list into the "Implementation Divergences from Plan" section. For Light/inline, write these yourself.
   **Mechanical harness-capture**: if this phase recorded a governance violation (self-caught or user-caught), a QA BLOCKED verdict, or a spec deviation in its implementation notes, write the corresponding `## Harness Improvement Opportunities` entry (per `shared/AGENTS.md § Harness Improvement Capture`) NOW, in this same project-file update — a verbal "I'll note this as a harness friction item" without the write is the failure mode this item exists to prevent.
5. **Update review resolutions** -- for any review findings fixed this phase, update the Resolution column.
6. **Apply deferred exit criteria** (Standard/Major, when `exit_criteria_deferred` is non-empty): for each deferred item, add the entry to the target phase's exit criteria list per the Step 7 deferral paragraph.
7. **Append a review log entry**:
   ```markdown
   ### YYYY-MM-DD -- Implementation Review (after Phase N, persona: <name or names>)

   Implementation health: Green/Yellow/Red.
   N findings (X High, Y Medium, Z Low).

   | # | Severity | Finding (one line) | Resolution (one line) |
   |---|---|---|---|
   ```

   **Resolution column values** (renaming this block label breaks citations — `/qreview`'s Verdict rubrics cite it by name) — the orchestrator may only write:
   - `Fixed — <what was done>` (auto-fixed findings)
   - `Escalated — <recommendation>` (presented to user; updated after user responds)
   - `User: accepted — <user's reason>` (only after the user explicitly approves dismissal)
   - `Orchestrator: proposed-accept — pending user decision` — unresolved per `/qreview`'s Verdict rubrics for health derivation and gating; the finding must be surfaced at the next gate (a proposed-accept written during Step 9 surfaces at `/qclose`'s archival gate — deliberate parity with `Escalated` handling).

   A user response converts the cell to `Fixed — <what>` (fix applied) or `User: accepted — <decision>` (accepted / follow-up plan opened / deferred with reason) — the Step 6 and Step 9 action sets reference this mapping.

   The orchestrator must never write "Accepted", "Noted", or "No action needed" in the Resolution column without prior user approval. A `User: accepted` resolution must cite the user turn it records; absent a citable turn, the only valid states are `Escalated — <recommendation>` or `Orchestrator: proposed-accept — pending user decision`. Write the citation into the cell as you record the turn: the user's words quoted, or the date with `user turn`. `qvalidate`'s `acceptance-evidence` check FAILs a `User: accepted` table cell without a marker: a quote, a `YYYY-MM-DD` date, or a reference (`user turn`, `user answer`, `user decision`, `same (user) turn`, `decision <id>`). A bare `Follow-up <n>` is not one, nor is a negated reference (`pending user decision`). Wherever you mention or quote the label (a Finding cell, prose), write it in backticks, since plain text there is a hit; never backtick it in a cell that records an acceptance, whether a Resolution or a decisions-table cell. Never add a marker to an existing row the user did not give. A stage-deferred closure reads `User: accepted — stage-deferred: <stage> ("<the user's words>", <YYYY-MM-DD>) — <reason>`.

   `User: accepted — <reason>` is the justified-override audit category per `/qreview`'s Verdict rubrics.

   The heading line above the table (e.g. `### YYYY-MM-DD -- Implementation Review (after Phase N, persona: <name or names>)`) carries the persona attribution; do not duplicate it per row. Each Finding cell is one prose sentence, ≤25 words; each Resolution cell is one prose sentence, ≤25 words. If a finding needs more, move detail to the prose body below the table (the dropped Confidence column also belongs there). Quote sub-agent prose only when the finding's wording is essential.

   *Note: for 2+ persona reviews, identical findings raised by multiple personas are merged into one row before logging; record the contributing personas in the prose body below the table if it matters for traceability.*
8. **Commit project-file changes only** (Standard/Major **and Light tier with a project file**): stage `plans/<plan>.md` (nothing else) and commit `docs(<plan-slug>): phase N progress (code: abc1234)` using the `<plan-slug>` computed at Step 1; when the resolved project-file root is a different repository from the code (a workspace store, per `shared/skills/qdream/memory-rules.md § Resolution contract`), run it against the plan's own repository instead — `git -C <plan-root> add -- <plan-path-relative-to-plan-root>` then `git -C <plan-root> commit -m "docs(<plan-slug>): phase N progress (code: abc1234)" -- <plan-path-relative-to-plan-root>`, `<plan-root>` being the directory holding the project file — and pass both `--project-root` (the code repository) and `--plan-root` (the store) to `commit-pairing` when validating a store-backed plan, since it has no cross-repository guard against a swapped pair. See `shared/skills/qclose/SKILL.md § Step 6: Execute the move` for why `git -C` is required for a cross-repository commit.

Skip project file updates for inline plans. Instead, present a completion summary: files changed, tests, divergences, follow-ups. (For the final phase, see Completion output in Step 9 which supersedes this format.)

If later rollout/migration/cleanup phases remain open, the status update and completion summary must say so explicitly using the state–detail form `In Progress — <what remains>` (for example, `In Progress — implementation complete, rollout pending`) per `shared/skills/qplan/TEMPLATES.md § Status Grammar`. Do NOT present the overall task as complete yet.

**Parallel groups**: see `parallel-execution.md`, item 7.

### Step 8: Auto-continue or stop

**Auto-continue** to the next phase if ALL conditions are met:
- Phase review health is Green or Yellow
- No unresolved High findings (evaluated against the merged findings list for 2+ persona reviews)
- All escalated or proposed-accept findings (any severity) have received a user response
- No blockers (user decisions, manual tests, external prerequisites)
- No pending rollout/migration/cleanup phases required for production correctness or deferred rollback-window cleanup
- Next phase prerequisites are met
- All exit criteria for the just-completed phase are either ticked `- [x]` or explicitly deferred to a later phase (Standard/Major only; Light's narrative Verification suffices)
- User did not request specific phases only
- QA verdict is PASS, SKIP or BLOCKED (user declined) — not FAIL or an unescalated BLOCKED

Print a brief transition summary: `Phase N complete (<health>). Continuing to Phase N+1...` where `<health>` is the actual review health (Green or Yellow).

**Stop** when any auto-continue condition above fails, and also when:
- All phases are complete — proceed to Step 9 (Final review)
- Code-only phases are done but any rollout/migration/cleanup phase remains pending
- A qvalidate check returned FAIL (see `shared/skills/qvalidate/SKILL.md § Failure semantics`)
- A previously-deferred exit criterion has failed a second deferral (violates the one-hop cap)
- Sub-agent returned `tests: fail` for a Standard/Major phase (always a stop — do not auto-continue on a failing test run)
- Sub-agent returned `tests: not_run` for a Standard/Major phase without an accompanying rationale in the `detail` field (stop pending user acknowledgement; `not_run` with an explicit, user-visible reason such as "no tests apply to prose-only edits" is downgraded to a warning rather than a hard stop)

**Parallel groups**: see `parallel-execution.md`, item 8.

### Step 9: Final review

Existing review log entries describe past reviews, not the current session's review. Always perform a fresh review.

After all phases are complete, run a holistic review using **one sub-agent per review persona**, dispatched per `/qreview`'s Sub-agent fan-out rules.

**Non-deferrable on self-assessed context pressure**: the Step 9 final review and the remaining acceptance / cold-read exit criteria (Step 9b) are never deferred to a "fresh session" on a self-assessed "context depth" / "token budget" judgment. Before claiming a context constraint, **measure the actual remaining budget**; when it is ample, dispatch the review and exit-criteria sub-agents now rather than deferring. Each persona and cold-read runs as its own sub-agent with its own budget, so orchestrator context pressure is not a valid reason to skip them. (Mechanical reinforcement of `providers/kiro/steering/kiro-governance-discipline.md § Context-constraint excuses` in the shared skill.)

Before constructing the final review briefs, make sure `/qreview`'s SKILL.md is still in context: reload it if the context was compacted since the per-phase reviews, or if you can no longer quote the Spawn brief contract.

#### Effort declaration

Default effort: standard, at every plan tier. The user may override effort via plan metadata or inline instruction.

> Note: the final review continues to use the one-sub-agent-per-persona model for review only. No implementation sub-agent is spawned during Step 9. Code committed by per-phase implementation sub-agents in Steps 4 and 6 is part of the git history reviewed by the Step 9 persona sub-agents.

#### Persona selection

Persona selection follows `/qreview`'s Persona-selection rules for the `/qdev Step 9 (final)` call site. Select the persona set based on the breadth of changes and risk profile of the implementation:

- **Narrow, low-risk implementations**: Use the minimum set -- **`Senior engineer`** plus one domain-relevant persona.
- **Broad or high-risk implementations** (cross-cutting changes, security-sensitive, multi-domain): Use a wider set from `/qreview`'s Personas table for maximum coverage.
- **Minimum 2 personas**: always include **`Senior engineer`** plus at least one domain-relevant persona.

#### Review scope

Each sub-agent evaluates the full implementation (not just a single phase) through its persona's lens:

- Cross-phase consistency and integration
- Overall test coverage
- Documentation completeness against the project's `## Doc & Test Guidelines` (or out of scope if the section is a waiver — the heading present with a single-line decline body — per shared/skills/qplan/TEMPLATES.md § Doc & Test Guidelines) (existing docs updated; no unsanctioned new doc files; durable AGENTS.md updates were proposed via the `Save / Skip / Edit?` idiom for any contradictory requests applied during implementation — a governance/doc-policy proposal whose Skip writes no declination record)
- Any patterns that emerged across phases that warrant refactoring
- Resolution status of all findings from per-phase reviews

#### Sub-agent execution

Spawn brief follows `/qreview`'s Spawn brief contract. Pass: project file path + governance files + standards subset + assigned persona name(s) + focus area(s) + lens instruction (with the review-scope items above as scope context). Launch one sub-agent per selected persona, per `/qreview`'s Sub-agent execution.

Each sub-agent returns what `/qreview`'s Spawn brief contract specifies under **Sub-agent returns**.

#### Findings integration

Merging and deduplication of findings across personas follow `/qreview`'s Sub-agent execution; the merged table uses `/qreview`'s Findings table format. `/qdev` Step 9 then:

1. Classifies findings: auto-fixable vs escalate (same binary rule as Step 6 — no "Accept" category).
2. Synthesizes overall implementation health per `/qreview`'s Verdict rubrics (derived from the merged findings and current resolution states; sub-agents no longer return health).

#### Legacy REVISIT marker resolution

Before declaring the implementation complete, check the plan's review log for any `REVISIT WHEN SUB-AGENTS AVAILABLE` lines from prior sessions (before the sub-agent unavailability gate was introduced). For each legacy marker:

1. Re-run the review using the original persona(s) and standards subset, dispatched to a sub-agent with fresh context. Replace the old log entry with the sub-agent's findings and remove the REVISIT marker.
2. If sub-agent dispatch fails, follow `/qreview`'s Sub-agent unavailability gate (hard stop, user decision required).

New sessions do not generate REVISIT markers — they follow the Sub-agent unavailability gate instead.

#### Deferred exit criteria roll-up (Standard/Major only)

Before declaring the implementation complete, enumerate all `(deferred from Phase N)` entries across the plan. Any that remain unchecked at the final review are treated as blockers requiring user decision: mark resolved, convert to a follow-up plan, or escalate. Do NOT silently accept unsatisfied deferrals.

#### Auto-fix loop

Apply auto-fixable fixes (a fix that changes a test expectation follows Step 6's **Justify every changed test expectation**), then re-run review per `/qreview`'s Sub-agent fan-out rules. Max 2 cycles. **Ready state**: no unresolved High findings and no auto-fixable findings remain. Stop early if ready state is reached.

**Cycle-cap cleanup, Low-only short-circuit and governance/prose carve-out**: as in Step 6 (item 3's short-circuit and carve-out, item 5's cleanup, convergence-signal heading included), with two differences. "Fix now" is an orchestrator-direct edit here, not a sub-agent re-spawn. Skips and decisions are recorded in the Post-Implementation Review log entry below, per Step 7's `Resolution column values` mapping.

If sub-agent dispatch fails during the auto-fix review cycle, follow `/qreview`'s Sub-agent unavailability gate (hard stop, user decision required).

#### Step 9b: Exhaustive QA verification

After the review auto-fix loop closes (ready state reached or cycle cap hit and user-directed cleanup complete), run an exhaustive `/qqa` pass against the full implementation. This fires BEFORE the final stage and commit step so that QA fix-ups are included in that commit.

> **Relationship to per-phase QA**: Step 9b covers ALL runtime surfaces — including those already PASSed per-phase. Per-phase QA verified surfaces in isolation; Step 9b verifies them integrated. A surface that PASSed per-phase may FAIL here due to integration issues (wrong data format between phases, race conditions, topology-dependent bugs). This is not redundancy — it is integration testing.

> **Standalone holistic review (fast path)**: When `/qdev` is invoked on a fully-executed plan (all phases complete), Step 9b runs as part of the standalone review — the full implementation is present and testable.

**SKIP eligibility**: If ALL phases in the plan are docs/types-only (no phase produced executable code changes), skip this step entirely — no runtime surfaces exist to verify. Record: `Step 9b skipped — no executable code in plan.`

**"The environment isn't running" is not SKIP eligibility.** If the application is startable from the workspace, starting it is a bootstrap task — the same rule that governs BLOCKED (`shared/skills/qqa/SKILL.md § BLOCKED handling`) governs SKIP, or the excuse simply moves verdicts. Record SKIP only when no runtime surface *exists*, never when one exists but is not currently up. Test-suite, typecheck and build passes are not substitutes for exercising the surface.

**Invocation**: Activate `/qqa` with an exhaustive claim scoped to all runtime surfaces across the entire plan:

> Verify all runtime surfaces introduced or modified by this plan: [list surfaces by type, derived from plan phase descriptions and file-change summaries]. Full topology enumeration, full probe mandate (≥2 categories per surface, at least one state-dependent), adversarial probing.

Pass the project file path as context so `/qqa` can derive the change scope.

**Verdict handling**:
- **PASS**: Record in the Post-Implementation Review log entry. Proceed to commit.
- **FAIL**: Each finding is treated as an at-least-Medium-severity item (severity floor — see `/qreview`'s Verdict rubrics). Apply the same binary classification (auto-fix vs escalate). Auto-fixable findings: apply the fix, re-run `/qqa` (max 1 re-run). If the re-run also FAILs, escalate ALL remaining findings to the user — do NOT re-run again. Implementation cannot be declared complete until user resolves or explicitly defers each finding.
- **BLOCKED**: Before accepting a BLOCKED verdict, confirm `/qqa` attempted environment bootstrap (`shared/skills/qqa/SKILL.md § BLOCKED handling`): restart the service or app, request elevation from the user when the surface needs it, or run a headless or offscreen platform (for example an offscreen Qt platform or a virtual display) instead of deferring. If a bootstrap route was not tried, try it and re-run `/qqa` once. A BLOCKED that remains after that is escalated to the user (same as Step 8 blockers) before the plan closes, naming the surface, the bootstrap attempts made and the specific missing prerequisite. Do not proceed to the final commit, and do not hand the plan to `/qclose`, with a BLOCKED or deferred Step 9b surface until the user has chosen to resolve it or to accept it, recorded as BLOCKED (user declined) with the reason in the Post-Implementation Review log entry.
- **SKIP**: Should not occur (SKIP eligibility check above filters these). If it does, record and proceed.

After applying final fixes, stage and commit all remaining changes using Conventional Commits format `<type>(<plan-slug>): <description>` where `<type>` matches the nature of the fix (typically `fix` or `refactor`) and `<plan-slug>` is the literal slug computed at Step 1. For truly inline plans (no project file), use the inline-only format `<type>: <description>` without a scope. Do not push.

**Deploy-terminal plans**: when a deployment/rollout phase (e.g., a `/qconfig-sync` propagation phase) precedes this final review, any Step 9 auto-fix to authored content re-drifts the just-deployed copies. In that case the completion summary MUST flag that a follow-up re-sync is needed to propagate the Step 9 changes, naming the providers that hold generated copies (overlay-bearing Kiro skills, which deploy as merged copies on every platform; symlinked deployments reflect edits automatically). Alternatively, plans whose final phase is deployment may sequence the holistic review before the deploy phase to avoid the redeploy round-trip.

Append the review log entry using this template:

```markdown
### YYYY-MM-DD -- Post-Implementation Review

Overall implementation health: Green/Yellow/Red.
Personas: <list of personas used>.
N findings (X High, Y Medium, Z Low).
QA verification: PASS/FAIL/SKIP (N surfaces verified, M probes executed).

#### Test execution summary

| Phase | Tests | QA | Notes |
|---|---|---|---|
| 1: <name> | pass/fail/not_run | PASS/FAIL/SKIP | <brief note if not_run or fail> |

| # | Severity | Finding (one line) | Resolution (one line) |
|---|---|---|---|
```

**Test execution summary data source**: For Standard/Major tiers, populate each row from the sub-agent's `tests` field (Step 4 return) and the Step 5b QA verdict captured in implementation notes. For Light/inline tiers (no sub-agent JSON return), derive the Tests column from in-session verification commands (pass if commands succeeded, fail if errors, not_run if no tests executed).

**Table suppression**: If ALL phases report `tests: not_run` AND ALL QA verdicts are SKIP (i.e., the plan is entirely prose/docs with no executable code), emit a single line `Test execution summary: all phases prose-only, no tests or QA applicable.` instead of the full table.

Step 9 uses multiple personas (one per fan-out sub-agent), so when a finding is persona-specific, prefix the Finding cell with `[<persona>]` (e.g. `[Reliability] strict-mode flag missing`). Otherwise persona attribution lives in the `Personas:` header line above. Each Finding/Resolution cell is one prose sentence, ≤25 words; if longer, move detail to the prose body below the table (the dropped Confidence column also belongs there).

Use "Post-Implementation Review" (not "Implementation Review") to distinguish it from per-phase entries. If the plan was already fully complete when `/qdev` was invoked (fast path from Step 1), note this in the log entry: "Invoked on fully-executed plan; performed standalone holistic review."

**Completion output** (present to the user AFTER the Post-Implementation Review log entry is written and AFTER Step 9b QA and the auto-fix loop fully close):

1. **Test execution summary** — print the per-phase test results table as written in the review log entry above (or the single-line suppression note if applicable).
2. **Review findings** — summarize: N findings (X High, Y Medium, Z Low), overall health.
3. **Lifecycle handoff** — scan the project file for remaining `- [ ]` boxes; if any exist outside explicitly-deferred items, phases remain pending (do NOT suggest `/qclose`). For Light tier (no checkboxes), the handoff fires when the final phase's implementation notes are written and no rollout/migration/cleanup phases remain. When the condition is met: suggest `/qclose <plan-path>` as the next step. If pending phases remain, state what remains instead.
4. **Deploy-terminal addendum** — if applicable per the deploy-terminal rule above, flag the re-sync need.
5. **How to see it** — when reproduction is non-obvious (a browser flow, a specific invocation, a service that must be started), give the exact command or steps to observe the change working. Where Step 9b actually drove the surfaces, reuse its invocations; where it SKIPped or returned BLOCKED, give only commands you executed in this session. Omit where reading the diff is the honest answer, which covers most governance and prose changes.

For inline plans (no project file): print the test summary (table or suppression line), review findings, and — when reproduction is non-obvious — item 5's how-to-see-it, verbally. Omit the `/qclose` suggestion (no file to archive). This supersedes Step 7's brief inline-plan summary ("files changed, tests, divergences, follow-ups") for the final phase — Step 7's format still applies at intermediate phases before Step 9.

## Multi-agent execution reference

The parallel-group machinery (Standard/Major only) is in `parallel-execution.md` alongside this file. Read it in full when Step 1 detects that the next phases form a `[P:N]` group. Steps 4-8 cite its items by number.

**Brief violations**: when a sub-agent breaks its brief (for example it commits in a commit-suppressed re-spawn, or edits a file outside its scope), the orchestrator reports the violation to the user. It never ratifies the violation as accepted behaviour and never reuses it as precedent for later dispatches.

## Rules

Rules that are not stated in a step above:

- Do NOT report the task as fully complete while required rollout, migration, cutover, or cleanup phases remain pending
- Do NOT modify the plan's future phases (only update the phase you just completed)
- If you encounter an issue not covered by the plan, STOP and ask the user
- Commit changes after each completed phase and after the final review using Conventional Commits format with the `<plan-slug>` computed at Step 1 as the scope. Do not push. Each phase produces two commits: code commit (`feat(<plan-slug>): phase N — <desc>`) and plan commit (`docs(<plan-slug>): phase N progress (code: <sha-short>)`). Truly inline plans use the single-commit `feat(phase-N): ...` model. See `shared/AGENTS.md § Commit Conventions` for the canonical rule. Write any multi-line commit message to a scratch file and commit with `git commit -F <file> -- <your-files>`: the environment runs two shells whose here-document syntax differs, and a PowerShell here-string passed to the Bash tool shipped a commit whose entire subject line was `@`. That subject is unrepairable, because `--amend` is banned. Give each message file a name unique to that commit (for example the phase and an epoch), and check `git log -1 --format=%s` right after committing: a reused name can commit an earlier commit's message, and amend is banned. A one-line message needs no file: use `-m`.
- The orchestrator never evaluates its own implementation or plan output. All review passes through a sub-agent dispatch. If dispatch fails, stop and ask the user per `/qreview`'s Sub-agent unavailability gate.
- Apply the **Harness Improvement Capture** rule in `shared/AGENTS.md` — append friction observations (steps that didn't fit, ambiguous gates, missing categories, awkward conventions) to the project file's `## Harness Improvement Opportunities` section as you encounter them.
- Apply the **Council-Enriched Escalation** rule in `shared/AGENTS.md` when escalating design trade-offs to the user.
