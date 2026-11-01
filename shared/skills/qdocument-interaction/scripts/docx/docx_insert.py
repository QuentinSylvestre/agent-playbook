"""Insert headings, paragraphs, numbered steps, bullets and pictures into an existing .docx.

Use it to add a section (for example a procedure with screenshots) before or after a heading of a
finished document without re-creating the document. It edits the XML directly: other parts are
copied unchanged, and the output is a new file. Deliver it with safe_replace.py, validate it with
scripts/office/validate.py, and render it through Word to look at the pages.

Spec (JSON):
    {
      "anchor": {"text": "Widget app activation", "where": "before"},   # before | after
      "step_like": "Check the prerequisites",    # start of an existing numbered paragraph to copy
      "bullet_like": "UUID: shared by",          # optional: start of an existing bullet paragraph
      "update_fields": true,                     # ask Word to refresh the TOC on open (it prompts)
      "blocks": [
        {"type": "heading", "level": 3, "text": "Bulk configuration"},
        {"type": "para", "text": "Plain paragraph.", "keep_next": true},
        {"type": "para", "runs": [{"text": "See also: "}, {"text": "Docs", "url": "https://example.com"}]},
        {"type": "step", "text": "Numbered step, restarts at 1 for this insert."},
        {"type": "bullet", "text": "Bullet."},
        {"type": "image", "path": "shot.png", "width_px": 662, "emu_per_px": 6000, "alt": "Menu"}
      ]
    }

"anchor.text" must equal the whole text of exactly one Heading paragraph (the table of contents
entry has a TOC style and is ignored). "step_like" selects the numbered list whose look the steps
copy: the script adds a new list with the same format that restarts at 1, so existing lists keep
their numbers. Image paths resolve against the spec file's folder; only PNG is supported.
Pictures are centred. The hyperlink style "Hyperlink" must exist in the document.

Usage:
    python docx_insert.py <in.docx> <spec.json> <out.docx>

Prints JSON: {"output", "inserted_blocks", "new_numId", "images"}.
Exit codes: 0 = success, 1 = failure (anchor not found or ambiguous, bad spec, unsupported image).
"""
import json
import os
import re
import struct
import sys
import zipfile
from xml.sax.saxutils import escape, unescape

SP = '<w:spacing w:after="160" w:line="259" w:lineRule="auto"/>'


def fail(msg):
    print("docx_insert failed: %s" % msg, file=sys.stderr)
    sys.exit(1)


def para_text(p):
    return unescape(re.sub(r"<[^>]+>", "", p))


def paragraphs(xml):
    return list(re.finditer(r"<w:p[ >](?:(?!</w:p>).)*</w:p>", xml, flags=re.S))


def png_size(data):
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        fail("only PNG images are supported")
    return struct.unpack(">II", data[16:24])


def find_model(xml, start_text):
    for m in paragraphs(xml):
        p = m.group(0)
        if "<w:numId " in p and "TOC" not in p[:300] and para_text(p).startswith(start_text):
            return p
    fail("no numbered paragraph starts with %r" % start_text)


def abstract_of(numbering, num_id):
    m = re.search(r'<w:num w:numId="%s"[^>]*>\s*<w:abstractNumId w:val="(\d+)"' % num_id, numbering)
    if not m:
        fail("numId %s not found in numbering.xml" % num_id)
    return m.group(1)


