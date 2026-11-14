# PowerPoint (.pptx) — Procedural Reference

## Quick Reference

| Operation | Tool / Approach | Notes |
|-----------|----------------|-------|
| **Read** content | markitdown, thumbnail.py, raw XML via unpack.py | markitdown extracts text per slide |
| **Edit** existing | unpack → XML manipulation → clean → pack | Template-based; preserves styles/masters |
| **Create** from scratch | pptxgenjs (Node.js) | **CREATE-ONLY** — cannot open/edit existing .pptx |

> **Routing rule**: pptxgenjs is CREATE-ONLY. To modify an existing .pptx, always use the unpack/XML/pack pipeline. Never attempt to load an existing file with pptxgenjs.

## Reading Content

### Text extraction with markitdown

```bash
markitdown presentation.pptx > content.md
```

Returns slide-by-slide text content in markdown format. Good for content review, not layout.

### Thumbnail generation

```bash
python scripts/pptx/thumbnail.py presentation.pptx --output grid.png
```

Produces a visual grid of all slides. Requires LibreOffice + Pillow.

### Slide images for a document (Windows, PowerPoint)

```bash
python scripts/pptx/export_slide_images.py deck.pptx out/ --slides 12,13,20-25   # cropped to screenshots and callouts
python scripts/pptx/export_slide_images.py deck.pptx out/ --slides 5 --full --hide Caption   # whole slide
```

Text placeholders and master graphics are left out and each image is cropped to the remaining
shapes, so a screenshot-per-slide deck becomes document-ready images. The deck is opened read-only.
It refuses to run while PowerPoint is already running (exit 4): automation would join the user's
PowerPoint and could close their open presentations. Ask the user to close PowerPoint, or pass
`--allow-running` only with their agreement; the script then closes only its own copy and never quits.
Use it when converting a deck into a Word guide (docx.md, "Converting a slide deck into a Word guide").

### Raw XML access

```bash
python scripts/office/unpack.py presentation.pptx unpacked/
```

Then inspect `unpacked/ppt/slides/slide*.xml` for full structural detail.

## Editing Existing Presentations

When the task involves a currently open PowerPoint application — rather than a closed file — additionally read `pptx-com.md` (co-located) before proceeding.

### Workflow: analyze → unpack → build → edit → clean → pack

1. **Analyze** — read with markitdown to understand current content and structure
2. **Unpack** — `python scripts/office/unpack.py template.pptx work/`
3. **Build** — if adding slides, use `python scripts/pptx/add_slide.py work/ --duplicate <n>` or `--layout <name>`
4. **Edit** — modify XML files in `work/ppt/slides/slide*.xml`
5. **Clean** — `python scripts/pptx/clean.py work/` to remove orphaned files
6. **Pack** — `python scripts/office/pack.py work/ output.pptx`

### XML editing tips

- Slide content lives in `<p:sp>` (shape) elements containing `<p:txBody>` (text body)
- Each paragraph is `<a:p>`, each run is `<a:r>` with `<a:rPr>` for formatting
- Images are referenced via relationships in `slide*.xml.rels` pointing to `../media/`
- Slide dimensions are in EMU (English Metric Units): 1 inch = 914400 EMU

### Adding images to existing slides

1. Copy image file to `work/ppt/media/`
2. Add relationship entry in the slide's `.rels` file
3. Add `<p:pic>` element in the slide XML referencing the relationship ID

## Creating from Scratch (pptxgenjs)

> **pptxgenjs is CREATE-ONLY.** It generates new .pptx files from code. It cannot open, read, or modify existing presentations. For editing, use the unpack/XML/pack pipeline above.

### Setup

```javascript
const pptxgen = require("pptxgenjs");
const pptx = new pptxgen();

// Set presentation-level properties
pptx.layout = "LAYOUT_WIDE";  // 13.33 x 7.5 inches
pptx.author = "Author Name";
pptx.title = "Presentation Title";

// Full HD layout (1440×810 pt = 20×11.25 in) — use when the target is a Full HD display
// (common in COM/python-pptx environments; also available in pptxgenjs 3.12.0+ via defineLayout):
// pptx.defineLayout({ name: 'FullHD', width: 20, height: 11.25 });
// pptx.layout = 'FullHD';
```

