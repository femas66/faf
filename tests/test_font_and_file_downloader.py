from __future__ import annotations

import io
import os
import tarfile
import tempfile
import zipfile
import pytest
from unittest.mock import AsyncMock, patch

from src.core.tool_router import tool_router, CATEGORY_FILES, CATEGORY_WEB_MEDIA
from src.tools.base import ToolContext
from src.tools.file_mgr import FileManagerTool
from src.tools.media_downloader import (
    MediaDownloaderTool,
    _resolve_font_asset,
    _safe_extract_archive,
    POPULAR_NERD_FONTS,
)


@pytest.fixture
def mock_context():
    return ToolContext(
        chat_id=12345,
        user_id=111,
        message_id=999,
        on_status_update=AsyncMock(),
    )


# ---------------------------------------------------------------------------
# 1. Font Asset Resolution Tests
# ---------------------------------------------------------------------------

def test_resolve_font_asset_popular_presets():
    # JetBrains Mono
    title, url = _resolve_font_asset("jetbrains mono nerd font")
    assert "JetBrainsMono" in title
    assert url.endswith("/JetBrainsMono.tar.xz")

    title, url = _resolve_font_asset("jetbrains mono")
    assert "JetBrainsMono" in title
    assert url.endswith("/JetBrainsMono.tar.xz")

    title, url = _resolve_font_asset("jetbrains")
    assert "JetBrainsMono" in title

    # Fira Code
    title, url = _resolve_font_asset("fira code nerd font")
    assert "FiraCode" in title
    assert url.endswith("/FiraCode.tar.xz")

    # Hack
    title, url = _resolve_font_asset("hack font")
    assert "Hack" in title
    assert url.endswith("/Hack.tar.xz")

    # Cascadia Code
    title, url = _resolve_font_asset("cascadia code")
    assert "CascadiaCode" in title
    assert url.endswith("/CascadiaCode.tar.xz")

    # Meslo
    title, url = _resolve_font_asset("meslo nerd font")
    assert "Meslo" in title
    assert url.endswith("/Meslo.tar.xz")


def test_resolve_font_asset_custom_name():
    # Custom unmapped font converts to PascalCase Nerd Font release URL
    title, url = _resolve_font_asset("comic shanns nerd font")
    assert "ComicShanns" in title
    assert url.endswith("/ComicShanns.tar.xz")


# ---------------------------------------------------------------------------
# 2. Archive Safe Extraction Tests (Zip & Tar.xz & Traversal Protection)
# ---------------------------------------------------------------------------

def test_safe_extract_font_tar_xz(tmp_path):
    # Create in-memory tar.xz containing font files and non-font files
    archive_path = str(tmp_path / "test_fonts.tar.xz")
    target_dir = str(tmp_path / ".fonts")

    with tarfile.open(archive_path, mode="w:xz") as t:
        # Font file 1
        data1 = b"\x00\x01\x00\x00dummy ttf 1"
        ti1 = tarfile.TarInfo(name="subfolder/JetBrainsMono-Regular.ttf")
        ti1.size = len(data1)
        t.addfile(ti1, io.BytesIO(data1))

        # Font file 2
        data2 = b"OTTOdummy otf 2"
        ti2 = tarfile.TarInfo(name="JetBrainsMono-Bold.otf")
        ti2.size = len(data2)
        t.addfile(ti2, io.BytesIO(data2))

        # Non-font file (should be ignored in font_only mode)
        data3 = b"README text"
        ti3 = tarfile.TarInfo(name="README.md")
        ti3.size = len(data3)
        t.addfile(ti3, io.BytesIO(data3))

    extracted = _safe_extract_archive(archive_path, target_dir, font_only=True)
    assert len(extracted) == 2
    fnames = [os.path.basename(p) for p in extracted]
    assert "JetBrainsMono-Regular.ttf" in fnames
    assert "JetBrainsMono-Bold.otf" in fnames
    assert "README.md" not in fnames

    # Check that fonts were extracted to target_dir directly
    assert os.path.exists(os.path.join(target_dir, "JetBrainsMono-Regular.ttf"))
    assert os.path.exists(os.path.join(target_dir, "JetBrainsMono-Bold.otf"))


def test_safe_extract_zip_slip_prevention(tmp_path):
    archive_path = str(tmp_path / "malicious.zip")
    target_dir = str(tmp_path / "safe_dir")

    with zipfile.ZipFile(archive_path, mode="w") as z:
        # Normal font file
        z.writestr("NormalFont.ttf", b"safe font")
        # Traversal file attempt
        z.writestr("../../etc/passwd", b"malicious content")
        z.writestr("../outside.ttf", b"outside font")

    extracted = _safe_extract_archive(archive_path, target_dir, font_only=True)
    assert len(extracted) == 1
    assert os.path.basename(extracted[0]) == "NormalFont.ttf"

    # Ensure traversal file did not escape
    outside_file = tmp_path / "outside.ttf"
    assert not outside_file.exists()


