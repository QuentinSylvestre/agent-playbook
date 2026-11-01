"""Export slides of a .pptx as PNG images through PowerPoint (Windows), cropped to their content.

Made for turning a screenshot-per-slide deck (a setup guide, a how-to) into document images:
the slide's text placeholders (title, step text, footer, date, slide number) and the master
graphics are left out, and the image is cropped to the remaining shapes, with the arrows,
boxes and callouts drawn over the screenshots kept. Use --full for a whole-slide export,
such as an architecture diagram, and --hide to leave out named shapes (a caption).

The deck is opened read-only and never saved; shapes are removed from the in-memory copy only.

Usage:
    python export_slide_images.py <deck.pptx> <out_dir> [--slides 12,13,20-25] [--width 2667]
                                  [--full] [--keep-placeholders] [--hide NAME ...] [--pad 4]

Writes <out_dir>/s<NN>.png per slide and prints JSON: [{"slide", "file", "size", "removed", "kept"}].
Slides left with no shape after the removal are reported with "file": null.

Exit codes: 0 = success, 1 = failure, 2 = PowerPoint or pywin32 not available
"""
import argparse
import json
import os
import sys

PLACEHOLDER, GROUP = 14, 6
PICTURE_CONTENT = 13  # PlaceholderFormat.ContainedType of a picture placeholder: keep it


def parse_slides(spec, count):
    if not spec:
        return list(range(1, count + 1))
    out = []
    for part in spec.split(","):
        a, _, b = part.strip().partition("-")
        out.extend(range(int(a), int(b or a) + 1))
    bad = [n for n in out if not 1 <= n <= count]
    if bad:
        raise ValueError("slides out of range 1-%d: %s" % (count, bad))
    return out


def text_placeholders(slide):
    found = []
    for i in range(1, slide.Shapes.Count + 1):
        shp = slide.Shapes(i)
        if shp.Type == PLACEHOLDER:
            try:
                if shp.PlaceholderFormat.ContainedType == PICTURE_CONTENT:
                    continue
            except Exception:
                pass
            found.append(shp)
    return found


def export(pres, n, out_dir, width, full, keep_ph, hide, pad):
    from PIL import Image
    s = pres.Slides(n)
    sw, sh = pres.PageSetup.SlideWidth, pres.PageSetup.SlideHeight
    k = width / sw
    removed = []
    for i in range(s.Shapes.Count, 0, -1):
        if s.Shapes(i).Name in hide:
            removed.append(s.Shapes(i).Name)
            s.Shapes(i).Delete()
    if not full:
        s.DisplayMasterShapes = False
        if not keep_ph:
            # A single pass can leave placeholders behind: delete until none remain.
            for _ in range(5):
                phs = text_placeholders(s)
                if not phs:
                    break
                for shp in phs:
                    removed.append(shp.Name)
                    shp.Delete()
    boxes, kept = [], []
    for i in range(1, s.Shapes.Count + 1):
        shp = s.Shapes(i)
        if not full and shp.Type == PLACEHOLDER and not keep_ph:
            continue
        l, t = max(shp.Left, 0), max(shp.Top, 0)
        r, b = min(shp.Left + shp.Width, sw), min(shp.Top + shp.Height, sh)
        if r > l and b > t:
            boxes.append((l, t, r, b))
            kept.append(shp.Name)
    if not full and not boxes:
        return {"slide": n, "file": None, "size": None, "removed": removed, "kept": kept}
    out = os.path.join(out_dir, "s%02d.png" % n)
    s.Export(out, "PNG", int(width), int(sh * k))
    im = Image.open(out)
    if not full:
        L = min(x[0] for x in boxes) * k - pad
        T = min(x[1] for x in boxes) * k - pad
        R = max(x[2] for x in boxes) * k + pad
        B = max(x[3] for x in boxes) * k + pad
        im = im.crop((max(int(L), 0), max(int(T), 0), min(int(R), im.width), min(int(B), im.height)))
        im.save(out)
    return {"slide": n, "file": out, "size": list(im.size), "removed": removed, "kept": kept}


def main():
    ap = argparse.ArgumentParser(description="Export cropped slide images through PowerPoint")
    ap.add_argument("pptx")
    ap.add_argument("out_dir")
    ap.add_argument("--slides", help="1-based list and ranges, e.g. 12,13,20-25 (default: all)")
    ap.add_argument("--width", type=int, default=2667, help="export width in pixels (default 2667, about 200 dpi)")
    ap.add_argument("--full", action="store_true", help="whole slide, with placeholders and master graphics")
    ap.add_argument("--keep-placeholders", action="store_true", help="keep text placeholders in the crop")
    ap.add_argument("--hide", action="append", default=[], help="shape name to leave out (repeatable)")
    ap.add_argument("--pad", type=int, default=4, help="crop margin in pixels")
    args = ap.parse_args()
    if not os.path.isfile(args.pptx):
        print("file not found: %s" % args.pptx, file=sys.stderr)
        sys.exit(1)
    try:
        import win32com.client
        from PIL import Image  # noqa: F401
    except ImportError as e:
        print("missing dependency: %s (needs pywin32 and Pillow, Windows with PowerPoint)" % e, file=sys.stderr)
        sys.exit(2)
    os.makedirs(args.out_dir, exist_ok=True)
    try:
        app = win32com.client.DispatchEx("PowerPoint.Application")
    except Exception as e:
        print("PowerPoint not available: %s" % e, file=sys.stderr)
        sys.exit(2)
    results = []
    try:
        pres = app.Presentations.Open(os.path.abspath(args.pptx), True, False, False)  # read-only, no window
        try:
            for n in parse_slides(args.slides, pres.Slides.Count):
                results.append(export(pres, n, os.path.abspath(args.out_dir), args.width, args.full,
                                      args.keep_placeholders, set(args.hide), args.pad))
        finally:
            pres.Close()
    except Exception as e:
        print("export failed: %s" % e, file=sys.stderr)
        sys.exit(1)
    finally:
        app.Quit()
    print(json.dumps(results, indent=1))


if __name__ == "__main__":
    main()
