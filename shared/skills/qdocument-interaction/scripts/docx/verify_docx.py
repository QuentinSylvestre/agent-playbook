"""Check a .docx with tracked changes before handing it to the user.

Checks, on a simulation of the document with all changes accepted:
  - deletion markup: no w:t / w:instrText inside w:del (text boxes excluded,
    Word keeps a deleted drawing's own runs), no w:delText / w:delInstrText
    outside w:del
  - cross-references: every REF field shows the number of the heading its
    bookmark sits on (numbered headings, REF \\n style)
  - headings whose outline number was removed (numId 0), which Word shows
    unnumbered and which shift every later REF
  - comments anchored inside a tracked deletion: Word hides them (the comments
    pane can stay empty) and deletes them on Accept All. Happens when tracked
    edits delete the content a comment sits on, e.g. a replaced picture
  - optional: Word opens the file without repair (Windows, Word, pywin32)

Heading levels come from styles.xml (internal names "heading 1".."heading 9"),
so localized style ids work. Heading numbers assume every heading level is
numbered, as in numbered setup guides.

Only word/document.xml is linted and checked. Headers, footers and their text
boxes are covered by --word alone.

Usage:
    python verify_docx.py <file.docx> [--word] [--accepted] [--outline]
                          [--fix-authors OUT.docx | --fix-comment-anchors OUT.docx]

--accepted has Word accept every revision on a temporary copy and repeats the
REF and heading checks there: the state the reader gets after review.

--fix-authors writes a copy where revision authors like "Name [2]" become
"Name" (Word adds the suffix when one name maps to several identities).

--fix-comment-anchors writes a copy where comment markers and references found
inside a tracked deletion are moved out of it (range starts before the
deletion, range ends and references after it), so the comments stay visible
and survive Accept All. The checks then run on that copy.

Outputs JSON. Exit codes: 0 = all checks pass, 1 = a check failed, 2 = usage error
"""
import json
import os
import re
import sys
import zipfile

DEL_RE = re.compile(r"<w:del\s[^>]*[^/]>.*?</w:del>", re.S)
TXBX_RE = re.compile(r"<w:txbxContent>.*?</w:txbxContent>", re.S)
PPRCHANGE_RE = re.compile(r"<w:pPrChange\s.*?</w:pPrChange>", re.S)
PARA_RE = re.compile(r"<w:p[ >].*?</w:p>", re.S)
TEXT_RE = re.compile(r"<w:t(?:\s[^>]*)?>([^<]*)</w:t>")
FIELD_TOKEN_RE = re.compile(
    r"<w:fldChar\b[^>]*w:fldCharType=\"(begin|separate|end)\"[^>]*/?>"
    r"|<w:instrText(?:\s[^>]*)?>([^<]*)</w:instrText>"
    r"|<w:t(?:\s[^>]*)?>([^<]*)</w:t>"
    r"|<w:fldSimple\b[^>]*w:instr=\"([^\"]*)\"[^>]*>(.*?)</w:fldSimple>", re.S)


def fields(paras):
    """Yield (paragraph index, field code, shown text) for every field.

    Walks begin/separate/end markers across paragraphs, so field codes split
    over several instrText runs (common when Word writes them) are joined.
    """
    stack = []
    for i, p in enumerate(paras):
        for m in FIELD_TOKEN_RE.finditer(p):
            kind, instr, text, simple_instr, simple_body = m.groups()
            if kind == "begin":
                stack.append({"para": i, "code": "", "shown": "", "in_result": False})
            elif kind == "separate" and stack:
                stack[-1]["in_result"] = True
            elif kind == "end" and stack:
                f = stack.pop()
                yield f["para"], f["code"].strip(), f["shown"]
            elif instr is not None and stack and not stack[-1]["in_result"]:
                stack[-1]["code"] += instr
            elif text is not None:
                for f in stack:
                    if f["in_result"]:
                        f["shown"] += text
            elif simple_instr is not None:
                yield i, simple_instr.strip(), "".join(TEXT_RE.findall(simple_body))
