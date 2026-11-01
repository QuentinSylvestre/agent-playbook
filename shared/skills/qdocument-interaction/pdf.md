# PDF — Procedural Knowledge

## Quick Reference

| Task | Tool | Notes |
|---|---|---|
| Read text | `pypdf` or `pdfplumber` | pdfplumber better for tables/layout |
| Extract tables | `pdfplumber` | Returns structured table data |
| Create new PDF | `reportlab` | Full control over layout |
| Merge/split/rotate | `pypdf` | Lightweight, no rendering needed |
| Fill fillable forms | `pypdf` | Uses AcroForm fields |
| Fill non-fillable forms | reportlab annotations | Overlay text at coordinates |
| OCR scanned PDFs | `pytesseract` + `pdf2image` | Requires Tesseract installed |
| CLI text extraction | `pdftotext` (poppler) | Fast, no Python needed |
| CLI manipulation | `qpdf` | Decrypt, linearize, repair |
| Convert to images | `pdf2image` or `scripts/pdf/convert_pdf_to_images.py` | Requires poppler |

## Dependencies

```bash
# Python libraries
pip install "pypdf>=4.0" pdfplumber reportlab pdf2image pytesseract Pillow

# System tools (platform-specific)
# Windows (chocolatey):
choco install poppler tesseract
# macOS:
brew install poppler tesseract
# Linux (Debian/Ubuntu):
sudo apt install poppler-utils tesseract-ocr
# Linux (Fedora):
sudo dnf install poppler-utils tesseract

# CLI tools
# qpdf: https://qpdf.readthedocs.io/
# Windows: choco install qpdf
# macOS: brew install qpdf
# Linux: sudo apt install qpdf
```

**CRITICAL**: Use `pypdf>=4.0`. Do NOT use the deprecated `PyPDF2` package — it is unmaintained and has known bugs. All imports should be `from pypdf import PdfReader, PdfWriter`.

## Reading & Extracting Content

### pypdf — Basic text extraction

```python
from pypdf import PdfReader

reader = PdfReader("document.pdf")
for page in reader.pages:
    text = page.extract_text()
    print(text)
```

### pdfplumber — Layout-aware extraction

Better for documents with tables, columns, or complex layouts:

```python
import pdfplumber

with pdfplumber.open("document.pdf") as pdf:
    for page in pdf.pages:
        # Full text
        text = page.extract_text()

        # Tables (returns list of lists)
        tables = page.extract_tables()
        for table in tables:
            for row in table:
                print(row)

        # Words with positions
        words = page.extract_words()
        # Each word: {'text': '...', 'x0': ..., 'top': ..., 'x1': ..., 'bottom': ...}
```

### Image extraction

```python
from pypdf import PdfReader

reader = PdfReader("document.pdf")
for page in reader.pages:
    for image in page.images:
        with open(image.name, "wb") as f:
            f.write(image.data)
```

## Creating PDFs with reportlab

### Basic document

```python
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.units import inch, cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

doc = SimpleDocTemplate("output.pdf", pagesize=letter)
styles = getSampleStyleSheet()
story = []

story.append(Paragraph("Title", styles["Title"]))
story.append(Spacer(1, 12))
story.append(Paragraph("Body text here.", styles["Normal"]))

doc.build(story)
```

### Tables

```python
data = [
    ["Header 1", "Header 2", "Header 3"],
    ["Row 1", "Data", "123"],
    ["Row 2", "Data", "456"],
]

table = Table(data, colWidths=[2*inch, 2*inch, 1.5*inch])
table.setStyle(TableStyle([
    ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
    ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
    ("FONTSIZE", (0, 0), (-1, 0), 12),
    ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
    ("GRID", (0, 0), (-1, -1), 1, colors.black),
]))
story.append(table)
```

### CRITICAL: Subscript and superscript

**NEVER use Unicode subscript/superscript characters** (e.g., Unicode chars like superscript digits) in reportlab. They render incorrectly or as missing glyphs in most PDF fonts.

