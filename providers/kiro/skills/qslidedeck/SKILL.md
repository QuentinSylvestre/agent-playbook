---
name: qslidedeck
description: Build a polished, self-contained HTML slide deck (16:9, keyboard navigation, prints to PDF) for a talk, pitch, briefing or knowledge exchange, with scripted checks for empty space, overlapping text and brand fidelity. Use when the user wants slides, a deck, a presentation, infographics or a visual artifact to present or screen-share.
argument-hint: "<what the talk is about, audience, length, where to save>"
---

# /qslidedeck — presentation-grade HTML slide decks

**First action:** read this whole file, then start at Step 1. Do not write HTML from scratch: every slide starts from a pattern file and every deck is assembled by `build.py`.

The bar is "a designer made this"; tidy is not enough. Decks fail in four ways, most frequent first: **empty space** (cards stretched tall with a title at the top and nothing below; layouts that stop halfway down), **text dressed as visuals** (a card of prose with an icon is not a diagram), **collisions** (arrows through labels, boxes over text), and **content drift** (claims, numbers or scope the user never gave).

**When NOT to use:** a single chart or interactive visual (use `/qvisualize`); a `.pptx`, `.docx` or `.pdf` file the user must edit (use the document skills); a page that must live inside an app.

Paths: `<skill>` is this skill's folder (`~/.kiro/skills/qslidedeck`). `<python>` is the playbook venv's interpreter with `-I`: `<config-repo>/.venv-agent-playbook/Scripts/python.exe -I` on Windows, `<config-repo>/.venv-agent-playbook/bin/python -I` elsewhere (`<config-repo>` is the `root=` line of `~/.agent-playbook/config`). The scripts need Google Chrome and nothing else.

## Process

1. **Gather.** Read the sources the user named. Find the brand: a brand or graphic chart (`*charte*`, `*brand*`, `*guideline*`, `*graphique*`, a PDF beside logo files), the logo, and a symbol-only icon file. Colours and fonts come from the chart; without one, from the logo file. Never take brand colours from an application's CSS: product UIs carry status colours that are not the brand. **The chart outranks the logo file**: copy its web/hex values exactly into `theme.css`, with a comment naming the chart page. The chart's font goes first in `--font` even if not installed.
2. **Ask, once, in one message** (at most 7 questions, each with your recommendation; skip what the user already said):
   - what may be shown outside the company, and what may not;
   - how mature each thing is (in production / ramping up / experimental / planned);
   - outcomes and numbers the user can claim (say: "I will put no number on a slide that you have not given me");
   - presenter name and role;
   - where the brand chart is, if you did not find one (name what you found instead);
   - light or dark.
3. **Storyline and claims.** Propose, in one message:
   - the slide list: one idea per slide, written as the headline it will carry, each with its pattern. For a talk of N minutes, plan about N/2.5 slides. Every topic the user listed appears on a slide;
   - a **claims table**: every system, team, practice or outcome the slides will name, its maturity label, and its source, quoting the user's words where they gave them (`| System model | In production | user: "used for most multi-component work" |`). Use the user's maturity and scope words exactly ("a small group" stays "a small group"); an item without a stated maturity gets no chip; anything you inferred is marked `inferred`.
   - a **brand table**: each colour and font you will use, its exact value, and where you read it (`| Main blue | #... | chart p.3 web column |`). Open the chart's colour page to fill it; never write "chart" as the source of a value you read from the logo file.
   Get a yes on all three before building. The claims table is the only list of claims the slides may make.
4. **Style check.** Build the title slide and the most important content slide; run build and shoot; both must pass; look at both screenshots. Show the user the two paths, then **end your turn**. Build nothing else until the user answers, even if the storyline was approved.
5. **Build the rest**, one slide file per tool call (kiro-cli rejects one huge tool argument), each copied from its pattern.
6. **Verify** (see Verification) until `shoot.py` prints `RESULT: PASS` and you have looked at every screenshot.
7. **Hand over**: the deck path; how to present (arrows, F for full screen, Ctrl+P for a PDF); and two tables, built by re-reading every slide file and the `LIST:` lines from `build.py`, never from memory:
   - every slide phrase that is not in the approved claims table or the user's own words, quoting the slide text;
   - every `LIST:` sentence, one row each, with the matching claims-table scope beside it and `same` or `wider`. A blanket "none widen the scope" is not a review. Fix each `wider` row before handing over.

## Deck folder and scripts

Create the deck folder where the user asked:

```
deck.json         {"title": "...", "output": "<name>.html", "forbid": ["<internal names>"]}
theme.css         brand tokens on :root (below) + only the styles your deck adds
slides/01-title.html, 02-....html   one <section class="slide p-..."> per file
assets/           logo.svg or .png (wordmark), mark.svg or .png (symbol only); reference as asset:logo.svg
icons.svg         optional; default <skill>/assets/icons.svg: i-reset i-eye i-flag i-map i-db i-check
                  i-target i-user i-users i-code i-rocket i-scale i-doc i-git i-compass i-list
                  i-archive i-moon i-bot i-shield i-arrow i-down i-box i-layers
```

