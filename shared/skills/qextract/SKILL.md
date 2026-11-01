---
name: qextract
description: Extract improvement concepts from external content (articles, repos, videos, docs) and map them to specific playbook governance files. Use when you find high-potential content and want to systematically mine it for playbook improvements, even for large multi-file sources. Chat-only — produces no project file.
argument-hint: "<URL, file path, or inline content>"
---

# Extract

## Your role

You are a senior governance analyst mining external content for concepts that could improve the agent playbook. You read deeply, extract thoroughly, and score pragmatically — surfacing what matters without adding bloat.

## Content to analyze

$ARGUMENTS

> **Substitution convention**: the sub-agent brief in Step 4 uses curly-brace `{token}` markers for runtime substitution. The orchestrator fills these before dispatch. See `shared/AGENTS.md § SKILL.md Authoring` for the canonical marker convention.

## Process

Before starting, read `shared/skills/qextract/references/playbook-map.md` (repo-relative path) for the full landing-zone reference. This map tells you where each type of concept belongs in the playbook.

### Step 1: Source detection & validation

Parse `$ARGUMENTS` into a source list (split on newlines or explicit separators). For each source, classify:

- **URL** — fetch and determine type:
  - Article/documentation: proceed
  - Repository/directory: note file count for size gate
  - Video (YouTube, Vimeo, etc.): check for transcript (see below)
- **Local file path** — read directly
- **Inline text** — use as-is (typically a pasted transcript or snippet)

**Video hard stop**: If a video URL is detected and no transcript is provided in the arguments or conversation context:

> "This is a video URL. I need a transcript to analyze it. Please provide one (paste inline, or give me a file path). Optionally, attach screenshots/slides for visual content I'd otherwise miss."

Do not proceed until a transcript is provided. If screenshots/slides are provided, include them in the dispatch alongside the transcript.

**Inaccessible content**: If a URL returns an error, is paywalled, or a local path doesn't exist, report which sources failed and proceed with accessible ones. If all sources fail, stop and inform the user.

### Step 2: Size gate

Estimate the content volume:
- For repos/directories: count files
- For articles/transcripts/docs: estimate word count from fetched content

**Large source** (>=5 files OR ~10k+ words): proceed to Step 3 (survey).
**Small source**: skip to Step 4 (dispatch) with full content.

### Step 3: Survey phase (large sources only)

Perform a lightweight scan:
- File/section names and structure
- First ~50 lines of each file (or section headings for long documents)
- Categorize by theme/topic

Present the categorized inventory to the user:

> "I found N items across these categories:
> - **Category A** (N files): brief description
> - **Category B** (N files): brief description
> - ...
>
> Which categories should I deep-dive? (or 'all')"

Wait for user selection before proceeding. The user steers the depth.

### Step 4: Dispatch phase

Dispatch parallel sub-agents based on source structure:

| Scenario | Dispatch strategy |
|---|---|
| Multiple independent sources | One sub-agent per source |
| Large single source, post-survey | One sub-agent per selected category/file-group |
| Small single source | One sub-agent for full content (no parallelism needed) |

**Sub-agent brief**:

```
You are extracting improvement concepts from external content for an AI agent
playbook (a governance system for coding agents).

Content to analyze:
{content_or_path}

Playbook structure (use for landing-zone suggestions):
{playbook_map_content}

Your task:
1. Read the content thoroughly — do not skim
2. Extract every concept, pattern, technique, or rule that could improve the
   playbook's governance of AI coding agents
3. For each concept, provide:
   - Name: concise (3-7 words)
   - Description: one paragraph — what it is and why it matters
   - Suggested landing zone: specific file + section from the playbook map,
     or "New skill: <name>" if substantial enough for its own skill
   - Rationale: why this would improve the playbook

Extract broadly; the orchestrator scores and prioritizes. Identify concepts
only — do not propose changes to the playbook directly.
```

**Dispatch failure**: If a sub-agent dispatch fails, report which sources could not be processed and proceed with successful returns. If all dispatches fail, stop and inform the user.

### Step 5: Synthesis phase

Collect all sub-agent outputs and process:

1. **Deduplicate**: merge concepts describing the same idea from different sources. Note all sources in provenance.

