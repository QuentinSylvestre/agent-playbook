---
name: qhandoff
description: Export a structured handoff document so another session or agent can continue the current work.
argument-hint: "<optional: destination or next-session focus>"
---

# Handoff

## Your role

You export a structured continuation document for cross-session work transfer. The handoff captures current execution state in a format a fresh agent can act on immediately — three temporal layers (what happened, what's parked, what's active) with references to persistent artifacts rather than duplicated content.

## Input

$ARGUMENTS

## Process

### Step 1 — Argument parsing

**Resolve the project-file root before parsing any path**, through `shared/skills/qdream/memory-rules.md § Resolution contract`, artifact class *project files*. Every `plans/` path **this skill scans or writes** means that resolved root: the `plans/` of the workspace's store in the store repo, or the workspace's own `plans/` when the contract keeps project files in the folder.

Two things stay literal and are never rebound: a path the **user typed** as an argument, which is used exactly as given, and the **invocation examples** in this skill, which show what a user types rather than what the skill resolves.

Parse the user's invocation to determine output destination:

- **No argument**: default to appending `## Handoff` section to the active project file (Step 2).
- **Path argument**: user provides an explicit file path — write there instead.
- **Descriptive argument** (e.g., "standalone", "to clipboard"): resolve semantically (contains a path separator or file extension → path argument; else descriptive). "Standalone" → `plans/.handoff-YYYY-MM-DD.md`. Unsupported targets (clipboard, remote) → "Clipboard output isn't supported. Writing standalone to `<fallback path>` instead."
- **Next-session focus** (e.g., "focus on the CSS migration"): capture as advisory in the `### Current` section; output destination remains the default.

**Multi-plan ambiguity**: If >1 project file in `plans/` has `Status: In Progress` and the user did not specify a path, do NOT guess. Error with: "Multiple active plans found: `<list>`. Specify which plan to write the handoff to, or use a standalone path, e.g., `/qhandoff plans/260715_MY_PLAN.md`"

### Step 2 — Locate active plan

Scan the project-file root resolved in Step 1 (excluding its `done/` subdirectory) for files whose Status line reads `In Progress` (status values per `shared/skills/qplan/TEMPLATES.md § Status Grammar`).

- **Exactly one found**: use it as the target project file.
- **Zero found**: no active plan — output will go to standalone path (`plans/.handoff-YYYY-MM-DD.md`) unless the user specified a path.
- **Multiple found**: handled by Step 1 ambiguity gate.

If the resolved root does not exist, treat as zero-found and route to standalone mode. If standalone mode would write to `plans/.handoff-YYYY-MM-DD.md` but the resolved root doesn't exist, write to `.handoff-YYYY-MM-DD.md` in the workspace root instead.

Plans lacking a Status line are skipped with a warning to the user.

### Step 3 — Gather state

Collect from the current session and workspace:

1. **Conversation context** — key decisions made, corrections received, open questions, user preferences expressed this session.
2. **Plan status** — if a plan exists: which phases are complete, which is current, what exit criteria remain.
3. **Open decisions** — any unresolved choices the user deferred or that await external input.
4. **Working-tree state** — uncommitted changes (`git status`), current branch, recent relevant commits (depth at agent's judgment). If not in a git repository or no commits exist, skip working-tree state and note the absence in the handoff.

### Step 4 — Produce handoff

Write the document using the template in `## Output format` below.

- **Previously** — completed work, key decisions with reasoning, constraints discovered. Reference project file, commits, and memory entries by path.
- **Parked** — suspended threads with notes, file refs, open questions. Each item marked with staleness advisory when state may have changed.
- **Current** — exact current objective. What's done, what remains. Suggested next steps (advisory) — name specific skill + entry point.

### Step 5 — Write output

**Project-file mode** (default): Append a `## Handoff` section to the target project file. If a `## Handoff` section already exists, replace it entirely (the skill is idempotent — latest invocation wins).

**Standalone mode**: Write to `plans/.handoff-YYYY-MM-DD.md` (or user-specified path; the general pattern is `plans/.handoff-*.md`). The file contains only the handoff content (timestamp + 3 sections), prefixed with a one-line header: `# Handoff — <plan title or "ad-hoc session">`. The standalone file has two actual consumers: `/qdev`'s Handoff ingestion step (`shared/skills/qdev/SKILL.md § Step 1`) reads and deletes it when a plan session starts, and `/qclose`'s cleanup pass (`shared/skills/qclose/SKILL.md § Pass 1: Project cleanup`) removes any leftover copy at archive time if no `/qdev` session ever consumed it. Users who git-track `plans/` may want to add `plans/.handoff-*` to `.gitignore`.

**User-specified path**: Write to the exact path provided. Create parent directories if needed.

After writing, confirm to the user:
- **Project-file mode**: "Handoff written to `<path>`. A fresh session running `/qdev` on this plan will ingest the handoff automatically."
- **Standalone/ad-hoc mode**: "Handoff written to `<path>`. A fresh session can read this file to resume context."

## Output format

The handoff document has this structure:

```
> Handoff written: YYYY-MM-DDTHH:MM:SS±HH:MM

### Previously

- <completed item — reference by path, not inline content>
- Key decision: <what was decided> — rationale: <why> (see plans/<file>.md § <section>)
- Constraint discovered: <description> (see memory/MEMORY.md § <entry>)

### Parked

- <thread description> — ref: <path:line-range> — [potentially stale]
- Open question: <question> — awaiting: <what/who>

### Current

- Objective: <one sentence>
- Done: <what's complete in current phase>
- Remaining: <what's left>
- Suggested next: `/qdev` on `plans/<file>.md` Phase N (advisory)
```

**Size advisory**: Soft cap of ~50 lines. If exceeding, compress the `### Previously` section first (it references persistent artifacts that the consuming agent can read directly). The `### Current` section should never be compressed — it carries the highest-value state for continuation.

## Rules

- Do not duplicate content already in the project file, commits, or memory — reference by path (e.g., `plans/<slug>.md § Phase N`, `memory/MEMORY.md § <heading>`, commit `abc1234`) <!-- verify-links: skip memory/MEMORY.md -->
- Redact secrets — reference by key name, never value (e.g., `$DATABASE_URL`, not the connection string)
- Do not record agent-inferred statements as user statements (per `shared/AGENTS.md § Multi-Agent Coordination`)
- Use qualified file references (`path:line-range`) for code locations
- Maximize information density; zero filler
- The handoff is advisory — the consuming agent may disregard suggestions if context has changed
- If no actionable state exists (no decisions, no open threads, no in-progress work), inform the user: "No actionable state to hand off. If you want to capture intent for a future session, try `/qexplore` first."
- Apply the **Harness Improvement Capture** rule in `shared/AGENTS.md` when encountering harness friction during handoff production
- Inter-tool and multi-agent handoff (agent A → agent B in same session) is out of scope — this skill transfers state across sessions, not within them