### Adding slides with text

```javascript
const slide = pptx.addSlide();

// Title
slide.addText("Slide Title", {
  x: 0.5, y: 0.3, w: "90%", h: 1.0,
  fontSize: 32, bold: true, color: "363636",
  fontFace: "Segoe UI"
});

// Body text with multiple paragraphs
slide.addText([
  { text: "First point", options: { bullet: true, breakLine: true } },
  { text: "Second point", options: { bullet: true, breakLine: true } },
  { text: "Sub-point", options: { bullet: true, indentLevel: 1 } }
], { x: 0.5, y: 1.5, w: "90%", h: 5.0, fontSize: 18, color: "4a4a4a" });

// Full HD equivalents (×1.5 scale): fontSize: 48 title, fontSize: 27 body
```

### Lists and bullets

```javascript
slide.addText([
  { text: "Item A", options: { bullet: true, breakLine: true } },
  { text: "Item B", options: { bullet: true, breakLine: true } },
  { text: "Sub-item", options: { bullet: true, indentLevel: 1, breakLine: true } },
  { text: "Item C", options: { bullet: true } }
], { x: 0.5, y: 1.5, w: "90%", h: 5.0, fontSize: 18, valign: "top" });
```

### Shapes and backgrounds

```javascript
// Solid background
slide.background = { color: "1a1a2e" };

// Gradient background
slide.background = { color: "1a1a2e",
  // Note: use fill property for gradients on shapes, not backgrounds
};

// Rectangle shape
slide.addShape(pptx.shapes.RECTANGLE, {
  x: 0.5, y: 2.0, w: 4.0, h: 3.0,
  fill: { color: "e94560" },
  shadow: { type: "outer", blur: 6, offset: 3, color: "000000", opacity: 0.3 }
});
```

### Images

```javascript
// From file path
slide.addImage({ path: "./image.png", x: 1, y: 1, w: 4, h: 3 });

// From base64
slide.addImage({ data: "data:image/png;base64,...", x: 1, y: 1, w: 4, h: 3 });

// Sizing to fit (maintain aspect ratio manually)
slide.addImage({ path: "./photo.jpg", x: 0.5, y: 1.5, w: 5, h: 3.75 });
```

### Tables

```javascript
const rows = [
  [
    { text: "Header 1", options: { bold: true, fill: { color: "2d3436" }, color: "ffffff" } },
    { text: "Header 2", options: { bold: true, fill: { color: "2d3436" }, color: "ffffff" } }
  ],
  [{ text: "Row 1 Col 1" }, { text: "Row 1 Col 2" }],
  [{ text: "Row 2 Col 1" }, { text: "Row 2 Col 2" }]
];

slide.addTable(rows, {
  x: 0.5, y: 1.5, w: "90%",
  border: { type: "solid", pt: 1, color: "cccccc" },
  fontSize: 14,
  colW: [3, 3]
});
```

### Charts

```javascript
const chartData = [
  { name: "Series 1", labels: ["Q1", "Q2", "Q3", "Q4"], values: [10, 20, 30, 40] },
  { name: "Series 2", labels: ["Q1", "Q2", "Q3", "Q4"], values: [15, 25, 35, 45] }
];

slide.addChart(pptx.charts.BAR, chartData, {
  x: 0.5, y: 1.5, w: "90%", h: 5.0,
  showTitle: true, title: "Quarterly Results",
  showValue: true,
  catAxisLabelFontSize: 12,
  valAxisLabelFontSize: 12
});
```

### Saving

```javascript
pptx.writeFile({ fileName: "output.pptx" })
  .then(() => console.log("Created output.pptx"))
  .catch(err => { console.error(err); process.exit(1); });
```