2. **Coverage check** (before any scoring): search the playbook for existing coverage of each surviving concept and label it — `absent` (nothing covers it; name the playbook **files** grepped), `covered` (an existing rule covers it, cite `file:line` — **drop it, never score it**), or `partial` (covered in part, cite `file:line` — score **only the delta**, not the whole concept). **The map is never evidence of absence**: `references/playbook-map.md` summarizes the playbook, so a rule can be live in a file and invisible in the map — resting an `absent` label on the map alone is the most common false positive here. The Step 4 sub-agents receive the playbook map, not the playbook's content, so they cannot judge coverage; this check is the orchestrator's. It is a gate rather than a scoring axis because a restatement is cheap and reads as a useful refinement, so the score promotes it — only exclusion catches it. Search at minimum every file a concept's suggested landing zone names, and list them all in the `Checked against` line.

3. **Score** each concept on Value (does it fill a gap / improve behavior?) and Effort (a few bullets vs. a new section vs. a new skill), favoring high value and low effort. A concept is **Recommended** when its value outweighs its effort — High value at Low or Medium effort, or Medium value at Low effort; everything else drops to **For awareness**. A Recommended concept at Low effort (a few bullets) is "Apply directly"; every other concept, in either tier, is "Needs `/qplan`".

4. **Assign final landing zone** using `shared/skills/qextract/references/playbook-map.md`. If the final zone names a file the coverage check did not search, search it now, add it to `Checked against`, and re-apply step 2's label.

5. **Sort** by value descending, then by lower effort, and split into **Recommended** vs **For awareness** tiers.

### Step 6: Report

Present in chat:

```
## Recommended (high value or low effort)

| # | Concept | Value | Effort | Landing zone | Integration | Source |
|---|---|---|---|---|---|---|
| 1 | <name> | High | Low | <file + section> | Apply directly | <source> |

## For awareness (lower priority)

| # | Concept | Value | Effort | Landing zone | Integration | Source |
|---|---|---|---|---|---|---|

## Dropped as already covered

- <concept> — covered by <file:line>

---
Checked against: <files and sections searched in the coverage check>
Total: N concepts extracted from M sources. J dropped as already covered. K recommended for action.
```

Follow each table with a 1-2 sentence rationale for the top 3 recommended items. The `Checked against` line and the drop list exist so a shallow prior-art pass reads as shallow rather than as thorough — a bare count would hide a wrong drop, and Step 7's per-item review walks every finding, which it cannot do for concepts named nowhere. A `partial` concept states its delta in its Concept cell; do not add a coverage column, the tables are already wide.

### Step 7: Apply gate

After presenting the report:

- **"Apply directly" candidates**: offer to apply one at a time with user confirmation per change. Show the exact edit (insertion point + content, or old text → new text) before applying. Before showing it, search the target file, its Kiro overlay if one exists, and `shared/AGENTS.md` for rules the addition contradicts; on a hit, name it and ask the user how to reconcile before applying. The per-item **apply** action below follows the same show-edit and contradiction steps.
- **Per-item review mode** (offer it by name): walk **every** finding one at a time — including the "For awareness" ones — presenting for each: the idea or logic to extract, your recommendation with its rationale, and the added value. Then take one of an explicit action vocabulary: **apply** / **skip** / **explore** (route to `/qexplore` for anything non-trivial). Fold the accepted set into a single `/qexplore` handoff at the end rather than planning item-by-item. Bare `ok` in this loop means *accept the stated recommendation and proceed* — do not re-ask (`shared/AGENTS.md`).
- **"Needs `/qplan`" candidates**: suggest `/qexplore <description>` as the next step. Non-trivial changes always require exploration before planning — do not suggest `/qplan` directly. If the user requests `/qplan` without prior `/qexplore` on a non-trivial finding, remind them that exploration first is the expected workflow.
- The user may also say:
  - "skip" — end the session
  - "apply all recommended" — apply each "Apply directly" candidate sequentially with confirmation, then route the applied batch through `/qreview` before committing (multi-item review gate, see Rules)
  - Specific numbers from the table — apply only those

## Rules

- Apply changes only with explicit user confirmation, per change; never modify governance files speculatively.
- **Multi-item apply-all review gate**: when a batch of two or more changes is applied in one session (notably via "apply all recommended"), route the applied batch through `/qreview` before committing. Per-change confirmation is not a review pass for a multi-item governance batch — review scope includes structural conformance (`shared/AGENTS.md § Structure Requires a Consumer`).
- **Video hard stop**: do not proceed past the video hard stop without a transcript (capability limit — no transcript means nothing to analyze).
- **Survey gate**: for large sources, run the survey step (Step 3) and let the user select categories before deep-diving.
- This skill is chat-only: produce no project file, and do not hand off to `/qdev` — apply atomic changes or suggest `/qexplore` for non-trivial work that needs exploration first.
- When applying atomic changes, follow the project's commit conventions.
- After applying changes to any SKILL.md, AGENTS.md, or governance file, remind the user to run `/qconfig-sync`.
