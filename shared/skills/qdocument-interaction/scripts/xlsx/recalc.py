"""Recalculate xlsx formulas via LibreOffice headless macro and scan for errors.

Opens the file in LibreOffice with a Basic macro that calls calculateAll(),
saves (updating cached values), then scans all cells for formula errors.

Usage:
    python recalc.py <input.xlsx> [--output <output.xlsx>]

Exit codes: 0 = success (even if errors found), 1 = failure, 2 = LibreOffice not found
Stdout: JSON report with error locations
Stderr: human-readable error messages
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

# Resolve soffice.py from sibling directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "office"))
from soffice import find_soffice


FORMULA_ERRORS = {"#REF!", "#DIV/0!", "#NAME?", "#NULL!", "#NUM!", "#VALUE!", "#N/A"}


def _path_to_url(path):
    import pathlib
    return pathlib.Path(path).as_uri()


def _write_recalc_macro(basic_dir, file_url, save_url):
    """Write a Basic macro that opens, recalculates all, saves, closes."""
    module_dir = os.path.join(basic_dir, "Standard")
    os.makedirs(module_dir, exist_ok=True)

    macro_code = f'''\
Sub RecalcAll()
    Dim sUrl As String
    Dim oDoc As Object
    Dim aArgs(0) As New com.sun.star.beans.PropertyValue

    sUrl = "{file_url}"
    aArgs(0).Name = "Hidden"
    aArgs(0).Value = True

    oDoc = StarDesktop.loadComponentFromURL(sUrl, "_blank", 0, aArgs())
    If IsNull(oDoc) Or IsEmpty(oDoc) Then
        Exit Sub
    End If

    ' Force full recalculation of all formulas
    oDoc.calculateAll()

    Dim aSaveArgs(0) As New com.sun.star.beans.PropertyValue
    aSaveArgs(0).Name = "FilterName"
    aSaveArgs(0).Value = "Calc MS Excel 2007 XML"

    oDoc.storeToURL("{save_url}", aSaveArgs())
    oDoc.close(True)
End Sub
'''
    macro_path = os.path.join(module_dir, "Recalc.xba")
    with open(macro_path, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write('<!DOCTYPE script:module PUBLIC "-//OpenOffice.org//DTD OfficeDocument 1.0//EN" "module.dtd">\n')
        f.write('<script:module xmlns:script="http://openoffice.org/2000/script" ')
        f.write('script:name="Recalc" script:language="StarBasic">\n')
        f.write(macro_code)
        f.write('</script:module>\n')

    xlb_path = os.path.join(module_dir, "script.xlb")
    xlb_content = '''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE library:library PUBLIC "-//OpenOffice.org//DTD OfficeDocument 1.0//EN" "library.dtd">
<library:library xmlns:library="http://openoffice.org/2000/library" library:name="Standard" library:readonly="false" library:passwordprotected="false">
 <library:element library:name="Recalc"/>
</library:library>
'''
    with open(xlb_path, "w", encoding="utf-8") as f:
        f.write(xlb_content)


def recalculate(input_path, output_path, soffice_path):
    """Open file in LibreOffice, call calculateAll(), save."""
    tmpdir = tempfile.mkdtemp(prefix="recalc_")
    try:
        user_profile = os.path.join(tmpdir, "user")
        basic_dir = os.path.join(user_profile, "basic")
        os.makedirs(basic_dir, exist_ok=True)

        file_url = _path_to_url(input_path)
        save_url = _path_to_url(output_path)

        _write_recalc_macro(basic_dir, file_url, save_url)

        env = os.environ.copy()
        env["HOME"] = tmpdir

        cmd = [
            soffice_path, "--headless", "--norestore", "--nofirststartwizard",
            "-env:UserInstallation=" + _path_to_url(user_profile),
            "macro:///Standard.Recalc.RecalcAll"
        ]

        result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            print("LibreOffice macro error: " + result.stderr, file=sys.stderr)
            return False

        if not os.path.isfile(output_path):
            print("Recalculated file not created", file=sys.stderr)
            return False

        return True
    except subprocess.TimeoutExpired:
        print("LibreOffice timed out after 120s", file=sys.stderr)
        return False
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def scan_errors(filepath):
    """Scan all cells for formula errors. Returns list of error dicts."""
    try:
        from openpyxl import load_workbook
    except ImportError:
        print("openpyxl not installed. pip install openpyxl>=3.1.0", file=sys.stderr)
        sys.exit(1)

    errors = []
    wb = load_workbook(filepath, data_only=True)
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        for row in ws.iter_rows():
            for cell in row:
                if isinstance(cell.value, str) and cell.value in FORMULA_ERRORS:
                    errors.append({
                        "sheet": sheet_name,
                        "cell": cell.coordinate,
                        "error": cell.value
                    })
    wb.close()

    if errors:
        wb_formulas = load_workbook(filepath, data_only=False)
        for err in errors:
            ws = wb_formulas[err["sheet"]]
            formula_val = ws[err["cell"]].value
            err["formula"] = str(formula_val) if formula_val else ""
        wb_formulas.close()

    return errors


def main():
    if len(sys.argv) < 2:
        print("Usage: recalc.py <input.xlsx> [--output <output.xlsx>]", file=sys.stderr)
        sys.exit(1)

    input_path = os.path.abspath(sys.argv[1])
    output_path = input_path
    if "--output" in sys.argv:
        idx = sys.argv.index("--output")
        if idx + 1 < len(sys.argv):
            output_path = os.path.abspath(sys.argv[idx + 1])

    if not os.path.isfile(input_path):
        print("File not found: " + input_path, file=sys.stderr)
        sys.exit(1)

    soffice_path = find_soffice()
    if not soffice_path:
        print("LibreOffice not found. Install from https://www.libreoffice.org/download/", file=sys.stderr)
        sys.exit(2)

    # If output differs from input, work on a copy
    if output_path != input_path:
        shutil.copy2(input_path, output_path)

    if not recalculate(input_path, output_path, soffice_path):
        sys.exit(1)

    errors = scan_errors(output_path)
    total_formulas = 0
    try:
        from openpyxl import load_workbook
        wb = load_workbook(output_path, data_only=False)
        for ws in wb:
            for row in ws.iter_rows():
                for cell in row:
                    if isinstance(cell.value, str) and cell.value.startswith("="):
                        total_formulas += 1
        wb.close()
    except Exception:
        pass

    report = {
        "status": "errors_found" if errors else "success",
        "total_errors": len(errors),
        "total_formulas": total_formulas,
        "error_summary": {}
    }
    if errors:
        for err in errors:
            key = err["error"]
            if key not in report["error_summary"]:
                report["error_summary"][key] = {"count": 0, "locations": []}
            report["error_summary"][key]["count"] += 1
            report["error_summary"][key]["locations"].append(
                f"{err['sheet']}!{err['cell']}"
            )

    print(json.dumps(report, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
