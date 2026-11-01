"""Generate a visual grid of slide thumbnails from a .pptx file.

Converts the presentation to PDF via LibreOffice, splits into page images,
then composes a grid using Pillow.

Usage:
    python thumbnail.py <input.pptx> --output <grid.png> [--cols <N>] [--width <px>]

Exit codes: 0 = success, 1 = failure, 2 = missing dependency
"""
import os
import subprocess
import sys
import tempfile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SOFFICE_SCRIPT = os.path.join(SCRIPT_DIR, "..", "office", "soffice.py")


def _convert_to_pdf(pptx_path, out_dir):
    """Convert pptx to PDF via soffice.py."""
    result = subprocess.run(
        [sys.executable, SOFFICE_SCRIPT, "--convert-to", "pdf", pptx_path, "--outdir", out_dir],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print("LibreOffice conversion failed: %s" % result.stderr.strip(), file=sys.stderr)
        return None
    base = os.path.splitext(os.path.basename(pptx_path))[0]
    pdf_path = os.path.join(out_dir, base + ".pdf")
    if os.path.isfile(pdf_path):
        return pdf_path
    # Fallback: find any PDF in output dir
    for f in os.listdir(out_dir):
        if f.endswith(".pdf"):
            return os.path.join(out_dir, f)
    return None


def _pdf_to_images(pdf_path, out_dir, dpi=150):
    """Convert PDF pages to PNG images using pdftoppm or Pillow/pdf2image."""
    from shutil import which
    if which("pdftoppm"):
        prefix = os.path.join(out_dir, "slide")
        result = subprocess.run(
            ["pdftoppm", "-png", "-r", str(dpi), pdf_path, prefix],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            print("pdftoppm failed: %s" % result.stderr.strip(), file=sys.stderr)
            return []
    else:
        # Fallback: try pdf2image (Python package wrapping poppler)
        try:
            from pdf2image import convert_from_path
            images = convert_from_path(pdf_path, dpi=dpi)
            for i, img in enumerate(images, 1):
                img.save(os.path.join(out_dir, "slide-%02d.png" % i))
        except ImportError:
            print("Neither pdftoppm nor pdf2image available. Install poppler-utils or `pip install pdf2image`.", file=sys.stderr)
            return []

    # Collect generated images
    imgs = sorted(f for f in os.listdir(out_dir) if f.startswith("slide") and f.endswith(".png"))
    return [os.path.join(out_dir, f) for f in imgs]


def _compose_grid(image_paths, output_path, cols=3, thumb_width=400):
    """Compose images into a grid."""
    try:
        from PIL import Image
    except ImportError:
        print("Pillow not installed. Run: pip install Pillow", file=sys.stderr)
        sys.exit(2)

    if not image_paths:
        print("No slide images to compose", file=sys.stderr)
        return False

    thumbs = []
    for p in image_paths:
        img = Image.open(p)
        ratio = thumb_width / img.width
        new_h = int(img.height * ratio)
        thumbs.append(img.resize((thumb_width, new_h), Image.LANCZOS))

    rows = (len(thumbs) + cols - 1) // cols
    thumb_height = max(t.height for t in thumbs)
    padding = 10

    grid_w = cols * thumb_width + (cols + 1) * padding
    grid_h = rows * thumb_height + (rows + 1) * padding

    grid = Image.new("RGB", (grid_w, grid_h), (255, 255, 255))

    for i, thumb in enumerate(thumbs):
        row = i // cols
        col = i % cols
        x = padding + col * (thumb_width + padding)
        y = padding + row * (thumb_height + padding)
        grid.paste(thumb, (x, y))

    grid.save(output_path)
    return True


def main():
    if len(sys.argv) < 2:
        print("Usage: thumbnail.py <input.pptx> --output <grid.png> [--cols N] [--width px]", file=sys.stderr)
        sys.exit(1)

    pptx_path = sys.argv[1]
    output_path = "grid.png"
    cols = 3
    thumb_width = 400

    args = sys.argv[2:]
    i = 0
    while i < len(args):
        if args[i] == "--output" and i + 1 < len(args):
            output_path = args[i + 1]
            i += 2
        elif args[i] == "--cols" and i + 1 < len(args):
            cols = int(args[i + 1])
            i += 2
        elif args[i] == "--width" and i + 1 < len(args):
            thumb_width = int(args[i + 1])
            i += 2
        else:
            print("Unknown argument: %s" % args[i], file=sys.stderr)
            sys.exit(1)

    if not os.path.isfile(pptx_path):
        print("File not found: %s" % pptx_path, file=sys.stderr)
        sys.exit(1)

    with tempfile.TemporaryDirectory() as tmp_dir:
        pdf_path = _convert_to_pdf(pptx_path, tmp_dir)
        if not pdf_path:
            print("Failed to convert to PDF", file=sys.stderr)
            sys.exit(1)

        image_paths = _pdf_to_images(pdf_path, tmp_dir)
        if not image_paths:
            print("Failed to generate slide images", file=sys.stderr)
            sys.exit(1)

        if _compose_grid(image_paths, output_path, cols, thumb_width):
            print("Thumbnail grid saved to %s (%d slides)" % (output_path, len(image_paths)))
            sys.exit(0)
        else:
            sys.exit(1)


if __name__ == "__main__":
    main()
