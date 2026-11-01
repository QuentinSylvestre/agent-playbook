"""Compose annotated screenshots for documents: blur, numbered boxes, crop, frame, and grids.

One JSON spec produces one output image made of one or more panels. Each panel is a
source image with optional blurred areas (names, emails, IDs, keys), red boxes with step
numbers that match the numbered steps of the procedure, a crop, and a thin grey frame.
Several panels are laid out in a grid; one column (stacked) keeps text readable once the
image is scaled to page width.

All coordinates are in source-image pixels, before the crop. A number that would fall
outside the cropped panel is moved to the opposite side, then below the box, and the move
is reported as a warning, so a clipped label never reaches the document silently.

Spec:
    {
      "output": "out.png",
      "cols": 1,                 # panels per row (default 1)
      "gap": 24,                 # pixels between panels (default 24)
      "style": {"color": "#DC0000", "width": 4, "font_size": 26},
      "panels": [
        {"image": "shot.png",
         "blur": [[x0, y0, x1, y1]],
         "replace": [{"box": [x0, y0, x1, y1], "text": "300", "size": 14}],   # size optional
         "marks": [{"box": [x0, y0, x1, y1], "label": "1", "side": "left"}],   # side: left, right, top, bottom; label optional
         "crop": [x0, y0, x1, y1],
         "frame": true}
      ]
    }
"replace" corrects a value shown in the screenshot (a recommended setting, a version) when the
user has approved it: it finds the text inside "box", erases it with the box's background colour,
and redraws "text" in the same place, colour and (unless "size" is given) height. Give the box
just around the old text and its own background. It is applied before blur and marks. Say in the
report that the image was edited and that the live system still differs.
Relative image paths resolve against the spec file's folder.

Usage:
    python annotate_screenshot.py <spec.json>

Prints JSON: {"output", "size", "warnings"}.
Exit codes: 0 = success, 1 = failure (bad spec, missing image), 2 = Pillow not available
"""
import json
import os
import sys

DEFAULT_STYLE = {"color": "#DC0000", "width": 4, "font_size": 26}
FRAME_COLOR = (190, 190, 190)
FONTS = ("arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf")
TEXT_FONTS = ("segoeui.ttf", "arial.ttf", "Arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf")


def load_font(size):
    from PIL import ImageFont
    for name in FONTS:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def load_text_font(size):
    from PIL import ImageFont
    for name in TEXT_FONTS:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def replace_text(im, spec, warnings, index):
    """Erase the ink inside spec["box"] and draw spec["text"] where it was."""
    from PIL import ImageDraw
    box = tuple(int(v) for v in spec["box"])
    region = im.crop(box)
    bg = max(region.getcolors(region.width * region.height))[1]

    def dist(c):
        return sum(abs(c[i] - bg[i]) for i in range(3))

    px = region.load()
    ink = [(x, y) for y in range(region.height) for x in range(region.width) if dist(px[x, y]) > 120]
    if not ink:
        warnings.append("panel %d: replace box %s holds no text" % (index, list(box)))
        return
    xs, ys = [p[0] for p in ink], [p[1] for p in ink]
    x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
    color = max((px[p] for p in ink), key=dist)
    d = ImageDraw.Draw(im)
    d.rectangle((box[0] + x0 - 1, box[1] + y0 - 1, box[0] + x1 + 1, box[1] + y1 + 1), fill=bg)
    text = str(spec["text"])
    size = int(spec.get("size") or 0)
    if not size:
        best = None
        for sz in range(6, 60):
            f = load_text_font(sz)
            t = f.getbbox(text)
            gap = abs((t[3] - t[1]) - (y1 - y0 + 1))
            if best is None or gap < best[0]:
                best = (gap, sz)
        size = best[1]
    font = load_text_font(size)
    t = font.getbbox(text)
    d.text((box[0] + x0 - t[0], box[1] + y0 - t[1]), text, fill=color, font=font)
    if box[0] + x0 + (t[2] - t[0]) > box[2]:
        warnings.append("panel %d: replacement text %r is wider than its box" % (index, text))


def hex_rgb(value):
    v = value.lstrip("#")
    return tuple(int(v[i:i + 2], 16) for i in (0, 2, 4))


