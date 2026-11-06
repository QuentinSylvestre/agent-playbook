---
name: qexplain
description: Explain a code change so the reader genuinely understands it. Writes a self-contained HTML walkthrough of a diff, branch, PR, or commit range — a narrative part, a Cytoscape.js maps part, a Mermaid change-summary part, and an interactive diff-review part — then quizzes the reader in chat and teaches through the gaps. Use when the goal is comprehension of a change — reviewing an inbound PR, understanding a diff an agent wrote, or onboarding into a subsystem. Manual invocation only.
argument-hint: "<PR number, branch, commit range, path, or several label=repo::range pairs> [--all-maps]"
disable-model-invocation: true
---

# Explain

## Your role

You are a teacher. The reader wants to understand a code change, not to be told whether it is good. Everything in this skill serves one test: at the end, can the reader explain the change to someone else without the artifact in front of them.

**Your first action is to resolve the target and run the measuring script, before reading any changed file** (Step 1). Do not start writing the explanation from the diff alone.

**The banned habit is summarising the diff in chat.** A file-by-file recap of what changed is what you would do without this skill. It is not an explanation. It tells the reader what moved; it does not tell them why the change makes sense.

**Do not evaluate.** No findings, no severity, no verdict, no suggestions for improvement. If you notice a real defect while reading, note it in one line at the end of the chat and route the user to `/qreview` — do not fold it into the explanation. Stating what was and was not verified (Part 1) is reporting a fact, not a verdict.

**Do not put secrets in the artifact.** The diff is copied into the page, context lines included, and the page may be stored or shared.

**Do not edit source code.** This skill writes exactly one file in the working tree: the explanation artifact. Its intermediate content files go in a temporary directory outside the repository.

**The artifact is a local file the reader opens from disk.** Do not publish it as a hosted page, and do not apply another skill's page conventions (such as an artifact-design or diagramming skill) to it: this skill's template and validator define the page.

**When NOT to use this skill**:
- To judge whether a change is correct or well-built, use `/qreview`.
- To check whether a change works at runtime, use `/qqa`.
- To hand execution state to another session, use `/qhandoff`.
- To understand the codebase rather than a specific change, use `/qexplore`.

**Isolation**: this skill is manual-invocation only. `disable-model-invocation: true` enforces this on Claude Code — the model cannot auto-load the skill, preload it into a sub-agent, or fire it from a scheduled task. Other providers ignore that field, so the rule also stands in prose: no other skill calls this one, it calls no other skill, and it is never invoked automatically at the end of a phase, a plan, or a review.

## What to explain

$ARGUMENTS

Resolve the argument to a concrete diff:

| Argument form | Resolution |
|---|---|
| Empty | The pending diff on the current branch against its merge base |
| A number (`482`) | That PR — fetch its head and diff against its base |
| A branch name | That branch against its merge base with the default branch |
| A commit range (`abc123..def456`) or a single SHA | That range, or that commit against its parent |
| A path | The pending diff, restricted to that path |
| Several `<label>=<repo>::<range>` pairs | One artifact over those repos; each file's path starts with its label |

`--all-maps` overrides the size tier's map selection (Step 3) and includes every map view.

If the form is ambiguous, ask the user which they meant. If the resolved diff is empty, say so plainly and stop — do not write an artifact for an empty change.

## Step 1: Resolve the target and read beyond the diff

**Measure first, and read nothing yet.** `<python>` is `<config-repo>/.venv-agent-playbook/Scripts/python.exe -I` (`<config-repo>`: `shared/AGENTS.md § Config Repo Locations`), the playbook's one interpreter. If that file is missing or fails to start, stop and tell the user "venv missing — run setup.ps1"; never use a Python from `PATH`.

```
<python> <config-repo>/shared/skills/qexplain/scripts/measure-change.py --repo <dir> --diff-args "<git diff arguments>" [--exclude <glob>]...
```

For several repos, replace `--repo` and `--diff-args` with one `--target "<label>=<repo>::<git diff arguments>"` per repo. For a fetched PR diff, use `--diff-file <unified diff>`. The script prints paths, counts and setting names, never file content. Act on its lines in this order, and re-measure after any change to the excludes:

