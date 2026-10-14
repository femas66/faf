#!/usr/bin/env python3
"""Build interactive, fillable PDF forms (AcroForms) from a JSON specification."""

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


PAGE_SIZES = {
    "A4": (595.28, 841.89),
    "LETTER": (612.0, 792.0),
    "LEGAL": (612.0, 1008.0),
}


def parse_rgb(c: Any, default: tuple[float, float, float] = (0.0, 0.0, 0.0)) -> tuple[float, float, float]:
    """Parse color into RGB tuple in range 0.0-1.0."""
    if not c:
        return default
    if isinstance(c, str) and c.startswith("#"):
        c = c.lstrip("#")
        if len(c) == 6:
            r = int(c[0:2], 16) / 255.0
            g = int(c[2:4], 16) / 255.0
            b = int(c[4:6], 16) / 255.0
            return (r, g, b)
    if isinstance(c, (list, tuple)) and len(c) >= 3:
        # Check if values are in 0-255 or 0-1
        if any(v > 1.0 for v in c[:3]):
            return (c[0] / 255.0, c[1] / 255.0, c[2] / 255.0)
        return (float(c[0]), float(c[1]), float(c[2]))
    return default


def parse_rect(rect_spec: list[float] | dict[str, float], page_h: float, origin: str = "top-left") -> pymupdf.Rect:
    """Normalize rect to pymupdf.Rect(x0, y0, x1, y1) with top-left origin."""
    if isinstance(rect_spec, dict):
        x = float(rect_spec.get("x", 0))
        y = float(rect_spec.get("y", 0))
        w = float(rect_spec.get("width", rect_spec.get("w", 100)))
        h = float(rect_spec.get("height", rect_spec.get("h", 20)))
    elif len(rect_spec) == 4:
        # Interpret [x, y, w, h] if w, h looks like dimensions or [x0, y0, x1, y1] if x1 > x0 and y1 > y0
        v0, v1, v2, v3 = [float(v) for v in rect_spec]
        if v2 > v0 and v3 > v1 and v2 - v0 > 10 and v3 - v1 > 5:
            # likely [x0, y0, x1, y1]
            x, y, w, h = v0, v1, v2 - v0, v3 - v1
        else:
            x, y, w, h = v0, v1, v2, v3
    else:
        raise ValueError(f"Invalid rect specification: {rect_spec}")

    if origin.lower() == "bottom-left":
        # Invert Y coordinate
        y_top = page_h - y - h
        return pymupdf.Rect(x, y_top, x + w, y_top + h)
    else:
        return pymupdf.Rect(x, y, x + w, y + h)


