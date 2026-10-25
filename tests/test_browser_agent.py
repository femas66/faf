from __future__ import annotations

import asyncio
import base64
import json
import os
import struct
import tempfile
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.tools.base import ToolContext, ToolResult
from src.tools.cdp_client import (
    CDPWebSocketClient,
    ChromiumSessionManager,
    RFC6455Frame,
    _find_browser_binary,
)
from src.tools.browser_agent import BrowserAgentTool
from src.tools import default_registry
from src.core.tool_router import ToolRouter, CATEGORY_WEB_MEDIA


# ---------------------------------------------------------------------------
# 1. RFC 6455 Frame Tests
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_rfc6455_encode_decode_text_unmasked():
    payload = b"Hello, faf-agent browser!"
    frame = RFC6455Frame.encode_frame(payload, opcode=RFC6455Frame.OP_TEXT, mask=False)

    reader = asyncio.StreamReader()
    reader.feed_data(frame)
    reader.feed_eof()

    opcode, read_payload, fin = await RFC6455Frame.read_frame(reader)
    assert opcode == RFC6455Frame.OP_TEXT
    assert read_payload == payload
    assert fin is True


@pytest.mark.asyncio
async def test_rfc6455_encode_decode_masked():
    payload = b'{"id": 1, "method": "Page.navigate", "params": {"url": "https://example.com"}}'
    frame = RFC6455Frame.encode_frame(payload, opcode=RFC6455Frame.OP_TEXT, mask=True)

    reader = asyncio.StreamReader()
    reader.feed_data(frame)
    reader.feed_eof()

    opcode, read_payload, fin = await RFC6455Frame.read_frame(reader)
    assert opcode == RFC6455Frame.OP_TEXT
    assert read_payload == payload
    assert fin is True


@pytest.mark.asyncio
async def test_rfc6455_encode_decode_medium_length():
    payload = b"A" * 1000  # length > 125, fits in 16-bit
    frame = RFC6455Frame.encode_frame(payload, opcode=RFC6455Frame.OP_BINARY, mask=True)

    reader = asyncio.StreamReader()
    reader.feed_data(frame)
    reader.feed_eof()

    opcode, read_payload, fin = await RFC6455Frame.read_frame(reader)
    assert opcode == RFC6455Frame.OP_BINARY
    assert read_payload == payload
    assert fin is True


@pytest.mark.asyncio
async def test_rfc6455_control_frames():
    # Ping & Pong
    ping_frame = RFC6455Frame.encode_frame(b"ping", opcode=RFC6455Frame.OP_PING, mask=False)
    reader = asyncio.StreamReader()
    reader.feed_data(ping_frame)
    reader.feed_eof()

    opcode, read_payload, fin = await RFC6455Frame.read_frame(reader)
    assert opcode == RFC6455Frame.OP_PING
    assert read_payload == b"ping"

    # Close
    close_frame = RFC6455Frame.encode_frame(b"", opcode=RFC6455Frame.OP_CLOSE, mask=False)
    reader2 = asyncio.StreamReader()
    reader2.feed_data(close_frame)
    reader2.feed_eof()

    opcode, read_payload, fin = await RFC6455Frame.read_frame(reader2)
    assert opcode == RFC6455Frame.OP_CLOSE


# ---------------------------------------------------------------------------
# 2. CDP WebSocket Client Integration with Mock Server
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_cdp_websocket_client_handshake_and_command():
    async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        # Read handshake
        req = await reader.readuntil(b"\r\n\r\n")
        assert b"Upgrade: websocket" in req

        # Send 101 Switching Protocols
        handshake_resp = (
            b"HTTP/1.1 101 Switching Protocols\r\n"
            b"Upgrade: websocket\r\n"
            b"Connection: Upgrade\r\n"
            b"Sec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=\r\n\r\n"
        )
        writer.write(handshake_resp)
        await writer.drain()

        # Read command frame from client
        opcode, payload, _ = await RFC6455Frame.read_frame(reader)
        cmd = json.loads(payload.decode("utf-8"))
        msg_id = cmd["id"]
        method = cmd["method"]

        # Send response frame
        resp_data = {"id": msg_id, "result": {"navigated": True, "method": method}}
        resp_frame = RFC6455Frame.encode_frame(json.dumps(resp_data).encode("utf-8"), mask=False)
        writer.write(resp_frame)
        await writer.drain()

        # Wait for close or EOF
        try:
            await RFC6455Frame.read_frame(reader)
        except Exception:
            pass
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle_client, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]

    client = CDPWebSocketClient()
    try:
        await client.connect(f"ws://127.0.0.1:{port}/devtools/page/test")
        assert client.is_connected

        result = await client.send_command("Page.navigate", {"url": "https://example.com"})
        assert result.get("navigated") is True
        assert result.get("method") == "Page.navigate"
    finally:
        await client.close()
        server.close()
        await server.wait_closed()


