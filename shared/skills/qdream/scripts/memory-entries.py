#!/usr/bin/env python3
"""memory-entries.py -- the one parser of memory files (MEMORY.md, HIGHER_ORDER.md, topic files).

Stdlib only, Python 3.8+, no I/O. No call raises on malformed text: anything that is not a str is
read as "" (bytes are decoded as UTF-8 with replacement). Each consumer owns its filter over the
output (plan 261016 Phase 11).

Text. A leading BOM is dropped; CRLF and a lone CR become LF; lines split on LF only (a form feed,
U+2028 and the other str.splitlines breaks are ordinary text) and are numbered from 1.

Fences. A line that starts, after whitespace, with ``` or ~~~ opens a fence, and the next line
starting with the same marker closes it; the other marker inside a fence is ordinary text. Lines in
a fence are never headings or table rows, but belong to the body of the entry they sit in.

Sections and entries. A line starting "## " opens a section; its name is the line stripped, less
the "## " marker (so "## " + name is the stripped line). A line starting "# " ends the section:
until the next "## " there is none. A line starting "### " inside a section opens an entry; its
heading is the rest of the line stripped, and its body is every line up to the next "# ", "## " or
"### " line outside a fence. A "### " line with no section is not an entry.

Source. The entry's Source is the first body line outside a fence matching ^\\W*\\*\\*Source\\*\\*: (a bullet or
quote prefix is allowed; the spelling **Source:** is accepted too). Its value is the text after
the field name, cut at the first `|\\s*\\*\\*Verified\\*\\*:` (the inline Verified tail; any other
`|`, a quoted one say, is kept), stripped. No such line: None.

Verified. The first `**Verified**: YYYY-MM-DD` in the entry body outside a fence gives the date text
(not checked to be a real day); none: None.

Topics rows. In a section named Topics (case-insensitive), a line outside a fence that starts with
`|` is a row when it has exactly three cells (the leading `|` and one trailing `|` are dropped,
the rest split on `|`) and its first cell is one backticked path. -> (path, second cell), both
stripped. The header (`Topic file`) and the separator row are not rows.

  memory-entries.py --selftest
"""

import os
import re
import sys

# FENCE_RE and SOURCE_RE are public: the qdream scripts match fences and Source lines with these.
FENCE_RE = re.compile(r"^\s*(```|~~~)")
SOURCE_RE = re.compile(r"^\W*\*\*Source(?:\*\*:|:\*\*)(.*)$")
_VERIFIED_TAIL_RE = re.compile(r"\|\s*\*\*Verified\*\*:")
_VERIFIED_RE = re.compile(r"\*\*Verified\*\*:\s*(\d{4}-\d{2}-\d{2})")
_TOPIC_PATH_RE = re.compile(r"^\s*`([^`]+)`\s*$")


def normalize(text):
    """The text with a leading BOM dropped and CRLF / lone CR as LF; "" for a non-str."""
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    if not isinstance(text, str):
        return ""
    if text.startswith("﻿"):
        text = text[1:]
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _scan(text):
    """-> (entries, sections, topics) in one fence-aware pass; see the module docstring."""
    entries, sections, topics = [], [], []
    section, cur, fence = None, None, None
    for no, line in enumerate(normalize(text).split("\n"), 1):
        fm = FENCE_RE.match(line)
        if fence:
            if fm and fm.group(1) == fence:
                fence = None
            if cur is not None:
                cur[2].append(line)
            continue
        if fm:
            fence = fm.group(1)
            if cur is not None:
                cur[2].append(line)
            continue
        if line.startswith("# ") or line.startswith("## ") or line.startswith("### "):
            if cur is not None:
                entries.append(cur)
                cur = None
            if line.startswith("### "):
                if section is not None:
                    cur = (section, line[4:].strip(), [], no)
            elif line.startswith("## "):
                section = line.strip()[3:]
                sections.append((section, no))
            else:
                section = None
            continue
        if section is not None and section.strip().casefold() == "topics" and line.startswith("|"):
            row = _topic_row(line)
            if row is not None:
                topics.append(row)
        if cur is not None:
            cur[2].append(line)
    if cur is not None:
        entries.append(cur)
    return entries, sections, topics


