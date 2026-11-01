"""Repack a directory to an OOXML file (.docx, .pptx, .xlsx).

Validates basic structure and preserves vbaProject.bin for macro-enabled
formats (.docm, .pptm, .xlsm). All files are written as-is (raw bytes) —
no XML re-serialization — to preserve namespace prefixes and other XML
attributes that ET.tostring would silently corrupt.

Usage:
    python pack.py <input_dir> <output_file>

Exit codes: 0 = success, 1 = failure
"""
import os
import sys
import zipfile


# Files that must appear at the root of an OOXML package
REQUIRED_FILES = ["[Content_Types].xml"]


def _validate_structure(input_dir):
    """Check that required OOXML files exist."""
    errors = []
    for req in REQUIRED_FILES:
        if not os.path.isfile(os.path.join(input_dir, req)):
            errors.append("Missing required file: " + req)
    rels_path = os.path.join(input_dir, "_rels", ".rels")
    if not os.path.isfile(rels_path):
        errors.append("Missing required file: _rels/.rels")
    return errors


def _ensure_macro_content_type(input_dir):
    """Ensure vbaProject.bin content type is registered if the file exists.

    Uses string operations rather than ET.parse/ET.tostring to avoid
    namespace prefix corruption.
    """
    vba_paths = []
    for root, dirs, files in os.walk(input_dir):
        for f in files:
            if f == "vbaProject.bin":
                vba_paths.append(
                    os.path.relpath(os.path.join(root, f), input_dir).replace(os.sep, "/")
                )
    if not vba_paths:
        return

    ct_path = os.path.join(input_dir, "[Content_Types].xml")
    if not os.path.isfile(ct_path):
        return

    with open(ct_path, "r", encoding="utf-8") as f:
        ct_text = f.read()

    changed = False
    for vba_path in vba_paths:
        part_name = "/" + vba_path
        content_type = "application/vnd.ms-office.vbaProject"
        if part_name not in ct_text:
            override = f'<Override PartName="{part_name}" ContentType="{content_type}"/>'
            ct_text = ct_text.replace("</Types>", override + "\n</Types>")
            changed = True

    if changed:
        with open(ct_path, "w", encoding="utf-8") as f:
            f.write(ct_text)


def pack(input_dir, output_file):
    """Pack directory into OOXML ZIP.

    All files are written as raw bytes with no XML processing. This
    preserves namespace prefixes exactly as they appear on disk — the
    previous ET.tostring-based condensing step silently rewrote all
    namespace prefixes (w:, mc:, r: …) to ns0:, ns1:, ns2: …, producing
    documents Word refused to open.
    """
    errors = _validate_structure(input_dir)
    if errors:
        for e in errors:
            print("Error: " + e, file=sys.stderr)
        sys.exit(1)

    _ensure_macro_content_type(input_dir)

    with zipfile.ZipFile(output_file, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(input_dir):
            for fname in files:
                file_path = os.path.join(root, fname)
                arc_name = os.path.relpath(file_path, input_dir).replace(os.sep, "/")
                zf.write(file_path, arc_name)


def main():
    if len(sys.argv) != 3:
        print("Usage: pack.py <input_dir> <output_file>", file=sys.stderr)
        sys.exit(1)

    input_dir = sys.argv[1]
    output_file = sys.argv[2]

    if not os.path.isdir(input_dir):
        print("Error: input directory not found: " + input_dir, file=sys.stderr)
        sys.exit(1)

    pack(input_dir, output_file)


if __name__ == "__main__":
    main()