1. **`FILE` and `LEFT-OUT`: keep secrets out of your context and the artifact.** The script leaves out common secret-bearing names, files it cannot parse, and binary patches. Check every `FILE` path and add `--exclude` for any file that project governance, memory, or the user says not to read in full, and any configuration file that may hold live credentials. A `WARN` means an exclude matched nothing: fix it, because the build refuses it. Never read a left-out file or its diff. To explain its change, use its `SETTING` lines, which name the settings without their values, or ask the user.
2. **`CREDENTIAL`: a flagged file counts as left out until you resolve it.** Never read the flagged line; when you read that file, read around it. For a test or fixture file, or any file the reader needs, pass the match to the build as `--mask-credential <path>:<side>:<line>`, labelled path included: the page shows the line with its value hidden, and you say so in the verified section. For a configuration file, exclude it. If the line says `made-up-test-value=yes`, pass that match to the build as `--allow-credential <path>:<side>:<line>`, labelled path included; the build refuses it for any other match. That mark is a guess from the value's length and wording, so if the plan or the code suggests the value is real, mask it instead. Tell the user about every masked match that is not marked made up: a credential committed to a test file is theirs to judge. Only the user can show such a value on the page, by saying it is not a live credential, and then you pass `--user-confirmed-credential` with the same form. Never copy a credential value into anything you write. The scan is a safety net with known gaps, such as values holding spaces, key bodies with no header in the hunk and passwords holding `@`, so it does not replace step 1.
3. **`SPLIT`: settle it before reading further.** One artifact would be too thin, because the Step 2 limits stay fixed however large the change is. Propose separate runs, by plan or by subsystem, giving each run's commit range and its lines to read from a re-measure. The user chooses. Without a choice, keep one artifact and say in chat what its limits leave out. A change across repos can use one artifact when its parts are one behaviour.
4. **`PLAN`: read the plan.** Find the project file under the project-file root of the repo the line names (`shared/skills/qdream/memory-rules.md § Resolution contract`), in `<root>/` or `<root>/done/`. An archived name has a different date prefix, so match on the name after the first underscore. Read its Intent, Design Decisions, Implementation Divergences, Review Log, verification results and Follow-up Work. Treat them as the author's account: they give the reasons, the code gives the facts, and where they differ the code wins and you say so in chat. `PLAN-SKIPPED`, or no project file: carry on without one.

Next read the diff of every file still shown, then the code around it. The diff shows what changed; the surrounding code is what makes the change intelligible.

At minimum, read:
- Every changed production file still shown, in full — not just the changed hunks.
- Every changed test and fixture file's test names or record shapes, and in full the tests that pin the behaviour you explain, skipping any line a `CREDENTIAL` entry names.
- The callers of every changed function or component, and its callees.
- Any test that exercises the changed behaviour, old or new.
- The data structures the change reads or writes, at their definition.
- The owners of any state the change moves through: what writes it, what reads it, what it is serialised into.

Stop reading when you can answer these three questions without guessing:
1. What did the system do before this change, and why was that a problem?
2. What does it do now, and what is the one idea that makes the new behaviour work?
3. What would break if this change were reverted?

If you cannot answer all three, keep reading. If neither the code nor the plan can settle them, ask the user before writing. A confidently wrong background section is worse than no artifact.

As you read each file still shown, record a one-sentence rationale describing why that file changed. These become `rationales.json` in Step 3 and appear on each file card in Part 4. No additional pass is needed — Step 1 is where you read every changed file.

## Step 2: Size the change and confirm the path

### Size tier

Take the tier from the script's `TIER` line. It counts the lines to read: changed lines outside tests, fixtures and generated files, because a large test file does not make a change harder to explain. The tier sets how much artifact the change has earned. All four parts (Step 3) are always produced; the tier scales depth inside them.

