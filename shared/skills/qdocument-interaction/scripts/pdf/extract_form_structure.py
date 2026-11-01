#!/usr/bin/env python3
"""Extract visual form structure (labels, lines, checkboxes) with coordinates.

Usage: python extract_form_structure.py <input.pdf> [--page N]
Output: JSON with text elements, lines, and rectangles per page.
Exit 0 on success, non-zero on failure.
"""
import json
import sys

def main():
    if len(sys.argv) < 2:
        print("Usage: extract_form_structure.py <input.pdf> [--page N]", file=sys.stderr)
        sys.exit(1)

    pdf_path = sys.argv[1]
    target_page = None
    if "--page" in sys.argv:
        idx = sys.argv.index("--page")
        if idx + 1 < len(sys.argv):
            target_page = int(sys.argv[idx + 1]) - 1  # Convert to 0-indexed

    try:
        import pdfplumber
    except ImportError:
        print("Error: pdfplumber required. Install with: pip install pdfplumber", file=sys.stderr)
        sys.exit(1)

    try:
        pdf = pdfplumber.open(pdf_path)
    except Exception as e:
        print(f"Error reading PDF: {e}", file=sys.stderr)
        sys.exit(1)

    result = {"pages": [], "page_count": len(pdf.pages)}

    pages_to_process = [pdf.pages[target_page]] if target_page is not None else pdf.pages

    for page in pages_to_process:
        page_data = {
            "page_number": page.page_number,
            "width": float(page.width),
            "height": float(page.height),
            "text_elements": [],
            "lines": [],
            "rectangles": [],
        }

        # Extract text with positions
        words = page.extract_words()
        for w in words:
            page_data["text_elements"].append({
                "text": w["text"],
                "x0": round(float(w["x0"]), 2),
                "top": round(float(w["top"]), 2),
                "x1": round(float(w["x1"]), 2),
                "bottom": round(float(w["bottom"]), 2),
            })

        # Extract lines (potential form field boundaries)
        if page.lines:
            for line in page.lines:
                page_data["lines"].append({
                    "x0": round(float(line["x0"]), 2),
                    "top": round(float(line["top"]), 2),
                    "x1": round(float(line["x1"]), 2),
                    "bottom": round(float(line["bottom"]), 2),
                    "orientation": "horizontal" if abs(float(line["top"]) - float(line["bottom"])) < 1 else "vertical",
                })

        # Extract rectangles (potential checkboxes or field borders)
        if page.rects:
            for rect in page.rects:
                w = float(rect["x1"]) - float(rect["x0"])
                h = float(rect["bottom"]) - float(rect["top"])
                page_data["rectangles"].append({
                    "x0": round(float(rect["x0"]), 2),
                    "top": round(float(rect["top"]), 2),
                    "x1": round(float(rect["x1"]), 2),
                    "bottom": round(float(rect["bottom"]), 2),
                    "width": round(w, 2),
                    "height": round(h, 2),
                    "likely_checkbox": 5 < w < 20 and 5 < h < 20,
                })

        result["pages"].append(page_data)

    pdf.close()
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()