Instead, use reportlab's inline markup:

```python
# Correct — use <super> and <sub> tags in Paragraph
Paragraph("H<sub>2</sub>O is water", styles["Normal"])
Paragraph("E = mc<super>2</super>", styles["Normal"])

# WRONG — never do this
# Paragraph("H₂O", styles["Normal"])  # Unicode subscript — will break
# Paragraph("x²", styles["Normal"])    # Unicode superscript — will break
```

### Custom fonts

```python
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

pdfmetrics.registerFont(TTFont("CustomFont", "/path/to/font.ttf"))
style = ParagraphStyle("custom", fontName="CustomFont", fontSize=12)
```

## Merge, Split, and Rotate

### Merge multiple PDFs

```python
from pypdf import PdfWriter

writer = PdfWriter()
for pdf_path in ["file1.pdf", "file2.pdf", "file3.pdf"]:
    writer.append(pdf_path)
writer.write("merged.pdf")
writer.close()
```

### Split PDF (extract pages)

```python
from pypdf import PdfReader, PdfWriter

reader = PdfReader("input.pdf")
writer = PdfWriter()

# Extract pages 2-5 (0-indexed)
for page_num in range(1, 5):
    writer.add_page(reader.pages[page_num])

writer.write("pages_2_to_5.pdf")
writer.close()
```

### Rotate pages

```python
from pypdf import PdfReader, PdfWriter

reader = PdfReader("input.pdf")
writer = PdfWriter()

for page in reader.pages:
    page.rotate(90)  # 90, 180, or 270
    writer.add_page(page)

writer.write("rotated.pdf")
writer.close()
```

### Add watermark

```python
from pypdf import PdfReader, PdfWriter

reader = PdfReader("input.pdf")
watermark = PdfReader("watermark.pdf").pages[0]
writer = PdfWriter()

for page in reader.pages:
    page.merge_page(watermark)
    writer.add_page(page)

writer.write("watermarked.pdf")
writer.close()
```

## Form Filling

### Workflow: Fillable PDFs (AcroForm)

1. **Detect** — check if the PDF has fillable fields:
   ```
   python scripts/pdf/check_fillable_fields.py input.pdf
   ```
2. **Extract field info** — get field names, types, and options:
   ```
   python scripts/pdf/extract_form_field_info.py input.pdf
   ```
3. **Fill fields** — provide a JSON mapping of field names to values:
   ```
   python scripts/pdf/fill_fillable_fields.py input.pdf output.pdf --data '{"field_name": "value"}'
   ```

### Workflow: Non-fillable PDFs (annotation overlay)

For PDFs where form fields are just static text/lines (not AcroForm fields):

1. **Extract structure** — find text labels, lines, and checkboxes with coordinates:
   ```
   python scripts/pdf/extract_form_structure.py input.pdf
   ```
2. **Check bounding boxes** — validate estimated field positions:
   ```
   python scripts/pdf/check_bounding_boxes.py input.pdf --fields fields.json
   ```
3. **Fill with annotations** — overlay text at computed coordinates:
   ```
   python scripts/pdf/fill_pdf_form_with_annotations.py input.pdf output.pdf --data fields.json
   ```

### Programmatic form filling (pypdf)

```python
from pypdf import PdfReader, PdfWriter

reader = PdfReader("form.pdf")
writer = PdfWriter()
writer.append(reader)

# Fill fields on first page
writer.update_page_form_field_values(
    writer.pages[0],
    {"field_name": "value", "another_field": "another_value"},
    auto_regenerate=False,
)

writer.write("filled.pdf")
writer.close()
```

## OCR for Scanned PDFs

```python
from pdf2image import convert_from_path
import pytesseract

# Convert PDF pages to images
images = convert_from_path("scanned.pdf", dpi=300)

# OCR each page
for i, image in enumerate(images):
    text = pytesseract.image_to_string(image)
    print(f"--- Page {i + 1} ---")
    print(text)
```

