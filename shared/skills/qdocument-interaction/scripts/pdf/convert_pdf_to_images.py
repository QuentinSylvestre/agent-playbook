#!/usr/bin/env python3
"""Convert PDF pages to PNG images.

Usage: python convert_pdf_to_images.py <input.pdf> [--output-dir DIR] [--dpi N] [--pages N-M]
Output: PNG files in output directory. JSON summary to stdout.
Exit 0 on success, non-zero on failure.
"""
import json
import os
import sys

def main():
    if len(sys.argv) < 2:
        print("Usage: convert_pdf_to_images.py <input.pdf> [--output-dir DIR] [--dpi N] [--pages N-M]", file=sys.stderr)
        sys.exit(1)

    pdf_path = sys.argv[1]
    output_dir = "."
    dpi = 200
    first_page = None
    last_page = None

    # Parse optional arguments
    args = sys.argv[2:]
    i = 0
    while i < len(args):
        if args[i] == "--output-dir" and i + 1 < len(args):
            output_dir = args[i + 1]
            i += 2
        elif args[i] == "--dpi" and i + 1 < len(args):
            dpi = int(args[i + 1])
            i += 2
        elif args[i] == "--pages" and i + 1 < len(args):
            parts = args[i + 1].split("-")
            first_page = int(parts[0])
            last_page = int(parts[1]) if len(parts) > 1 else first_page
            i += 2
        else:
            i += 1

    try:
        from pdf2image import convert_from_path
    except ImportError:
        print("Error: pdf2image required. Install with: pip install pdf2image", file=sys.stderr)
        print("Also requires poppler: choco install poppler (Win) / brew install poppler (Mac) / apt install poppler-utils (Linux)", file=sys.stderr)
        sys.exit(1)

    os.makedirs(output_dir, exist_ok=True)

    try:
        kwargs = {"dpi": dpi, "fmt": "png"}
        if first_page is not None:
            kwargs["first_page"] = first_page
        if last_page is not None:
            kwargs["last_page"] = last_page

        images = convert_from_path(pdf_path, **kwargs)
    except Exception as e:
        print(f"Error converting PDF: {e}", file=sys.stderr)
        sys.exit(1)

    base_name = os.path.splitext(os.path.basename(pdf_path))[0]
    output_files = []

    for i, image in enumerate(images):
        page_num = (first_page or 1) + i
        filename = f"{base_name}_page_{page_num}.png"
        filepath = os.path.join(output_dir, filename)
        image.save(filepath, "PNG")
        output_files.append(filepath)

    result = {
        "status": "success",
        "pages_converted": len(output_files),
        "output_dir": output_dir,
        "dpi": dpi,
        "files": output_files,
    }
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()