AUTHOR_SUFFIX_RE = re.compile(rb"(w:author=\"[^\"]*?) \[\d+\]\"")
COMMENT_MARK_RE = re.compile(r"<w:comment(?:RangeStart|RangeEnd|Reference) w:id=\"(\d+)\"\s*/>")
COMMENT_START_RE = re.compile(r"<w:commentRangeStart w:id=\"\d+\"\s*/>")
COMMENT_END_RE = re.compile(r"<w:commentRangeEnd w:id=\"\d+\"\s*/>")
COMMENT_REF_RUN_RE = re.compile(r"<w:r\b(?:(?!</w:r>).)*?<w:commentReference w:id=\"\d+\"\s*/>\s*</w:r>", re.S)
DEL_PARTS_RE = re.compile(r"(<w:del\s[^>]*[^/]>)(.*?)(</w:del>)", re.S)


def comments_in_deletion(doc):
    """Comment ids that Word hides or deletes on Accept All.

    A range marker or reference inside a tracked deletion, or a range that holds
    deleted content and nothing live.
    """
    ids = set()
    for d in DEL_RE.findall(doc):
        ids.update(COMMENT_MARK_RE.findall(d))
    for cid in set(re.findall(r"<w:commentRangeStart w:id=\"(\d+)\"", doc)):
        s = doc.find('<w:commentRangeStart w:id="%s"' % cid)
        e = doc.find('<w:commentRangeEnd w:id="%s"' % cid)
        if s < e and DEL_RE.search(doc[s:e]) and not _has_live(doc[s:e]):
            ids.add(cid)
    return sorted(ids, key=int)


def fix_comment_anchors_xml(doc):
    """Move comment markers and reference runs out of tracked deletions.

    Range starts go in front of the deletion; range ends and reference runs go
    right after it, in their original order. A deletion left with no run is dropped.
    Returns (new_xml, number_of_deletions_changed).
    """
    changed = 0
    tail_re = re.compile("%s|%s" % (COMMENT_END_RE.pattern, COMMENT_REF_RUN_RE.pattern), re.S)

    def move(m):
        nonlocal changed
        open_tag, inner, close_tag = m.groups()
        if not COMMENT_MARK_RE.search(inner):
            return m.group(0)
        changed += 1
        starts = "".join(COMMENT_START_RE.findall(inner))
        tail = "".join(p.group(0) for p in tail_re.finditer(inner))
        rest = inner
        for pat in (COMMENT_START_RE, COMMENT_END_RE, COMMENT_REF_RUN_RE):
            rest = pat.sub("", rest)
        kept = open_tag + rest + close_tag if "<w:r" in rest else ""
        return starts + kept + tail

    doc = DEL_PARTS_RE.sub(move, doc)
    return _cover_live_content(doc), changed


LIVE_ITEM_RE = re.compile(r"<w:ins\s[^>]*[^/]>.*?</w:ins>"
                          r"|<w:r\b(?:(?!</w:r>).)*?(?:<w:t[\s>]|<w:drawing>|<w:pict>)(?:(?!</w:r>).)*?</w:r>", re.S)


def _has_live(segment):
    return bool(LIVE_ITEM_RE.search(DEL_RE.sub("", segment)))


def _cover_live_content(doc):
    """Word deletes, on Accept All, a comment whose range holds only deleted content.

    For each comment whose range is all-deleted, move its end marker and reference run
    past the next live run or insertion of the same paragraph (the replacement content).
    """
    for cid in sorted(set(re.findall(r"<w:commentRangeStart w:id=\"(\d+)\"", doc)), key=int):
        start_tag = '<w:commentRangeStart w:id="%s"/>' % cid
        end_tag = '<w:commentRangeEnd w:id="%s"/>' % cid
        s, e = doc.find(start_tag), doc.find(end_tag)
        if s < 0 or e < s or _has_live(doc[s:e]):
            continue
        p_end = doc.find("</w:p>", e)
        ref_m = re.compile(r"<w:r\b(?:(?!</w:r>).)*?<w:commentReference w:id=\"%s\"\s*/>\s*</w:r>" % cid, re.S) \
            .search(doc, e, p_end)
        after = (ref_m.end() if ref_m else e + len(end_tag))
        nxt = None
        for m in LIVE_ITEM_RE.finditer(doc, after, p_end):
            if not any(d.start() <= m.start() < d.end() for d in DEL_RE.finditer(doc, after, p_end)):
                nxt = m
                break
        if nxt is None:
            continue
        moved = end_tag + (ref_m.group(0) if ref_m else "")
        insert_at = nxt.end()
        pieces = [(e, e + len(end_tag))] + ([(ref_m.start(), ref_m.end())] if ref_m else [])
        for a, b in sorted(pieces, reverse=True):
            doc = doc[:a] + doc[b:]
            if a < insert_at:
                insert_at -= b - a
        doc = doc[:insert_at] + moved + doc[insert_at:]
    return doc