Requirements:
- Tesseract must be installed and in PATH
- poppler must be installed (for pdf2image)
- For Windows, set `pytesseract.pytesseract.tesseract_cmd` if not in PATH

## Password Protection

### Encrypt a PDF

```python
from pypdf import PdfReader, PdfWriter

reader = PdfReader("input.pdf")
writer = PdfWriter()
writer.append(reader)

writer.encrypt(user_password="read_password", owner_password="owner_password")
writer.write("encrypted.pdf")
writer.close()
```

### Decrypt a PDF

```python
from pypdf import PdfReader, PdfWriter

reader = PdfReader("encrypted.pdf")
if reader.is_encrypted:
    reader.decrypt("password")

writer = PdfWriter()
writer.append(reader)
writer.write("decrypted.pdf")
writer.close()
```

## CLI Tools

### pdftotext (poppler)

```bash
# Extract text from PDF
pdftotext input.pdf output.txt

# Extract specific pages
pdftotext -f 2 -l 5 input.pdf output.txt

# Maintain layout
pdftotext -layout input.pdf output.txt
```

### qpdf

```bash
# Decrypt a PDF
qpdf --decrypt --password=secret input.pdf output.pdf

# Linearize (optimize for web)
qpdf --linearize input.pdf output.pdf

# Split into single pages
qpdf --split-pages input.pdf output_%d.pdf

# Merge
qpdf --empty --pages file1.pdf file2.pdf -- output.pdf

# Repair damaged PDF
qpdf --replace-input input.pdf
```

## Converting PDF to Images

Use the helper script for batch conversion:

```bash
python scripts/pdf/convert_pdf_to_images.py input.pdf --output-dir ./pages --dpi 200
```

Or programmatically:

```python
from pdf2image import convert_from_path

images = convert_from_path("input.pdf", dpi=200, fmt="png")
for i, image in enumerate(images):
    image.save(f"page_{i + 1}.png", "PNG")
```

## Scripts Reference

| Script | Purpose | Output |
|---|---|---|
| `check_fillable_fields.py` | Detect if PDF has fillable AcroForm fields | JSON: `{has_fields, field_count}` |
| `extract_form_field_info.py` | Extract field metadata (name, type, options) | JSON array of field objects |
| `extract_form_structure.py` | Extract visual structure (labels, lines, boxes) | JSON with elements and coordinates |
| `fill_fillable_fields.py` | Fill AcroForm fields from JSON data | Writes filled PDF |
| `fill_pdf_form_with_annotations.py` | Overlay text annotations on non-fillable PDF | Writes annotated PDF |
| `convert_pdf_to_images.py` | Convert pages to PNG images | PNG files in output directory |
| `check_bounding_boxes.py` | Validate field bounding boxes | JSON with validation results |

## Verification Gate

Apply these checks after every edit to content, layout, metadata, or form fields, and before delivery.

**Render after every edit.** Render the PDF to page images with `pdftoppm` and inspect all pages for layout defects: clipped text, overlapping elements, missing glyphs, broken tables, and incorrect page order.

```bash
pdftoppm -png output.pdf ./qa_pages/page
# Inspect: qa_pages/page-1.png, page-2.png, ...
```

**Reopen and verify after write.** After writing an output file, reopen it with `PdfReader` and verify it meets all expected properties (page count, form fields present, no encryption added unintentionally) before delivery. A successful `writer.write()` call does not guarantee a well-formed output.

```python
from pypdf import PdfReader
reader = PdfReader("output.pdf")
assert len(reader.pages) == expected_page_count
```

**AcroForm field data must be verified programmatically.** A correct visual appearance does not prove that canonical field data was updated. After filling an AcroForm, verify field values via `reader.get_fields()`, not only by visual render.

```python
fields = reader.get_fields()
assert fields["field_name"]["/V"] == expected_value
```
