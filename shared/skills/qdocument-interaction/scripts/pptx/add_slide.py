"""Add a slide to an unpacked .pptx presentation.

Duplicates an existing slide or creates a new one from a layout.

Usage:
    python add_slide.py <unpacked_dir> --duplicate <slide_number>
    python add_slide.py <unpacked_dir> --layout <layout_name>

Exit codes: 0 = success, 1 = failure
"""
import os
import re
import shutil
import sys
import xml.etree.ElementTree as ET

NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "ct": "http://schemas.openxmlformats.org/package/2006/content-types",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}

for prefix, uri in NS.items():
    ET.register_namespace(prefix, uri)


def _get_existing_slide_numbers(slides_dir):
    """Return sorted list of existing slide numbers."""
    nums = []
    for f in os.listdir(slides_dir):
        m = re.match(r"slide(\d+)\.xml$", f)
        if m:
            nums.append(int(m.group(1)))
    return sorted(nums)


def _next_slide_number(slides_dir):
    nums = _get_existing_slide_numbers(slides_dir)
    return (nums[-1] + 1) if nums else 1


def _update_presentation_xml(ppt_dir, new_slide_num, after_slide_num=None):
    """Add slide reference to presentation.xml."""
    pres_path = os.path.join(ppt_dir, "presentation.xml")
    tree = ET.parse(pres_path)
    root = tree.getroot()

    # Find or create sldIdLst
    sld_id_lst = root.find("p:sldIdLst", NS)
    if sld_id_lst is None:
        sld_id_lst = ET.SubElement(root, "{%s}sldIdLst" % NS["p"])

    # Determine next id
    existing_ids = [int(el.get("id", "0")) for el in sld_id_lst.findall("p:sldId", NS)]
    next_id = max(existing_ids, default=255) + 1

    # Add relationship to presentation.xml.rels
    rels_path = os.path.join(ppt_dir, "_rels", "presentation.xml.rels")
    rels_tree = ET.parse(rels_path)
    rels_root = rels_tree.getroot()
    existing_rids = [el.get("Id") for el in rels_root.findall("{%s}Relationship" % NS["rel"])]
    rid_nums = [int(r.replace("rId", "")) for r in existing_rids if r.startswith("rId")]
    new_rid = "rId%d" % (max(rid_nums, default=0) + 1)

    rel_el = ET.SubElement(rels_root, "{%s}Relationship" % NS["rel"])
    rel_el.set("Id", new_rid)
    rel_el.set("Type", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide")
    rel_el.set("Target", "slides/slide%d.xml" % new_slide_num)
    rels_tree.write(rels_path, xml_declaration=True, encoding="UTF-8")

    # Add sldId entry
    sld_id_el = ET.SubElement(sld_id_lst, "{%s}sldId" % NS["p"])
    sld_id_el.set("id", str(next_id))
    sld_id_el.set("{%s}id" % NS["r"], new_rid)
    tree.write(pres_path, xml_declaration=True, encoding="UTF-8")

    # Update [Content_Types].xml
    ct_path = os.path.join(os.path.dirname(ppt_dir), "[Content_Types].xml")
    if os.path.exists(ct_path):
        ct_tree = ET.parse(ct_path)
        ct_root = ct_tree.getroot()
        override = ET.SubElement(ct_root, "{%s}Override" % NS["ct"])
        override.set("PartName", "/ppt/slides/slide%d.xml" % new_slide_num)
        override.set("ContentType", "application/vnd.openxmlformats-officedocument.presentationml.slide+xml")
        ct_tree.write(ct_path, xml_declaration=True, encoding="UTF-8")


def duplicate_slide(unpacked_dir, slide_num):
    """Duplicate an existing slide."""
    ppt_dir = os.path.join(unpacked_dir, "ppt")
    slides_dir = os.path.join(ppt_dir, "slides")
    src_path = os.path.join(slides_dir, "slide%d.xml" % slide_num)

    if not os.path.isfile(src_path):
        print("Slide %d not found at %s" % (slide_num, src_path), file=sys.stderr)
        return 1

    new_num = _next_slide_number(slides_dir)
    dst_path = os.path.join(slides_dir, "slide%d.xml" % new_num)
    shutil.copy2(src_path, dst_path)

    # Copy rels file if it exists
    src_rels = os.path.join(slides_dir, "_rels", "slide%d.xml.rels" % slide_num)
    if os.path.isfile(src_rels):
        dst_rels_dir = os.path.join(slides_dir, "_rels")
        os.makedirs(dst_rels_dir, exist_ok=True)
        shutil.copy2(src_rels, os.path.join(dst_rels_dir, "slide%d.xml.rels" % new_num))

    _update_presentation_xml(ppt_dir, new_num, slide_num)
    print("Duplicated slide %d as slide %d" % (slide_num, new_num))
    return 0


def create_from_layout(unpacked_dir, layout_name):
    """Create a new slide from a slide layout."""
    ppt_dir = os.path.join(unpacked_dir, "ppt")
    slides_dir = os.path.join(ppt_dir, "slides")
    layouts_dir = os.path.join(ppt_dir, "slideLayouts")

    if not os.path.isdir(layouts_dir):
        print("No slideLayouts directory found", file=sys.stderr)
        return 1

    # Find layout by name attribute or filename
    target_layout = None
    for f in os.listdir(layouts_dir):
        if not f.endswith(".xml"):
            continue
        layout_path = os.path.join(layouts_dir, f)
        tree = ET.parse(layout_path)
        root = tree.getroot()
        cSld = root.find("p:cSld", NS)
        name = cSld.get("name", "") if cSld is not None else ""
        if name.lower() == layout_name.lower() or f.lower() == layout_name.lower():
            target_layout = f
            break

    if not target_layout:
        # List available layouts
        available = []
        for f in sorted(os.listdir(layouts_dir)):
            if f.endswith(".xml"):
                available.append(f)
        print("Layout '%s' not found. Available: %s" % (layout_name, ", ".join(available)), file=sys.stderr)
        return 1

    new_num = _next_slide_number(slides_dir)
    dst_path = os.path.join(slides_dir, "slide%d.xml" % new_num)

    # Create minimal slide XML referencing the layout
    slide_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<p:sld xmlns:a="%s" xmlns:r="%s" xmlns:p="%s">\n'
        '  <p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/>'
        '<p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/></p:spTree></p:cSld>\n'
        '</p:sld>' % (NS["a"], NS["r"], NS["p"])
    )
    with open(dst_path, "w", encoding="utf-8") as f:
        f.write(slide_xml)

    # Create rels file pointing to layout
    rels_dir = os.path.join(slides_dir, "_rels")
    os.makedirs(rels_dir, exist_ok=True)
    rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="%s">\n'
        '  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/%s"/>\n'
        '</Relationships>' % (NS["rel"], target_layout)
    )
    with open(os.path.join(rels_dir, "slide%d.xml.rels" % new_num), "w", encoding="utf-8") as f:
        f.write(rels_xml)

    _update_presentation_xml(ppt_dir, new_num)
    print("Created slide %d from layout '%s'" % (new_num, target_layout))
    return 0


def main():
    if len(sys.argv) < 4:
        print("Usage: add_slide.py <unpacked_dir> --duplicate <N> | --layout <name>", file=sys.stderr)
        sys.exit(1)

    unpacked_dir = sys.argv[1]
    if not os.path.isdir(unpacked_dir):
        print("Directory not found: %s" % unpacked_dir, file=sys.stderr)
        sys.exit(1)

    mode = sys.argv[2]
    arg = sys.argv[3]

    if mode == "--duplicate":
        try:
            slide_num = int(arg)
        except ValueError:
            print("Slide number must be an integer", file=sys.stderr)
            sys.exit(1)
        sys.exit(duplicate_slide(unpacked_dir, slide_num))
    elif mode == "--layout":
        sys.exit(create_from_layout(unpacked_dir, arg))
    else:
        print("Unknown mode: %s. Use --duplicate or --layout" % mode, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
