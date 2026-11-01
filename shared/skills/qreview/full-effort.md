# /qreview — Full effort

<!-- Read from shared/skills/qreview/SKILL.md when a review runs at Full effort: § Spawn brief contract (brief additions), § Verification phase and § Completeness critic. -->

## Brief additions

Append to every persona brief:

"Apply these analysis angles systematically: (1) line-by-line diff scan — read every added/removed/changed line for correctness; (2) removed-behavior audit — for every deleted or modified line, verify the old behavior is either preserved elsewhere or intentionally dropped; (3) cross-file caller/callee tracing — for every changed function/method signature or behavior, trace callers and callees to verify no contract is broken; (4) language-pitfall scan — check added/changed lines against classic pitfalls of the diff's language (see list below)."

Also append:

- **Plausible-by-default**: Do not refute a candidate for being "speculative" or "depends on runtime state" when the failure scenario is realistic. Concurrency races, nil on rare-but-reachable paths, falsy-zero, off-by-one on non-excluded boundaries — these are PLAUSIBLE, not REFUTED. Err on surfacing.
- **Language-pitfall catalog** (for angle 4): JS/TS (falsy-zero, `==` coercion, closure-captured `var` in loop, missing `await`); Python (mutable default args, late-binding closures, bare `except`); Go (nil-map write, range-var capture in goroutine pre-1.22, unchecked error); Java/Kotlin (autoboxing NPE, unchecked generic cast, ConcurrentModificationException); C/C++ (buffer overflow, use-after-free, signed overflow UB); Rust (unwrap in non-test code); SQL (string interpolation → injection); General (timezone/DST arithmetic, float equality, integer overflow). Flag any instance the diff introduces.

## Verification phase

After persona sub-agents return findings (per Sub-agent execution), dispatch one verifier sub-agent per finding in parallel. Each verifier operates independently with a precision bias — its job is to REFUTE.

**Corroboration substitutes for a verifier.** A finding raised independently by two or more personas counts as corroborated and needs no verifier; dispatch verifiers only for single-source findings. When dispatch cost or rate limits bite, single-source findings may share a verifier (at most five per verifier sub-agent); record the grouping in the review log.

**Verifier brief** (per finding):
- Receives: the finding text, the relevant source code, and the diff
- Stance: "Your goal is to refute this finding. Look for reasons it is wrong, inapplicable, or already handled. Return your verdict with evidence."
- **Refutation evidence gate**: A finding is REFUTED *only* when one of these conditions is met (all require quoting the actual code):
  - Factually wrong — the code does something different than claimed (quote the line)
  - Provably impossible — a type, constant, or invariant makes the failure scenario unreachable (show it)
  - Already handled in this diff — a guard, check, or fallback addresses the concern (cite it)
  - Pure style with no observable effect on behavior
  If none of these apply, the finding is PLAUSIBLE. "Speculative," "unlikely," or "would need runtime testing to confirm" are NOT valid refutation grounds.
- Returns exactly one of: **confirmed** / **plausible** / **refuted**, plus a one-sentence evidence line
- Tool surface: read-only; no sub-agent dispatch

**Disposition**: Keep findings rated confirmed or plausible. Drop findings rated refuted. The surviving findings list proceeds to the Completeness critic and then to the Findings table format. The refutation evidence gate above ensures that uncertain-but-realistic findings survive — the bar for REFUTED is evidence of impossibility, not absence of proof.

## Completeness critic

After the Verification phase, dispatch one critic sub-agent that receives all surviving findings plus the full diff.

**Critic brief**:
- "What categories of issue were not examined? What files in the diff received no findings? Identify gaps in review coverage."
- Returns: a list of informational gaps (no severity, no resolution — purely advisory for the caller)
- Tool surface: read-only; no sub-agent dispatch

The critic output is appended below the findings table as an informational section. It does not add findings, does not escalate severity, and does not trigger additional review rounds.