| Tier | Lines to read | Maps | Nodes per map | Tour steps | Quiz questions |
|---|---|---|---|---|---|
| Tiny | Under 75 | System overview only | 2-3 | 1-2 | 3 |
| Small | 75-249 | System overview, plus the one other most relevant | 3-4 | 2-4 | 4 |
| Medium | 250-800 | Three maps | 4-7 | 3-5 | 5 |
| Large | Over 800 | All five | 5-12 | 4-8 | 5 |

Go one tier up when the change spans more subsystems than its line count suggests. When the tier is still unclear, use the lower one.

**Anti-inflation rule.** Do not inflate a small change to fill the page. If two nodes would teach the same fact, merge them. If a map would duplicate another map, omit it rather than pad it. If a section has nothing to say at this tier, cut the section — a sparse artifact that respects the reader beats a padded one that does not.

With `--all-maps`, include every map regardless of tier, and mark each map the tier would normally have omitted with a short note saying so. Keep the node and tour-step budgets of the actual tier; the flag widens coverage, not volume.

### Artifact path

Propose a path in the workspace's store or inside the current repository, then wait for the user to confirm or correct it before writing.

Pick the directory by the first rule that matches:
1. The project resolves to a workspace store for the *project files* artifact class per `shared/skills/qdream/memory-rules.md § Resolution contract` — propose `<store>/explanations/`.
2. A `plans/` directory exists at the repo root — propose `plans/explanations/`.
3. A `docs/` directory exists at the repo root — propose `docs/explanations/`.
4. Otherwise — propose `explanations/` at the repo root. This is the fallback when nothing else matches.

Name the file `YYMMDD_<SLUG>_EXPLANATION.html`, where `YYMMDD` is today's date and `<SLUG>` is a short upper-snake description of the change (for example `260814_TOKEN_REFRESH_EXPLANATION.html`).

State the path, the size tier you measured and why, and whether git ignores the path. Run `git -C <the repo holding the path> check-ignore -q <path>`, after creating the directory if it is new, because the command fails on a path outside the repo. Report one of:
- "This path is git-ignored, so the file will not show up in `git status`."
- "This path is **not** git-ignored, so the file will appear as untracked in `git status`."

Do not modify `.gitignore`. Do not stage the file. Do not commit it. If the user wants the artifact tracked, that is their commit to make.

Wait for confirmation before writing. If the user names a different path, use it as given.

## Step 3: Write the explanation

One HTML file, split into four **parts** the reader switches between from a bar at the top. Each part is a different way of explaining the same change, and each is labelled so the reader always knows which one they are looking at.

| Part | Key | What it is |
|---|---|---|
| Narrative | `narrative` | The prose walkthrough: background, intuition, code |
| Maps | `maps` | Interactive Cytoscape.js views of the changed system, each with a guided tour |
| Change summary | `summary` | Per-file inventory table plus Mermaid sequence diagrams |
| Diff review | `diff` | Interactive split-pane diff navigator with file sidebar, filter buttons, reviewed tracking, and per-file rationale |

**You write the content; the template supplies the page.** The page itself (part bar, map tabs, tours, theme toggle, URL hash routing, the whole diff-review UI, pinned libraries) lives in `assets/template.html` and is never rewritten per artifact. Write four content files in a temporary directory outside the repository:

| File | Contains |
|---|---|
| `narrative.html` | The Part 1 HTML fragment |
| `summary.html` | The Part 3 HTML fragment |
| `maps.json` | The Part 2 views, in the shape below |
| `rationales.json` | `{"<path as in the diff>": "<one sentence>"}` for every file still shown, from Step 1 |

Then build the artifact at the path confirmed in Step 2, with the `<python>` from Step 1.

```
<python> <config-repo>/shared/skills/qexplain/scripts/build-explanation.py --out <path> --title "<title>" \
  --base <base SHA> --head <head branch, or SHA when there is no branch> \
  --repo <dir> --diff-args "<the git diff arguments that resolve the target>" \
  --narrative <dir>/narrative.html --summary <dir>/summary.html \
  --maps <dir>/maps.json --rationales <dir>/rationales.json \
  [--exclude <glob>]... [--mask-credential <path>:<side>:<line>]... [--allow-credential <path>:<side>:<line>]... [--user-confirmed-credential <path>:<side>:<line>]...
```

