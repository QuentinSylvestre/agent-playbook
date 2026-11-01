"""
html_table_parser.py — Convert HTML tables to readable plain text.

Usage (CLI):
    python html_table_parser.py < email_body.html
    python html_table_parser.py path/to/file.html

Usage (as a module):
    from html_table_parser import parse_tables, fmt_table
    tables = parse_tables(html_string)
    for t in tables:
        print(fmt_table(t))

Why this exists
---------------
The msgraph MCP returns email bodies as HTML. Stripping tags with a regex
destroys table structure — all cell contents run together in one flat stream.
This parser walks the DOM properly and preserves rows/columns.

Works with Python's built-in html.parser — no third-party dependencies.
"""

import sys
import textwrap
from html.parser import HTMLParser


# ── Parser ─────────────────────────────────────────────────────────────────

class TableParser(HTMLParser):
    """Extract the content of every <table> in an HTML document."""

    def __init__(self):
        super().__init__()
        self.tables   = []      # list of finished tables; each table = list of rows; each row = list of cell strings
        self._rows    = []
        self._cells   = []
        self._buf     = ""
        self._in_cell = False
        self._depth   = 0       # nesting guard — only process outermost tables

    def handle_starttag(self, tag, attrs):
        t = tag.lower()
        if t == "table":
            self._depth += 1
            if self._depth == 1:
                self._rows = []
        elif t == "tr" and self._depth == 1:
            self._cells = []
        elif t in ("td", "th") and self._depth == 1:
            self._buf = ""
            self._in_cell = True
        elif t == "br" and self._in_cell:
            self._buf += "\n"

    def handle_endtag(self, tag):
        t = tag.lower()
        if t == "table":
            if self._depth == 1 and self._rows:
                self.tables.append(self._rows)
            self._depth = max(0, self._depth - 1)
        elif t == "tr" and self._depth == 1:
            if self._cells:
                self._rows.append(list(self._cells))
        elif t in ("td", "th") and self._depth == 1:
            self._cells.append(self._buf.strip())
            self._in_cell = False

    def handle_data(self, data):
        if self._in_cell:
            self._buf += data

    def handle_entityref(self, name):
        _map = {
            "nbsp": " ", "amp": "&", "lt": "<", "gt": ">",
            "quot": '"', "apos": "'", "ndash": "–", "mdash": "—",
        }
        if self._in_cell:
            self._buf += _map.get(name, "")

    def handle_charref(self, name):
        if self._in_cell:
            try:
                ch = chr(int(name[1:], 16) if name.startswith("x") else int(name))
                self._buf += ch
            except Exception:
                pass


def parse_tables(html: str) -> list[list[list[str]]]:
    """Return a list of tables; each table is a list of rows; each row is a list of cell strings."""
    p = TableParser()
    p.feed(html)
    return p.tables


# ── Formatter ──────────────────────────────────────────────────────────────

def fmt_table(rows: list[list[str]], col_wrap: int = 40) -> str:
    """Render a table (list of rows) as a fixed-width ASCII grid."""
    if not rows:
        return "(empty table)"

    ncols = max(len(r) for r in rows)
    rows = [r + [""] * (ncols - len(r)) for r in rows]   # normalise row widths

    # compute column widths capped at col_wrap
    widths = []
    for c in range(ncols):
        w = max(
            len(line)
            for row in rows
            for line in (row[c] or "").split("\n")
        )
        widths.append(min(w, col_wrap))

    sep = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
    lines = [sep]

    for row in rows:
        # wrap each cell independently
        wrapped = []
        for ci, cell in enumerate(row):
            cell_lines = []
            for para in cell.split("\n"):
                para = para.strip()
                if not para:
                    cell_lines.append("")
                else:
                    cell_lines.extend(textwrap.wrap(para, widths[ci]) or [""])
            wrapped.append(cell_lines)

        height = max(len(c) for c in wrapped)
        for h in range(height):
            parts = []
            for ci in range(ncols):
                text = wrapped[ci][h] if h < len(wrapped[ci]) else ""
                parts.append(f" {text:<{widths[ci]}} ")
            lines.append("|" + "|".join(parts) + "|")

        lines.append(sep)

    return "\n".join(lines)


# ── CLI entry point ─────────────────────────────────────────────────────────

def main():
    if len(sys.argv) > 1:
        with open(sys.argv[1], encoding="utf-8") as f:
            html = f.read()
    else:
        html = sys.stdin.read()

    tables = parse_tables(html)
    if not tables:
        print("(no tables found)")
        return

    print(f"Found {len(tables)} table(s).\n")
    for i, tbl in enumerate(tables):
        print(f"=== Table {i + 1} ({len(tbl)} rows) ===")
        print(fmt_table(tbl))
        print()


if __name__ == "__main__":
    main()
