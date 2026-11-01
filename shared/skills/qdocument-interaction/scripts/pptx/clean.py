"""Remove orphaned files from an unpacked .pptx presentation.

Removes slides not referenced in presentation.xml and media files not
referenced by any slide's .rels file.

Usage:
    python clean.py <unpacked_dir> [--dry-run]

Exit codes: 0 = success, 1 = failure
"""
import os
import re
import sys
import xml.etree.ElementTree as ET

NS = {
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}


def _get_referenced_slides(ppt_dir):
    """Get slide filenames referenced in presentation.xml via rels."""
    rels_path = os.path.join(ppt_dir, "_rels", "presentation.xml.rels")
    if not os.path.isfile(rels_path):
        return set()
    tree = ET.parse(rels_path)
    root = tree.getroot()
    referenced = set()
    for rel in root.findall("{%s}Relationship" % NS["rel"]):
        target = rel.get("Target", "")
        if "slides/slide" in target:
            referenced.add(os.path.basename(target))
    return referenced


def _get_referenced_media(ppt_dir):
    """Get media filenames referenced by any slide or layout rels."""
    media_refs = set()
    # Check all .rels files under ppt/
    for dirpath, _, filenames in os.walk(ppt_dir):
        for f in filenames:
            if f.endswith(".rels"):
                rels_path = os.path.join(dirpath, f)
                try:
                    tree = ET.parse(rels_path)
                    for rel in tree.getroot().findall("{%s}Relationship" % NS["rel"]):
                        target = rel.get("Target", "")
                        if "../media/" in target or "media/" in target:
                            media_refs.add(os.path.basename(target))
                except ET.ParseError:
                    continue
    return media_refs


def clean(unpacked_dir, dry_run=False):
    """Remove orphaned slides and media."""
    ppt_dir = os.path.join(unpacked_dir, "ppt")
    slides_dir = os.path.join(ppt_dir, "slides")
    media_dir = os.path.join(ppt_dir, "media")

    if not os.path.isdir(ppt_dir):
        print("Not a valid unpacked pptx: %s" % unpacked_dir, file=sys.stderr)
        return 1

    removed = []

    # Clean orphaned slides
    if os.path.isdir(slides_dir):
        referenced_slides = _get_referenced_slides(ppt_dir)
        for f in os.listdir(slides_dir):
            if re.match(r"slide\d+\.xml$", f) and f not in referenced_slides:
                path = os.path.join(slides_dir, f)
                if dry_run:
                    print("[dry-run] Would remove: %s" % path)
                else:
                    os.remove(path)
                removed.append("slides/" + f)
                # Also remove its rels
                rels_path = os.path.join(slides_dir, "_rels", f + ".rels")
                if os.path.isfile(rels_path):
                    if not dry_run:
                        os.remove(rels_path)
                    removed.append("slides/_rels/" + f + ".rels")

    # Clean orphaned media
    if os.path.isdir(media_dir):
        referenced_media = _get_referenced_media(ppt_dir)
        for f in os.listdir(media_dir):
            if f not in referenced_media:
                path = os.path.join(media_dir, f)
                if dry_run:
                    print("[dry-run] Would remove: %s" % path)
                else:
                    os.remove(path)
                removed.append("media/" + f)

    if removed:
        action = "Would remove" if dry_run else "Removed"
        print("%s %d orphaned file(s): %s" % (action, len(removed), ", ".join(removed)))
    else:
        print("No orphaned files found.")
    return 0


def main():
    if len(sys.argv) < 2:
        print("Usage: clean.py <unpacked_dir> [--dry-run]", file=sys.stderr)
        sys.exit(1)

    unpacked_dir = sys.argv[1]
    dry_run = "--dry-run" in sys.argv

    if not os.path.isdir(unpacked_dir):
        print("Directory not found: %s" % unpacked_dir, file=sys.stderr)
        sys.exit(1)

    sys.exit(clean(unpacked_dir, dry_run))


if __name__ == "__main__":
    main()
