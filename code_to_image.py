#!/usr/bin/env python3
"""
code_to_image.py — Ubah teks/kode jadi gambar PNG bergaya VS Code (tema Dark+).
Dependensi: Pillow, Pygments (pkg install python-pillow && pip install pygments)

Fitur:
- Tema otentik VS Code Dark+ (palet warna persis)
- Nomor baris kustom (--start-line, misal mulai baris 40)
- Highlight baris tunggal & range baris (--highlight 3,5-7)
- Kursor aktif & highlight baris aktif (--cursor 12:5)
- Mode frame: 'tab' (default, tanpa status bar), 'full' (+ title bar + status bar), 'none' (kode saja)
- Gaya OS Windows atau macOS untuk title bar
- Breadcrumb dinamis & tab file dengan ikon bahasa berwarna
- Soft wrap (--wrap 80) agar gambar tidak terlalu lebar
- Dukungan custom font (.fonts folder, --font, --font-dir)
- Dukungan multi-bahasa (Python, Go, PHP, JS, TS, HTML, CSS, Bash, Rust, C++, JSON, Markdown, IPYNB, dll.)
- Dukungan Jupyter Notebook (.ipynb) dengan pemisahan cell code & markdown
- Resolusi tajam HiDPI / Retina (--scale 2)
"""

from __future__ import annotations

import argparse
import io
import json
import os
import pathlib
import re
import sys
from typing import Any

from PIL import Image, ImageDraw, ImageFont

# Pygments imports with graceful fallback
try:
    import pygments
    from pygments.lexer import Lexer
    from pygments.lexers import (
        TextLexer,
        get_lexer_by_name,
        get_lexer_for_filename,
        guess_lexer,
    )
    from pygments.token import Token
    PYGMENTS_AVAILABLE = True
except ImportError:
    PYGMENTS_AVAILABLE = False
    Token = None  # type: ignore


# ==============================================================================
# 1. VS CODE DARK+ COLOR PALETTE & TOKEN MAPPING
# ==============================================================================

# VS Code Dark+ UI Colors
BG_EDITOR = "#1E1E1E"              # 30, 30, 30
BG_TITLEBAR = "#323233"            # 50, 50, 51
FG_TITLEBAR = "#CCCCCC"            # 204, 204, 204
BG_TAB_BAR = "#252526"             # 37, 37, 38
BG_TAB_ACTIVE = "#1E1E1E"          # Matches editor seamlessly
FG_TAB_ACTIVE = "#FFFFFF"          # White
BORDER_TAB_ACTIVE_TOP = "#007ACC"  # Classic VS Code blue tab top border
FG_TAB_CLOSE = "#858585"           # Tab close 'x' icon
BG_BREADCRUMB = "#1E1E1E"          # Breadcrumbs background
FG_BREADCRUMB = "#858585"          # Breadcrumb path segment
FG_BREADCRUMB_ACTIVE = "#CCCCCC"   # Current file in breadcrumb
BORDER_DIVIDER = "#2B2B2B"         # Subtle separator line
GUTTER_FG = "#858585"              # Line numbers
GUTTER_ACTIVE_FG = "#C6C6C6"       # Active line number
LINE_ACTIVE_BG = "#282828"         # Subtle active line highlight
HIGHLIGHT_BG = "#21364F"           # Highlighted line background (selection-like)
HIGHLIGHT_ACCENT = "#007ACC"       # Left indicator on highlighted lines
CURSOR_COLOR = "#AEAFAD"           # Cursor vertical bar
BG_STATUSBAR = "#007ACC"           # VS Code blue status bar
FG_STATUSBAR = "#FFFFFF"           # Status bar text
DEFAULT_FG = "#D4D4D4"             # Default text color
WINDOW_BORDER = "#3C3C3C"          # Outer window outline

# macOS traffic light colors
MAC_RED = "#ED6A5E"
MAC_YELLOW = "#F4BF4F"
MAC_GREEN = "#61C554"

# Authentic VS Code Dark+ Pygments Token Map
DARK_PLUS_TOKEN_MAP = {
    # Keywords
    "Token.Keyword.Control": "#C586C0",     # if, else, for, while, return, try, except
    "Token.Keyword.Return": "#C586C0",
    "Token.Keyword.Conditional": "#C586C0",
    "Token.Keyword.Repeat": "#C586C0",
    "Token.Keyword.Exception": "#C586C0",
    "Token.Keyword.Type": "#4EC9B0",        # int, str, bool, void, etc.
    "Token.Keyword.Declaration": "#569CD6", # def, class, const, let, var
    "Token.Keyword.Namespace": "#C586C0",   # import, from
    "Token.Keyword": "#569CD6",             # async, await, etc.

    # Names / Identifiers
    "Token.Name.Function": "#DCDCAA",       # function calls / definitions
    "Token.Name.Function.Magic": "#569CD6", # __init__, __str__
    "Token.Name.Class": "#4EC9B0",          # ClassName, types
    "Token.Name.Exception": "#4EC9B0",      # Exception types
    "Token.Name.Decorator": "#DCDCAA",      # @decorators
    "Token.Name.Builtin": "#4EC9B0",        # range, len, print
    "Token.Name.Builtin.Pseudo": "#569CD6", # self, cls, this
    "Token.Name.Variable": "#9CDCFE",       # variables
    "Token.Name.Variable.Instance": "#9CDCFE",
    "Token.Name.Variable.Class": "#9CDCFE",
    "Token.Name.Variable.Global": "#9CDCFE",
    "Token.Name.Variable.Parameter": "#9CDCFE",
    "Token.Name.Constant": "#4FC1FF",       # CONSTANTS
    "Token.Name.Tag": "#569CD6",            # HTML / XML tags
    "Token.Name.Attribute": "#9CDCFE",      # HTML / XML attributes
    "Token.Name": "#9CDCFE",

    # Literals - Strings
    "Token.String.Doc": "#6A9955",          # Python docstrings (green in Dark+)
    "Token.String.Escape": "#D7BA7D",       # Escape characters \n, \t
    "Token.String.Interpol": "#9CDCFE",     # {var} in f-strings
    "Token.String.Regex": "#D16969",        # Regex patterns
    "Token.String": "#CE9178",              # "hello", 'world'

    # Literals - Numbers
    "Token.Number": "#B5CEA8",              # 123, 3.14, 0xFF

    # Comments
    "Token.Comment": "#6A9955",             # # comment, // comment

    # Operators & Punctuation
    "Token.Operator.Word": "#569CD6",       # and, or, not, in, is
    "Token.Operator": "#D4D4D4",            # +, -, *, =, ==
    "Token.Punctuation": "#D4D4D4",         # (, ), {, }, [, ], ,, ;

    # Generic / Text
    "Token.Generic.Heading": "#569CD6",
    "Token.Generic.Subheading": "#4EC9B0",
    "Token.Generic.Deleted": "#CE9178",
    "Token.Generic.Inserted": "#B5CEA8",
    "Token.Generic.Error": "#F44747",
    "Token.Text": "#D4D4D4",
}

# File type metadata (Extension -> (Display Name, Icon Color, Icon Symbol))
FILE_TYPE_REGISTRY = {
    ".py": ("Python", "#3572A5", "PY"),
    ".go": ("Go", "#00ADD8", "GO"),
    ".php": ("PHP", "#777BB4", "PHP"),
    ".js": ("JavaScript", "#F7DF1E", "JS"),
    ".mjs": ("JavaScript", "#F7DF1E", "JS"),
    ".cjs": ("JavaScript", "#F7DF1E", "JS"),
    ".ts": ("TypeScript", "#3178C6", "TS"),
    ".jsx": ("React", "#61DAFB", "JSX"),
    ".tsx": ("React TS", "#61DAFB", "TSX"),
    ".html": ("HTML", "#E34F26", "<>"),
    ".htm": ("HTML", "#E34F26", "<>"),
    ".css": ("CSS", "#563D7C", "#"),
    ".scss": ("SCSS", "#CF649A", "#"),
    ".json": ("JSON", "#CBCB41", "{ }"),
    ".sh": ("Bash", "#4EAA25", "$_"),
    ".bash": ("Bash", "#4EAA25", "$_"),
    ".zsh": ("Zsh", "#4EAA25", "$_"),
    ".rs": ("Rust", "#DEA584", "RS"),
    ".java": ("Java", "#B07219", "JV"),
    ".cpp": ("C++", "#00599C", "C++"),
    ".c": ("C", "#555555", "C"),
    ".h": ("C Header", "#555555", "H"),
    ".sql": ("SQL", "#E38C00", "SQL"),
    ".md": ("Markdown", "#083FA1", "MD"),
    ".ipynb": ("Jupyter", "#F37626", "NB"),
    ".yaml": ("YAML", "#CB171E", "YM"),
    ".yml": ("YAML", "#CB171E", "YM"),
    ".toml": ("TOML", "#9C4121", "TO"),
    ".env": ("Config", "#6D8086", "⚙"),
    ".txt": ("Plain Text", "#CCCCCC", "TXT"),
}