# ---------------------------------------------------------------------------
# 3. Chromium Session Manager Lifecycle & Idle Reaper
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_session_manager_touch_and_alive():
    manager = ChromiumSessionManager(port=9999)
    assert not manager.is_alive()
    t1 = manager.last_activity
    await asyncio.sleep(0.05)
    manager.touch()
    assert manager.last_activity >= t1


@pytest.mark.asyncio
async def test_session_manager_stop():
    manager = ChromiumSessionManager(port=9999)
    # Mock process
    proc = MagicMock()
    proc.returncode = None
    proc.terminate = MagicMock()
    proc.wait = AsyncMock(return_value=0)
    manager.process = proc
    temp_dir = tempfile.mkdtemp(prefix="faf_test_chrome_")
    manager.user_data_dir = temp_dir

    await manager.stop()
    assert manager.process is None
    assert not os.path.exists(temp_dir)


# ---------------------------------------------------------------------------
# 4. Browser Agent Tool Security & SSRF
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_browser_agent_ssrf_protection():
    tool = BrowserAgentTool()
    ctx = ToolContext(chat_id=123, user_id=123)

    with patch("src.tools.browser_agent._find_browser_binary", return_value="/bin/chromium"):
        # Localhost rejection
        res = await tool.execute(ctx, action="open", url="http://127.0.0.1:8080/admin")
        assert res.success is False
        assert "tidak aman" in res.error.lower()

        # RFC1918 Private IP rejection
        res = await tool.execute(ctx, action="open", url="http://192.168.1.1/router")
        assert res.success is False
        assert "tidak aman" in res.error.lower()

        # Cloud metadata IP rejection
        res = await tool.execute(ctx, action="open", url="http://169.254.169.254/latest/meta-data/")
        assert res.success is False
        assert "tidak aman" in res.error.lower()

        # File scheme rejection
        res = await tool.execute(ctx, action="open", url="file:///etc/passwd")
        assert res.success is False
        assert "tidak aman" in res.error.lower()


@pytest.mark.asyncio
async def test_browser_agent_missing_binary():
    tool = BrowserAgentTool()
    ctx = ToolContext(chat_id=123, user_id=123)

    with patch("src.tools.browser_agent._find_browser_binary", return_value=None):
        res = await tool.execute(ctx, action="open", url="https://example.com")
        assert res.success is False
        assert "Chromium headless belum terpasang" in res.error


