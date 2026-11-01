# Higher-Order Memory

## Decision

### Grounded node — all checkable ground present

**Why**: Test node for grounded label (R>0, CA=0).
**How to apply**: Test.
**Source**: Session aaa11111 — induced by sweep | **Verified**: 2026-07-01
**Support-set**: [episodic_ledger #1, user memory § Entry one with anchor, 260101-1200_FIXTURE_PLAN § Intent]

### Weak node — some verified-gone ground alongside resolved

**Why**: Test node for weak label (R>0, CA>0).
**How to apply**: Test.
**Source**: Session bbb22222 — induced by sweep | **Verified**: 2026-07-01
**Support-set**: [episodic_ledger #2, user memory § Nonexistent heading gone, episodic_ledger #1]

## Pattern

### Ungrounded node — all checkable ground gone

**Why**: Test node for ungrounded label (R=0, CA>0).
**How to apply**: Test.
**Source**: induced by sweep | **Verified**: 2026-07-01
**Support-set**: [user memory § Deleted heading alpha, user memory § Deleted heading beta]

### Unverifiable node — only indeterminate pointers

**Why**: Test node for unverifiable label (R=0, CA=0, I>0).
**How to apply**: Test.
**Source**: induced by sweep | **Verified**: 2026-07-01
**Support-set**: [session abc12345, session def67890, project memory (SomeProject) § Some heading]

### No-support-set node — no Support-set line at all

**Why**: Test node for no-support-set label.
**How to apply**: Test.
**Source**: induced by sweep | **Verified**: 2026-07-01
