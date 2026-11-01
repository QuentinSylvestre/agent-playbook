# Project Memory — seedlab

## Feedback

### Reset the fixture seed before every integration run — except the nightly soak, which must carry the previous run's seed

Run `make seed-reset` before every integration run in this project, with one exception: the nightly soak (`make soak`) must run against the seed the previous soak left behind. Never reset the seed inside a soak window.

**Why**: The soak's drift detector measures how far this night's run has moved from the last one, so it needs the previous run's seed as its reference point. Resetting the seed before a soak silently re-bases the detector on the current run, and it then reports zero drift for as long as nobody resets again — the detector goes quiet rather than failing, so the loss is invisible until a real regression slips through.
**How to apply**: Reset in CI's integration stage only. The soak stage runs from a separate target that deliberately does not depend on `seed-reset`; if you add that dependency to make the stages uniform, the drift detector stops reporting and nothing errors.
**Source**: 260722_SEEDLAB_SOAK_DRIFT_BASELINE § Phase 3 | **Verified**: 2026-07-24 (human:alice)

## Decision

## Pattern

## Declined

<!-- Declination records: the user's Skip of an agent-initiated memory proposal. A live row suppresses re-proposal of that subject for 60 days. Sessions append rows only; the /qdream sweep prunes expired rows. Row format: - "<proposed heading>" — declined <YYYY-MM-DD> (<reason, if given>) -->
