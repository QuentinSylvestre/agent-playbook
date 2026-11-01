---
name: fixture-seed-reset
description: Reset the fixture seed before every integration run — a stale tmp/seed.lock makes the replay comparator pass against the wrong baseline
metadata:
  type: feedback
---

Run `make seed-reset` before every integration run in this project. The seed is not held in memory: it is written to `tmp/seed.lock`, and that file survives a failed run, a cancelled run, and a container restart.

**Why:** The replay comparator reads its baseline by seed, not by run id. A stale `tmp/seed.lock` therefore makes it compare the new run against the *previous* run's baseline, and the suite goes green while comparing the wrong two things. Nothing in the output says which baseline was used, so the failure is invisible in the log.

**How to apply:** `make seed-reset` deletes `tmp/seed.lock` and re-derives the seed from the fixture manifest. Run it as a separate step, not inside the test target — a test target that resets its own seed cannot be re-run against a captured baseline for debugging.
