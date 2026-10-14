#!/usr/bin/env python3
"""Read, inspect, and extract text, tables, metadata, and form fields from PDF files."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from typing import Any

try:
    import pypdf
except ImportError as err:
    print(
        f"Error: Required library 'pypdf' is missing ({err}).\n"
        f"Install it via: pip install pypdf",
        file=sys.stderr,
    )
    sys.exit(1)


def parse_page_range(pages_str: str | None, max_pages: int) -> list[int]:
    """Parse 1-based page range string (e.g. '1-3,5') to 0-based index list."""
    if not pages_str:
        return list(range(max_pages))
    result = set()
    for part in pages_str.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_s, end_s = part.split("-", 1)
            start = int(start_s) if start_s else 1
            end = int(end_s) if end_s else max_pages
            for p in range(max(1, start), min(max_pages, end) + 1):
                result.add(p - 1)
        else:
            p = int(part)
            if 1 <= p <= max_pages:
                result.add(p - 1)
    return sorted(list(result))


def extract_text(pdf_path: str, page_indices: list[int], raw: bool = False) -> dict[str, Any] | str:
    reader = pypdf.PdfReader(pdf_path)
    pages_data = []
    raw_texts = []

    for idx in page_indices:
        page = reader.pages[idx]
        text = page.extract_text() or ""
        box = page.mediabox
        pages_data.append({
            "page": idx + 1,
            "width": float(box.width),
            "height": float(box.height),
            "char_count": len(text),
            "text": text,
        })
        raw_texts.append(f"--- Page {idx + 1} ---\n{text}")

    if raw:
        return "\n\n".join(raw_texts)
    return {"file": pdf_path, "total_pages": len(reader.pages), "pages": pages_data}


def extract_tables(pdf_path: str, page_indices: list[int], csv_dir: str | None = None) -> dict[str, Any]:
    try:
        import pdfplumber
    except ImportError:
        print("Error: 'pdfplumber' is required for table extraction. Run: pip install pdfplumber", file=sys.stderr)
        sys.exit(1)

    tables_out = []
    if csv_dir:
        os.makedirs(csv_dir, exist_ok=True)

    with pdfplumber.open(pdf_path) as pdf:
        for idx in page_indices:
            if idx >= len(pdf.pages):
                continue
            page = pdf.pages[idx]
            extracted = page.extract_tables()
            for t_idx, table in enumerate(extracted):
                cleaned_rows = []
                for row in table:
                    cleaned_rows.append([cell if cell is not None else "" for cell in row])
                
                table_item = {
                    "page": idx + 1,
                    "table_index": t_idx + 1,
                    "row_count": len(cleaned_rows),
                    "col_count": len(cleaned_rows[0]) if cleaned_rows else 0,
                    "rows": cleaned_rows,
                }
                tables_out.append(table_item)

                if csv_dir:
                    csv_filename = os.path.join(csv_dir, f"table_p{idx + 1}_{t_idx + 1}.csv")
                    with open(csv_filename, "w", newline="", encoding="utf-8") as f:
                        writer = csv.writer(f)
                        writer.writerows(cleaned_rows)
                    table_item["csv_path"] = csv_filename

    return {"file": pdf_path, "tables_count": len(tables_out), "tables": tables_out}


def extract_metadata(pdf_path: str) -> dict[str, Any]:
    reader = pypdf.PdfReader(pdf_path)
    meta = reader.metadata or {}

    total_pages = len(reader.pages)
    total_chars = 0
    has_images = False
    page_sizes = []

    for idx, page in enumerate(reader.pages):
        box = page.mediabox
        page_sizes.append({
            "page": idx + 1,
            "width": float(box.width),
            "height": float(box.height),
            "rotation": int(page.get("/Rotate", 0) or 0),
        })
        text = page.extract_text() or ""
        total_chars += len(text)
        if len(page.images) > 0:
            has_images = True

    avg_chars_per_page = total_chars / max(1, total_pages)
    is_scanned = (avg_chars_per_page < 30 and has_images)

    scanned_heuristic = {
        "is_scanned": is_scanned,
        "confidence": "high" if (avg_chars_per_page < 10 and has_images) else ("medium" if is_scanned else "low"),
        "total_chars": total_chars,
        "avg_chars_per_page": round(avg_chars_per_page, 1),
        "has_images": has_images,
        "recommendation": "Use OCR (Firecrawl web_extract for URLs or local OCR) to extract text." if is_scanned else "Native text available.",
    }

    info = {
        "file": pdf_path,
        "is_encrypted": reader.is_encrypted,
        "total_pages": total_pages,
        "metadata": {
            "title": meta.get("/Title"),
            "author": meta.get("/Author"),
            "subject": meta.get("/Subject"),
            "creator": meta.get("/Creator"),
            "producer": meta.get("/Producer"),
            "creation_date": str(meta.get("/CreationDate", "")),
            "mod_date": str(meta.get("/ModDate", "")),
        },
        "pages": page_sizes,
        "scanned_detection": scanned_heuristic,
    }
    return info


def extract_fields(pdf_path: str) -> dict[str, Any]:
    reader = pypdf.PdfReader(pdf_path)
    fields_dict = reader.get_fields() or {}

    fields_list = []
    for name, f_obj in fields_dict.items():
        field_type = str(f_obj.get("/FT", "unknown"))
        type_map = {
            "/Tx": "text",
            "/Btn": "button/checkbox/radio",
            "/Ch": "choice/dropdown",
            "/Sig": "signature",
        }
        human_type = type_map.get(field_type, field_type)
        val = f_obj.get("/V")
        default_val = f_obj.get("/DV")

        fields_list.append({
            "name": name,
            "type": human_type,
            "raw_type": field_type,
            "value": str(val) if val is not None else None,
            "default_value": str(default_val) if default_val is not None else None,
            "read_only": bool(f_obj.get("/Ff", 0) & 1),
        })

    return {
        "file": pdf_path,
        "fields_count": len(fields_list),
        "has_form": len(fields_list) > 0,
        "fields": fields_list,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract text, tables, metadata, and form fields from PDF documents."
    )
    parser.add_argument("pdf", help="Path to PDF file.")
    parser.add_argument("--text", action="store_true", help="Extract text per page (JSON format).")
    parser.add_argument("--raw", action="store_true", help="Output raw plain text instead of JSON (when with --text).")
    parser.add_argument("--tables", action="store_true", help="Extract structured tables.")
    parser.add_argument("--csv-dir", help="Directory to export extracted tables as CSV files.")
    parser.add_argument("--meta", action="store_true", help="Extract document metadata, page sizes, encrypted and scanned flags.")
    parser.add_argument("--fields", action="store_true", help="Extract AcroForm fields (names, types, values).")
    parser.add_argument("--pages", help="Page range filter (e.g. '1-3,5').")
    parser.add_argument("-o", "--output", help="Write JSON output to file instead of stdout.")

    args = parser.parse_args()

    if not os.path.isfile(args.pdf):
        print(f"Error: File '{args.pdf}' not found.", file=sys.stderr)
        sys.exit(1)

    if not any([args.text, args.tables, args.meta, args.fields]):
        # Default to --text if no option specified
        args.text = True

    try:
        reader = pypdf.PdfReader(args.pdf)
        page_indices = parse_page_range(args.pages, len(reader.pages))

        result: Any = {}

        if args.meta:
            result = extract_metadata(args.pdf)
        elif args.fields:
            result = extract_fields(args.pdf)
        elif args.tables:
            result = extract_tables(args.pdf, page_indices, csv_dir=args.csv_dir)
        elif args.text:
            text_res = extract_text(args.pdf, page_indices, raw=args.raw)
            if args.raw and isinstance(text_res, str):
                if args.output:
                    with open(args.output, "w", encoding="utf-8") as f:
                        f.write(text_res)
                else:
                    print(text_res)
                return
            result = text_res

        out_json = json.dumps(result, indent=2, ensure_ascii=False)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(out_json)
            print(f"Results saved to: {args.output}")
        else:
            print(out_json)

    except Exception as e:
        print(f"Error processing PDF '{args.pdf}': {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