def build_form_from_spec(spec_data: dict[str, Any], output_path: str) -> None:
    doc = pymupdf.open()
    page_size_name = spec_data.get("page_size", "A4").upper()
    page_w, page_h = PAGE_SIZES.get(page_size_name, PAGE_SIZES["A4"])
    if isinstance(spec_data.get("page_size"), list) and len(spec_data["page_size"]) == 2:
        page_w, page_h = float(spec_data["page_size"][0]), float(spec_data["page_size"][1])

    global_origin = spec_data.get("origin", "top-left")

    pages_spec = spec_data.get("pages")
    # If no pages array, treat root fields as page 1
    if not pages_spec:
        pages_spec = [{"page_number": 1, "fields": spec_data.get("fields", []), "drawings": spec_data.get("drawings", [])}]

    for p_spec in pages_spec:
        page = doc.new_page(width=page_w, height=page_h)

        # 1. Background drawings (labels, lines, rectangles, titles)
        for draw in p_spec.get("drawings", []):
            d_type = draw.get("type", "").lower()
            if d_type in ("text", "heading", "label"):
                text = draw.get("text", "")
                x = float(draw.get("x", 50))
                y = float(draw.get("y", 50))
                size = float(draw.get("size", draw.get("font_size", 10)))
                color = parse_rgb(draw.get("color", "#0F172A"))
                font_name = draw.get("font", "helv")
                if global_origin.lower() == "bottom-left":
                    y = page_h - y
                page.insert_text(pymupdf.Point(x, y), text, fontsize=size, color=color, fontname=font_name)

            elif d_type == "line":
                x0 = float(draw.get("x0", 0))
                y0 = float(draw.get("y0", 0))
                x1 = float(draw.get("x1", 0))
                y1 = float(draw.get("y1", 0))
                color = parse_rgb(draw.get("color", "#CCCCCC"))
                width = float(draw.get("width", 1))
                if global_origin.lower() == "bottom-left":
                    y0, y1 = page_h - y0, page_h - y1
                shape = page.new_shape()
                shape.draw_line(pymupdf.Point(x0, y0), pymupdf.Point(x1, y1))
                shape.finish(color=color, width=width)
                shape.commit()

            elif d_type in ("rect", "box"):
                rect = parse_rect(draw.get("rect", [0, 0, 100, 20]), page_h, origin=global_origin)
                stroke_color = parse_rgb(draw.get("stroke_color", draw.get("color", "#CBD5E1")))
                fill_color = parse_rgb(draw.get("fill_color", None), default=None)
                width = float(draw.get("width", 1))
                shape = page.new_shape()
                shape.draw_rect(rect)
                shape.finish(color=stroke_color, fill=fill_color, width=width)
                shape.commit()

        # 2. Form fields / widgets
        for field in p_spec.get("fields", []):
            f_type = field.get("type", "text").lower()
            rect = parse_rect(field.get("rect", [50, 50, 150, 24]), page_h, origin=global_origin)

            widget = pymupdf.Widget()
            widget.rect = rect
            widget.field_name = field.get("name", f"field_{len(list(page.widgets()))}")
            widget.field_label = field.get("label", widget.field_name)

            if field.get("tooltip"):
                widget.field_tooltip = field.get("tooltip")

            if f_type in ("text", "textarea", "string"):
                widget.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
                if field.get("multiline", False) or f_type == "textarea":
                    widget.field_flags |= pymupdf.PDF_TX_FIELD_IS_MULTILINE
                val = field.get("value", field.get("default", ""))
                widget.field_value = str(val) if val is not None else ""

            elif f_type in ("checkbox", "check", "bool"):
                widget.field_type = pymupdf.PDF_WIDGET_TYPE_CHECKBOX
                val = field.get("value", field.get("default", False))
                widget.field_value = bool(val)

            elif f_type in ("choice", "combobox", "dropdown", "select"):
                widget.field_type = pymupdf.PDF_WIDGET_TYPE_COMBOBOX
                options = field.get("options", field.get("choices", []))
                widget.choice_values = [str(opt) for opt in options]
                val = field.get("value", field.get("default"))
                if val:
                    widget.field_value = str(val)
                elif options:
                    widget.field_value = str(options[0])

            elif f_type in ("radio", "radiobutton"):
                widget.field_type = pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON
                # Radio buttons share field_name in a group
                widget.field_name = field.get("group", field.get("name", "radio_group"))
                widget.field_value = field.get("value", field.get("default", "choice1"))

            elif f_type == "signature":
                widget.field_type = pymupdf.PDF_WIDGET_TYPE_SIGNATURE

            else:
                widget.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
                widget.field_value = str(field.get("value", ""))

            # Border and styling
            if field.get("border_color"):
                widget.border_color = parse_rgb(field["border_color"])
            if field.get("fill_color"):
                widget.fill_color = parse_rgb(field["fill_color"])
            if field.get("font_size"):
                widget.text_fontsize = float(field["font_size"])

            page.add_widget(widget)

    doc.save(output_path)
    doc.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build interactive fillable PDF AcroForms from a JSON specification."
    )
    parser.add_argument("formspec", help="Path to JSON form specification (or '-' for stdin).")
    parser.add_argument("-o", "--output", default="form.pdf", help="Output form PDF path (default: form.pdf).")

    args = parser.parse_args()

    try:
        if args.formspec == "-":
            spec_data = json.load(sys.stdin)
        else:
            with open(args.formspec, "r", encoding="utf-8") as f:
                spec_data = json.load(f)

        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        build_form_from_spec(spec_data, args.output)
        print(f"Successfully generated fillable PDF form: {args.output}")
    except Exception as e:
        print(f"Error creating form PDF: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
