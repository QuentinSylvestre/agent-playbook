"""Turn plain "@Name" text in Word comments into real @mentions; list the people a document knows.

Word stores a mention as a HYPERLINK "mailto:<email>" field around the text "@Name",
with a hidden bookmark named _@_<32 hex>Z and the "Mention" character style. Plain
"@Name" text (what Comments.Replies.Add writes) is linked to nobody and notifies nobody.

Email lookup, in this order. Never guess an address:
  1. `people`: word/people.xml lists every comment author signed in with Microsoft 365,
     with presenceInfo userId "S::<email>::<directory object id>".
  2. An address the user gives, or one found in a directory or mail search, passed
     as --person "Name=email".

Usage:
    python docx_mentions.py people <file.docx>
    python docx_mentions.py mention <in.docx> <out.docx> --person "Name" [--person "Other Name=email" ...]

`mention` converts every plain "@Name" in word/comments.xml for each person, adds
the Mention style if the document lacks it, and fails if a person has no email or
no "@Name" was found. Microsoft 365 sends the notification when the file is saved
in OneDrive or SharePoint; check with the user that it arrived.

Outputs JSON. Exit codes: 0 = done, 1 = a person was unresolved or not found, 2 = usage error
"""
import html
import json
import os
import re
import sys
import uuid
import zipfile

PRESENCE_RE = re.compile(r'<w15:person w15:author="([^"]+)"\s*>\s*<w15:presenceInfo [^>]*w15:userId="S::([^:"]+)::')
RUN_RE = re.compile(r"<w:r(?: [^>]*)?>(<w:rPr>(?:(?!</w:rPr>).)*</w:rPr>)?<w:t(?: xml:space=\"preserve\")?>([^<]*)</w:t></w:r>", re.S)
MENTION_STYLE = ('<w:style w:type="character" w:styleId="Mention"><w:name w:val="Mention"/>'
                 '<w:basedOn w:val="DefaultParagraphFont"/><w:uiPriority w:val="99"/><w:unhideWhenUsed/>'
                 '<w:rPr><w:color w:val="2B579A"/><w:shd w:val="clear" w:color="auto" w:fill="E1DFDD"/></w:rPr></w:style>')


def people(z):
    """{author name: email} from word/people.xml."""
    if "word/people.xml" not in z.namelist():
        return {}
    return {html.unescape(n): e for n, e in PRESENCE_RE.findall(z.read("word/people.xml").decode("utf-8"))}


def run(rpr, text):
    return '<w:r>%s<w:t xml:space="preserve">%s</w:t></w:r>' % (rpr or "", text) if text else ""


def mention_xml(name, email, bm_id):
    return ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            '<w:r><w:instrText xml:space="preserve">HYPERLINK "mailto:%s"</w:instrText></w:r>'
            '<w:bookmarkStart w:id="%d" w:name="_@_%sZ"/>'
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r><w:bookmarkEnd w:id="%d"/>'
            '<w:r><w:rPr><w:rStyle w:val="Mention"/><w:noProof/></w:rPr><w:t>@%s</w:t></w:r>'
            '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
            % (html.escape(email, quote=True), bm_id, uuid.uuid4().hex.upper(), bm_id, html.escape(name, quote=False)))


def convert(comments_xml, name, email, next_bm):
    """Replace plain '@name' text in comment runs. Returns (xml, count, next_bm)."""
    needle = "@" + html.escape(name, quote=False)
    count = 0

    def sub(m):
        nonlocal count, next_bm
        rpr, text = m.group(1) or "", m.group(2)
        if needle not in text or 'w:val="Mention"' in rpr:
            return m.group(0)
        out, rest = [], text
        while needle in rest:
            before, rest = rest.split(needle, 1)
            out.append(run(rpr, before))
            out.append(mention_xml(name, email, next_bm))
            next_bm += 1
            count += 1
        out.append(run(rpr, rest))
        return "".join(out)

    return RUN_RE.sub(sub, comments_xml), count, next_bm


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Real @mentions in Word comments")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("people")
    p1.add_argument("docx")
    p2 = sub.add_parser("mention")
    p2.add_argument("docx")
    p2.add_argument("out")
    p2.add_argument("--person", action="append", required=True, help='"Name" (email from people.xml) or "Name=email"')
    args = ap.parse_args()
    if not os.path.isfile(args.docx):
        print(json.dumps({"error": "file not found: %s" % args.docx}))
        sys.exit(2)
    z = zipfile.ZipFile(args.docx)
    known = people(z)
    if args.cmd == "people":
        print(json.dumps({"people": known}, indent=2, ensure_ascii=False))
        return
    if "word/comments.xml" not in z.namelist():
        print(json.dumps({"error": "document has no comments"}))
        sys.exit(1)

    comments = z.read("word/comments.xml").decode("utf-8")
    all_xml = "".join(z.read(n).decode("utf-8", "ignore") for n in z.namelist() if n.startswith("word/") and n.endswith(".xml"))
    next_bm = max([int(i) for i in re.findall(r'<w:bookmarkStart w:id="(\d+)"', all_xml)] + [0]) + 1
    report, failed = [], False
    for spec in args.person:
        name, _, email = spec.partition("=")
        name, email = name.strip(), (email.strip() or known.get(name.strip(), ""))
        if not email:
            report.append({"person": name, "error": "no email: not in people.xml, pass \"Name=email\""})
            failed = True
            continue
        comments, n, next_bm = convert(comments, name, email, next_bm)
        report.append({"person": name, "email": email, "mentions": n})
        failed |= n == 0
    if failed:
        print(json.dumps({"ok": False, "persons": report}, indent=2, ensure_ascii=False))
        sys.exit(1)

    styles = z.read("word/styles.xml").decode("utf-8")
    added_style = 'w:styleId="Mention"' not in styles
    if added_style:
        styles = styles.replace("</w:styles>", MENTION_STYLE + "</w:styles>")
    with zipfile.ZipFile(args.out, "w") as zout:
        for info in z.infolist():
            data = z.read(info.filename)
            if info.filename == "word/comments.xml":
                data = comments.encode("utf-8")
            elif info.filename == "word/styles.xml":
                data = styles.encode("utf-8")
            zout.writestr(info, data, compress_type=info.compress_type)
    print(json.dumps({"ok": True, "persons": report, "mention_style_added": added_style}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