# ---------------------------------------------------------------------------
# 3. MediaDownloaderTool Font Download Action Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_media_downloader_download_font_success(mock_context, tmp_path):
    tool = MediaDownloaderTool()
    target_fonts_dir = str(tmp_path / ".fonts")

    # Prepare a dummy font archive
    dummy_archive = str(tmp_path / "JetBrainsMono.tar.xz")
    with tarfile.open(dummy_archive, mode="w:xz") as t:
        data = b"\x00\x01\x00\x00JetBrainsMonoNerdFont-Regular"
        ti = tarfile.TarInfo(name="JetBrainsMonoNerdFont-Regular.ttf")
        ti.size = len(data)
        t.addfile(ti, io.BytesIO(data))

    # Mock _download_file_to to simulate successful download
    async def mock_dl(url, dest_path, timeout, kwargs):
        import shutil
        shutil.copy2(dummy_archive, dest_path)
        return {"success": True, "engine": "mock", "path": dest_path}

    with patch.object(tool, "_download_file_to", side_effect=mock_dl):
        res = await tool.execute(
            mock_context,
            action="download_font",
            font_name="jetbrains mono nerd font",
            output_dir=target_fonts_dir,
        )

        assert res.success is True
        assert "Pengunduhan dan Pemasangan Font Selesai" in res.output
        assert "JetBrainsMono (Nerd Font)" in res.output
        assert "JetBrainsMonoNerdFont-Regular.ttf" in res.output
        assert os.path.exists(os.path.join(target_fonts_dir, "JetBrainsMonoNerdFont-Regular.ttf"))


@pytest.mark.asyncio
async def test_media_downloader_download_font_routed_from_download_action(mock_context, tmp_path):
    tool = MediaDownloaderTool()
    target_fonts_dir = str(tmp_path / ".fonts")

    dummy_archive = str(tmp_path / "FiraCode.tar.xz")
    with tarfile.open(dummy_archive, mode="w:xz") as t:
        data = b"\x00\x01\x00\x00FiraCodeNerdFont-Regular"
        ti = tarfile.TarInfo(name="FiraCodeNerdFont-Regular.ttf")
        ti.size = len(data)
        t.addfile(ti, io.BytesIO(data))

    async def mock_dl(url, dest_path, timeout, kwargs):
        import shutil
        shutil.copy2(dummy_archive, dest_path)
        return {"success": True, "engine": "mock", "path": dest_path}

    with patch.object(tool, "_download_file_to", side_effect=mock_dl):
        # User prompt passed action="download" with font_name parameter
        res = await tool.execute(
            mock_context,
            action="download",
            font_name="fira code nerd font",
            output_dir=target_fonts_dir,
        )

        assert res.success is True
        assert "FiraCode" in res.output
        assert "FiraCodeNerdFont-Regular.ttf" in res.output


@pytest.mark.asyncio
async def test_media_downloader_download_font_ssrf_blocked(mock_context):
    tool = MediaDownloaderTool()
    # Try downloading font from private RFC1918 / loopback IP
    res = await tool.execute(
        mock_context,
        action="download_font",
        url="http://192.168.1.1/font.tar.xz",
    )
    assert res.success is False
    assert "Akses ditolak" in res.error or "Privat" in res.error


# ---------------------------------------------------------------------------
# 4. MediaDownloaderTool General Archive Extraction Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_media_downloader_extract_archive(mock_context, tmp_path):
    tool = MediaDownloaderTool()
    archive_file = str(tmp_path / "bundle.zip")
    extract_target = str(tmp_path / "extracted")

    with zipfile.ZipFile(archive_file, mode="w") as z:
        z.writestr("data/config.json", b'{"key": "value"}')
        z.writestr("notes.txt", b"meeting notes")

    res = await tool.execute(
        mock_context,
        action="extract_archive",
        path=archive_file,
        output_dir=extract_target,
    )

    assert res.success is True
    assert "Ekstraksi Arsip Selesai" in res.output
    assert os.path.exists(os.path.join(extract_target, "data", "config.json"))
    assert os.path.exists(os.path.join(extract_target, "notes.txt"))


# ---------------------------------------------------------------------------
# 5. FileManagerTool Archive Extraction Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_file_manager_extract_archive(mock_context, tmp_path):
    tool = FileManagerTool()
    archive_file = str(tmp_path / "project.tar.gz")
    extract_target = str(tmp_path / "output")

    with tarfile.open(archive_file, mode="w:gz") as t:
        data = b"print('hello world')"
        ti = tarfile.TarInfo(name="main.py")
        ti.size = len(data)
        t.addfile(ti, io.BytesIO(data))

    res = await tool.execute(
        mock_context,
        action="extract_archive",
        path=archive_file,
        destination_path=extract_target,
    )

    assert res.success is True
    assert "Ekstraksi Arsip Selesai" in res.output
    assert os.path.exists(os.path.join(extract_target, "main.py"))


# ---------------------------------------------------------------------------
# 6. Tool Router Classification Tests
# ---------------------------------------------------------------------------

def test_tool_router_font_download_phrases():
    # The exact phrase user tested with
    phrase1 = "downloadkan saya jetbrains mono nerd font lalu simpan pada folder .fonts/"
    cats1 = tool_router.classify_categories(phrase1)
    tools1 = tool_router.get_tool_names(phrase1)

    assert CATEGORY_FILES in cats1
    assert CATEGORY_WEB_MEDIA in cats1
    assert "media_downloader" in tools1
    assert "file_manager" in tools1

    # Alternative Indonesian variations
    phrase2 = "unduhkan font fira code ke folder .fonts"
    tools2 = tool_router.get_tool_names(phrase2)
    assert "media_downloader" in tools2

    phrase3 = "download font hack nerd font simpan di ~/.fonts"
    tools3 = tool_router.get_tool_names(phrase3)
    assert "media_downloader" in tools3

    phrase4 = "tolong ekstrak arsip backup.zip ke direktori data"
    tools4 = tool_router.get_tool_names(phrase4)
    assert "file_manager" in tools4
    assert "media_downloader" in tools4
