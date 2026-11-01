# pair-2-heading-similar — expected outcome

**OUTCOME: two entries, and the pair is surfaced to the user.**

The harvested native entry is written as its **own** entry under `## Feedback`, alongside the existing
one. The near-duplicate pair is then surfaced at
`shared/skills/qdream/sweep-decide-apply.md § Phase 4b — Decisions § DEC-GATE` as `Merge / Keep both?`. The sweep
does **not** decide.

## Why

**Gate 0 (already harvested) does not fire.** The existing entry's `Source` is a plan-slug anchor
(`260722_SEEDLAB_SOAK_DRIFT_BASELINE § Phase 3`). It names neither the native file
(`feedback_fixture_seed_reset.md`) nor the legacy native ID (`fixture-seed-reset`) — this entry was
written in a session, not migrated, so the native entry has never been harvested.

**Gate 1 (translation-equivalence) does not fire.** Each side carries a load-bearing fact the other
lacks:

| Carried only by the **native** entry | Carried only by the **existing** entry |
|---|---|
| the seed lives in `tmp/seed.lock`, which survives a failed run, a cancelled run and a container restart | the nightly soak is an **exception** and must carry the previous run's seed |
| the replay comparator reads its baseline **by seed**, so a stale lock makes the suite go green against the previous run's baseline | resetting inside a soak window silently re-bases the drift detector, which then reports zero drift indefinitely |
| `make seed-reset` must be a separate step, not folded into the test target | the soak target deliberately does not depend on `seed-reset` |

Merging in either direction destroys one column. Worse, the two give **opposite instructions for one
case**: the native entry says reset before every integration run with no exception; the existing entry
says never reset inside a soak window. A merged entry is not merely thinner — for the soak it is wrong.

The temptation is real and is the point of the fixture: same type (`feedback`), same subject, same
command, and headings that share their first nine words. A dedup keyed on
`(type, normalized subject)` — which is exactly what
`shared/skills/qdream/memory-rules.md § Dedup Check Procedure` step 1 uses in the general case — calls
this a hit.

## After the user chooses

Either branch is terminal. `Merge` and `Keep both` both leave the native `Source` recorded on a live
entry, so gate 0 answers first on every later sweep and this pair is never raised again. Nothing is
persisted to make that true — it falls out of the `Source` line.

## FAIL if

- the two are merged, or either is dropped, or either heading is rewritten;
- **both are written but nothing is surfaced** — the user never learns the two disagree about the soak,
  which is the whole finding;
- the harvest asks the user *before* writing (keep-both is the fail-safe default, not a question);
- a `Defer` option is offered (this gate has none — `Keep both` is the no-op).
