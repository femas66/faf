#!/usr/bin/env python3
"""Extract or split pages from a PDF document with optional page rotation."""

from __future__ import annotations

import argparse
import os
import sys

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
    """Parse 1-based page range string (e.g. '1-3,7') to 0-based index list."""
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


def split_pdf(
    input_path: str,
    output_pattern: str,
    page_indices: list[int],
    rotation: int = 0,
) -> list[str]:
    reader = pypdf.PdfReader(input_path)
    output_files = []

    # If output pattern contains {page}, output each page separately
    if "{page}" in output_pattern:
        for idx in page_indices:
            writer = pypdf.PdfWriter()
            page = reader.pages[idx]
            if rotation:
                page.rotate(rotation)
            writer.add_page(page)

            out_f = output_pattern.replace("{page}", str(idx + 1))
            os.makedirs(os.path.dirname(os.path.abspath(out_f)), exist_ok=True)
            with open(out_f, "wb") as f_out:
                writer.write(f_out)
            output_files.append(out_f)
    else:
        writer = pypdf.PdfWriter()
        for idx in page_indices:
            page = reader.pages[idx]
            if rotation:
                page.rotate(rotation)
            writer.add_page(page)

        os.makedirs(os.path.dirname(os.path.abspath(output_pattern)), exist_ok=True)
        with open(output_pattern, "wb") as f_out:
            writer.write(f_out)
        output_files.append(output_pattern)

    return output_files


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract and split PDF pages with optional rotation."
    )
    parser.add_argument("pdf", help="Path to input PDF file.")
    parser.add_argument(
        "--pages",
        required=True,
        help="Page numbers or ranges to extract (e.g. '1-3,7', '5-', '1'). 1-based.",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="part.pdf",
        help="Output file path (default: part.pdf). Use '{page}' pattern for single-page files (e.g. 'page_{page}.pdf').",
    )
    parser.add_argument(
        "--rotate",
        type=int,
        default=0,
        choices=[0, 90, 180, 270, -90, -180, -270],
        help="Rotate extracted pages clockwise in degrees (0, 90, 180, 270).",
    )

    args = parser.parse_args()

    if not os.path.isfile(args.pdf):
        print(f"Error: File '{args.pdf}' not found.", file=sys.stderr)
        sys.exit(1)

    try:
        reader = pypdf.PdfReader(args.pdf)
        page_indices = parse_page_range(args.pages, len(reader.pages))

        if not page_indices:
            print("Error: No valid pages selected.", file=sys.stderr)
            sys.exit(1)

        created = split_pdf(args.pdf, args.output, page_indices, rotation=args.rotate)
        print(f"Successfully extracted {len(page_indices)} page(s) into: {', '.join(created)}")
    except Exception as e:
        print(f"Error splitting PDF: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
