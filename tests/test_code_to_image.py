from __future__ import annotations

import asyncio
import json
import os
import tempfile
import pytest
from unittest.mock import AsyncMock

from PIL import Image

from code_to_image import (
    parse_highlight_ranges,
    parse_cursor_pos,
    get_file_type_meta,
    resolve_lexer,
    tokenize_code_lines,
    soft_wrap_token_lines,
    parse_ipynb_cells,
    render_code_to_image,
    VSCodeImageRenderer,
)
from src.tools.base import ToolContext
from src.tools.code_to_image import CodeToImageTool
from src.tools import default_registry


# ------------------------------------------------------------------------------
# 1. Unit Tests for Parsing & Helper Functions
# ------------------------------------------------------------------------------

def test_parse_highlight_ranges():
    assert parse_highlight_ranges("3,5-7,10") == {3, 5, 6, 7, 10}
    assert parse_highlight_ranges("40-42") == {40, 41, 42}
    assert parse_highlight_ranges(None) == set()
    assert parse_highlight_ranges("") == set()
    assert parse_highlight_ranges("abc,12-x") == set()


def test_parse_cursor_pos():
    assert parse_cursor_pos("12:5") == (12, 5)
    assert parse_cursor_pos("1:1") == (1, 1)
    assert parse_cursor_pos(None) is None
    assert parse_cursor_pos("invalid") is None
    assert parse_cursor_pos("12:abc") is None


def test_get_file_type_meta():
    name, color, badge = get_file_type_meta("main.py")
    assert name == "Python"
    assert badge == "PY"

    name_go, color_go, badge_go = get_file_type_meta("server.go")
    assert name_go == "Go"
    assert badge_go == "GO"

    name_php, _, badge_php = get_file_type_meta("index.php")
    assert name_php == "PHP"

    # Test language fallback
    name_js, _, _ = get_file_type_meta("unknown.file", lang="javascript")
    assert name_js == "JavaScript"


def test_resolve_lexer():
    lex_py = resolve_lexer("python", "test.py", "x = 1")
    assert lex_py is not None
    assert "python" in lex_py.name.lower()

    lex_go = resolve_lexer("golang", "", "package main")
    assert lex_go is not None
    assert "go" in lex_go.name.lower()

    lex_php = resolve_lexer("php", "", "<?php echo 1;")
    assert lex_php is not None
    assert "php" in lex_php.name.lower()


def test_tokenize_code_lines():
    code = "def add(a, b):\n    return a + b\n"
    lex = resolve_lexer("python", "test.py", code)
    lines = tokenize_code_lines(code, lex)
    assert len(lines) >= 2
    # Ensure tokens have text and hex colors
    for line in lines:
        for text, color in line:
            assert isinstance(text, str)
            assert color.startswith("#")


def test_soft_wrap_token_lines():
    lines = [[("this_is_a_very_long_string_exceeding_twenty_chars", "#FFFFFF")]]
    wrapped = soft_wrap_token_lines(lines, max_chars=20)
    assert len(wrapped) > 1
    # First row has line index 0, subsequent row has None
    assert wrapped[0][0] == 0
    assert wrapped[1][0] is None


def test_parse_ipynb_cells():
    nb_dict = {
        "cells": [
            {"cell_type": "markdown", "source": ["# Title\n"]},
            {"cell_type": "code", "execution_count": 1, "source": ["print(123)"]},
        ]
    }
    cells = parse_ipynb_cells(json.dumps(nb_dict))
    assert cells is not None
    assert len(cells) == 2
    assert cells[0]["cell_type"] == "markdown"
    assert cells[1]["cell_type"] == "code"

    # Non-json input returns None
    assert parse_ipynb_cells("not a json") is None


# ------------------------------------------------------------------------------
# 2. Rendering Tests for Various Frame and Language Configurations
# ------------------------------------------------------------------------------

