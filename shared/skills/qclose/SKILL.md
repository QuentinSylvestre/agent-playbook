---
name: qclose
description: Archive a completed plan or research run following the project's archival conventions. Adds completion summary, renames, and moves to archive location, then runs memory consolidation.
argument-hint: "<path to project file> | research"
---

# Close

## Your role

End a project's lifecycle cleanly. Two modes:

- **Plan mode** (`/qclose <path-to-plan>`) — update status, add completion summary, move the project file to its archive location, then run memory consolidation.
- **Research mode** (`/qclose research`) — append a completion summary to the research-branch `research.md`, archive `research.md` + `research-log.jsonl` onto the source branch under `<plan-root>/done/`, optionally squash-merge last-known-good and tear down the worktree, then run memory consolidation.

Both modes finish by running `/qdream lightweight` for memory consolidation.

## Arguments

$ARGUMENTS

## Script location

The archive script lives in the `scripts/` subdirectory alongside this skill file. In the invocation examples below, `<skill-dir>` refers to the directory containing this SKILL.md — resolve it per your environment's co-located file resolution.

## Process

### Mode detection

**Resolve the project-file root before inferring anything**, through `shared/skills/qdream/memory-rules.md § Resolution contract`, artifact class *project files*. Call the result `<plan-root>`. It is the `plans/` of the workspace's store in the store repo, or the workspace's own `plans/` when the contract keeps project files in the folder (a folder with no store), and every path below means `<plan-root>`, never a literal `plans/`. Resolving only at the archive step (Step 4) is not enough: a store-backed project file is then written by `/qexplore` but invisible to a bare `/qclose`, which reports no active plans while the file sits one resolution away.

Parse `$ARGUMENTS` to dispatch:

- **Path-like** (the value points to an existing file, starts with `<plan-root>/`, or contains `.md`) → **Plan mode**. Continue with Step 1 below.
- **Literal string `research`** (case-sensitive keyword, no path component) → **Research mode**. Read `research-mode.md` alongside this file and follow it.
- **Empty** → attempt inference:
  1. If the session has an active project context (a plan was being executed via `/qdev` in this session), use that plan's path. Continue with Step 1.
  2. Otherwise, list `.md` files in `<plan-root>` (excluding `<plan-root>/done/`). If exactly one exists, use it with a confirmation prompt. If multiple exist, present the list and ask the user which to close.
  3. If no plans exist, print: `No active plans found in <plan-root>. Usage: /qclose <path-to-project-file>  |  /qclose research`. Stop. Print the resolved root, not the literal string — a user whose plans live in a store needs to see which location was searched.

## Plan mode

### Step 1: Read the plan

Read the project file. Verify the mechanical archival-readiness gates by running qvalidate (run `shared/skills/qvalidate/scripts/qvalidate.py` with the playbook venv, per `shared/skills/qvalidate/SKILL.md` — never re-implement the checks inline): the `status-grammar` check confirms the status line is well-formed, and the `completeness` check confirms that — when the status is `Complete` — every `- [ ]` box in the file is ticked (including `(deferred from Phase N)` entries). Handle a FAIL per `shared/skills/qvalidate/SKILL.md § Failure semantics`. **Note the ordering**: `completeness` fires only at State `Complete`, but a plan reaching archival often still reads `In Progress` (`/qdev` does not auto-set `Complete`; Step 3 below does). So for a full-completion archival, re-run `completeness` after Step 3 sets the status to `Complete` — that is the point the all-boxes-ticked gate becomes live. For a deliberate partial-handoff archival (status stays `In Progress — <what remains>`), `completeness` correctly stays inert and the semantic gates below govern.

Then verify the semantic gates qvalidate does not cover:
- Final validation/verification has been done
- No blocking review findings remain open
- Any required rollout, migration, cutover, or post-rollback cleanup phases are also complete, unless the user explicitly wants archival as a partial handoff with pending operational work called out

If the plan is NOT fully complete, warn the user and ask for confirmation before proceeding.

**Early REVISIT marker warning**: If the plan's review log contains any `REVISIT WHEN SUB-AGENTS AVAILABLE` lines (legacy markers from sessions before the sub-agent unavailability gate was introduced), warn the user immediately: "This plan has N legacy self-review markers that must be resolved (re-run with sub-agents or explicitly approved) before archival can complete. See Step 2 Pass 3." This is informational at Step 1 — the hard gate is enforced in Step 2 Pass 3.

