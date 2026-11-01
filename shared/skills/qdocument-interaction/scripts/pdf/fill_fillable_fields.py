#!/usr/bin/env python3
"""Fill fillable AcroForm fields in a PDF.

Usage: python fill_fillable_fields.py <input.pdf> <output.pdf> --data '<json>'
       python fill_fillable_fields.py <input.pdf> <output.pdf> --data-file data.json
Output: Writes filled PDF to output path.
Exit 0 on success, non-zero on failure.
"""
import json
import sys

def main():
    if len(sys.argv) < 4:
        print("Usage: fill_fillable_fields.py <input.pdf> <output.pdf> --data '<json>' | --data-file <path>", file=sys.stderr)
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
    except ImportError:
        print("Error: pypdf>=4.0 required. Install with: pip install 'pypdf>=4.0'", file=sys.stderr)
        sys.exit(1)

    try:
        reader = PdfReader(pdf_path)
    except Exception as e:
        print(f"Error reading PDF: {e}", file=sys.stderr)
        sys.exit(1)

    writer = PdfWriter()
    writer.append(reader)

    # Fill fields on all pages
    filled_count = 0
    for page_num in range(len(writer.pages)):
        try:
            writer.update_page_form_field_values(
                writer.pages[page_num], data, auto_regenerate=False
            )
            filled_count += len(data)
        except Exception:
            pass  # Page may not have the fields — continue

    try:
        with open(output_path, "wb") as f:
            writer.write(f)
    except Exception as e:
        print(f"Error writing output PDF: {e}", file=sys.stderr)
        sys.exit(1)

    result = {"status": "success", "output": output_path, "fields_provided": len(data)}
    print(json.dumps(result))

if __name__ == "__main__":
    main()
