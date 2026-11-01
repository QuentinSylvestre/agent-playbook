# Plan Mode Process

Full process for `/qtest plan`. Produces a persistent test plan artifact with per-feature testing intelligence.

## Step 1 — Bootstrap

**Resolve the project-file root first**, through `shared/skills/qdream/memory-rules.md § Resolution contract`, artifact class *project files*. Call the result `<plan-root>` — the same token `shared/skills/qtest/SKILL.md § Artifacts` binds, resolved here as well because this process can be entered directly. Test artifacts live in `<plan-root>/tests/`.

Read `<plan-root>/tests/HARNESS.md` if it exists (prior resource knowledge). Create `<plan-root>/tests/` directory if absent.

**Give the destination disclosure here**, as soon as resolution returns — not at Step 9. `SKILL.md § Harness doc schema` requires telling the user which repo the artifacts commit to "before the first write", and creating the directory above is already a write.

## Step 2 — Establish oracle

Read user-facing documentation (README, specs, AGENTS.md, API docs) to understand expected behavior. A legacy surface the target replaces is an oracle too; inventory it in Step 5. Without an oracle, "broken" is unfalsifiable.

## Step 3 — Research components

Read source code and architecture docs. Enumerate distinct components (services, modules, UI layers, CLI commands). Each component = an independent execution unit for run mode.

## Step 4 — Present component map

Present the enumerated components to the user:
- Default: full coverage (all components included)
- User may subtract, reorder, or adjust
- Light touch — one confirmation, not per-component interrogation

**Single-component short-circuit**: if only one component exists, skip step 6 — proceed directly from confirmation here to step 7 (feature map confirmation is collapsed into this step).

## Step 5 — Deep feature inventory (parallel sub-agents)

Dispatch one sub-agent per confirmed component. Each sub-agent receives a self-contained brief and returns a structured feature list.

**Cost-confirm gate**: if >3 components confirmed, prompt: "This will dispatch {component_count} parallel research agents. Proceed?"

**Sub-agent brief template**:

> You are a feature-inventory researcher for the `{component_name}` component.
>
> ## Context
> - Component: `{component_name}`
> - File paths: `{file_paths}`
> - Oracle docs: `{oracle_summary}`
> - Legacy surface this component replaces, if any: `{legacy_paths}` — inventory its features too, and for each feature add `legacy_counterpart` (file:line or none) and `parity` with file:line evidence
>
> ## Task
> Read the source files and documentation for this component. Produce a comprehensive feature inventory — every user-facing behavior, interaction gate, state transition, and known risk area.
>
> ## Return schema
> Return a JSON array of features:
> ```json
> [
>   {
>     "feature": "short name",
>     "surface": "GUI | API | CLI | library | agent",
>     "interaction_gates": ["click X", "navigate to Y"],
>     "state_transitions": ["logged-out → logged-in", "empty → populated"],
>     "known_risks": ["race condition on rapid toggle", "shared DB state"]
>   }
> ]
> ```
>
> ## Done-criteria
> Return ≥1 feature with all 4 fields populated. Prefer completeness over brevity.

## Step 6 — Consolidate feature map

Merge sub-agent returns into a unified feature map. Present to user for confirmation:
- Show per-component feature count
- User may prune features, flag priorities, add missing features
- Default: full coverage

(Collapsed with step 4 for single-component systems.)

## Step 7 — Approach + resource inventory

Ask the user:
1. **Approach**: organic (default) or systematic? (See `## Approaches` in `shared/skills/qtest/SKILL.md`)
2. **Resources**: read harness doc for known resources. If harness doc exists, prompt: "Last time you had {resource_names} — still available? Anything new?" If no harness doc, ask: "What test resources are available? (environments, credentials by name, constraints)"

## Step 8 — Produce test plan

For each confirmed feature, produce 5-item testing intelligence (plus `parity` when it applies):

| Field | Content |
|---|---|
| **what** | Feature under test (one sentence) |
| **how-to-reach** | Navigation/setup steps to exercise the feature |
| **probes** | Specific interactions to attempt (boundary, error, race) |
| **oracle** | Expected behavior source (doc, spec, code invariant) |
| **risks** | Known fragility, shared state, timing sensitivity |
| **parity** | Only when a legacy surface is the oracle: `match`, `intentional difference (<decision ref>)`, or `gap` |

Add plan-level metadata:
- `approach`: organic | systematic
- `resource_constraints`: which components share browser/state/external services (informs run-mode parallelism)
- `created`: ISO-8601 timestamp
- `last_executed`: null (populated by run mode)

## Step 9 — Write artifacts

1. Write test plan to `<plan-root>/tests/{YYMMDD}_{NAME}.md` (YYMMDD = today, NAME = target slug)
2. Create or update `<plan-root>/tests/HARNESS.md` with resource inventory from step 7 — say which repo that commits to, per `## Harness doc schema` in `shared/skills/qtest/SKILL.md`
3. Report: "Test plan written to `{path}`. Run `/qtest run <target>` to execute."