def fix_comment_anchors(src, dst):
    zin = zipfile.ZipFile(src)
    n = 0
    with zipfile.ZipFile(dst, "w") as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename == "word/document.xml":
                text, n = fix_comment_anchors_xml(data.decode("utf-8"))
                data = text.encode("utf-8")
            zout.writestr(info, data, compress_type=info.compress_type)
    return n


def heading_levels(styles_xml):
    """Map styleId -> heading level (1-9) from the styles' internal names."""
    levels = {}
    for m in re.finditer(r"<w:style\b[^>]*w:styleId=\"([^\"]+)\"[^>]*>(.*?)</w:style>", styles_xml, re.S):
        name = re.search(r"<w:name w:val=\"([^\"]+)\"", m.group(2))
        hm = re.match(r"heading (\d)$", name.group(1), re.I) if name else None
        if hm:
            levels[m.group(1)] = int(hm.group(1))
    return levels


def text_of(p):
    return "".join(TEXT_RE.findall(p))


def mark_deleted(p):
    ppr = re.search(r"<w:pPr>.*?</w:pPr>", p, re.S)
    return bool(ppr and re.search(r"<w:rPr>.*?<w:del\s", ppr.group(0), re.S))


def check(path):
    z = zipfile.ZipFile(path)
    doc = z.read("word/document.xml").decode("utf-8")
    levels = heading_levels(z.read("word/styles.xml").decode("utf-8"))

    dels = [TXBX_RE.sub("", x) for x in DEL_RE.findall(doc)]
    accepted = DEL_RE.sub("", doc)
    lint = {
        "t_or_instrText_inside_del": sum(len(re.findall(r"<w:(?:t|instrText)[\s>]", x)) for x in dels),
        "delText_outside_del": len(re.findall(r"<w:del(?:Text|InstrText)[\s>]", accepted)),
    }

    body = accepted[accepted.index("<w:body>"):]
    body = PPRCHANGE_RE.sub("", TXBX_RE.sub("", body))
    paras = [p for p in PARA_RE.findall(body) if not (mark_deleted(p) and not text_of(p).strip())]

    num = [0] * 9
    headings, bookmark_at, unnumbered = {}, {}, []
    for i, p in enumerate(paras):
        sm = re.search(r"<w:pStyle w:val=\"([^\"]+)\"", p)
        lvl = levels.get(sm.group(1)) if sm else None
        if lvl and text_of(p).strip():
            ppr = re.search(r"<w:pPr>.*?</w:pPr>", p, re.S)
            if ppr and re.search(r"<w:numId w:val=\"0\"\s*/>", ppr.group(0)):
                # numbering removed on this heading (e.g. ListFormat.RemoveNumbers): Word shows no number
                unnumbered.append(text_of(p)[:60])
                headings[i] = ("", text_of(p))
                continue
            num[lvl - 1] += 1
            for k in range(lvl, 9):
                num[k] = 0
            headings[i] = (".".join(str(n) for n in num[:lvl]), text_of(p))
        for name in re.findall(r"<w:bookmarkStart [^>]*w:name=\"([^\"]+)\"", p):
            bookmark_at[name] = i

    def section(i):
        keys = [k for k in headings if k <= i]
        return headings[max(keys)] if keys else ("", "")

    refs = []
    for i, code, shown in fields(paras):
        parts = code.split()
        if len(parts) < 2 or parts[0].upper() != "REF":  # PAGEREF, NOTEREF, TOC... are other fields
            continue
        name = parts[1]
        target = section(bookmark_at[name]) if name in bookmark_at else ("?", "missing bookmark")
        refs.append({"in": section(i)[0], "bookmark": name, "shows": shown,
                     "target": target[0], "target_heading": target[1][:60],
                     "ok": shown == target[0]})

    authors = {}
    for a in re.findall(r"<w:(?:ins|del) [^>]*w:author=\"([^\"]+)\"", doc):
        authors[a] = authors.get(a, 0) + 1

    return {
        "file": os.path.abspath(path),
        "lint": lint,
        "ref_fields": len(refs),
        "ref_mismatches": [r for r in refs if not r["ok"]],
        "unnumbered_headings": unnumbered,
        "comments_in_deletion": comments_in_deletion(doc),
        "revision_authors": authors,
        "outline": [" ".join(h) for _, h in sorted(headings.items())],
    }