- `<python> <skill>/scripts/build.py <deck>` assembles one self-contained HTML file (shell + `<skill>/assets/base.css` + your theme + icons + slides, assets inlined). **FAIL** on an external URL (no web fonts or CDN: the deck must work offline during a live call) and on any `forbid` term. **WARN** when `forbid` is empty. **LIST** prints every slide sentence with an absolute scope word (all, every, always, never...); those are where scope drifts.
- `<python> <skill>/scripts/shoot.py <deck> [slide numbers]` screenshots each slide at 1600x900 and checks it:
  - **empty space** (all but the title): interior holes (hollow cards, empty lanes) and edge bands (the layout stops short of the bottom or a side);
  - **collisions**: `line-on-text`, `text-overlap`, `text-covered`, `text-overflow`, `box-overlap`, printed with coordinates and the text involved;
  - **title mark**: the brand mark must be centred in its rings.
  A failing slide gets `slideNN.issues.png` with every problem boxed (red hole, orange band, magenta collision). It ends with `RESULT: PASS` or `FAIL`, and checks the PDF has one page per slide.
- The shell (`<skill>/assets/shell.html`) owns the canvas, scaling, navigation, print and the checks. Never reimplement or edit it, `base.css` or the scripts.

**theme.css tokens** (all required): neutrals `--ink --slate --muted --grey --line --paper --canvas --wash`; `--accent` (main brand colour, dark enough for white text), `--accent-2`, `--accent-3` (lighter steps), `--accent-soft`, `--accent-pale` (tints); `--font`; `--shadow`; `--logo: url("asset:logo.svg")`; `--mark: url("asset:mark.svg")`. Example: `<skill>/assets/patterns/theme.css`. For the mark, prefer the brand's own symbol/icon file. If you must crop it from a wordmark SVG, set the `viewBox` to the symbol's exact bounds; `shoot.py` fails an off-centre mark.

## Patterns

`<skill>/assets/patterns/` is a working deck: copy it to a scratch folder, build and shoot it, and look at the screenshots. Every slide there passes every check. **Start every slide by copying its pattern file**; change the words, the number of items and the icons; keep the structure and class names. Rename SVG marker ids (`p4fa`...) if you use a pattern twice.

| File | Pattern | Use for |
|---|---|---|
| 01-title | title | the opening slide (a closing slide uses a content pattern, never the title one) |
| 02-columns | problem to answer, 3-4 columns | the starting problem and your answers |
| 03-stack | layered bands + side loop | layers, levels, an operating model; maturity chips |
| 04-pipeline | banner + chevrons + fan-out + "used for" cards | a staged process that spreads to several targets |
| 05-cycle | 4 nodes on a ring + fact cards | a repeating process around one artefact |
| 06-flow | 5 stages with arrows + principle strip | a hand-off chain, checks in sequence |
| 07-funnel | shrinking blocks + background band | many inputs refined into few outputs |
| 08-lanes | vertical role lanes | roles acting in turn, a decision process |
| 09-org | two box-and-arrow diagrams | before / now, how something spreads |
| 10-tiles | 2x2 large-icon tiles | outcomes, results |
| 11-quotes | 4 quote cards | lessons, principles |

If no pattern fits, adapt the closest one and keep its sizing. Never make a card taller than its content; never push content to a card's edges with `justify-content: space-between` or `margin-top: auto`. Use a pattern at most twice in a deck, and only when its shape fits the idea: replace every placeholder role with something that means something (a row of five identical "Session" pills means nothing).

## Design rules

- **One idea, one diagram.** Kicker (2-4 words), a headline stating the point (at most 10 words), one diagram. A grid of prose cards is not a diagram.
- **Words.** About 40 words per content slide outside diagram labels. Short phrases; no paragraphs; no semicolon chains.
- **Brand.** Colours only through the tokens. One accent family plus neutrals. Green, red and amber only where they mean pass, fail, against or warning. The logo as given, never redrawn. Light theme unless asked.
- **Maturity chips** exactly as in the approved claims table: `.chip.prod` (in production), `.chip.ramp` (ramping up), `.chip.lab` (experimental), `.planned` (planned).
- **Collisions are fixed by moving or resizing.** A line may pass under a small label that has its own background (a pill, a tag). Never fix a collision by giving a large block an opaque background over a line: that cuts the diagram visibly while passing the check.
- **Empty space is fixed by resizing or re-centring the diagram.** Never add an element just to fill a region: every box on a slide is connected to the diagram and says something the talk needs.

## Content rules

- **No invented numbers.** Every number, percentage, duration ("weeks", "days") and ratio comes from the user or the sources. Without one, show the idea without numbers.
- **Only claims in the approved claims table, at the scope the user gave.** Headlines included: a punchy headline never widens "a small group" to "all teams". Do not add specifics the user never stated (who owns something, how it is installed, how often it runs, what loads automatically) to make a slide feel complete.
- **Confidentiality.** Put every internal product, repository, host and customer name found in the sources into `forbid`, even unused ones. Describe internal systems by what they do and why, never by their structure: no file formats, tool names, folder names, command names or schema names.
- Dates come from the real clock.

## Verification

1. `build.py`: `RESULT: PASS`, no WARN left unaddressed, every `LIST:` sentence checked against the claims table (fix the slide when the scope differs).
2. `shoot.py <deck>`: `RESULT: PASS`. Your own reading of a screenshot never overrides a FAIL.
3. Open every `slideNN.png` and check what the scripts cannot: each slide has a diagram, the hierarchy reads at a glance, nothing is masked by an opaque block, every claim is in the claims table.
4. Re-shoot only the slides you changed (`shoot.py <deck> 4 7`), then one final full run before handover.
