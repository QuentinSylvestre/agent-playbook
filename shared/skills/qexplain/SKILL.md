---
name: qexplain
description: Write a self-contained HTML brief of a code change for a human reviewer. A brief (intent, context, changes, verified, open items) is always there; walkthrough, maps (D2 or Mermaid diagrams with guided tours), a file inventory and an interactive diff review are optional parts. Use to understand or review a diff, branch, PR or commit range of any size, then optionally quiz the reader in chat. Not for judging the change (use /qreview). Manual invocation only.
argument-hint: "<PR number, branch, commit range, path, or several label=repo::range pairs> [--all-maps]"
disable-model-invocation: true
---

# Explain

## Your role

You are writing for a person who has to understand a change, and often has to review it. The page serves comprehension and review. At the end the reader can explain the change to someone else without the page in front of them, and knows what to check before it ships.

**Your first action is to resolve the target and run the measuring script, before reading any changed file** (Step 1). Do not start writing from the diff alone.

**The banned habit is summarising the diff in chat.** A file-by-file recap tells the reader what moved, not why the change makes sense.

**Do not evaluate.** No findings, no severity, no verdict, no suggestions for improvement. Facts a reviewer needs are in scope: the decisions taken and why, precedent in the codebase, deploy impact, open items, and what evidence exists. If you notice a real defect while reading, note it in one line at the end of the chat and route the user to `/qreview`. Do not fold it into the page.

**Do not put secrets in the artifact.** The diff is copied into the page, context lines included, and the page may be stored or shared.

**Do not edit source code.** This skill writes exactly one file in the working tree: the artifact. Intermediate content files go in a temporary directory outside the repository.

**The artifact is a local file the reader opens from disk.** Do not publish it as a hosted page, and do not apply another skill's page conventions (artifact-design, diagramming): this skill's template and validator define the page.

**Run it in a fresh context that did not write the code**, when you can. A writer of the change explains what it meant to do; a fresh reader explains what the code does. Say so to the user if the session is the one that wrote the change.

**When NOT to use this skill**:
- To judge whether a change is correct or well-built, use `/qreview`.
- To check whether a change works at runtime, use `/qqa`.
- To hand execution state to another session, use `/qhandoff`.
- To understand the codebase rather than a specific change, use `/qexplore`.

**Isolation**: manual-invocation only. `disable-model-invocation: true` enforces this on Claude Code. Other providers ignore that field, so the rule also stands in prose: no other skill calls this one, it calls no other skill, and it is never invoked automatically at the end of a phase, a plan, or a review.

**Maintenance**: when you edit this skill, run its three self-tests with the interpreter from Step 1: `scripts/measure-change.py --selftest`, `scripts/build-explanation.py --selftest` and `scripts/validate-explanation.py --selftest`. They are not part of `/qconfig-sync`. The build self-test prints how many D2 cases ran, or "skipped (d2 not found)": a skip is not a pass. `scripts/visual-check.js` has no self-test.

## What to explain

$ARGUMENTS

| Argument form | Resolution |
|---|---|
| Empty | The pending diff on the current branch against its merge base |
| A number (`482`) | That PR: fetch its head and diff against its base |
| A branch name | That branch against its merge base with the default branch |
| A commit range (`abc123..def456`) or a single SHA | That range, or that commit against its parent |
| A path | The pending diff, restricted to that path |
| Several `<label>=<repo>::<range>` pairs | One artifact over those repos; each file's path starts with its label |

`--all-maps` overrides the tier's map selection (Step 2) and includes every map view. If the form is ambiguous, ask which the user meant. If the resolved diff is empty, say so and stop.

## Step 1: Measure, then read

**Measure first, and read nothing yet.** `<python>` is the interpreter of `<config-repo>/.venv-agent-playbook` with `-I` (`<config-repo>` and the interpreter path: `shared/AGENTS.md § Config Repo Locations`), the playbook's one interpreter. If it is missing or fails to start, stop and tell the user "venv missing: run setup.ps1 or setup.sh"; never use a Python from `PATH`.

