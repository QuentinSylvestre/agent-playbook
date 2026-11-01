# /qdev — multi-agent (parallel group) execution

<!-- Read from shared/skills/qdev/SKILL.md when the next phases form a [P:N] parallel group. Item numbers are cited from SKILL.md Steps 4-8. -->

This section holds the parallel-group execution machinery linked from Steps 4-8. It applies to **Standard/Major tier only**. When the next phase(s) form a parallel group (detected in Step 1), follow these items:

**1. Construct parallel briefs**: For each phase in the group, build the standard sub-agent brief (plan path, phase number, governance files, `<plan-slug>`, authority grant) with these additions:
- **Cross-phase context block**: For each sibling phase in the group, include:
  - Phase number and goal (from the plan's `**Goal**:` line)
  - File-scope boundary: list of files the sibling will modify (from the plan's phase description or exit criteria)
  - Instruction: "Phase {N} is being implemented concurrently and owns these files: [{list}]. Do NOT modify these files. If you discover a need that crosses into Phase {N}'s scope, flag it as a divergence rather than implementing it yourself."
- **Exit-criteria ticking suppressed**: "Do NOT edit the project file to tick exit criteria. Report satisfied criteria in your `exit_criteria_ticked` count only. The orchestrator will apply ticks after all parallel phases return."
- **Commit suppressed**: "Do NOT stage or commit your changes. Make the code changes, run tests/verification, then return your **changed-files list** (paths you modified/created) plus your `change_description`; leave `commit_sha` empty. The orchestrator commits each parallel phase's code serially after all phases return." This overrides authority grant (d) for parallel dispatch only — parallel sub-agents committing concurrently in a shared working tree would race on the git `index.lock`, so the orchestrator owns all commits for the group.

**2. Dispatch**: Use the `subagent` tool with one stage per phase in the group, no `depends_on` between them (they start in parallel). Each stage's `prompt_template` is the constructed brief. Because parallel sub-agents do NOT commit (item 1), there is **no git-index race regardless of the dispatch mechanism** — the orchestrator owns all commits for the group and applies them serially (items 4 and 7). This keeps parallel dispatch safe under any sub-agent runner, including ones that share a single working tree and do not serialize shell access.

**3. Await and collect**: The subagent tool returns when all stages complete. Collect each stage's structured return (JSON block + change description).

**Partial-blocked handling**: If any sub-agent returns `status: blocked` while others return `status: completed`:
- Proceed with completed phases through Steps 5-7 (reviews, fixes, plan-updates)
- Present blocked phase(s) to the user as a blocker with the sub-agent's reason
- Do NOT auto-continue past the parallel group until ALL phases (including blocked ones) are resolved — group-aware auto-continue (item 8) gates on the entire group result

**4. Consistency check**: Before proceeding to Step 5, compare the **changed-files manifests** returned by all completed parallel phases for overlap (sub-agents have not committed yet — there is nothing to `git diff-tree`; use the returned path lists):
- If ANY file path appears in more than one phase's manifest: HALT. Report the overlap to the user. Present options: (a) discard the higher-numbered phase's working-tree changes (`git restore -- <its-files>`) and re-run it with adjusted scope, (b) accept the overlap and proceed (user acknowledges risk)
- If no overlap: proceed to Step 5. (Because nothing is committed yet, an overlapping phase is resolved by discarding working-tree changes, not by reverting a commit.)

**5. Parallel review**: Dispatch Step 5 reviews for all completed phases simultaneously. Each review evaluates only its assigned phase. Findings collected per-phase for Step 6.

**6. Auto-fix**: Run Step 6's auto-fix cycle for each phase in the group. Phases whose file scopes item 4 confirmed disjoint MAY run their cycles concurrently; serialize only where scopes overlap. In parallel mode the auto-fix re-spawn is **also commit-suppressed** (item 1) — it returns the updated changed-files manifest + `change_description` and does NOT commit; the orchestrator commits the final post-fix state in item 7, so there is no git-index race for phase-order serialization to prevent.

**7. Serialized commits + project-file updates**: Process Step 7 for each phase sequentially (phase-number order). Because parallel sub-agents did NOT commit (item 1), the orchestrator authors BOTH commits per phase, serially — no index race. For each phase the orchestrator:
  0. **Stages and commits that phase's code** (using the phase's changed-files manifest as the pathspec): `feat(<plan-slug>): phase N — <desc>` (or another appropriate type). The commit is orchestrator-authored but the `change_description` it summarizes is the sub-agent's. Capture the resulting `<sha>`. This is the parallel-mode substitute for the sub-agent's code commit; the same message format keeps qvalidate's `commit-pairing` check able to pair the phase's `feat`/`docs` commits.
  1. Applies exit-criteria ticks for Phase N (from `exit_criteria_ticked` count)
  2. Adds implementation notes for Phase N (the sub-agent's `change_description`, verbatim)
  3. Applies deferred exit criteria — **cross-deferral check**: if any deferral targets a phase within the same parallel group, HALT and escalate (phases were not truly independent)
  4. Appends review log entry for Phase N
  5. Commits the project-file changes only: `docs(<plan-slug>): phase N progress (code: <sha>)` referencing the step-0 SHA
  6. Repeats for next phase in the group

  **Per-phase commit-pairing constraint**: each phase in a `[P:N]` group MUST produce its own separate `docs(<slug>): phase N progress` commit. Do not combine multiple phases into a single docs commit (e.g., "docs(<slug>): phases 2&3 progress") — `/qvalidate`'s `commit-pairing` check depends on per-phase correspondence between `feat` and `docs` commits.

**8. Group-aware auto-continue**: After Steps 5-7 complete for ALL phases in the group, evaluate auto-continue:
- If ANY phase has Red health, unresolved High findings, or pending escalations or proposed-accept proposals → STOP
- If ALL pass → auto-continue to next phase/group
- Transition summary: `Phases N,M complete (<health summary>). Continuing to Phase P...`

**9. Parallel dispatch summary** (observability): After item 3 returns, print a brief status block:
```
Parallel group [N,M] dispatch complete:
  Phase N: <status> (sha: <short>, <duration>)
  Phase M: <status> (sha: <short>, <duration>)
```
