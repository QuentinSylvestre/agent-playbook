"""Add a comment to an unpacked .docx document.

Handles the boilerplate of updating both word/comments.xml and
word/document.xml with proper comment range markers and references.

Usage:
    python comment.py <unpacked_dir> --text "Comment text" --target "text to comment on"
                      [--author "Author Name"] [--initials "AN"]

The script searches word/document.xml for the target text and wraps it
with comment range markers. If the target is not found, the comment is
attached to the first paragraph.

Exit codes: 0 = success, 1 = failure
"""
import datetime
import os
import sys
import xml.etree.ElementTree as ET

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"

ET.register_namespace("w", W_NS)
ET.register_namespace("r", R_NS)


def _w(tag):
    return "{%s}%s" % (W_NS, tag)


def _get_next_comment_id(comments_path):
    """Get next available comment ID from comments.xml."""
    if not os.path.isfile(comments_path):
        return 1
    tree = ET.parse(comments_path)
    root = tree.getroot()
    max_id = 0
    for comment in root.iter(_w("comment")):
        cid = int(comment.get(_w("id"), "0"))
        if cid > max_id:
            max_id = cid
    return max_id + 1


def _ensure_comments_xml(unpacked_dir):
    """Create word/comments.xml if it doesn't exist, and register in relationships."""
    comments_path = os.path.join(unpacked_dir, "word", "comments.xml")
    if not os.path.isfile(comments_path):
        root = ET.Element(_w("comments"))
        tree = ET.ElementTree(root)
        os.makedirs(os.path.dirname(comments_path), exist_ok=True)
        tree.write(comments_path, encoding="UTF-8", xml_declaration=True)
        _register_comments_relationship(unpacked_dir)
        _register_comments_content_type(unpacked_dir)
    return comments_path


def _register_comments_relationship(unpacked_dir):
    """Add comments.xml to word/_rels/document.xml.rels if missing."""
    rels_path = os.path.join(unpacked_dir, "word", "_rels", "document.xml.rels")
    if not os.path.isfile(rels_path):
        return
    tree = ET.parse(rels_path)
    root = tree.getroot()
    ns = "http://schemas.openxmlformats.org/package/2006/relationships"
    ET.register_namespace("", ns)
    comment_type = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments"
    for rel in root:
        if rel.get("Type") == comment_type:
            return  # already registered
    # Find max rId
    max_id = 0
    for rel in root:
        rid = rel.get("Id", "")
        if rid.startswith("rId"):
            try:
                max_id = max(max_id, int(rid[3:]))
            except ValueError:
                pass
    new_id = "rId%d" % (max_id + 1)
    ET.SubElement(root, "Relationship", Id=new_id, Type=comment_type, Target="comments.xml")
    tree.write(rels_path, encoding="UTF-8", xml_declaration=True)


def _register_comments_content_type(unpacked_dir):
    """Add comments.xml override to [Content_Types].xml if missing."""
    ct_path = os.path.join(unpacked_dir, "[Content_Types].xml")
    if not os.path.isfile(ct_path):
        return
    tree = ET.parse(ct_path)
    root = tree.getroot()
    ET.register_namespace("", CT_NS)
    part_name = "/word/comments.xml"
    for override in root.iter("{%s}Override" % CT_NS):
        if override.get("PartName") == part_name:
            return
    ET.SubElement(root, "{%s}Override" % CT_NS, PartName=part_name,
                  ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml")
    tree.write(ct_path, encoding="UTF-8", xml_declaration=True)


def _add_comment_to_comments_xml(comments_path, comment_id, text, author, initials):
    """Add comment entry to word/comments.xml."""
    tree = ET.parse(comments_path)
    root = tree.getroot()
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    comment_el = ET.SubElement(root, _w("comment"))
    comment_el.set(_w("id"), str(comment_id))
    comment_el.set(_w("author"), author)
    comment_el.set(_w("date"), now)
    comment_el.set(_w("initials"), initials)
    para = ET.SubElement(comment_el, _w("p"))
    run = ET.SubElement(para, _w("r"))
    t = ET.SubElement(run, _w("t"))
    t.text = text
    tree.write(comments_path, encoding="UTF-8", xml_declaration=True)


def _add_comment_markers_to_document(unpacked_dir, comment_id, target_text):
    """Add commentRangeStart, commentRangeEnd, and commentReference to document.xml."""
    doc_path = os.path.join(unpacked_dir, "word", "document.xml")
    tree = ET.parse(doc_path)
    root = tree.getroot()

    # Find paragraph containing target text
    target_para = None
    for para in root.iter(_w("p")):
        para_text = ""
        for t in para.iter(_w("t")):
            if t.text:
                para_text += t.text
        if target_text and target_text in para_text:
            target_para = para
            break

    # Fallback: first paragraph with text
    if target_para is None:
        for para in root.iter(_w("p")):
            if any(t.text for t in para.iter(_w("t")) if t.text):
                target_para = para
                break

    if target_para is None:
        print("Error: no text content found in document", file=sys.stderr)
        sys.exit(1)

    # Insert commentRangeStart before first run
    range_start = ET.Element(_w("commentRangeStart"))
    range_start.set(_w("id"), str(comment_id))

    range_end = ET.Element(_w("commentRangeEnd"))
    range_end.set(_w("id"), str(comment_id))

    ref_run = ET.Element(_w("r"))
    ref_rpr = ET.SubElement(ref_run, _w("rPr"))
    ET.SubElement(ref_rpr, _w("rStyle"), {_w("val"): "CommentReference"})
    ET.SubElement(ref_run, _w("commentReference"), {_w("id"): str(comment_id)})

    # Find insertion points
    children = list(target_para)
    first_run_idx = None
    last_run_idx = None
    for i, child in enumerate(children):
        if child.tag == _w("r"):
            if first_run_idx is None:
                first_run_idx = i
            last_run_idx = i

    if first_run_idx is not None:
        target_para.insert(first_run_idx, range_start)
        # Indices shifted by 1
        target_para.insert(last_run_idx + 2, range_end)
        target_para.insert(last_run_idx + 3, ref_run)
    else:
        target_para.append(range_start)
        target_para.append(range_end)
        target_para.append(ref_run)

    tree.write(doc_path, encoding="UTF-8", xml_declaration=True)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Add a comment to unpacked .docx XML")
    parser.add_argument("unpacked_dir", help="Path to unpacked .docx directory")
    parser.add_argument("--text", required=True, help="Comment text")
    parser.add_argument("--target", default="", help="Text string to attach comment to")
    parser.add_argument("--author", default="Agent", help="Comment author name")
    parser.add_argument("--initials", default="A", help="Author initials")
    args = parser.parse_args()

    if not os.path.isdir(args.unpacked_dir):
        print("Error: directory not found: " + args.unpacked_dir, file=sys.stderr)
        sys.exit(1)

    doc_path = os.path.join(args.unpacked_dir, "word", "document.xml")
    if not os.path.isfile(doc_path):
        print("Error: word/document.xml not found in " + args.unpacked_dir, file=sys.stderr)
        sys.exit(1)

    comments_path = _ensure_comments_xml(args.unpacked_dir)
    comment_id = _get_next_comment_id(comments_path)
    _add_comment_to_comments_xml(comments_path, comment_id, args.text, args.author, args.initials)
    _add_comment_markers_to_document(args.unpacked_dir, comment_id, args.target)


if __name__ == "__main__":
    main()