```
<python> <config-repo>/shared/skills/qexplain/scripts/measure-change.py --repo <dir> --diff-args "<git diff arguments>" [--exclude <glob>]...
```

For several repos, replace `--repo` and `--diff-args` with one `--target "<label>=<repo>::<git diff arguments>"` per repo. For a fetched PR diff, use `--diff-file <unified diff>`. The script prints paths, counts and setting names, never file content. Act on its lines in this order, and re-measure after any change to the excludes:

1. **`FILE` and `LEFT-OUT`: keep secrets out of your context and the artifact.** The script leaves out common secret-bearing names, files it cannot parse, and binary patches. Check every `FILE` path and add `--exclude` for any file that project governance, memory, or the user says not to read in full, and any configuration file that may hold live credentials. A `WARN` means an exclude matched nothing: fix it, because the build refuses it. Never read a left-out file or its diff. To explain its change, use its `SETTING` lines, which name the settings without their values (printed for left-out files only), or ask the user.
2. **`CREDENTIAL`: a flagged file counts as left out until you resolve it.** Never read the flagged line; when you read that file, read around it. For a test or fixture file, or any file the reader needs, pass the match to the build as `--mask-credential <path>:<side>:<line>`, labelled path included: the page shows the line with its value hidden, and you say so in the verified section. For a configuration file, exclude it. If the line says `made-up-test-value=yes`, pass that match to the build as `--allow-credential <path>:<side>:<line>`, labelled path included; the build refuses it for any other match. That mark is a guess from the value's length and wording, so if the plan or the code suggests the value is real, mask it instead. Tell the user about every masked match that is not marked made up: a credential committed to a test file is theirs to judge. Only the user can show such a value on the page, by saying it is not a live credential, and then you pass `--user-confirmed-credential` with the same form. Never copy a credential value into anything you write. The scan is a safety net with known gaps, such as values holding spaces, key bodies with no header in the hunk and passwords holding `@`, so it does not replace step 1.
3. **`HEAVY`: warn, do not split.** The page will be long (over 2500 lines to read, or more than one plan). Tell the user so in the Step 2 gate. The page stays one page: do not propose separate runs. Sub-tabs per subsystem keep it navigable.
4. **`SUBSYSTEMS` and `D2`.** `SUBSYSTEMS <n> <names>` counts production areas (repo label plus the first one or two directory levels; tests, docs and generated files excluded). `D2 <version>` or `D2 not found` decides how you draw: write D2 when it is found, Mermaid when it is not. Never write one diagram in both.
5. **`PLAN`: read the plan.** Find the project file under the project-file root of the repo the line names (`shared/skills/qdream/memory-rules.md § Resolution contract`), in `<root>/` or `<root>/done/`. An archived name has a different date prefix, so match on the name after the first underscore. Read its Intent, Design Decisions, Implementation Divergences, Review Log, verification results and Follow-up Work. Treat them as the author's account: they give the reasons, the code gives the facts, and where they differ the code wins and you say so in chat. `PLAN-SKIPPED`, or no project file: carry on without one.

Next read the diff of every file still shown, then the code around it. At minimum:
- Every changed production file still shown, in full, not just the hunks.
- Every changed test and fixture's test names or record shapes, and in full the tests that pin the behaviour you explain, skipping any line a `CREDENTIAL` entry names.
- The callers and callees of every changed function or component, and the data structures it reads or writes, at their definition.
- Any test that exercises the changed behaviour, old or new.
- The owners of any state the change moves through: what writes it, what reads it, what it is serialised into.
- Precedent: where the codebase already does the same thing, and the commit or plan that introduced it.
- Deploy impact: migrations, settings, scripts to re-run, other repos or hosts affected.

Stop reading when you can answer without guessing: what did the system do before and why was that a problem; what does it do now and what one idea makes it work; what would break if the change were reverted. If you cannot answer all three, keep reading. If neither the code nor the plan can settle them, ask the user before writing. A confidently wrong background is worse than no artifact.