# ==============================================================================
# 2. HELPER FUNCTIONS: PARSING, LEXING, FONTS
# ==============================================================================

def parse_highlight_ranges(hl_str: str | None) -> set[int]:
    """Parse comma-separated line numbers and ranges like '3,5-7,40-42'."""
    if not hl_str or not hl_str.strip():
        return set()
    result: set[int] = set()
    parts = hl_str.split(",")
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            bounds = part.split("-", 1)
            try:
                start = int(bounds[0].strip())
                end = int(bounds[1].strip())
                for n in range(min(start, end), max(start, end) + 1):
                    result.add(n)
            except ValueError:
                continue
        else:
            try:
                result.add(int(part))
            except ValueError:
                continue
    return result


def parse_cursor_pos(cursor_str: str | None) -> tuple[int, int] | None:
    """Parse cursor position formatted as 'line:col' (e.g. '12:5')."""
    if not cursor_str or ":" not in cursor_str:
        return None
    try:
        parts = cursor_str.split(":", 1)
        line = int(parts[0].strip())
        col = int(parts[1].strip())
        return line, col
    except ValueError:
        return None


def get_token_hex_color(ttype: Any) -> str:
    """Walk Pygments token inheritance hierarchy to get VS Code Dark+ color."""
    if not PYGMENTS_AVAILABLE or not ttype:
        return DEFAULT_FG
    curr = ttype
    while curr:
        key = str(curr)
        if key in DARK_PLUS_TOKEN_MAP:
            return DARK_PLUS_TOKEN_MAP[key]
        curr = getattr(curr, "parent", None)
    return DEFAULT_FG


def resolve_lexer(lang: str | None, filename: str, code: str) -> Any:
    """Find appropriate Pygments lexer based on lang, filename, or content."""
    if not PYGMENTS_AVAILABLE:
        return None

    # Normalization for common aliases
    lang_aliases = {
        "js": "javascript",
        "ts": "typescript",
        "py": "python",
        "sh": "bash",
        "zsh": "bash",
        "shell": "bash",
        "yml": "yaml",
        "golang": "go",
        "ipynb": "python",  # Jupyter python code cells
    }

    if lang:
        normalized_lang = lang_aliases.get(lang.lower().strip(), lang.lower().strip())
        try:
            return get_lexer_by_name(normalized_lang)
        except Exception:
            pass

    if filename:
        try:
            return get_lexer_for_filename(filename, code)
        except Exception:
            pass

    try:
        return guess_lexer(code)
    except Exception:
        return TextLexer()


def tokenize_code_lines(code: str, lexer: Any) -> list[list[tuple[str, str]]]:
    """Tokenize source code into lines of (token_text, hex_color)."""
    if not PYGMENTS_AVAILABLE or lexer is None:
        # Fallback: plain text
        raw_lines = code.split("\n")
        return [[(line, DEFAULT_FG)] for line in raw_lines]

    tokens = list(lexer.get_tokens(code))
    lines: list[list[tuple[str, str]]] = []
    current_line: list[tuple[str, str]] = []

    for ttype, text in tokens:
        color = get_token_hex_color(ttype)
        if "\n" in text:
            subparts = text.split("\n")
            for i, part in enumerate(subparts):
                if part:
                    current_line.append((part, color))
                if i < len(subparts) - 1:
                    lines.append(current_line)
                    current_line = []
        else:
            if text:
                current_line.append((text, color))

    if current_line or not lines:
        lines.append(current_line)

    return lines


