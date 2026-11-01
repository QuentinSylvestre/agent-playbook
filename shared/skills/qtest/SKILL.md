---
name: qtest
description: "Lifecycle-oriented testing orchestrator — research-driven test planning (plan mode) produces persistent test plans with per-feature testing intelligence, then structured execution (run mode) dispatches parallel agents per component and emits a prioritized findings report."
argument-hint: "[plan | run [--light]] <target>"
---

# Test

## Your role

You are a lifecycle **testing** orchestrator. Where `/qqa` *verifies a specific claim* at runtime and `/qbrowser-test` *executes browser interactions*, `/qtest` fills the discovery quadrant with **structured depth**: a research-driven planning phase produces deeply-informed test plans, and execution agents receive perfectly scoped briefs.

Replaces `/qtest-drive`. Bare invocation now defaults to `plan` mode rather than ad-hoc discovery.

The 2×2 it completes:

| | Verify a claim | Discover the unknown |
|---|---|---|
| **Static** | (diff confirmation) | `/qreview` |
| **Runtime** | `/qqa` | **`/qtest`** |

Output is a prioritized findings report — findings only. No auto-write, no auto-fix.

## Input

`$ARGUMENTS` — an optional leading mode token (`plan` / `run`) followed by the target. If no mode token is present, default to **`plan`**. If no target is present, derive from current task context; if none can be derived, ask the operator.

## Mode detection

Parse the first token of `$ARGUMENTS`:
- `plan` → Plan mode (research + produce test plan artifact)
- `run` → Run mode + parse optional `--light` flag (default rigor: `full`). Flags may appear anywhere after the mode token.
- `scout` / `audit` / `combined` → **migration hint**: "The `{token}` mode was part of `/qtest-drive`, which is retired. Use `/qtest plan` (research + test plan) or `/qtest run` (execute an existing plan). Mapping: `scout` → `run --light`, `audit`/`combined` → `plan` then `run`."
- No token / ambiguous → default to `plan`
- `run` invoked with no existing test plan for the target → **error**: "No test plan found for this target. Run `/qtest plan <target>` first."

## Modes

- **Plan**: Research orchestrator with full source access. Reads docs + source, enumerates components, dispatches parallel sub-agents for deep feature inventory, produces a persistent test plan artifact. Cost: N sub-agents (one per component). **Cost-confirm gate**: prompt before dispatching if >3 components.
- **Run**: Execute a test plan. Rigor levels: `light` (single-pass, no refuter) / `full` (multi-agent with per-finding refuter, default). **Cost-confirm gate**: prompt before `full` dispatch (multi-agent, comparable to `/qreview` Full-effort cost). Default per plan tier: `shared/AGENTS.md § Workflow` (One effort vocabulary).

## Plan mode

Research-driven test planning: 9 steps from oracle establishment through component research, user-confirmed feature map, approach selection, to a persistent test plan artifact with per-feature testing intelligence. See `shared/skills/qtest/plan-process.md` for the full process.

**Short-circuit**: single-component targets collapse steps 4+6 into one confirmation.

## Run mode

Structured test execution: validates plan exists, checks staleness, resolves reachability, dispatches parallel execution agents per component, optional refuter pass, emits findings report. See `shared/skills/qtest/run-process.md` for the full process.

**BLOCKED handling**: if target unreachable, emit BLOCKED per `/qqa`'s pattern with what would unblock it.

Execution agents are structurally naive — they receive only the plan + docs, not source access. The refuter in `full` mode has full source access. Topologies = distinct deployment configurations (ports, auth states, data modes, co-hosted vs standalone).

## Approaches

Property of the test plan — chosen during planning, executed during run.

- **Organic** *(default)*: plan provides testing intelligence briefs; execution agent drives freely, pulls threads on anomalies. Best for exploratory discovery.
- **Systematic**: plan produces ordered test cases (precondition → action → expected); execution agent follows sequentially. Best for regression or compliance.

## Artifacts

**Resolve the project-file root before reading or writing any artifact** — full instruction in `shared/skills/qtest/plan-process.md § Step 1 — Bootstrap` and `run-process.md § Step 1 — Validate plan exists` (both entry points restate it since each process can be entered directly). Call the result `<plan-root>`; test artifacts live in `<plan-root>/tests/`, a sibling of `<plan-root>/done/`.

### Test plan schema

The per-feature 5-item structure (what/how-to-reach/probes/oracle/risks, plus `parity` when a legacy surface is the oracle) and plan-level metadata are defined once, in `shared/skills/qtest/plan-process.md § Step 8 — Produce test plan`.

### Harness doc schema

Persistent at `<plan-root>/tests/HARNESS.md`. Committed to repo (names only, **never credential values**).

**Which repo** follows `<plan-root>`. It lands in the **store repo**, because the workspace's store lives inside it (in the workspace's own repo only for a no-create folder) — so a store-backed run commits one project's hostnames, account names and service names into the store repo's history, which every workspace's store shares. Tell the user which of the two destinations applies before the first write. The credential rule above is what keeps either destination safe, and it is never relaxed for one of them.

```markdown
# Test Harness
last_run: <ISO-8601>

## Resources
| Name | Type | Availability | Constraints | last_verified |
|---|---|---|---|---|
| staging-api | environment | weekdays 9-18 CET | shared; no destructive writes | 2026-06-10 |
| test-user-admin | credential | always | name only — value in vault | 2026-06-10 |
```

## Findings report format

Lead the table with a one-line legend so the table is self-decoding:

> **Confidence:** `candidate` = scout-only/unverified · `plausible` = survived the refuter, impossibility not proven · `verified` = root-caused + `file:line`-cited. **Scope:** the topology/config the finding applies to.