## Common Pitfalls

1. **No `#` in hex colors** — use `"e94560"` not `"#e94560"`. The `#` causes silent color failures.
2. **No Unicode bullet characters** — use `bullet: true` option, never `"\u2022"` or `"•"` in text. Unicode bullets render as boxes on many systems.
3. **Use `breakLine: true`** — to separate items in a text array. Without it, all items render on the same line.
4. **Option object reuse** — create fresh option objects for each text item. Reusing the same object reference causes mutations across items.
5. **Shadow corruption** — complex shadow objects on many elements can corrupt the file. Use sparingly and test output.
6. **Coordinate system** — x/y/w/h are in inches (not pixels, not EMU). `w: "90%"` is relative to slide width.
7. **Font availability** — fonts must be installed on the rendering machine. Use widely-available fonts (Segoe UI, Arial, Calibri) or embed fonts.
8. **Large images** — pptxgenjs does not compress images. Pre-compress to keep file size reasonable.
9. **Text overflow** — text exceeding the shape boundary is hidden, not wrapped to a new shape. Set adequate height or use `autoFit: true`.

## Font Embedding Guidance

For portable presentations that render correctly on any machine:

1. Prefer system fonts (Segoe UI on Windows, Arial as universal fallback)
2. When using custom fonts, embed them:
   - After creating, open in LibreOffice → File → Properties → Font tab → check "Embed fonts in the document"
   - Or via XML: set `<p:embeddedFont>` entries in `presentation.xml`
3. Subset embedding reduces file size (only characters used are embedded)

## Macro-Enabled .pptm Handling

- `.pptm` files contain VBA macros in `ppt/vbaProject.bin`
- `pack.py` automatically preserves `vbaProject.bin` and its content-type entry
- When unpacking/repacking, never delete the `vbaProject.bin` file from the extracted directory
- Content type `application/vnd.ms-office.vbaProject` must remain in `[Content_Types].xml`

## Converting to Images

For QA verification or thumbnail generation:

```bash
# Convert to PDF first, then to images
python scripts/office/soffice.py --convert-to pdf presentation.pptx --outdir ./tmp
# Then use pdftoppm (poppler) or Pillow to split pages
pdftoppm -png ./tmp/presentation.pdf ./tmp/slide
```

Or use `thumbnail.py` for a ready-made grid.

## Mandatory Creation and QA Process

**Every pptx creation task MUST include this verification loop.** Do not skip it.

### Phase 0: Content planning (before authoring begins)

Before writing or generating any slides:

1. Read `pptx-design.md` (co-located with this skill file) in full — note the anti-patterns to avoid and the design directions appropriate for the subject.
2. Plan the slide structure: list slide titles, identify the layout pattern for each slide, and decide where data visualizations replace bullet lists.
3. Confirm you are not reproducing any of the anti-patterns listed in `pptx-design.md § Anti-Patterns`.
4. **Define the audience** before the first slide — one line per field: who (role and expertise level), goal (what they should decide or do after the talk), setting (live room / video call / read alone — "read alone" requires fuller notes since the slides must carry more), accessibility needs, and tolerance for density and motion. Every downstream choice — word budget, font floor, amount of motion — follows from these.
5. **Plan speaker notes per slide** — write notes before visible slide text. Structure every slide's notes in two parts:
   - **Spoken script**: 2–5 natural sentences the presenter actually says, point first, each figure with its source in the sentence. Write for the ear: no bullet fragments, no label-only lines.
   - **Presenter reference** (after a `---` divider, brief): `assumptions` (anything you added that the brief does not state, labelled "Assumed (confirm before presenting):"), `sources`, anticipated Q&A answers.
   Notes are where all depth lives; the slide carries only the claim.
6. **For 4+ slides sharing a design grammar**, build the opener and one representative detail slide first, render and review both with the user, then batch the rest. Iterating slide 1 of 6 is cheap; rebuilding all six after the grammar turns out wrong is not.

