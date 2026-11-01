#!/usr/bin/env python3
"""Fill non-fillable PDF forms by overlaying text annotations at coordinates.

Usage: python fill_pdf_form_with_annotations.py <input.pdf> <output.pdf> --data '<json>'
       python fill_pdf_form_with_annotations.py <input.pdf> <output.pdf> --data-file data.json

Data format (JSON array):
[
  {"page": 1, "x": 100, "y": 700, "text": "John Doe", "font_size": 10},
  {"page": 1, "x": 100, "y": 650, "text": "123 Main St", "font_size": 10}
]

Coordinates are in PDF points (72 per inch), origin at bottom-left.
Exit 0 on success, non-zero on failure.
"""
import json
import sys

def main():
    if len(sys.argv) < 4:
        print("Usage: fill_pdf_form_with_annotations.py <input.pdf> <output.pdf> --data '<json>' | --data-file <path>", file=sys.stderr)
        sys.exit(1)

    pdf_path = sys.argv[1]
    output_path = sys.argv[2]

    # Parse data argument
    data = None
    if "--data" in sys.argv:
        idx = sys.argv.index("--data")
        if idx + 1 < len(sys.argv):
            try:
                data = json.loads(sys.argv[idx + 1])
            except json.JSONDecodeError as e:
                print(f"Error parsing JSON data: {e}", file=sys.stderr)
                sys.exit(1)
    elif "--data-file" in sys.argv:
        idx = sys.argv.index("--data-file")
        if idx + 1 < len(sys.argv):
            try:
                with open(sys.argv[idx + 1], "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as e:
                print(f"Error reading data file: {e}", file=sys.stderr)
                sys.exit(1)

    if data is None:
        print("Error: --data or --data-file required", file=sys.stderr)
        sys.exit(1)

    try:
        from pypdf import PdfReader, PdfWriter
        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import letter
    except ImportError as e:
        print(f"Error: required packages missing ({e}). Install: pip install 'pypdf>=4.0' reportlab", file=sys.stderr)
        sys.exit(1)

    import io

    try:
        reader = PdfReader(pdf_path)
    except Exception as e:
        print(f"Error reading PDF: {e}", file=sys.stderr)
        sys.exit(1)

    # Group annotations by page
    page_annotations = {}
    for item in data:
        page_num = item.get("page", 1) - 1  # Convert to 0-indexed
        if page_num not in page_annotations:
            page_annotations[page_num] = []
        page_annotations[page_num].append(item)

    writer = PdfWriter()

    for page_idx, page in enumerate(reader.pages):
        if page_idx in page_annotations:
            # Create overlay with annotations
            page_width = float(page.mediabox.width)
            page_height = float(page.mediabox.height)
            packet = io.BytesIO()
            c = canvas.Canvas(packet, pagesize=(page_width, page_height))

            for ann in page_annotations[page_idx]:
                font_size = ann.get("font_size", 10)
                font_name = ann.get("font", "Helvetica")
                c.setFont(font_name, font_size)
                c.drawString(float(ann["x"]), float(ann["y"]), str(ann["text"]))

            c.save()
            packet.seek(0)

            # Merge overlay onto page
            overlay_reader = PdfReader(packet)
            page.merge_page(overlay_reader.pages[0])

        writer.add_page(page)

    try:
        with open(output_path, "wb") as f:
            writer.write(f)
    except Exception as e:
        print(f"Error writing output PDF: {e}", file=sys.stderr)
        sys.exit(1)

    result = {"status": "success", "output": output_path, "annotations_added": len(data)}
    print(json.dumps(result))

if __name__ == "__main__":
    main()