As you read each file still shown, record a one-sentence rationale (why it changed) and a one-sentence role (what the file does). They become `rationales.json` and `roles.json`.

## Step 2: Size the change, choose the parts and the path

Take the tier from the `TIER` line: lines to read, outside tests, fixtures and generated files. It scales depth inside the parts. Go one tier up when the change spans more subsystems than its line count suggests. When unclear, use the lower tier.

| Tier | Lines to read | Maps | Nodes per map | Tour steps | Quiz questions |
|---|---|---|---|---|---|
| Tiny | Under 75 | System overview only | 2-3 | 1-2 | 3 |
| Small | 75-249 | System overview, plus the one other most relevant | 3-4 | 2-4 | 4 |
| Medium | 250-800 | Three maps | 4-7 | 3-5 | 5 |
| Large | Over 800 | All five | 5-12 | 4-8 | 5 |

**Anti-inflation rule.** Do not inflate a small change to fill the page. If two nodes teach the same fact, merge them. If a map duplicates another, omit it. A sparse page that respects the reader beats a padded one. With `--all-maps`, include every map and mark each one the tier would omit with a short note; keep the tier's node and step budgets.

### The gate: parts and path, asked together

One question to the user, with a recommendation and a one-line reason for each pre-selected part:

| Change | Pre-selected parts |
|---|---|
| Tiny | Brief, Diff |
| Small | Brief, Diff |
| Medium, or 2+ subsystems | Brief, Maps, Diff |
| Large, or 2+ repos | Brief, Walkthrough, Maps, Change summary, Diff |

The Brief is always in. Diff review is always pre-selected. State the `HEAVY` warning here if it fired. Offer the other parts as additions, not as recommendations the table does not make. Then propose the path.

**Artifact path.** Pick the directory by the first rule that matches:
1. The project resolves to a workspace store for the *project files* artifact class per `shared/skills/qdream/memory-rules.md § Resolution contract`: `<store>/explanations/`.
2. A `plans/` directory exists at the repo root: `plans/explanations/`.
3. A `docs/` directory exists at the repo root: `docs/explanations/`.
4. Otherwise `explanations/` at the repo root.

Name the file `YYMMDD_<SLUG>_EXPLANATION.html`, where `YYMMDD` is today's date from the clock and `<SLUG>` is a short upper-snake description (for example `260814_TOKEN_REFRESH_EXPLANATION.html`).

State the path, the tier and why, and whether git ignores the path (`git -C <the repo holding the path> check-ignore -q <path>`, after creating the directory if new): "This path is git-ignored, so the file will not show up in `git status`." or "This path is **not** git-ignored, so the file will appear as untracked in `git status`." Do not modify `.gitignore`, stage or commit the file. Wait for the answer. If the user names a different path, use it as given.

## Step 3: Write the content

You write content files in a temporary directory outside the repository. The template supplies the page, and the build emits only the parts chosen.

| File | Part | Contains |
|---|---|---|
| `brief.html` | Brief (always) | The brief fragment, below |
| `walkthrough.html` | Walkthrough | Deep background, intuition, code walkthrough |
| `maps.json` | Maps | The views and their tours |
| `diagrams/<name>.d2` or `.mmd` | any | One diagram per file |
| `rationales.json` | Diff, Summary | `{"<path as in the diff>": "<one sentence>"}` for every file still shown |
| `roles.json` | Summary | Same shape: what each file does (optional) |

Build with the `<python>` from Step 1:

```
<python> <config-repo>/shared/skills/qexplain/scripts/build-explanation.py --out <path> --title "<title>" \
  --repo <dir> --diff-args "<the git diff arguments that resolve the target>" \
  --parts brief,walkthrough,maps,summary,diff --brief <dir>/brief.html --walkthrough <dir>/walkthrough.html \
  --maps <dir>/maps.json --diagrams <dir>/diagrams --rationales <dir>/rationales.json --roles <dir>/roles.json \
  [--ticket <text>]... [--link <label>=<url>]... [--exclude <glob>]... [--mask-credential <path>:<side>:<line>]... [--allow-credential <path>:<side>:<line>]... [--user-confirmed-credential <path>:<side>:<line>]...
```

