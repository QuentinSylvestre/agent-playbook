# Transition Fixtures — Cold-Read Regression Corpus

This file is the regression net for `/qdream`'s model-executed transitions. Each fixture pins a non-obvious derivation path through the sweep's prose rules.

Those rules live in the sweep files beside this one, not in `SKILL.md`: `sweep-orient.md`, `sweep-recovery.md`, `sweep-gather.md`, `sweep-synthesize.md` and `sweep-decide-apply.md` carry the `(regression fixtures: transition-fixtures.md FIX-…)` back-references, and `SKILL.md`'s phase index maps each `[TRANSITION-ID]` step ID to its file.

Eleven fixtures are **script-tested**, because a script now executes their transition: FIX-DISPATCH-quiet, FIX-DISPATCH-user-memory-flagged, FIX-COUNTVERIFY-truncated and the eight FIX-STATE-* fixtures. Each carries a `script-tested:` line naming the script and its selftest case or cases; that case is its test, and it is not replayed (§ Named consumer). Every other fixture is a frontier fixture, tested by replay.

## Preamble

### Fixture-ID grammar

`FIX-<FAMILY>-<branch>`

### Families

PRUNE, SIZE, BUDGET, STALE, DEMOTE, RERAISE, SUBSUMED, RECOVER, SPANSUB, SUPPORTSET, COUNTVERIFY, MERGE, FABRICATION, EXPIRY, DISCOVER, DISPATCH, HARVEST, STATE, SIGNAL, GATE, PHASE, RETURN

### VERDICT vocabulary (closed, exact-equality match; substring-disjoint)

- `excluded-from-prune`
- `surface-not-delete`
- `dont-demote`
- `quote-drifted`
- `not-subsumed`
- `subsumed-beats-stale`
- `no-op`
- `indeterminate`
- `skipped-context-budget`
- `new-conflict`
- `suppress-re-raise`
- `not-ungrounded`
- `recheck-passes`
- `nonterminal-wins`
- `refuted`
- `still-matching-re-raise`
- `reverify-not-stale`
- `no-agent`
- `floor-not-met`
- `landed`
- `workspace-path-only`
- `store-path-only`
- `both-paths`
- `not-stamped`
- `counter-4`
- `counter-plus-1`
- `counter-0`
- `key-dropped`
- `route-first-no-delete`
- `autonomous-size-prune`
- `user-skip-recorded`
- `expired-signal-removed`
- `human-expiry-gated`
- `lapse-reported`
- `one-gate-item`
- `gate-skipped`
- `human-keep-redated`
- `sweep-redated`
- `deferred-unchanged`
- `silent-merge`
- `phase-failure-not-shown`
- `presented-as-written`
- `write-needs-decision-and-end`
- `ask-retry-skip-abort`
- `keep-waiting`
- `write-output-now`
- `note-not-error`
- `error-blocks-stamp`

Scope note for the two verification-passed tokens, which a replay can otherwise confuse: **`recheck-passes`** is `[SYN-GATE]` — the Cross-validation *verifier* re-ran a `stale_entries` item's **quoted failing check** and it now passes. **`reverify-not-stale`** is `[GAT-CLASSIFY]` — an **expiry** forced a check on an entry that was never in `stale_entries` and has no quoted failing check, the check passed, and the orchestrator re-dates `Verified` and clears the fired expiry field. That outcome is wrong for a `human:` entry, which goes to `human_expiries` instead (`human-expiry-gated`). If there is no verifier and no stale item, it is not `recheck-passes`.

Scope note for **`no-op`**: it is `[ORI-RECOVER]` only, the end state of a journal record whose rename or removal did not land (surfaced, nothing restored). No other transition's verdict is `no-op`: a fixture whose end state is an entry or file left unchanged names its own token (for example `excluded-from-prune` or `deferred-unchanged`).

Scope notes for the tokens the human-attestation fixtures add:
- **`human-expiry-gated`** is `[GAT-CLASSIFY]`: a passing expiry-forced check on a `human:` entry is routed to `human_expiries` instead of being re-dated and cleared. FIX-EXPIRY-human-precedence-terminal, tagged `[SYN-RECONCILE]`, reuses it as its VERDICT with the same meaning: after reconciliation the routing still applies.
- **`lapse-reported`** is `[SYN-WRITE]`: a merge dropped a `human:` actor, so the Report's `Attestations lapsed on merge` line names the surviving heading.
- **`one-gate-item`** is `[SYN-RECONCILE]`: an entry on two routes gets only the route precedence keeps, one `DEC-GATE` item, not a second one for its passing expiry. In FIX-EXPIRY-human-precedence-terminal it is the MUST NOT: the wrong outcome in which a detection that reconciliation suppressed still counts as the entry's one item.
- **`gate-skipped`** is `[SYN-WRITE]`: a heading this sweep removed never enters `human_expiries`, so no expiry gate item exists for it.
- **`human-keep-redated`**, **`sweep-redated`** and **`deferred-unchanged`** are `[APP-ADJUDICATE]`: the end state of a human-attested expiry after `Keep`, `Re-date-as-sweep` and `Defer`.
- A precedence fixture is tagged with its VERDICT token's step, except FIX-EXPIRY-human-precedence-terminal (see `human-expiry-gated` above).
- **`silent-merge`** is `[SYN-WRITE]` and appears only as a MUST NOT: the wrong outcome in which a merge that dropped a `human:` actor leaves the Report without an `Attestations lapsed on merge` entry.

Scope notes for the tokens the phase-agent, gate and return fixtures add:
- **`phase-failure-not-shown`** is `[DEC-GATE]`: before presenting a gate item, the orchestrator's `handoff check gate.md` (or `dream-sweep.py decisions`) finds that `gate.md` is not the script's own render of the drafts, or that a text `decisions.json` would carry does not appear verbatim in the item's `gate.md` text, so it does not present the item and treats the Synthesize phase as failed under the Failure gate. **`presented-as-written`** appears only as a MUST NOT: the wrong outcome in which the item is shown, or its texts are taken, as `gate.md` wrote them.
- **`write-needs-decision-and-end`** is the phase agent's own end state when it cannot go on without the orchestrator: it writes a `needs-decision-<n>.json`, records its progress, and ends without asking, waiting or retrying. **`ask-retry-skip-abort`** appears only as a MUST NOT: the wrong outcome in which the phase agent puts the Failure gate's question to the user itself.
- **`keep-waiting`** is the phase agent's state while a child it launched is still running: it writes no output file and no `needs-decision` yet, waits, and checks again. **`write-output-now`** appears only as a MUST NOT: the wrong outcome in which the phase agent writes its output handoff file while a child has no final message.
- **`note-not-error`** is the Return Schema split: a condition that is not a failed analysis goes in `notes`, `error` stays `null`, and the return does not block the stamp. **`error-blocks-stamp`** appears only as a MUST NOT: the wrong outcome in which such a condition is put in `error`, so the project is not stamped.

Both VERDICT and MUST NOT tokens are checked by exact-equality on the parsed `VERDICT:` line value — not by substring presence in reasoning text. A MUST NOT failure means the replay agent emitted a MUST NOT token as its VERDICT, not that the token appeared in explanatory prose.

### Pass protocol

2-of-3 replay majority. This is a **meaning-testing** acceptance criterion, not a hard CI gate. A persistent miss (the same fixture fails across multiple replays) signals either a genuine prose ambiguity in the transition's rules (fix the prose) or a fixture defect (fix the fixture).

### Lockstep rule

Edit a transition's semantics → update AND replay its `[TRANSITION-ID]`-tagged fixtures in the same change.

The dispatch rule's fixtures (`FIX-DISPATCH-*`) are tagged `[ORI-DISPATCH]`, the step that builds the dispatch list in `sweep-orient.md`. They are script-tested: run their `dream-sweep.py --selftest --case` cases whenever `[ORI-DISPATCH]` or the manifest fields it reads (`[ORI-DISCOVER]`) change. For every script-tested fixture, the lockstep update is to the fixture and its selftest case, and the case run replaces the replay.

### Named consumer

Two consumers, distinguished by what each actually checks (per `shared/AGENTS.md § Structure Requires a Consumer`):

