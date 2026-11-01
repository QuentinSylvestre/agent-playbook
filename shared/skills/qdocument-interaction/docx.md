# DOCX Format Reference

A .docx file is a ZIP archive containing XML files following the Office Open XML (OOXML) specification. The primary content lives in `word/document.xml`.

## Quick-Reference Routing

| Operation | Tool | Notes |
|-----------|------|-------|
| **Create** new document | Node.js `docx` library | CREATE-ONLY — cannot open/edit existing files |
| **Read** content | `pandoc` or `unpack.py` → read XML | pandoc for text; unpack for structure |
| **Edit** existing document | `unpack.py` → edit XML → `pack.py` | Method for modifying existing .docx without Word |
| **Edit with tracked changes** (Word installed, Windows) | `scripts/docx/word_com.py` (Word COM via `pywin32`) | Word writes the revision markup; check with `verify_docx.py`, deliver with `safe_replace.py`; see "Editing through Word (COM)" |
| **Edit a screenshot already in a document** | `scripts/docx/docx_media.py swap` | Replaces the embedded image bytes, size and position unchanged |
| **Insert a section** (headings, steps, bullets, pictures, links) before or after a heading, no Word needed | `scripts/docx/docx_insert.py` | JSON spec in, new file out; steps restart at 1; see "Inserting a section without Word" |
| **Accept tracked changes** | `scripts/docx/accept_changes.py` | Uses LibreOffice macro |
| **Add comments** | `scripts/docx/comment.py` | Operates on unpacked XML |
| **Reply to comments, @mention people** | `WordSession.reply` + `scripts/docx/docx_mentions.py` | Emails from the document's `people.xml`, never guessed; see "Comment replies and @mentions" |
| **Screenshots for a procedure** | `scripts/office/annotate_screenshot.py` | Numbered boxes, blur, crop, grid; see "Screenshots for a procedure" |
| **Slide deck → Word guide** | `scripts/pptx/export_slide_images.py` + `word_com.py` | See "Converting a slide deck into a Word guide" |
| **Convert to images** | LibreOffice → pdftoppm | Via soffice.py |

**Critical**: The `docx` npm library is CREATE-ONLY. It cannot open or parse existing .docx files. To edit an existing document, you MUST use the unpack → XML edit → pack pipeline.

## Content and Delivery Standards

### AI writing failure modes

Avoid these patterns in every document you produce.

- **Awkward or unnatural phrasing** — text that reads as machine-generated: stiff sentence construction, unidiomatic word order, or phrases a fluent human writer would never produce. Rewrite from scratch rather than paraphrasing the same structure.
- **Excessive or flowery wording** — language that inflates without adding meaning: ornamental adjectives, redundant intensifiers ("very unique", "absolutely essential"), overwrought metaphors, over-decorated phrasing. Cut to the simplest phrasing that carries the meaning.
- **Vague or empty wording** — assertions without content: "this is an important step", "there are several considerations", "it is crucial to note". Replace with the specific fact, number, or reason.
- **Unnecessary wording** — padding that delays the point: canned preambles ("In this section, we will discuss…"), filler phrases ("it is worth noting that"), ornamental transitions ("having said that", "with that in mind"). Delete the filler; start with the substance.
- **Illogical wording** — conclusions that do not follow from their premises, or explanations that contradict earlier statements. Trace the inferential chain before writing it: state the premises, then the conclusions that follow from them. When a conclusion doesn’t follow, rewrite the supporting argument first, or remove the conclusion.

### Render-before-ship gate

No DOCX is satisfactory until rendered to page images via LibreOffice headless and every page visually inspected. Text-parser checks and XML validation do not substitute — they prove the file is well-formed, not that it looks correct.

```bash
# Via the skill's soffice.py wrapper:
python scripts/office/soffice.py --convert-to png output.docx --outdir ./qa_pages/
```

On defect (clipped text, broken table, missing image, overflowing content): fix the source, re-render immediately, and re-inspect all pages before continuing. A fix that is not re-rendered is not verified.

### Table intentionality rules

Use a table only when the content genuinely requires tabular structure:
- Comparing items across the same set of attributes
- Presenting numeric or metric data where column alignment aids reading
- A compact matrix (options × criteria, features × platforms)
- A repeated set of records with a consistent schema (release history, field reference)

For anything else — process steps with explanations, grouped notes, content with uneven depth — use prose under descriptive headings.

