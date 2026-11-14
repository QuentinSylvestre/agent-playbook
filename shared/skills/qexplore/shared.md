# Cross-mode question discipline

Rules that govern every question asked by `/qexplore` and `/qexplore-other`. Read this file at the start of any exploration session.

## Per-question discipline

- **One question at a time.** Even if you have many questions in mind, surface them one at a time as the conversation reveals which matters most. Depth-first. Exception: a Probe-gate consent request may ride with the first question in the same message; it is a yes/no on side effects, not a competing question.
- **Check before you ask.** An empirically verifiable assumption is checked, not asked: if a file read, grep, version query, or live request you can run right now would answer it, run it and report the result instead of surfacing it as a question or a to-confirm-later assumption. Questions are for what only the user knows (intent, priorities, constraints outside the repo).
- **Recommend an answer.** Every question carries a recommended answer. If confidence is low or medium, tag it on a separate line (using the walk's decision-unit label — see `## Question numbering`; default `Q`):

  ```
  <unit>: <question>
  Recommended: <answer> (confidence: medium)
  ```

  High confidence carries no tag — absence means "high".
- **Voice disagreement** when the user's answer (a) creates downstream risk in this codebase, OR (b) contradicts established best practices in the relevant domain (UI/frontend, backend, embedded, infra). Cite specific evidence — `file:line` for codebase, named pattern or repo convention for domain. Avoid generic "industry standards" appeals.
- **Honor user-stop.** If the user says "proceed", "enough", or "just plan it", summarize what's been covered and flag remaining gaps as Open Items. Do not push for more rounds.

- **Do not re-ask what the user's wording settles.** When the user's own wording of the item (its title, its stated goal, or an instruction in the request) already decides the point, do not turn it into a question, and never recommend an option that contradicts that wording. Treat the wording as the answer, state it as a settled fact, and ask only about what it leaves open. Example: an item titled "Align PA session settings with kiro-cli" has already settled that the target is kiro-cli's settings, so asking whether to align them is not a question.

## Exploration depth
<!-- Cited by name (`§ Exploration depth`) from qexplore/SKILL.md and providers/kiro/skills/qexplore/OVERLAY.md — renaming this heading breaks those citations. qplan/SKILL.md couples via the 9-item contract count (not this heading name). The Step 3 output contract's 9-section count is load-bearing: the Assumptions ledger must stay a labelled adjunct, never a 10th numbered section. -->

Exploration runs at one of three **depth levels** controlling how much the
interview interrogates the user. "Exploration depth" is the canonical name for
this axis ("interview depth" is an occasional gloss). The level governs
interview depth ONLY — codebase/correctness research (e.g. `/qexplore` Step 1.5
sub-agent dispatch) runs in full at every level. This axis is **orthogonal** to
`/qplan`'s complexity *tiers* (Trivial/Light/Standard/Major): a simple task can
warrant high depth and a complex one minimal. ("Tier" belongs to qplan
complexity; this axis uses "level".)

| Level | Interview behavior | Assumption ledger |
|---|---|---|
| **minimal** | Ask only genuinely-blocking questions (no safe default exists, or the safety floor applies). Resolve every other self-audit category by best-guess assumption and proceed to capture. "Let the model cook." | Large — every assumed resolution is listed |
| **medium** (default) | Ask the approach-changing questions; run the self-audit; leave lower-impact items to reasonable defaults. (The established behavior.) | Moderate — residual assumptions noted |
| **high** | Relentless: every self-audit category is explicitly confirmed with the user; no assumption left unconfirmed. | Trends to empty |

**Selection.** Default is **medium** — when the user gives no depth signal,
explore at medium. The user may set the level explicitly (a `minimal` /
`medium` / `high` argument, or natural language such as "just explore lightly"
/ "go deep / be thorough"). At the start of exploration the orchestrator
**recommends** a level from the stakes it can see (reversibility, blast radius,
cost) and states it, e.g. "low-stakes and reversible — I'll explore at
**minimal** unless you'd like more depth." In greenfield mode (Step 1.5
skipped) the recommendation leans on Step 1 governance/scope signals only,
since blast-radius evidence is thinner. The user can override at any time.