Leave out the flags of parts not chosen (`--parts` defaults to `brief,diff`). For a PR diff fetched another way, pass `--diff-file <unified diff> --base <text> --head <text>` instead of `--diff-args`; `--base` and `--head` are accepted only there. `--link` refuses a URL with a login or a signature or token in its query. For several repos pass one `--target` per repo, key the JSON files by the labelled paths, and pass the same `--exclude` values you measured with. The scripts accept only revisions, paths, `--cached`, `--merge-base` and `-U<n>` in those arguments; a value starting with a dash needs the `=` form. The build reads branch, base and head SHAs, commit counts and plan slugs from git for the provenance strip. Pass `--ticket` and `--link` for ticket ids and links you know. It prints "not recorded" for the rest.

The build captures the diff as UTF-8, removes excluded files, renders the diagrams, inlines the data safely, warns about any file without a rationale or role, and runs the Step 4 validator. Fix every warning. It stops with nothing written if it finds credential-shaped text in the diff or in any file you wrote, diagram sources, tickets and links included; reword your own text, it cannot be allowed.

### The Brief

One fragment, one scrolling page. Heading ids are fixed and the validator checks them, in this order:

| id | Required | Content |
|---|---|---|
| `intent` | yes | Why the change exists, in a few sentences, from the ticket, plan or commit messages |
| `context` | yes | The mechanism the change touches and its state just before. End on the problem. A diagram goes here when it shows a structure |
| `change-<name>` | yes, one or more | What changed. Group the sections by subsystem when there are several (`SUBSYSTEMS` line). Order them so each builds on the previous: entry point first, then what it calls. Never git order or alphabetical |
| `decisions` | optional | Choices made and why, with the alternative rejected, when the plan or code records them |
| `precedent` | optional | Where the codebase already does this, and where this differs |
| `deploy` | optional | Migrations, settings, re-runs, other hosts or repos affected |
| `surface` | optional | A table of the externally visible surface: name, kind, default, new or changed. Written by you while reading; there is no extractor |
| `verified` | yes | Facts only: what ran and where, what did not run among the environments and paths the plan or code names, where each fact comes from (a test name, a plan section, a command you ran), "not recorded" when no source says. Name a review that ran without restating its findings. List files left out and what you could not explain because of them. No judgement of whether that is enough |
| `open-items` | yes | Two lists, "Before production" and "Backlog". When nothing is open, one line: "No open items recorded" |

Use `<h2 id="...">` headings. Other heading ids are refused. Keep the brief short: a reviewer reads it in minutes. Use toy data (three records, two users) to show old and new behaviour.

### The Walkthrough

For a reader new to the area. Open with a line saying a familiar reader can skip ahead. Two levels: deep background (the domain and machinery the change sits on) and the code walkthrough (grouped, ordered, short excerpts, mechanical churn skipped in one line). For several subsystems, wrap each in `<section data-subsystem="Name">...</section>`: the build makes one sub-tab each.

**Artifact-independence test.** The deep background and the Maps `system` view must make sense with the change closed, as if pasted into the project's documentation. No "this change", "this PR" or "before and after" phrasing there, and no links into the diff. Deltas belong in the Brief, the code walkthrough and the other maps. The `system` view's highlight comes from classes; the page has a Show changes switch that turns it off.

### Diagrams

Put `<div data-diagram="name"></div>` in the brief or walkthrough where a diagram goes; in `maps.json` the view's `"diagram"` field names it. The build resolves `name` against `<name>.d2` or `<name>.mmd` in `--diagrams`.

| Kind | D2 found | No D2 |
|---|---|---|
| Architecture, pipeline, data flow, state machine | D2 | Mermaid `flowchart` or `stateDiagram-v2` |
| Sequence | D2 with `shape: sequence_diagram` | Mermaid `sequenceDiagram` |
| Timeline | Mermaid `gantt` | same |