def word_opens(path):
    """True if Word opens the file read-only without a repair prompt."""
    import win32com.client
    w = win32com.client.DispatchEx("Word.Application")
    w.Visible = False
    w.DisplayAlerts = 0
    try:
        d = w.Documents.OpenNoRepairDialog(os.path.abspath(path), False, True, False)
        d.Close(0)
        return True
    except Exception:
        return False
    finally:
        w.Quit()


def accepted_copy(path):
    """Accept every revision on a temporary copy through Word; return its path.

    Checks the state the reader gets after review, including Word's own handling
    of deleted paragraph marks (a heading after a deleted paragraph displays with
    that paragraph's style until the deletion is accepted).
    """
    import tempfile
    import win32com.client
    tmp = os.path.join(tempfile.mkdtemp(prefix="verify_docx_"), "accepted.docx")
    w = win32com.client.DispatchEx("Word.Application")
    w.Visible = False
    w.DisplayAlerts = 0
    d = None
    try:
        d = w.Documents.Open(os.path.abspath(path), False, False, False)
        d.TrackRevisions = False
        d.Revisions.AcceptAll()
        d.SaveAs2(tmp, 12)
    finally:
        if d is not None:
            d.Close(0)
        w.Quit()
    return tmp


def fix_authors(src, dst):
    zin = zipfile.ZipFile(src)
    n = 0
    with zipfile.ZipFile(dst, "w") as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename.endswith(".xml"):
                data, k = AUTHOR_SUFFIX_RE.subn(rb"\1\"", data)
                data = re.sub(rb"(w15:author=\"[^\"]*?) \[\d+\]\"", rb"\1\"", data)
                n += k
            zout.writestr(info, data, compress_type=info.compress_type)
    return n


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Check a tracked-change .docx before delivery")
    parser.add_argument("docx")
    parser.add_argument("--word", action="store_true", help="also check that Word opens it without repair")
    parser.add_argument("--outline", action="store_true", help="include the heading outline in the output")
    parser.add_argument("--accepted", action="store_true",
                        help="also accept all revisions on a temp copy through Word and check that final state")
    fix = parser.add_mutually_exclusive_group()
    fix.add_argument("--fix-authors", metavar="OUT", help="write a copy with 'Name [N]' authors normalized")
    fix.add_argument("--fix-comment-anchors", metavar="OUT",
                     help="write a copy with comment markers moved out of tracked deletions")
    args = parser.parse_args()
    if not os.path.isfile(args.docx):
        print(json.dumps({"error": "file not found: %s" % args.docx}))
        sys.exit(2)

    target = args.docx
    renamed = moved = None
    if args.fix_authors:
        renamed = fix_authors(args.docx, args.fix_authors)
        target = args.fix_authors
    if args.fix_comment_anchors:
        moved = fix_comment_anchors(args.docx, args.fix_comment_anchors)
        target = args.fix_comment_anchors
    result = check(target)
    if renamed is not None:
        result["authors_normalized"] = renamed
    if moved is not None:
        result["comment_anchor_deletions_fixed"] = moved
    if not args.outline:
        result.pop("outline")
    if args.word:
        result["word_opens"] = word_opens(target)
    accepted_ok = True
    if args.accepted:
        acc = check(accepted_copy(target))
        result["accepted"] = {"ref_fields": acc["ref_fields"], "ref_mismatches": acc["ref_mismatches"],
                              "unnumbered_headings": acc["unnumbered_headings"]}
        if args.outline:
            result["accepted"]["outline"] = acc["outline"]
        accepted_ok = not acc["ref_mismatches"] and not acc["unnumbered_headings"]

    ok = (not any(result["lint"].values()) and not result["ref_mismatches"]
          and not result["unnumbered_headings"] and not result["comments_in_deletion"]
          and result.get("word_opens", True) and accepted_ok)
    result["ok"] = ok
    print(json.dumps(result, indent=2, ensure_ascii=False))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
