"""List or swap images embedded in a .docx without touching the document XML.

Swapping replaces the bytes of word/media/imageN.* in place, so the image keeps
its size and position and no revision is recorded. Use it to fix a screenshot
that is already in the document (relabel, blur, correct a value).

The embedded file is found by content, not by name: Word renumbers media files
when it saves and may downsample large images on insert. A match needs the same
aspect ratio (within 2 %) and a close grayscale thumbnail. The replacement is
resized to the stored pixel size.

Usage:
    python docx_media.py list <file.docx>
    python docx_media.py swap <in.docx> <out.docx> --map ORIGINAL.png=EDITED.png [--map ...]

ORIGINAL is the image as it was inserted (before your edit); EDITED is the new
version. Requires Pillow.

Exit codes: 0 = success, 1 = an original matched zero or several media files,
2 = usage error
"""
import io
import json
import sys
import zipfile

THUMB = (64, 32)
MAX_DISTANCE = 3.0  # mean absolute grayscale difference on the thumbnail (0-255)
MAX_RATIO_DELTA = 0.02


def _open(data):
    from PIL import Image
    return Image.open(io.BytesIO(data)).convert("RGB")


def distance(a, b):
    """Mean grayscale difference between two images on a small thumbnail."""
    from PIL import Image
    if a.size != b.size:
        b = b.resize(a.size, Image.LANCZOS)
    ta = a.convert("L").resize(THUMB).tobytes()
    tb = b.convert("L").resize(THUMB).tobytes()
    return sum(abs(x - y) for x, y in zip(ta, tb)) / float(len(ta))


def media_images(zin):
    out = {}
    for info in zin.infolist():
        if info.filename.startswith("word/media/"):
            try:
                out[info.filename] = _open(zin.read(info.filename))
            except Exception:
                pass  # EMF/WMF and other formats Pillow cannot read
    return out


def match(original, images):
    ratio = original.size[0] / float(original.size[1])
    hits = []
    for name, im in images.items():
        if abs(im.size[0] / float(im.size[1]) - ratio) / ratio > MAX_RATIO_DELTA:
            continue
        d = distance(im, original)
        if d < MAX_DISTANCE:
            hits.append((d, name))
    return sorted(hits)


def cmd_list(path):
    with zipfile.ZipFile(path) as z:
        for name, im in sorted(media_images(z).items()):
            print("%s %dx%d" % (name, im.size[0], im.size[1]))
    return 0


def cmd_swap(src, dst, pairs):
    from PIL import Image
    zin = zipfile.ZipFile(src)
    images = media_images(zin)
    replacements, report, failed = {}, [], False
    for orig_path, new_path in pairs:
        original = Image.open(orig_path).convert("RGB")
        hits = match(original, images)
        if len(hits) != 1:
            failed = True
            report.append({"original": orig_path, "error": "%d matches" % len(hits),
                           "matches": [h[1] for h in hits]})
            continue
        name = hits[0][1]
        stored = images[name]
        edited = Image.open(new_path).convert("RGB")
        if edited.size != stored.size:
            edited = edited.resize(stored.size, Image.LANCZOS)
        buf = io.BytesIO()
        fmt = "PNG" if name.lower().endswith(".png") else "JPEG"
        edited.save(buf, fmt)
        replacements[name] = buf.getvalue()
        report.append({"original": orig_path, "media": name, "size": list(stored.size),
                       "distance": round(hits[0][0], 2)})
    if not failed:
        with zipfile.ZipFile(dst, "w") as zout:
            for info in zin.infolist():
                data = replacements.get(info.filename, zin.read(info.filename))
                zout.writestr(info, data, compress_type=info.compress_type)
    print(json.dumps({"ok": not failed, "swaps": report}, indent=2))
    return 1 if failed else 0


def main():
    import argparse
    parser = argparse.ArgumentParser(description="List or swap images embedded in a .docx")
    sub = parser.add_subparsers(dest="cmd")
    p_list = sub.add_parser("list")
    p_list.add_argument("docx")
    p_swap = sub.add_parser("swap")
    p_swap.add_argument("src")
    p_swap.add_argument("dst")
    p_swap.add_argument("--map", action="append", required=True, metavar="ORIGINAL=EDITED")
    args = parser.parse_args()
    if args.cmd == "list":
        sys.exit(cmd_list(args.docx))
    if args.cmd == "swap":
        pairs = []
        for m in args.map:
            if "=" not in m:
                print("--map needs ORIGINAL=EDITED, got %r" % m)
                sys.exit(2)
            pairs.append(tuple(m.split("=", 1)))
        sys.exit(cmd_swap(args.src, args.dst, pairs))
    parser.print_help()
    sys.exit(2)


if __name__ == "__main__":
    main()