**Visual constraints** (the default house style; the user's house-style memory topic, if any, overrides it):
- Borders: explicit gray (`#D9D9D9`); no borderless tables in body copy
- Header fill: light gray, dark gray, dark blue, or light blue — never a gradient
- Text color: white on dark fills; black on light fills
- Row heights: no fixed heights; allow text wrap
- Padding: generous internal cell padding (minimum 4pt top/bottom, 6pt left/right)
- Vertical alignment: center

### Callout box ban

Never use shaded note cards, accent-bar blocks, text boxes with filled borders, or boxed summaries — regardless of how they are constructed (direct shape, styled paragraph, table cell, content control).

The callout box ban applies to tables used as containers for a single note or summary — a table whose purpose is visual emphasis rather than data organization. Standard data tables with header fills per the Table intentionality rules above are unaffected.

Present the content as a plain paragraph. Use a bold lead-in phrase if the note needs visual weight: **Note:** followed by the text on the same line.

### Author voice discipline

Write in the author's voice. "I" and "we" refer to the human author, not to the agent producing the document.

- Never invent experience or credentials ("In my ten years working with…").
- Never invent commitments ("We will follow up by Friday").
- Never invent facts the author did not provide.
- Match the author-to-recipient tone and relationship — a memo to a direct report differs from a board report.

When the author's position on a point is unknown, leave a `[TODO: author to complete]` placeholder rather than filling in plausible content.

### Document density

Avoid unbroken walls of text unless the document type explicitly requires it (e.g., a legal agreement). Visual anchors — section headings, tables, whitespace between paragraphs — reduce cognitive load and help readers locate specific content on re-read.

Apply spacing discipline: a blank paragraph between sections, consistent indent depth, tables or lists where four or more items follow the same structure.

### Heading vagueness

A heading like "Overview", "Introduction", or "Background" cannot be improved by word substitution alone. Before finalizing any heading, ask: what specific subject or finding does this section address? A heading that names the subject is more useful than one that names the genre (“Authentication Overview” → “How the session token lifecycle works” is a mid-level improvement; “Overview” → “Session tokens expire after 30 minutes of inactivity” is the full transformation the rule targets).

Reframe the heading before polishing its wording.

### Style hierarchy

Control document appearance through paragraph styles (Heading 1, Heading 2, Heading 3, Normal, Caption), never through direct formatting that duplicates what a named style already controls.

- Never apply a bold font directly to a Heading paragraph — Heading styles are already bold; direct formatting creates drift when styles are updated.
- Never apply a font size or color to Normal paragraphs as a substitute for creating a named style.
- For one-off emphasis within a paragraph, direct formatting (bold, italic) is appropriate.

## Reading Content

### With pandoc (text extraction)

```bash
pandoc input.docx -t plain -o output.txt       # plain text
pandoc input.docx -t markdown -o output.md      # markdown with formatting
pandoc input.docx -t json                       # AST for programmatic access
```

### With unpack.py (structural access)

```bash
python scripts/office/unpack.py document.docx ./unpacked/
# XML files are pretty-printed in ./unpacked/word/
```

Key files after unpacking:
- `word/document.xml` — main body content
- `word/styles.xml` — style definitions
- `word/numbering.xml` — list definitions
- `word/_rels/document.xml.rels` — relationship targets (images, headers, etc.)
- `word/comments.xml` — comments (if any)
- `word/header1.xml`, `word/footer1.xml` — headers/footers

## Creating New Documents (docx library, Node.js)

### Setup

```bash
cd <skill-dir>
npm install   # installs docx from package.json
```

### Basic document structure

```javascript
const { Document, Packer, Paragraph, TextRun, HeadingLevel,
        AlignmentType, PageBreak, Table, TableRow, TableCell,
        WidthType, ImageRun, ExternalHyperlink, Footer, Header,
        PageNumber, TabStopPosition, TabStopType, SectionType,
        LevelFormat } = require("docx");
const fs = require("fs");

const doc = new Document({
    sections: [{
        properties: {
            page: {
                size: { width: 12240, height: 15840 },  // Letter (twips)
                margin: { top: 1440, bottom: 1440, left: 1440, right: 1440 }
            }
        },
        children: [
            new Paragraph({
                heading: HeadingLevel.HEADING_1,
                children: [new TextRun({ text: "Title", bold: true })]
            }),
            new Paragraph({
                children: [new TextRun("Body text here.")]
            })
        ]
    }]
});

Packer.toBuffer(doc).then(buf => fs.writeFileSync("output.docx", buf));
```

### Page sizes (in twips, 1 inch = 1440 twips)

| Size | Width | Height |
|------|-------|--------|
| Letter | 12240 | 15840 |
| A4 | 11906 | 16838 |
| Legal | 12240 | 20160 |

### Styles and text runs

```javascript
new TextRun({ text: "Bold", bold: true })
new TextRun({ text: "Italic", italics: true })
new TextRun({ text: "Colored", color: "FF0000" })  // no # prefix
new TextRun({ text: "Sized", size: 24 })            // half-points (24 = 12pt)
new TextRun({ text: "Superscript", superScript: true })
new TextRun({ text: "Subscript", subScript: true })
```

### Lists

```javascript
const doc = new Document({
    numbering: {
        config: [{
            reference: "my-bullets",
            levels: [{
                level: 0,
                format: LevelFormat.BULLET,
                text: "\u2022",   // use Unicode bullet
                alignment: AlignmentType.LEFT,
                style: { paragraph: { indent: { left: 720, hanging: 360 } } }
            }]
        }]
    },
    sections: [{
        children: [
            new Paragraph({
                numbering: { reference: "my-bullets", level: 0 },
                children: [new TextRun("First item")]
            })
        ]
    }]
});
```

### Tables

```javascript
new Table({
    width: { size: 100, type: WidthType.PERCENTAGE },
    rows: [
        new TableRow({
            children: [
                new TableCell({
                    width: { size: 50, type: WidthType.PERCENTAGE },
                    children: [new Paragraph({ children: [new TextRun("Cell 1")] })]
                }),
                new TableCell({
                    width: { size: 50, type: WidthType.PERCENTAGE },
                    children: [new Paragraph({ children: [new TextRun("Cell 2")] })]
                })
            ]
        })
    ]
})
```

### Images

```javascript
new Paragraph({
    children: [
        new ImageRun({
            data: fs.readFileSync("image.png"),
            transformation: { width: 600, height: 400 }  // pixels
        })
    ]
})
```

### Page breaks

```javascript
new Paragraph({ children: [new PageBreak()] })
```

### Hyperlinks

```javascript
new ExternalHyperlink({
    children: [new TextRun({ text: "Click here", style: "Hyperlink" })],
    link: "https://example.com"
})
```

### Headers and footers

```javascript
sections: [{
    properties: {},
    headers: {
        default: new Header({
            children: [new Paragraph({ children: [new TextRun("Header text")] })]
        })
    },
    footers: {
        default: new Footer({
            children: [new Paragraph({
                alignment: AlignmentType.CENTER,
                children: [
                    new TextRun("Page "),
                    new TextRun({ children: [PageNumber.CURRENT] })
                ]
            })]
        })
    },
    children: [/* ... */]
}]
```

### Tab stops

```javascript
new Paragraph({
    tabStops: [
        { type: TabStopType.RIGHT, position: TabStopPosition.MAX }
    ],
    children: [
        new TextRun("Left text"),
        new TextRun({ children: ["\t"] }),
        new TextRun("Right-aligned text")
    ]
})
```

### Multi-column layouts

```javascript
sections: [{
    properties: {
        column: { count: 2, space: 720 }  // 2 columns, 0.5" gap
    },
    children: [/* ... */]
}]
```

### Table of Contents

```javascript
// TOC field — requires Word/LibreOffice to update page numbers
new Paragraph({
    children: [
        new TextRun({ text: "" }),  // placeholder
    ],
    // Use XML injection for TOC field
})
// Alternative: use raw XML in the unpack/pack pipeline for TOC
```

Note: docx-js TOC support requires declaring the TOC field; page numbers are only resolved when the document is opened in Word or LibreOffice and the TOC is updated.

### Footnotes

```javascript
const { FootnoteReferenceRun } = require("docx");

const doc = new Document({
    footnotes: {
        1: { children: [new Paragraph({ children: [new TextRun("Footnote text")] })] }
    },
    sections: [{
        children: [
            new Paragraph({
                children: [
                    new TextRun("Text with footnote"),
                    new FootnoteReferenceRun(1)
                ]
            })
        ]
    }]
});
```

## Critical Rules for docx-js

1. **No newlines in TextRun** — `\n` does NOT create line breaks. Use separate Paragraph objects, or use `new TextRun({ break: 1 })` for a soft line break within a paragraph.

2. **No Unicode bullet characters in numbering** — use `\u2022` in the `text` field of bullet configs (level format). Do NOT use Windows-specific bullet symbols.

3. **Page size defaults to Letter** — always explicitly set page size to avoid platform-dependent defaults.

4. **Table widths require BOTH table-level and cell-level** — set `width` on the Table AND on each TableCell. Omitting either produces unpredictable layout.

5. **Color values have no # prefix** — use `"FF0000"` not `"#FF0000"`.

6. **Size is in half-points** — `size: 24` means 12pt font. Common mistake: setting `size: 12` for 12pt (actually renders as 6pt).

7. **Image dimensions** — `transformation` values are in pixels. Use reasonable values (e.g., width: 600 for a ~6-inch-wide image at 100 DPI).

8. **Packer is async** — always `await Packer.toBuffer(doc)` or use `.then()`.

## Editing Existing Documents

Without Word, the only way to edit an existing .docx is the unpack → XML → pack pipeline. When Word
is installed (Windows) and the user wants tracked changes, prefer driving Word through COM: hand-written
revision markup (`w:ins`, `w:del`, `w:delText`, `w:delInstrText`, deleted paragraph marks, moved
bookmarks) is where most "unreadable content" failures come from. See "Editing through Word (COM)".

### Workflow

```bash
# 1. Unpack
python scripts/office/unpack.py input.docx ./work/

# 2. Edit XML files in ./work/word/
# (manual or scripted XML manipulation)

# 3. Validate
python scripts/office/validate.py ./work/

# 4. Repack
python scripts/office/pack.py ./work/ output.docx

# 5. Confirm Word opens it (see "Verify with Word, not with an XML parser")
```

`validate.py` checks the package only (content types, relationships, well-formed XML). It does not
check WordprocessingML rules, so a file that passes it can still fail in Word.

### Common XML edits

**Replace text**: Find `<w:t>` elements in `word/document.xml`:
```xml
<w:r>
  <w:rPr><w:b/></w:rPr>
  <w:t>Original text</w:t>
</w:r>
```

**Add a paragraph**: Insert a `<w:p>` element:
```xml
<w:p>
  <w:r>
    <w:t>New paragraph text</w:t>
  </w:r>
</w:p>
```

**Modify styles**: Edit `word/styles.xml` to change fonts, sizes, colors globally.

**Restart a numbered list** for a new procedure that reuses an existing list's look: add a `w:num`
to `word/numbering.xml` that points to the same `abstractNumId` and restarts at 1, and use its new
`numId` in the new paragraphs. Insert it before `w:numIdMacAtCleanup` when that element exists.
```xml
<w:num w:numId="29"><w:abstractNumId w:val="15"/>
  <w:lvlOverride w:ilvl="0"><w:startOverride w:val="1"/></w:lvlOverride></w:num>
```
Take the `abstractNumId` from the `w:num` of an existing list of the format you want (decimal or
bullet), not from a guess.

**Refresh the table of contents and cross-references on open** after adding headings: put
`<w:updateFields w:val="true"/>` in `word/settings.xml` before `w:hdrShapeDefaults` (before
`w:footnotePr` when that element is absent). Word then asks the user whether to update fields;
tell them to click Yes. Do not use this flag on a copy you render through Word for checking: strip
it first, or Word waits on the prompt.

## Critical Pitfalls When Editing Existing .docx Files

### `pack.py` was corrupting namespace prefixes — now fixed

The previous `pack.py` re-serialized every XML file through `ET.parse` + `ET.tostring`, silently
rewriting `w:`, `mc:`, `r:` etc. prefixes to `ns0:`, `ns1:`, `ns2:` etc. Word refused to open
the result with "unreadable content". This was fixed in the script: XML files are now written as
raw bytes with no re-serialization. `unpack.py` was not affected (it uses `xml.dom.minidom`, which
preserves namespace prefixes correctly).

**Do not re-introduce any `ET.tostring` call for existing XML files in either script.**

### Safe pattern for programmatic edits to an existing .docx

Never route an existing document's XML through `ElementTree`. Instead, read `document.xml` as raw
text from the original zip, apply changes as string/regex operations, and write back to a new zip
copying all other files byte-for-byte:

```python
with zipfile.ZipFile(ORIG) as z:
    doc = z.read('word/document.xml').decode('utf-8')
    all_entries = {n: z.read(n) for n in z.namelist()}

# ... apply changes to doc as string / regex operations ...

with zipfile.ZipFile(OUT, 'w', zipfile.ZIP_DEFLATED) as zout:
    for name, data in all_entries.items():
        zout.writestr(name, doc.encode('utf-8') if name == 'word/document.xml' else data)
```

### `w14:paraId` is optional — omit it on inserted paragraphs

`w14:paraId` and `w14:textId` are optional; Word assigns them on the next save. Stripping them
from 20 paragraphs of a document Word already opened did not stop Word opening it (tested
2026-09-28 via the COM check below). The simplest correct choice is to omit both on paragraphs you
insert. If you do set them, each `paraId` must be unique in the part and below `0x80000000` (MS-DOCX
constraint). Never generate them with `random.randint(1, 0xFFFFFFFE)` — half the values are out of
range.

### Deleted fields need `w:delInstrText`, not `w:instrText`

Inside a `<w:del>`, every text-bearing element must use its deleted form: `<w:t>` becomes
`<w:delText>` and `<w:instrText>` becomes `<w:delInstrText>`. Converting only `<w:t>` leaves a
well-formed file that Word rejects with "Word found unreadable content". This bites when a tracked
deletion covers a field, such as a `REF _Ref… \n \h` cross-reference or a hyperlink field. Converting
one `w:instrText` inside a deleted `REF` field was the whole fix for a setup guide that had failed
in Word across ten diagnostic variants (2026-09-28).

Lint before packing:

```python
dels = re.findall(r'<w:del\s[^>]*[^/]>.*?</w:del>', doc, flags=re.S)
assert not any(re.search(r'<w:(?:t|instrText)[\s>]', d) for d in dels), 'w:t/w:instrText inside w:del'
outside = re.sub(r'<w:del\s[^>]*[^/]>.*?</w:del>', '', doc, flags=re.S)
assert not re.search(r'<w:del(?:Text|InstrText)[\s>]', outside), 'delText/delInstrText outside w:del'
```

### Regex run-boundary matching

Patterns like `<w:rPr>[\s\S]*?</w:rPr>` can backtrack across `</w:r>` boundaries when a
`<w:drawing>` element follows the rPr. The regex silently matches content spanning two different
runs (or more), producing malformed XML. Use explicit `str.find('<w:r')` +
`str.find('</w:r>')` to bound each run, then apply regex only within that substring.

### Tracked-change nesting guard

`<w:del>` directly inside `<w:ins>` (or vice versa) is invalid OOXML. Before wrapping a run in
tracked-change markup, verify the run is not already inside an open tracked-change element:

```python
before = xml[:run_start]
if (before.count('<w:del ') - before.count('</w:del>')) > 0 or \
   (before.count('<w:ins ') - before.count('</w:ins>')) > 0:
    continue  # skip — wrapping here would create invalid nesting
```

Cross-reference fields (`REF \n \h`) cache their section title as display-text runs with `<w:t>`
elements. If you run a term replacement over the whole document before processing stub paragraphs
that contain those fields, the cached display runs get wrapped in del/ins, and a subsequent
`del_run_content` pass on the stub paragraph then creates nested del/ins inside the existing ins.
The guard above prevents this.

## `rfind('<w:p')` matches `<w:pPr>` and `<w:pStyle>` — use `<w:p[ >]`

When searching for genuine paragraph opening tags via string operations, `rfind('<w:p')` or
`str.find('<w:p')` also matches `<w:pPr>`, `<w:pStyle>`, `<w:pPrChange>`, etc. — all of which
are nested *inside* existing paragraphs. Inserting content before such a match puts a `<w:p>`
element inside a paragraph's property block: well-formed XML, invalid OOXML. Word refuses to
open the file with "experienced an error" (no recovery offered).

Use a regex that requires the character after `<w:p` to be a space or `>`:

```python
# Wrong — matches <w:pPr>, <w:pStyle>, …
p_start = xml.rfind('<w:p', 0, pos)

# Correct — only genuine paragraph openings
candidates = [m.start() for m in re.finditer(r'<w:p[ >]', xml[:pos])]
p_start = candidates[-1] if candidates else -1
```

## Inserting a section without Word

`scripts/docx/docx_insert.py <in.docx> <spec.json> <out.docx>` adds a block (heading, paragraphs,
numbered steps, bullets, hyperlinks, centred PNG pictures) before or after one Heading paragraph.
The spec names the anchor heading by its full text, a numbered paragraph to copy the step list
format from (`step_like`), and optionally a bullet paragraph (`bullet_like`). Steps use a new list
with the same format that restarts at 1, so existing lists keep their numbers. `update_fields`
adds the flag described under "Common XML edits". The docstring of the script has the full spec.

Check the result the usual way: `scripts/office/validate.py out.docx`, then render a copy through
Word (or LibreOffice) and look at the pages; deliver with `safe_replace.py`. Put the spec in a file
(paths and quotes in a shell heredoc get mangled on Windows). Use `word_com.py` instead when the
document has tracked changes you must add to, or fields and bookmarks that must be repaired.

## Verify with Word, not with an XML parser

`ET.fromstring` succeeding only proves the XML is well-formed. Every failure listed above passes
that check. Do not hand a file to the user as fixed on the strength of a parser check, and do not
ask the user to open diagnostic variants one by one when Word is installed locally. Test it
yourself through COM (`pywin32`). `OpenNoRepairDialog` read-only never prompts and never repairs,
so a rejected file raises instead of opening a dialog:

```python
import os, win32com.client
w = win32com.client.DispatchEx('Word.Application'); w.Visible = False; w.DisplayAlerts = 0
try:
    for f in paths:
        try:
            d = w.Documents.OpenNoRepairDialog(os.path.abspath(f), False, True, False)
            print('OK  ', f); d.Close(0)
        except Exception:
            print('FAIL', f)
finally:
    w.Quit()  # otherwise a hidden WINWORD.EXE stays behind and keeps a lock on failed files
```

Run it on the untouched original first. If the original also reports FAIL, the check cannot tell
good files from bad ones. Do not delete a file that just failed to open in the same run, because
Word still holds a lock on it. Do not name a helper script after a stdlib module (`bisect.py`,
`random.py`), because it shadows that module for every script in the same folder.

When Word rejects a file and the cause is not obvious, bisect instead of guessing. Split
`<w:body>` into its top-level children, keep the trailing `<w:sectPr>`, and write variants that keep
only the first N children. The first N that fails points to the offending paragraph or table. A
lone paragraph that fails when placed in an otherwise empty body confirms it. Without Word
(Linux/macOS), a LibreOffice round-trip is only a weak proxy, because LibreOffice accepts markup
that Word rejects.

## Editing through Word (COM)

Use the toolkit in `scripts/docx/` instead of writing COM code from scratch. It implements every
rule below:

| Script | Purpose |
|--------|---------|
| `word_com.py` | `WordSession` library: guarded find, replace, insert before headings with bookmark repair, tables (cloned from a model table, or bordered), pictures (insert, tracked replace), REF fields, header/footer text boxes, custom properties, comment replies |
| `verify_docx.py` | JSON check: deletion markup lint, REF number vs target heading, unnumbered headings, comments anchored in deletions, outline, `--word` open check, `--accepted` post-review check, `--fix-authors`, `--fix-comment-anchors` |
| `docx_media.py` | `list` / `swap` embedded images by content (edit a screenshot already in the document) |
| `docx_insert.py` | Insert headings, paragraphs, restarted numbered steps, bullets, hyperlinks and PNG pictures at an anchor heading by JSON spec; copies every other part unchanged |
| `docx_mentions.py` | `people` (emails of comment authors from `people.xml`) / `mention` (turn plain "@Name" in comments into real @mentions) |
| `safe_replace.py` | Copy the result over the user's file only if it is closed and unchanged since your base copy |
| `../office/annotate_screenshot.py` | Screenshots for a document: blur, numbered red boxes, crop, frame, grid; warns when a number would be clipped (see "Screenshots for a procedure") |
| `../pptx/export_slide_images.py` | Slide images through PowerPoint, cropped to the screenshots and callouts, text placeholders removed (see "Converting a slide deck into a Word guide") |
| `tests/test_word_com.py` | Builds a fixture through Word and exercises all of the above (about a minute) |

Workflow:

```bash
cp "<user file>.docx" scratch/base.docx          # base copy, never edited
python -u my_edits.py scratch/base.docx scratch/out.docx   # uses word_com.WordSession
python scripts/docx/verify_docx.py scratch/out.docx --word --accepted --outline --fix-authors scratch/final.docx
python scripts/docx/safe_replace.py scratch/final.docx "<user file>.docx" --base scratch/base.docx --word
```

```python
import sys
sys.path.insert(0, r"<skill-dir>\scripts\docx")
from word_com import WordSession, H2
with WordSession(sys.argv[1], sys.argv[2], log=print) as ws:
    ws.replace("old wording", "new wording")
    tpl = ws.template(["A plain body paragraph without bookmarks"])
    ws.insert_before(ws.para("Next chapter", level=1), tpl, "New section", style=H2)
```

The rules below explain what the toolkit guards against. They came out of a 2026-09-28 session
where each one cost hours.

**Finding text**

- `Find` matches text inside tracked deletions, even in the Final/No Markup view. Skip a match only
  when a deletion revision actually overlaps it. `Range.Revisions` can list every revision in the
  paragraph, so test the overlap:

  ```python
  def in_deletion(r):
      for rev in r.Revisions:
          if rev.Type == 2:  # wdRevisionDelete
              rr = rev.Range
              if rr.Start < r.End and rr.End > r.Start:
                  return True
      return False
  ```

  When an earlier tool interleaved `w:del` and `w:ins` inside one paragraph, Word can report a
  deletion that covers live inserted text. Bypass the guard for text you know is live.
- Near the table of contents and other fields, `Find` can return a match that starts *before* the
  search range. A loop that restarts at `r.End` then never advances. Always move forward
  (`s = max(r.End, s + 1)`), cap the iterations, and start body searches after
  `max(t.Range.End for t in doc.TablesOfContents)`.
- A phrase you replaced earlier in the session is no longer contiguous: the tracked-deleted old text
  sits between the pieces. Anchor on text after it, or delete a range computed from two anchors.
- `Range.Text` omits tracked-deleted text, but character positions still count it. Never compute a
  range from an offset into `Range.Text`. Use a `Find` bounded to the paragraph instead.
- Take the paragraph of a match with `doc.Range(r.Start, r.Start).Paragraphs(1)`. Reusing the Range
  returned by `Find` raised "Object has been deleted".

**Structure**

- Inserting content at the start of a paragraph moves the bookmarks that start there (`_Ref...`,
  `_Toc...`) onto the new text. `REF` cross-references then point at the wrong heading. Before
  inserting in front of a heading, record its bookmark names and re-add them to the heading
  afterwards with `doc.Bookmarks.Add(name, heading.Range)` (set `Bookmarks.ShowHidden = True` first).
- Never call `ListFormat.RemoveNumbers()` on a heading: it writes `numId 0` and the heading loses its
  outline number, which shifts every `REF` after it. To drop a bullet copied from a template, set
  the style and call `Paragraph.Reset()`. If a heading keeps `numId 0` next to a tracked
  `pPrChange`, remove that `w:numPr` from the paragraph's XML. `verify_docx.py` reports these as
  `unnumbered_headings`.
- Deleting a whole paragraph right before a heading (a caption, say) makes Word display the heading
  with the deleted paragraph's style until the deletion is accepted. After Accept All the heading is
  correct. Check the post-review state with `verify_docx.py --accepted` rather than trusting the
  pending view.
- `Tables.Add` on a placeholder paragraph placed before a heading gives the cells the heading style.
  Set `table.Range.Style` to Normal and remove numbering, with `TrackRevisions` off for that step so
  the review shows no "Formatted" noise. The table itself stays a tracked insertion.
- A document's tables often get their look (borders, header shading) from direct formatting, not
  from a table style. Copying only `Table.Style` from such a table gives "Table Normal": no borders.
  `add_table(..., model=doc.Tables(n))` clones an existing table of the document instead and refills
  it; without a model it adds single borders. Seen 2026-10-05: an AOS 8 guide's new tables shipped
  borderless. Two tables with no paragraph between them merge into one.
- Text boxes are not in `doc.Paragraphs`. Captions that live in a text box are found through
  `doc.Shapes` (`TextFrame.TextRange`). `Shape.Delete()` with tracking on is recorded as a deletion.
- Write cross-references as `REF _RefNNN \n \h` fields, never as typed numbers, and update only
  `REF` fields at the end (`field.Type == 3`). Leave the table of contents to the user unless asked.
- Header and footer text often sits in text boxes, which `HeaderFooter.Range` does not include.
  Search and update fields through `hf.Shapes(i).TextFrame.TextRange` as well.
- Version, date or reference values shown through `DOCPROPERTY` fields come from
  `doc.CustomDocumentProperties` (UI: File > Info > Properties > Advanced Properties > Custom).
  Set the property, then update the fields in every header, footer and header/footer text box.
  Updating the body (Ctrl+A, F9) does not reach them. Property changes are not tracked.
- When deleting stale text from a paragraph that anchors shapes (footer bands, logos), delete only
  the matched characters, never the paragraph, and compare `hf.Shapes.Count` before and after.
- A tracked deletion of content that carries comments (a picture replaced with `replace_picture`, a
  rewritten sentence) can pull the comment end markers and references into the `w:del`. Word then
  shows an empty comments pane, even for comments elsewhere in the document, and deletes those
  comments on Accept All. A comment whose range holds only deleted content is also deleted on Accept
  All. `verify_docx.py` reports both as `comments_in_deletion`. `--fix-comment-anchors OUT` moves the
  markers out of the deletion and stretches each such range over the next live content (the
  replacement). Seen 2026-10-05 on a reviewer's comments attached to a replaced diagram.

**Images**

- `InlineShapes.AddPicture` downsamples large images (a 1915 px screenshot was stored at 1438 px).
  To edit a screenshot already in the document, replace the bytes of its `word/media/imageN.png`
  in the saved zip instead of re-inserting it: size and position stay as they are, and nothing new
  shows in the review. Find the media file by content (same aspect ratio plus a small grayscale
  thumbnail comparison), not by name. Word renumbers media files when the user saves.
- Several revision authors can surface as `Name [2]`. Normalize the `w:author` attribute in the
  saved XML afterwards (`document.xml`, `people.xml`) instead of changing `Application.UserName`,
  which persists in the registry and is not restored if the process is killed.

**Performance**

- Do not walk `doc.Paragraphs` reading `Range.ListFormat.ListString`. On a 420-paragraph document
  with tracked changes it ran for over 30 minutes. Walking `doc.Fields` and deleting while iterating
  hung the same way. Locate targets with `Find` and derive heading numbers offline from the XML.

**Process hygiene**

- Run the script with `python -u`, log a timestamp per step to a file, and wrap it in `timeout`. A
  pipe through `tail` hides all progress until the end, so a hang looks like slow work.
- Close the document in an `except BaseException` handler (`SystemExit` is not an `Exception`) and
  always `Quit()` in `finally`.
- Killing Word leaves windowless `WINWORD.EXE` processes and `~$` lock files. Kill only windowless
  instances started by your own runs, and delete lock files in your scratch folder only. After
  several forced kills, Word shows a crash-recovery dialog at the next start. It blocks COM
  invisibly: `Documents.Open` hangs without an error. Ask the user to dismiss it, because it may
  not appear in a screenshot.
- Before overwriting the user's file, check that it is closed (no `~$` file) and hash it against the
  copy you edited. Users save between rounds, sometimes with real edits. Diff the body text and
  rebase your changes onto their version.

**Comment replies and @mentions**

A real @mention notifies the person; plain "@Name" text notifies nobody. `Comments.Replies.Add`
(`ws.reply(...)`) writes plain text, so convert it afterwards:

1. Reply in the session: `ws.reply("text of the reviewer's comment", "@First Last answer...")`.
   The author is the current Office user.
2. Resolve each person's email. Never guess an address.
   - `python docx_mentions.py people out.docx` lists every comment author signed in with Microsoft
     365, read from `word/people.xml` (`S::<email>::<object id>`). A reviewer you reply to is always
     there.
   - Anyone else: ask the user, or search a directory or mail tool you have. The msgraph MCP
     configured here searches recent mail, Teams, tasks and calendar only (14 to 30 days) and has
     no directory lookup: on 2026-10-05 it found nothing for a colleague who had only commented.
3. `python docx_mentions.py mention out.docx final.docx --person "First Last" [--person "Other=email"]`.
   It fails when an email is missing or no "@Name" text was found.
4. Verify: `verify_docx.py final.docx --word`, and in Word each reply shows the name as a mention
   (`Comment.Range.Hyperlinks` holds `mailto:<email>`).
5. Microsoft 365 sends the notification when the file is saved in OneDrive or SharePoint. Whether
   it does so for a mention written by a script was not verified (2026-10-05): tell the user, and
   ask them to confirm the person was notified or to re-pick the name from Word's @ list.

The stored form, which `docx_mentions.py` reproduces from a mention Word itself wrote:
a `HYPERLINK "mailto:<email>"` field whose result is the run `@Name` in the `Mention` character
style, with a bookmark `_@_<32 hex>Z` around the field separator.

**Converting a slide deck into a Word guide**

Used 2026-10-05 to turn a 50-slide setup-guide deck into a structured Word guide on an existing
guide's template:

1. Copy the template guide. In one untracked `WordSession`, accept its revisions, delete its
   comments, then insert the new body before the template's first body heading. Anchor insertions on
   a bookmark placed on the paragraph after that heading, not on a saved character offset: hyperlinks
   and comments added on the way shift every offset. Delete the old body last, from the old heading
   to the end, keeping the final paragraph mark (it carries the section's headers and footers).
2. Reuse the template's own paragraphs as models (`ws.template`), its bullet and numbered lists, and
   its tables (`add_table(model=...)`). A copied run can carry direct bold: call
   `Range.Font.Reset()` on plain paragraphs you insert. Restart a numbered list on its first item
   (`ApplyListTemplateWithLevel(lf.ListTemplate, False, 2, 2)`) and copy that item for the next ones.
3. Slide images: `python scripts/pptx/export_slide_images.py deck.pptx img/ --slides 12-21`. Diagrams:
   `--full --hide Caption`.
4. Reset the change record, the `ref`, `Doc version` and `Doc Date` properties and the core title,
   refresh header and footer fields, update the TOC, and export the PDF with an absolute path: a
   relative path lands in Word's working folder (OneDrive Documents).
5. Render the PDF and look at every page. Watch for a heading page break that leaves a page holding
   one line: remove a spacer paragraph or merge two short paragraphs rather than shrinking fonts.
   Keep tables on one page with `Rows.AllowBreakAcrossPages = False` and `KeepWithNext` on all
   rows but the last.

**Screenshots for a procedure**

- Number each step's red box in the picture and cite the number in the step text ("click
  “Export” (3)"). `scripts/office/annotate_screenshot.py spec.json` draws the boxes and numbers,
  blurs names, emails, tenant IDs and keys, crops, frames, and lays out several panels. It moves a
  number that would be clipped by the crop and reports it under `warnings`: read them.
- Stack panels in one column (`"cols": 1`) when they will be scaled to page width; side by side,
  the UI text becomes unreadable. Crop out the browser header with the signed-in user.
- Capturing a web UI with the browser tools: sections that expand with an animation can stop
  half-open while the window is in the background; take another screenshot and they finish. Do not
  force them open with CSS overrides: the panel resets its heights and the sections overlap. A
  panel whose content scrolls inside a fixed height can be shown whole by lifting `max-height` and
  `overflow` on the one scrolling element (a local, unsaved change).
- Never save, enable or generate anything to get a screenshot: open forms and dialogs, capture,
  then cancel. Ask the user before any step that changes the tenant (activations, keys).
- A value that must match the guide (a recommended power level, a version) can be corrected in the
  image when the user approves; say so in the report, and that the live system still differs.
  `annotate_screenshot.py` does it with a panel key `"replace": [{"box": [x0, y0, x1, y1], "text": "300"}]`:
  it erases the text in the box and redraws the new text in the same place, colour and height.
  To correct a picture already in a document, edit the extracted image and put it back with
  `docx_media.py swap`.

**Verifying the result**

Besides the Word acceptance check, simulate the accepted view from the XML: drop `<w:del>` content,
`<w:txbxContent>` blocks and `<w:pPrChange>` records, and drop empty paragraphs whose paragraph
mark is deleted. Then number the headings and check that every `REF` field shows the number of the
heading its bookmark sits on. When linting `w:t`/`w:instrText` inside `w:del`, exclude text-box
content: a deleted drawing run keeps its text box's own runs, and Word accepts that.

## XML Reference

### Document structure (word/document.xml)

```xml
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p>              <!-- paragraph -->
      <w:pPr>          <!-- paragraph properties -->
        <w:pStyle w:val="Heading1"/>
      </w:pPr>
      <w:r>            <!-- run -->
        <w:rPr>        <!-- run properties (bold, italic, etc.) -->
          <w:b/>
        </w:rPr>
        <w:t>Text</w:t>
      </w:r>
    </w:p>
  </w:body>
</w:document>
```

### Tracked changes

Tracked insertions and deletions wrap content in `<w:ins>` and `<w:del>` elements:

```xml
<w:ins w:id="1" w:author="User" w:date="2024-01-01T00:00:00Z">
  <w:r>
    <w:t>inserted text</w:t>
  </w:r>
</w:ins>

<w:del w:id="2" w:author="User" w:date="2024-01-01T00:00:00Z">
  <w:r>
    <w:delText>deleted text</w:delText>
  </w:r>
</w:del>
```

To accept all changes programmatically, use `scripts/docx/accept_changes.py` (LibreOffice macro approach) for reliable results across complex documents.

### Comments

Comments in OOXML span multiple files:
- `word/comments.xml` — comment content
- `word/document.xml` — `<w:commentRangeStart>` and `<w:commentRangeEnd>` markers + `<w:commentReference>`

```xml
<!-- In word/comments.xml -->
<w:comments>
  <w:comment w:id="1" w:author="Agent" w:date="2024-01-01T00:00:00Z" w:initials="A">
    <w:p>
      <w:r><w:t>Comment text here</w:t></w:r>
    </w:p>
  </w:comment>
</w:comments>

<!-- In word/document.xml, wrapping the commented text -->
<w:commentRangeStart w:id="1"/>
<w:r><w:t>commented text</w:t></w:r>
<w:commentRangeEnd w:id="1"/>
<w:r>
  <w:rPr><w:rStyle w:val="CommentReference"/></w:rPr>
  <w:commentReference w:id="1"/>
</w:r>
```

Use `scripts/docx/comment.py` to add comments to unpacked documents — it handles the boilerplate across both files.

Replies and modern comments add three parts, keyed by the `w14:paraId` of the comment's last
paragraph: `commentsExtended.xml` (`w15:paraIdParent` links a reply to its parent, `w15:done` marks
resolved), `commentsIds.xml` (durable ids) and `commentsExtensible.xml`. `people.xml` maps author
names to Microsoft 365 identities. Create replies through Word (`WordSession.reply`) rather than by
hand: Word writes all four parts consistently.

### Images

Images are stored in `word/media/` and referenced via relationships:
- `word/_rels/document.xml.rels` maps `rId` values to media paths
- `<w:drawing>` elements in document.xml reference images by `rId`

## Font Embedding

To ensure consistent rendering across machines, embed fonts:

### In XML (word/settings.xml)

Add the `<w:embedTrueTypeFonts/>` element:
```xml
<w:settings>
  <w:embedTrueTypeFonts/>
  <w:saveSubsetFonts/>  <!-- Embed only used characters (smaller file) -->
</w:settings>
```

### Considerations

- Embedding increases file size significantly (full fonts: 1-5MB each; subsetted: 50-500KB)
- `saveSubsetFonts` embeds only glyphs used in the document — recommended
- Some fonts have licensing restrictions on embedding — check the `fsType` flag in the font's OS/2 table
- When creating with docx-js, font embedding is NOT directly supported — use the unpack/settings.xml/pack pipeline to add these flags after creation

## Encrypted / Password-Protected Files

### Detection

`unpack.py` automatically detects encrypted files and exits with code 3. Signs of encryption:
- Missing `[Content_Types].xml` (file is an OLE compound document wrapping encrypted content)
- Presence of `EncryptionInfo` or `EncryptedPackage` entries

### Decryption

Use `msoffcrypto-tool` (Python):
```bash
pip install msoffcrypto-tool
msoffcrypto-tool input.docx output.docx -p "password"
```

Then proceed with the decrypted file normally.

### Password-protecting output

LibreOffice can encrypt on save:
```bash
python scripts/office/soffice.py --macro "Standard.Module1.SaveWithPassword" input.docx
```

Or use msoffcrypto-tool for encryption (read-only protection only).

## Macro-Enabled .docm Files

A `.docm` file is identical to `.docx` in structure but includes `word/vbaProject.bin` containing VBA macro code.

### Key differences from .docx

- Content type in `[Content_Types].xml` uses `application/vnd.ms-word.document.macroEnabled.main+xml` instead of `application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml`
- `word/vbaProject.bin` must be preserved during any edit operations
- `pack.py` automatically preserves `vbaProject.bin` and registers the `.bin` content type

### Working with .docm

```bash
# Unpack normally — vbaProject.bin is extracted as binary
python scripts/office/unpack.py document.docm ./work/

# Edit XML as needed (do NOT modify vbaProject.bin)

# Pack — vbaProject.bin is preserved, content type auto-registered
python scripts/office/pack.py ./work/ output.docm
```

## Converting to Images

For visual verification or thumbnail generation:

```bash
# Convert to PDF first, then to images
python scripts/office/soffice.py --convert-to pdf document.docx --outdir ./tmp/
# Then use pdftoppm (from poppler-utils):
pdftoppm -png ./tmp/document.pdf ./tmp/page
# Produces: page-1.png, page-2.png, etc.
```

On Windows, install poppler via: `choco install poppler` or download from https://github.com/oschwartz10612/poppler-windows/releases

## Dependencies

| Tool | Purpose | Install |
|------|---------|---------|
| Node.js + `docx` package | Create new documents | `npm install` in skill dir |
| pandoc | Read/convert documents | `choco install pandoc` / `brew install pandoc` / `apt install pandoc` |
| LibreOffice | Convert, accept changes, render | `choco install libreoffice-fresh` / `brew install --cask libreoffice` / `apt install libreoffice` |
| poppler-utils (pdftoppm) | PDF/image conversion | `choco install poppler` / `brew install poppler` / `apt install poppler-utils` |
| msoffcrypto-tool | Decrypt protected files | `pip install msoffcrypto-tool` |
