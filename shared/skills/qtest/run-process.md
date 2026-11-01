# Run Mode Process

Full process for `/qtest run`. Executes an existing test plan and emits a prioritized findings report.

## Step 1 — Validate plan exists

**Resolve the project-file root first**, through `shared/skills/qdream/memory-rules.md § Resolution contract`, artifact class *project files*. Call the result `<plan-root>` — the same token `shared/skills/qtest/SKILL.md § Artifacts` binds, resolved here as well because this process can be entered directly. Test artifacts live in `<plan-root>/tests/`. **Do not skip the resolution**: if you search only the workspace's own `plans/`, a store-backed plan reads as absent and the run stops one resolution short of the file it needs.

If no test plan exists for the target under `<plan-root>/tests/`, emit error and stop:
> "No test plan found for this target. Run `/qtest plan <target>` first."

## Step 2 — Load artifacts

Read the test plan (`<plan-root>/tests/{YYMMDD}_{NAME}.md`) and harness doc (`<plan-root>/tests/HARNESS.md`).

## Step 3 — Staleness check

Compare the plan's `created` or `last_executed` timestamp against last-modified dates of source files referenced in the plan.

- If plan is >7 days old OR source files have changed since plan creation → warn:
  > "Plan may be outdated (last created/executed: {date}, source changed: {changed_files}). Re-run `/qtest plan` to update, or proceed with current plan?"
- User confirms → proceed. User declines → stop.

## Step 4 — Reachability / BLOCKED handling

Attempt to reach each target surface defined in the plan.

- **Single-component**: if unreachable, emit **BLOCKED** with what would unblock it (per `/qqa`'s BLOCKED pattern) and stop.
- **Multi-component**: report per-component reachability. Reachable components proceed; unreachable components emit BLOCKED in the coverage section. At least one component must be reachable to proceed.

## Step 5 — Dispatch execution sub-agents

Determine parallelism from the plan's `resource_constraints`:
- Components with no shared resources → parallel dispatch
- Components sharing resources (browser, DB state, external service) → sequenced

Each execution sub-agent receives:
- The plan's per-feature testing intelligence for its component
- Harness doc resource info relevant to its component
- Surface-specific guidance (from `shared/skills/qtest/SKILL.md`)
- **No source access** (structurally naive — enforced by not providing read tools for implementation files)

**Execution sub-agent brief template**:

> You are a runtime tester for the `{component_name}` component.
>
> **Approach**: {approach_instruction} <!-- organic: "Drive the system freely, pull threads on anomalies, explore beyond the listed probes." | systematic: "Follow the test cases sequentially. Report pass/fail per case." -->
>
> **Testing intelligence**: {per_feature_testing_intelligence}
> **Resources**: {harness_resources}
> **Surface guidance**: {surface_specific_guidance}
>
> You MUST NOT read implementation source files. Test based only on the plan's intelligence and observable behavior.
>
> **Return schema**: JSON array of findings:
> ```json
> [{"severity": "High|Medium|Low", "finding": "one-sentence description", "reproduction": "steps to reproduce", "scope": "topology/config this applies to"}]
> ```

**Rigor gate**:
- `--light`: single execution pass per component, no refuter. Emits Confidence=`candidate` only.
- `full` (default): execution pass + refuter. **Cost-confirm gate**: "Full mode dispatches execution + refuter agents per component ({n} components). Proceed?" Offer `--light` as cheaper alternative.

## Step 6 — Refuter pass (full only)

For each finding from step 5, dispatch a refuter sub-agent.

**Refuter sub-agent brief template**:

> You are a source-level refuter. Your goal is to root-cause or refute this finding.
>
> **Finding under review**: {finding_description}
> **Source files**: {relevant_source_paths}
>
> Root-cause the finding. MUST cite `file:line` for every causal claim. Before confirming any 'missing / not implemented' claim, verify absence in source — an unrendered element is not an absent feature; check for interaction gates (conditional renders, auth states, unmounted paths) first.
>
> **Verdict** (exactly one): `confirmed` (root-caused + cited) | `plausible` (realistic failure scenario, not disproven) | `refuted` (provably wrong or already handled — cite the evidence)

- Verdict: `confirmed` → finding becomes `verified` | `plausible` → stays `plausible` | `refuted` → **dropped**

## Step 7 — Merge + emit report

The plan's feature manifest is the definition-of-done. The run MUST NOT conclude until every feature is covered or explicitly scoped-out with a reason in the Coverage section.

1. Merge findings from all execution sub-agents
2. Deduplicate (same root cause across components → single finding, note scope)
3. Emit findings report per `## Findings report format` in `shared/skills/qtest/SKILL.md`:
   - 6-column table (#, severity, finding, confidence, scope, resolution)
   - Coverage section (per-feature: covered / scoped-out / blocked)
   - Recommendations section (top findings → `/qexplore` handoff, patterns, unblock suggestions)

## Step 8 — Update artifacts

1. Stamp the test plan with `last_executed: <ISO-8601>` and a one-line summary (e.g., "3 findings (1H/2M), 12/14 features covered")
2. Update harness doc with operational notes (resource availability confirmed/changed, new constraints discovered)
3. Offer: (a) persist full report to `<plan-root>/tests/` and (b) `/qexplore` → `/qplan` handoff for top findings. Both opt-in.
