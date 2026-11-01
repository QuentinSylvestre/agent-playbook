#!/usr/bin/env python3
"""Detect whether a PDF has fillable AcroForm fields.

Usage: python check_fillable_fields.py <input.pdf>
Output: JSON to stdout with has_fields (bool) and field_count (int).
Exit 0 on success, non-zero on failure.
"""
import json
import sys

def main():
    if len(sys.argv) < 2:
        print("Usage: check_fillable_fields.py <input.pdf>", file=sys.stderr)
        sys.exit(1)

    pdf_path = sys.argv[1]

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

    fields = reader.get_fields()
    has_fields = fields is not None and len(fields) > 0
    field_count = len(fields) if fields else 0

    result = {"has_fields": has_fields, "field_count": field_count}
    print(json.dumps(result))

if __name__ == "__main__":
    main()
