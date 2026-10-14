#!/usr/bin/env python3
"""Merge multiple PDF files into a single document with optional bookmark outlines."""

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


def merge_pdfs(input_files: list[str], output_path: str, add_bookmarks: bool = False) -> None:
    writer = pypdf.PdfWriter()

    for fpath in input_files:
        if not os.path.isfile(fpath):
            raise FileNotFoundError(f"Input file not found: {fpath}")

        bookmark_title = os.path.splitext(os.path.basename(fpath))[0] if add_bookmarks else None
        writer.append(fpath, outline_item=bookmark_title)

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "wb") as f_out:
        writer.write(f_out)
    writer.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Merge multiple PDF documents into a single document."
    )
    parser.add_argument("files", nargs="+", help="Two or more PDF files to merge.")
    parser.add_argument("-o", "--output", default="merged.pdf", help="Output merged PDF path (default: merged.pdf).")
    parser.add_argument(
        "--bookmarks",
        action="store_true",
        help="Generate table of contents / bookmarks for each merged file using its filename.",
    )

    args = parser.parse_args()

    if len(args.files) < 2:
        print("Error: Please provide at least 2 PDF files to merge.", file=sys.stderr)
        sys.exit(1)

    try:
        merge_pdfs(args.files, args.output, add_bookmarks=args.bookmarks)
        print(f"Successfully merged {len(args.files)} files into: {args.output}")
    except Exception as e:
        print(f"Error merging PDFs: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