def _topic_row(line):
    body = line.rstrip()[1:]
    if body.endswith("|"):
        body = body[:-1]
    cells = body.split("|")
    if len(cells) != 3:
        return None
    m = _TOPIC_PATH_RE.match(cells[0])
    if not m or m.group(1) == "Topic file":
        return None
    return m.group(1).strip(), cells[1].strip()


def entries(text):
    """-> [(section, heading, body_lines, line_no)] for every ### entry under a ## section, in file
    order; line_no is the 1-based line of the ### line."""
    return _scan(text)[0]


def sections(text):
    """-> [(section, line_no)] for every ## line outside a fence, in file order."""
    return _scan(text)[1]


def topic_rows(text):
    """-> [(path, trigger)] from the Topics table(s), by the three-cell rule."""
    return _scan(text)[2]


def _lines(body):
    if isinstance(body, (list, tuple)):
        return [x for x in body if isinstance(x, str)]
    return normalize(body).split("\n")


def _unfenced(body):
    """The body's lines outside a fence (a fence never closed runs to the end of the body)."""
    fence = None
    for line in _lines(body):
        fm = FENCE_RE.match(line)
        if fence:
            if fm and fm.group(1) == fence:
                fence = None
            continue
        if fm:
            fence = fm.group(1)
            continue
        yield line


def source(body):
    """The entry's Source value (body: its lines, or their text); None when it has none."""
    for line in _unfenced(body):
        m = SOURCE_RE.match(line)
        if m:
            return _VERIFIED_TAIL_RE.split(m.group(1), 1)[0].strip()
    return None


def verified(body):
    """The entry's first Verified date text (YYYY-MM-DD shaped); None when it has none."""
    m = _VERIFIED_RE.search("\n".join(_unfenced(body)))
    return m.group(1) if m else None


# --------------------------------------------------------------------------
# Selftest
# --------------------------------------------------------------------------

_DOC = (
    "# Memory\n"
    "### Preamble heading\n"
    "\n"
    "## Topics\n"
    "\n"
    "| Topic file | Read when | Also cited from |\n"
    "|---|---|---|\n"
    "| `memory/topics/git.md` | a git operation | nowhere |\n"
    "| `memory/topics/two.md` | two cells |\n"
    "| `memory/topics/four.md` | four | cells | here |\n"
    "| `Topic file` | backticked header | x |\n"
    "| not `backticked` | x | y |\n"
    "```\n"
    "| `memory/topics/fenced.md` | in a fence | x |\n"
    "```\n"
    "\n"
    "## Feedback\n"
    "\n"
    "### First entry\n"
    "\n"
    "**Why**: a reason.\n"
    "```\n"
    "### Fenced backtick heading\n"
    "~~~\n"
    "### Still fenced\n"
    "```\n"
    "~~~\n"
    "### Fenced tilde heading\n"
    "```\n"
    "## Fenced section\n"
    "~~~\n"
    "- **Source**: session abc | quoted | pipe | **Verified**: 2026-09-01\n"
    "**Source**: the second Source line\n"
    "\n"
    "### Second entry\n"
    "**Source:** old spelling\n"
    "**Verified**: 2026-09-02 (human:alice)\n"
    "\n"
    "# Reset\n"
    "### After a reset\n"
    "\n"
    "## Declined\n"
    "\n"
    "### Declined entry\n"
    "> **Source**: quoted prefix\n"
)


def _case_entries():
    got = [(s, h, n) for s, h, _b, n in entries(_DOC)]
    want = [("Feedback", "First entry", 19), ("Feedback", "Second entry", 35),
            ("Declined", "Declined entry", 44)]
    return [] if got == want else ["entries: %r, expected %r" % (got, want)]


