"""Measure empty space on a 1600x900 slide screenshot, and check the title mark is centred.

    python measure.py slide02.png [slide03.png ...]

The content area (x 88-1512, y 230-820) is cut into 32x32 px blocks. A block is BLANK when its
pixels are near-uniform (max-min luminance < 10): no text, line, icon or edge. Blank rectangles at
least 128x128 px are collected greedily:
  interior holes  do not touch the content-area edge: empty space inside the layout (hollow cards)
  edge bands      touch an edge: unused margin (the layout stops short of the bottom or a side)
A slide FAILS when interior holes > 12% or edge bands > 20% of the content area.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import png  # noqa: E402

X0, X1, Y0, Y1, B = 88, 1512, 230, 820, 32
MIN_SIDE = 4
INTERIOR_MAX, EDGE_MAX = 12.0, 20.0


def _grid(img):
    cols, rows = (X1 - X0) // B, (Y1 - Y0) // B
    g = []
    for r in range(rows):
        row = []
        for c in range(cols):
            lo, hi = img.gray_extrema(X0 + c * B, Y0 + r * B, X0 + (c + 1) * B, Y0 + (r + 1) * B)
            row.append(hi - lo < 10)
        g.append(row)
    return g, rows, cols


def _largest_rect(g, rows, cols):
    best = (0, 0, 0, 0, 0)
    h = [0] * cols
    for r in range(rows):
        for c in range(cols):
            h[c] = h[c] + 1 if g[r][c] else 0
        stack = []
        for c in range(cols + 1):
            cur = h[c] if c < cols else 0
            start = c
            while stack and stack[-1][1] >= cur:
                s, height = stack.pop()
                area = height * (c - s)
                if area > best[0]:
                    best = (area, r - height + 1, s, height, c - s)
                start = s
            stack.append((start, cur))
    return best


def measure(img):
    g, rows, cols = _grid(img)
    total = rows * cols
    work = [row[:] for row in g]
    interior, edge = [], []
    for _ in range(12):
        area, r0, c0, hh, ww = _largest_rect(work, rows, cols)
        if area < MIN_SIDE * MIN_SIDE:
            break
        for r in range(r0, r0 + hh):
            for c in range(c0, c0 + ww):
                work[r][c] = False
        if hh < MIN_SIDE or ww < MIN_SIDE:
            continue
        rect = (X0 + c0 * B, Y0 + r0 * B, ww * B, hh * B, area)
        touches = r0 == 0 or c0 == 0 or r0 + hh == rows or c0 + ww == cols
        (edge if touches else interior).append(rect)
    pct = lambda hs: 100.0 * sum(h[4] for h in hs) / total
    return dict(interior=pct(interior), edge=pct(edge), holes=[h[:4] for h in interior], bands=[h[:4] for h in edge])


def verdict(m):
    return m["interior"] <= INTERIOR_MAX and m["edge"] <= EDGE_MAX


def mark_offset(img, box):
    """Offset (dx, dy) in px between the centre of the coloured pixels inside box=(x,y,w,h) and the
    box centre. Coloured = channel spread > 60 (the brand mark, not the faint rings). None if no
    coloured pixel is found (a grey or white mark cannot be checked this way)."""
    x, y, w, h = (int(v) for v in box)
    xs, ys = [], []
    for yy in range(max(0, y), min(img.height, y + h), 2):
        for xx in range(max(0, x), min(img.width, x + w), 2):
            r, g, b = img.pixel(xx, yy)
            if max(r, g, b) - min(r, g, b) > 60:
                xs.append(xx)
                ys.append(yy)
    if not xs:
        return None
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    return cx - (x + w / 2), cy - (y + h / 2)


if __name__ == "__main__":
    ok_all = True
    for p in sys.argv[1:]:
        m = measure(png.read(p))
        ok = verdict(m)
        ok_all &= ok
        print(f"{'ok  ' if ok else 'FAIL'} {p}  interior-holes {m['interior']:.0f}%  edge-bands {m['edge']:.0f}%")
    sys.exit(0 if ok_all else 1)