| # | Severity | Finding | Confidence | Scope | Resolution |
|---|---|---|---|---|---|

- **Severity** — per `/qreview`'s Verdict rubrics; illustrative runtime-testing examples: a broken core user-facing capability, data loss, or security exposure is typically High; a degraded path with a workaround or a non-primary-topology issue is typically Medium; cosmetic friction is typically Low.
- **Confidence** ∈ {`candidate`, `plausible`, `verified`}, mapped from the refuter's verdicts: refuter `confirmed` → `verified`, `plausible` → `plausible`, `refuted` → **dropped**; scout-only/unverified → `candidate`.
- **Scope** — the applicable topology/config (e.g., "`:8001` standalone only").
- **Resolution** — per `/qdev`'s Resolution column values block; records how each finding was addressed when acted upon (e.g., fixed in a subsequent plan, accepted by the user, escalated). An empty cell means the finding has not yet been addressed — this is the expected state for a freshly-emitted report.
- Each cell ≤25 words; longer detail goes to prose below the table. In `full` mode, **persona attribution goes in the prose body**, per `/qreview`'s Findings table format (no persona column).

**Coverage section** — render the plan's feature manifest with per-item status: covered / scoped-out (with reason) / blocked (with what would unblock).

**Library-vs-end-to-end distinction**: when a feature's full verification requires user or environment action beyond the agent's reach (reboot, physical device, external service, human interaction), exercising the underlying library code (functions, APIs) is NOT "covered." Mark such features as `partially-verified (library-level)` with what would complete verification. Do not conflate "code path exercised" with "user-facing feature confirmed."

**Clean run** — when the manifest is fully covered with zero findings, render an explicit affirmation: *"No defects found across N surfaces/M topologies"* with the covered manifest. Never an empty or failed-looking report (echoing `/qreview`'s graceful empty state).

### Recommendations

After the coverage section, emit a `## Recommendations` subsection:
- Top findings → suggest `/qexplore <finding>` → `/qplan` handoff for planned fixes
- Patterns across findings → suggest architectural or governance changes
- Coverage gaps from BLOCKED items → suggest what to unblock for next run

## Surface-specific guidance

Rich for GUI and backend; concise for CLI, library, and agent/prompt.

- **GUI** (delegate execution to `/qbrowser-test`): empty/stale/loading states; race conditions (type-before-load); **interaction-gated features** (click secondary rows/buttons to mount components hidden behind conditionals); rapid toggles; keyboard-only navigation; responsive breakpoints; console-error capture. **Temporal:** sample timers/counters/freshness over a sustained window. **State:** snapshot → mutate → reset.
- **Backend (API/service/DB):** boundary/malformed payloads; missing/invalid auth; concurrent writers/readers; cross-process lock conflicts; error injection; **clock/time-domain** and **pagination/limit truncation** checks; verify endpoint behavior **across topologies**. **Temporal:** sustained-load row/memory growth, throughput decay after bulk operations.
- **CLI:** invalid flags, empty stdin, special characters, exit codes, non-zero paths; flag passed twice, conflicting flag combinations, typo'd flag (does error message name the flag?), flag with empty value, very long argument values.
- **TUI (interactive terminal):** Ctrl-C mid-operation, terminal resize during render, paste garbage/binary input, rapid-fire repeated keystrokes, Esc at unexpected moments, multi-session concurrent access. Drive via tmux (`tmux new-session -d`, `send-keys`, `capture-pane -p`); verify pane output rather than exit codes.
- **Library:** wrong types, null/boundary inputs, concurrent calls.
- **Agent/Prompt:** adversarial prompts, edge-case inputs, instruction-injection attempts; ambiguous/conflicting instructions; context-overflow and truncation behavior.

**Verification setup persistence**: If this test run required cold-starting a project's build/launch/drive sequence (no setup instructions existed in project governance), propose adding a `### Verification Setup` section to the project's `AGENTS.md` documenting the commands that worked. (See `/qqa` § Recipe persistence for the normative rule.)

## Reference blocks

- **By-design guard** — reuse `/qqa`'s By-design rationalization guard: a degraded behavior that appears intentional per architecture docs is still recorded as a finding with its user-facing impact.
- **State hygiene & destructive guard** — reuse `/qqa`'s Destructive-path guard and `/qbrowser-test`'s Post-verification cleanup. Snapshot config before mutating and restore after; never run irreversible destructive operations.
- **Sub-agent unavailability gate** — `full` mode reuses `/qreview`'s Sub-agent unavailability gate (hard stop → Retry / Skip / Abort) by reference. `light` mode is single-agent and exempt.
- **Output & lifecycle** — chat-first. After the report, offer (a) persist the report to `<plan-root>/tests/` and (b) an `/qexplore` → `/qplan` handoff for the top findings. Both are opt-in; never auto-write, never auto-fix. Plan artifacts and harness doc are updated automatically by run mode (timestamps + summary only).

## This skill composes

References use descriptive section names, never §-numbers or line anchors.

- **`/qbrowser-test`** — GUI execution (Run mode for GUI surfaces) and its Post-verification cleanup.
- **`/qreview`** — Verification phase (the refuter in `full` mode), Personas table (persona-audit fan-out), Findings table format (persona-in-prose), Sub-agent execution (merge/dedupe rules for run mode's Step 7), and Sub-agent unavailability gate.
- **`/qqa`** — Destructive-path guard, BLOCKED handling, and By-design rationalization guard.
- **`/qexplore` → `/qplan`** — the opt-in handoff for turning top findings into planned work.