For a PR whose diff you fetched another way, pass `--diff-file <unified diff>` instead of `--diff-args`. For several repos, pass one `--target` per repo instead, key `rationales.json` by the labelled paths, and give `--base` and `--head` a readable text naming each repo's ref. Pass the same `--exclude` values you measured with. The scripts accept only revisions, paths, `--cached`, `--merge-base` and `-U<n>` in those arguments. A value starting with a dash needs the `=` form: `--diff-args=--cached`.

The script captures the diff as UTF-8, removes the excluded files, inlines all data safely, wires the part and map tabs, warns about any changed file without a rationale, and runs the Step 4 validator. Fix every warning before moving on. It stops with nothing written if it finds credential-shaped text in the diff or in your content files; reword your own text, because it cannot be allowed.

Inside the Narrative part, the content stays one scrolling page with its own table of contents — the argument has to be readable straight through, so do not tab it up.

### Part 1 — Narrative

#### Background

Two levels, clearly labelled:

1. **Deep background** — for a reader new to this part of the system. Open it with a one-line note that a reader already familiar with the area can skip ahead. Explain the domain concepts and the machinery the change sits on.
2. **Narrow background** — the specific mechanism this change touches, and the state of it immediately before the change. End on the problem: what was wrong, or what was missing.

**Artifact-independence test.** The deep background and the system overview map must make sense with the change closed. Written well, either could be pasted into the project's own documentation and read by someone who has never seen this diff. Enforce it concretely: no "this change...", "this PR...", or "before and after" phrasing in those two places, and no links into the diff from them. Deltas belong in the narrow background, the code walkthrough, and the other maps. If a sentence in the deep background stops making sense once the diff is forgotten, it is in the wrong section.

#### Intuition

The core idea, and only the core idea. Details belong in the next section.

- Lead with the one sentence a reader should remember.
- Use concrete toy data. Invent small, readable examples — three records, two users, one request — and walk them through the old behaviour and then the new. Named values beat abstract descriptions.
- Use diagrams here more than anywhere else in this part. Mermaid renders only in the Maps and Change summary parts, so draw these with styled HTML.

#### Code walkthrough

Walk the changes at a high level. Group and order them so they build on each other — the entry point first, then what it calls, then the supporting edits. Never walk the files in the order git printed them, and never in alphabetical order.

For each group: what it does, and why it had to change given the idea from the Intuition section. Show short excerpts, not whole files. Skip mechanical churn (renames, import reordering, formatting) in one line rather than narrating it.

#### What was and was not verified

A heading with `id="verified"`; the validator fails without it. State facts only, so the reader knows what the evidence covers:

- What ran, and where: test suites, reviews, lab runs, and the environment each used.
- What did not run, among the environments and paths the plan or the code names. Name a review that ran without restating its findings.
- Where each fact comes from: a test name, a plan section, or a command you ran. Say "not recorded" when no source says.

No judgement of whether that is enough. List the files left out here too, with what you could not explain because of them.

### Part 2 — Maps

A tabbed panel of complementary views, rendered with **Cytoscape.js + dagre**. Each view answers a different question, so do not merge them into one diagram.

| View | Key | Answers |
|---|---|---|
| System overview | `system` | What is this subsystem, independent of the change? Component cards, not a graph. Subject to the artifact-independence test |
| Data flow | `dataflow` | How do state, events, requests, and rendered output move through the changed system? |
| Code dependencies | `deps` | Which changed components depend on which? Where are the seams, the entry points, the leaves? |
| User actions | `actions` | What does the user do, what surface do they touch, and how does that reach the implementation? |
| Sequence | `sequence` | In what order do the participants talk to each other, for one concrete scenario? |

Include the views the size tier allows, in this order, skipping the rest.

Each view carries a **guided tour**: numbered steps that highlight one node at a time with a caption. The tour is what makes a map teach rather than decorate. Budget the steps per the tier table. The template adds the previous and next controls, zoom, pan and fit-to-view.

Label edges with example data, not type names. `user_42 → {plan: "pro"}` teaches; `User → Plan` does not.