- **Existence — deterministic-tool consumer**: `verify-citations` confirms the corpus and its back-reference are present. It cannot detect content rot (a transition whose prose drifts away from its fixture) — see the existence-guard note below.
- **Content — frontier-replay net**: the 2-of-3 replay majority (§ Pass protocol) is the content consumer of every frontier fixture. A frontier replay agent emits a `VERDICT:` token compared by **exact equality** — the comparison is deterministic, but the replay that produces the token is a frontier model, and the majority is an acceptance criterion, not a hard CI gate. So content correctness is not machine-gated; a drifted transition surfaces only on replay.
- **Content — script selftests, for the eleven script-tested fixtures**: FIX-DISPATCH-quiet, FIX-DISPATCH-user-memory-flagged, FIX-COUNTVERIFY-truncated and the eight FIX-STATE-* fixtures. The selftest case on each one's `script-tested:` line (`dream-sweep.py --selftest` or `dream-write.py --selftest`) runs the script over the fixture's scenario and fails on a wrong end state, so these are machine-gated and not replayed. Their prose stays here as the statement of the rule the case checks.

### Authoring conventions

1. Parenthetical glosses on VERDICT lines and intermediate results are **authoring annotations**, stripped before the scenario is shown to the replay agent.
2. The existence-guard catches deletion of the **whole corpus or back-reference**, NOT a per-transition back-reference deletion.

---

## Fixtures

### FIX-PRUNE-conflict-excluded [SYN-WRITE]

A project memory file has 31 entries (over the ~30 Size-check threshold). Entry E carries `Governance-conflict: contradicts shared/skills/qdream/memory-rules.md § Session-start memory context budget — adjudicated 2026-06-15: rule-update-pending` and `Governance-conflict-quote: "aim for under ~30 entries"`. Entry E also fails its type-specific verification (pattern grep returns no hits). The Size check runs.

VERDICT: excluded-from-prune
MUST NOT: pruned

(The reader must derive: rule-update-pending is non-terminal; non-terminal entries are excluded from BOTH entry count AND prune set; E is also a stale_entries candidate, which separately excludes it from the prune set)

### FIX-SIZE-signals-exempt [SYN-WRITE]

A project `memory/MEMORY.md` that is not git-tracked (a solely-owned file: a folder the store resolver creates no store for) holds 31 entries: 29 plain `feedback`/`pattern` entries, each passing its verification with `Usage` 2 or more, and 2 `[improvement_signal]` entries under `## Pattern`. Signal S has `**Frequency**: 1 (below threshold)`, no `Usage` line, and was last observed 30 days ago. No entry has an `Outcome` or a `Governance-conflict` record, and Task 4 flagged nothing. The Size check runs. What happens to S, and to the plain entries?

VERDICT: excluded-from-prune
MUST NOT: pruned

(The reader must derive: every `[improvement_signal]` entry is excluded from the prune set wherever it lives, and in a project memory file also from the entry count. The count is therefore 29, under the ~30 threshold, so nothing is pruned: neither S, which looks lowest on `Usage`, nor any plain entry. Only an `Apply` at APP-ADJUDICATE, or the 90-day stale-singleton expiry at SYN-PROMOTE (not yet due for S), removes a signal.)

### FIX-BUDGET-over [SYN-WRITE]

A full sweep runs. The config repo's user memory is 500 words over the pin `MEMORY_BUDGET_WORDS` reports, per `dream-check.py budget`'s `memory` row. `memory/MEMORY.md` holds 40 entries, one `## Topics` row whose trigger is "editing a CI pipeline", and no `## Declined` rows. That topic file holds 12 entries. Entry R (300 words) is a `pattern` about CI caching, which that topic's trigger covers, and has no `Usage` line. Entry P (250 words) has `Usage: 0`, verifies, ranks first in the full prune order, and is the oldest `Verified` entry. Entry G carries `Governance-conflict: ... rule-update-pending`. `memory/HIGHER_ORDER.md` holds 6 nodes, one of them with no `Usage` line. The sweep did not analyze every project. Task 4 flagged nothing. The Size check runs. What does the sweep do to the user tier?

VERDICT: autonomous-prune-over-budget
MUST NOT: gate-item