**Follow-up Work surfacing**: Read the plan's `## Follow-up Work (Deferred)` section (`shared/skills/qplan/TEMPLATES.md § Follow-up Work (Deferred)`) if present. If non-empty, present its contents to the user now as a concise numbered summary — informational, not a blocking gate, but never silently skipped. Absence of the heading (a plan predating this convention) is not a failure — proceed without surfacing anything.

### Step 2: Scan for cleanup items

Before archiving, scan the plan and codebase for loose ends in four passes.

#### Pass 1: Project cleanup

Classify every found item as **resolved** or **unresolved** using these rules:

| Category | Source | Resolved when | Unresolved → per-item decision required |
|---|---|---|---|
| Review findings | Plan's review log table(s) | Resolution resolved per `/qreview`'s Verdict rubrics partition (cited — illustratively: begins `Fixed` or `User: accepted`); legacy `N/A` and `Resolved`-prefix rows count as resolved (archival-only carve-outs — `Resolved --` was qplan's sanctioned fix-recording vocabulary until 2026-07-22, plan 260722_QREVIEW_ANCHORED_RUBRICS_AND_JUSTIFIED_OVERRIDES) | Yes |
| TODO/FIXME grep hits | Affected files (per plan's file change list) | Never auto-resolved | Yes |
| Documented divergences | "Implementation Divergences from Plan" section | A review log entry in the same plan explicitly verified the divergence as acceptable (cite the review finding number) | Yes |
| Documentation gaps | "Documentation Updates" table | Every row's target file appears in the plan's diff (`/qvalidate` `doc-updates`) — a ticked box is the claim, not the evidence | Yes |
| Roadmap reconciliation | `<plan-root>/ROADMAP.md` | If the plan's scope included adding or removing roadmap items, the roadmap reflects the completed work. Covered mechanically by `doc-updates` when `ROADMAP.md` is a Documentation Updates row; check by hand when it is not | Yes |
| Temporary scaffolding | Implementation notes mentioning debug logging, feature flags, or temporary workarounds | Never auto-resolved (grep is unreliable) | Yes |
| Pending operational work | Rollout, migration, cutover, rollback-window cleanup phases | Phase marked complete | Yes |
| Orphaned `## Handoff` section | Project file `## Handoff` section | Always — strip at archive (transient coordination artifact) | No (auto-removed) |
| Leftover standalone handoff file | `.handoff-*.md` directly under the resolved project-file root (`shared/skills/qhandoff/SKILL.md § Step 5` standalone mode) | The file's header or `Suggested next` line names this plan, or says "ad-hoc session" with no better-matching in-progress plan (same affinity check as `shared/skills/qdev/SKILL.md § Step 1` Handoff ingestion) | No (auto-removed) when it matches this plan; a file clearly naming a *different* plan is left untouched — it belongs to that plan's lifecycle, not flagged as unresolved here |
| Plan's scratch folder | `<store>/scratch/<plan-slug>/` (`shared/skills/qdream/memory-rules.md § Store scratch folder`) | Always. Before archiving, ask the user about any file there you judge worth keeping, with your reason; a kept file moves to `artifacts/` | No (auto-removed after the archive move, by `store-resolver.py scratch-clean --plan <source-path>`; kept on a partial archive, where the 30-day rule then applies) |

**Per-item decision requirement** (blocking): for every **unresolved** item, the user must choose one of:

- **Fix now** — stop archival, address the item, re-invoke `/qclose` afterward
- **Accept and note in completion summary** — proceed with archival; item is copied into the Completion Summary section (see Step 3)
- **Open follow-up plan** — proceed with archival; item is copied into the Completion Summary with a note that a follow-up plan is intended. Archival does not block on follow-up plan creation; the user creates it afterward.

Bulk "acknowledge all" is not permitted. Present items to the user grouped by category, one decision at a time. Already-resolved items are listed for awareness but require no decision. The resolution-detection rules above are deliberately conservative — refine them based on recurring friction patterns after several real archivals.

**Write each question for a cold reader.** A review-log row is shorthand for reviewers, so do not paste it as the whole question. Say in plain words what the item is, which file or behavior it touches, what happens if it stays as it is, and what each decision would change. Use the project's own terms, and define any term the plan coined.

Example presentation:

```
Cleanup scan — Review findings (2 unresolved, 1 resolved)

Q1. Review finding #5 (Low) — "deferred; no owner"
    Fix now / Accept and note / Open follow-up plan?

Q2. Review finding #8 (Medium) — "deferred pending API spec"
    Fix now / Accept and note / Open follow-up plan?

(Already resolved: review finding #3 — fixed in Phase 2)

Cleanup scan — TODO/FIXME grep hits (1 unresolved)

Q3. src/auth.ts:42 — "remove after migration"
    Fix now / Accept and note / Open follow-up plan?

...
```

#### Pass 2: Harness governance (conditional)

**Run this pass only when the project file contains a `## Harness Improvement Opportunities` section.** If the section is absent or empty, skip Pass 2 and continue with Pass 3.

Harness improvement opportunities use a different action set than Pass 1 categories: **Promote** / **Accept and note** / **Skip**. The divergence is intentional — these items are about playbook governance, not project work, so the action vocabulary mirrors the artifact lifecycle.

- **Promote** — apply the suggested change as an edit to `shared/AGENTS.md` or the relevant `shared/skills/*/SKILL.md`. **Show the user the proposed edit text and get approval before writing it** — a Promote decision authorizes the change, not its wording (`shared/AGENTS.md § Harness Improvement Capture`). When the harness asks through a dialog that can hide the message above it (Claude Code's AskUserQuestion, observed 2026-09-28), put the edit text inside the question, or print it as plain text and ask for a typed reply; never ask for approval of text "above". Never substitute your own judgment for a Promote the user already chose: if you believe the item is below a promotion threshold, say so and let the user re-decide rather than silently downgrading it to Accept-and-note. **Removal-candidate search (one-in-one-out soft budget)**: before promoting, search the target governance file(s) for content the new addition obsoletes or duplicates, and state the outcome in the commit body. If a removal candidate exists, propose removing it in this same commit so governance does not grow every time the ratchet fires; if none exists, promote without forced deletion (the budget is a search obligation, not a mandatory deletion). Stage the governance edit alongside the archive move in a single commit using `docs(<plan-slug>): archive to <archive-filename> + harness promotion` (with `<plan-slug>` = the plan filename without `.md`, and `<archive-filename>` = the new filename under `plans/done/`) with a multi-line body documenting both. The single mixed commit is intentional — it keeps the governance promotion atomic with the archival decision that triggered it, and a future `git log --follow` over either path traces the same commit. After commit, suggest the user run `/qconfig-sync` to propagate the edit to all providers.
- **Accept and note** — copy the entry verbatim into the Completion Summary's `### Acknowledged at archival` sub-heading with label `Accepted (harness opportunity)`. Accepted items are not write-only: `/qdream`'s `plans/done/` harness-opportunity harvest re-reads accepted, un-promoted items on each full sweep, clusters equivalent friction across archived plans, and promotes recurring concerns (frequency gate: 2+ distinct plans, or 1 plan + live session signal) into governance proposals — the loop closes there. See `shared/AGENTS.md § Harness Improvement Capture` (Read side).
- **Skip** — discard with a one-line reason. Record under the same sub-heading with label `Skipped (harness opportunity): <reason>`. Use `Skipped: obsolete reference` when the suggested change names a skill that no longer exists.

**Item whose fix is project code or project steering.** When the suggested change belongs in the project's own code or in the project's `AGENTS.md` or `CLAUDE.md`, not in `shared/AGENTS.md` or a `shared/skills/*/SKILL.md`, Promote does not apply, and Pass 2 offers no **Fix now** (that action exists only in Pass 1). Offer **Accept and note** instead, with the label text starting `Accepted (harness opportunity): project fix, <where it belongs>`, or **Skip**. If the user wants the fix done, they choose **Open follow-up plan** in a new project file or edit the project directly after archival; do not stop archival to fix it. Do not invent other options.

Bulk "acknowledge all" is not permitted for harness-improvement-opportunity items. Present items one decision at a time. Write each question per Pass 1's cold-reader rule.

#### Pass 3: Legacy REVISIT marker enforcement (mandatory)

**Always run this pass.** Scan the project file's review log for any lines containing `REVISIT WHEN SUB-AGENTS AVAILABLE`. These are legacy markers from sessions before the sub-agent unavailability gate was introduced — new sessions no longer generate them. Each such line represents a review that was self-performed due to sub-agent unavailability and has not yet been re-performed with proper sub-agent context isolation.

**This is a hard archival gate.** Outstanding REVISIT markers block archival by default. For each marker found:

1. **Re-run the review now** — if sub-agents are available, re-perform the review using the original persona(s) and standards subset, dispatched to a sub-agent with fresh context. On completion, replace the self-review log entry with the sub-agent's findings and remove the REVISIT marker. Then re-evaluate: if the sub-agent review surfaces new High-severity findings, those become Pass 1 unresolved items subject to the standard per-item decision flow.
2. **User explicit approval** — if sub-agents are still unavailable or the user chooses not to re-run, the user must explicitly approve archival with reduced review rigor **per marker**. Bulk acknowledgement is not permitted. Present each marker individually:

```
REVISIT marker enforcement — N outstanding markers

Q1. Self-reviewed (sub-agent unavailable) -- persona(s): Security auditor.
    Phase 2 review, logged YYYY-MM-DD.
    Re-run now / Approve archival without sub-agent review?

Q2. Self-reviewed (sub-agent unavailable) -- persona(s): Senior engineer.
    Final review, logged YYYY-MM-DD.
    Re-run now / Approve archival without sub-agent review?
```

For each marker the user approves without re-running, record it in the Completion Summary under `### Acknowledged at archival` with label `Accepted (reduced review rigor): <persona(s)>, <phase or final>, <date>`. This creates an auditable record that the archival proceeded with known review debt.

**Do NOT proceed past Pass 3 while any REVISIT marker remains unresolved (neither re-run nor user-approved).**

#### Pass 4: Documentation-ripple sweep (conditional)

**Gating**: Check the project's `## Doc & Test Guidelines` section. When it is a waiver (heading with a single-line decline body per `shared/skills/qplan/TEMPLATES.md § Doc & Test Guidelines`), skip Pass 4 entirely. When the section is absent, run with the canonical default rules. When the section is present and active, run normally.

**Signal derivation**: Identify the plan's commits by filtering `git log` for commits whose message scope matches `<plan-slug>` (e.g., `git log --all --grep="(<slug>)" --format="%H"`). If no commits match the slug (plans predating convention adoption, inline plans, or squashed history), skip Pass 4 and record in the Completion Summary's `### Acknowledged at archival` sub-heading: "Pass 4 skipped — no slug-matched commits found (doc-ripple coverage unchecked)."

From the matched commits, derive removal/rename signals:
- **Renamed/deleted files**: `git diff <first-slug-commit>^..<last-slug-commit> --diff-filter=RD --name-only` (if the first slug-matched commit has no parent — i.e., it is the repo's initial commit — use the empty tree as the base: `git diff 4b825dc...<last-slug-commit> --diff-filter=RD --name-only`)
- **Within-file identifier extraction**: For each commit, `git show <sha> --diff-filter=MD -U0` piped through a heuristic filter for: removed lines containing port-like patterns (`:\d{4,5}`), URL-like patterns (`https?://`, `localhost:`), identifier-like tokens (`[A-Z_]{3,}` environment variables, `\w+\.\w+` file paths), entry-point commands (`python \S+`, `node \S+`), and mode/component names from removed function/class definitions. This step is agent-assisted (not purely mechanical) — the agent uses judgment to extract meaningful search terms from the diff context.

**Scope exclusion**: Exclude from the grep:
- Identifiers already covered by the plan's `## Documentation Updates` table (verified by Pass 1)
- `plans/done/` (archived, write-frozen)
- `plans/<current-plan-file>` (contains old identifiers as quoted context)

**Grep scope**: All git-tracked `*.md` files not excluded above, plus any non-markdown files listed in the plan's Documentation Updates table.

**Commit topology for fixes**: Pass 4 approved fixes are applied to the doc files and staged before Step 6 begins. Step 6's archive commit pathspec includes both the archive-move paths AND any Pass 4-modified doc paths — producing a single commit that atomically archives the plan and fixes the stale references it left behind.

**Findings presentation** (agent-judged scope assessment):

- **Limited/mechanical** (the stale references are pure substitutions — old name → new name, old path → new path, old port → new port): present a numbered table of findings with file:line, the stale reference, the suggested replacement, and a one-line rationale per item. The user confirms/rejects as a batch or partially (by item number). Applied fixes are staged alongside the archive commit.

- **Substantial** (conceptual drift, architecture descriptions requiring rewriting, or volume beyond mechanical substitution): provide a strong rationale explaining why this warrants its own `/qexplore` → `/qplan` and ask the user how to handle it. The user can: accept the follow-up recommendation (noted in Completion Summary, archival proceeds), or override to inspect items individually.

**Scope-assessment heuristic**: mechanical = every finding is a literal-string substitution (old name → new name, old port → new port, old path → new path); substantial = any finding requires sentence rewriting, paragraph restructuring, or domain-context judgment beyond mechanical replacement.

**No autonomous doc edits** — the user always confirms before any documentation file is modified.

**Uncertain findings**: When the agent cannot determine whether a grep hit is genuinely stale or intentionally retained (e.g., a backwards-compatibility reference, a deliberately preserved old name), include it in the findings table with a `[needs judgment]` marker and a brief explanation of the ambiguity. The user decides.

**Rejection audit**: When the user rejects findings (all or partial via "Reject all" or by item number), record a one-line entry in the Completion Summary's `### Acknowledged at archival` sub-heading: `Pass 4: N documentation-ripple findings rejected by user` (listing the rejected items). This maintains the audit trail for future readers.

**Zero findings**: If the sweep finds no stale references beyond the Documentation Updates table coverage, proceed silently (no user prompt needed).

### Step 3: Add completion summary

At the top of the project file (in the header blockquote), update:
- **Status**: set to `Complete` only if all required phases are truly complete. If operational rollout or cleanup remains pending, use the state–detail form `In Progress — <what remains>` (for example, `In Progress — implementation complete, rollout/cleanup pending`) instead of `Complete` — per `shared/skills/qplan/TEMPLATES.md § Status Grammar`. (Archived state is encoded by the `plans/done/` location, not by a Status value.)
- **Last Updated**: set to today's date and time — the `Last Updated` header field defined in `shared/skills/qplan/TEMPLATES.md § Status Grammar`.
- **Memory relied on**: if the header has no `> **Memory relied on**:` line, add `> **Memory relied on**: none` after `> **Scope**:` (same section), so an archived plan never leaves the field ambiguous. An existing line (headings separated by ` | `) is kept as `/qdev` wrote it. `/qdream` reads it as the `Usage` feeder (`shared/skills/qdream/memory-rules.md § Derived Utility & Pruning`).

If Step 2 surfaced any items the user chose to act on (other than **Fix now**), add (or extend) a `## Completion Summary` section below the header blockquote with an `### Acknowledged at archival` sub-heading. List each item under that sub-heading with its category, original text, and decision label. The label set is:

- `Accepted` — standard category, action chosen was Accept-and-note.
- `Follow-up plan intended` — standard category, action chosen was Open-follow-up.
- `Promoted: <one-line>` — harness-improvement-opportunity, action was Promote (the linked governance edit ships in the same commit; this label records the intent in human-readable form).
- `Accepted (harness opportunity): <one-line>` — harness-improvement-opportunity, action was Accept-and-note.
- `Skipped (harness opportunity): <reason>` — harness-improvement-opportunity, action was Skip.
- `Accepted (reduced review rigor): <persona(s)>, <phase or final>, <date>` — REVISIT marker, user approved archival without sub-agent re-review.

This section is the documented home for post-implementation loose ends so future readers can reconstruct what was knowingly deferred — or knowingly promoted into governance — at archival time.

### Step 4: Determine archive destination

First check the project's governance files (`AGENTS.md`, `CLAUDE.md`, or equivalent). If they define the archive location or naming convention, follow them over this skill's defaults. **When governance-defined naming differs from this skill's default**, warn the user explicitly before proceeding — e.g., "Governance in `AGENTS.md` specifies `<governance form>` which differs from this skill's default `YYMMDD-HHMM_UPPER_CASE_NAME.md`. Using governance form." This surfaces the override rather than silently applying it.

1. **Archive location**: use the project-governed archive location. If governance is silent, resolve the project-file root through `shared/skills/qdream/memory-rules.md § Resolution contract`, artifact class *project files*, and archive to `done/` under that root. In a no-create folder (step 3) the contract returns the workspace's own `plans/`, so the archive location is `plans/done/` there, and active project files live in `plans/` per `/qplan` defaults.

   **Do not re-purpose `--project-root` as a plan-root flag.** That flag selects the workspace root inside a monorepo, which is a different question from which repository the project file lives in. When the resolved project-file root sits in a **different repository** from the workspace, **no special handling is needed and no halt applies**: the archive script derives its repo root from the SOURCE path, so `git mv` runs in the repository the project file actually lives in whatever the current directory is. **`--project-root` is an optional override, not a required flag**: the script derives the destination root from the source's own `plans/` parent, so a store-backed plan at `<store>/plans/<file>.md` in the store repo archives to `<store>/plans/done/` — inside the store — with no flag at all, and a monorepo plan at `<sub>/plans/<file>.md` archives to `<sub>/plans/done/`. Pass the flag only to override that derivation, and when you do, **pass an absolute path**: a relative value resolves against the script's working directory, which for a store-backed plan is normally a different repository, and the script then exits 4 with `--project-root directory does not exist`. The script hard-errors with exit 5 whenever the destination lands in a **different repository** than the source — from `--project-root`, from `--dest`, or from the derived default alike — archival has no legitimate cross-repository case, so a cross-repo `git mv` is never run silently. (Note the same flag name means something different in `qvalidate.py`, where it is the CODE root for git operations; that divergence is deliberate and documented in both scripts' headers.)
2. **Archive filename derivation (dry-run)**: invoke

   `<python> <skill-dir>/scripts/close-plan.py --dry-run <source-path>`, where `<python>` is the playbook venv's interpreter with `-I` (`<config-repo>/.venv-agent-playbook/Scripts/python.exe -I`, `shared/AGENTS.md § Config Repo Locations`), never a `python` from PATH.

   A source outside `$PWD/plans/` needs no flag: the script locates `plans/` from the source path itself. Pass `--project-root <absolute-dir>` only to override that derivation — and only as an **absolute** path, since a relative one resolves against the script's working directory.

   **Workspace root detection (monorepo safety):** No longer needed for the common case — the script strips the trailing `plans/<filename>` itself, so `support/acme/widget/plans/foo.md` already archives to `support/acme/widget/plans/done/` with no flag. If you do check by hand, **anchor the git query at the source**: `git -C "$(dirname <source-path>)" rev-parse --show-toplevel`. A bare `git rev-parse --show-toplevel` answers for `$PWD`, and when the project file lives in another repository `$PWD` is that other repository — so comparing its root against a source-derived root reports a difference that says nothing about the source's layout.

   Capture the printed `DRY_RUN\t<destination>` line — the destination path is the second tab-separated field. **Hold the captured destination in working memory** for Step 5 (display) and Step 6 (live invocation). The script preserves the source's existing UPPER_CASE name and prepends the current `YYMMDD-HHMM` prefix; convention is `YYMMDD-HHMM_UPPER_CASE_NAME.md`. Example: `260416_WORKFLOW_SKILL_IMPROVEMENTS.md` → `plans/done/260416-1830_WORKFLOW_SKILL_IMPROVEMENTS.md`.

   **Governance override**: if the governance check above determined the archive uses a non-default name or location, invoke the script with `--dest <governance-derived-full-path>` for both the dry-run here and the live move in Step 6. The `--dest` flag bypasses the script's default-derivation entirely. Pre-script behavior (the warning when governance differs from the skill default) is unchanged.
3. **Grandfathering**: existing files in `plans/done/` keep their current names (most are `YYMMDD-HHMM_snake_case.md`). Only future archivals use the new UPPER_CASE default. Do not retroactively rename existing files.

### Step 5: Confirm with the user

**Auto-confirm**: Skip this confirmation step when Step 2's cleanup scan found zero unresolved items AND the user explicitly requested archival in the current session. Proceed directly to Step 6.

Otherwise, before moving the file, show:
- Source path: `<current location>`
- Destination path: `<archive location>/YYMMDD-HHMM_name.md`
- Status update preview

Ask the user to confirm before proceeding.

### Step 6: Execute the move

1. Edit the project file in-place (status/timestamp updates from Step 3)
2. **Stage the edits**: run `git -C <plan-root> add -- <source-path>` so the working-tree changes are in the index. This is critical — `git mv` moves the indexed (staged) content, not the working tree. Without this step, the archive destination will contain the old committed content and the edits will appear as unstaged modifications on the new path. **`git -C <plan-root>` is not optional when the project file lives in another repository** (a workspace store): a pathspec reaches only inside the repository the command runs in, so a bare `git add` run from a working directory in the code repository errors. `<plan-root>` is the root resolved in Step 1 — any directory inside the plan's own repository will do, since git resolves the repository from it.
3. **Live archive move (timestamp-locked)**: invoke the same archive script with `--dest <captured-destination-from-Step-4>` (no `--dry-run`):

   `<python> <skill-dir>/scripts/close-plan.py --dest <captured> <source-path>`

   The `--dest` flag locks the destination so the move uses the exact filename previewed to the user in Step 5 — no timestamp drift between preview and actual move. The script prints `MOVED\t<destination>` on success, preserves git history as a tracked rename, and exits 2 with nothing moved when a git command it needs fails. The script also **auto-stages any unstaged working-tree edits to the source** immediately before `git mv` — without this, the Step 3 status/timestamp edit (made in the working tree but not yet staged) would be excluded from the archival commit because `git mv` stages only the path move and reads content from the index. Auto-staging keeps the rename + content update atomic in a single commit. **Recovery on failure**:

   - **`git mv` fails before any commit**: the script puts the index back as it was before the run, so nothing is half-staged and the user's own staged changes are kept. Fix the cause its message names, then re-invoke item 3. Only when the message says the index restore itself failed, run the `git -C <plan-root> restore --staged <source>` it prints.
   - **`git mv` fails after the status-edit was already committed**: complete the archive rename as a separate fixup commit — `git -C <plan-root> mv <source> <captured-destination>` followed by `git -C <plan-root> commit -m "fix(<plan-slug>): complete archive rename"`. If the situation is ambiguous (e.g., unclear whether the status-edit commit is correct), stop and ask the user.

   Every git command in this step carries `-C <plan-root>` for the reason given in item 2.

   **Same-minute collision** (destination already exists) → script exits 3 with `close-plan.py: destination exists: <path>`; resolve by re-running Step 4 to capture a fresh timestamp or by manually computing a different `--dest` path.

   Note: the source file must be tracked in git (`git mv` requirement). If the plan was created with `/qexplore`/`/qplan` and committed, this is satisfied automatically. The script automatically creates `plans/done/` if it does not exist.

   **Non-git plan root**: when `git -C "$(dirname <source-path>)" rev-parse --show-toplevel` fails (the plan's directory is not inside any git repository, for example a plain-folder roadmap workspace), the archive script cannot run: it exits 2 with `not in a git repo`. Skip items 2 and 3 and item 4's commit, and archive with a plain move instead. Use the destination captured in Step 4 (construct it by the Recovery section's item 1 rule when the dry-run also exited 2), create the `done/` directory if absent, then move the file with `Move-Item` (Windows) or `mv` (Linux/WSL/macOS), after the item 1 edit has been saved. Confirm the source no longer exists and the destination does, and report in the Completion Summary that archival was a plain move with no commit. Do not run `git init` to make the script work. A plain move keeps no history, so the plan's `> **Date**: YYYY-MM-DD` header (Recovery, item 1) is the only authoring anchor: confirm it is present before moving. Pass 4 of Step 2 is already skipped in this case, because no slug-matched commits exist.
4. If the user wants, create a git commit for the archival using the format `docs(<plan-slug>): archive to <archive-filename>` (ASCII "to", not a Unicode arrow), where `<plan-slug>` is the source plan filename without `.md` and `<archive-filename>` is the new filename under `plans/done/` (e.g., `260416-1830_WORKFLOW_SKILL_IMPROVEMENTS.md`). See `shared/AGENTS.md § Commit Conventions` for the canonical rule. **Run it as `git -C <plan-root> commit … -- <paths-relative-to-plan-root>`**: this commit has no safety net — the script auto-stages the source in item 3, but nothing stages or commits for you here, and a bare pathspec commit from a working directory in the code repository simply errors. The commit pathspec must include BOTH sides of the rename — the old `plans/<file>` path and the new `plans/done/<file>` path — because `git mv` stages a delete+add pair and a pathspec naming only the destination commits half the rename, leaving the staged deletion dangling. Additionally, if Pass 4 (documentation-ripple sweep) modified any doc files, include those paths in the same commit pathspec — this produces a single atomic commit that archives the plan and fixes the stale references it left behind.

5. **Scratch folder**: on a full archive, run `<python> <config-repo>/shared/skills/qdream/scripts/store-resolver.py scratch-clean --plan <source-path>`, and name any `DELETED` or `FAILED` line in your report. Skip this on a partial archive.

### Step 7: Memory consolidation (lightweight)

After archival is complete, invoke `/qdream lightweight` scoped to the just-archived plan. This extracts learnings (resolved decisions, feedback, patterns) from the completed plan and proposes them as memory entries via the standard proposal format. Maximum 3 proposals. A user's `Skip` of one of these proposals is recorded as a `## Declined` row, on every provider including kiro, at the location `shared/skills/qdream/memory-rules.md § Resolution contract` returns (`shared/skills/qdream/memory-rules.md § Memory File Format`, Declined records). Do not treat a lightweight run as exempt from that rule. Before showing a candidate, apply the write-time self-test to it (durable? painful to rediscover? already in governance? — `shared/AGENTS.md § Write-time quality gates`); a candidate that fails is suppressed, not shown. The `/qclose` report states the suppressed count ("suppressed: N", 0 included). The extraction pass itself is unconditional — run it, and if it yields nothing, report "no proposals"; only the proposal *output* may be empty. Judging the session "too long" or the learnings "too straightforward" before running the extraction is the rationalization the mandatory-step rule forbids.

Relay both lines that the lightweight report ends with (`dream-manifest.py count`: `sweep due:` and `memory budget:`) in the `/qclose` report, verbatim — in Research mode too.

This step replaces the previous memory-proposal behavior. It does not block archival — if `/qdream` fails or is unavailable, archival is already committed. **"Unavailable" means a dispatch or tool error with recorded output** — never your own judgment that consolidation is unnecessary, redundant, or already covered. Self-declaring the step unavailable is the mandatory-step rationalization this paragraph forbids one sentence earlier.

### Recovery (when the script fails)

If the archive script errors and the issue cannot be quickly resolved, prefer fixing the script issue and retrying. Use this manual path only after diagnosing why the script failed:

1. **Construct the archive filename**: `YYMMDD-HHMM_<UPPER_CASE_NAME>.md` using current local time. The `<UPPER_CASE_NAME>` portion is the source filename with its `YYMMDD_` date prefix stripped. Example: `260428_MY_FEATURE.md` → `260428-1530_MY_FEATURE.md`.

   **The prefix is ARCHIVAL time, not authoring time — so preserve the authoring date inside the file.** Before renaming, confirm the plan carries a `> **Date**: YYYY-MM-DD` header recording when it was authored; add it from the plan's first commit date if absent. Once the file moves, that header is the only recoverable authoring anchor. Any consumer reading `plans/done/` chronologically — including `/qdream`'s plan-cluster analysis — must cross-check it rather than trusting filename order: archival-time filenames do not reliably preserve authoring order, and a plan with no internal date header makes that cross-check impossible.
2. **Create the archive directory** if absent: `mkdir -p <plan-root>/done` (Linux/macOS) or `New-Item -ItemType Directory -Path <plan-root>/done -Force` (Windows).
3. **Move with history**: `git -C <plan-root> mv <source> <plan-root>/done/<constructed-name>` — anchored with `-C` because `$PWD` may be a different repository than the project file's. `<plan-root>` is already the workspace's own `plans/` in a monorepo, so never substitute a repo-root `plans/`.
4. **Stage and commit**.

## Research mode

Archives a completed `/qauto-research` run: a close commit on the research branch, an archive commit on the source branch under `<plan-root>/done/<plan-slug>/`, an optional squash-merge and teardown, then `/qdream lightweight`. The full procedure is in `research-mode.md` alongside this file; read it in full before starting.

## Rules

Rules that are not stated in a step above:

- Do NOT archive a plan with incomplete phases without explicit user approval
- Never archive a plan as `Complete` while rollout, migration, cutover, or cleanup work is still pending, even with approval: archive it as `In Progress — <what remains>`
- Archived files under `<plan-root>/done/` are write-frozen: never retro-edit an archived project file — `/qdream`'s harvest re-reads the archive as ground truth, and a retro-edit corrupts its frequency gates. Corrections and follow-ups go in a new plan or the live project file, citing the archive.
