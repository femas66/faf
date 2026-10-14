#!/usr/bin/env python3
"""Build PDF documents from a structured JSON specification using ReportLab."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, LETTER, LEGAL
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch, cm, mm
    pt = 1
    from reportlab.pdfgen import canvas
    from reportlab.platypus import (
        HRFlowable,
        Image,
        KeepTogether,
        ListFlowable,
        ListItem,
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )
except ImportError as err:
    print(
        f"Error: Required library 'reportlab' is missing ({err}).\n"
        f"Install it via: pip install reportlab",
        file=sys.stderr,
    )
    sys.exit(1)


PAGE_SIZES = {
    "A4": A4,
    "LETTER": LETTER,
    "LEGAL": LEGAL,
}


def parse_color(c: Any, default: colors.Color = colors.black) -> colors.Color:
    if not c:
        return default
    if isinstance(c, str):
        if c.startswith("#"):
            return colors.HexColor(c)
        try:
            return getattr(colors, c.lower(), default)
        except Exception:
            return default
    if isinstance(c, (list, tuple)) and len(c) in (3, 4):
        return colors.Color(*c)
    return default


class NumberedCanvas(canvas.Canvas):
    """Two-pass canvas to dynamically inject 'Page X of Y' in headers and footers."""

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._saved_page_states: list[dict[str, Any]] = []
        self.doc_header: str | None = None
        self.doc_footer: str | None = None

    def showPage(self) -> None:
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, total_pages: int) -> None:
        self.saveState()
        self.setFont("Helvetica", 9)
        self.setFillColor(colors.HexColor("#64748B"))
        w, h = self._pagesize

        # Draw Header
        if self.doc_header:
            header_text = (
                self.doc_header.replace("{page}", str(self._pageNumber))
                .replace("{pages}", str(total_pages))
            )
            self.drawString(54, h - 36, header_text)
            self.setStrokeColor(colors.HexColor("#E2E8F0"))
            self.setLineWidth(0.5)
            self.line(54, h - 42, w - 54, h - 42)

        # Draw Footer
        if self.doc_footer:
            footer_text = (
                self.doc_footer.replace("{page}", str(self._pageNumber))
                .replace("{pages}", str(total_pages))
            )
            self.drawRightString(w - 54, 30, footer_text)
            self.setStrokeColor(colors.HexColor("#E2E8F0"))
            self.setLineWidth(0.5)
            self.line(54, 42, w - 54, 42)

        self.restoreState()


def build_pdf_from_spec(spec_data: dict[str, Any], output_path: str, page_size_override: str | None = None) -> None:
    page_size_name = (page_size_override or spec_data.get("page_size", "A4")).upper()
    page_size = PAGE_SIZES.get(page_size_name, A4)
    if isinstance(spec_data.get("page_size"), list) and len(spec_data["page_size"]) == 2:
        page_size = (float(spec_data["page_size"][0]), float(spec_data["page_size"][1]))

    margins = spec_data.get("margins", {})
    left_m = float(margins.get("left", 54))
    right_m = float(margins.get("right", 54))
    top_m = float(margins.get("top", 54))
    bottom_m = float(margins.get("bottom", 54))

    # Adjust top/bottom margins if header/footer is present
    if spec_data.get("header"):
        top_m = max(top_m, 54)
    if spec_data.get("footer"):
        bottom_m = max(bottom_m, 54)

    doc = SimpleDocTemplate(
        output_path,
        pagesize=page_size,
        leftMargin=left_m,
        rightMargin=right_m,
        topMargin=top_m,
        bottomMargin=bottom_m,
        title=spec_data.get("title", ""),
        author=spec_data.get("author", ""),
        subject=spec_data.get("subject", ""),
    )

    base_styles = getSampleStyleSheet()
    story: list[Any] = []

    elements = spec_data.get("elements", [])
    if not isinstance(elements, list):
        raise ValueError("'elements' in spec must be a list")

    for idx, el in enumerate(elements):
        el_type = el.get("type", "").lower()

        if el_type == "heading":
            level = int(el.get("level", 1))
            size = 22 if level == 1 else (16 if level == 2 else 13)
            leading = size + 4
            color = parse_color(el.get("color", "#0F172A"))
            align_map = {"center": 1, "right": 2, "justify": 4, "left": 0}
            alignment = align_map.get(el.get("align", "left").lower(), 0)
            style = ParagraphStyle(
                f"Heading_{level}_{idx}",
                parent=base_styles["Heading1" if level == 1 else "Heading2"],
                fontSize=size,
                leading=leading,
                textColor=color,
                alignment=alignment,
                spaceAfter=float(el.get("space_after", 10)),
                keepWithNext=True,
            )
            story.append(Paragraph(el.get("text", ""), style))

        elif el_type == "paragraph":
            font_size = float(el.get("font_size", 10.5))
            leading = float(el.get("leading", font_size * 1.35))
            color = parse_color(el.get("color", "#1E293B"))
            align_map = {"center": 1, "right": 2, "justify": 4, "left": 0}
            alignment = align_map.get(el.get("align", "left").lower(), 0)
            style = ParagraphStyle(
                f"Para_{idx}",
                parent=base_styles["Normal"],
                fontSize=font_size,
                leading=leading,
                textColor=color,
                alignment=alignment,
                spaceAfter=float(el.get("space_after", 8)),
            )
            story.append(Paragraph(el.get("text", ""), style))

        elif el_type == "spacer":
            height = float(el.get("height", 12))
            story.append(Spacer(1, height))

        elif el_type in ("hr", "divider"):
            thickness = float(el.get("thickness", 0.75))
            color = parse_color(el.get("color", "#CBD5E1"))
            space_after = float(el.get("space_after", 10))
            space_before = float(el.get("space_before", 6))
            story.append(
                HRFlowable(
                    width="100%",
                    thickness=thickness,
                    color=color,
                    spaceBefore=space_before,
                    spaceAfter=space_after,
                )
            )

        elif el_type == "table":
            raw_data = el.get("data", [])
            if not raw_data:
                continue

            # Convert cell strings to Paragraphs for auto-wrap
            table_cells: list[list[Any]] = []
            header_cell_style = ParagraphStyle(
                f"TH_{idx}",
                parent=base_styles["Normal"],
                fontSize=float(el.get("header_font_size", 10)),
                leading=float(el.get("header_font_size", 10)) * 1.25,
                textColor=parse_color(el.get("header_color", "#FFFFFF")),
                fontName="Helvetica-Bold",
            )
            body_cell_style = ParagraphStyle(
                f"TD_{idx}",
                parent=base_styles["Normal"],
                fontSize=float(el.get("font_size", 9)),
                leading=float(el.get("font_size", 9)) * 1.25,
                textColor=parse_color(el.get("text_color", "#1E293B")),
            )

            for row_idx, row in enumerate(raw_data):
                row_cells = []
                for cell in row:
                    text_val = str(cell)
                    style = header_cell_style if row_idx == 0 and el.get("has_header", True) else body_cell_style
                    row_cells.append(Paragraph(text_val, style))
                table_cells.append(row_cells)

            col_widths = el.get("col_widths")
            if col_widths and isinstance(col_widths, list):
                col_widths = [float(w) for w in col_widths]

            t = Table(table_cells, colWidths=col_widths)
            t_styles = [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ]

            if el.get("has_header", True):
                header_bg = parse_color(el.get("header_bg", "#1E3A8A"))
                t_styles.append(("BACKGROUND", (0, 0), (-1, 0), header_bg))

            if el.get("striped", True):
                stripe_bg = parse_color(el.get("stripe_bg", "#F8FAFC"))
                for r in range(1 if el.get("has_header", True) else 0, len(raw_data)):
                    if r % 2 == 1:
                        t_styles.append(("BACKGROUND", (0, r), (-1, r), stripe_bg))

            if el.get("grid", True):
                border_color = parse_color(el.get("border_color", "#CBD5E1"))
                t_styles.append(("GRID", (0, 0), (-1, -1), 0.5, border_color))

            t.setStyle(TableStyle(t_styles))
            story.append(t)
            story.append(Spacer(1, float(el.get("space_after", 10))))

        elif el_type == "image":
            img_path = el.get("path")
            if not img_path or not os.path.isfile(img_path):
                print(f"Warning: Image file '{img_path}' not found. Skipping.", file=sys.stderr)
                continue
            width = float(el.get("width")) if el.get("width") else None
            height = float(el.get("height")) if el.get("height") else None
            img = Image(img_path, width=width, height=height)
            align_map = {"center": "CENTER", "right": "RIGHT", "left": "LEFT"}
            img.hAlign = align_map.get(el.get("align", "center").lower(), "CENTER")
            story.append(img)
            story.append(Spacer(1, float(el.get("space_after", 10))))

        elif el_type == "list":
            items = el.get("items", [])
            bullet_type = el.get("bullet_type", "bullet").lower()
            list_items = []
            item_style = ParagraphStyle(
                f"ListItem_{idx}",
                parent=base_styles["Normal"],
                fontSize=float(el.get("font_size", 10)),
                leading=float(el.get("font_size", 10)) * 1.3,
                textColor=parse_color(el.get("color", "#1E293B")),
                spaceAfter=4,
            )
            for item in items:
                list_items.append(ListItem(Paragraph(str(item), item_style), leftIndent=20))
            story.append(
                ListFlowable(
                    list_items,
                    bulletType="1" if bullet_type == "number" else "bullet",
                    start=1,
                    leftIndent=10,
                )
            )
            story.append(Spacer(1, float(el.get("space_after", 8))))

        elif el_type == "page_break":
            story.append(PageBreak())

    # Build canvas with two-pass header/footer support
    def make_canvas(*args: Any, **kwargs: Any) -> NumberedCanvas:
        c = NumberedCanvas(*args, **kwargs)
        c.doc_header = spec_data.get("header")
        c.doc_footer = spec_data.get("footer")
        return c

    doc.build(story, canvasmaker=make_canvas)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build professional PDF documents from a structured JSON specification using ReportLab."
    )
    parser.add_argument("spec", help="Path to JSON specification file (or '-' for stdin).")
    parser.add_argument("-o", "--output", default="out.pdf", help="Output PDF file path (default: out.pdf).")
    parser.add_argument(
        "--page-size",
        choices=["A4", "LETTER", "LEGAL"],
        help="Override page size (A4, LETTER, LEGAL).",
    )

    args = parser.parse_args()

    try:
        if args.spec == "-":
            spec_data = json.load(sys.stdin)
        else:
            with open(args.spec, "r", encoding="utf-8") as f:
                spec_data = json.load(f)

        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        build_pdf_from_spec(spec_data, args.output, args.page_size)
        print(f"Successfully generated PDF: {args.output}")
    except Exception as e:
        print(f"Error creating PDF: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