(The reader must derive: `apply-all` removes the 500-word excess autonomously, lowest utility first, naming each removal; the older text of this note described a gated route and no longer holds. The sweep queues a routing proposal for R first (`Move / Keep / Defer`, showing the topic file's 12 entries), then prune proposals ranked by § Derived Utility & Pruning, starting with P with its `Usage` shown, as `Delete / Keep / Defer`, all for DEC-GATE. If any queued prune candidate lacked a `Usage` line, the prune batch would carry the header `Usage absent on <N> of <M> candidates; ranking is by age`; here P has one, and R is a routing proposal, not a prune candidate. R plus P would bring the tier under the pin, so no further prune proposal is queued, and R is not also a prune candidate. G is never a candidate (non-terminal conflict), though its words count. No HIGHER_ORDER.md node is ever proposed. Nothing is deleted without the user's `Delete`.)

### FIX-BUDGET-project-unchanged [SYN-WRITE]

A full sweep runs. A project `memory/MEMORY.md` that is not git-tracked (a solely-owned file: a folder the store resolver creates no store for) holds 35 plain `feedback`/`pattern` entries. Five of them fail their type-specific verification; the rest pass with `Usage` 2 or more. No entry has an `Outcome`, a `Governance-conflict` record or an `[improvement_signal]` tag, and Task 4 flagged nothing. The user tier is within its word pin. The Size check runs. What happens to the project file?

VERDICT: autonomous-size-prune
MUST NOT: route-first-no-delete

(The reader must derive: project memory files keep the entry advisory unchanged. The count is 35, over ~30, so the Size check prunes autonomously in the § Derived Utility & Pruning order, the five verification-failed entries first, records each as `pruned` in the working map, and names them in the Report.)

### FIX-STALE-conflict-excluded [SYN-STALE]

Entry F carries `Governance-conflict: contradicts shared/skills/qdev/SKILL.md § Process — adjudicated 2026-07-01: deferred` and `Governance-conflict-quote: "Always run verification steps before marking a phase complete"`. F fails its type-specific verification (the pattern it describes no longer exists in the codebase). Task-4 returned F in stale_entries with task4_status: checked (count-verified). The Cross-validation verifier returned staleness verdict: confirmed.

VERDICT: surface-not-delete
MUST NOT: demoted

(The reader must derive: deferred is non-terminal; the § SYN-STALE rule says "Never autonomously delete or rewrite an entry carrying any non-terminal Governance-conflict record" — regardless of confirmed verdict and checked status; surface in DEC-GATE)

### FIX-DEMOTE-unreachable [SYN-STALE]

Entry G carries Source: `Session abc123 (2026-05-15), turns 40-55`. Provenance re-open: the session file `abc123.jsonl` does not exist (rotated). The entry's type-specific verification (pattern grep) passes.

VERDICT: dont-demote
MUST NOT: demoted

(The reader must derive: unreachable provenance is indeterminate, never a demotion trigger; fall back to type-specific verification which passes)

### FIX-DEMOTE-conflict-surfaces [SYN-STALE]

Entry H carries Source: `plans/done/260601-1200_EXAMPLE_PLAN.md § Phase 2`. Provenance re-open: the project file exists and the cited section contradicts the entry's claim (the plan chose a different approach). Entry H also carries `Governance-conflict: contradicts shared/AGENTS.md § Commit Conventions — adjudicated 2026-06-20: rule-update-pending`.

VERDICT: surface-not-delete
MUST NOT: demoted

(The reader must derive: the provenance IS reachable-and-contradicting, which would normally trigger demotion — BUT the entry carries a non-terminal Governance-conflict record, so the carve-out fires: surface in Phase 4b showing both the contradicting provenance AND the pending adjudication)

### FIX-RERAISE-pending-still-matching [SYN-RECONCILE]

Entry J carries `Governance-conflict: contradicts shared/AGENTS.md § Git Staging — adjudicated 2026-07-05: rule-update-pending` and `Governance-conflict-quote: "Never use git add -A or git add . Always stage specific files."`. The re-raise predicate runs. The cited section shared/AGENTS.md § Git Staging currently contains the span "Never use git add -A or git add . Always stage specific files." verbatim.

VERDICT: still-matching-re-raise
MUST NOT: suppress-re-raise

(The reader must derive: rule-update-pending is re-raised EVERY SWEEP UNCONDITIONALLY — the span-match is prompt-framing, not a re-raise guard; it fires regardless of whether the span still matches)

### FIX-RERAISE-keep-quote-drifted [SYN-RECONCILE]

Entry K carries `Governance-conflict: contradicts shared/skills/qdev/SKILL.md § Process — adjudicated 2026-06-01: keep-entry` and `Governance-conflict-quote: "Run tests after every code change"`. The re-raise predicate runs. The cited section shared/skills/qdev/SKILL.md § Process currently contains "Run verification steps after each completed phase" but NOT the exact span "Run tests after every code change".

VERDICT: quote-drifted
MUST NOT: suppress-re-raise

(The reader must derive: keep-entry is re-raised when its quoted span NO LONGER matches the cited section — the rule changed, so the user's keep-entry decision may need revisiting)

### FIX-SUBSUMED-residue [SYN-GATE]

Memory entry L has heading "Pathspec-scoped git commit drops staged chmod bits on Windows", Why: "git commit -- <paths> drops chmod changes from the index on Windows", How to apply: "After a pathspec commit, run `git update-index --chmod=+x <file>` for any file that needs the executable bit". The subsuming_quote from Task-4 is: "Use pathspec-scoped commands for all git operations — only reference files you are responsible for" citing shared/AGENTS.md § Git Staging. The verifier runs the subsumption test.

VERDICT: not-subsumed
MUST NOT: subsumed

(The reader must derive: the entry's How to apply carries an operational workaround — the `git update-index --chmod=+x` step — that the subsuming rule's principle does not contain; this is residue; the entry is not subsumed)

### FIX-SUBSUMED-beats-stale [SYN-RECONCILE]

Entry M is returned by Task-4 in BOTH subsumed_entries (with a subsuming_quote citing shared/AGENTS.md § Commit Conventions) AND stale_entries (its pattern grep fails). The five-way disposition runs.

VERDICT: subsumed-beats-stale
MUST NOT: surface-not-delete

(The reader must derive: the precedence rule — subsumed beats stale; an entry in both channels is dispositioned as subsumed, routed by § SYN-RECONCILE (removed on a `confirmed` verdict except a `human:` entry, otherwise the Phase 4b Remove/Keep/Defer), never deleted via the stale path)

### FIX-RECOVER-both-present [ORI-RECOVER]

The crash-recovery journal contains `{"rename":["user memory § Old heading","user memory § New heading"]}`. The sweep reads the config-repo memory file. Both "Old heading" and "New heading" exist as entry headings in the file.

VERDICT: no-op
MUST NOT: landed

(The reader must derive: rename truth table — A present (either B state) → didn't-land/ambiguous → no-op + surface)

### FIX-RECOVER-remove-unreadable [ORI-RECOVER]

The crash-recovery journal contains `{"remove":["project memory (~/work/api) § Deleted entry","pruned"]}`. The sweep attempts to read `~/work/api/memory/MEMORY.md` but the path is inaccessible (directory does not exist on this machine).

VERDICT: indeterminate
MUST NOT: landed

(The reader must derive: remove truth table — target file unreadable/absent → indeterminate → no-op + surface, never a landed report)

### FIX-RECOVER-rename-double-absent [ORI-RECOVER]

The crash-recovery journal contains `{"rename":["user memory § Gone A","user memory § Gone B"]}`. The sweep reads the config-repo memory file. Neither "Gone A" nor "Gone B" exists as an entry heading.

VERDICT: no-op
MUST NOT: landed

(The reader must derive: rename truth table — A absent AND B absent → no-op + surface)

### FIX-RECOVER-topic-removal-not-landed [ORI-RECOVER]

The crash-recovery journal contains `{"remove":["user memory § Old signal","expired_signal"]}`. The sweep reads the config-repo memory files. `memory/MEMORY.md` does not hold "Old signal", and `memory/topics/improvement-signals.md` still holds it as an entry heading.

VERDICT: no-op
MUST NOT: landed

(The reader must derive: the remove table's present row covers a target present in any of the user-memory files, and an `expired_signal` removal is not the `pruned` Move case — so the entry that is still in the topic file reads didn't-land, no-op + surface, never a landed report)

### FIX-RECOVER-store-backed-target [ORI-RECOVER]

The crash-recovery journal contains `{"remove":["project memory (~/work/api) § Deleted entry","pruned"]}`. `~/work/api` exists and holds no `memory/` directory; a store directory in the store repo carries a `STORE` file whose `local` line names `~/work/api`, and its `memory/MEMORY.md` no longer holds "Deleted entry".

VERDICT: landed
MUST NOT: indeterminate

(The reader must derive: the target file is the memory-class location `shared/skills/qdream/memory-rules.md § Resolution contract` returns, which is the store's file here — deriving `~/work/api/memory/MEMORY.md` finds nothing and reports indeterminate, so recovery silently under-recovers)

### FIX-DISCOVER-store-not-a-project [ORI-DISCOVER]

The store repo holds `Api-ab12cd/` with a `STORE` file whose `local` line names `~/work/api`, a `memory/MEMORY.md`, and a `plans/done/`. `~/work/api` exists, holds no `memory/` of its own and has no session in the window. The sweep runs discovery. Which project path(s) does discovery return for this store: `~/work/api` only (`workspace-path-only`), `~/.agent-playbook/stores/Api-ab12cd` only (`store-path-only`), or both (`both-paths`)?

VERDICT: workspace-path-only
MUST NOT: both-paths

(The reader must derive: `~/work/api` is discovered and the store directory is not; method C reads the `STORE` contents through the store resolver — never the directory name — and discovers a `local` store whose folder exists under that folder's real path)

### FIX-SPANSUB-new-conflict [SYN-RECONCILE]

Entry N carries `Governance-conflict: contradicts shared/AGENTS.md § Style & Output — adjudicated 2026-06-10: keep-entry` and `Governance-conflict-quote: "Use plain text for prose"`. Task-4 freshly detects N in governance_conflicts for the SAME section shared/AGENTS.md § Style & Output, but with governance_span: "Lead with the outcome: the first sentence after completing work should answer what happened" (a different rule in the same section). The reconciliation pass runs.

VERDICT: new-conflict
MUST NOT: suppress-re-raise

(The reader must derive: the fresh detection's governance_span is a genuinely different rule from the recorded quote — neither contains the other; this is a NEW conflict and proceeds to Phase 4b. The existing keep-entry record for the other span is handled separately by the re-raise predicate)

### FIX-SPANSUB-contained-suppress [SYN-RECONCILE]

Entry P carries `Governance-conflict: contradicts shared/AGENTS.md § Git Staging — adjudicated 2026-07-01: keep-entry` and `Governance-conflict-quote: "Never use git add -A or git add ."`. Task-4 freshly detects P in governance_conflicts for the same section with governance_span: "Never use git add -A or git add . Always stage specific files or paths that were part of the current task." (the recorded quote is contained within the fresh span). The reconciliation pass runs.

VERDICT: suppress-re-raise
MUST NOT: new-conflict

(The reader must derive: containment-based matching — the recorded Governance-conflict-quote IS contained within the fresh governance_span, so they match; the entry already carries a terminal keep-entry record for this same section; it is removed from the fresh set and routed ONLY by the re-raise predicate — which for keep-entry with a still-matching span stays silent)

### FIX-SUPPORTSET-indeterminate-blocks [SYN-HIGHERORDER]

A higher-order node has Support-set: ["project memory (~/work/api) § Pattern X", "session abc123"]. The sweep analyzed project ~/work/api this run and confirmed "Pattern X" is absent from its memory file. The session pointer is always indeterminate (session transcripts are not verified during reconciliation). The trigger check runs.

VERDICT: not-ungrounded
MUST NOT: ungrounded

(The reader must derive: the trigger requires EVERY pointer to be confirmed-absent AND zero indeterminate; the session pointer is indeterminate, which blocks the gate — the sweep cannot claim the node lost all its ground when there is ground it never checked)

### FIX-COUNTVERIFY-truncated [SYN-RECONCILE]

The memory file's entry headings are {H1, H2, H3, H4, H5, H6, H7, H8, H9, H10, H11}. Task-4's four class lists contain: unrelated: {H1, H2, H3}, not_a_conflict: {H4}, subsumed_entries: {H5, H6}, governance_conflicts: {H7, H8}. Task-4 self-reports task4_status: checked.

VERDICT: skipped-context-budget
MUST NOT: checked
script-tested: dream-sweep.py countverify-truncated

(The reader must derive: the four-class union is {H1..H8} = 8 headings, but the file has 11; the union is incomplete; the self-reported checked is overridden to skipped-context-budget regardless of the self-report)

### FIX-STALE-recheck-passing [SYN-GATE]

Task-4 returned entry Q in stale_entries with reason: "pattern grep for 'Result<T> wrapper' in src/ returned 0 hits". The Cross-validation verifier re-runs the grep: `grep -r 'Result<T> wrapper' src/` returns 3 hits (the pattern exists in src/api/handler.rs, src/lib/types.rs, src/tests/mock.rs).

VERDICT: recheck-passes
MUST NOT: confirmed

(The reader must derive: the verifier re-ran the quoted failing check and it PASSES now; the entry is NOT stale; verdict is refuted/plausible, NOT confirmed — autonomous deletion requires confirmed)

### FIX-MERGE-nonterminal-wins [APP-ADJUDICATE]

A dedup merge is collapsing two Governance-conflict records on entry R, both keyed to the same (shared/AGENTS.md § Memory Management, whitespace-normalized span). Record A: `adjudicated 2026-07-10: keep-entry`. Record B: `adjudicated 2026-07-10: rule-update-pending`. Same date.

VERDICT: nonterminal-wins
MUST NOT: keep-entry-wins

(The reader must derive: same-key records collapse to the most-recent by adjudicated date; same-day tie → the non-terminal state wins — rule-update-pending over keep-entry)

### FIX-FABRICATION-absent-quote [SYN-GATE]

A memory proposal's evidence_quote is "user said: always use SQLite for local storage". Its source is: session def456. The verifier opens session def456.jsonl (the file exists and is readable). The verifier searches the session content for the quoted string "always use SQLite for local storage" — it does not appear anywhere in the session transcript.

VERDICT: refuted
MUST NOT: confirmed

(The reader must derive: quote absent from a REACHABLE source → refuted/fabricated evidence; the source IS reachable — unlike the unreachable case where it would be indeterminate)

### FIX-EXPIRY-not-staleness [GAT-CLASSIFY]

Entry S is a `pattern` entry in project P's memory file, carrying `**Stale-after**: 2026-06-30`. Today's sweep runs on 2026-08-04, so the date has passed. P had no new session and no new plan. The manifest flags S `stale_after_passed`, so P's `memory_pass` is `flagged` and P gets a `Tasks 4-5 only` dispatch. Task 4 runs S's type-specific verification: `grep -r 'Result<T> wrapper' src/` returns 4 hits — the pattern is still in use. No governance rule is on point. The agent classifies every entry of the file, lists S's heading in `verified`, and returns task4_status: checked, and the count-verify passes.

VERDICT: reverify-not-stale
MUST NOT: stale

(The reader must derive: a fired Stale-after revokes the cheap pre-filter skip and forces the semantic re-open plus the type-specific check — it is NOT itself staleness evidence, and the manifest flag only sent P to be verified. The check PASSED, so entry S does not enter stale_entries and keeps its ordinary governance-relationship class, unrelated. Because the check passed, S's heading is in `verified`, and the file's task4_status is checked after the count-verify, the orchestrator re-dates Verified and clears the fired Stale-after — otherwise it re-fires every sweep while the frozen Verified date ratchets the entry toward the front of the criterion-5 prune order. An expiry date is a reason to look, never a verdict. Had the count-verify overridden the file to skipped-context-budget, or had S been missing from `verified`, nothing would be re-dated or cleared. S is project memory, so the user-memory `pattern` exception, where the expiry is the check, does not apply. S's `Verified` carries no `human:` actor, which is why the orchestrator re-dates it: with a `human:` actor the passing check would go to the user instead, as in FIX-EXPIRY-human-gate.)

### FIX-STALE-human-verified [SYN-STALE]

Entry T carries `**Verified**: 2026-07-16 (human:alice, grep)`. Task 4 returned it in stale_entries with reason "grep for 'legacy_auth_handler' in src/ returned 0 hits", `task4_status: checked` and the orchestrator's count-verify passes (the union of Task-4 class headings equals the file's entry headings). The Cross-validation verifier re-ran the quoted grep, got 0 hits, and returned a `confirmed` staleness verdict.

VERDICT: surface-not-delete
MUST NOT: autonomous-delete

(The reader must derive: gate conditions (a) count-verified checked and (b) confirmed verdict are BOTH satisfied, which would normally license autonomous deletion — but condition (c) blocks it because the entry's Verified carries a `human:` actor. It goes to § DEC-GATE as `Delete / Keep / Defer`, showing the failing grep alongside the human attestation. An agent's own re-check is not independent evidence against a person's confirmation.)

### FIX-STALE-user-memory [SYN-STALE]

User memory's `memory_pass` is `periodic`, so the topic file `memory/topics/powershell.md` got a `Tasks 4-5 only` dispatch of its own. Its entry U (`**Verified**: 2026-06-01 (sweep, plan-check)`) is a `decision` entry. The agent found the config repo's `plans/done/260801_DROP_FOO.md` reversing the decision, returned U in stale_entries quoting that plan-slug, classified U `unrelated`, and returned task4_status: checked; the count-verify passes. The verifier opened the plan and returned staleness verdict: confirmed.

VERDICT: autonomous-delete
MUST NOT: gate-item

(The reader must derive: conditions (a)-(d) of § SYN-STALE all hold and the tier does not change that; the older text of this note said a stale item from a user-memory entry was never deleted autonomously — the orchestrator never deletes a user-memory entry on the agent's finding alone — so U is surfaced in § DEC-GATE as `Delete / Keep / Defer` with the reversing plan shown.)

### FIX-STALE-fresh-conflict [SYN-STALE]

Project P's per-project sub-agent (`all tasks`) returned entry W in governance_conflicts, contradicting `shared/AGENTS.md § Git Staging` with its governance_span, and also in stale_entries with reason "grep for 'stage-by-hand' in scripts/ returned 0 hits". W carries no `Governance-conflict` record yet, and its `Verified` is `2026-05-02 (sweep, grep)`. task4_status is checked and the count-verify passes. The Cross-validation verifier re-ran the grep and returned staleness verdict: confirmed.

VERDICT: surface-not-delete
MUST NOT: autonomous-delete

(The reader must derive: conditions (a)-(d) of § SYN-STALE all hold, and W carries no non-terminal Governance-conflict record, so neither the four-condition gate nor the pending-conflict rule stops the delete. But W's heading is also in this sweep's governance_conflicts, and a contradiction is never staleness evidence: such a stale item is never deleted or salvage-rewritten autonomously. W goes to § DEC-GATE beside the conflict, which the user adjudicates.)

### FIX-DISPATCH-quiet [ORI-DISPATCH]

Four confirmed projects, from `manifest.json` and their side files, with no `errors[]` lines:
- P1: 2 sessions in `sessions[]`; `memory_pass` null.
- P2: no session, `plans.new_plans` empty; `memory_pass: flagged`, `memory_flags: [stale_after_passed]`.
- P3: no session, `plans.new_plans` empty; `quiet_sweeps: 4`, `memory_pass: periodic`, `memory_flags: []`.
- Q: no session, `plans.new_plans` empty; a `memory_file`, `quiet_sweeps: 2`, `memory_pass` null, `memory_flags: [cited_paths_missing, cited_slugs_missing]` (three entries cite paths or slugs the script could not find); two items in `plans.accept_and_note`.

The dispatch list is built. What does Q get?

VERDICT: no-agent
MUST NOT: tasks-4-5-only
script-tested: dream-sweep.py dispatch-quiet

(The reader must derive: Q has no session and no new plan, so it gets no `all tasks` agent. Its memory_pass is null: a missing cited path or slug is an input for a dispatched agent, never a trigger by itself, and Q's counter is below 4. So Q is quiet — no agent, not stamped (reason quiet) — and the Gather phase agent still harvests its two accept_and_note items. The whole list: P1 `all tasks`; P2 and P3 `Tasks 4-5 only` with their entries' flags; Q no agent; P2, P3 and Q get the Gather phase agent's harvest.)

### FIX-HARVEST-quiet [SYN-GATE]

Quiet projects A, B and C got no `all tasks` agent this sweep. The Gather phase agent's harness harvest built 11 `HARNESS_HARVEST:` signals for A, 2 for B and 1 for C, and sent all 14 to one harvest verifier batch. The verifier spot-checked the evidence_quote of 10 items against their plan files, all 10 of them A's, and returned verdicts for those 10 only. Did the batch meet its spot-check coverage floor?

VERDICT: floor-not-met
MUST NOT: floor-met

(The reader must derive: inside a harvest batch the floor is counted per member project, never over the batch. A carries 11 items, so at least 10 of A's must be checked, which holds. B and C carry 10 or fewer each, so every one of their items must be checked, and none was. Ten checks would meet a batch-wide reading of the floor, but not the per-project one. B's and C's items got no verdict, so each defaults to refuted for its own project: not written, not promoted, and not recorded in rejected_lessons.)

### FIX-DISPATCH-user-memory-flagged [ORI-DISPATCH]

User memory, from the manifest's `user_memory` block: `memory_pass: flagged`, `quiet_sweeps: 2`, no top-level `errors[]` line. `user_memory.json` lists two files. `file_flags`: `memory/topics/powershell.md` → `[stale_after_passed]` (one `pattern` entry's `Stale-after` has passed); `memory/topics/git.md` → `[cited_paths_missing]` (one entry cites a path the script could not find). The dispatch list is built. What does `memory/topics/git.md` get?

VERDICT: no-agent
MUST NOT: tasks-4-5-only
script-tested: dream-sweep.py dispatch-user-memory-flagged, dispatch-user-memory-flagged-at-four

(The reader must derive: a `flagged` user memory whose counter is below 4 dispatches only the files whose `file_flags` hold a trigger flag, `stale_after_passed`, `stale_when_fired` or `governance_conflict_open`. A missing cited path is an input for a dispatched agent, never a trigger, so git.md gets no agent. Exactly one dispatch: `Tasks 4-5 only` for powershell.md. Had `quiet_sweeps` been 4 or more, both files would be dispatched, as for `periodic`.)

### FIX-STALE-user-memory-keep [APP-ADJUDICATE]

Sweep N, on 2026-08-04. The manifest's `user_memory` block: `memory_pass: flagged`, `quiet_sweeps: 6`, no top-level `errors[]` line. `user_memory.json` lists three files: `memory/MEMORY.md`, `memory/topics/powershell.md` and `memory/topics/git.md`. Only powershell.md's `file_flags` hold a trigger flag: its entry E, a `pattern` entry with `**Verified**: 2026-01-10 (sweep, grep)`, carries `**Stale-after**: 2026-06-30`. The dispatch list was built per `sweep-orient.md § ORI-DISPATCH`, and every dispatched agent returned task4_status: checked, each count-verified. The powershell.md agent returned E in stale_entries with reason quoting the passed `Stale-after`, `expiry_fired: true`, and E's heading in `verified`; no other check failed. E was surfaced at § DEC-GATE, the user chose `Keep`, and the sweep finished. Sweep N+1 runs with no new session or plan for the config repo and no other flag on any user-memory entry. What does user memory get in sweep N+1?

VERDICT: no-agent
MUST NOT: tasks-4-5-only

(The reader must derive: in sweep N the counter was 4 or more, so the flagged pass dispatched every file, not only powershell.md, and every file came back checked, so § APP-STATE wrote `quiet_sweeps.user_memory` 0. E is an expiry-only user-memory stale item, so the user's `Keep` was not a no-op: E's `Verified` became 2026-08-04 with a `human:<id>` actor naming the user and no method, and its fired `Stale-after` line was removed; the user's `Keep` is the verification, so the autonomous re-dating conditions do not govern it. In sweep N+1, E carries no trigger flag and the counter is below 4, so `memory_pass` is null: no agent. Without the every-file dispatch the counter would have risen to 7 and forced a periodic pass; without the re-date E would be flagged and surfaced again every sweep.)

### FIX-STATE-tasks45-unread-session [APP-STATE]

Project Q has a memory file and no new plan. The manifest lists Q with an empty `sessions[]`, `memory_pass: periodic`, and one `errors[]` line saying a Claude transcript of Q could not be read. Q got a `Tasks 4-5 only` dispatch. Its agent returned with `error` null, `project_accessible` true and `task4_status: checked`, count-verified. At § APP-STATE, is Q stamped with `snapshot_at`?

VERDICT: not-stamped
MUST NOT: stamped
script-tested: dream-write.py state-fix-tasks45-unread-session; dream-sweep.py coverage-unreadable-manifest-named

(The reader must derive: the manifest leaves an unread session out of `sessions[]`, so the empty list does not mean Q had nothing to read. A project whose `errors[]` names a transcript or session the script could not read is not covered, and the `Tasks 4-5 only` coverage rule requires that no such line exists. Q keeps its old `last_analyzed`, so the next manifest offers the unread session again. Its `quiet_sweeps` is still written: 0, since its file came back checked.)

### FIX-STATE-quiet-counter-defer [APP-STATE]

Project P1 has a memory file; the manifest emits `quiet_sweeps: 1` for it. P1 had a new session, so it got an `all tasks` dispatch, and its file came back `task4_status: checked`, count-verified. At § DEC-GATE the user chose `Defer` on a subsumption candidate from P1's file. What does § APP-STATE write to `quiet_sweeps.projects` for P1?

VERDICT: counter-4
MUST NOT: counter-0
script-tested: dream-write.py state-fix-quiet-counter-defer

(The reader must derive: a checked file would reset the counter to 0, but a user `Defer` on a subsumption candidate or a stale entry overrides both branches and writes 4, so the next sweep runs P1's periodic pass and re-surfaces the deferred item even if P1 has no new session.)

### FIX-STATE-quiet-counter-budget [APP-STATE]

Project P2 has a memory file and no new session or plan; the manifest emits `quiet_sweeps: 4` and `memory_pass: periodic`. Its `Tasks 4-5 only` agent returned `task4_status: checked`, but the union of its four class lists is missing two of the file's entry headings in the manifest. No `Defer` was chosen for P2. What does § APP-STATE write for P2's counter?

VERDICT: counter-plus-1
MUST NOT: counter-0
script-tested: dream-write.py state-fix-quiet-counter-budget

(The reader must derive: the count-verify turns the self-reported `checked` into `skipped-context-budget`, so the file was not checked and the counter becomes the emitted value + 1, which is 5. A truncated pass does not buy five more sweeps without a check.)

### FIX-STATE-quiet-counter-failed [APP-STATE]

Project P3 has a memory file; the manifest emits `quiet_sweeps: 2`. P3 had a new session and got an `all tasks` dispatch, but the agent failed, and the user chose `Skip` at the Retry / Skip / Abort gate. P3 is not stamped. What does § APP-STATE write for P3's counter?

VERDICT: counter-plus-1
MUST NOT: counter-unchanged
script-tested: dream-write.py state-fix-quiet-counter-failed

(The reader must derive: every confirmed project with a memory file gets a counter write, stamped or not. A failed or skipped agent is not a checked file, so the counter becomes the emitted value + 1, which is 3. Only a project declined or excluded at the confirm list keeps its stored value unchanged.)

### FIX-STATE-quiet-counter-quiet [APP-STATE]

Project P4 was confirmed at the confirm list. It has a memory file, no new session, no new plan, and the manifest emits `quiet_sweeps: 1` with `memory_pass` null, so it got no agent and is not stamped (reason `quiet`). What does § APP-STATE write for P4's counter?

VERDICT: counter-plus-1
MUST NOT: counter-unchanged
script-tested: dream-write.py state-fix-quiet-counter-quiet

(The reader must derive: a quiet project is still a confirmed project with a memory file, so its counter is written as the emitted value + 1, which is 2. Leaving it unchanged would stop the cadence from ever reaching the periodic pass.)

### FIX-STATE-quiet-counter-checked [APP-STATE]

Project P5 has a memory file and no new session or plan; the manifest emits `quiet_sweeps: 4` and `memory_pass: periodic`. Its `Tasks 4-5 only` agent returned `task4_status: checked`, and the count-verify against the manifest's entry headings passes. No `Defer` was chosen for P5. What does § APP-STATE write for P5's counter?

VERDICT: counter-0
MUST NOT: counter-plus-1
script-tested: dream-write.py state-fix-quiet-counter-checked

(The reader must derive: a file checked after the count-verify resets the counter to 0 whatever the dispatch scope; `Tasks 4-5 only` counts the same as `all tasks`. P5 is also stamped, since its errors[] names no unread transcript.)

### FIX-STATE-quiet-counter-user-memory [APP-STATE]

The manifest's `user_memory` block reads `memory_pass: flagged`, `quiet_sweeps: 5`. `user_memory.json` lists three files; only one carries a trigger flag. The dispatch list was built per `sweep-orient.md § ORI-DISPATCH`, and every dispatched agent returned `task4_status: checked`, each count-verified. No `Defer` was chosen on a user-memory item. What does § APP-STATE write to `quiet_sweeps.user_memory`?

VERDICT: counter-0
MUST NOT: counter-plus-1
script-tested: dream-write.py state-fix-quiet-counter-user-memory

(The reader must derive: a `flagged` user memory with its counter at 4 or more dispatches every file, as for `periodic`, and a pass that dispatched every file with every file checked resets the counter to 0. Had the counter been below 4, only the flagged file would have been dispatched, and even with it checked the counter would count + 1.)

### FIX-STATE-quiet-counter-removed [APP-STATE]

Project R's path no longer exists. The confirm list showed R as removed and the user acknowledged it. The stored state holds `projects[R]` and `quiet_sweeps.projects[R]: 3`. What happens to R's `quiet_sweeps` key at § APP-STATE?

VERDICT: key-dropped
MUST NOT: counter-plus-1
script-tested: dream-write.py state-fix-quiet-counter-removed

(The reader must derive: a removed project the user acknowledged is deleted from `projects`, and its `quiet_sweeps.projects` key is deleted with it. It is not a confirmed project with a memory file, so no counter is written for it.)

### FIX-SIGNAL-insession-skip [SYN-PROMOTE]

Session X (2026-10-07, project alpha, Claude Code) has no project file. Mid-session the agent proposed, per `memory-rules.md § Plan-less governance capture`, a `Save / Skip` row `[improvement_signal] /qplan re-asks the tier question after the user answered it`, targeting `shared/skills/qplan/SKILL.md`, with `Sessions: in-session 2026-10-07 X, alpha`. The user replied "skip". Later in X the user says again "this skill keeps asking me the same thing". Session Y (2026-10-07, project beta) shows the same /qplan friction. Nothing was written in-session. The 2026-10-08 sweep reads X and Y; the verifier confirms Y's signal. No prior `rejected_lessons` record matches. What happens to this signal at § SYN-PROMOTE and § APP-STATE?

VERDICT: user-skip-recorded
MUST NOT: promoted

(The reader must derive: alpha's sub-agent returns the X signal only in `user_skipped`, with the proposal heading and the "skip" turn quoted, never in `improvement_signals`. At § SYN-PROMOTE the "user-skipped first" rule drops every signal matching this sweep's `user_skipped` list (same `target_file`, equivalent concern) before the frequency gate and before below-threshold persistence, so Y's matching signal is dropped too: X and Y would otherwise union to 2 sessions and promote. The prior-sweep `rejected_lessons` consult cannot catch it, since no record exists yet. At § APP-STATE a `rejected_lessons` record `{target: shared/skills/qplan/SKILL.md, signal: <the heading>, reason: skipped, date: 2026-10-08}` is appended, so later sweeps suppress it for 60 days through the normal consult. Nothing is written to `memory/topics/improvement-signals.md`: persisting the signal below threshold would be wrong too.)

### FIX-SIGNAL-expired [SYN-PROMOTE]

A full sweep runs on 2026-10-09. `memory/topics/improvement-signals.md` holds three below-threshold signals. Signal A has `**Frequency**: 1 (below threshold)` and `**Last observed**: 2026-06-01`, and no session this sweep re-observes it. Signal B has `**Frequency**: 1` and `**Last observed**: 2026-06-01`, and this sweep re-observes it in a new session dated 2026-10-02. Signal C has `**Frequency**: 3` and `**Last observed**: 2026-05-01`. No `rejected_lessons` record matches any of them. What happens to A, B and C?

VERDICT: expired-signal-removed
MUST NOT: pruned

(The reader must derive: A is a stale singleton, at `Frequency 1` and last observed more than 90 days before the sweep, so § SYN-PROMOTE removes it as removal class `expired_signal`, journal-first (record its `user memory § <heading>` target with the class, flush, then delete), and the Report's `Deleted` line names it. It is not a Size-check prune, so the class is not `pruned`. B is re-observed first: its `Sessions` gains the new session, `Frequency` becomes 2 and `Last observed` is re-dated to 2026-10-02, so it does not expire and reaches the frequency gate at 2 sessions. C never expires, because only a `Frequency 1` signal does, whatever its age.)

### FIX-EXPIRY-human-gate [GAT-CLASSIFY]

Entry H is a `feedback` entry in project P's memory file, carrying `**Verified**: 2026-03-02 (human:alice)` and `**Stale-after**: 2026-07-01`. Today's sweep runs on 2026-08-04, so the date has passed. P had no new session and no new plan. The manifest flags H `stale_after_passed`, so P's `memory_pass` is `flagged` and P gets a `Tasks 4-5 only` dispatch. Task 4 runs H's type-specific check: the artifact H names, `scripts/deploy.sh`, still exists. No governance rule is on point. The agent classifies every entry of the file, lists H in `verified` as `{"heading": "H", "expiry": "Stale-after"}`, and returns task4_status: checked; the count-verify passes. H is not merged, renamed or removed this sweep. What does the orchestrator do with H at Re-dating?

VERDICT: human-expiry-gated
MUST NOT: reverify-not-stale

(The reader must derive: the check passed and H is expiry-forced, but its current `Verified` carries a `human:` actor, so the orchestrator neither re-dates `Verified` nor clears `Stale-after`. It adds `{H, file, Stale-after, "2026-07-01", no method}` to `human_expiries`, which § DEC-GATE surfaces as `Keep / Re-date-as-sweep / Defer`. The conditions of the autonomous re-date are met (listed in `verified`, not in `stale_entries`, file checked after the count-verify), so the routing applies. Compare FIX-EXPIRY-not-staleness, where the entry carries no `human:` actor and is re-dated.)

### FIX-EXPIRY-human-flag-only-key [GAT-CLASSIFY]

Entry N is a `decision` entry in project P's memory file, carrying `**Verified**: 2026-03-02 (human:alice)` and `**Stale-after**: 2026-07-01`. Today's sweep runs on 2026-08-04. The manifest flags N `stale_after_passed`, so P gets a `Tasks 4-5 only` dispatch. Task 4 runs N's type-specific check: the artifact N names still exists. The agent lists N in `verified` as the bare heading `"N"`, with no `expiry` key, and returns task4_status: checked; the count-verify passes. N is not merged, renamed or removed this sweep. What does the orchestrator do with N at Re-dating?

VERDICT: human-expiry-gated
MUST NOT: reverify-not-stale

(The reader must derive: a check is expiry-forced when its `verified` object carries `expiry` or when the manifest set `stale_after_passed` or `stale_when_fired` on the entry, and the two signals resolve toward the gate when they disagree. The manifest flag alone forces N's check, so the missing `expiry` key changes nothing. N's `Verified` carries a `human:` actor, so the orchestrator neither re-dates it nor clears `Stale-after`: it adds `{N, file, Stale-after, "2026-07-01", no method}` to `human_expiries`. An orchestrator that keys only on the agent's `expiry` key would re-date N as `sweep` and drop the human mark silently.)

### FIX-EXPIRY-human-precedence-pattern [SYN-STALE]

User memory's `memory_pass` is `periodic`, so the topic file `memory/topics/powershell.md` got a `Tasks 4-5 only` dispatch. Its entry U is a `pattern` entry with `**Verified**: 2026-01-10 (human:alice)` and `**Stale-after**: 2026-06-30`. Today is 2026-08-04. A user-memory dispatch has no project tree, so the agent found no codebase check to run: U's fired `Stale-after` is its type-specific check. It returned U in `stale_entries` with reason quoting the fired `Stale-after`, `expiry_fired: true` and `entry_verified` carrying `human:alice`, and returned task4_status: checked; the count-verify passes. The verifier re-ran the check and returned staleness verdict: confirmed. Where does U go this sweep?

VERDICT: surface-not-delete
MUST NOT: human-expiry-gated

(The reader must derive: for a user-memory `pattern` entry the fired expiry is the check, so U is a stale item, not a passing check. It is surfaced at § DEC-GATE as a stale entry, `Delete / Keep / Defer`, showing the fired field beside the `human:` actor; a user-memory item is never deleted autonomously, and gate condition (c) also blocks it. Because U is in `stale_entries`, precedence keeps it out of `human_expiries`: it gets one gate item, not two. Rule (d) of § SYN-STALE keeps expiry-only items out of `stale_entries` except for this user-memory `pattern` case.)

### FIX-EXPIRY-human-precedence-subsumed [SYN-RECONCILE]

Project P's `all tasks` agent returned entry K, a `feedback` entry with `**Verified**: 2026-02-11 (human:alice)` and `**Stale-after**: 2026-07-01`, in `subsumed_entries` (subsuming_quote cited from `shared/AGENTS.md § Commit Conventions`) and also in `verified` as `{"heading": "K", "expiry": "Stale-after"}`; its forced check passed. Today is 2026-08-04. task4_status is checked and the count-verify passes. The verifier returned `confirmed` for the subsumption. K is not merged, renamed or removed in § SYN-WRITE. How many § DEC-GATE items does K produce this sweep?

VERDICT: one-gate-item
MUST NOT: human-expiry-gated

(The reader must derive: the orchestrator builds `human_expiries` as the last step of § SYN-RECONCILE, and a heading with a subsumption item that reaches § DEC-GATE never enters it. K produces exactly one item: the subsumption candidate, `Remove / Keep / Defer`. K's expiry fires again at its file's next pass if K is still there. A second item for the same entry could collide in Phase 5, a `Remove` then a gate `Keep` re-dating an entry that no longer exists.)

### FIX-EXPIRY-human-precedence-reraised [SYN-RECONCILE]

A full sweep runs on 2026-08-04. Project P's memory file holds entry R, a `feedback` entry with `**Verified**: 2026-02-11 (human:alice)` and `**Stale-after**: 2026-07-01`. R also carries `**Governance-conflict**: contradicts shared/AGENTS.md § Git Staging — adjudicated 2026-07-05: rule-update-pending` and a `Governance-conflict-quote`. That record is non-terminal, so the manifest flags P `governance_conflict_open` and P is dispatched. The agent did not return R in `governance_conflicts`: the fresh detection was subtracted as already adjudicated. It listed R in `verified` as `{"heading": "R", "expiry": "Stale-after"}`; its forced check passed. task4_status is checked and the count-verify passes. R is not merged, renamed or removed in § SYN-WRITE. How many § DEC-GATE items does R produce this sweep?

VERDICT: one-gate-item
MUST NOT: human-expiry-gated

(The reader must derive: the orchestrator builds `human_expiries` as the last step of § SYN-RECONCILE, after the re-raise scan, and a heading carrying a recorded adjudication that the scan re-raises never enters it. A `rule-update-pending` record is re-raised every sweep unconditionally, so R produces exactly one item, the re-raised conflict at the Phase-4b conflict gate. R is not re-dated and its `Stale-after` is not cleared this sweep. The expiry fires again at P's next pass while R is still there.)

### FIX-EXPIRY-human-precedence-terminal [SYN-RECONCILE]

A full sweep runs on 2026-08-04. Project P's memory file holds entry T, a `feedback` entry with `**Verified**: 2026-02-11 (human:alice)` and `**Stale-after**: 2026-07-01`. T carries `**Governance-conflict**: subsumed by shared/AGENTS.md § Commit Conventions — adjudicated 2026-06-20: subsumption-kept` and a `Governance-conflict-quote` that still appears, whitespace-normalized, inside that section. P's `all tasks` agent returned T in `subsumed_entries` with a `governance_span` equal to the recorded quote, and also in `verified` as `{"heading": "T", "expiry": "Stale-after"}`; its forced check passed. task4_status is checked and the count-verify passes. T is not merged, renamed or removed in § SYN-WRITE. Which § DEC-GATE item does T produce this sweep?

VERDICT: human-expiry-gated
MUST NOT: one-gate-item

(The reader must derive: § SYN-RECONCILE removes the fresh subsumption detection from the fresh set, because T already carries a terminal `subsumption-kept` record for the same absorbing section whose quote still matches, and the re-raise predicate stays silent. T therefore has no subsumption item at § DEC-GATE. The precedence rule counts only items that actually reach the gate, so as the last step of the pass the orchestrator adds T to `human_expiries`, and T's one item is the human-attested expiry, `Keep / Re-date-as-sweep / Defer`. An orchestrator that keys the exclusion on what the agent returned in `subsumed_entries` would count the suppressed detection as T's one item, keep T out of `human_expiries`, and never surface the expiry. Compare FIX-EXPIRY-human-precedence-subsumed, where the subsumption is un-adjudicated and does reach the gate.)

### FIX-EXPIRY-human-precedence-workingmap [SYN-WRITE]

A full sweep runs on 2026-08-04. Project P's `memory/MEMORY.md` is not git-tracked (a solely-owned file: a folder the store resolver creates no store for) and holds 31 entries. Entry J carries `**Verified**: 2026-02-11 (human:alice)`, `**Stale-after**: 2026-07-01` and `**Outcome**: recurred 2026-06-10`, and has `Usage: 0`. The other 30 entries pass verification, carry no `Outcome`, and have `Usage` 2 or more. The agent returned J in `verified` as `{"heading": "J", "expiry": "Stale-after"}`: its forced check passed. task4_status is checked and the count-verify passes. The Size check prunes the lowest-ranked entry. What happens to J's expiry at the Re-dating step?

VERDICT: gate-skipped
MUST NOT: human-expiry-gated

(The reader must derive: the Size check runs at § SYN-WRITE, before the count-verify. The file is over the ~30 count, J ranks first in the derived-utility order on criterion (2), `Outcome: recurred`, and a `human:` actor is only a tiebreak at criterion (5), so the Size check prunes J and records it in the working map as removed, class `pruned`. A heading removed in § SYN-WRITE this sweep, whatever the class, never enters `human_expiries`, so there is no gate item and no re-date. The existing human-attestation carve-out does not exclude an entry from the Size-check prune.)

### FIX-EXPIRY-human-precedence-duplicate [SYN-RECONCILE]

A full sweep runs on 2026-08-04. An earlier `Move` was interrupted between its two writes, so the heading of entry D now appears in both `memory/MEMORY.md` and `memory/topics/ci.md`, and the manifest reports the error `duplicate heading across user-memory files` naming both files. <!-- verify-links: skip memory/topics/ci.md --> D is a `feedback` entry with `**Verified**: 2026-04-02 (human:alice)` and `**Stale-after**: 2026-07-15`. The user-memory dispatch returned D in `verified` as `{"heading": "D", "expiry": "Stale-after"}`; its forced check passed. task4_status is checked for both files and the count-verify passes. D is not merged, renamed or removed in § SYN-WRITE, and it is in no Task-4 class other than `unrelated`. How many § DEC-GATE items does D produce this sweep?

VERDICT: one-gate-item
MUST NOT: human-expiry-gated

(The reader must derive: a duplicate-heading item is a § DEC-GATE item for the heading, so D never enters `human_expiries`. D produces exactly one item, `Delete <file A> copy / Delete <file B> copy / Keep both / Defer?`, showing both copies. A second item for the same heading could collide in Phase 5: a `Delete <file> copy` executes against one file while a gate `Keep` would re-date a copy that no longer exists. D is not re-dated and its `Stale-after` is not cleared this sweep. If both copies stand next sweep, the expiry fires again then.)

### FIX-EXPIRY-human-keep [APP-ADJUDICATE]

A full sweep on 2026-08-04 surfaced Human-attested expiry #1 at § DEC-GATE: entry E, a `feedback` entry in project P's memory file, with `**Verified**: 2026-03-02 (human:alice, grep)` and `**Stale-after**: 2026-07-01`. The check passed and returned method `plan-check`. The user, whose id is `alice`, chose `Keep`. § APP-ADJUDICATE re-reads E from disk and finds it unchanged since the gate showed it. What are E's `Verified` line and `Stale-after` line after Phase 5?

VERDICT: human-keep-redated
MUST NOT: sweep-redated

(The reader must derive: `Keep` is the user re-attesting. `Verified` becomes `2026-08-04 (human:alice)` with no method, even though the check returned `plan-check`: the user's `Keep` is the verification, not the agent's method. The fired `Stale-after` line is removed. The edit is in place; nothing is journalled. The Report's `Updated:` line counts it as user-gated.)

### FIX-EXPIRY-human-redate [APP-ADJUDICATE]

A full sweep on 2026-08-04 surfaced Human-attested expiry #2 at § DEC-GATE: entry F, a `decision` entry in project P's memory file, with `**Verified**: 2026-03-02 (human:alice)` and `**Stale-when**: claude-code version > 2.30`, which the manifest flagged `stale_when_fired`. The check passed and returned method `artifact-check`. The user chose `Re-date-as-sweep`. § APP-ADJUDICATE re-reads F from disk and finds it unchanged since the gate showed it. What are F's `Verified` line and `Stale-when` line after Phase 5?

VERDICT: sweep-redated
MUST NOT: human-keep-redated

(The reader must derive: `Verified` becomes `2026-08-04 (sweep, artifact-check)`, with the method the check returned, and the fired `Stale-when` line is removed. The `human:` mark is dropped on the user's say-so. The edit is in place; nothing is journalled. The Report's `Updated:` line counts it as user-gated.)

### FIX-EXPIRY-human-defer [APP-ADJUDICATE]

A full sweep on 2026-08-04 surfaced Human-attested expiry #3 at § DEC-GATE: entry G, a `feedback` entry in project P's memory file, with `**Verified**: 2026-03-02 (human:alice, grep)` and `**Stale-after**: 2026-07-01`. The check passed. The user chose `Defer`. What are G's `Verified` line and `Stale-after` line after Phase 5?

VERDICT: deferred-unchanged
MUST NOT: human-keep-redated

(The reader must derive: `Defer` changes nothing. `Verified` stays `2026-03-02 (human:alice, grep)` and `Stale-after: 2026-07-01` stays, so the item returns when the expiry next forces a check. There is no `Delete` action at this gate: a fired expiry is never staleness evidence. Nothing is counted in `Updated:`.)

### FIX-MERGE-human-lapse-verifying [SYN-WRITE]

A full sweep on 2026-08-04. Entry R in project P's memory file has `**Verified**: 2026-05-20 (human:alice)`. A confirmed sub-agent proposal on the same subject is merged into R by the dedup check. The merge includes a type-specific check: the orchestrator greps for the pattern R names and finds it. R keeps its heading. The Report is being assembled. Does the Report name R?

VERDICT: lapse-reported
MUST NOT: silent-merge

(The reader must derive: the merge included a real verification, so the surviving `Verified` is `2026-08-04 (sweep, grep)`: the merged text is new, and the old `human:` mark no longer vouches for it. The merge rule is unchanged. § SYN-WRITE records R's heading because the surviving `Verified` no longer carries the `human:` actor the replaced entry carried, and the Report's `Attestations lapsed on merge` line names R with the instruction to re-attest.)

### FIX-MERGE-human-lapse-nonverifying [SYN-WRITE]

A full sweep on 2026-08-04. Entry Q in the config repo's `memory/MEMORY.md` has `**Verified**: 2026-05-20 (human:alice)`. A confirmed proposal on the same subject carries `**Verified**: 2026-07-28 (sweep)`. The dedup check merges it into Q, and no type-specific check runs. Q keeps its heading. Does the Report name Q?

VERDICT: lapse-reported
MUST NOT: silent-merge

(The reader must derive: a non-verifying merge keeps the more recent `Verified` date together with its own annotation, so the surviving line is `2026-07-28 (sweep)` and the `human:` actor of the older date is gone. The date and actor pair is never recombined. That is a lapse even though no check ran, so § SYN-WRITE records Q's heading and the Report's `Attestations lapsed on merge` line names it.)

### FIX-GATE-self-contained [DEC-GATE]

A full sweep's Synthesize phase agent ended with `handoff/synthesize.json` and `handoff/gate.md`, and both pass `handoff check`. Gate item G3 proposes a change to `shared/AGENTS.md § Commit Safety` in the config repository. Its extracted draft, `sweep/drafts/D02.json`, joined to G3 through its record's `data` file, holds a `current_text` of nine lines, one of which contains a `"` character, and a `new_text` of eleven lines. In `gate.md`, G3's `File:` line reads `this repo shared/AGENTS.md § Commit Safety`; its `Current text:` line quotes only the first and the last of the nine lines, joined by `[…]`; its `New text:` line holds the eleven lines verbatim. Every other item's texts appear verbatim in `gate.md`. The orchestrator is about to present the gate. What happens to G3?

VERDICT: phase-failure-not-shown
MUST NOT: presented-as-written

(The reader must derive: approved text is the written text. Only `dream-sweep.py gate` writes `gate.md`, rendering each drafted text whole from the extracted draft, and `dream-sweep.py decisions` copies an Applied item's texts into `decisions.json` from that draft, never from `gate.md`, after checking that each appears verbatim in the item's `gate.md` text. A G3 block that quotes only two of nine lines is not the script's render: `handoff check gate.md`, which the orchestrator runs before presenting the gate, refuses a `gate.md` that differs from what `gate` wrote, and the verbatim check refuses G3's `current_text`. So the item is not presented: it is a child failure of the Synthesize phase under `sweep-handoff.md § Failure gate`, a first failure, so the orchestrator reports it, writes a `decision-<n>.json` answering `Retry` and relaunches the phase once. It does not show G3 as written, and it does not repair the quote itself. The `this repo` wording also breaks the gate item format, which wants repository names in full, but the verbatim check alone decides.)

### FIX-PHASE-needs-decision [SYN-GATE]

A full sweep runs on Claude Code. The Synthesize phase agent, attempt 1, rendered verifier briefs V01 and V02 at § SYN-GATE and launched both in one message. V01 returned and `extract` accepted its verdicts. V02 did not: `dream-sweep.py wait` shows V02 `no-final-message`, its last record 25 minutes old. This is V02's first failure in this sweep. The phase agent's last `context` reading is far under its limit, after 40 tool calls. Project P2's three memory proposals depend on V02's verdicts. What does the phase agent do?

VERDICT: write-needs-decision-and-end
MUST NOT: ask-retry-skip-abort

(The reader must derive: a child whose last record is more than 10 minutes old has failed. A phase agent never asks, waits for a reset or retries a child on its own. It records V02 as failed in `progress-synthesize.json`, writes `needs-decision-<n>.json` of kind `failure` (step `SYN-GATE`, the kind's fixed options, a recommendation, `resume_from` `SYN-GATE`), runs `handoff check` on it, and ends without writing `synthesize.json` or `gate.md`. The Failure gate is the orchestrator's: on this first failure it relaunches the phase once, which dispatches V02 again as attempt 2; only a second consecutive failure asks the user `Retry / Skip / Abort`. P2's proposals are not downgraded to `Save / Skip`: that follows only a user `Skip`.)

### FIX-PHASE-wait-children [ORI-DISPATCH]

A full sweep runs on Claude Code. The Gather phase agent launched its last batch, the task4 agents A06, A07 and A08 that `sweep/dispatch.json` lists, in one message. Completion notifications for A06 and A08 have arrived, and `extract` accepted both returns; none has arrived for A07. `dream-sweep.py wait --labels A06=<id>,A07=<id>,A08=<id>` exits 3: A06 and A08 are `final`, and A07 is `no-final-message` with its last record 4 minutes old. Every earlier batch is extracted. The phase agent has used 70 of its budget of about 150 tool calls. What does the phase agent do now?

VERDICT: keep-waiting
MUST NOT: write-output-now

(The reader must derive: the Dream Phase Agent Brief's termination condition in `sweep-handoff.md` holds only when every child's result is in context and `wait` reports a final message for every label of every batch. A label `no-final-message` whose last record is under 10 minutes old is still running, so the agent waits and runs `wait` again. It does not record A07 as failed, which needs a last record older than 10 minutes or a `wait` exit 3 because the transcript is another agent's, and it does not run `coverage` and write `gather.json` with A07 missing, nor end.)

### FIX-RETURN-notes-not-error [GAT-PLANS]

A full sweep's `all tasks` per-project agent analyzes project P. No plan archive was resolved for P, so Task 3 (§ GAT-PLANS) has nothing to read and is skipped. The agent reads P's two `normal` sessions, S1 and S2, in full, Task 4 gives every memory entry a class, and no failure archetype matches. It is about to write its return. Where does it record that no plan archive was resolved and Task 3 was skipped, and what does that do to P's stamp?

VERDICT: note-not-error
MUST NOT: error-blocks-stamp

(The reader must derive: the return has `error` null and `notes` naming the missing archive and the skipped task, and `dream-sweep.py coverage` stamps P. The script half is covered by the `dream-sweep.py` selftest cases `extract-error-vs-notes` and `coverage-notes-never-block`.)