def label_xy(box, side, tw, th, gap=6):
    x0, y0, x1, y1 = box
    cy = (y0 + y1) // 2 - th // 2
    return {"left": (x0 - tw - gap, cy), "right": (x1 + gap, cy),
            "top": (x0, y0 - th - gap), "bottom": (x0, y1 + gap)}[side]


def inside(xy, tw, th, area):
    x, y = xy
    return x >= area[0] and y >= area[1] and x + tw <= area[2] and y + th <= area[3]


def render_panel(spec, base_dir, style, font, warnings, index):
    from PIL import Image, ImageDraw, ImageFilter
    path = spec["image"] if os.path.isabs(spec["image"]) else os.path.join(base_dir, spec["image"])
    im = Image.open(path).convert("RGB")
    area = tuple(spec.get("crop") or (0, 0, im.width, im.height))
    for r in spec.get("replace", []):
        replace_text(im, r, warnings, index)
    for b in spec.get("blur", []):
        b = tuple(int(v) for v in b)
        im.paste(im.crop(b).filter(ImageFilter.GaussianBlur(9)), b[:2])
    d = ImageDraw.Draw(im)
    color, width = hex_rgb(style["color"]), int(style["width"])
    for m in spec.get("marks", []):
        box = tuple(int(v) for v in m["box"])
        d.rectangle(box, outline=color, width=width)
        label = str(m.get("label", "")).strip()
        if not label:
            continue
        l, t, r, b = d.textbbox((0, 0), label, font=font)
        tw, th = r - l, b - t
        side = m.get("side", "left")
        order = [side] + [s for s in ({"left": "right", "right": "left", "top": "bottom", "bottom": "top"}[side],
                                      "bottom", "top", "right", "left") if s != side]
        for s in order:
            xy = label_xy(box, s, tw, th)
            if inside(xy, tw, th, area):
                break
        else:
            s, xy = side, label_xy(box, side, tw, th)
            warnings.append("panel %d: label %s does not fit on any side of its box" % (index, label))
        if s != side:
            warnings.append("panel %d: label %s moved from %s to %s (would be clipped)" % (index, label, side, s))
        d.text((xy[0] - l, xy[1] - t), label, fill=color, font=font)
    im = im.crop(area)
    if spec.get("frame", True):
        ImageDraw.Draw(im).rectangle((0, 0, im.width - 1, im.height - 1), outline=FRAME_COLOR, width=2)
    return im


def grid(panels, cols, gap):
    from PIL import Image
    rows = [panels[i:i + cols] for i in range(0, len(panels), cols)]
    w = max(sum(p.width for p in r) + gap * (len(r) - 1) for r in rows)
    h = sum(max(p.height for p in r) for r in rows) + gap * (len(rows) - 1)
    out = Image.new("RGB", (w, h), (255, 255, 255))
    y = 0
    for r in rows:
        x = 0
        for p in r:
            out.paste(p, (x, y))
            x += p.width + gap
        y += max(p.height for p in r) + gap
    return out


def main():
    if len(sys.argv) != 2:
        print(__doc__.split("Usage:")[1].split("Prints")[0].strip(), file=sys.stderr)
        sys.exit(1)
    try:
        import PIL  # noqa: F401
    except ImportError:
        print("Pillow is required: pip install Pillow", file=sys.stderr)
        sys.exit(2)
    spec_path = os.path.abspath(sys.argv[1])
    try:
        with open(spec_path, encoding="utf-8") as f:
            spec = json.load(f)
        base_dir = os.path.dirname(spec_path)
        style = dict(DEFAULT_STYLE, **spec.get("style", {}))
        font = load_font(int(style["font_size"]))
        warnings = []
        panels = [render_panel(p, base_dir, style, font, warnings, i) for i, p in enumerate(spec["panels"], 1)]
        out_img = grid(panels, int(spec.get("cols", 1)), int(spec.get("gap", 24)))
        out = spec["output"] if os.path.isabs(spec["output"]) else os.path.join(base_dir, spec["output"])
        out_img.save(out)
    except (OSError, KeyError, ValueError) as e:
        print("annotate failed: %s" % e, file=sys.stderr)
        sys.exit(1)
    print(json.dumps({"output": out, "size": list(out_img.size), "warnings": warnings}, indent=1))


if __name__ == "__main__":
    main()