def main():
    if len(sys.argv) != 4:
        print(__doc__.split("Usage:")[1].split("Prints")[0].strip(), file=sys.stderr)
        sys.exit(1)
    src, spec_path, dst = sys.argv[1:4]
    spec_path = os.path.abspath(spec_path)
    base = os.path.dirname(spec_path)
    try:
        spec = json.load(open(spec_path, encoding="utf-8"))
        zin = zipfile.ZipFile(src)
    except (OSError, ValueError, zipfile.BadZipFile) as e:
        fail(str(e))
    doc = zin.read("word/document.xml").decode("utf8")
    numbering = zin.read("word/numbering.xml").decode("utf8")
    rels = zin.read("word/_rels/document.xml.rels").decode("utf8")
    settings = zin.read("word/settings.xml").decode("utf8")
    ctypes = zin.read("[Content_Types].xml").decode("utf8")
    for ns in ("xmlns:wp=", "xmlns:r="):
        if ns not in doc[:6000]:
            fail("document.xml root does not declare %s" % ns)

    # anchor
    anchor = spec["anchor"]
    hits = [m for m in paragraphs(doc)
            if re.search(r'<w:pStyle w:val="Heading\d"/>', m.group(0)) and para_text(m.group(0)).strip() == anchor["text"]]
    if len(hits) != 1:
        fail("anchor heading %r matched %d paragraphs (need exactly 1)" % (anchor["text"], len(hits)))
    pos = hits[0].start() if anchor.get("where", "before") == "before" else hits[0].end()

    # lists
    new_num = None
    step_style = "ListParagraph"
    if any(b["type"] == "step" for b in spec["blocks"]):
        model = find_model(doc, spec["step_like"])
        abstract = abstract_of(numbering, re.search(r'<w:numId w:val="(\d+)"', model).group(1))
        ms = re.search(r'<w:pStyle w:val="([^"]+)"', model)
        step_style = ms.group(1) if ms else step_style
        new_num = max(int(x) for x in re.findall(r'<w:num w:numId="(\d+)"', numbering)) + 1
        override = ('<w:num w:numId="%d"><w:abstractNumId w:val="%s"/><w:lvlOverride w:ilvl="0">'
                    '<w:startOverride w:val="1"/></w:lvlOverride></w:num>' % (new_num, abstract))
        tail = "<w:numIdMacAtCleanup" if "<w:numIdMacAtCleanup" in numbering else "</w:numbering>"
        numbering = numbering.replace(tail, override + tail, 1)
    bullet_num = None
    if any(b["type"] == "bullet" for b in spec["blocks"]):
        bullet_num = re.search(r'<w:numId w:val="(\d+)"', find_model(doc, spec["bullet_like"])).group(1)

    # ids
    docpr = max([int(x) for x in re.findall(r'<wp:docPr id="(\d+)"', doc)] or [0])
    rid = max(int(x) for x in re.findall(r'Id="rId(\d+)"', rels))
    media = max([int(x) for x in re.findall(r"word/media/image(\d+)\.", " ".join(zin.namelist()))] or [0])
    new_rels, new_media = [], {}

    def keep(b):
        return "<w:keepNext/>" if b.get("keep_next") else ""

    def run(t):
        return '<w:r><w:t xml:space="preserve">%s</w:t></w:r>' % escape(t)

    def listp(b, num):
        return ('<w:p><w:pPr><w:pStyle w:val="%s"/>%s<w:numPr><w:ilvl w:val="0"/><w:numId w:val="%s"/></w:numPr>%s</w:pPr>%s</w:p>'
                % (step_style, keep(b), num, SP, run(b["text"])))

    out = []
    for b in spec["blocks"]:
        t = b["type"]
        if t == "heading":
            out.append('<w:p><w:pPr><w:pStyle w:val="Heading%d"/>%s</w:pPr>%s</w:p>' % (int(b["level"]), keep(b), run(b["text"])))
        elif t == "para":
            runs = b.get("runs") or [{"text": b["text"]}]
            xml = ""
            for r in runs:
                if r.get("url"):
                    rid += 1
                    new_rels.append('<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="%s" TargetMode="External"/>' % (rid, escape(r["url"], {'"': "&quot;"})))
                    xml += ('<w:hyperlink r:id="rId%d" w:history="1"><w:r><w:rPr><w:rStyle w:val="Hyperlink"/></w:rPr>'
                            '<w:t xml:space="preserve">%s</w:t></w:r></w:hyperlink>' % (rid, escape(r["text"])))
                else:
                    xml += run(r["text"])
            out.append("<w:p><w:pPr>%s%s</w:pPr>%s</w:p>" % (keep(b), SP, xml))
        elif t == "step":
            out.append(listp(b, new_num))
        elif t == "bullet":
            out.append(listp(b, bullet_num))
        elif t == "image":
            path = b["path"] if os.path.isabs(b["path"]) else os.path.join(base, b["path"])
            data = open(path, "rb").read()
            w, h = png_size(data)
            if b.get("width_px"):
                h = round(h * int(b["width_px"]) / w)
                w = int(b["width_px"])
            k = int(b.get("emu_per_px", 6000))
            cx, cy = w * k, h * k
            rid += 1
            docpr += 1
            media += 1
            target = "media/image%d.png" % media
            new_media["word/" + target] = data
            new_rels.append('<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="%s"/>' % (rid, target))
            out.append(
                '<w:p><w:pPr>%s%s<w:jc w:val="center"/></w:pPr><w:r><w:rPr><w:noProof/></w:rPr><w:drawing>'
                '<wp:inline distT="0" distB="0" distL="0" distR="0"><wp:extent cx="%d" cy="%d"/>'
                '<wp:effectExtent l="0" t="0" r="0" b="0"/><wp:docPr id="%d" name="Picture %d" descr="%s"/>'
                '<wp:cNvGraphicFramePr><a:graphicFrameLocks xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" noChangeAspect="1"/></wp:cNvGraphicFramePr>'
                '<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
                '<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:nvPicPr><pic:cNvPr id="%d" name=""/><pic:cNvPicPr/></pic:nvPicPr>'
                '<pic:blipFill><a:blip r:embed="rId%d"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
                '<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="%d" cy="%d"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic>'
                '</a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>'
                % (keep(b), SP, cx, cy, docpr, docpr, escape(b.get("alt", ""), {'"': "&quot;"}), docpr, rid, cx, cy))
        else:
            fail("unknown block type %r" % t)

    doc = doc[:pos] + "".join(out) + doc[pos:]
    rels = rels.replace("</Relationships>", "".join(new_rels) + "</Relationships>")
    if new_media and 'Extension="png"' not in ctypes:
        ctypes = ctypes.replace("<Override", '<Default Extension="png" ContentType="image/png"/><Override', 1)
    if spec.get("update_fields") and "<w:updateFields" not in settings:
        for anchor_tag in ("<w:hdrShapeDefaults", "<w:footnotePr", "<w:endnotePr", "<w:compat"):
            if anchor_tag in settings:
                settings = settings.replace(anchor_tag, '<w:updateFields w:val="true"/>' + anchor_tag, 1)
                break
        else:
            fail("no safe place found in settings.xml for updateFields")

    repl = {"word/document.xml": doc, "word/numbering.xml": numbering, "word/_rels/document.xml.rels": rels,
            "word/settings.xml": settings, "[Content_Types].xml": ctypes}
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = repl[info.filename].encode("utf8") if info.filename in repl else zin.read(info.filename)
            zi = zipfile.ZipInfo(info.filename, info.date_time)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = info.external_attr
            zout.writestr(zi, data)
        for name, data in new_media.items():
            zout.writestr(name, data)
    print(json.dumps({"output": os.path.abspath(dst), "inserted_blocks": len(out), "new_numId": new_num,
                      "images": len(new_media)}, indent=1))


if __name__ == "__main__":
    main()