**`maps.json` shape.** `{"views": [...]}`, one entry per included view, each with `key` (from the table above), `label`, `kind`, `tour`, and an optional `note`. With `--all-maps`, put the "the tier would normally omit this" note in `note`.

| `kind` | Use for | Content | Tour step |
|---|---|---|---|
| `cards` | `system` (component cards, not a graph) | `html`: the cards, each tagged `data-node="<id>"`; the template styles `.cards` and `.card` | `{"caption", "highlight": [ids]}` |
| `graph` | `dataflow`, `deps`, `actions` | `elements`: Cytoscape nodes and edges. Node `data.type` of `"changed"` or `"new"` colours it. `rankDir` `"LR"` for flows and dependencies, `"TB"` for sequential action flows | `{"caption", "highlight": [node or edge ids]}` |
| `sequence` | `sequence` | `mermaid`: `sequenceDiagram` source. Cytoscape cannot draw lifelines | `{"caption", "scrollTo": "<text of one message or note>"}` |

Dagre parks a node with no edges far from the rest. Connect each isolated node to its nearest logical neighbour with an edge carrying `"classes": "phantom"`, which the template draws invisible.

### Part 3 — Change summary

Two things, in order:

1. **Change inventory** — a table of every file still shown, one row each: path, what it does, why it changed. Link each path to its anchor in the PR's Files-changed tab when a PR URL is known.
2. **Sequence diagrams** — Mermaid `sequenceDiagram` blocks for the interactions the change touches: API calls, event flows, async work. One diagram per scenario, and a one-line caption above each saying which scenario it traces. If the change touches no interaction between participants, say so in one line and omit the diagrams rather than inventing one.

### Part 4 — Diff review

The template builds this part from the diff and `rationales.json`: a file sidebar (grouped by type, or as a tree), a split-pane diff per file, the rationale on each card, reviewed tracking and per-file notes that survive a reload, a Copy notes button that exports the notes as Markdown, a list of the files left out, keyboard navigation, and base and head pills. Your inputs are the rationales and the `--base` and `--head` values. Give `--head` the branch name when the head is a branch, so the pill is readable.

Reviewed state persists in the browser under `qexplain-diff-<slug>`, where `<slug>` is the artifact's file name stem lowercased with underscores turned into hyphens. The key follows the file name, so renaming the file starts a fresh review.

### Format rules

These cover the content you write. The template already meets them for the page itself.

- **No extra libraries.** The template loads pinned UMD builds of Mermaid, Cytoscape.js, dagre and cytoscape-dagre from `cdn.jsdelivr.net`. If a page ever needs another, pin an exact version from `cdn.jsdelivr.net`, `unpkg.com` or `cdnjs.cloudflare.com`, and use the UMD build: `<script type="module">` is blocked on a `file://` origin. The validator fails an unpinned URL or a module script.
- **The artifact's own data is inlined.** No `fetch` or XHR in your fragments; they fail on a `file://` origin.
- **Links out are fine.** Anchor each changed-file row and code excerpt to its diff when a PR URL is known.
- **No ASCII diagrams.** Everything visual is Cytoscape.js, Mermaid, or styled HTML.
- **No emoji in what you write.** The check does not read the diff, which shows the repo's own text as it is, so never leave a file out because of one.
- **Mermaid notes**: use `Note right of X`, not `Note over X,Y` — a spanning note is as wide as the span whatever its text. Reserve `Note over X,Y` for intentional full-width section headers. `<br/>` does not work in note text; split a long note into separate `Note right of` lines. Never use `#10;`, which renders as a literal space. The template resizes note boxes to their text after every render.
- **Code blocks use `<pre>`.** Wide content (tables, large figures) goes in a `<div class="table-wrap">` so it scrolls inside itself, not the page.
- **Callouts** (`<div class="callout">`) for definitions, key concepts, and edge cases that would otherwise interrupt the flow.
- **Prose** follows `shared/AGENTS.md § Style & Output`, written for a cold reader with no session context. Define an unavoidable technical term the first time, then use the project's own term for it, never a synonym. Give the example before the rule it illustrates.

