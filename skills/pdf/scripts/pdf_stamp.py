#!/usr/bin/env python3
"""Stamp text or image annotations onto PDF pages with configurable position, rotation, opacity, and color."""

from __future__ import annotations

import argparse
import io
import os
import sys
from typing import Any

try:
    import pypdf
    from PIL import Image as PILImage
    from reportlab.lib import colors
    from reportlab.pdfgen import canvas
except ImportError as err:
    print(
        f"Error: Required library is missing ({err}).\n"
        f"Ensure pypdf, reportlab, and pillow are installed.",
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


def parse_color(c: str, alpha: float = 1.0) -> colors.Color:
    if c.startswith("#"):
        c = c.lstrip("#")
        if len(c) == 6:
            r = int(c[0:2], 16) / 255.0
            g = int(c[2:4], 16) / 255.0
            b = int(c[4:6], 16) / 255.0
            return colors.Color(r, g, b, alpha=alpha)
    try:
        base = getattr(colors, c.lower(), colors.black)
        return colors.Color(base.red, base.green, base.blue, alpha=alpha)
    except Exception:
        return colors.Color(0, 0, 0, alpha=alpha)


def stamp_pdf(
    input_path: str,
    output_path: str,
    text: str | None = None,
    image_path: str | None = None,
    x: float = 0,
    y: float = 0,
    font_size: float = 24,
    rotation: float = 0,
    opacity: float = 1.0,
    color_hex: str = "#000000",
    font_name: str = "Helvetica-Bold",
    width: float | None = None,
    height: float | None = None,
    pages_filter: str | None = None,
    origin: str = "bottom-left",
) -> None:
    reader = pypdf.PdfReader(input_path)
    writer = pypdf.PdfWriter()

    target_pages = parse_page_range(pages_filter, len(reader.pages))

    # Image dimensions auto-detect
    img_w, img_h = width, height
    if image_path and os.path.isfile(image_path):
        if img_w is None and img_h is None:
            with PILImage.open(image_path) as im:
                img_w, img_h = float(im.width), float(im.height)
        elif img_w is not None and img_h is None:
            with PILImage.open(image_path) as im:
                aspect = float(im.height) / float(im.width)
                img_h = img_w * aspect
        elif img_h is not None and img_w is None:
            with PILImage.open(image_path) as im:
                aspect = float(im.width) / float(im.height)
                img_w = img_h * aspect

    for idx, page in enumerate(reader.pages):
        if idx in target_pages:
            p_width = float(page.mediabox.width)
            p_height = float(page.mediabox.height)

            calc_y = y
            if origin.lower() == "top-left":
                # Convert top-left to PDF bottom-left
                if image_path and img_h:
                    calc_y = p_height - y - img_h
                else:
                    calc_y = p_height - y

            # Render stamp overlay in memory
            buf = io.BytesIO()
            canv = canvas.Canvas(buf, pagesize=(p_width, p_height))
            canv.saveState()

            if text:
                canv.translate(x, calc_y)
                if rotation:
                    canv.rotate(rotation)
                color = parse_color(color_hex, alpha=opacity)
                canv.setFillColor(color)
                canv.setFont(font_name, font_size)
                canv.drawString(0, 0, text)

            elif image_path:
                canv.translate(x, calc_y)
                if rotation:
                    canv.rotate(rotation)
                # If opacity < 1, set alpha
                if hasattr(canv, "setFillAlpha"):
                    canv.setFillAlpha(opacity)
                canv.drawImage(image_path, 0, 0, width=img_w, height=img_h, mask="auto")

            canv.restoreState()
            canv.save()

            buf.seek(0)
            stamp_doc = pypdf.PdfReader(buf)
            page.merge_page(stamp_doc.pages[0], over=True)

        writer.add_page(page)

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "wb") as f_out:
        writer.write(f_out)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stamp custom text or image annotations onto PDF pages."
    )
    parser.add_argument("pdf", help="Path to input PDF file.")
    parser.add_argument("-o", "--output", default="out.pdf", help="Output PDF file path (default: out.pdf).")

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--text", help="Text string to stamp (e.g. 'DRAFT', 'CONFIDENTIAL').")
    group.add_argument("--image", help="Image file path to stamp (e.g. signature.png, logo.png).")

    # Geometry & Styling
    parser.add_argument("--x", type=float, default=100, help="X coordinate in points (default: 100).")
    parser.add_argument("--y", type=float, default=100, help="Y coordinate in points (default: 100).")
    parser.add_argument("--font-size", type=float, default=24, help="Font size for text stamp (default: 24).")
    parser.add_argument("--rotation", type=float, default=0, help="Rotation angle in degrees (default: 0).")
    parser.add_argument("--opacity", type=float, default=1.0, help="Opacity level 0.0 - 1.0 (default: 1.0).")
    parser.add_argument("--color", default="#000000", help="Hex color (e.g. '#cc0000') or name (default: #000000).")
    parser.add_argument("--width", type=float, help="Target image width in points.")
    parser.add_argument("--height", type=float, help="Target image height in points.")
    parser.add_argument("--pages", help="Target pages (e.g. '1-3,5'). Default: all pages.")
    parser.add_argument(
        "--origin",
        default="bottom-left",
        choices=["bottom-left", "top-left"],
        help="Coordinate origin system (default: bottom-left).",
    )

    args = parser.parse_args()

    if not os.path.isfile(args.pdf):
        print(f"Error: File '{args.pdf}' not found.", file=sys.stderr)
        sys.exit(1)

    if args.image and not os.path.isfile(args.image):
        print(f"Error: Image file '{args.image}' not found.", file=sys.stderr)
        sys.exit(1)

    try:
        stamp_pdf(
            input_path=args.pdf,
            output_path=args.output,
            text=args.text,
            image_path=args.image,
            x=args.x,
            y=args.y,
            font_size=args.font_size,
            rotation=args.rotation,
            opacity=args.opacity,
            color_hex=args.color,
            width=args.width,
            height=args.height,
            pages_filter=args.pages,
            origin=args.origin,
        )
        target = f"text '{args.text}'" if args.text else f"image '{args.image}'"
        print(f"Successfully stamped {target} onto: {args.output}")
    except Exception as e:
        print(f"Error stamping PDF: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