**Mid-session adjustment.** The level is not frozen at the start. The existing
user-stop ("proceed" / "enough" / "just plan it") collapses toward capture
regardless of level; conversely a "go deeper" / "what else?" signal raises the
level toward high. **On an upward bump, re-open every assumption already written
to the ledger under the lower level as a pending question before continuing** —
raising the level re-interviews the categories previously resolved by
assumption, not just future ones. Backfilled questions remain subject to the
`## Convergence test` and the user-stop, so a late bump cannot become
non-terminating. Re-recommend only when stakes visibly change.

**Reach.** Interview depth only. The mandatory dispatch gate and Step 1.5
research are unaffected by the level.

**Assumption ledger (coupling).** The lower the level, the more the burden
shifts from asking to *stating*. Whenever a self-audit category is resolved by
model assumption rather than a user answer, record it as an **Assumptions
(unconfirmed)** entry. This ledger is surfaced to the user in chat for veto AND
persisted in the capture artifact (see `/qexplore` Step 3) as a labelled
adjunct, distinct from genuinely-undecided Open Items. The in-chat veto
surfacing happens through the single end-of-interview assumptions checkpoint
(the `## Convergence test` item-3 disclosure): one veto surface, with the
consequence-significant assumptions (costly to reverse, scrutinized regardless
of confidence) leading and the residual depth-driven ledger following — the
checkpoint is the in-chat gate, this ledger its persisted/carried record. At **high** the ledger
is empty (everything confirmed); at **minimal** it carries the bulk of the
design.
- **Veto handling.** The in-chat ledger surfacing + veto must happen before
  **any** exit — both the Step 3 capture path AND the Post-interview Trivial
  convergence skip (which bypasses Step 3 entirely). A veto raised before that
  exit converts the entry to an Open Item or a re-asked question; a vetoed
  assumption is never written to the ledger. (A veto after the artifact is
  written is handled by re-entry, out of scope here.) **Trivial-convergence
  carry-over**: if a minimal/medium exploration converges to Trivial with a
  non-empty ledger, the end-of-interview assumptions checkpoint has already
  surfaced it for veto; carry the un-vetoed assumptions into the inline `/qplan`
  handoff — they must not silently evaporate just because no project file is written.
- **Convergence test.** At minimal, the `## Convergence test` synthesis test is
  satisfied *by the ledger*: the documented assumptions are the basis a senior
  engineer would act on. The test still applies — it treats the ledger, not
  user confirmation, as the record.

**Oscillation gate.** The `## Recommendation oscillation gate` fires at **every**
level. A model-internal flip-flop on an *assumed* resolution — the same
recurrence (a recommendation changed more than once) the gate already governs —
is exactly its trigger: surface the pros/cons table and council opt-in rather
than silently landing the oscillated value in the ledger.

**Safety floor.** Even at minimal, any self-audit category whose different
answer would be **irreversible, breaking, or compliance-gating** (e.g.
migration strategy, data loss, breaking API change, security posture,
regulatory acceptance, hardware/resource contention) must be asked, not
assumed — these cannot be deferred to the ledger. The floor is this predicate,
not a fixed list. In greenfield mode (Step 1.5 skipped) the floor errs toward
asking — treat unknown blast radius or reversibility as floor-triggering, since
the evidence needed to clear a category is absent. Minimal reduces questions
about reversible choices; it never
silently assumes an unrecoverable one.

## Recommendation oscillation gate

When you change your recommendation on the same question more than once (i.e., you recommended A, then switched to B, and are now considering switching back to A or to C), STOP oscillating and instead follow these three named steps (the names are the stable cite-by-name targets; downstream skills like `/qcouncil` reference them by name, not by number):