**D2 rules.** The build prepends the class set and renders four variants (sketch or classic, light or dark) with ELK, so you write structure and classes only:
- Classes: `new`, `changed`, `existing`, `removed`, `decision`, `step`, `question`, `container` on shapes; `new-edge`, `changed-edge`, `removed-edge` on connections. Write `class: new`, never a colour: colours do not follow the dark theme.
- No `icon:`, no `link:`, no `layers:`, `scenarios:` or `steps:`, no `d2-config`, and no `@` import of any form, quoted or not (so keep `@` out of labels too). The build refuses them and names the construct.
- A system view marks change with `new`, `changed` and `removed`; the Show changes switch turns those off and hides `removed` shapes.
- Name ids neutrally (`auth_cache`, not `token_store`): an id that holds a word like token, secret, key or password, followed by a colon and a quoted value, reads as a credential and stops the build. The wording belongs in the label.
- Label connections with example data, not type names.
- A sequence diagram is written in D2 only when D2 is found.

**Mermaid rules.** Avoid the reserved word `end` as a class name. For change marking in a flowchart use `classDef` names `new`, `changed`, `removed`; the Show changes switch reads them. In sequence diagrams use `Note right of X`, not `Note over X,Y` (a spanning note is as wide as the span whatever its text), no `<br/>` in note text (split a long note into separate `Note right of` lines), and never `#10;`, which renders as a literal space. Mermaid is pinned at 11.17.2 and redrawn when the theme toggles. Do not draw the same diagram in both D2 and Mermaid. Diagrams use a wider band than the prose, capped in height, and open full window on click, so size them for reading.

### Maps

A view answers one question; do not merge views. Include the views the tier allows, in this order:

| View | Key | Answers |
|---|---|---|
| System overview | `system` | What is this subsystem, independent of the change? Subject to the artifact-independence test |
| Data flow | `dataflow` | How do state, events, requests and output move through the changed system? |
| Code dependencies | `deps` | Which changed components depend on which? |
| User actions | `actions` | What does the user do, and how does that reach the implementation? |
| Sequence | `sequence` | In what order do the participants talk, for one concrete scenario? |

`maps.json`: `{"views": [{"key", "label", "diagram", "note"?, "subsystem"?, "tour"?}]}`. Each tour step is `{"caption", "highlight": [ids]}`. Views sharing a `subsystem` value share a sub-tab; use that for Large changes. With `--all-maps`, put the "the tier would normally omit this" note in `note`.

Tour ids for D2 are D2 object ids: `site.mistap` for a node, `(site.bl -> gw.http)[0]` for a connection (`site.(a -> b)[0]` when both ends sit in container `site`). The build checks them against the rendered diagram and fails on an unknown id, listing the valid ones. Connections between two highlighted nodes stay lit. For Mermaid flowcharts the ids are node ids; for a Mermaid sequence they are text fragments of a participant, message or note. A step dims everything else, outlines its elements and keeps containers visible. Budget the steps by tier.

### Change summary and Diff review

The build generates both from `rationales.json`, `roles.json` and the diff; you write nothing else. The summary is a file inventory grouped by subsystem, each row linking to the file's card in Diff review. Diff review keeps its sidebar, split-pane diff, rationale per file, reviewed tracking and notes (stored under `qexplain-diff-<slug>`, `<slug>` being the file name stem lowercased with underscores turned to hyphens, so renaming the file starts a fresh review), Copy notes, left-out list, keyboard navigation and base and head pills.

The page also keeps the theme (`qexplain-theme`) and the sketch or classic style (`qexplain-sketch`) across visits.

### Format rules