## Step 4: Validate the artifact

The build script ends by running the static validator; you can re-run it alone:

```
<python> <config-repo>/shared/skills/qexplain/scripts/validate-explanation.py <path-to-html>
```

Standard library only — nothing to install in the venv. It emits one `PASS`/`FAIL` line per check and exits non-zero if any check failed. The eleven checks, where `verified-section` needs the heading in the Narrative part with text after it: `document-shape`, `title-present`, `remote-assets-pinned`, `no-module-scripts`, `no-runtime-fetch`, `code-whitespace`, `anchors-resolve`, `tabs-wired`, `parts-wired`, `verified-section`, `no-emoji`.

**A FAIL is a blocker.** Fix the content and rebuild until the suite is clean. Do not report the artifact as ready on a failing run, and do not describe a failed check as a caveat — repair it.

**Then check it in a browser.** The validator cannot see whether a graph drew, a diagram parsed, or a tour step highlights anything:

```
node <config-repo>/shared/skills/qexplain/scripts/visual-check.js <path-to-html> --out <screenshot dir>
```

It exercises every map, tour step, part and diff-review control, prints one `OK`/`BAD` line per check, and saves screenshots. **Look at the screenshots** — a page can pass every check and still read badly. A `BAD` line or a visible defect is a blocker, the same as a validator FAIL. Without Node and Playwright, run the checklist in the script's header comment through a Playwright MCP instead.

Building needs Python 3. Without it the artifact cannot be built: stop and tell the user rather than writing the page by hand.

Only when no browser can be run at all, report the artifact as **statically validated but not visually confirmed**, and say which checks were skipped.

## Step 5: Run the quiz in chat

The quiz is a conversation, not a page. Do not put it in the HTML file. Its posture is drawn from Matt Pocock's `/teach`; say so in one line when you start, so the reader knows this part has a different lineage from the artifact.

Give the user the path, ask them to read it, and wait. When they say they are done, run the number of questions the size tier sets.

Question design:
- Medium difficulty. A reader who understood the change answers correctly; a reader who skimmed does not. No trick questions, no trivia about names or line numbers.
- Cover different ground: the background, the intuition, the code, and one on consequences ("what breaks if X").
- Four options each.
- **Every option is the same length** — the same word count, and the same character count as near as you can manage. Length is the classic tell: the longest, most hedged option reads as correct. Equal options force the reader to use the content.
- Never signal the answer through formatting, ordering, or specificity. Wrong options must be plausible to someone who half-understood.

Ask **one question at a time and wait for the answer.** Never post all questions at once. Never reveal the answer in the question.

### Teaching posture

- On a correct answer: confirm it, then add one sentence the reader did not already have — why it is correct, or where the idea shows up elsewhere.
- On a wrong answer: do not give the answer. Give one hint pointing at the artifact section that covers it, and invite one more try. If the second try is also wrong, give the answer and explain why the chosen option was tempting and why it fails.
- On a vague or hedged answer: ask them to commit to an option before you respond.
- If two or more misses cluster on the same concept, stop the quiz. Re-teach that concept in chat with a fresh example. Offer to amend the relevant artifact section, and amend it if they accept — then rebuild and re-run Step 4.
- Stay in the teacher's chair throughout. No score-keeping tone.

If the user asks to skip the quiz, skip it and go to Step 6.

## Step 6: Close

Two things, in order.

**A short recap in chat**: what the change does, in two or three sentences, plus a plain note on which concepts were shaky in the quiz and worth a second look. If you spotted a likely defect while reading in Step 1, this is where the one-line note and the `/qreview` pointer go.

**The delete question.** Ask it directly, name the path, and wait:

> "Keep `<path>`, or delete it now that you have read it?"

- **Delete** — remove the file and confirm it is gone. If the directory you created in Step 2 is now empty, remove it too.
- **Keep** — say the file is untracked and uncommitted, and leave it exactly as it is. This is the fallback if the answer is unclear or the user does not respond; say that you are keeping it.

Do not assume either way. Do not delete without being told to.

