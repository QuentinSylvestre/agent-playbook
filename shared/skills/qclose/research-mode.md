# Close — research mode

Loaded by `shared/skills/qclose/SKILL.md` for `/qclose research`. It archives a completed `/qauto-research` run. It produces two commits with the same `<plan-slug>`: one on the research branch that pins the run's end-state in place, and one on the source branch that lands the artifacts under `<plan-root>/done/<plan-slug>/`. `<plan-root>` is resolved as in SKILL.md § Mode detection; every path below means it, never a literal `plans/`. When `<plan-root>` is a workspace store, the archive commit lands in the store's repository, not on the source branch; that is intended, so research archives sit with the project's other archived plans. After the archive, the user is offered a squash-merge of the run's last-known-good onto the source branch plus worktree/branch teardown, then `/qdream lightweight` runs for memory consolidation.

**Orchestrator directory contract** (applies to every step in this section). The orchestrator runs from the **source-branch working tree** throughout — it never `cd`s into the research worktree. Cross-branch interactions use one of two mechanisms:

- **Read from research branch into source worktree**: `git show research/<tag>:<path>` (e.g., `git show research/<tag>:research-log.jsonl`). The orchestrator stays in the source worktree and reads cross-branch content into memory or redirects it into a file under the source tree.
- **Stage and commit inside the research worktree**: `git -C <research-worktree> add <path>` and `git -C <research-worktree> commit -m "..."`. The `-C <path>` flag tells git to operate in that directory without the orchestrator changing its own working directory. The research-worktree filesystem path is known from `/qauto-research setup` — default `../<project-name>-research`, or the user-configured path captured at setup time.