- **No extra libraries.** The template loads one pinned UMD build of Mermaid from `cdn.jsdelivr.net`, only when a Mermaid diagram is used. D2 needs no library. Another library needs an exact version from `cdn.jsdelivr.net`, `unpkg.com` or `cdnjs.cloudflare.com`, UMD build: `<script type="module">` is blocked on `file://`. The validator fails an unpinned URL or a module script.
- **The artifact's own data is inlined.** No `fetch` or XHR in your fragments.
- **No ASCII diagrams.** Everything visual is D2, Mermaid or styled HTML.
- **No emoji** in what you write. The check does not read the diff, so never leave a file out because of one.
- **Code blocks use `<pre>`.** Wide content goes in `<div class="table-wrap">`. Callouts use `<div class="callout">`.
- **Prose** follows `shared/AGENTS.md § Style & Output`, written for a cold reader. Define a technical term at first use, then use the project's own term. Give the example before the rule.

## Step 4: Validate

The build runs the validator; you can re-run it alone:

```
<python> <config-repo>/shared/skills/qexplain/scripts/validate-explanation.py <path-to-html>
```

Twelve checks, each looking only at the parts present: `document-shape`, `title-present`, `remote-assets-pinned`, `no-module-scripts`, `no-runtime-fetch`, `code-whitespace`, `anchors-resolve` (also fails on duplicate ids), `no-active-links` (no `javascript:` URL, no remote image-like resource), `tabs-wired`, `parts-wired`, `brief-sections`, `no-emoji`. **A FAIL is a blocker.** Repair the content and rebuild. Do not report the artifact as ready on a failing run, and do not call a failed check a caveat.

**Then check it in a browser.** The validator cannot see whether a diagram drew or a tour step lights anything:

```
node <config-repo>/shared/skills/qexplain/scripts/visual-check.js <path-to-html> --out <screenshot dir>
```

It checks only the parts present: provenance, Mermaid, D2 variants, every tour step, sub-tabs, the sketch and Show changes switches, theme redraw, the summary link, every diff-review control, phone width. **Look at the screenshots.** A `BAD` line or a visible defect is a blocker. Without Node and Playwright, run the checklist in the script's header by hand through a browser tool. Only when no browser can run at all, report the artifact as **statically validated but not visually confirmed** and name the checks skipped. Building needs Python 3; without it, stop and tell the user rather than writing the page by hand.

## Step 5: Offer the quiz

Give the user the path and offer a quiz in chat; the user decides. The quiz never goes into the page. If accepted, say in one line its posture comes from Matt Pocock's `/teach`, wait until the reader has read the page, then ask the number of questions the tier sets.

- Medium difficulty: a reader who understood the change answers correctly, a skimmer does not. No trick questions, no trivia about names or line numbers.
- Cover different ground: background, the idea, the code, and one on consequences ("what breaks if X").
- Four options each, **every option the same length** in words and as near as you can in characters, with no signal through formatting, order or specificity. Wrong options are plausible to a half-reader.
- **One question at a time, waiting for the answer.** Never post all questions at once. Never reveal the answer in the question.

On a correct answer, confirm and add one sentence the reader did not have. On a wrong answer, do not give the answer: give one hint pointing at the page section and invite one more try; after a second miss give the answer and say why the chosen option tempted and fails. On a hedged answer, ask them to commit first. Two misses on one concept: stop, re-teach it with a fresh example, offer to amend that section, and if accepted amend, rebuild and re-run Step 4. Stay in the teacher's chair throughout: no score-keeping tone.

## Step 6: Close

**A short recap in chat**: what the change does in two or three sentences, and which concepts were shaky in the quiz, if one ran. If you spotted a likely defect in Step 1, the one-line note and the `/qreview` pointer go here.

**The delete question.** Ask it directly, name the path, and wait:

> "Keep `<path>`, or delete it now that you have read it?"

- **Delete**: remove the file and confirm it is gone. If the directory you created in Step 2 is now empty, remove it too.
- **Keep**: say the file is untracked and uncommitted, and leave it. This is also the fallback if the answer is unclear or missing; say you are keeping it.

Do not assume either way, and do not delete without being told to.

## Optional: install D2

D2 draws the diagrams. Without it, the skill writes Mermaid. Install: `winget install Terrastruct.D2`, `brew install d2`, or https://d2lang.com. The scripts find `d2` on `PATH` or from the `QEXPLAIN_D2` environment variable (a full path to the executable).