def _case_fences():
    fails = []
    heads = [h for _s, h, _b, _n in entries(_DOC)]
    for h in ("Fenced backtick heading", "Still fenced", "Fenced tilde heading"):
        if h in heads:
            fails.append("a fenced ### became an entry: %s" % h)
    if "Fenced section" in [s for s, _n in sections(_DOC)]:
        fails.append("a fenced ## became a section")
    body = entries(_DOC)[0][2]
    if "### Still fenced" not in body or "~~~" not in body:
        fails.append("fence lines are not in the entry body: %r" % body)
    return fails


def _case_preamble_and_reset():
    heads = [h for _s, h, _b, _n in entries(_DOC)]
    fails = []
    if "Preamble heading" in heads:
        fails.append("a ### before any ## became an entry")
    if "After a reset" in heads:
        fails.append("a ### after a # line became an entry")
    if [s for s, _n in sections(_DOC)] != ["Topics", "Feedback", "Declined"]:
        fails.append("sections: %r" % sections(_DOC))
    return fails


def _case_topics():
    got = topic_rows(_DOC)
    want = [("memory/topics/git.md", "a git operation")]
    return [] if got == want else ["topic_rows: %r, expected %r" % (got, want)]


def _case_source():
    fails = []
    e = {h: b for _s, h, b, _n in entries(_DOC)}
    for heading, want in (("First entry", "session abc | quoted | pipe"),
                          ("Second entry", "old spelling"),
                          ("Declined entry", "quoted prefix")):
        if source(e[heading]) != want:
            fails.append("source(%s) = %r, expected %r" % (heading, source(e[heading]), want))
    if source("\n".join(e["First entry"])) != "session abc | quoted | pipe":
        fails.append("source() over the joined body differs from over its lines")
    for body, want in (("**Why**: none", None), ("**Source**:   spaced  | **Verified**:x", "spaced"),
                       ("text **Source**: mid-line", None), ("**Source**:", ""),
                       ("**Source**: a |**Verified**: 2026-01-01", "a")):
        if source(body) != want:
            fails.append("source(%r) = %r, expected %r" % (body, source(body), want))
    return fails


def _case_verified():
    fails = []
    e = {h: b for _s, h, b, _n in entries(_DOC)}
    for heading, want in (("First entry", "2026-09-01"), ("Second entry", "2026-09-02"),
                          ("Declined entry", None)):
        if verified(e[heading]) != want:
            fails.append("verified(%s) = %r, expected %r" % (heading, verified(e[heading]), want))
    if verified("**Verified**: 2026-02-30 | **Verified**: 2026-01-01") != "2026-02-30":
        fails.append("verified() does not return the first date as written")
    return fails


def _case_fenced_fields():
    """A Source or Verified line in a fence of the body is an example, never the entry's field."""
    fails = []
    body = ["```", "**Source**: fenced example | **Verified**: 2026-01-01", "```",
            "~~~", "**Verified**: 2026-01-02", "```", "**Source**: other marker, still fenced", "~~~",
            "**Source**: the real one", "**Verified**: 2026-03-03"]
    for form, b in (("lines", body), ("text", "\n".join(body))):
        if source(b) != "the real one":
            fails.append("source(%s) = %r, expected the real one" % (form, source(b)))
        if verified(b) != "2026-03-03":
            fails.append("verified(%s) = %r, expected 2026-03-03" % (form, verified(b)))
    only = ["~~~", "**Source**: fenced", "**Verified**: 2026-01-01"]  # a fence never closed
    if source(only) is not None or verified(only) is not None:
        fails.append("a fence never closed still gave %r / %r" % (source(only), verified(only)))
    doc = "## Feedback\n### E\n```\n**Source**: example\n```\n**Source**: real\n"
    if source(entries(doc)[0][2]) != "real":
        fails.append("source() of a parsed entry with a fenced example: %r" % source(entries(doc)[0][2]))
    return fails


