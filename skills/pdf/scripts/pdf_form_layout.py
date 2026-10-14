#!/usr/bin/env python3
"""Lint PDF form layouts for bounding box overlaps and boundaries before building, with visual overlay rendering."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError as err:
    print(
        f"Error: Required library 'pillow' is missing ({err}).\n"
        f"Install it via: pip install pillow",
        file=sys.stderr,
    )
    sys.exit(1)

PAGE_SIZES = {
    "A4": (595.28, 841.89),
    "LETTER": (612.0, 792.0),
    "LEGAL": (612.0, 1008.0),
}


def parse_rect(rect_spec: list[float] | dict[str, float], page_h: float, origin: str = "top-left") -> tuple[float, float, float, float]:
    """Returns normalized (x0, y0, x1, y1) in top-left coordinate system."""
    if isinstance(rect_spec, dict):
        x = float(rect_spec.get("x", 0))
        y = float(rect_spec.get("y", 0))
        w = float(rect_spec.get("width", rect_spec.get("w", 100)))
        h = float(rect_spec.get("height", rect_spec.get("h", 20)))
    elif len(rect_spec) == 4:
        v0, v1, v2, v3 = [float(v) for v in rect_spec]
        if v2 > v0 and v3 > v1 and v2 - v0 > 10 and v3 - v1 > 5:
            x, y, w, h = v0, v1, v2 - v0, v3 - v1
        else:
            x, y, w, h = v0, v1, v2, v3
    else:
        raise ValueError(f"Invalid rect: {rect_spec}")

    if origin.lower() == "bottom-left":
        y_top = page_h - y - h
        return (x, y_top, x + w, y_top + h)
    else:
        return (x, y, x + w, y + h)


def check_intersection(r1: tuple[float, float, float, float], r2: tuple[float, float, float, float]) -> bool:
    """Returns True if two (x0, y0, x1, y1) rectangles intersect."""
    x0_1, y0_1, x1_1, y1_1 = r1
    x0_2, y0_2, x1_2, y1_2 = r2
    return not (x1_1 <= x0_2 or x0_1 >= x1_2 or y1_1 <= y0_2 or y0_1 >= y1_2)


def lint_formspec(spec_data: dict[str, Any]) -> tuple[list[str], list[str], list[dict[str, Any]]]:
    errors: list[str] = []
    warnings: list[str] = []
    normalized_fields: list[dict[str, Any]] = []

    page_size_name = spec_data.get("page_size", "A4").upper()
    page_w, page_h = PAGE_SIZES.get(page_size_name, PAGE_SIZES["A4"])
    if isinstance(spec_data.get("page_size"), list) and len(spec_data["page_size"]) == 2:
        page_w, page_h = float(spec_data["page_size"][0]), float(spec_data["page_size"][1])

    origin = spec_data.get("origin", "top-left")
    pages = spec_data.get("pages")
    if not pages:
        pages = [{"page_number": 1, "fields": spec_data.get("fields", [])}]

    seen_names: dict[str, str] = {}

    for p_idx, page in enumerate(pages, start=1):
        p_num = page.get("page_number", p_idx)
        fields = page.get("fields", [])
        page_fields = []

        for f_idx, field in enumerate(fields):
            name = field.get("name", "").strip()
            f_type = field.get("type", "text").lower()

            if not name:
                errors.append(f"Page {p_num}, Field #{f_idx + 1}: Field is missing a name.")

            # Duplicate name check
            if name in seen_names and f_type != "radio":
                warnings.append(
                    f"Page {p_num}: Duplicate field name '{name}' (previously seen on Page {seen_names[name]})."
                )
            else:
                seen_names[name] = str(p_num)

            # Dimensions & Coordinates
            try:
                rect = parse_rect(field.get("rect", [0, 0, 0, 0]), page_h, origin=origin)
            except Exception as e:
                errors.append(f"Page {p_num}, Field '{name}': Invalid rect format ({e}).")
                continue

            x0, y0, x1, y1 = rect
            w = x1 - x0
            h = y1 - y0

            if w <= 0 or h <= 0:
                errors.append(
                    f"Page {p_num}, Field '{name}': Zero or negative dimensions (width={w:.1f}, height={h:.1f})."
                )

            # Out of bounds
            if x0 < 0 or y0 < 0 or x1 > page_w or y1 > page_h:
                errors.append(
                    f"Page {p_num}, Field '{name}': Out of page bounds. "
                    f"Rect: [{x0:.1f}, {y0:.1f}, {x1:.1f}, {y1:.1f}] exceeds [0, 0, {page_w:.1f}, {page_h:.1f}]."
                )

            # Usability warnings
            if f_type in ("checkbox", "radio") and (w < 10 or h < 10):
                warnings.append(
                    f"Page {p_num}, Field '{name}': Small target size ({w:.1f}x{h:.1f} pt). Recommend at least 14x14 pt."
                )
            elif f_type in ("text", "choice") and h < 14:
                warnings.append(
                    f"Page {p_num}, Field '{name}': Field height is only {h:.1f} pt. Recommend at least 18 pt."
                )

            f_info = {
                "page": p_num,
                "name": name,
                "type": f_type,
                "rect": rect,
                "w": w,
                "h": h,
                "has_collision": False,
            }
            page_fields.append(f_info)

        # Overlap / collision check on same page
        for i in range(len(page_fields)):
            for j in range(i + 1, len(page_fields)):
                f1 = page_fields[i]
                f2 = page_fields[j]
                if check_intersection(f1["rect"], f2["rect"]):
                    f1["has_collision"] = True
                    f2["has_collision"] = True
                    errors.append(
                        f"Page {p_num}: Collision detected! Field '{f1['name']}' overlaps with '{f2['name']}'."
                    )

        normalized_fields.extend(page_fields)

    return errors, warnings, normalized_fields


def render_overlay_image(
    spec_data: dict[str, Any],
    fields: list[dict[str, Any]],
    output_image: str,
    pdf_path: str | None = None,
    dpi: int = 150,
) -> None:
    page_size_name = spec_data.get("page_size", "A4").upper()
    page_w, page_h = PAGE_SIZES.get(page_size_name, PAGE_SIZES["A4"])
    if isinstance(spec_data.get("page_size"), list) and len(spec_data["page_size"]) == 2:
        page_w, page_h = float(spec_data["page_size"][0]), float(spec_data["page_size"][1])

    scale = dpi / 72.0
    img_w = int(page_w * scale)
    img_h = int(page_h * scale)

    # Base image
    if pdf_path and os.path.isfile(pdf_path):
        try:
            import pymupdf
            doc = pymupdf.open(pdf_path)
            page = doc[0]
            pix = page.get_pixmap(dpi=dpi)
            base_img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            doc.close()
        except Exception as e:
            print(f"Warning: Failed to render PDF background ({e}), creating blank canvas.", file=sys.stderr)
            base_img = Image.new("RGBA", (img_w, img_h), (255, 255, 255, 255))
    else:
        base_img = Image.new("RGBA", (img_w, img_h), (255, 255, 255, 255))
        # Draw light grid lines
        grid_draw = ImageDraw.Draw(base_img)
        step = int(50 * scale)
        for gx in range(0, img_w, step):
            grid_draw.line([(gx, 0), (gx, img_h)], fill=(240, 243, 246), width=1)
        for gy in range(0, img_h, step):
            grid_draw.line([(0, gy), (img_w, gy)], fill=(240, 243, 246), width=1)

    # Overlay layer with transparency
    overlay = Image.new("RGBA", base_img.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)

    try:
        font = ImageFont.load_default()
    except Exception:
        font = None

    color_map = {
        "text": ((59, 130, 246, 50), (37, 99, 235, 255)),       # Blue
        "checkbox": ((34, 197, 94, 60), (22, 163, 74, 255)),    # Green
        "choice": ((168, 85, 247, 50), (147, 51, 234, 255)),    # Purple
        "radio": ((249, 115, 22, 50), (234, 88, 12, 255)),      # Orange
        "signature": ((14, 165, 233, 50), (2, 132, 199, 255)),  # Cyan
    }
    collision_color = ((239, 68, 68, 100), (220, 38, 38, 255))  # Bright Red

    for f in fields:
        if f.get("page", 1) != 1:
            continue
        x0, y0, x1, y1 = f["rect"]
        px0, py0 = int(x0 * scale), int(y0 * scale)
        px1, py1 = int(x1 * scale), int(y1 * scale)

        if f.get("has_collision"):
            fill_c, stroke_c = collision_color
            border_w = 3
        else:
            fill_c, stroke_c = color_map.get(f["type"], ((100, 116, 139, 50), (71, 85, 105, 255)))
            border_w = 2

        # Draw box
        draw.rectangle([px0, py0, px1, py1], fill=fill_c, outline=stroke_c, width=border_w)

        # Label tag
        label_text = f"{f['name']} ({f['type']})"
        if f.get("has_collision"):
            label_text = f"⚠️ COLLISION: {label_text}"

        tag_y = max(0, py0 - 14)
        draw.text((px0 + 3, tag_y), label_text, fill=stroke_c, font=font)

    # Composite
    base_img = base_img.convert("RGBA")
    final_img = Image.alpha_composite(base_img, overlay)
    final_img.convert("RGB").save(output_image)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Lint PDF form layout (overlap, bounds, usability) before building, with optional visual overlay."
    )
    parser.add_argument("formspec", help="Path to JSON form specification.")
    parser.add_argument("--render-overlay", help="Output image path for visual bounding box overlay (e.g. boxes.png).")
    parser.add_argument("--pdf", help="Optional PDF file to render under the overlay boxes.")
    parser.add_argument("--dpi", type=int, default=150, help="DPI for overlay rendering (default: 150).")

    args = parser.parse_args()

    try:
        with open(args.formspec, "r", encoding="utf-8") as f:
            spec_data = json.load(f)

        errors, warnings, fields = lint_formspec(spec_data)

        print(f"=== Form Layout Lint Report: {args.formspec} ===")
        print(f"Total fields scanned: {len(fields)}")

        if warnings:
            print(f"\n[!] {len(warnings)} Warning(s):")
            for w in warnings:
                print(f"  - {w}")

        if errors:
            print(f"\n[X] {len(errors)} Error(s) found:")
            for e in errors:
                print(f"  - {e}")
        else:
            print("\n[✓] Layout validation PASSED (no fatal errors).")

        if args.render_overlay:
            render_overlay_image(spec_data, fields, args.render_overlay, pdf_path=args.pdf, dpi=args.dpi)
            print(f"[✓] Rendered layout overlay image: {args.render_overlay}")

        if errors:
            sys.exit(1)

    except Exception as e:
        print(f"Error linting formspec: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
