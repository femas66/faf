#!/usr/bin/env python3
"""Convert PDF pages to high-resolution images (PNG, JPEG, WebP) using PyMuPDF."""

from __future__ import annotations

import argparse
import os
import sys

try:
    import pymupdf
except ImportError as err:
    print(
        f"Error: Required library 'pymupdf' is missing ({err}).\n"
        f"Install it via: pip install pymupdf",
        file=sys.stderr,
    )
    sys.exit(1)


def parse_page_range(pages_str: str | None, max_pages: int) -> list[int]:
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


def render_pages_to_images(
    pdf_path: str,
    output_dir: str,
    page_indices: list[int],
    dpi: int = 150,
    img_format: str = "png",
    prefix: str = "page_",
) -> list[str]:
    doc = pymupdf.open(pdf_path)
    os.makedirs(output_dir, exist_ok=True)
    generated_files = []

    ext = img_format.lower().lstrip(".")
    if ext == "jpeg":
        ext = "jpg"

    for idx in page_indices:
        if idx >= len(doc):
            continue
        page = doc[idx]
        pix = page.get_pixmap(dpi=dpi)
        filename = f"{prefix}{idx + 1:03d}.{ext}"
        filepath = os.path.join(output_dir, filename)
        pix.save(filepath)
        generated_files.append(filepath)

    doc.close()
    return generated_files


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert PDF document pages to raster images (PNG, JPG, WebP)."
    )
    parser.add_argument("pdf", help="Path to input PDF file.")
    parser.add_argument("--pages", help="Target page numbers or ranges (e.g. '1-3,5'). Default: all pages.")
    parser.add_argument("--dpi", type=int, default=150, help="Resolution in dots per inch (default: 150).")
    parser.add_argument("--out-dir", default="imgs", help="Directory to save rendered images (default: imgs).")
    parser.add_argument("--format", default="png", choices=["png", "jpg", "jpeg", "webp"], help="Image format (default: png).")
    parser.add_argument("--prefix", default="page_", help="Filename prefix for generated images (default: 'page_').")

    args = parser.parse_args()

    if not os.path.isfile(args.pdf):
        print(f"Error: File '{args.pdf}' not found.", file=sys.stderr)
        sys.exit(1)

    try:
        doc = pymupdf.open(args.pdf)
        indices = parse_page_range(args.pages, len(doc))
        doc.close()

        saved = render_pages_to_images(
            args.pdf,
            output_dir=args.out_dir,
            page_indices=indices,
            dpi=args.dpi,
            img_format=args.format,
            prefix=args.prefix,
        )
        print(f"Successfully rendered {len(saved)} image(s) into: {args.out_dir}/")
        for f in saved[:5]:
            print(f"  - {f}")
        if len(saved) > 5:
            print(f"  ... and {len(saved) - 5} more.")

    except Exception as e:
        print(f"Error rendering pages: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
