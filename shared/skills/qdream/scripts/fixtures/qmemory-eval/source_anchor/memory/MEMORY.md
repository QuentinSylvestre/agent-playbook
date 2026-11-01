# Memory

## Feedback

### Session-anchored Source (should classify as anchored)

**Why**: Tests that a session anchor in Source is classified as anchored, with no other anchor field.
**How to apply**: Test.
**Source**: Session abc12345 — session anchor in Source | **Verified**: 2026-07-01

### Anchored plans/done Source with no section marker (should classify as anchored)

**Why**: Tests plans/done/<slug>.md without § section.
**How to apply**: Test.
**Source**: `plans/done/260101-1200_TEST_PLAN.md` (Phases 1-2 QA SKIP) | **Verified**: 2026-07-01

### Governance file § section Source (should classify as free-text)

**Why**: A governance file ref is NOT a re-openable anchor even with §.
**How to apply**: Test.
**Source**: `shared/skills/qdream/SKILL.md` § Phase 3 — updated 2026-07-14 | **Verified**: 2026-07-01

### Bare plan-slug Source with no plans/done path and no section (anchored under lenient slug detection)

**Why**: A bare plan-slug is re-openable, so it classifies as anchored — the former "free-text by design" limitation was lifted 2026-07-20 (it under-counted real anchors by ~89%).
**How to apply**: Test.
**Source**: 260101-1200_TEST_PLAN — from the exploration phase | **Verified**: 2026-07-01

### Verified carries an actor and method annotation (must still classify as anchored)

**Why**: Pins that the `Verified` actor/method annotation is discarded by the `" | "` split and cannot corrupt Source extraction.
**How to apply**: Test.
**Source**: `plans/done/260101-1200_TEST_PLAN.md` § Intent | **Verified**: 2026-07-28 (human:alice, anchor-reopen)
**Stale-after**: 2026-12-31
**Stale-when**: kiro-cli v3 replaces the v2 steering files

### Free-text Source with an anchor-shaped Verified tail (should classify as free-text)

**Why**: Pins that the `" | "` split discards the `Verified` tail; the session id in the tail would count as an anchor if it stayed in Source. The annotation is deliberately outside the Verified grammar, to model a malformed tail.
**How to apply**: Test.
**Source**: observed while reviewing a sweep report | **Verified**: 2026-07-28 (sweep, session abc12345)

### Legacy Provenance line beside a free-text Source (should classify as free-text)

**Why**: The retired `Provenance` field is not read as an anchor; only `Source` counts.
**How to apply**: Test.
**Source**: noticed during a manual review | **Verified**: 2026-07-01
**Provenance**: 260101-1200_TEST_PLAN § Intent