def test_render_tab_frame(tmp_path):
    out_file = str(tmp_path / "tab_frame.png")
    code = "def hello():\n    print('VS Code Dark+')\n"
    saved = render_code_to_image(
        code=code,
        output_path=out_file,
        lang="python",
        name="test.py",
        frame="tab",
        start_line=40,
        highlight="41",
        cursor="41:8",
        scale=2,
    )
    assert os.path.isfile(saved)
    with Image.open(saved) as im:
        assert im.format == "PNG"
        w, h = im.size
        assert w > 300
        assert h > 100


def test_render_full_frame_mac_and_win(tmp_path):
    out_mac = str(tmp_path / "full_mac.png")
    out_win = str(tmp_path / "full_win.png")
    code = "package main\nimport \"fmt\"\nfunc main() { fmt.Println(\"hi\") }\n"

    # macOS style
    saved_mac = render_code_to_image(
        code=code,
        output_path=out_mac,
        lang="go",
        name="main.go",
        frame="full",
        os_style="mac",
        project="go-service",
        branch="main",
    )
    assert os.path.isfile(saved_mac)

    # Windows style
    saved_win = render_code_to_image(
        code=code,
        output_path=out_win,
        lang="go",
        name="main.go",
        frame="full",
        os_style="win",
        project="go-service",
        branch="develop",
        no_status_bar=True,
    )
    assert os.path.isfile(saved_win)


def test_render_none_frame(tmp_path):
    out_file = str(tmp_path / "none_frame.png")
    code = "SELECT * FROM users;"
    saved = render_code_to_image(
        code=code,
        output_path=out_file,
        lang="sql",
        name="query.sql",
        frame="none",
    )
    assert os.path.isfile(saved)


def test_render_ipynb_notebook(tmp_path):
    out_file = str(tmp_path / "nb.png")
    nb_dict = {
        "cells": [
            {"cell_type": "markdown", "source": ["# Analysis Notebook\n"]},
            {"cell_type": "code", "execution_count": 2, "source": ["import numpy as np\n"]},
        ]
    }
    saved = render_code_to_image(
        code=json.dumps(nb_dict),
        output_path=out_file,
        name="experiment.ipynb",
        frame="tab",
    )
    assert os.path.isfile(saved)


# ------------------------------------------------------------------------------
# 3. CodeToImageTool Execution & Security Tests
# ------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tool_execute_with_text(tmp_path):
    tool = CodeToImageTool()
    ctx = ToolContext(chat_id=123, user_id=456)
    ctx.on_status_update = AsyncMock()

    res = await tool.execute(
        context=ctx,
        text="console.log('Hello World');",
        name="app.js",
        lang="javascript",
        start_line=1,
        highlight="1",
        frame="tab",
    )

    assert res.success is True
    assert res.media_path is not None
    assert os.path.isfile(res.media_path)
    assert res.media_type == "photo"
    assert "app.js" in res.output
    ctx.on_status_update.assert_called_once()


@pytest.mark.asyncio
async def test_tool_execute_with_file(tmp_path):
    test_code_file = tmp_path / "sample.py"
    test_code_file.write_text("x = [1, 2, 3]\nprint(sum(x))\n", encoding="utf-8")

    tool = CodeToImageTool()
    ctx = ToolContext(chat_id=123, user_id=456)

    res = await tool.execute(
        context=ctx,
        file_path=str(test_code_file),
        start_line=10,
        frame="tab",
    )

    assert res.success is True
    assert res.media_path is not None
    assert os.path.isfile(res.media_path)


@pytest.mark.asyncio
async def test_tool_execute_missing_params():
    tool = CodeToImageTool()
    ctx = ToolContext(chat_id=123, user_id=456)

    res = await tool.execute(context=ctx)
    assert res.success is False
    assert "Harap sertakan kode" in (res.error or "")


@pytest.mark.asyncio
async def test_tool_execute_credential_security_block():
    tool = CodeToImageTool()
    ctx = ToolContext(chat_id=123, user_id=456)

    res = await tool.execute(context=ctx, file_path=".env")
    assert res.success is False
    assert "kredensial" in (res.error or "").lower()


def test_tool_registry_registration():
    assert "code_to_image" in default_registry._tools
    registered_tool = default_registry.get("code_to_image")
    assert isinstance(registered_tool, CodeToImageTool)
    schema = registered_tool.to_openai_tool()
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "code_to_image"