# ---------------------------------------------------------------------------
# 5. Browser Agent Actions with Mock CDP Client
# ---------------------------------------------------------------------------
class FakeCDPClient:
    def __init__(self):
        self.commands = []
        self.eval_results = {}

    async def send_command(self, method: str, params: dict[str, Any] | None = None, timeout: float = 30.0):
        self.commands.append((method, params or {}))
        if method == "Page.navigate":
            return {"frameId": "123"}
        elif method == "Runtime.evaluate":
            expr = (params or {}).get("expression", "")
            # DOM indexing response
            if "querySelectorAll" in expr and "data-faf-id" in expr:
                return {
                    "result": {
                        "value": {
                            "title": "Portal Berita FAF",
                            "url": "https://news.example.com",
                            "innerText": "Berita utama hari ini...",
                            "elements": [
                                {"id": 1, "tag": "input", "description": "input[search] placeholder=\"Cari berita...\""},
                                {"id": 2, "tag": "button", "description": "button \"Search\""},
                                {"id": 3, "tag": "a", "description": "a \"Teknologi\" -> /tech"},
                            ],
                        }
                    }
                }
            elif "click()" in expr:
                return {"result": {"value": {"success": True}}}
            elif "value =" in expr:
                return {"result": {"value": {"success": True}}}
            elif "scrollTo" in expr or "scrollBy" in expr:
                return {"result": {"value": None}}
            elif "links.map" in expr:
                return {
                    "result": {
                        "value": [
                            {"text": "Artikel 1", "href": "https://example.com/1"},
                            {"text": "Artikel 2", "href": "https://example.com/2"},
                        ]
                    }
                }
            elif "tables.map" in expr:
                return {
                    "result": {
                        "value": [
                            [["Header 1", "Header 2"], ["Data 1", "Data 2"]]
                        ]
                    }
                }
            elif "document.body.innerText" in expr:
                return {"result": {"value": "Teks lengkap halaman contoh."}}
            return {"result": {"value": "Evaluated"}}
        elif method == "Page.captureScreenshot":
            # 1x1 transparent png in base64
            dummy_png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
            return {"data": dummy_png}
        elif method == "Page.printToPDF":
            dummy_pdf = base64.b64encode(b"%PDF-1.4 mock content").decode("ascii")
            return {"data": dummy_pdf}
        return {}


class FakeSessionManager:
    def __init__(self, cdp_client):
        self.cdp_client = cdp_client
        self.stopped = False

    async def get_cdp_client(self):
        return self.cdp_client

    async def stop(self):
        self.stopped = True


@pytest.mark.asyncio
async def test_browser_agent_action_open():
    fake_cdp = FakeCDPClient()
    fake_mgr = FakeSessionManager(fake_cdp)
    tool = BrowserAgentTool(session_manager=fake_mgr)
    ctx = ToolContext(chat_id=123, user_id=123)

    with patch("src.tools.browser_agent._find_browser_binary", return_value="/bin/chromium"):
        res = await tool.execute(ctx, action="open", url="https://news.example.com", wait_seconds=1)
        assert res.success is True
        assert "Portal Berita FAF" in res.output
        assert "[1] input[search]" in res.output
        assert "[2] button \"Search\"" in res.output


@pytest.mark.asyncio
async def test_browser_agent_action_click():
    fake_cdp = FakeCDPClient()
    fake_mgr = FakeSessionManager(fake_cdp)
    tool = BrowserAgentTool(session_manager=fake_mgr)
    ctx = ToolContext(chat_id=123, user_id=123)

    with patch("src.tools.browser_agent._find_browser_binary", return_value="/bin/chromium"):
        res = await tool.execute(ctx, action="click", element_id=2, wait_seconds=1)
        assert res.success is True
        assert "Berhasil mengklik elemen [2]" in res.output


@pytest.mark.asyncio
async def test_browser_agent_action_type():
    fake_cdp = FakeCDPClient()
    fake_mgr = FakeSessionManager(fake_cdp)
    tool = BrowserAgentTool(session_manager=fake_mgr)
    ctx = ToolContext(chat_id=123, user_id=123)

    with patch("src.tools.browser_agent._find_browser_binary", return_value="/bin/chromium"):
        res = await tool.execute(ctx, action="type", element_id=1, text="agent AI", submit=True, wait_seconds=1)
        assert res.success is True
        assert "Berhasil mengetikkan 'agent AI' ke dalam elemen [1]" in res.output


@pytest.mark.asyncio
async def test_browser_agent_action_scroll():
    fake_cdp = FakeCDPClient()
    fake_mgr = FakeSessionManager(fake_cdp)
    tool = BrowserAgentTool(session_manager=fake_mgr)
    ctx = ToolContext(chat_id=123, user_id=123)

    with patch("src.tools.browser_agent._find_browser_binary", return_value="/bin/chromium"):
        res = await tool.execute(ctx, action="scroll", direction="down", amount_px=500)
        assert res.success is True
        assert "Halaman digulir (down, 500px)" in res.output


