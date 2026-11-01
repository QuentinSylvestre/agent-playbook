---
name: qmemory-eval
description: Read-only memory-health metrics snapshot — aggregates .dream-state.json outcome_tags and cost_records and the memory files into anchor-completeness, support-set-resolution, outcome-resolution, sweep-cost, and memory-footprint metrics. Invoke for an on-demand health check; also auto-emitted in each full /qdream sweep Report.
argument-hint: "<optional --json | --per-node>"
---

# qmemory-eval
Run `shared/skills/qdream/scripts/qmemory-eval.py` (run it with `<config-repo>/.venv-agent-playbook/Scripts/python.exe -I`, the playbook's one interpreter; if that file is missing or fails to start, report "qmemory-eval could not run: venv missing — run setup.ps1" and stop, never use a Python from `PATH`) from the config-repo root and present its block verbatim. Read-only — it writes nothing. If the state file is missing it SKIPs (no full sweep yet). Do not re-grade outcome_tags or interpret beyond what the engine prints. Requires `/qdream` to be deployed (the engine lives in its scripts dir). It reads `memory/MEMORY.md`, `memory/HIGHER_ORDER.md`, and — as an additional user-memory source — every `memory/topics/*.md` file, reporting the topic entries' anchor completeness on their own line so the always-loaded config-repo count is never distorted by an entry routed to the on-demand tier.

**Cost line** (v3 state only; a v1/v2 state prints none): from `cost_records` (`shared/skills/qdream/memory-rules.md § State File Format`) it prints the last `baseline` and the last `sweep` record (tokens, agents summed over roles, sessions, bytes, findings surfaced/kept, proposals surfaced/applied), the sweep's change against the baseline in tokens and agents, and the token trend over the last 5 sweeps that recorded tokens. A record whose `kept` or `applied` exceeds its `surfaced`, or whose `dropped_by_stage` sums above `surfaced − kept`, is flagged `inconsistent`, and every such record is listed. A trend that mixes retired-path sweeps (an `agents` role `collector`) with retained-path sweeps is labelled "not like for like". `tokens: null` (Kiro records none) shows as `n/a` and is left out of the trend. An empty `cost_records` prints `N/A — 0 records`. `--json` carries the same figures under `cost`.

**Cost ratios line** (printed under the Cost line when `cost_records` is not empty): for the last `sweep` record, tokens per surfaced finding (`tokens / findings.surfaced`), tokens per applied proposal (`tokens / proposals.applied`), and role shares, each role's percentage of the record's `tokens_by_role` sum (orchestrator, task4, verifier, drafter, other; a legacy record with the four keys without drafter is accepted and prints four). A ratio is `n/a` when `tokens` is null or its denominator is 0; role shares are `n/a (no tokens_by_role)` when the field is absent, malformed or sums to 0. The line ends `(inconsistent record)` when the record it reads is flagged on the Cost line. With no `sweep` record the line reads `n/a — no sweep record`. `--json` carries them under `cost.ratios`.

**Memory footprint** is the prose term for the words the config-repo memory files put into every session at start. `memory_tax` is only its internal key, in `--json` and in the script. The footprint is the word count `shared/skills/qdream/memory-rules.md § Session-start memory context budget` pins: `compute_memory_tax` is its only counter, and `dream-check.py budget` (its `memory` row, `<words>/<pin>` plus `OVER` when over) and `dream-manifest.py count` (its `memory budget: <words>/<pin>` line) both call it, so all three print the same words. Those two compare it with `MEMORY_BUDGET_WORDS` in `dream-manifest.py` and warn only; this report shows no pin.

## Flags

| Flag | Purpose |
|---|---|
| `--json` | Output as JSON (machine-readable) |
| `--omit-support-set` | Skip support-set metric (used by in-sweep caller) |
| `--per-node` | Per-node groundedness breakdown (standalone, read-only) |
| `--selftest` | Run fixture tests + no-writes assertion |

## `--per-node` mode

Standalone per-node groundedness breakdown. Read-only, derived-at-read — resolves each Higher-Order node's Support-set pointers individually and derives a groundedness label.

**Reachable-now caveat**: This is a point-in-time snapshot using `resolve_pointer`'s current reachability (episodic_ledger in-range, user memory heading present, plans/done/ file exists). It is NOT the sweep's reconciliation — the sweep resolves with full project access and session-file checks that this tool cannot perform. Sessions and cross-project project-memory pointers resolve as `indeterminate` (tool cannot check), which is neutral, not weak.

**Per-node vs store-wide node-count difference**: The store-wide support-set line counts only Support-set-bearing nodes (nodes that have a `**Support-set**:` line). The `--per-node` view lists ALL nodes in HIGHER_ORDER.md, including those without a Support-set line (labeled `no-support-set`).

### Label taxonomy

| Label | Condition | Meaning |
|---|---|---|
| `grounded` | R>0, CA=0 | All checkable ground present |
| `weak` | R>0, CA>0 | Some verified-gone ground alongside resolved |
| `ungrounded` | R=0, CA>0 | All checkable ground gone |
| `unverifiable` | R=0, CA=0, I>0 | Only indeterminate pointers — tool couldn't check; neutral, not weak |
| `no-support-set` | No Support-set line | Node has no Support-set field |

### Output format (text)

```
Per-node groundedness (qmemory-eval --per-node — read-only, reachable-now snapshot; not the sweep's reconciliation):
- "<heading>": <R>R/<CA>CA/<I>I (<total> ptrs) -> <label>
```

### Output format (--per-node --json)

Adds a `per_node` array to the JSON output:
```json
{
  "per_node": [
    {"heading": "...", "resolved": N, "confirmed_absent": N, "indeterminate": N, "total": N, "label": "grounded"}
  ]
}
```
