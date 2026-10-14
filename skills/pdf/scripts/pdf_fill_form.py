#!/usr/bin/env python3
"""Fill AcroForm fields in a PDF with values from JSON, with optional field flattening."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

try:
    import pymupdf
except ImportError as err:
    print(
        f"Error: Required library 'pymupdf' is missing ({err}).\n"
        f"Install it via: pip install pymupdf",
        file=sys.stderr,
    )
    sys.exit(1)


def parse_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    s = str(v).strip().lower()
    return s in ("true", "1", "yes", "on", "checked", "y")


def fill_form(
    pdf_path: str,
    output_path: str,
    field_values: dict[str, Any],
    flatten: bool = False,
) -> int:
    doc = pymupdf.open(pdf_path)
    updated_count = 0
    all_fields: set[str] = set()

    for page in doc:
        for widget in page.widgets():
            fname = widget.field_name
            all_fields.add(fname)
            if fname in field_values:
                val = field_values[fname]
                if widget.field_type == pymupdf.PDF_WIDGET_TYPE_CHECKBOX:
                    widget.field_value = parse_bool(val)
                elif widget.field_type == pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON:
                    widget.field_value = str(val)
                else:
                    widget.field_value = str(val) if val is not None else ""
                widget.update()
                updated_count += 1

    unmatched = set(field_values.keys()) - all_fields
    if unmatched:
        print(f"Warning: The following fields were in input data but not found in PDF form: {sorted(list(unmatched))}", file=sys.stderr)

    if flatten:
        # Bake annotations and widgets into page content
        doc.bake()

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    doc.save(output_path)
    doc.close()
    return updated_count


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fill interactive AcroForm fields in a PDF document from JSON."
    )
    parser.add_argument("form", help="Path to input fillable PDF form.")
    parser.add_argument("--fields-json", help="Path to JSON file with field values (or '-' for stdin).")
    parser.add_argument(
        "--field",
        action="append",
        metavar="KEY=VALUE",
        help="Specify individual field values on CLI (repeatable, e.g. --field name='John Doe').",
    )
    parser.add_argument("-o", "--output", default="filled.pdf", help="Output filled PDF path (default: filled.pdf).")
    parser.add_argument(
        "--flatten",
        action="store_true",
        help="Flatten/bake form fields, converting them to permanent static content.",
    )

    args = parser.parse_args()

    if not os.path.isfile(args.form):
        print(f"Error: Form file '{args.form}' not found.", file=sys.stderr)
        sys.exit(1)

    values: dict[str, Any] = {}

    if args.fields_json:
        try:
            if args.fields_json == "-":
                values.update(json.load(sys.stdin))
            else:
                with open(args.fields_json, "r", encoding="utf-8") as f:
                    values.update(json.load(f))
        except Exception as e:
            print(f"Error loading fields JSON: {e}", file=sys.stderr)
            sys.exit(1)

    if args.field:
        for item in args.field:
            if "=" in item:
                k, v = item.split("=", 1)
                values[k.strip()] = v.strip()
            else:
                values[item.strip()] = ""

    if not values:
        print("Error: No field values provided. Use --fields-json or --field KEY=VALUE.", file=sys.stderr)
        sys.exit(1)

    try:
        updated = fill_form(args.form, args.output, values, flatten=args.flatten)
        status = "flattened" if args.flatten else "editable"
        print(f"Successfully filled {updated} field(s) ({status}) into: {args.output}")
    except Exception as e:
        print(f"Error filling PDF form: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
