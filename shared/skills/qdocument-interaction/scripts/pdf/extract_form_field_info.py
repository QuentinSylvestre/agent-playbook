#!/usr/bin/env python3
"""Extract form field metadata from a fillable PDF.

Usage: python extract_form_field_info.py <input.pdf>
Output: JSON array of field objects with name, type, value, options.
Exit 0 on success, non-zero on failure.
"""
import json
import sys

def main():
    if len(sys.argv) < 2:
        print("Usage: extract_form_field_info.py <input.pdf>", file=sys.stderr)
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
    if not fields:
        print(json.dumps([]))
        return

    result = []
    for name, field in fields.items():
        field_info = {
            "name": name,
            "type": field.get("/FT", "unknown"),
            "value": field.get("/V", ""),
            "default_value": field.get("/DV", ""),
            "flags": field.get("/Ff", 0),
        }
        # Map PDF field type codes to readable names
        ft_map = {"/Tx": "text", "/Btn": "button", "/Ch": "choice", "/Sig": "signature"}
        field_info["type_name"] = ft_map.get(field_info["type"], str(field_info["type"]))

        # Extract options for choice fields
        if field_info["type"] == "/Ch" and "/Opt" in field:
            field_info["options"] = [str(o) for o in field["/Opt"]]

        # Clean up value (IndirectObject handling)
        if hasattr(field_info["value"], "get_object"):
            field_info["value"] = str(field_info["value"].get_object())
        else:
            field_info["value"] = str(field_info["value"]) if field_info["value"] else ""

        if hasattr(field_info["default_value"], "get_object"):
            field_info["default_value"] = str(field_info["default_value"].get_object())
        else:
            field_info["default_value"] = str(field_info["default_value"]) if field_info["default_value"] else ""

        result.append(field_info)

    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()
