#!/usr/bin/env python3
"""Apply PDF watermark or stamp document over or under pages."""

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


def parse_page_range(pages_str: str | None, max_pages: int) -> set[int]:
    if not pages_str:
        return set(range(max_pages))
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
    return result


def apply_watermark(
    doc_path: str,
    stamp_path: str,
    output_path: str,
    under: bool = False,
    pages_filter: str | None = None,
) -> None:
    doc_reader = pypdf.PdfReader(doc_path)
    stamp_reader = pypdf.PdfReader(stamp_path)

    if len(stamp_reader.pages) == 0:
        raise ValueError("Stamp/watermark PDF has no pages.")

    stamp_page = stamp_reader.pages[0]
    writer = pypdf.PdfWriter()

    target_pages = parse_page_range(pages_filter, len(doc_reader.pages))

    for idx, page in enumerate(doc_reader.pages):
        if idx in target_pages:
            # Clone stamp page to avoid mutation conflicts
            page.merge_page(stamp_page, over=not under)
        writer.add_page(page)

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "wb") as f_out:
        writer.write(f_out)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Apply watermark or stamp from a PDF file onto another PDF."
    )
    parser.add_argument("pdf", help="Path to input PDF document.")
    parser.add_argument("--stamp", required=True, help="Path to watermark/stamp PDF file.")
    parser.add_argument("-o", "--output", default="stamped.pdf", help="Output PDF path (default: stamped.pdf).")
    parser.add_argument(
        "--under",
        action="store_true",
        help="Place watermark underneath existing page content (background). Default is overlay on top.",
    )
    parser.add_argument(
        "--pages",
        help="Target pages to stamp (e.g. '1-3,5'). Default: all pages.",
    )

    args = parser.parse_args()

    if not os.path.isfile(args.pdf):
        print(f"Error: File '{args.pdf}' not found.", file=sys.stderr)
        sys.exit(1)
    if not os.path.isfile(args.stamp):
        print(f"Error: Stamp file '{args.stamp}' not found.", file=sys.stderr)
        sys.exit(1)

    try:
        apply_watermark(args.pdf, args.stamp, args.output, under=args.under, pages_filter=args.pages)
        position = "underneath (background)" if args.under else "overlay (foreground)"
        print(f"Successfully applied watermark {position} to: {args.output}")
    except Exception as e:
        print(f"Error applying watermark: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