### Phase 1: Content QA (text/data correctness)

```bash
markitdown output.pptx > content_check.md
```

Review the extracted text for:
- Missing or duplicated content
- Incorrect ordering of slides
- Spelling/data errors
- AI writing failure modes: awkward/unnatural phrasing, excessive/flowery wording, vague/empty assertions, unnecessary filler, illogical conclusions (see `docx.md § AI writing failure modes` for the full definitions)
- Slide titles that are labels, not claims — a title of 1–2 words with no verb is almost always a label ("Decisions", "Q3 Results"). A claim title makes an assertion the audience can agree or disagree with ("East leads Q1, up 8 %"). Quick test: can the audience say "I agree" or "I disagree"? If not, it is a label.
- Bullet-heavy slides with more than 5 bullets — flag for redesign (rule: `pptx-design.md § Cognitive load limits` and Anti-Patterns #9)
- Summary slides that also carry a chart — flag as duplicate charting (rule: `pptx-design.md § Data Display`)
- Derived figures that were computed by hand — totals, percentages, averages, and changes must come from source numbers; cross-check any figure adjacent to words like "total", "up X %", or "average"
- Facts beyond the brief — any figure, target, timeline or rate not in the brief belongs in the notes' assumptions section, labelled "Assumed (confirm before presenting):"; never assert it on the slide as fact
- Missing or skeleton speaker notes — every slide (including cover and close) gets notes; a slide whose notes contain no spoken script (fewer than two full sentences) is incomplete
- Success targets that are not measurable — targets must state a number, percent, date, or named comparison ("below 30 %", "≥ 95 % of Q4 level", "by 30 June"); flag vague targets like "Clearly lower" or "No drop" for revision

### Phase 2: Visual QA (layout/design correctness)

1. **Render to images**:
   ```bash
   python scripts/pptx/thumbnail.py output.pptx --output qa_grid.png
   ```
   Or for individual slides:
   ```bash
   python scripts/office/soffice.py --convert-to pdf output.pptx --outdir ./qa
   pdftoppm -png ./qa/output.pdf ./qa/slide
   ```

2. **Visual inspection** — examine the rendered images for:
   - Text overflow or clipping
   - Misaligned elements
   - Color contrast issues
   - Missing images or broken references
   - Inconsistent spacing between slides
   - Font rendering problems

3. **Fix and re-verify** — if issues are found:
   - Fix the generation code
   - Regenerate the .pptx
   - Re-render and re-inspect
   - Repeat until all issues are resolved

### Phase 3: Final validation

```bash
python scripts/office/validate.py output.pptx
```

Confirms OOXML structural integrity (relationships, content types, required files).

### QA Loop Rules

- **Tool success is not evidence** — a script that exits 0 only means the file was written; it cannot see text overflow, squashed charts, or font fallback. The rendered image is the verification. Always LOOK at the render before calling anything done.
- **Never ship without visual inspection** — code-level review cannot catch layout bugs
- **Minimum one full loop** — even if content QA passes, visual QA must run
- **Fix-forward only** — once an issue is found, fix it and re-verify the entire output (not just the fix)
- **Document failures** — if QA reveals a pptxgenjs limitation, note it in the response to the user

## Dependencies

| Tool | Purpose | Install |
|------|---------|---------|
| Node.js + npm | pptxgenjs creation | https://nodejs.org/ |
| pptxgenjs | .pptx generation | `npm install` in skill dir (package.json) |
| LibreOffice | Rendering, PDF conversion | `choco install libreoffice-fresh` / `brew install --cask libreoffice` / `apt install libreoffice` |
| poppler (pdftoppm) | PDF to images | `choco install poppler` / `brew install poppler` / `apt install poppler-utils` |
| markitdown | Text extraction | `pip install markitdown` |
| Pillow | Thumbnail grid | `pip install Pillow` |
| Python 3.8+ | Scripts | Pre-installed or https://python.org/ |
