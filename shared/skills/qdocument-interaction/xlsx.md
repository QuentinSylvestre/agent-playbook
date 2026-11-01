# xlsx — Spreadsheet Reference

## Requirements for All Outputs

- Use a professional font (Calibri 11pt by default; the user's house-style memory topic, if any, overrides it)
- Zero formula errors in final output — run `recalc.py` and verify
- Preserve existing templates and formatting when editing
- Never overwrite source data without explicit confirmation

## Verification Gate

Apply these checks before delivering any spreadsheet.

> **This gate is authoritative for delivery requirements.** It supersedes the `## Formula Verification Checklist` section below, which defers to this gate.

**Recalculate before delivery.** Run `recalc.py` after every formula change and before every delivery. A workbook saved with openpyxl reflects your formulas as strings, not evaluated values; LibreOffice headless evaluation is the only way to confirm zero errors.

```bash
python scripts/xlsx/recalc.py output.xlsx
# Confirm "total_errors": 0 before continuing
```

**Structural formula verification.** After recalculation, spot-check structural integrity:
- Open with `data_only=True` and verify key totals match expected values
- Confirm no `#REF!`, `#DIV/0!`, `#NAME?`, `#NULL!`, `#NUM!`, `#VALUE!`, or `#N/A` errors remain
- Verify named ranges (`wb.defined_names`) — none should reference `#REF!`
- Check cross-sheet references point to sheets that actually exist

Do not deliver a file with formula errors. Fix the source formula, re-save, and re-run `recalc.py` until `total_errors` is 0.

## Financial Modeling Conventions

### Color Coding (Industry Standard)

| Color | Font/Fill | Meaning | Example |
|---|---|---|---|
| Blue font | `Font(color="0000FF")` | Input/assumption (hard-coded value) | Revenue growth rate |
| Black font | `Font(color="000000")` | Formula (calculated) | Total revenue |
| Green font | `Font(color="008000")` | Cross-sheet reference | `=Sheet2!B5` |
| Red font | `Font(color="FF0000")` | External link / broken ref | Link to another workbook |
| Yellow fill | `PatternFill(fgColor="FFFF00", fill_type="solid")` | Key assumption cell | Discount rate |

### Number Formatting

| Data type | Format code | Example |
|---|---|---|
| Currency | `'$#,##0.00'` | $1,234.56 |
| Percentage | `'0.0%'` | 12.5% |
| Large numbers | `'#,##0'` | 1,234,567 |
| Dates | `'YYYY-MM-DD'` | 2026-01-15 |
| Accounting | `'_($* #,##0.00_);_($* (#,##0.00);_($* "-"??_);_(@_)'` | ($1,234.56) |

### Formula Construction Rules

1. **Never hardcode a value that could change** — use a named range or input cell
2. **One formula per row/column pattern** — fill down/across, never mix logic
3. **Label all assumptions** in a dedicated Assumptions sheet or section
4. **Document hardcodes** — if unavoidable, add a cell comment explaining why
5. **Use structured references** in tables: `=[@Revenue]*[@Growth_Rate]`

## CRITICAL RULE: Formulas Over Hardcoded Values

**WRONG** — hardcoded calculation:
```python
ws["C2"] = 150000  # revenue * growth — NEVER do this
```

**RIGHT** — formula that recalculates:
```python
ws["C2"] = "=A2*B2"  # references input cells
```

**Why**: Hardcoded values become stale immediately. Formulas maintain relationships and allow what-if analysis.

## CRITICAL WARNING: openpyxl Reads Cached Values Only

openpyxl does NOT evaluate formulas. When you read a cell containing `=SUM(A1:A10)`, you get the **last cached value from when Excel/LibreOffice last saved the file** — NOT the current calculated result.

**Implications**:
- If you modify source cells and read formula cells, values will be STALE
- After writing formulas with openpyxl, the `.value` attribute is the formula string, not a number
- You CANNOT verify formula correctness by reading the workbook back with openpyxl

**Mandatory workflow after formula changes**:
```
1. Save workbook with openpyxl
2. Run: python scripts/xlsx/recalc.py <file.xlsx>
3. Check JSON output for errors
4. Only THEN is the file ready for delivery
```

## Common Workflow

```
1. Choose tool (openpyxl for create/edit, pandas for analysis)
2. Create or load workbook
3. Modify (formulas, formatting, data)
4. Save
5. Recalculate: python scripts/xlsx/recalc.py output.xlsx
6. Verify: check recalc JSON for zero errors
```

## Creating New Files (openpyxl)

```python
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, numbers
from openpyxl.utils import get_column_letter

wb = Workbook()
ws = wb.active
ws.title = "Model"

# Column widths
for col, width in [(1, 20), (2, 15), (3, 15)]:
    ws.column_dimensions[get_column_letter(col)].width = width

# Headers with bold
headers = ["Item", "Q1", "Q2"]
for col, h in enumerate(headers, 1):
    cell = ws.cell(row=1, column=col, value=h)
    cell.font = Font(bold=True)
    cell.alignment = Alignment(horizontal="center")

# Input cells (blue font = assumption)
ws["B2"] = 100000
ws["B2"].font = Font(color="0000FF")
ws["B2"].number_format = '$#,##0'

# Formula cells (black font = calculated)
ws["B5"] = "=SUM(B2:B4)"
ws["B5"].font = Font(color="000000")
ws["B5"].number_format = '$#,##0'

# Cross-sheet reference (green font)
ws["C2"] = "=Assumptions!B3"
ws["C2"].font = Font(color="008000")

wb.save("output.xlsx")
```

## Editing Existing Files

```python
from openpyxl import load_workbook

# keep_vba=True for .xlsm files; data_only=False to preserve formulas
wb = load_workbook("existing.xlsx", keep_vba=False, data_only=False)
ws = wb.active

# Read formula (returns string like "=SUM(A1:A10)")
formula = ws["B5"].value

# Modify — always use formulas, not computed values
ws["B6"] = "=B5*1.1"

wb.save("existing.xlsx")
# Then run recalc.py!
```

**Key parameters**:
- `data_only=True` — reads cached values instead of formula strings (useful for analysis, NOT for editing)
- `keep_vba=True` — required when editing `.xlsm` to preserve macros

## Encrypted .xlsx Handling

```python
import msoffcrypto
import io
from openpyxl import load_workbook

with open("encrypted.xlsx", "rb") as f:
    office_file = msoffcrypto.OfficeFile(f)
    office_file.load_key(password="secret")
    decrypted = io.BytesIO()
    office_file.decrypt(decrypted)

wb = load_workbook(decrypted)
```

**Deps**: `pip install msoffcrypto-tool`

## Macro-Enabled .xlsm Handling

```python
# Reading/editing .xlsm — keep_vba=True preserves the VBA project
wb = load_workbook("macros.xlsm", keep_vba=True)
# ... edit ...
wb.save("macros.xlsm")  # saves with macros intact
```

- Always use `keep_vba=True` when loading `.xlsm` files
- Save with `.xlsm` extension (not `.xlsx`) to preserve macros
- The `vbaProject.bin` binary is preserved opaquely — cannot read/edit VBA via openpyxl
- For unpacked XML approach: `pack.py` preserves `vbaProject.bin` and adds the required content-type entry

## Data Analysis (pandas)

```python
import pandas as pd

# Read — uses cached values (same limitation as openpyxl data_only=True)
df = pd.read_excel("data.xlsx", sheet_name="Sheet1")

# Analysis
summary = df.describe()
pivot = df.pivot_table(values="Revenue", index="Region", aggfunc="sum")

# Write analysis results to a new sheet (preserves other sheets)
from openpyxl import load_workbook
wb = load_workbook("data.xlsx")
with pd.ExcelWriter("data.xlsx", engine="openpyxl", mode="a", if_sheet_exists="replace") as writer:
    writer.workbook = wb
    summary.to_excel(writer, sheet_name="Summary")
```

**pandas tips**:
- `sheet_name=None` reads all sheets into a dict
- `header=0` (default) uses first row as column names
- `dtype=str` prevents pandas from converting text-that-looks-like-numbers
- Use `mode="a"` with `if_sheet_exists="replace"` to add sheets without destroying existing ones

## Recalculating Formulas

After any formula modification, run:

```bash
python scripts/xlsx/recalc.py model.xlsx
```

**What it does**:
1. Opens the file in LibreOffice headless
2. Forces recalculation of all formulas
3. Saves the file (cached values updated)
4. Scans for formula errors (#REF!, #DIV/0!, #NAME?, #NULL!, #NUM!, #VALUE!, #N/A)
5. Returns JSON report

**Interpreting output**:
```json
{
  "file": "model.xlsx",
  "status": "success",
  "total_errors": 2,
  "errors": [
    {"sheet": "Model", "cell": "D5", "error": "#REF!", "formula": "=Sheet2!Z99"},
    {"sheet": "Model", "cell": "E3", "error": "#DIV/0!", "formula": "=B3/B4"}
  ]
}
```

- `total_errors: 0` = all formulas valid, file ready for delivery
- Any errors = fix the formula source, re-save, re-run recalc

## Formula Verification Checklist

After creating/editing a spreadsheet with formulas:

1. Run `recalc.py` — confirms zero errors
2. Spot-check: open with `data_only=True`, verify key totals match expectations
3. Check circular references: openpyxl raises `CircularReferenceError` on save if detected
4. Validate named ranges: `wb.defined_names` lists all; check none reference `#REF!`
5. Cross-sheet refs: verify target sheets exist before writing `=SheetName!Cell`

## Best Practices

**Library selection**:
- Create/edit structure and formulas → openpyxl
- Bulk data analysis → pandas
- Recalculation/verification → `recalc.py` (LibreOffice)
- Never mix openpyxl and pandas on the same open file handle

**openpyxl tips**:
- Use `ws.append([...])` for bulk row insertion (faster than cell-by-cell)
- Set `ws.freeze_panes = "A2"` to freeze header row
- Use `ws.auto_filter.ref = ws.dimensions` for filterable headers
- Named styles (`NamedStyle`) for reusable formatting

**Code style**:
- Keep Python minimal — the spreadsheet IS the deliverable
- Document which cells contain what with comments: `ws["B2"].comment = Comment("Annual growth rate", "Agent")`
- Group related operations (all formatting, then all data, then all formulas)

## Dependencies

```
openpyxl>=3.1.0
pandas>=2.0.0
msoffcrypto-tool>=5.0.0  # only for encrypted files
```

**System requirement**: LibreOffice (for recalc.py)
- Windows: `winget install TheDocumentFoundation.LibreOffice` or https://www.libreoffice.org/download/
- macOS: `brew install --cask libreoffice`
- Linux: `sudo apt install libreoffice-calc` (Debian/Ubuntu) or `sudo dnf install libreoffice-calc` (Fedora)