1. **Pros/cons step**: present a structured **pros/cons table** covering all options considered.
2. **Opt-in step**: offer to invoke `/qcouncil`. The user must explicitly accept before the council runs.
3. **Dispatch step**: if the user accepts, invoke council per `shared/skills/qcouncil/SKILL.md § Council-Enriched Escalation (canonical body)` (Dispatch and Presentation format subsections; `shared/AGENTS.md § Council-Enriched Escalation` carries the trigger rule, not these subsections). In oscillation mode the orchestrator does NOT add its own recommendation — present summary + full council output + decision prompt (skip Presentation format item 2).

**A change caused by new input is not an oscillation.** New input is a goal, constraint or fact the user stated after your earlier recommendation, or a probe result. When you change a recommendation for that reason, name the input in the same message ("you added the goal of supporting more users, so I now recommend B"). The gate counts only changes that name no new input.

## Convergence test

Before producing the final summary:

1. **Synthesis test.** Draft the Recommended Approach internally. Ask: would a senior engineer acting on this approach, *without seeing this conversation*, be able to start work? If a clarifying question would arise, ask it now.
2. **Top-3 uncertainties.** List the three things you're least sure about. For each: would a different answer change the implementation approach?
3. **Consequence stress-test.** Items 1-2 key off how *uncertain you feel*; the costly misses are assumptions you feel sure about. So also scan assumptions by *consequence, independent of confidence*: tag one **consequence-significant** if a different answer would be costly to reverse once work commits to it or once downstream decisions depend on it — in code, e.g. a data structure, a module/contract boundary, or a pipeline stage; in a non-code decision, e.g. a budget basis, an org/process commitment, or a downstream-binding choice. For each, construct one concrete example that tries to break it; if it breaks, the design is not converged — reopen the thread. If many qualify, falsify the highest-consequence handful. Treat any assumption about an **external system's contract** (API field/model names, required fields, enforcement, response shapes) as never-a-fact: verify it with a read-only probe (permitted — it observes without implementing), or record it as an Open Item (execution-contingent) — never carry it forward as resolved.

**Visibility rule**: keep the synthesis draft and top-3 uncertainties internal by default. Surface them as a checkpoint message to the user when ≥1 of the top-3 uncertainties would change the implementation approach. The model's own uncertainty is the trigger; there is no round-count fallback.

**Item 3 is exempt from the internal-by-default rule above**: the consequence-significant assumptions and their stress-test results are *always* disclosed at end-of-interview as an actionable checkpoint before any summary is written or handoff offered (items 1-2 remain confidence-triggered). Each mode's skill defines where, and folds the surfaced top-3 uncertainties into that one checkpoint rather than emitting two — `/qexplore` Step 2 pre-summary; `/qexplore-other` before its summary.

## Question numbering

**Decision-unit label (choose once, up front).** Questions and decisions are numbered with a decision-unit label chosen at the start of the walk. The default is `Q` (yielding `Q1`, `Q2`, …) and is assumed unless the user frames the exploration around a different unit. When the user does — e.g. "walk the changes one by one" — adopt the matching label for the whole session (e.g. `Change`, yielding `Change-1`, `Change-2`, …). Choose the label once; do not switch mid-walk. The same chosen label applies to both the questions described here and the `## Decisions format (Q→A→Decision)` provenance below. Throughout this file and `/qexplore`, `<unit>` denotes the chosen label-and-number (`Q1` by default, `Change-1` when framed around changes).

Number every question continuously across all rounds within the session, starting at the first unit (`Q1` by default) and never resetting — round 2 begins at the next number after the last used in round 1. This lets the user unambiguously reference any question by its `<unit>` in their reply.

## Decisions format (Q→A→Decision)

Both `/qexplore` (in its 9-section summary's `Resolved decisions` item) and `/qexplore-other` (in its 3-section summary's `Decisions` block) record decisions in the same one-line provenance form, using the walk's decision-unit label (see `## Question numbering`; default `Q`):

```
- <unit>: <question text> — A: <user's answer> — Decision: <resulting decision>
```

The heading names the three-part shape (question → answer → decision), which is fixed; only the `<unit>` token varies — `Q1` by default, or `Change-1` when the walk is framed around changes. This format preserves the question-to-decision chain so downstream readers (a future `/qplan` invocation, a code reviewer, the user re-reading the file) can audit how every decision was reached.
