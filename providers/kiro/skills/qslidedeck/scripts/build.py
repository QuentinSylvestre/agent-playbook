"""Assemble a deck folder into one self-contained HTML file, then check it.

Usage:  <python> build.py <deck-folder>

Deck folder layout:
  deck.json        {"title": "...", "output": "my-deck.html", "forbid": ["term", ...],
                    "dropped": ["claim the user rejected", ...]}
  theme.css        brand tokens on :root plus deck-specific styles. <skill>/assets/base.css (every
                   component and pattern style) is included automatically BEFORE it.
  icons.svg        optional: your own icon sprite; default is <skill>/assets/icons.svg
  slides/NN-*.html one <section class="slide ...">...</section> per file, sorted by name
  assets/          images; reference them as  asset:logo.svg  in HTML or CSS

Exit 0 = built and all checks passed; exit 1 = a check failed (the file is still written so you
can look at it, but it is NOT done). Checks:
  FAIL  an external URL (http://, https://, //host): the deck must work offline during a live call
  FAIL  a term from deck.json "forbid" (case-insensitive): confidentiality scrub
  FAIL  a slide file without exactly one <section class="slide ...">, or a missing asset:NAME
  WARN  "forbid" is empty: list every internal product, repository, host and customer name
  LIST  every on-slide sentence with an absolute scope word (all, every, always, never...):
        compare each with the approved claims table at handover; these are where scope drifts
  LIST  every claim in deck.json "dropped": it must not appear on a slide in any wording
"""
import base64, html as htmllib, json, mimetypes, re, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path

SHELL = Path(__file__).resolve().parent.parent / "assets" / "shell.html"
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("font/woff2", ".woff2")
ABSOLUTE = re.compile(r"\b(all|every|everyone|everything|always|never|none|no one|nobody|entire|entirely|"
                      r"fully|completely|any|anyone|automatically)\b", re.I)


def slide_sentences(txt):
    body = re.sub(r"<(script|style|svg)\b.*?</\1>", " ", txt, flags=re.S | re.I)
    body = re.sub(r"<!--.*?-->", " ", body, flags=re.S)
    body = re.sub(r"<br\s*/?>|</(p|div|li|h[1-6]|span|b|i|article|aside)>", " | ", body, flags=re.I)
    text = htmllib.unescape(re.sub(r"<[^>]+>", " ", body))
    parts = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\||(?<=[.!?])\s", text)]
    return [p for p in parts if p]


def main(deck: Path) -> int:
    cfg = json.loads((deck / "deck.json").read_text(encoding="utf-8"))
    problems, scope = [], []
    slide_files = sorted((deck / "slides").glob("*.html"))
    if not slide_files:
        problems.append("no slides/*.html files: write one file per slide in <deck>/slides/")
    slides = []
    for f in slide_files:
        txt = f.read_text(encoding="utf-8")
        n = len(re.findall(r'<section\s+class="slide[\s"]', txt))
        if n != 1:
            problems.append(f"{f.name}: expected 1 <section class=\"slide ...\">, found {n}: one slide per file")
        slides.append(f"<!-- {f.name} -->\n{txt.strip()}")
        for s in slide_sentences(txt):
            if ABSOLUTE.search(s):
                scope.append((f.name, s))
    base = (SHELL.parent / "base.css").read_text(encoding="utf-8")
    theme = base + "\n/* ---- theme.css ---- */\n" + (
        (deck / "theme.css").read_text(encoding="utf-8") if (deck / "theme.css").exists() else "")
    icons_file = deck / "icons.svg" if (deck / "icons.svg").exists() else SHELL.parent / "icons.svg"
    icons = icons_file.read_text(encoding="utf-8") if icons_file.exists() else ""
    out_html = (SHELL.read_text(encoding="utf-8")
                .replace("{{TITLE}}", cfg.get("title", "Deck"))
                .replace("{{THEME}}", theme).replace("{{ICONS}}", icons)
                .replace("{{SLIDES}}", "\n\n".join(slides)))

    def inline(m):
        name = m.group(1)
        p = deck / "assets" / name
        if not p.exists():
            problems.append(f"missing asset: {name}: copy it into {deck / 'assets'} or fix the reference")
            return m.group(0)
        mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode("ascii")
    out_html = re.sub(r"asset:([\w.\-]+)", inline, out_html)

    scan = re.sub(r"data:[^\"')\s]+", "", out_html).replace("http://www.w3.org/", "")
    for url in sorted(set(re.findall(r"(?:https?:)?//[a-zA-Z0-9][\w.\-]*\.[a-z]{2,}[^\s\"'<>)]*", scan))):
        problems.append(f"external URL: {url}: inline the resource in assets/ or remove it (no web fonts, no CDN)")
    low = scan.lower()
    forbid = cfg.get("forbid", [])
    for term in forbid:
        if term.lower() in low:
            problems.append(f"forbidden term present: {term!r}: describe the thing by what it does, without its name")

    out = deck / cfg.get("output", "deck.html")
    out.write_text(out_html, encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size} bytes, {len(slides)} slides)")
    if not forbid:
        print("WARN: deck.json \"forbid\" is empty. Add every internal product, repository, host and customer "
              "name from the sources, even ones you did not use: it stops them reaching a slide later.")
    if scope:
        print(f"LIST: {len(scope)} sentence(s) with an absolute scope word. At handover, check each against the "
              "claims table; the user's scope wins (\"a small group\" never becomes \"all teams\"):")
        for name, s in scope:
            print(f"   {name}: {s[:140]}")
    dropped = cfg.get("dropped", [])
    if dropped:
        print(f"LIST: {len(dropped)} claim(s) the user dropped. Search every slide for each MEANING, not its words: "
              "a reworded dropped claim is still dropped. Remove any you find:")
        for d in dropped:
            print(f"   dropped: {d}")
    for p in problems:
        print("FAIL:", p)
    print("RESULT:", "PASS" if not problems else f"FAIL ({len(problems)} problem(s)): fix each FAIL above and rebuild")
    return 0 if not problems else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.exit(main(Path(sys.argv[1]).resolve()))
