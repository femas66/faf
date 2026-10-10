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
    _BOT_DETECTION_TITLE_PATTERNS,
    _check_url_safety,
    _unwrap_bing_url,
    _normalize_search_query,
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


def test_bot_detection_title_patterns_constant():
    expected = (
        "access denied", "access to this page has been denied", "blocked", "bot detected", "verification required",
        "please verify", "are you a robot", "captcha", "cloudflare", "ddos protection", "checking your browser",
        "just a moment", "attention required",
    )
    assert _BOT_DETECTION_TITLE_PATTERNS == expected


def test_check_url_safety_valid():
    safe, msg, info = _check_url_safety("https://id.wikipedia.org/wiki/Indonesia")
    assert safe is True
    assert "aman" in msg.lower()


def test_check_url_safety_schemes():
    for bad_url in [
        "file:///etc/passwd",
        "data:text/html,<h1>hacked</h1>",
        "gopher://127.0.0.1:70",
        "javascript:alert(1)",
        "ftp://example.com/file",
    ]:
        safe, msg, info = _check_url_safety(bad_url)
        assert safe is False
        assert "tidak aman" in msg.lower()


def test_check_url_safety_ssrf():
    for ssrf_url in [
        "http://localhost:8080/admin",
        "http://127.0.0.1:3000",
        "http://0.0.0.0:80",
        "http://10.0.0.1/dashboard",
        "http://192.168.1.1/router",
        "http://172.16.0.5/internal",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]:8080",
    ]:
        safe, msg, info = _check_url_safety(ssrf_url)
        assert safe is False
        assert "tidak aman" in msg.lower()


def test_check_url_safety_ports():
    for dangerous_port_url in [
        "http://example.com:22/secret",
        "http://example.com:3306/db",
        "http://example.com:6379/data",
        "http://example.com:5432/query",
    ]:
        safe, msg, info = _check_url_safety(dangerous_port_url)
        assert safe is False
        assert "tidak aman" in msg.lower()


def test_check_url_safety_dangerous_extensions():
    for bad_ext in [
        "https://example.com/download.exe",
        "https://example.com/payload.sh",
        "https://example.com/app.apk",
    ]:
        safe, msg, info = _check_url_safety(bad_ext)
        assert safe is False
        assert "tidak aman" in msg.lower()


def test_unwrap_bing_url():
    # URL encoded base64 in Bing click tracking
    # aHR0cHM6Ly9leGFtcGxlLmNvbS9hcnRpY2xl == https://example.com/article
    bing_link = "https://www.bing.com/ck/a?!&&p=123&u=a1aHR0cHM6Ly9leGFtcGxlLmNvbS9hcnRpY2xl&ntb=1"
    unwrapped = _unwrap_bing_url(bing_link)
    assert unwrapped == "https://example.com/article"

    direct_link = "https://example.com/page"
    assert _unwrap_bing_url(direct_link) == direct_link


def test_normalize_search_query():
    q = "siapa pemenang indonesia vs thailand kemarin?"
    norm = _normalize_search_query(q)
    assert "siapa" not in norm.lower()
    assert "?" not in norm
    assert "indonesia" in norm
    assert "thailand" in norm


async def test_action_check_safety_tool():
    tool = WebSearchTool()
    # Safe URL
    res_safe = await tool.execute(_ctx(), action="check_safety", url="https://example.com")
    assert res_safe.success
    assert "AMAN" in res_safe.output

    # Unsafe URL
    res_unsafe = await tool.execute(_ctx(), action="check_safety", url="http://127.0.0.1:8080")
    assert not res_unsafe.success
    assert "tidak aman" in res_unsafe.error.lower()


async def test_visit_blocks_unsafe_url():
    tool = WebSearchTool()
    res = await tool.execute(_ctx(), action="visit", url="http://192.168.1.1/router")
    assert not res.success
    assert "tidak aman" in res.error.lower()


async def test_visit_detects_bot_challenge():
    tool = WebSearchTool()
    bot_html = """
    <!DOCTYPE html>
    <html>
    <head><title>Just a moment... | Cloudflare</title></head>
    <body><p>Please wait while we verify you are not a robot.</p></body>
    </html>
    """

    class MockResponse:
        status_code = 403
        text = bot_html
        headers = {"content-type": "text/html"}

    with patch("httpx.AsyncClient.get", AsyncMock(return_value=MockResponse())):
        res = await tool.execute(_ctx(), action="visit", url="https://example.com/protected")

    assert not res.success
    assert "bot" in res.error.lower() or "cloudflare" in res.error.lower()


async def test_inspect_action():
    tool = WebSearchTool()
    sample_html = """
    <!DOCTYPE html>
    <html>
    <head>
      <title>Halaman Tes</title>
      <meta name="description" content="Deskripsi Halaman" />
      <meta property="og:title" content="OpenGraph Title" />
    </head>
    <body><h1>Tes</h1></body>
    </html>
    """

    class MockResponse:
        status_code = 200
        text = sample_html
        headers = {
            "content-type": "text/html; charset=utf-8",
            "server": "nginx",
            "strict-transport-security": "max-age=31536000",
            "x-frame-options": "DENY",
        }

    with patch("httpx.AsyncClient.get", AsyncMock(return_value=MockResponse())):
        res = await tool.execute(_ctx(), action="inspect", url="https://example.com")

    assert res.success
    assert "200" in res.output
    assert "Halaman Tes" in res.output
    assert "Keamanan Header" in res.output