def find_monospace_font(
    custom_path: str | None = None,
    custom_dir: str | None = None,
    size: int = 14,
    bold: bool = False,
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """
    Find and load a crisp monospace font.
    Searches custom_path, custom_dir, .fonts/, ~/.fonts/, Termux fonts, and OS fonts.
    """
    candidate_paths: list[str] = []

    if custom_path and os.path.isfile(custom_path):
        candidate_paths.append(custom_path)

    # Folders to inspect
    search_dirs = []
    if custom_dir:
        search_dirs.append(custom_dir)
    search_dirs.extend([
        ".fonts",
        os.path.expanduser("~/.fonts"),
        os.path.expanduser("~/.local/share/fonts"),
        os.path.expanduser("~/.termux"),
        "/data/data/com.termux/files/usr/share/fonts/TTF",
        "/data/data/com.termux/files/home/.termux",
        "/system/fonts",
        "/Library/Fonts",
        "/System/Library/Fonts",
        "/System/Library/Fonts/Supplemental",
        "/usr/share/fonts/truetype",
        "/usr/share/fonts/TTF",
        "C:\\Windows\\Fonts",
    ])

    # Preferred font filenames
    preferred_names = [
        "SF-Mono-Regular.otf" if not bold else "SF-Mono-Bold.otf",
        "Menlo.ttc",
        "CascadiaCode.ttf",
        "JetBrainsMono-Regular.ttf",
        "FiraCode-Regular.ttf",
        "Consolas.ttf",
        "DejaVuSansMono.ttf",
        "DroidSansMono.ttf",
        "font.ttf",  # Termux custom font
        "Courier New.ttf",
    ]

    for d in search_dirs:
        if not os.path.isdir(d):
            continue
        # Direct preferred check
        for name in preferred_names:
            p = os.path.join(d, name)
            if os.path.isfile(p):
                candidate_paths.append(p)
        # Scan dir for any ttf/otf
        try:
            for root, _, files in os.walk(d):
                for f in files:
                    ext = os.path.splitext(f)[1].lower()
                    if ext in [".ttf", ".otf", ".ttc"]:
                        candidate_paths.append(os.path.join(root, f))
                # Limit walk depth
                break
        except Exception:
            pass

    for p in candidate_paths:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue

    # Ultimate fallback to PIL default font
    return ImageFont.load_default()


def find_sans_font(
    custom_path: str | None = None,
    custom_dir: str | None = None,
    size: int = 14,
    bold: bool = False,
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Find and load a clean sans-serif font for UI and rendered markdown."""
    candidate_paths: list[str] = []

    if custom_path and os.path.isfile(custom_path):
        candidate_paths.append(custom_path)

    if bold:
        candidate_paths.extend([
            "/System/Library/Fonts/SFNS.ttf",
            "/System/Library/Fonts/HelveticaNeue.ttc",
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "/Library/Fonts/Arial Bold.ttf",
            "/system/fonts/Roboto-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "C:\\Windows\\Fonts\\segoeuib.ttf",
            "C:\\Windows\\Fonts\\arialbd.ttf",
        ])
    else:
        candidate_paths.extend([
            "/System/Library/Fonts/SFNS.ttf",
            "/System/Library/Fonts/HelveticaNeue.ttc",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/Library/Fonts/Arial.ttf",
            "/system/fonts/Roboto-Regular.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "C:\\Windows\\Fonts\\segoeui.ttf",
            "C:\\Windows\\Fonts\\arial.ttf",
        ])

    for p in candidate_paths:
        if os.path.isfile(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue

    # Fallback to monospace font
    return find_monospace_font(custom_path, custom_dir, size, bold=bold)


def parse_markdown_spans(text: str) -> list[dict[str, str]]:
    """Parse inline markdown into list of spans (regular, bold, italic, code)."""
    spans: list[dict[str, str]] = []
    pattern = re.compile(r"(\*\*.*?\*\*|\*.*?\*|`[^`]+`)")
    last_idx = 0
    for m in pattern.finditer(text):
        if m.start() > last_idx:
            spans.append({"style": "regular", "text": text[last_idx:m.start()]})
        val = m.group()
        if val.startswith("**") and val.endswith("**"):
            spans.append({"style": "bold", "text": val[2:-2]})
        elif val.startswith("*") and val.endswith("*"):
            spans.append({"style": "italic", "text": val[1:-1]})
        elif val.startswith("`") and val.endswith("`"):
            spans.append({"style": "code", "text": val[1:-1]})
        last_idx = m.end()
    if last_idx < len(text):
        spans.append({"style": "regular", "text": text[last_idx:]})
    return spans


def parse_markdown_blocks(source: str) -> list[dict[str, Any]]:
    """Parse notebook markdown text into structured block elements."""
    lines = source.split("\n")
    blocks: list[dict[str, Any]] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            blocks.append({"type": "blank"})
        elif line.startswith("# "):
            blocks.append({"type": "h1", "text": line[2:].strip()})
        elif line.startswith("## "):
            blocks.append({"type": "h2", "text": line[3:].strip()})
        elif line.startswith("### "):
            blocks.append({"type": "h3", "text": line[4:].strip()})
        elif line.startswith("#### "):
            blocks.append({"type": "h4", "text": line[5:].strip()})
        elif line.startswith("- ") or line.startswith("* "):
            blocks.append({"type": "bullet", "spans": parse_markdown_spans(line[2:].strip())})
        elif re.match(r"^\d+\.\s+", line):
            m = re.match(r"^(\d+\.)\s+(.*)$", line)
            if m:
                blocks.append({
                    "type": "number",
                    "num": m.group(1),
                    "spans": parse_markdown_spans(m.group(2)),
                })
            else:
                blocks.append({"type": "paragraph", "spans": parse_markdown_spans(line)})
        elif line.startswith("> "):
            blocks.append({"type": "quote", "spans": parse_markdown_spans(line[2:].strip())})
        elif stripped in ["---", "***", "___"]:
            blocks.append({"type": "hr"})
        else:
            blocks.append({"type": "paragraph", "spans": parse_markdown_spans(line)})
    return blocks


def get_file_type_meta(filename: str, lang: str | None = None) -> tuple[str, str, str]:
    """Return (Language Name, Badge Color, Badge Text) for filename and lang."""
    ext = os.path.splitext(filename)[1].lower()
    if ext in FILE_TYPE_REGISTRY:
        return FILE_TYPE_REGISTRY[ext]

    if lang:
        lang_lower = lang.lower().strip()
        for fext, (name, color, badge) in FILE_TYPE_REGISTRY.items():
            if name.lower() == lang_lower or fext.lstrip(".") == lang_lower:
                return (name, color, badge)

    return ("Plain Text", "#858585", "TXT")


def parse_ipynb_cells(content: str) -> list[dict[str, Any]] | None:
    """Parse Jupyter Notebook JSON into structured cell list, or None if not JSON."""
    try:
        data = json.loads(content)
        if isinstance(data, dict) and "cells" in data and isinstance(data["cells"], list):
            cells: list[dict[str, Any]] = []
            for c in data["cells"]:
                cell_type = c.get("cell_type", "code")
                source = c.get("source", "")
                if isinstance(source, list):
                    source = "".join(source)
                execution_count = c.get("execution_count")

                # Extract stdout or execute_result text if available
                output_lines: list[str] = []
                raw_outputs = c.get("outputs", [])
                if isinstance(raw_outputs, list):
                    for out in raw_outputs:
                        if isinstance(out, dict):
                            if out.get("output_type") == "stream" and "text" in out:
                                t = out["text"]
                                if isinstance(t, list):
                                    output_lines.extend([ln.rstrip("\r\n") for ln in t])
                                elif isinstance(t, str):
                                    output_lines.extend(t.splitlines())
                            elif "data" in out and isinstance(out["data"], dict):
                                plain = out["data"].get("text/plain")
                                if isinstance(plain, list):
                                    output_lines.extend([ln.rstrip("\r\n") for ln in plain])
                                elif isinstance(plain, str):
                                    output_lines.extend(plain.splitlines())

                cells.append({
                    "cell_type": cell_type,
                    "source": source,
                    "execution_count": execution_count,
                    "outputs": output_lines,
                })
            return cells
    except Exception:
        pass
    return None


def soft_wrap_token_lines(
    token_lines: list[list[tuple[str, str]]],
    max_chars: int,
) -> list[tuple[int | None, list[tuple[str, str]]]]:
    """
    Soft-wrap lines exceeding max_chars.
    Returns list of (line_index_or_none, tokens) where None indicates continuation row.
    """
    if max_chars <= 0:
        return [(i, line) for i, line in enumerate(token_lines)]

    wrapped_rows: list[tuple[int | None, list[tuple[str, str]]]] = []

    for orig_idx, line in enumerate(token_lines):
        line_char_count = sum(len(text) for text, _ in line)
        if line_char_count <= max_chars:
            wrapped_rows.append((orig_idx, line))
            continue

        # Wrap this line across multiple visual rows
        curr_row: list[tuple[str, str]] = []
        curr_len = 0
        is_first = True

        for text, color in line:
            remaining_text = text
            while remaining_text:
                space_left = max_chars - curr_len
                if len(remaining_text) <= space_left:
                    curr_row.append((remaining_text, color))
                    curr_len += len(remaining_text)
                    remaining_text = ""
                else:
                    # Split chunk
                    chunk = remaining_text[:space_left]
                    remaining_text = remaining_text[space_left:]
                    curr_row.append((chunk, color))
                    wrapped_rows.append((orig_idx if is_first else None, curr_row))
                    is_first = False
                    curr_row = []
                    curr_len = 0

        if curr_row:
            wrapped_rows.append((orig_idx if is_first else None, curr_row))

    return wrapped_rows


# ==============================================================================
# 3. CORE RENDERING ENGINE (VS CODE DARK+ AESTHETICS)
# ==============================================================================

class VSCodeImageRenderer:
    """Renderer that creates authentic VS Code Dark+ code screenshot images."""

    def __init__(
        self,
        code: str,
        lang: str | None = None,
        name: str = "main.py",
        path: str | None = None,
        frame: str = "tab",            # 'tab', 'full', 'none'
        os_style: str = "mac",         # 'mac', 'win'
        project: str = "faf-agent",
        branch: str = "main",
        highlight_str: str | None = None,
        cursor_str: str | None = None,
        wrap_cols: int | None = None,
        scale: int | float = 2,
        start_line: int = 1,
        font_path: str | None = None,
        font_dir: str | None = ".fonts",
        no_status_bar: bool = False,
    ) -> None:
        self.raw_code = code
        self.name = name or "main.py"
        self.lang = lang
        self.path = path or self.name
        self.frame = frame.lower().strip()
        if self.frame not in ["tab", "full", "none"]:
            self.frame = "tab"
        self.os_style = os_style.lower().strip()
        if self.os_style not in ["mac", "win"]:
            self.os_style = "mac"
        self.project = project or "project"
        self.branch = branch or "main"
        self.scale = max(1, float(scale))
        self.start_line = max(1, int(start_line))
        self.font_path = font_path
        self.font_dir = font_dir
        self.no_status_bar = no_status_bar

        # Highlight lines & Cursor
        self.highlight_set = parse_highlight_ranges(highlight_str)
        self.cursor_pos = parse_cursor_pos(cursor_str)
        self.wrap_cols = int(wrap_cols) if wrap_cols and wrap_cols > 0 else None

        # Resolve language metadata
        self.lang_name, self.badge_color, self.badge_symbol = get_file_type_meta(
            self.name, self.lang
        )

        # Detect Jupyter Notebook
        self.ipynb_cells = parse_ipynb_cells(self.raw_code)

        # Initialize fonts (scaled)
        self.base_font_size = int(14 * self.scale)
        self.code_font = find_monospace_font(
            self.font_path, self.font_dir, size=self.base_font_size, bold=False
        )
        self.code_font_bold = find_monospace_font(
            self.font_path, self.font_dir, size=self.base_font_size, bold=True
        )
        self.ui_font_size = int(12 * self.scale)
        self.ui_font = find_monospace_font(
            self.font_path, self.font_dir, size=self.ui_font_size, bold=False
        )
        self.ui_font_bold = find_monospace_font(
            self.font_path, self.font_dir, size=self.ui_font_size, bold=True
        )

        # Markdown fonts for Jupyter Notebook
        self.md_h1_font = find_sans_font(
            self.font_path, self.font_dir, size=int(self.base_font_size * 1.5), bold=True
        )
        self.md_h2_font = find_sans_font(
            self.font_path, self.font_dir, size=int(self.base_font_size * 1.3), bold=True
        )
        self.md_h3_font = find_sans_font(
            self.font_path, self.font_dir, size=int(self.base_font_size * 1.15), bold=True
        )
        self.md_text_font = find_sans_font(
            self.font_path, self.font_dir, size=self.base_font_size, bold=False
        )
        self.md_text_bold = find_sans_font(
            self.font_path, self.font_dir, size=self.base_font_size, bold=True
        )

        # Measurements
        self._measure_char_metrics()

    def _measure_char_metrics(self) -> None:
        """Measure average monospace character width and line height."""
        # Test character width
        try:
            self.char_w = self.code_font.getlength("M")
        except AttributeError:
            bbox = self.code_font.getbbox("M")
            self.char_w = bbox[2] - bbox[0]

        if self.char_w <= 0:
            self.char_w = 8.5 * self.scale

        self.line_height = int(self.base_font_size * 1.55)

    def _prepare_render_rows(self) -> list[dict[str, Any]]:
        """
        Tokenize code and break into rendered visual rows for standard editor.
        Returns a list of row dicts with tokens, line numbers, highlight state, cursor.
        """
        rows: list[dict[str, Any]] = []
        lexer = resolve_lexer(self.lang, self.name, self.raw_code)
        token_lines = tokenize_code_lines(self.raw_code, lexer)
        wrapped = soft_wrap_token_lines(token_lines, self.wrap_cols or 0)

        for orig_line_idx, tokens in wrapped:
            disp_line_no = (
                (self.start_line + orig_line_idx)
                if orig_line_idx is not None
                else None
            )

            # Check highlight (matches either displayed number or 1-based index)
            is_hl = False
            if orig_line_idx is not None:
                idx_1based = orig_line_idx + 1
                if (
                    disp_line_no in self.highlight_set
                    or idx_1based in self.highlight_set
                ):
                    is_hl = True

            # Check cursor
            has_cur = False
            cur_col = None
            if orig_line_idx is not None and self.cursor_pos:
                c_line, c_col = self.cursor_pos
                if c_line == disp_line_no or c_line == (orig_line_idx + 1):
                    has_cur = True
                    cur_col = max(1, c_col)

            rows.append({
                "is_cell_banner": False,
                "cell_type": "code",
                "line_no": disp_line_no,
                "tokens": tokens,
                "is_highlight": is_hl,
                "has_cursor": has_cur,
                "cursor_col": cur_col,
            })

        return rows

    def render(self) -> Image.Image:
        """Draw and produce the final VS Code styled PNG image."""
        if self.ipynb_cells:
            return self._render_notebook()
        return self._render_standard_editor()

    def _render_standard_editor(self) -> Image.Image:
        """Render single file buffer in classic VS Code editor layout."""
        rows = self._prepare_render_rows()

        # Compute max line number for gutter width
        max_line_no = self.start_line + len(rows)
        for r in rows:
            if r["line_no"] and r["line_no"] > max_line_no:
                max_line_no = r["line_no"]

        gutter_digits = max(3, len(str(max_line_no)))
        gutter_width = int((gutter_digits * self.char_w) + (26 * self.scale))

        # Calculate longest line width
        max_tokens_len = 0
        for r in rows:
            line_str = "".join(t[0] for t in r["tokens"])
            try:
                line_w = self.code_font.getlength(line_str)
            except AttributeError:
                line_w = len(line_str) * self.char_w
            if line_w > max_tokens_len:
                max_tokens_len = line_w

        # Padding constants (scaled)
        pad_x = int(16 * self.scale)
        pad_y = int(12 * self.scale)

        # Header heights
        titlebar_h = int(32 * self.scale) if self.frame == "full" else 0
        tabbar_h = int(35 * self.scale) if self.frame in ["tab", "full"] else 0
        breadcrumb_h = int(24 * self.scale) if self.frame in ["tab", "full"] else 0

        # Status bar height: only in frame full and if not disabled
        has_statusbar = (self.frame == "full") and (not self.no_status_bar)
        statusbar_h = int(22 * self.scale) if has_statusbar else 0

        # Total dimensions
        editor_w = int(gutter_width + max_tokens_len + (pad_x * 2.5))
        min_width = int(540 * self.scale) if self.frame in ["tab", "full"] else int(320 * self.scale)
        width = max(editor_w, min_width)

        editor_h = int(len(rows) * self.line_height + (pad_y * 2))
        height = titlebar_h + tabbar_h + breadcrumb_h + editor_h + statusbar_h

        # Create canvas
        image = Image.new("RGBA", (width, height), BG_EDITOR)
        draw = ImageDraw.Draw(image)

        # Current Y pointer
        curr_y = 0

        # ----------------------------------------------------------------------
        # A. TITLE BAR (Full frame only)
        # ----------------------------------------------------------------------
        if self.frame == "full":
            draw.rectangle(
                [(0, curr_y), (width, curr_y + titlebar_h)],
                fill=BG_TITLEBAR,
            )
            # Divider below titlebar
            draw.line(
                [(0, curr_y + titlebar_h - 1), (width, curr_y + titlebar_h - 1)],
                fill=BORDER_DIVIDER,
                width=1,
            )

            if self.os_style == "mac":
                # macOS Traffic lights
                dot_r = int(6 * self.scale)
                dot_y = curr_y + (titlebar_h // 2)
                start_x = int(14 * self.scale)
                spacing = int(20 * self.scale)

                # Red, Yellow, Green circles
                for i, color in enumerate([MAC_RED, MAC_YELLOW, MAC_GREEN]):
                    cx = start_x + (i * spacing)
                    draw.ellipse(
                        [(cx - dot_r, dot_y - dot_r), (cx + dot_r, dot_y + dot_r)],
                        fill=color,
                    )

                # Title text (centered)
                title_text = f"{self.name} — {self.project}"
                try:
                    title_w = self.ui_font.getlength(title_text)
                except AttributeError:
                    title_w = len(title_text) * (self.char_w * 0.8)
                tx = (width - title_w) // 2
                ty = curr_y + (titlebar_h - self.ui_font_size) // 2
                draw.text((tx, ty), title_text, fill=FG_TITLEBAR, font=self.ui_font)

            else:
                # Windows Title Bar
                win_icon_x = int(12 * self.scale)
                win_ty = curr_y + (titlebar_h - self.ui_font_size) // 2
                # VS Code blue icon mark
                draw.text(
                    (win_icon_x, win_ty),
                    "◈",
                    fill="#007ACC",
                    font=self.ui_font_bold,
                )
                title_text = f"{self.name} - {self.project} - Visual Studio Code"
                draw.text(
                    (win_icon_x + int(18 * self.scale), win_ty),
                    title_text,
                    fill=FG_TITLEBAR,
                    font=self.ui_font,
                )

                # Windows controls: minimize, maximize, close
                ctrl_w = int(45 * self.scale)
                rx = width - (ctrl_w * 3)
                cy = curr_y + (titlebar_h // 2)
                # Minimize
                draw.line([(rx + 15, cy), (rx + 30, cy)], fill="#CCCCCC", width=1)
                # Maximize
                mx = rx + ctrl_w
                draw.rectangle([(mx + 16, cy - 5), (mx + 28, cy + 5)], outline="#CCCCCC", width=1)
                # Close
                cx = mx + ctrl_w
                draw.line([(cx + 17, cy - 5), (cx + 27, cy + 5)], fill="#CCCCCC", width=1)
                draw.line([(cx + 27, cy - 5), (cx + 17, cy + 5)], fill="#CCCCCC", width=1)

            curr_y += titlebar_h

        # ----------------------------------------------------------------------
        # B. TAB BAR (Tab frame & Full frame)
        # ----------------------------------------------------------------------
        if self.frame in ["tab", "full"]:
            draw.rectangle(
                [(0, curr_y), (width, curr_y + tabbar_h)],
                fill=BG_TAB_BAR,
            )

            # Active tab dimensions
            try:
                name_w = self.ui_font.getlength(self.name)
            except AttributeError:
                name_w = len(self.name) * (self.char_w * 0.8)

            badge_w = int(24 * self.scale)
            tab_padding = int(14 * self.scale)
            tab_w = int(name_w + badge_w + tab_padding * 2 + (20 * self.scale))

            # Active tab background
            draw.rectangle(
                [(0, curr_y), (tab_w, curr_y + tabbar_h)],
                fill=BG_TAB_ACTIVE,
            )
            # Active tab blue top accent line (VS Code Dark+ classic)
            draw.line(
                [(0, curr_y), (tab_w, curr_y)],
                fill=BORDER_TAB_ACTIVE_TOP,
                width=int(2 * self.scale),
            )
            # Tab border right divider
            draw.line(
                [(tab_w, curr_y), (tab_w, curr_y + tabbar_h)],
                fill=BG_TAB_BAR,
                width=1,
            )

            # File Badge Icon in active tab
            icon_x = int(12 * self.scale)
            icon_y = curr_y + (tabbar_h - int(14 * self.scale)) // 2
            # Draw badge background
            draw.rounded_rectangle(
                [
                    (icon_x, icon_y),
                    (icon_x + int(20 * self.scale), icon_y + int(14 * self.scale)),
                ],
                radius=int(3 * self.scale),
                fill=self.badge_color,
            )
            # Badge text (e.g. PY, GO, JS)
            draw.text(
                (icon_x + int(3 * self.scale), icon_y + int(1 * self.scale)),
                self.badge_symbol[:3],
                fill="#FFFFFF",
                font=self.ui_font_bold,
            )

            # Tab text (File name)
            tab_text_x = icon_x + int(26 * self.scale)
            tab_text_y = curr_y + (tabbar_h - self.ui_font_size) // 2
            draw.text(
                (tab_text_x, tab_text_y),
                self.name,
                fill=FG_TAB_ACTIVE,
                font=self.ui_font,
            )

            # Close button '✕'
            close_x = tab_w - int(16 * self.scale)
            draw.text(
                (close_x, tab_text_y),
                "×",
                fill=FG_TAB_CLOSE,
                font=self.ui_font,
            )

            # Tab bar right action icon dots '...'
            more_x = width - int(24 * self.scale)
            draw.text(
                (more_x, tab_text_y),
                "⋯",
                fill=FG_TAB_CLOSE,
                font=self.ui_font,
            )

            curr_y += tabbar_h

        # ----------------------------------------------------------------------
        # C. BREADCRUMBS BAR (Tab frame & Full frame)
        # ----------------------------------------------------------------------
        if self.frame in ["tab", "full"]:
            draw.rectangle(
                [(0, curr_y), (width, curr_y + breadcrumb_h)],
                fill=BG_BREADCRUMB,
            )
            # Divider below breadcrumbs
            draw.line(
                [(0, curr_y + breadcrumb_h - 1), (width, curr_y + breadcrumb_h - 1)],
                fill=BORDER_DIVIDER,
                width=1,
            )

            # Render breadcrumb parts (e.g. src > utils > main.py)
            clean_path = self.path.replace("\\", "/").strip("/")
            parts = clean_path.split("/") if clean_path else [self.name]
            bc_x = int(14 * self.scale)
            bc_y = curr_y + (breadcrumb_h - self.ui_font_size) // 2

            for i, p in enumerate(parts):
                is_last = (i == len(parts) - 1)
                color = FG_BREADCRUMB_ACTIVE if is_last else FG_BREADCRUMB

                # If last segment, draw small file icon dot
                if is_last:
                    draw.ellipse(
                        [(bc_x, bc_y + int(3 * self.scale)), (bc_x + int(6 * self.scale), bc_y + int(9 * self.scale))],
                        fill=self.badge_color,
                    )
                    bc_x += int(10 * self.scale)

                draw.text((bc_x, bc_y), p, fill=color, font=self.ui_font)
                try:
                    pw = self.ui_font.getlength(p)
                except AttributeError:
                    pw = len(p) * (self.char_w * 0.8)
                bc_x += int(pw)

                if not is_last:
                    sep_str = " › "
                    draw.text((bc_x, bc_y), sep_str, fill=FG_BREADCRUMB, font=self.ui_font)
                    try:
                        sw = self.ui_font.getlength(sep_str)
                    except AttributeError:
                        sw = len(sep_str) * (self.char_w * 0.8)
                    bc_x += int(sw)

            curr_y += breadcrumb_h

        # ----------------------------------------------------------------------
        # D. EDITOR AREA (Gutter + Code)
        # ----------------------------------------------------------------------
        editor_top_y = curr_y
        row_y = editor_top_y + pad_y

        for r in rows:
            # Check if this row is a Jupyter notebook banner
            if r.get("is_cell_banner"):
                banner_str = r["banner_text"]
                draw.text(
                    (pad_x + gutter_width, row_y),
                    banner_str,
                    fill=r["tokens"][0][1],
                    font=self.code_font_bold,
                )
                row_y += self.line_height
                continue

            # Row background highlight if active line or highlighted
            if r["is_highlight"]:
                draw.rectangle(
                    [(0, row_y - int(2 * self.scale)), (width, row_y + self.line_height - int(2 * self.scale))],
                    fill=HIGHLIGHT_BG,
                )
                # Left accent border on highlighted line
                draw.rectangle(
                    [(0, row_y - int(2 * self.scale)), (int(3 * self.scale), row_y + self.line_height - int(2 * self.scale))],
                    fill=HIGHLIGHT_ACCENT,
                )
            elif r["has_cursor"]:
                # Subtle active line highlight
                draw.rectangle(
                    [(0, row_y - int(2 * self.scale)), (width, row_y + self.line_height - int(2 * self.scale))],
                    fill=LINE_ACTIVE_BG,
                )

            # Draw Line Number in Gutter
            disp_no = r["line_no"]
            if disp_no is not None:
                no_str = str(disp_no)
                try:
                    no_w = self.code_font.getlength(no_str)
                except AttributeError:
                    no_w = len(no_str) * self.char_w

                no_x = int(gutter_width - no_w - (12 * self.scale))
                no_color = GUTTER_ACTIVE_FG if r["has_cursor"] else GUTTER_FG
                draw.text(
                    (no_x, row_y),
                    no_str,
                    fill=no_color,
                    font=self.code_font,
                )

            # Draw Code Tokens
            token_x = gutter_width + int(10 * self.scale)
            for token_text, token_color in r["tokens"]:
                draw.text(
                    (token_x, row_y),
                    token_text,
                    fill=token_color,
                    font=self.code_font,
                )
                try:
                    tw = self.code_font.getlength(token_text)
                except AttributeError:
                    tw = len(token_text) * self.char_w
                token_x += tw

            # Draw Cursor if active on this row
            if r["has_cursor"] and r["cursor_col"]:
                col_idx = r["cursor_col"] - 1
                # Calculate cursor X position
                full_line_text = "".join(t[0] for t in r["tokens"])
                prefix = full_line_text[:col_idx]
                try:
                    cur_offset_x = self.code_font.getlength(prefix)
                except AttributeError:
                    cur_offset_x = len(prefix) * self.char_w

                cur_x = gutter_width + int(10 * self.scale) + cur_offset_x
                cur_y1 = row_y - int(1 * self.scale)
                cur_y2 = row_y + self.line_height - int(3 * self.scale)
                draw.line(
                    [(cur_x, cur_y1), (cur_x, cur_y2)],
                    fill=CURSOR_COLOR,
                    width=int(2 * self.scale),
                )

            row_y += self.line_height

        curr_y += editor_h

        # ----------------------------------------------------------------------
        # E. STATUS BAR (Full frame only, when not disabled)
        # ----------------------------------------------------------------------
        if has_statusbar:
            draw.rectangle(
                [(0, curr_y), (width, curr_y + statusbar_h)],
                fill=BG_STATUSBAR,
            )
            sb_ty = curr_y + (statusbar_h - self.ui_font_size) // 2

            # Left items: Branch + Error/Warning
            branch_str = f" ⎇ {self.branch} "
            draw.text((int(8 * self.scale), sb_ty), branch_str, fill=FG_STATUSBAR, font=self.ui_font)
            try:
                bw = self.ui_font.getlength(branch_str)
            except AttributeError:
                bw = len(branch_str) * (self.char_w * 0.8)

            err_str = " ⮾ 0  ⚠ 0 "
            draw.text((int(8 * self.scale) + bw + int(10 * self.scale), sb_ty), err_str, fill=FG_STATUSBAR, font=self.ui_font)

            # Right items: Cursor / Spaces / UTF-8 / LF / Language
            cursor_line_disp = self.cursor_pos[0] if self.cursor_pos else (self.start_line + len(rows) - 1)
            cursor_col_disp = self.cursor_pos[1] if self.cursor_pos else 1
            info_parts = [
                f"Ln {cursor_line_disp}, Col {cursor_col_disp}",
                "Spaces: 4",
                "UTF-8",
                "LF",
                self.lang_name,
                "🔔",
            ]
            full_info_str = "   ".join(info_parts) + " "
            try:
                info_w = self.ui_font.getlength(full_info_str)
            except AttributeError:
                info_w = len(full_info_str) * (self.char_w * 0.8)

            draw.text(
                (width - info_w - int(10 * self.scale), sb_ty),
                full_info_str,
                fill=FG_STATUSBAR,
                font=self.ui_font,
            )

            curr_y += statusbar_h

        # ----------------------------------------------------------------------
        # F. FINAL TOUCH: BORDER
        # ----------------------------------------------------------------------
        if self.frame in ["tab", "full"]:
            draw.rectangle([(0, 0), (width - 1, height - 1)], outline=WINDOW_BORDER, width=1)

        return image

    def _render_notebook(self) -> Image.Image:
        """Render Jupyter Notebook cells with rich Markdown and dedicated Code cards."""
        # Header heights
        titlebar_h = int(32 * self.scale) if self.frame == "full" else 0
        tabbar_h = int(35 * self.scale) if self.frame in ["tab", "full"] else 0
        breadcrumb_h = int(24 * self.scale) if self.frame in ["tab", "full"] else 0
        has_statusbar = (self.frame == "full") and (not self.no_status_bar)
        statusbar_h = int(22 * self.scale) if has_statusbar else 0

        # Margins & card offsets
        left_pad = int(16 * self.scale) if self.frame != "none" else int(8 * self.scale)
        right_pad = int(20 * self.scale) if self.frame != "none" else int(8 * self.scale)
        prompt_w = int(50 * self.scale)
        card_x = left_pad + prompt_w + int(10 * self.scale)
        inter_cell_gap = int(16 * self.scale)
        editor_pad_y = int(16 * self.scale)

        cell_layouts: list[dict[str, Any]] = []
        max_card_content_w = int(520 * self.scale)

        # 1. Precompute layout and sizes for each cell
        for cell in (self.ipynb_cells or []):
            c_type = cell.get("cell_type", "code")
            source = cell.get("source", "")
            if c_type == "markdown":
                blocks = parse_markdown_blocks(source)
                card_h = int(24 * self.scale)  # padding top + bottom
                for b in blocks:
                    bt = b["type"]
                    if bt == "h1":
                        card_h += int(self.base_font_size * 1.5 * 1.4) + int(10 * self.scale)
                    elif bt == "h2":
                        card_h += int(self.base_font_size * 1.3 * 1.35) + int(8 * self.scale)
                    elif bt == "h3":
                        card_h += int(self.base_font_size * 1.15 * 1.3) + int(6 * self.scale)
                    elif bt == "h4":
                        card_h += int(self.base_font_size * 1.05 * 1.3) + int(4 * self.scale)
                    elif bt == "blank":
                        card_h += int(self.base_font_size * 0.6)
                    elif bt == "hr":
                        card_h += int(14 * self.scale)
                    else:
                        card_h += int(self.base_font_size * 1.55)
                cell_layouts.append({"type": "markdown", "blocks": blocks, "height": card_h})
            else:
                # Code cell
                lexer = resolve_lexer("python", "", source)
                token_lines = tokenize_code_lines(source, lexer)
                wrapped = soft_wrap_token_lines(token_lines, self.wrap_cols or 0)
                code_lines_h = len(wrapped) * int(self.base_font_size * 1.55) + int(20 * self.scale)

                raw_outputs = cell.get("outputs", [])
                out_h = (len(raw_outputs) * int(self.base_font_size * 1.55) + int(14 * self.scale)) if raw_outputs else 0
                total_card_h = code_lines_h + out_h

                inner_gutter_w = int(max(2, len(str(len(wrapped)))) * self.char_w + int(20 * self.scale))
                cell_layouts.append({
                    "type": "code",
                    "lines": wrapped,
                    "outputs": raw_outputs,
                    "exec_count": cell.get("execution_count"),
                    "height": total_card_h,
                    "gutter_w": inner_gutter_w,
                })

        # Calculate overall canvas dimensions
        min_width = int(720 * self.scale) if self.frame in ["tab", "full"] else int(520 * self.scale)
        width = max(min_width, card_x + max_card_content_w + right_pad)
        card_w = width - card_x - right_pad

        total_cells_h = sum(c["height"] for c in cell_layouts) + max(0, len(cell_layouts) - 1) * inter_cell_gap
        total_editor_h = editor_pad_y * 2 + total_cells_h
        height = titlebar_h + tabbar_h + breadcrumb_h + total_editor_h + statusbar_h

        image = Image.new("RGBA", (width, height), BG_EDITOR)
        draw = ImageDraw.Draw(image)

        curr_y = 0

        # ----------------------------------------------------------------------
        # A. TITLE BAR (Full frame only)
        # ----------------------------------------------------------------------
        if self.frame == "full":
            draw.rectangle([(0, curr_y), (width, curr_y + titlebar_h)], fill=BG_TITLEBAR)
            draw.line([(0, curr_y + titlebar_h - 1), (width, curr_y + titlebar_h - 1)], fill=BORDER_DIVIDER, width=1)

            if self.os_style == "mac":
                dot_r = int(6 * self.scale)
                dot_y = curr_y + (titlebar_h // 2)
                start_x = int(14 * self.scale)
                spacing = int(20 * self.scale)
                for i, color in enumerate([MAC_RED, MAC_YELLOW, MAC_GREEN]):
                    cx = start_x + (i * spacing)
                    draw.ellipse([(cx - dot_r, dot_y - dot_r), (cx + dot_r, dot_y + dot_r)], fill=color)

                title_text = f"{self.name} — {self.project}"
                try:
                    title_w = self.ui_font.getlength(title_text)
                except AttributeError:
                    title_w = len(title_text) * (self.char_w * 0.8)
                tx = (width - title_w) // 2
                ty = curr_y + (titlebar_h - self.ui_font_size) // 2
                draw.text((tx, ty), title_text, fill=FG_TITLEBAR, font=self.ui_font)
            else:
                win_icon_x = int(12 * self.scale)
                win_ty = curr_y + (titlebar_h - self.ui_font_size) // 2
                draw.text((win_icon_x, win_ty), "◈", fill="#007ACC", font=self.ui_font_bold)
                title_text = f"{self.name} - {self.project} - Visual Studio Code"
                draw.text((win_icon_x + int(18 * self.scale), win_ty), title_text, fill=FG_TITLEBAR, font=self.ui_font)

                ctrl_w = int(45 * self.scale)
                rx = width - (ctrl_w * 3)
                cy = curr_y + (titlebar_h // 2)
                draw.line([(rx + 15, cy), (rx + 30, cy)], fill="#CCCCCC", width=1)
                mx = rx + ctrl_w
                draw.rectangle([(mx + 16, cy - 5), (mx + 28, cy + 5)], outline="#CCCCCC", width=1)
                cx = mx + ctrl_w
                draw.line([(cx + 17, cy - 5), (cx + 27, cy + 5)], fill="#CCCCCC", width=1)
                draw.line([(cx + 27, cy - 5), (cx + 17, cy + 5)], fill="#CCCCCC", width=1)

            curr_y += titlebar_h

        # ----------------------------------------------------------------------
        # B. TAB BAR (Tab frame & Full frame)
        # ----------------------------------------------------------------------
        if self.frame in ["tab", "full"]:
            draw.rectangle([(0, curr_y), (width, curr_y + tabbar_h)], fill=BG_TAB_BAR)

            try:
                name_w = self.ui_font.getlength(self.name)
            except AttributeError:
                name_w = len(self.name) * (self.char_w * 0.8)

            badge_w = int(24 * self.scale)
            tab_padding = int(14 * self.scale)
            tab_w = int(name_w + badge_w + tab_padding * 2 + (20 * self.scale))

            draw.rectangle([(0, curr_y), (tab_w, curr_y + tabbar_h)], fill=BG_TAB_ACTIVE)
            draw.line([(0, curr_y), (tab_w, curr_y)], fill=BORDER_TAB_ACTIVE_TOP, width=int(2 * self.scale))
            draw.line([(tab_w, curr_y), (tab_w, curr_y + tabbar_h)], fill=BG_TAB_BAR, width=1)

            # File Badge Icon in active tab (Orange Jupyter NB)
            icon_x = int(12 * self.scale)
            icon_y = curr_y + (tabbar_h - int(14 * self.scale)) // 2
            draw.rounded_rectangle(
                [(icon_x, icon_y), (icon_x + int(20 * self.scale), icon_y + int(14 * self.scale))],
                radius=int(3 * self.scale),
                fill=self.badge_color,
            )
            draw.text((icon_x + int(3 * self.scale), icon_y + int(1 * self.scale)), self.badge_symbol[:3], fill="#FFFFFF", font=self.ui_font_bold)

            tab_text_x = icon_x + int(26 * self.scale)
            tab_text_y = curr_y + (tabbar_h - self.ui_font_size) // 2
            draw.text((tab_text_x, tab_text_y), self.name, fill=FG_TAB_ACTIVE, font=self.ui_font)

            close_x = tab_w - int(16 * self.scale)
            draw.text((close_x, tab_text_y), "×", fill=FG_TAB_CLOSE, font=self.ui_font)

            more_x = width - int(24 * self.scale)
            draw.text((more_x, tab_text_y), "⋯", fill=FG_TAB_CLOSE, font=self.ui_font)

            curr_y += tabbar_h

        # ----------------------------------------------------------------------
        # C. BREADCRUMBS BAR (Tab frame & Full frame)
        # ----------------------------------------------------------------------
        if self.frame in ["tab", "full"]:
            draw.rectangle([(0, curr_y), (width, curr_y + breadcrumb_h)], fill=BG_BREADCRUMB)
            draw.line([(0, curr_y + breadcrumb_h - 1), (width, curr_y + breadcrumb_h - 1)], fill=BORDER_DIVIDER, width=1)

            clean_path = self.path.replace("\\", "/").strip("/")
            parts = clean_path.split("/") if clean_path else [self.name]
            bc_x = int(14 * self.scale)
            bc_y = curr_y + (breadcrumb_h - self.ui_font_size) // 2

            for i, p in enumerate(parts):
                is_last = (i == len(parts) - 1)
                color = FG_BREADCRUMB_ACTIVE if is_last else FG_BREADCRUMB
                if is_last:
                    draw.ellipse(
                        [(bc_x, bc_y + int(3 * self.scale)), (bc_x + int(6 * self.scale), bc_y + int(9 * self.scale))],
                        fill=self.badge_color,
                    )
                    bc_x += int(10 * self.scale)

                draw.text((bc_x, bc_y), p, fill=color, font=self.ui_font)
                try:
                    pw = self.ui_font.getlength(p)
                except AttributeError:
                    pw = len(p) * (self.char_w * 0.8)
                bc_x += int(pw)

                if not is_last:
                    sep_str = " › "
                    draw.text((bc_x, bc_y), sep_str, fill=FG_BREADCRUMB, font=self.ui_font)
                    try:
                        sw = self.ui_font.getlength(sep_str)
                    except AttributeError:
                        sw = len(sep_str) * (self.char_w * 0.8)
                    bc_x += int(sw)

            curr_y += breadcrumb_h

        # ----------------------------------------------------------------------
        # D. NOTEBOOK CELLS AREA
        # ----------------------------------------------------------------------
        curr_y += editor_pad_y

        for c in cell_layouts:
            card_h = c["height"]

            if c["type"] == "markdown":
                # Render Markdown Card
                draw.rounded_rectangle(
                    [(card_x, curr_y), (card_x + card_w, curr_y + card_h)],
                    radius=int(4 * self.scale),
                    fill=BG_EDITOR,
                    outline="#2D2D2E",
                    width=1,
                )

                bx = card_x + int(14 * self.scale)
                by = curr_y + int(12 * self.scale)

                for b in c["blocks"]:
                    bt = b["type"]
                    if bt == "h1":
                        draw.text((bx, by), b["text"], fill="#FFFFFF", font=self.md_h1_font)
                        by += int(self.base_font_size * 1.5 * 1.4) + int(4 * self.scale)
                        # Subtle divider under H1
                        draw.line([(bx, by), (card_x + card_w - int(14 * self.scale), by)], fill="#2D2D2E", width=1)
                        by += int(6 * self.scale)
                    elif bt == "h2":
                        draw.text((bx, by), b["text"], fill="#FFFFFF", font=self.md_h2_font)
                        by += int(self.base_font_size * 1.3 * 1.35) + int(8 * self.scale)
                    elif bt == "h3":
                        draw.text((bx, by), b["text"], fill="#E0E0E0", font=self.md_h3_font)
                        by += int(self.base_font_size * 1.15 * 1.3) + int(6 * self.scale)
                    elif bt == "h4":
                        draw.text((bx, by), b["text"], fill="#E0E0E0", font=self.md_text_bold)
                        by += int(self.base_font_size * 1.05 * 1.3) + int(4 * self.scale)
                    elif bt == "bullet":
                        draw.text((bx + int(2 * self.scale), by), "•", fill="#007ACC", font=self.md_text_bold)
                        sp_x = bx + int(16 * self.scale)
                        for sp in b["spans"]:
                            f = self.md_text_bold if sp["style"] == "bold" else self.md_text_font
                            col = "#FFFFFF" if sp["style"] == "bold" else "#D4D4D4"
                            draw.text((sp_x, by), sp["text"], fill=col, font=f)
                            try:
                                sp_x += f.getlength(sp["text"])
                            except AttributeError:
                                sp_x += len(sp["text"]) * (self.char_w * 0.8)
                        by += int(self.base_font_size * 1.55)
                    elif bt == "number":
                        num_str = b.get("num", "1. ")
                        draw.text((bx, by), num_str, fill="#858585", font=self.md_text_font)
                        sp_x = bx + int(18 * self.scale)
                        for sp in b["spans"]:
                            f = self.md_text_bold if sp["style"] == "bold" else self.md_text_font
                            col = "#FFFFFF" if sp["style"] == "bold" else "#D4D4D4"
                            draw.text((sp_x, by), sp["text"], fill=col, font=f)
                            try:
                                sp_x += f.getlength(sp["text"])
                            except AttributeError:
                                sp_x += len(sp["text"]) * (self.char_w * 0.8)
                        by += int(self.base_font_size * 1.55)
                    elif bt == "quote":
                        draw.line([(bx, by), (bx, by + int(self.base_font_size * 1.4))], fill="#007ACC", width=int(3 * self.scale))
                        sp_x = bx + int(10 * self.scale)
                        for sp in b["spans"]:
                            draw.text((sp_x, by), sp["text"], fill="#A9A9A9", font=self.md_text_font)
                            try:
                                sp_x += self.md_text_font.getlength(sp["text"])
                            except AttributeError:
                                sp_x += len(sp["text"]) * (self.char_w * 0.8)
                        by += int(self.base_font_size * 1.55)
                    elif bt == "hr":
                        draw.line([(bx, by + int(7 * self.scale)), (card_x + card_w - int(14 * self.scale), by + int(7 * self.scale))], fill="#3C3C3C", width=1)
                        by += int(14 * self.scale)
                    elif bt == "paragraph":
                        sp_x = bx
                        for sp in b["spans"]:
                            if sp["style"] == "code":
                                try:
                                    cw = self.code_font.getlength(sp["text"])
                                except AttributeError:
                                    cw = len(sp["text"]) * self.char_w
                                pill_pad = int(4 * self.scale)
                                draw.rounded_rectangle(
                                    [(sp_x, by - int(1 * self.scale)), (sp_x + cw + pill_pad * 2, by + self.base_font_size + int(1 * self.scale))],
                                    radius=int(3 * self.scale),
                                    fill="#2D2D2D",
                                )
                                draw.text((sp_x + pill_pad, by), sp["text"], fill="#CE9178", font=self.code_font)
                                sp_x += cw + pill_pad * 2
                            else:
                                f = self.md_text_bold if sp["style"] == "bold" else self.md_text_font
                                col = "#FFFFFF" if sp["style"] == "bold" else "#D4D4D4"
                                draw.text((sp_x, by), sp["text"], fill=col, font=f)
                                try:
                                    sp_x += f.getlength(sp["text"])
                                except AttributeError:
                                    sp_x += len(sp["text"]) * (self.char_w * 0.8)
                        by += int(self.base_font_size * 1.55)
                    elif bt == "blank":
                        by += int(self.base_font_size * 0.6)

            else:
                # Code Cell
                # 1. Left prompt: Run button (Play circle)
                btn_cx = left_pad + int(26 * self.scale)
                btn_cy = curr_y + int(14 * self.scale)
                btn_r = int(8 * self.scale)
                draw.ellipse([(btn_cx - btn_r, btn_cy - btn_r), (btn_cx + btn_r, btn_cy + btn_r)], fill="#0E639C")
                draw.polygon(
                    [
                        (btn_cx - int(2 * self.scale), btn_cy - int(4 * self.scale)),
                        (btn_cx + int(4 * self.scale), btn_cy),
                        (btn_cx - int(2 * self.scale), btn_cy + int(4 * self.scale)),
                    ],
                    fill="#FFFFFF",
                )

                # Execution count
                ec_str = f"[{c['exec_count']}]" if c["exec_count"] is not None else "[ ]"
                draw.text((left_pad + int(14 * self.scale), curr_y + int(28 * self.scale)), ec_str, fill="#858585", font=self.ui_font)

                # 2. Draw Code Box Card
                draw.rounded_rectangle(
                    [(card_x, curr_y), (card_x + card_w, curr_y + card_h)],
                    radius=int(4 * self.scale),
                    fill=BG_EDITOR,
                    outline="#3C3C3C",
                    width=1,
                )

                inner_gutter = c.get("gutter_w", int(32 * self.scale))
                line_y = curr_y + int(10 * self.scale)

                # Draw code lines and line numbers
                for idx, (orig_idx, tokens) in enumerate(c["lines"]):
                    if orig_idx is not None:
                        ln_str = str(orig_idx + 1)
                        try:
                            ln_w = self.code_font.getlength(ln_str)
                        except AttributeError:
                            ln_w = len(ln_str) * self.char_w
                        draw.text((card_x + inner_gutter - ln_w - int(8 * self.scale), line_y), ln_str, fill=GUTTER_FG, font=self.code_font)

                    tx = card_x + inner_gutter + int(10 * self.scale)
                    for t_text, t_col in tokens:
                        draw.text((tx, line_y), t_text, fill=t_col, font=self.code_font)
                        try:
                            tw = self.code_font.getlength(t_text)
                        except AttributeError:
                            tw = len(t_text) * self.char_w
                        tx += tw

                    line_y += int(self.base_font_size * 1.55)

                # Draw Outputs if present
                if c.get("outputs"):
                    draw.line([(card_x, line_y + int(4 * self.scale)), (card_x + card_w, line_y + int(4 * self.scale))], fill="#2B2B2B", width=1)
                    out_y = line_y + int(10 * self.scale)
                    for out_ln in c["outputs"]:
                        draw.text((card_x + int(16 * self.scale), out_y), out_ln, fill="#CCCCCC", font=self.code_font)
                        out_y += int(self.base_font_size * 1.55)

            curr_y += card_h + inter_cell_gap

        # ----------------------------------------------------------------------
        # E. STATUS BAR (Full frame only)
        # ----------------------------------------------------------------------
        if has_statusbar:
            draw.rectangle([(0, curr_y), (width, curr_y + statusbar_h)], fill=BG_STATUSBAR)
            sb_ty = curr_y + (statusbar_h - self.ui_font_size) // 2

            branch_str = f" ⎇ {self.branch} "
            draw.text((int(8 * self.scale), sb_ty), branch_str, fill=FG_STATUSBAR, font=self.ui_font)
            try:
                bw = self.ui_font.getlength(branch_str)
            except AttributeError:
                bw = len(branch_str) * (self.char_w * 0.8)

            err_str = " ⮾ 0  ⚠ 0 "
            draw.text((int(8 * self.scale) + bw + int(10 * self.scale), sb_ty), err_str, fill=FG_STATUSBAR, font=self.ui_font)

            info_parts = [
                "Jupyter: Idle",
                "Python 3.12",
                "UTF-8",
                "LF",
                "Jupyter",
                "🔔",
            ]
            full_info_str = "   ".join(info_parts) + " "
            try:
                info_w = self.ui_font.getlength(full_info_str)
            except AttributeError:
                info_w = len(full_info_str) * (self.char_w * 0.8)

            draw.text((width - info_w - int(10 * self.scale), sb_ty), full_info_str, fill=FG_STATUSBAR, font=self.ui_font)
            curr_y += statusbar_h

        # ----------------------------------------------------------------------
        # F. FINAL TOUCH: BORDER
        # ----------------------------------------------------------------------
        if self.frame in ["tab", "full"]:
            draw.rectangle([(0, 0), (width - 1, height - 1)], outline=WINDOW_BORDER, width=1)

        return image


# ==============================================================================
# 4. CONVENIENCE ENTRYPOINTS & CLI PARSER
# ==============================================================================

def render_code_to_image(
    code: str,
    output_path: str = "code.png",
    lang: str | None = None,
    name: str = "main.py",
    path: str | None = None,
    frame: str = "tab",
    os_style: str = "mac",
    project: str = "faf-agent",
    branch: str = "main",
    highlight: str | None = None,
    cursor: str | None = None,
    wrap: int | None = None,
    scale: int | float = 2,
    start_line: int = 1,
    font_path: str | None = None,
    font_dir: str | None = ".fonts",
    no_status_bar: bool = False,
) -> str:
    """Render code string to a PNG file and return the saved file path."""
    renderer = VSCodeImageRenderer(
        code=code,
        lang=lang,
        name=name,
        path=path,
        frame=frame,
        os_style=os_style,
        project=project,
        branch=branch,
        highlight_str=highlight,
        cursor_str=cursor,
        wrap_cols=wrap,
        scale=scale,
        start_line=start_line,
        font_path=font_path,
        font_dir=font_dir,
        no_status_bar=no_status_bar,
    )
    img = renderer.render()
    output_abs = os.path.abspath(output_path)
    os.makedirs(os.path.dirname(output_abs) or ".", exist_ok=True)
    img.save(output_abs, format="PNG", optimize=True)
    return output_abs


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ubah teks/kode jadi gambar PNG bergaya VS Code (tema Dark+)."
    )
    group_input = parser.add_mutually_exclusive_group()
    group_input.add_argument("--file", "-f", help="Path berkas kode sumber")
    group_input.add_argument("--text", "-t", help="Teks kode secara langsung")

    parser.add_argument(
        "--lang",
        "-l",
        help="Bahasa pemrograman (python, js, go, php, json, bash, ipynb, dll.). Kosong = tebak.",
    )
    parser.add_argument(
        "--name",
        "-n",
        default=None,
        help="Nama file di tab (menentukan ikon & bahasa, contoh: main.py)",
    )
    parser.add_argument(
        "--path",
        "-p",
        default=None,
        help="Isi breadcrumb (contoh: src/utils/main.py)",
    )
    parser.add_argument(
        "--frame",
        choices=["tab", "full", "none"],
        default="tab",
        help="Gaya frame: tab (default, tanpa status bar), full (+ title bar & status bar), none (kode saja)",
    )
    parser.add_argument(
        "--os",
        dest="os_style",
        choices=["mac", "win"],
        default="mac" if sys.platform == "darwin" else "win",
        help="Gaya title bar untuk frame full (mac atau win)",
    )
    parser.add_argument(
        "--project",
        default="faf-agent",
        help="Nama folder/project di title bar",
    )
    parser.add_argument(
        "--branch",
        default="main",
        help="Nama branch di status bar",
    )
    parser.add_argument(
        "--highlight",
        help="Sorot baris tertentu (contoh: 3,5-7,40-42)",
    )
    parser.add_argument(
        "--cursor",
        help="Taruh kursor & highlight baris aktif (contoh: 12:5)",
    )
    parser.add_argument(
        "--wrap",
        type=int,
        default=None,
        help="Soft wrap pada N kolom (contoh: 80)",
    )
    parser.add_argument(
        "--scale",
        type=float,
        default=2.0,
        help="Skala resolusi (2 = tajam / Retina)",
    )
    parser.add_argument(
        "--start-line",
        "-s",
        type=int,
        default=1,
        help="Nomor baris awal pada gutter (contoh: 40)",
    )
    parser.add_argument(
        "--output",
        "-o",
        default="code.png",
        help="Path berkas gambar keluaran PNG (default: code.png)",
    )
    parser.add_argument(
        "--font",
        help="Path ke file font monospace custom (.ttf / .otf / .ttc)",
    )
    parser.add_argument(
        "--font-dir",
        default=".fonts",
        help="Folder berisi font custom (default: .fonts)",
    )
    parser.add_argument(
        "--no-status-bar",
        action="store_true",
        help="Nonaktifkan status bar bahkan ketika frame full digunakan",
    )

    args = parser.parse_args()

    # Read input code
    code_text = ""
    filename = args.name

    if args.file:
        if not os.path.isfile(args.file):
            sys.stderr.write(f"Error: Berkas tidak ditemukan: {args.file}\n")
            sys.exit(1)
        with open(args.file, "r", encoding="utf-8", errors="replace") as f:
            code_text = f.read()
        if not filename:
            filename = os.path.basename(args.file)
        if not args.path:
            args.path = args.file
    elif args.text is not None:
        code_text = args.text
    else:
        # Check stdin
        if not sys.stdin.isatty():
            code_text = sys.stdin.read()
        else:
            parser.print_help()
            sys.exit(1)

    if not filename:
        filename = "main.py"

    out_file = render_code_to_image(
        code=code_text,
        output_path=args.output,
        lang=args.lang,
        name=filename,
        path=args.path,
        frame=args.frame,
        os_style=args.os_style,
        project=args.project,
        branch=args.branch,
        highlight=args.highlight,
        cursor=args.cursor,
        wrap=args.wrap,
        scale=args.scale,
        start_line=args.start_line,
        font_path=args.font,
        font_dir=args.font_dir,
        no_status_bar=args.no_status_bar,
    )

    print(f"Gambar berhasil dibuat: {out_file}")


if __name__ == "__main__":
    main()
