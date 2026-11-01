#!/usr/bin/env python3
"""Validate field bounding boxes against PDF page dimensions.

Usage: python check_bounding_boxes.py <input.pdf> --fields '<json>' | --fields-file <path>

Fields format (JSON array):
[
  {"page": 1, "x": 100, "y": 700, "width": 200, "height": 20, "label": "Name"},
  {"page": 1, "x": 100, "y": 650, "width": 200, "height": 20, "label": "Address"}
]

Checks: within page bounds, no overlaps, reasonable sizes.
Exit 0 if all valid, exit 1 if any issues found.
"""
import json
import sys

def boxes_overlap(a, b):
    """Check if two bounding boxes overlap."""
    ax0, ay0 = a["x"], a["y"]
    ax1, ay1 = ax0 + a["width"], ay0 + a["height"]
    bx0, by0 = b["x"], b["y"]
    bx1, by1 = bx0 + b["width"], by0 + b["height"]
    return ax0 < bx1 and ax1 > bx0 and ay0 < by1 and ay1 > by0

def main():
    if len(sys.argv) < 3:
        print("Usage: check_bounding_boxes.py <input.pdf> --fields '<json>' | --fields-file <path>", file=sys.stderr)
        sys.exit(1)

    pdf_path = sys.argv[1]

    # Parse fields argument
    fields = None
    if "--fields" in sys.argv:
        idx = sys.argv.index("--fields")
        if idx + 1 < len(sys.argv):
            try:
                fields = json.loads(sys.argv[idx + 1])
            except json.JSONDecodeError as e:
                print(f"Error parsing JSON: {e}", file=sys.stderr)
                sys.exit(1)
    elif "--fields-file" in sys.argv:
        idx = sys.argv.index("--fields-file")
        if idx + 1 < len(sys.argv):
            try:
                with open(sys.argv[idx + 1], "r", encoding="utf-8") as f:
                    fields = json.load(f)
            except Exception as e:
                print(f"Error reading fields file: {e}", file=sys.stderr)
                sys.exit(1)

    if fields is None:
        print("Error: --fields or --fields-file required", file=sys.stderr)
        sys.exit(1)

    try:
        from pypdf import PdfReader
    except ImportError:
        print("Error: pypdf>=4.0 required. Install with: pip install 'pypdf>=4.0'", file=sys.stderr)
        sys.exit(1)

    try:
        reader = PdfReader(pdf_path)
    except Exception as e:
        print(f"Error reading PDF: {e}", file=sys.stderr)
        sys.exit(1)

    issues = []

    # Get page dimensions
    page_dims = {}
    for i, page in enumerate(reader.pages):
        box = page.mediabox
        page_dims[i + 1] = {"width": float(box.width), "height": float(box.height)}

    for i, field in enumerate(fields):
        page_num = field.get("page", 1)
        label = field.get("label", f"field_{i}")
        x = float(field.get("x", 0))
        y = float(field.get("y", 0))
        w = float(field.get("width", 0))
        h = float(field.get("height", 0))

        # Check page exists
        if page_num not in page_dims:
            issues.append({"field": label, "issue": "page_not_found", "detail": f"Page {page_num} does not exist"})
            continue

        dims = page_dims[page_num]

        # Check within page bounds
        if x < 0 or y < 0:
            issues.append({"field": label, "issue": "negative_coords", "detail": f"x={x}, y={y}"})
        if x + w > dims["width"]:
            issues.append({"field": label, "issue": "exceeds_width", "detail": f"x+w={x+w} > page_width={dims['width']}"})
        if y + h > dims["height"]:
            issues.append({"field": label, "issue": "exceeds_height", "detail": f"y+h={y+h} > page_height={dims['height']}"})

        # Check reasonable size
        if w <= 0 or h <= 0:
            issues.append({"field": label, "issue": "invalid_size", "detail": f"width={w}, height={h}"})
        elif w < 5 or h < 5:
            issues.append({"field": label, "issue": "too_small", "detail": f"width={w}, height={h}"})

    # Check overlaps between fields on the same page
    for i in range(len(fields)):
        for j in range(i + 1, len(fields)):
            if fields[i].get("page", 1) != fields[j].get("page", 1):
                continue
            if boxes_overlap(fields[i], fields[j]):
                label_i = fields[i].get("label", f"field_{i}")
                label_j = fields[j].get("label", f"field_{j}")
                issues.append({"field": f"{label_i}/{label_j}", "issue": "overlap", "detail": "Fields overlap"})

    result = {
        "valid": len(issues) == 0,
        "fields_checked": len(fields),
        "issues_found": len(issues),
        "issues": issues,
    }
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["valid"] else 1)

if __name__ == "__main__":
    main()
