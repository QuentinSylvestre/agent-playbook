"""Screenshot every slide of a built deck, run the layout checks, and print the deck to PDF.

Usage:  <python> shoot.py <deck-folder>            (all slides + PDF)
        <python> shoot.py <deck-folder> 3 5        (only slides 3 and 5)

Writes <deck>/screenshots/slideNN.png (1600x900) and checks every slide:
  - empty space (all but slide 1; see measure.py): interior holes (hollow cards, empty lanes) and
    edge bands (the layout stops short of the bottom or a side)
  - collisions (all slides; see collide.py): line-on-text, text-overlap, text-covered,
    text-overflow, box-overlap
  - title mark (a slide with the title pattern's .star): the brand mark must sit within 4 px of
    the centre of its rings
A failing slide gets slideNN.issues.png: red = interior hole, orange = edge band, magenta =
collision or off-centre mark. Every finding is also printed with coordinates and the text involved.
Ends with RESULT: PASS only when every slide passes and the PDF has one page per slide.
"""
import json, re, subprocess, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import png  # noqa: E402
from collide import check as collide, find_chrome  # noqa: E402
from measure import measure, verdict, mark_offset, INTERIOR_MAX, EDGE_MAX  # noqa: E402

RED, ORANGE, MAGENTA = (220, 30, 30), (240, 140, 0), (200, 0, 200)

deck = Path(sys.argv[1]).resolve()
only = {int(a) for a in sys.argv[2:]}
cfg = json.loads((deck / "deck.json").read_text(encoding="utf-8"))
html = deck / cfg.get("output", "deck.html")
if not html.exists():
    sys.exit(f"FAIL: {html} does not exist. Run build.py on the deck folder first.")
n = len(re.findall(r'<section\s+class="slide[\s"]', html.read_text(encoding="utf-8")))
out = deck / "screenshots"
out.mkdir(exist_ok=True)
chrome = find_chrome()
if not chrome:
    sys.exit("FAIL: Chrome not found. Install Google Chrome; do not hand the deck over unchecked - tell the user.")
base = [chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--window-size=1600,900",
        "--virtual-time-budget=2500"]
failures = []
for k in range(1, n + 1):
    if only and k not in only:
        continue
    shot = out / f"slide{k:02d}.png"
    marked = out / f"slide{k:02d}.issues.png"
    subprocess.run(base + [f"--screenshot={shot}", html.as_uri() + f"?noanim#{k}"], capture_output=True)
    if not shot.exists():
        print(f"FAIL slide {k}: no screenshot. Check the slide file opens a <section class=\"slide ...\">, rebuild, retry.")
        failures.append(k)
        continue
    img = png.read(shot)
    hits = collide(chrome, html, k)
    if hits is None:
        hits = [{"kind": "check-did-not-run", "x": 0, "y": 0, "w": 0, "h": 0,
                 "what": "the deck was not built with this skill's shell: run build.py"}]
    marks = [h for h in hits if h["kind"] == "title-mark"]
    hits = [h for h in hits if h["kind"] != "title-mark"]
    for mbox in marks:
        off = mark_offset(img, (mbox["x"], mbox["y"], mbox["w"], mbox["h"]))
        if off and (abs(off[0]) > 4 or abs(off[1]) > 4):
            hits.append({"kind": "mark-off-centre", "x": mbox["x"], "y": mbox["y"], "w": mbox["w"], "h": mbox["h"],
                         "what": f"brand mark is {off[0]:+.0f}px, {off[1]:+.0f}px from the ring centre: crop the "
                                 "mark file's viewBox to the symbol's exact bounds, or use the brand's own icon file"})
    m = measure(img) if k != 1 else None
    space_ok = m is None or verdict(m)
    space = (f"interior-holes {m['interior']:.0f}% (max {INTERIOR_MAX:.0f})  edge-bands {m['edge']:.0f}% (max {EDGE_MAX:.0f})"
             if m else "(title slide: space not measured)")
    ok = space_ok and not hits
    print(f"{'ok  ' if ok else 'FAIL'} {shot}  {space}  issues {len(hits)}")
    for h in hits:
        print(f"       {h['kind']:15} at x={h['x']:.0f} y={h['y']:.0f} {h['w']:.0f}x{h['h']:.0f}: {h['what']}")
    if ok:
        marked.unlink(missing_ok=True)
        continue
    failures.append(k)
    if m and not space_ok:
        for x, y, w, h in m["holes"]:
            img.rect(x, y, x + w, y + h, RED, 5)
        for x, y, w, h in m["bands"]:
            img.rect(x, y, x + w, y + h, ORANGE, 5)
    for h in hits:
        img.rect(h["x"] - 4, h["y"] - 4, h["x"] + h["w"] + 4, h["y"] + h["h"] + 4, MAGENTA, 4)
    png.write(marked, img)
    print(f"       -> open {marked}, then move or resize elements; never edit the checks or hide elements to pass")
pages_ok = True
if not only:
    pdf = out / "deck.pdf"
    subprocess.run(base + ["--no-pdf-header-footer", f"--print-to-pdf={pdf}", html.as_uri()], capture_output=True)
    pages = len(re.findall(rb"/Type\s*/Page[^s]", pdf.read_bytes())) if pdf.exists() else 0
    pages_ok = pages == n
    print(f"{pdf}: {pages} page(s) for {n} slide(s)" + ("" if pages_ok else
          "  <-- MISMATCH: a slide is taller than 900px or not a direct <section class=\"slide\">; fix it"))
print("RESULT:", "PASS" if not failures and pages_ok else
      f"FAIL (slides {failures or '-'}{'' if pages_ok else ', PDF page count'}): fix each slide listed above, "
      "re-run shoot.py on those slides, then a full run")
sys.exit(0 if not failures and pages_ok else 1)