def _case_text_forms():
    fails = []
    lf = "## Pattern\n### One\n**Source**: s\n### Two\n"
    want = [(s, h, n) for s, h, _b, n in entries(lf)]
    for label, text in (("BOM", "﻿" + lf), ("CRLF", lf.replace("\n", "\r\n")),
                        ("lone CR", lf.replace("\n", "\r")),
                        ("bytes", ("﻿" + lf).encode("utf-8"))):
        got = [(s, h, n) for s, h, _b, n in entries(text)]
        if got != want:
            fails.append("%s: %r, expected %r" % (label, got, want))
    if want != [("Pattern", "One", 2), ("Pattern", "Two", 4)]:
        fails.append("LF: %r" % want)
    if entries("﻿## Feedback\n### X\n")[0][:2] != ("Feedback", "X"):
        fails.append("a BOM before the first ## hid the section")
    return fails


def _case_malformed():
    fails = []
    for bad in (None, 3, ["## a"], "", "###", "## \n### \n", "```\n### open fence never closed",
                "\x00�## x\n"):
        try:
            entries(bad), sections(bad), topic_rows(bad), source(bad), verified(bad)
        except Exception as e:  # the contract: never raises
            fails.append("%r raised %s: %s" % (bad, type(e).__name__, e))
    if entries("## \n### \n") != [("", "", [""], 2)]:
        fails.append("an empty section name or heading is not kept: %r" % entries("## \n### \n"))
    if entries("##  Spaced\n### H\n")[0][0] != " Spaced":
        fails.append("the section name is not the stripped line less '## '")
    return fails


CASES = [("entries", _case_entries), ("fences", _case_fences),
         ("preamble-and-reset", _case_preamble_and_reset), ("topics", _case_topics),
         ("source", _case_source), ("verified", _case_verified),
         ("fenced-fields", _case_fenced_fields), ("text-forms", _case_text_forms),
         ("malformed", _case_malformed)]


def selftest():
    failed = 0
    for name, fn in CASES:
        try:
            fails = fn()
        except Exception as e:  # one broken case never stops the run
            fails = ["case raised %s: %s" % (type(e).__name__, e)]
        if fails:
            failed += 1
            print("FAIL %s" % name)
            for f in fails:
                print("  - %s" % f)
        else:
            print("PASS %s" % name)
    print("selftest: %d case(s), %d failed" % (len(CASES), failed))
    return 1 if failed else 0


# --- venv guard stub: identical in every qdream script (venv-selfcheck.py --selftest compares them) ---
def _require_venv(script):
    """plan 261016 Phase 5: exit 2, "guard did not run: venv missing", unless this process runs in the
    dedicated venv. A run's first action: it loads only venv-selfcheck.py (by path, no bytecode cache,
    stdlib only) before any other sibling script is imported, so a broken sibling cannot hide the guard;
    if even that load fails it exits 2 with "venv self-check unavailable". The check itself lives only in
    venv-selfcheck.py. Not called at import: the hook imports some of these files."""
    import importlib.util
    path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "venv-selfcheck.py")
    name = os.path.basename(script or __file__)
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location("venv_selfcheck", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as exc:
        sys.stderr.write("%s: guard did not run: venv self-check unavailable (%s: %s)\n"
                         % (name, type(exc).__name__, exc))
        sys.exit(2)
    finally:
        sys.dont_write_bytecode = saved
    mod.require(script or __file__)
# --- end venv guard stub ---


if __name__ == "__main__":
    _require_venv(__file__)
    if sys.argv[1:] == ["--selftest"]:
        sys.exit(selftest())
    sys.stderr.write("usage: memory-entries.py --selftest (a library; the qdream scripts and the "
                     "SessionStart hook load it by path)\n")
    sys.exit(2)