**`<plan-slug>` derivation** (compute once at the very start of Research mode, before Step 1's reads use it for log lines or the eventual commit messages). `<plan-slug>` for research mode is computed once at `/qclose` start as `<YYMMDD-HHMM>_RESEARCH_<TAG>` using today's local time (close date, NOT run-start date). The same slug is used for both the research-branch close commit, the source-branch archive commit, and the destination folder. `<TAG>` is `git.tag` read from `research.md`'s frontmatter.

### Research Step 1: Read configuration

Locate `research.md` at the workspace root (the source-branch working tree). Parse its frontmatter for `git.tag` and `git.source_branch`. If `git.source_branch` is missing (e.g., the run pre-dates the field), prompt the user for the source branch and proceed; if `git.tag` is missing, stop with an error — the slug cannot be derived without it.

Fetch the **full** `research-log.jsonl` content via `git show research/<tag>:research-log.jsonl` (the orchestrator reads from the research branch without leaving the source worktree). Inspect the **tail (last 10 entries)** for Step 2's stop-reason context-prep, but **retain the full content in memory** — Step 3's summary aggregation (kept/discarded/crashed totals, baseline + best metrics, improvement deltas, time elapsed) requires iterating every entry, not just the tail.

Compute `<plan-slug>` per the derivation rule stated at the top of this section, using today's local time and the `git.tag` value just read.

### Research Step 2: Sanity check

Two passes. Pass 3 (legacy REVISIT markers) is skipped — those markers are a plan-mode artifact and do not apply to research runs.

#### Pass 1: Stop-reason check

Classify the last log entry's stop reason and act accordingly:

- **`objectives reached`** — proceed silently to Step 3. The run ended on a desired outcome; no user prompt needed.
- **`plateau`** — present to the user: "Run plateaued — proceed with close, or resume with new hypotheses first?" Await decision before continuing. If the user resumes, stop the close flow.
- **`max_iterations`** or **`max_time`** — show the best-metrics-vs-baseline delta (computed from the full log) so the user can judge whether the budget-exhausted run is worth archiving. Present: "Run hit `<budget>` budget. Best vs baseline: `<delta summary>`. Proceed with close?" Await decision.
- **`consecutive crashes`** — **hard block**. Print: "Run ended on consecutive crashes (last error: `<msg from last log entry>`). Resolve before archiving, or explicitly approve archival with unresolved blocker (type `I accept archiving with unresolved blocker`)." Do not proceed unless the user types the exact override phrase. If approved, record the override in the Completion Summary's acknowledged-at-archival list.

#### Pass 2: Harness Improvement Opportunities (conditional)

**Run this pass only when `research.md` contains a `## Harness Improvement Opportunities` section.** If the section is absent or empty, skip Pass 2.

Apply the same per-item action set as plan-mode Step 2 Pass 2 — **Promote** / **Accept and note** / **Skip** — using the same definitions, including the requirement to **show the user the proposed edit text and get approval before writing it**. Approved promotions are staged alongside Step 4's archive commit (single mixed commit, mirroring plan-mode); accepts and skips are recorded in the Completion Summary built in Step 3.

### Research Step 3: Append Completion Summary on research branch, commit there

Build the Completion Summary content from the **full** `research-log.jsonl` retained in Step 1. The fields match the Summary-report section in `shared/skills/qauto-research/SKILL.md`:

- Stop reason (and, for `consecutive crashes`, the last error message and the user's override acknowledgement).
- Total experiments (excluding baseline).
- Kept / Discarded / Crashed counts.
- Time elapsed.
- Best metrics achieved (last-known-good), with units and direction per metric.
- Baseline metrics (experiment #0).
- Improvement deltas (baseline → best, absolute and percentage, per metric).
- Research branch (`research/<tag>`) and last-known-good commit SHA.

Append this content under a new `## Completion Summary` H2 in the **research-branch copy** of `research.md`. The research worktree has `research/<tag>` checked out, so the working copy at `<research-worktree>/research.md` **is** the research-branch content — no `git show` is needed for this read. The orchestrator (running from the source worktree) reads `<research-worktree>/research.md` directly via the filesystem, appends the new section in memory, and writes the updated content back to `<research-worktree>/research.md` via the filesystem. **Then** stage and commit using the `git -C` cross-branch staging mechanism defined above:

```
git -C <research-worktree> add research.md
git -C <research-worktree> commit -m "docs(<plan-slug>): close research run"
```

The filesystem write and the `git -C add/commit` are two distinct steps — the write updates the working copy; the add stages it; the commit records it on the research branch.

The research-branch commit comes first so `research/<tag>` holds the same finalized `research.md` that lands in the archive, and stays a complete record on its own.

### Research Step 4: Copy artifacts to source branch and commit

Create the destination folder: `mkdir -p <plan-root>/done/<plan-slug>/`.

Copy both artifacts cross-branch using `git show`:

```
git show research/<tag>:research.md       > <plan-root>/done/<plan-slug>/research.md
git show research/<tag>:research-log.jsonl > <plan-root>/done/<plan-slug>/research-log.jsonl
```

**Do NOT use `git mv`**: cross-branch is not a git rename, and these are new files on the source branch.

Stage the new folder and commit on the source branch:

```
git -C <plan-root> add done/<plan-slug>/
git -C <plan-root> commit -m "docs(<plan-slug>): archive research run"
```

If Step 2 Pass 2 produced any **Promote** decisions, stage the governance edits alongside the archive folder in this same commit (mirroring plan-mode's single-mixed-commit pattern) and extend the commit message body to document both — including any removal proposed under the Promote one-in-one-out soft budget.

### Research Step 5: Offer squash-merge + teardown

Present to the user:

```
Squash-merge research/<tag> last-known-good onto <source_branch>, then remove worktree at <path> and delete branch? (Y/n, default n)
```

`<source_branch>` is the value of `git.source_branch` read in Step 1; `<path>` is the worktree path captured at setup time (default `../<project-name>-research`); `<last-known-good-sha>` is the `commit` of the most recent log entry with `status: keep` or `status: baseline`.

- **On Y**:
  1. From the source-branch working tree: `git merge --squash <last-known-good-sha>`.
  2. Commit the squashed merge: `git commit -m "feat(<plan-slug>): adopt research run last-known-good"`.
  3. Remove the worktree: `git worktree remove <path>`.
  4. Delete the branch: `git branch -D research/<tag>`.
- **On n** (default): leave the branch and worktree intact. The archive folder under `<plan-root>/done/<plan-slug>/` remains the historical record; the branch and worktree remain available for resumption or inspection.

### Research Step 6: Memory consolidation (lightweight)

After archival is complete, invoke `/qdream lightweight` scoped to the just-archived research run. This extracts learnings from the research log and research.md, proposing them as memory entries via the standard proposal format. Maximum 3 proposals. The extraction pass itself is unconditional — run it, and if it yields nothing, report "no proposals"; only the proposal *output* may be empty.

Relay both `count` lines the lightweight report ends with (`sweep due:` and `memory budget:`) in the `/qclose` report, verbatim. Same Unavailable rule as Plan mode (`shared/skills/qclose/SKILL.md § Step 7: Memory consolidation (lightweight)`) — this step does not block archival.

