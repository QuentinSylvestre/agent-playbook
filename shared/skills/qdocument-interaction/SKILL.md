---
name: qdocument-interaction
description: "Support scripts and document rules for Word, PDF, PowerPoint and Excel tasks: Word COM edits with tracked changes and comment replies, PowerPoint COM edits for currently open presentations, safe overwrite of the user's file, swapping and annotating screenshots, inserting a section with pictures, slide deck to Word guide, plus format references. Use it for any .docx, .pdf, .pptx or .xlsx task, alongside Anthropic's docx, pdf, pptx and xlsx skills when those are available (they cover creation and the generic edit pipeline), and on its own where they are not."
argument-hint: "<optional: format override — docx, pdf, pptx, or xlsx>"
---

# /qdocument-interaction

Route document tasks to the correct format-specific procedural knowledge and execute using co-located scripts.

> **Relationship to Anthropic's skills.** This skill is an independent, shorter rewrite of Anthropic's
> docx / pdf / pptx / xlsx skills plus tools they lack. It does not receive upstream fixes: when a
> generic task fails here, compare against the current Anthropic skill of the same format. It is shared
> (all harnesses see it); on Kiro it is the only document skill. Where Anthropic's skills are also
> available, use them for creation and the generic unpack, edit and pack pipeline, and use this skill's
> `scripts/` for what they lack: Word COM (`scripts/docx/word_com.py`), `safe_replace.py`,
> `docx_media.py`, `docx_insert.py`, `docx_mentions.py`, `verify_docx.py`,
> `scripts/office/annotate_screenshot.py` and `scripts/pptx/export_slide_images.py`.
>
> **Finding the scripts.** Paths below are relative to this skill's folder: `~/.claude/skills/qdocument-interaction/`
> on Claude Code, `~/.kiro/skills/qdocument-interaction/` on Kiro. Run scripts by that absolute path
> from the folder that holds your working files.

When creating or revising a deliverable that follows a house style (setup guide, report, KB article, architecture deck), read the user's house-style topic first, if `memory/MEMORY.md § Topics` indexes one.

## Quick-Reference Routing Table

| Format | File | Primary operations | Notes |
|--------|------|-------------------|-----------------|
| .docx | docx.md | create, read, edit, tracked changes | Node.js (docx) |
| .pdf | pdf.md | read, create, merge/split, forms, OCR | Python (reportlab, pypdf) |
| .pptx | pptx.md | create, read, edit, QA verification | Node.js (pptxgenjs) |
| .pptx (design) | pptx-design.md | design reference (Step 4, not Step 3) | Read alongside pptx.md for creation tasks |
| .pptx (COM) | pptx-com.md | COM reference (Step 5, not Step 3) | Windows-only; read when task involves a currently open PowerPoint presentation |
| .xlsx | xlsx.md | create, edit, analysis, recalculation | Python (openpyxl) |

## Cross-Format Delivery Rules

1. **Safe overwrite** — before overwriting the user's file, verify it is closed (no `~$` lock file — Windows/Office lock artifact) and unchanged since your base copy. Use `scripts/docx/safe_replace.py` for docx; for non-docx formats, verify the file is not locked and check it against your base copy before overwriting; the per-format Verification Gate in each sub-document defines the minimum required checks.
2. **Runtime verification mandatory** — text extraction and parser checks do not prove a file is correct. The verification standard per format is documented in each sub-document. Do not deliver a file you have not verified by the method its sub-document specifies.

## Shared Dependencies

- **Python 3.8+** — required for all scripts
- **LibreOffice** — headless mode for conversion, recalculation, rendering
- **Node.js** — optional; required only for docx/pptx creation from scratch
- **Microsoft Word + pywin32** — optional (Windows); preferred for tracked-change edits to an existing .docx and required for the Word acceptance check (`scripts/docx/word_com.py`, see docx.md)
- **Pillow** — optional; required for `scripts/docx/docx_media.py`, `scripts/office/annotate_screenshot.py` and the Word toolkit test
- **Microsoft PowerPoint + pywin32** — optional (Windows); required for `scripts/pptx/export_slide_images.py` and for all COM interaction with currently open presentations (`pptx-com.md`)

## Degradation Matrix (Node.js absent)

| Operation | Available? | Fallback |
|-----------|-----------|----------|
| Read all formats | Yes | Python/CLI tools |
| Edit all formats | Yes | unpack → XML → pack pipeline |
| Create xlsx | Yes | openpyxl |
| Create pdf | Yes | reportlab |
| Create docx | No | Requires Node.js (docx library) |
| Create pptx | No | Requires Node.js (pptxgenjs) |

## Script Interface Contract

All scripts in `scripts/` follow these conventions:

- **Exit codes**: 0 = success, 1 = general failure, 2 = required tool not found (LibreOffice/poppler), 3 = input file encrypted, 4 = the Office application the script needs is already running with the user's work (refused, nothing touched)
- **Stdout**: JSON when returning structured data; otherwise silent on success
- **Stderr**: human-readable error messages
- **Standalone**: no cross-script imports; each script is a self-contained CLI tool
- **Invocation**: `python scripts/<subdir>/script.py [args]` from the skill root

## Process

1. **Detect format** — identify target format from: file extensions in the task (.docx, .pdf, .pptx, .xlsx), keywords ("presentation", "spreadsheet", "PDF", "Word", "slide deck", "form"), or the user's argument override. If ambiguous, ask.

2. **Check dependencies** — verify required tools are installed before attempting operations:
   - Run `python scripts/office/soffice.py --check` to verify LibreOffice availability
   - For creation tasks: verify Node.js (`node --version`) if the format requires it (docx, pptx)
   - Report missing tools with platform-specific install instructions; do not proceed with operations that will fail

3. **Load sub-document** — read the relevant format reference file:
   - .docx → read `docx.md` (co-located with this skill file)
   - .pdf → read `pdf.md` (co-located with this skill file)
   - .pptx → read `pptx.md` (co-located with this skill file)
   - .xlsx → read `xlsx.md` (co-located with this skill file)

4. **For pptx creation** — additionally read `pptx-design.md` (co-located) for color palettes, typography, layout patterns, and anti-patterns

5. **For tasks involving interaction with a currently open PowerPoint application on Windows** — additionally read `pptx-com.md` (co-located) for COM safety patterns, snapshot discipline, and idempotent build conventions

6. **Execute** — follow the procedures documented in the loaded sub-document. Use co-located scripts where specified. For Node.js creation tasks, run `npm install` in the skill directory if `node_modules/` is absent.
