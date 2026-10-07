from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest

from src.tools.base import ToolContext
from src.tools.web_search import (
    WebSearchTool,
    SmartWebExtractor,
    _clean_url,
    _strip_html_tags,
)


def _ctx() -> ToolContext:
    return ToolContext(chat_id=1, user_id=1)


SAMPLE_DDG_HTML = """
<!DOCTYPE html>
<html>
<body>
<div class="result results_links results_links_deep web-result ">
  <div class="links_main links_deep result__body">
    <h2 class="result__title">
      <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Ftermux-guide%3Futm_source%3Dtest&rut=1">
        Panduan Lengkap Termux Android 2026
      </a>
    </h2>
    <div class="result__snippet">
      Tutorial cara menggunakan Termux dari dasar hingga mahir untuk kebutuhan scripting.
    </div>
  </div>
</div>
<div class="result results_links results_links_deep web-result ">
  <div class="links_main links_deep result__body">
    <h2 class="result__title">
      <a class="result__a" href="https://github.com/test/repo">
        GitHub - test/repo: Termux Tools
      </a>
    </h2>
    <div class="result__snippet">
      Kumpulan alat otomatisasi di Termux untuk Android root dan non-root.
    </div>
  </div>
</div>
</body>
</html>
"""

SAMPLE_ARTICLE_HTML = """
<!DOCTYPE html>
<html>
<head>
  <title>Tutorial Root Android Termux</title>
  <meta name="description" content="Cara memasang dan mengelola akses root di Termux." />
  <style>.ad-banner { display: block; }</style>
  <script>console.log("tracking");</script>
</head>
<body>
  <nav><a href="/">Home</a><a href="/menu">Menu</a></nav>
  <main>
    <h1>Memasang Akses Root di Termux</h1>
    <p>Akses root memungkinkan pengguna mengontrol penuh subsistem Android.</p>
    <p>Gunakan paket tsu untuk berpindah ke pengguna superuser secara aman.</p>
    <a href="https://example.com/download">Download Installer</a>
  </main>
  <footer><p>Hak Cipta 2026</p></footer>
</body>
</html>
"""


def test_clean_url():
    raw = "//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fpath%3Futm_source%3Dpromo%26id%3D123"
    cleaned = _clean_url(raw)
    assert cleaned == "https://example.com/path?id=123"
    assert "utm_source" not in cleaned


def test_strip_html_tags():
    assert _strip_html_tags("<b>Halo</b> &amp; <i>Dunia</i>") == "Halo & Dunia"
    assert _strip_html_tags("") == ""


def test_smart_web_extractor():
    extractor = SmartWebExtractor()
    extractor.feed(SAMPLE_ARTICLE_HTML)
    title, desc, body = extractor.get_clean_text()

    assert title == "Tutorial Root Android Termux"
    assert desc == "Cara memasang dan mengelola akses root di Termux."
    assert "Memasang Akses Root di Termux" in body
    assert "Akses root memungkinkan pengguna" in body
    # Nav, script, and footer should be stripped
    assert "tracking" not in body
    assert "Hak Cipta" not in body


async def test_search_missing_query():
    tool = WebSearchTool()
    res = await tool.execute(_ctx(), action="search", query="")
    assert not res.success
    assert "query" in res.error


async def test_search_success():
    tool = WebSearchTool()

    class MockResponse:
        status_code = 200
        text = SAMPLE_DDG_HTML

    with patch("httpx.AsyncClient.post", AsyncMock(return_value=MockResponse())):
        res = await tool.execute(_ctx(), action="search", query="termux tutorial", max_results=2)

    assert res.success
    assert "Panduan Lengkap Termux Android 2026" in res.output
    assert "https://example.com/termux-guide" in res.output
    assert "GitHub - test/repo: Termux Tools" in res.output


async def test_search_empty_results():
    tool = WebSearchTool()

    class MockResponse:
        status_code = 200
        text = "<html><body>No results found</body></html>"

    with patch("httpx.AsyncClient.post", AsyncMock(return_value=MockResponse())):
        res = await tool.execute(_ctx(), action="search", query="kata kunci aneh xyz123")

    assert res.success
    assert "Tidak ditemukan hasil" in res.output


async def test_visit_missing_url():
    tool = WebSearchTool()
    res = await tool.execute(_ctx(), action="visit", url="")
    assert not res.success
    assert "url" in res.error


async def test_visit_success():
    tool = WebSearchTool()

    class MockResponse:
        status_code = 200
        text = SAMPLE_ARTICLE_HTML
        headers = {"content-type": "text/html; charset=utf-8"}

    with patch("httpx.AsyncClient.get", AsyncMock(return_value=MockResponse())):
        res = await tool.execute(_ctx(), action="visit", url="https://example.com/article")

    assert res.success
    assert "Tutorial Root Android Termux" in res.output
    assert "Memasang Akses Root di Termux" in res.output


async def test_visit_404_error():
    tool = WebSearchTool()

    class MockResponse:
        status_code = 404
        text = "Not found"
        headers = {"content-type": "text/html"}

    with patch("httpx.AsyncClient.get", AsyncMock(return_value=MockResponse())):
        res = await tool.execute(_ctx(), action="visit", url="https://example.com/404")

    assert not res.success
    assert "404" in res.error


async def test_visit_long_article_saved_as_document(tmp_path):
    tool = WebSearchTool()
    long_content = "<p>" + ("Teks artikel panjang berulang. " * 500) + "</p>"
    long_html = f"<html><head><title>Artikel Panjang</title></head><body>{long_content}</body></html>"

    class MockResponse:
        status_code = 200
        text = long_html
        headers = {"content-type": "text/html"}

    save_path = str(tmp_path / "article_test.txt")
    with patch("httpx.AsyncClient.get", AsyncMock(return_value=MockResponse())):
        res = await tool.execute(_ctx(), action="visit", url="https://example.com/long", save_to=save_path)

    assert res.success
    assert res.media_type == "document"
    assert res.media_path == save_path
    assert os.path.exists(save_path)


async def test_deep_research_flow():
    tool = WebSearchTool()

    class MockSearchResponse:
        status_code = 200
        text = SAMPLE_DDG_HTML

    class MockPageResponse:
        status_code = 200
        text = SAMPLE_ARTICLE_HTML
        headers = {"content-type": "text/html"}

    with patch("httpx.AsyncClient.post", AsyncMock(return_value=MockSearchResponse())), \
         patch("httpx.AsyncClient.get", AsyncMock(return_value=MockPageResponse())):
        res = await tool.execute(_ctx(), action="deep_research", query="termux root", max_results=2)

    assert res.success
    assert "Riset Multi-Sumber Selesai" in res.output
    assert "https://example.com/termux-guide" in res.output


async def test_extract_links():
    tool = WebSearchTool()

    class MockResponse:
        status_code = 200
        text = SAMPLE_ARTICLE_HTML
        headers = {"content-type": "text/html"}

    with patch("httpx.AsyncClient.get", AsyncMock(return_value=MockResponse())):
        res = await tool.execute(_ctx(), action="extract_links", url="https://example.com/page")

    assert res.success
    assert "https://example.com/download" in res.output
    assert "Download Installer" in res.output


async def test_unknown_action():
    tool = WebSearchTool()
    res = await tool.execute(_ctx(), action="invalid_action")
    assert not res.success
    assert "tidak dikenal" in res.error


async def test_registered_in_default_registry():
    from src.tools import create_default_registry

    reg = create_default_registry()
    assert reg.get("web_search") is not None