@pytest.mark.asyncio
async def test_browser_agent_action_extract_modes():
    fake_cdp = FakeCDPClient()
    fake_mgr = FakeSessionManager(fake_cdp)
    tool = BrowserAgentTool(session_manager=fake_mgr)
    ctx = ToolContext(chat_id=123, user_id=123)

    with patch("src.tools.browser_agent._find_browser_binary", return_value="/bin/chromium"):
        # Extract text
        res_text = await tool.execute(ctx, action="extract", mode="text")
        assert res_text.success is True
        assert "Teks lengkap halaman contoh" in res_text.output

        # Extract links
        res_links = await tool.execute(ctx, action="extract", mode="links")
        assert res_links.success is True
        assert "Artikel 1 -> https://example.com/1" in res_links.output

        # Extract tables
        res_tables = await tool.execute(ctx, action="extract", mode="tables")
        assert res_tables.success is True
        assert "Header 1 | Header 2" in res_tables.output


@pytest.mark.asyncio
async def test_browser_agent_action_screenshot():
    fake_cdp = FakeCDPClient()
    fake_mgr = FakeSessionManager(fake_cdp)
    tool = BrowserAgentTool(session_manager=fake_mgr)
    ctx = ToolContext(chat_id=123, user_id=123)

    with patch("src.tools.browser_agent._find_browser_binary", return_value="/bin/chromium"):
        res = await tool.execute(ctx, action="screenshot", annotate=True)
        assert res.success is True
        assert res.media_path is not None
        assert os.path.exists(res.media_path)
        assert res.media_type == "photo"
        os.remove(res.media_path)


@pytest.mark.asyncio
async def test_browser_agent_action_save_pdf():
    fake_cdp = FakeCDPClient()
    fake_mgr = FakeSessionManager(fake_cdp)
    tool = BrowserAgentTool(session_manager=fake_mgr)
    ctx = ToolContext(chat_id=123, user_id=123)

    with patch("src.tools.browser_agent._find_browser_binary", return_value="/bin/chromium"):
        res = await tool.execute(ctx, action="save_pdf", filename="test_output.pdf")
        assert res.success is True
        assert res.media_path is not None
        assert res.media_path.endswith("test_output.pdf")
        assert os.path.exists(res.media_path)
        assert res.media_type == "document"
        os.remove(res.media_path)


@pytest.mark.asyncio
async def test_browser_agent_action_close():
    fake_cdp = FakeCDPClient()
    fake_mgr = FakeSessionManager(fake_cdp)
    tool = BrowserAgentTool(session_manager=fake_mgr)
    ctx = ToolContext(chat_id=123, user_id=123)

    res = await tool.execute(ctx, action="close")
    assert res.success is True
    assert fake_mgr.stopped is True


# ---------------------------------------------------------------------------
# 6. Web Search SPA Fallback Integration
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_web_search_spa_fallback():
    from src.tools.web_search import WebSearchTool

    ws_tool = WebSearchTool()
    ctx = ToolContext(chat_id=123, user_id=123)

    # When normal HTTP returns empty body (e.g. CSR root tag)
    mock_empty_content = ({"title": "My React App", "description": "", "body": ""}, None)
    mock_browser_content = ({"title": "My React App", "description": "", "body": "Ini adalah teks render dari React SPA yang berhasil dibaca oleh headless browser."}, None)

    with patch.object(ws_tool, "_fetch_page_content", AsyncMock(return_value=mock_empty_content)), \
         patch("src.tools.cdp_client._find_browser_binary", return_value="/bin/chromium"), \
         patch.object(ws_tool, "_fetch_via_headless_browser", AsyncMock(return_value=mock_browser_content)):

        res = await ws_tool.execute(ctx, action="visit", url="https://spa.example.com")
        assert res.success is True
        assert "Ini adalah teks render dari React SPA" in res.output


# ---------------------------------------------------------------------------
# 7. Tool Registry & Router Registration
# ---------------------------------------------------------------------------
def test_tool_registry_and_router_integration():
    # 1. Registered in default registry
    tool = default_registry.get("browser_agent")
    assert tool is not None
    assert isinstance(tool, BrowserAgentTool)

    # 2. Routed by tool router
    router = ToolRouter()
    schema = router.get_tools_for_message("tolong buka web https://news.ycombinator.com dengan browser agent")
    tool_names = [t["function"]["name"] for t in schema]
    assert "browser_agent" in tool_names
