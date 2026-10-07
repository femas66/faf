from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest

from src.core.android_bridge import CommandResult
from src.tools.base import ToolContext
from src.tools.ocr import OcrTool, _clean_text, _resolve_lang


def _ctx() -> ToolContext:
    return ToolContext(chat_id=1, user_id=1)


def _cmd(stdout: str = "", stderr: str = "", rc: int = 0) -> CommandResult:
    return CommandResult(stdout=stdout, stderr=stderr, returncode=rc, command="", executed_as_root=False)


@pytest.fixture
def image(tmp_path):
    p = tmp_path / "struk.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    return str(p)


def test_resolve_lang_filters_uninstalled():
    assert _resolve_lang("ind+eng", ["eng", "osd"]) == "eng"
    assert _resolve_lang("ind+eng", ["eng", "ind"]) == "ind+eng"
    assert _resolve_lang("jpn", ["osd"]) == "osd"
    assert _resolve_lang("ind", []) == "ind"


def test_clean_text():
    assert _clean_text("a  \n\n\n\nb\x0c") == "a\n\nb"


async def test_missing_path():
    res = await OcrTool().execute(_ctx(), source="file")
    assert not res.success and "path" in res.error


async def test_file_not_found():
    res = await OcrTool().execute(_ctx(), path="/tidak/ada.png")
    assert not res.success and "tidak ditemukan" in res.error


async def test_unsupported_extension(tmp_path):
    p = tmp_path / "doc.pdf"
    p.write_bytes(b"x")
    res = await OcrTool().execute(_ctx(), path=str(p))
    assert not res.success and "tidak didukung" in res.error


async def test_tesseract_extract(image):
    async def fake_exec(cmd, **kw):
        if "--list-langs" in cmd:
            return _cmd("List of available languages (2):\neng\nind")
        return _cmd("TOTAL  Rp 25.000\n\x0c")

    with patch("src.tools.ocr._find_tesseract", return_value="/usr/bin/tesseract"), \
         patch("src.tools.ocr.bridge.execute_shell", side_effect=fake_exec) as mock_exec:
        res = await OcrTool().execute(_ctx(), path=image)

    assert res.success
    assert "TOTAL  Rp 25.000" in res.output
    assert "Tesseract (ind+eng)" in res.output
    assert "-l ind+eng" in mock_exec.call_args_list[-1].args[0]
    assert "--psm 3" in mock_exec.call_args_list[-1].args[0]


async def test_tesseract_custom_psm(image):
    async def fake_exec(cmd, **kw):
        if "--list-langs" in cmd:
            return _cmd("eng")
        return _cmd("Single line text")

    with patch("src.tools.ocr._find_tesseract", return_value="/usr/bin/tesseract"), \
         patch("src.tools.ocr.bridge.execute_shell", side_effect=fake_exec) as mock_exec:
        res = await OcrTool().execute(_ctx(), path=image, psm=6)

    assert res.success
    assert "Single line text" in res.output
    assert "--psm 6" in mock_exec.call_args_list[-1].args[0]


async def test_tesseract_missing_error(image):
    with patch("src.tools.ocr._find_tesseract", return_value=None):
        res = await OcrTool().execute(_ctx(), path=image)
    assert not res.success and "pkg install tesseract" in res.error


async def test_tesseract_execution_failure(image):
    async def fake_exec(cmd, **kw):
        if "--list-langs" in cmd:
            return _cmd("eng")
        return _cmd(stderr="Error reading image", rc=1)

    with patch("src.tools.ocr._find_tesseract", return_value="/usr/bin/tesseract"), \
         patch("src.tools.ocr.bridge.execute_shell", side_effect=fake_exec):
        res = await OcrTool().execute(_ctx(), path=image)
    assert not res.success and "Tesseract gagal" in res.error


async def test_long_text_saved_as_document(image, tmp_path):
    long_text = "baris teks penting\n" * 1000

    async def fake_exec(cmd, **kw):
        if "--list-langs" in cmd:
            return _cmd("eng")
        return _cmd(long_text)

    with patch("src.tools.ocr._find_tesseract", return_value="/usr/bin/tesseract"), \
         patch("src.tools.ocr.bridge.execute_shell", side_effect=fake_exec):
        save = tmp_path / "hasil.txt"
        res = await OcrTool().execute(_ctx(), path=image, save_to=str(save))

    assert res.success
    assert res.media_type == "document" and res.media_path == str(save)
    assert os.path.getsize(save) > 0
    assert "dipotong" in res.output


async def test_empty_result_message(image):
    async def fake_exec(cmd, **kw):
        if "--list-langs" in cmd:
            return _cmd("eng")
        return _cmd("")

    with patch("src.tools.ocr._find_tesseract", return_value="/usr/bin/tesseract"), \
         patch("src.tools.ocr.bridge.execute_shell", side_effect=fake_exec):
        res = await OcrTool().execute(_ctx(), path=image)
    assert res.success and "tidak ada teks" in res.output


async def test_check_engine_action():
    async def fake_exec(cmd, **kw):
        if "--version" in cmd:
            return _cmd("tesseract 5.3.4")
        if "--list-langs" in cmd:
            return _cmd("eng\nind")
        return _cmd()

    with patch("src.tools.ocr._find_tesseract", return_value="/usr/bin/tesseract"), \
         patch("src.tools.ocr.bridge.execute_shell", side_effect=fake_exec):
        res = await OcrTool().execute(_ctx(), action="check_engine")

    assert res.success
    assert "TERPASANG" in res.output
    assert "100% Lokal" in res.output
    assert "ind" in res.output


async def test_invalid_url():
    res = await OcrTool().execute(_ctx(), source="url", url="ftp://x/y.png")
    assert not res.success and "URL tidak valid" in res.error


async def test_screen_requires_root(tmp_path):
    with patch("src.tools.ocr._find_tesseract", return_value="/usr/bin/tesseract"), \
         patch("src.tools.ocr.get_settings") as gs, \
         patch("src.tools.ocr.bridge.execute_shell", AsyncMock(return_value=_cmd(stderr="su: not found", rc=1))):
        gs.return_value.temp_media_dir = str(tmp_path)
        res = await OcrTool().execute(_ctx(), source="screen")
    assert not res.success and "root" in res.error


async def test_registered_in_default_registry():
    from src.tools import create_default_registry

    assert create_default_registry().get("ocr_extract") is not None
