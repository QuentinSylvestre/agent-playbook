"""Validate OOXML structure of an unpacked directory or archive.

Checks: required files, content types, relationship consistency,
and .rels file integrity.

Usage:
    python validate.py <path>    (directory or .docx/.pptx/.xlsx file)

Outputs JSON with validation results.
Exit codes: 0 = valid, 1 = invalid, 2 = usage error
"""
import json
import os
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile


def _get_dir(path):
    """If path is a ZIP, extract to temp dir and return (dir, True). Otherwise return (path, False)."""
    if os.path.isfile(path) and zipfile.is_zipfile(path):
        tmp = tempfile.mkdtemp(prefix="ooxml_validate_")
        with zipfile.ZipFile(path, "r") as zf:
            zf.extractall(tmp)
        return tmp, True
    return path, False


def _check_required_files(root_dir):
    """Check required OOXML root files exist."""
    errors = []
    if not os.path.isfile(os.path.join(root_dir, "[Content_Types].xml")):
        errors.append("Missing [Content_Types].xml")
    if not os.path.isfile(os.path.join(root_dir, "_rels", ".rels")):
        errors.append("Missing _rels/.rels")
    return errors


def _check_content_types(root_dir):
    """Validate [Content_Types].xml references."""
    errors = []
    ct_path = os.path.join(root_dir, "[Content_Types].xml")
    if not os.path.isfile(ct_path):
        return errors

    try:
        tree = ET.parse(ct_path)
        root = tree.getroot()
        ns = "http://schemas.openxmlformats.org/package/2006/content-types"
        for override in root.iter("{%s}Override" % ns):
            part_name = override.get("PartName", "")
            # PartName starts with / — strip it for filesystem check
            rel_path = part_name.lstrip("/").replace("/", os.sep)
            full_path = os.path.join(root_dir, rel_path)
            if not os.path.isfile(full_path):
                errors.append("Content type override references missing file: " + part_name)
    except ET.ParseError as e:
        errors.append("[Content_Types].xml parse error: " + str(e))
    return errors


def _check_rels(root_dir):
    """Validate .rels files — check that targets exist."""
    errors = []
    for dirpath, dirs, files in os.walk(root_dir):
        for fname in files:
            if not fname.endswith(".rels"):
                continue
            rels_path = os.path.join(dirpath, fname)
            try:
                tree = ET.parse(rels_path)
                root = tree.getroot()
                ns = "http://schemas.openxmlformats.org/package/2006/relationships"
                for rel in root.iter("{%s}Relationship" % ns):
                    target = rel.get("Target", "")
                    target_mode = rel.get("TargetMode", "")
                    # Skip external targets (URLs)
                    if target_mode == "External" or target.startswith("http"):
                        continue
                    # Resolve relative to the parent of _rels directory
                    rels_dir = os.path.dirname(rels_path)
                    if os.path.basename(rels_dir) == "_rels":
                        base_dir = os.path.dirname(rels_dir)
                    else:
                        base_dir = rels_dir
                    target_path = os.path.normpath(os.path.join(base_dir, target))
                    if not os.path.exists(target_path):
                        rel_rels = os.path.relpath(rels_path, root_dir).replace(os.sep, "/")
                        errors.append("Broken relationship in %s: target '%s' not found" % (rel_rels, target))
            except ET.ParseError as e:
                rel_rels = os.path.relpath(rels_path, root_dir).replace(os.sep, "/")
                errors.append("Parse error in %s: %s" % (rel_rels, str(e)))
    return errors


def validate(path):
    """Validate OOXML at path. Returns dict with results."""
    root_dir, is_temp = _get_dir(path)
    try:
        all_errors = []
        all_errors.extend(_check_required_files(root_dir))
        all_errors.extend(_check_content_types(root_dir))
        all_errors.extend(_check_rels(root_dir))
        return {"valid": len(all_errors) == 0, "errors": all_errors}
    finally:
        if is_temp:
            import shutil
            shutil.rmtree(root_dir, ignore_errors=True)


def main():
    if len(sys.argv) != 2:
        print("Usage: validate.py <path>", file=sys.stderr)
        sys.exit(2)

    path = sys.argv[1]
    if not os.path.exists(path):
        print("Error: path not found: " + path, file=sys.stderr)
        sys.exit(2)

    result = validate(path)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["valid"] else 1)


if __name__ == "__main__":
    main()
