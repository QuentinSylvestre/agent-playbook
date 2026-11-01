"""End-to-end test of word_com.py, verify_docx.py, docx_media.py, docx_mentions.py and safe_replace.py.

Builds a small fixture document through Word at runtime (numbered headings, a
TOC, a REF cross-reference, a paragraph with an interleaved tracked change, a
footer text box showing a DOCPROPERTY, an inline picture with a comment), edits it with
WordSession, then checks the result. Needs Windows, Word, pywin32 and Pillow.

Usage:
    python -u tests/test_word_com.py

Takes about a minute. Work files go to a fresh temporary folder, removed at the
end unless --keep is given.

Exit codes: 0 = all checks pass, 1 = a check failed
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)

from word_com import WordSession, H1, H2, NORMAL, lock_file  # noqa: E402
from verify_docx import check, word_opens  # noqa: E402

FAILURES = []


def expect(cond, what):
    print(("PASS  " if cond else "FAIL  ") + what, flush=True)
    if not cond:
        FAILURES.append(what)


def make_png(path, label, color):
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (800, 400), color)
    d = ImageDraw.Draw(im)
    d.rectangle((40, 40, 760, 360), outline=(0, 0, 0), width=6)
    d.text((80, 180), label, fill=(0, 0, 0))
    im.save(path)


def build_fixture(path, png):
    """Create the fixture with Word, tracking off except for one interleaved change."""
    import win32com.client
    w = win32com.client.DispatchEx("Word.Application")
    w.Visible = False
    w.DisplayAlerts = 0
    d = None
    try:
        d = w.Documents.Add()
        paras = [(NORMAL, "Fixture guide"), (NORMAL, "TOC-HERE"),
                 (H1, "Alpha"), (NORMAL, "Alpha body text."),
                 (H2, "Alpha one"), (NORMAL, "Alpha one body."),
                 (H1, "Beta"), (NORMAL, "Beta body refers to section "),
                 (NORMAL, "Stale value 2020."),
                 (H1, "Gamma"), (NORMAL, "Gamma body."), (NORMAL, "Paragraph to delete."),
                 (H1, "Appendix"), (NORMAL, "End.")]
        r = d.Content
        r.Text = "\r".join(t for _, t in paras)
        for i, (style, _) in enumerate(paras, 1):
            d.Paragraphs(i).Style = d.Styles(style)
        # Outline numbering linked to Heading 1/2: "1", "1.1"
        lt = d.ListTemplates.Add(True)
        for lvl, fmt, sid in ((1, "%1", H1), (2, "%1.%2", H2)):
            ll = lt.ListLevels(lvl)
            ll.NumberFormat = fmt
            ll.NumberStyle = 0
            ll.LinkedStyle = d.Styles(sid).NameLocal
        d.Bookmarks.Add("_Ref100", d.Paragraphs(5).Range)
        beta_body = d.Paragraphs(8).Range
        d.Fields.Add(d.Range(beta_body.End - 1, beta_body.End - 1), -1, "REF _Ref100 \\n \\h", False)
        toc_p = d.Paragraphs(2).Range
        toc_p.Text = ""
        d.TablesOfContents.Add(d.Range(toc_p.Start, toc_p.Start), True, 1, 2)
        d.CustomDocumentProperties.Add("Doc version", False, 4, "v1.0")
        footer = d.Sections(1).Footers(1)
        footer.Range.Text = "stale footer text"
        box = footer.Shapes.AddTextbox(1, 72, 20, 300, 24)
        box.TextFrame.TextRange.Text = "rev: "
        at = box.TextFrame.TextRange.Duplicate
        if at.Text.endswith("\r"):
            at.MoveEnd(1, -1)
        at.Collapse(0)  # Fields.Add replaces a non-empty range, so insert at a collapsed position
        d.Fields.Add(at, -1, 'DOCPROPERTY "Doc version"', False)
        gamma_body = None
        for p in d.Paragraphs:
            if p.Range.Text.startswith("Gamma body"):
                gamma_body = p
        pic_p = gamma_body.Range
        pic_p.InsertParagraphAfter()
        target = gamma_body.Next(1).Range
        pic = d.InlineShapes.AddPicture(png, False, True, d.Range(target.Start, target.Start))
        d.Comments.Add(pic.Range, "Comment on the picture")
        for f in d.Fields:
            f.Update()
        d.TablesOfContents(1).Update()
        # Interleaved tracked change, like an earlier tool's del/ins in one paragraph
        d.TrackRevisions = True
        rr = d.Content
        if rr.Find.Execute("2020", True, False, False, False, False, True, 0, False):
            rr.Text = "2021"
        d.TrackRevisions = False
        d.SaveAs2(path, 12)
    finally:
        if d is not None:
            d.Close(0)
        w.Quit()


def xml(path, name):
    with zipfile.ZipFile(path) as z:
        return z.read(name).decode("utf-8")


def comments_after_accept_all(path):
    """Number of comments left once Word accepts every revision (on a copy)."""
    import win32com.client
    tmp = path + ".accept.docx"
    shutil.copyfile(path, tmp)
    w = win32com.client.DispatchEx("Word.Application")
    w.Visible = False
    w.DisplayAlerts = 0
    d = None
    try:
        d = w.Documents.Open(tmp, False, False, False)
        d.TrackRevisions = False
        d.Revisions.AcceptAll()
        return d.Comments.Count
    finally:
        if d is not None:
            d.Close(0)
        w.Quit()


def main():
    keep = "--keep" in sys.argv
    # verify_docx field parser: instruction split over two runs, PAGEREF not taken for REF
    from verify_docx import fields
    split = ('<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText> REF </w:instrText></w:r>'
             '<w:r><w:instrText>_Ref1 \\n \\h </w:instrText></w:r><w:r><w:fldChar w:fldCharType="separate"/></w:r>'
             '<w:r><w:t>2.1</w:t></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>')
    expect(list(fields([split])) == [(0, "REF _Ref1 \\n \\h", "2.1")], "field code split over runs is joined")
    work = tempfile.mkdtemp(prefix="word_com_test_")
    print("work folder: %s" % work, flush=True)
    try:
        png1, png2, png1_edit, png3 = (os.path.join(work, n) for n in
                                       ("pic1.png", "pic2.png", "pic1_edit.png", "pic3.png"))
        make_png(png1, "original picture", (200, 220, 240))
        make_png(png2, "second picture", (240, 220, 200))
        make_png(png1_edit, "edited picture", (200, 220, 240))
        make_png(png3, "replacement picture", (220, 240, 200))
        fixture = os.path.join(work, "fixture.docx")
        build_fixture(fixture, png1)
        expect(os.path.isfile(fixture), "fixture built")
        base = check(fixture)
        expect(base["ref_fields"] == 1 and not base["ref_mismatches"], "fixture REF field resolves to 1.1")

        out = os.path.join(work, "edited.docx")
        with WordSession(fixture, out, log=lambda m: print("      " + m, flush=True)) as ws:
            tpl = ws.template(["Alpha body text."])
            # 0. edit before the TOC: default searches must still start after it
            before = ws.body_start
            ws.replace("Fixture guide", "Fixture guide with a much longer title that shifts positions", start=0)
            expect(ws.body_start > before, "body_start follows edits made before the TOC")
            # 1. plain tracked replacement
            ws.replace("Gamma body.", "Gamma body, edited.")
            # 2. deletion guard: text that only exists as a tracked deletion is skipped by default
            try:
                ws.find("2020")
                skipped = False
            except LookupError:
                skipped = True
            expect(skipped, "find skips text inside a tracked deletion")
            expect(ws.find("2020", guard=False) is not None, "find(guard=False) still reaches deleted text")
            ws.set_text(ws.para("2021", guard=False), "Current value 2026.")
            # 3. insert in front of a heading that carries the REF bookmark
            ws.insert_before(ws.para("Alpha one", level=2), tpl, "Paragraph before Alpha one.")
            # 4. new numbered heading shifts later numbers
            ws.insert_before(ws.para("Beta", level=1), tpl, "Inserted chapter", style=H1)
            # 5. table in front of a heading keeps Normal cells and gets borders; a second one
            #    cloned from it keeps its look with a different row count
            t1 = ws.add_table(ws.para("Appendix", level=1), [["Key", "Value"], ["a", "1"]], tpl)
            expect(t1.Borders.OutsideLineStyle == 1, "default table has single borders")
            with ws.untracked():
                t1.Rows(1).Shading.BackgroundPatternColor = 0xC47244
            t2 = ws.add_table(ws.para("Gamma", level=1), [["K", "V"], ["b", "2"], ["c", "3"]], tpl, model=t1)
            expect(t2.Rows.Count == 3 and t2.Borders.OutsideLineStyle == 1, "cloned table: 3 rows, borders kept")
            expect(t2.Rows(1).Shading.BackgroundPatternColor == 0xC47244, "cloned table keeps header shading")
            expect(t2.Cell(3, 1).Range.Text.startswith("c"), "cloned table filled")
            try:
                ws.add_table(ws.para("Gamma", level=1), [["only one column"]], tpl, model=t1)
                refused = False
            except ValueError:
                refused = True
            expect(refused, "model with another column count is refused")
            # 6. picture after a paragraph
            ws.insert_picture_after(ws.para("Gamma body, edited."), png2, tpl)
            # 7. delete a paragraph
            ws.delete_para(ws.para("Paragraph to delete."), "test")
            # 8. header/footer: property, fields in text boxes, stale text
            ws.set_property("Doc version", "v2.0")
            ws.refresh_header_footer_fields()
            expect(ws.replace_in_header_footer("stale footer text", "") == 1, "stale footer text found once")
            labels = [lab for lab, _ in ws.header_footer_ranges()]
            expect(any(lab.startswith("text box") for lab in labels), "footer text box enumerated")
            # 9. new bookmark + REF field
            ws.bookmark("_Ref200", ws.para("Gamma", level=1))
            gp = ws.para("Gamma body, edited.")
            ws.add_ref(gp.Range.End - 1, "_Ref200")
            # 10. insert after the last paragraph of the document
            ws.insert_after(ws.para("End."), tpl, "Appended last paragraph.")
            # 11. replace_all
            expect(ws.replace_all("body", "BODY") >= 3, "replace_all replaced every live occurrence")
            # 12. reply to a comment, then replace the commented picture
            ws.reply("Comment on the picture", "@Fixture Person please check")
            expect(ws.doc.Comments.Count == 2, "reply added as a second comment")
            pic_p = ws.para_at(ws.doc.Comments(1).Scope.Start)
            expect(ws.replace_picture(pic_p, png3) >= 1, "replace_picture reports the comment on the picture")
        expect(os.path.isfile(out), "edited document saved")

        res = check(out)
        expect(not any(res["lint"].values()), "deletion markup lint clean")
        expect(res["ref_fields"] == 2 and not res["ref_mismatches"],
               "REFs resolve: 'Alpha one' after inserting in front of it, new REF to Gamma (%s)"
               % res["ref_mismatches"])
        doc_xml = xml(out, "word/document.xml")
        expect("Appended last paragraph." in doc_xml, "insert_after works on the last paragraph")
        expect(not res["unnumbered_headings"], "inserted headings keep their outline number (%s)"
               % res["unnumbered_headings"])
        expect("<w:ins " in doc_xml and "<w:del " in doc_xml, "edits are tracked revisions")
        heads = [h for h in res["outline"]]
        expect("3 Beta" in " | ".join(heads), "new chapter renumbers Beta to 3 (%s)" % heads)
        tables = re.findall(r"<w:tbl>.*?</w:tbl>", doc_xml, re.S)
        expect(tables and "Heading" not in re.sub(r"<w:pPrChange .*?</w:pPrChange>", "", tables[-1], flags=re.S),
               "table cells are not heading-styled")
        expect(len(tables) == 2 and all(re.search(r'<w:tblBorders>.*?w:val="single"', t, re.S) for t in tables),
               "both saved tables carry single borders (%d tables)" % len(tables))
        footer_xml = "".join(xml(out, n) for n in zipfile.ZipFile(out).namelist()
                             if re.match(r"word/footer\d+\.xml", n))
        live_footer = re.sub(r"<w:del\s[^>]*[^/]>.*?</w:del>", "", footer_xml, flags=re.S)
        footer_text = "".join(re.findall(r"<w:t(?:\s[^>]*)?>([^<]*)<", live_footer))
        expect("v2.0" in footer_text, "footer text box shows the new property value")
        expect("stale footer text" not in footer_text, "stale footer text deleted")
        expect("v2.0" in xml(out, "docProps/custom.xml"), "custom property updated")
        expect(word_opens(out), "Word opens the edited document without repair")

        # comments on replaced content: re-anchor, and both comments survive Accept All
        print("      comments flagged before the fix: %s" % res["comments_in_deletion"], flush=True)
        fixed = os.path.join(work, "fixed.docx")
        rc = subprocess.call([sys.executable, os.path.join(SCRIPTS, "verify_docx.py"), out, "--accepted",
                              "--fix-comment-anchors", fixed], stdout=subprocess.DEVNULL)
        expect(rc == 0, "verify_docx --accepted --fix-comment-anchors passes on the edited document")
        expect(not check(fixed)["comments_in_deletion"], "no comment left inside a deletion")
        expect(comments_after_accept_all(fixed) == 2, "comment and reply survive Accept All")
        from verify_docx import comments_in_deletion
        bad = ('<w:p><w:commentRangeStart w:id="5"/><w:del w:id="1" w:author="a"><w:r><w:delText>x</w:delText></w:r>'
               '<w:commentRangeEnd w:id="5"/><w:r><w:commentReference w:id="5"/></w:r></w:del></w:p>')
        expect(comments_in_deletion(bad) == ["5"], "detector flags a comment anchored in a deletion")

        # docx_mentions: plain "@Name" -> real mention, email never guessed
        import docx_mentions
        people_xml = ('<w15:person w15:author="Ann Example"><w15:presenceInfo w15:providerId="AD" '
                      'w15:userId="S::ann@example.com::00000000-0000-0000-0000-000000000000"/></w15:person>')
        expect(docx_mentions.PRESENCE_RE.findall(people_xml) == [("Ann Example", "ann@example.com")],
               "people.xml presence entry parsed")
        mentioned = os.path.join(work, "mentioned.docx")
        mt = [sys.executable, os.path.join(SCRIPTS, "docx_mentions.py"), "mention", fixed, mentioned]
        expect(subprocess.call(mt + ["--person", "Fixture Person"], stdout=subprocess.DEVNULL) == 1,
               "docx_mentions refuses a person without a known email")
        expect(subprocess.call(mt + ["--person", "Fixture Person=fixture.person@example.com"],
                               stdout=subprocess.DEVNULL) == 0, "docx_mentions converts the mention")
        cx = xml(mentioned, "word/comments.xml")
        expect('HYPERLINK "mailto:fixture.person@example.com"' in cx and 'w:name="_@_' in cx
               and 'w:val="Mention"' in cx, "mention has the mailto field, _@_ bookmark and Mention style")
        expect('w:styleId="Mention"' in xml(mentioned, "word/styles.xml"), "Mention style present")
        expect(word_opens(mentioned), "Word opens the document with the mention")

        # docx_media: swap the first picture for its edited version
        swapped = os.path.join(work, "swapped.docx")
        rc = subprocess.call([sys.executable, os.path.join(SCRIPTS, "docx_media.py"), "swap", out, swapped,
                              "--map", "%s=%s" % (png1, png1_edit)])
        expect(rc == 0 and os.path.isfile(swapped), "docx_media swap matched exactly one image")
        rc = subprocess.call([sys.executable, os.path.join(SCRIPTS, "docx_media.py"), "swap", out,
                              os.path.join(work, "never.docx"),
                              "--map", "%s=%s" % (os.path.join(work, "pic2.png"), png1_edit),
                              "--map", "%s=%s" % (png1, png1_edit)])
        expect(rc == 0, "docx_media swap handles two maps")
        expect(word_opens(swapped), "Word opens the swapped document")

        # safe_replace: succeeds on an unchanged target, refuses a changed or open one
        target = os.path.join(work, "target.docx")
        base_copy = os.path.join(work, "base.docx")
        shutil.copyfile(fixture, target)
        shutil.copyfile(fixture, base_copy)
        sr = [sys.executable, os.path.join(SCRIPTS, "safe_replace.py"), swapped, target, "--base", base_copy]
        expect(subprocess.call(sr) == 0, "safe_replace replaces an unchanged, closed target")
        expect(subprocess.call(sr) == 1, "safe_replace refuses a target that changed since the base")
        shutil.copyfile(base_copy, target)
        owner = os.path.join(work, "~$" + "target.docx"[2:])
        open(owner, "w").close()
        expect(lock_file(target) == owner, "lock_file detects the Word owner file")
        expect(subprocess.call(sr) == 1, "safe_replace refuses a target open in Word")
        os.remove(owner)
    except Exception as e:
        import traceback
        traceback.print_exc()
        FAILURES.append("exception: %s" % e)
    finally:
        if keep:
            print("kept: %s" % work)
        else:
            shutil.rmtree(work, ignore_errors=True)
    print("\n%d failure(s)" % len(FAILURES))
    for f in FAILURES:
        print("  - " + f)
    sys.exit(1 if FAILURES else 0)


if __name__ == "__main__":
    main()
