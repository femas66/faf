"""Chrome DevTools Protocol (CDP) client and Chromium session manager.

100% Pure Python & Zero Native Compilation.
Uses standard library asyncio + RFC 6455 WebSocket framing to communicate with
headless Chromium on localhost:9222.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import shlex
import shutil
import struct
import tempfile
import time
import urllib.parse
from typing import Any, Callable

import httpx

from src.config import get_settings
from src.tools.web_search import _check_url_safety

logger = logging.getLogger("faf_agent.tools.cdp_client")

# Binary search paths
BROWSER_CANDIDATES = [
    "chromium",
    "chromium-browser",
    "google-chrome-stable",
    "google-chrome",
    "chrome",
]

TERMUX_BROWSER_PATHS = [
    "/data/data/com.termux/files/usr/bin/chromium",
    "/data/data/com.termux/files/usr/bin/chromium-browser",
    "/data/data/com.termux/files/usr/bin/chrome",
]


def _find_browser_binary() -> str | None:
    """Find installed Chromium or Chrome binary path in system or Termux."""
    for candidate in BROWSER_CANDIDATES:
        p = shutil.which(candidate)
        if p:
            return p

    for tp in TERMUX_BROWSER_PATHS:
        if os.path.exists(tp) and os.access(tp, os.X_OK):
            return tp

    return None


# ---------------------------------------------------------------------------
# RFC 6455 Pure Python WebSocket Client
# ---------------------------------------------------------------------------
class RFC6455Frame:
    """Helper to encode and decode WebSocket frames according to RFC 6455."""

    OP_TEXT = 0x1
    OP_BINARY = 0x2
    OP_CLOSE = 0x8
    OP_PING = 0x9
    OP_PONG = 0xA

    @staticmethod
    def encode_frame(payload: bytes, opcode: int = OP_TEXT, mask: bool = True) -> bytes:
        """Encode payload into a masked (or unmasked) client frame."""
        b0 = 0x80 | (opcode & 0x0F)
        length = len(payload)
        mask_bit = 0x80 if mask else 0x00

        if length <= 125:
            header = bytes([b0, mask_bit | length])
        elif length <= 65535:
            header = bytes([b0, mask_bit | 126]) + struct.pack(">H", length)
        else:
            header = bytes([b0, mask_bit | 127]) + struct.pack(">Q", length)

        if mask:
            mask_key = os.urandom(4)
            masked = bytearray(length)
            for i in range(length):
                masked[i] = payload[i] ^ mask_key[i % 4]
            return header + mask_key + bytes(masked)
        return header + payload

    @staticmethod
    async def read_frame(reader: asyncio.StreamReader) -> tuple[int, bytes, bool]:
        """Read a single frame from stream. Returns (opcode, payload, is_final)."""
        b01 = await reader.readexactly(2)
        b0, b1 = b01[0], b01[1]

        fin = bool(b0 & 0x80)
        opcode = b0 & 0x0F
        is_masked = bool(b1 & 0x80)
        length = b1 & 0x7F

        if length == 126:
            length = struct.unpack(">H", await reader.readexactly(2))[0]
        elif length == 127:
            length = struct.unpack(">Q", await reader.readexactly(8))[0]

        if is_masked:
            mask_key = await reader.readexactly(4)
            raw = await reader.readexactly(length)
            payload = bytes(raw[i] ^ mask_key[i % 4] for i in range(length))
        else:
            payload = await reader.readexactly(length)

        return opcode, payload, fin


class CDPWebSocketClient:
    """Async Pure-Python WebSocket client for Chrome DevTools Protocol."""

    def __init__(self) -> None:
        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None
        self._next_id_val = 1
        self._pending_requests: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._read_task: asyncio.Task[None] | None = None
        self._closed = False
        self._close_event = asyncio.Event()

    @property
    def is_connected(self) -> bool:
        return not self._closed and self.writer is not None and not self.writer.is_closing()

    async def connect(self, ws_url: str, timeout: float = 10.0) -> None:
        """Establish WebSocket connection with CDP server via RFC 6455 handshake."""
        parsed = urllib.parse.urlparse(ws_url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 9222
        path = parsed.path or "/"

        self.reader, self.writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )

        nonce = base64.b64encode(os.urandom(16)).decode("ascii")
        handshake = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {nonce}\r\n"
            f"Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.writer.write(handshake.encode("utf-8"))
        await self.writer.drain()

        # Read handshake response
        response = await asyncio.wait_for(self.reader.readuntil(b"\r\n\r\n"), timeout=timeout)
        resp_lines = response.decode("utf-8", errors="replace").split("\r\n")
        if not resp_lines or "101" not in resp_lines[0]:
            raise ConnectionError(f"WebSocket handshake failed: {resp_lines[0] if resp_lines else 'empty'}")

        self._closed = False
        self._close_event.clear()
        self._read_task = asyncio.create_task(self._reader_loop())

    async def _reader_loop(self) -> None:
        """Background loop reading frames and resolving command responses."""
        frag_buffer = bytearray()
        frag_opcode = 0

        try:
            while not self._closed and self.reader is not None:
                try:
                    opcode, payload, is_final = await RFC6455Frame.read_frame(self.reader)
                except (asyncio.IncompleteReadError, ConnectionResetError):
                    break

                if opcode == RFC6455Frame.OP_CLOSE:
                    # Echo close frame and break
                    await self._send_raw_frame(RFC6455Frame.encode_frame(b"", RFC6455Frame.OP_CLOSE))
                    break
                elif opcode == RFC6455Frame.OP_PING:
                    # Send pong
                    await self._send_raw_frame(RFC6455Frame.encode_frame(payload, RFC6455Frame.OP_PONG))
                    continue
                elif opcode == RFC6455Frame.OP_PONG:
                    continue

                # Data frame handling (text or continuation)
                if opcode != 0:
                    frag_opcode = opcode
                    frag_buffer.clear()
                frag_buffer.extend(payload)

                if is_final and frag_opcode == RFC6455Frame.OP_TEXT:
                    msg_text = bytes(frag_buffer).decode("utf-8", errors="replace")
                    try:
                        msg_data = json.loads(msg_text)
                    except Exception:
                        continue

                    msg_id = msg_data.get("id")
                    if msg_id is not None and msg_id in self._pending_requests:
                        fut = self._pending_requests.pop(msg_id)
                        if not fut.done():
                            fut.set_result(msg_data)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug(f"CDPWebSocketClient read loop exited with: {e}")
        finally:
            self._closed = True
            self._close_event.set()
            for fut in self._pending_requests.values():
                if not fut.done():
                    fut.set_exception(ConnectionError("CDP connection closed"))
            self._pending_requests.clear()

    async def _send_raw_frame(self, frame_bytes: bytes) -> None:
        if self.writer and not self.writer.is_closing():
            self.writer.write(frame_bytes)
            await self.writer.drain()

    async def send_command(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Send a CDP method call and wait for its result."""
        if self._closed or not self.writer:
            raise ConnectionError("CDP WebSocket is not connected.")

        msg_id = self._next_id_val
        self._next_id_val += 1

        payload_obj = {
            "id": msg_id,
            "method": method,
            "params": params or {},
        }
        payload_bytes = json.dumps(payload_obj).encode("utf-8")
        frame = RFC6455Frame.encode_frame(payload_bytes, RFC6455Frame.OP_TEXT, mask=True)

        fut = asyncio.get_running_loop().create_future()
        self._pending_requests[msg_id] = fut

        await self._send_raw_frame(frame)

        resp = await asyncio.wait_for(fut, timeout=timeout)
        if "error" in resp:
            err = resp["error"]
            err_msg = err.get("message") or str(err)
            raise RuntimeError(f"CDP Command '{method}' failed: {err_msg}")

        return resp.get("result", {})

    async def close(self) -> None:
        """Gracefully close the WebSocket client."""
        if self._closed:
            return
        self._closed = True
        try:
            if self.writer and not self.writer.is_closing():
                close_frame = RFC6455Frame.encode_frame(b"", RFC6455Frame.OP_CLOSE, mask=True)
                self.writer.write(close_frame)
                await self.writer.drain()
                self.writer.close()
                await self.writer.wait_closed()
        except Exception:
            pass
        if self._read_task and not self._read_task.done():
            self._read_task.cancel()
        self._close_event.set()


# ---------------------------------------------------------------------------
# Chromium Session Manager (Warm Process + Auto-Idle Reaper)
# ---------------------------------------------------------------------------
class ChromiumSessionManager:
    """Manages background headless Chromium daemon, CDP connection, and idle timeout."""

    def __init__(self, port: int = 9222) -> None:
        self.port = port
        self.process: asyncio.subprocess.Process | None = None
        self.user_data_dir: str | None = None
        self.cdp_client: CDPWebSocketClient | None = None
        self.last_activity: float = time.time()
        self._lock = asyncio.Lock()
        self._reaper_task: asyncio.Task[None] | None = None
        self._shutting_down = False

    def is_alive(self) -> bool:
        """Check whether the Chromium subprocess is running."""
        return self.process is not None and self.process.returncode is None

    def touch(self) -> None:
        """Reset the idle activity timestamp."""
        self.last_activity = time.time()

    async def _ensure_reaper(self) -> None:
        if self._reaper_task is None or self._reaper_task.done():
            self._reaper_task = asyncio.create_task(self._idle_reaper_loop())

    async def _idle_reaper_loop(self) -> None:
        """Periodically checks inactivity and terminates browser when idle."""
        while not self._shutting_down:
            try:
                await asyncio.sleep(10)
                timeout = get_settings().browser_idle_timeout
                if self.is_alive() and (time.time() - self.last_activity) >= timeout:
                    logger.info("Chromium idle timeout (%ds) reached. Stopping browser process to save RAM.", timeout)
                    await self.stop()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Idle reaper loop error: {e}")

    async def get_cdp_client(self) -> CDPWebSocketClient:
        """Get or spawn warm Chromium process and return active CDP client."""
        async with self._lock:
            self.touch()
            await self._ensure_reaper()

            if self.is_alive() and self.cdp_client and self.cdp_client.is_connected:
                return self.cdp_client

            # Clean any stale client
            if self.cdp_client:
                await self.cdp_client.close()
                self.cdp_client = None

            # Spawn browser if not running
            if not self.is_alive():
                await self._spawn_chromium()

            # Connect CDP to page target
            self.cdp_client = await self._connect_to_tab()
            return self.cdp_client

    async def _spawn_chromium(self) -> None:
        """Spawn headless Chromium with memory-optimized & security flags."""
        browser_bin = _find_browser_binary()
        if not browser_bin:
            raise FileNotFoundError(
                "Browser Chromium tidak ditemukan di Termux. "
                "Silakan install dengan: pkg install x11-repo && pkg install chromium"
            )

        self.user_data_dir = tempfile.mkdtemp(prefix="faf_chrome_")

        # Security host resolver rules: block private IPs and localhost resolution inside Chromium
        host_rules = (
            "MAP localhost 0.0.0.0, MAP 127.* 0.0.0.0, MAP 10.* 0.0.0.0, "
            "MAP 172.16.* 0.0.0.0, MAP 192.168.* 0.0.0.0, MAP 169.254.* 0.0.0.0"
        )

        cmd_args = [
            browser_bin,
            "--headless=new",
            f"--remote-debugging-port={self.port}",
            "--remote-debugging-address=127.0.0.1",
            "--no-sandbox",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--disable-software-rasterizer",
            "--hide-scrollbars",
            "--disable-extensions",
            "--disable-background-networking",
            "--disable-sync",
            "--disable-translate",
            "--mute-audio",
            "--no-first-run",
            f"--user-data-dir={self.user_data_dir}",
            f'--host-resolver-rules="{host_rules}"',
            "about:blank",
        ]

        logger.info(f"Spawning headless Chromium on 127.0.0.1:{self.port}...")
        self.process = await asyncio.create_subprocess_exec(
            *cmd_args,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )

        # Wait for CDP endpoint to become ready
        ready = False
        start_wait = time.time()
        async with httpx.AsyncClient(timeout=1.0) as http:
            while time.time() - start_wait < 10.0:
                if not self.is_alive():
                    break
                try:
                    res = await http.get(f"http://127.0.0.1:{self.port}/json/version")
                    if res.status_code == 200:
                        ready = True
                        break
                except Exception:
                    pass
                await asyncio.sleep(0.3)

        if not ready:
            await self.stop()
            raise RuntimeError("Chromium remote debugging port gagal merespons setelah 10 detik.")

    async def _connect_to_tab(self) -> CDPWebSocketClient:
        """Find active page tab or create new one, then connect CDP WebSocket."""
        async with httpx.AsyncClient(timeout=3.0) as http:
            res = await http.get(f"http://127.0.0.1:{self.port}/json/list")
            tabs = res.json() if res.status_code == 200 else []
            ws_url = None
            for tab in tabs:
                if tab.get("type") == "page" and tab.get("webSocketDebuggerUrl"):
                    ws_url = tab["webSocketDebuggerUrl"]
                    break

            if not ws_url:
                res_new = await http.put(f"http://127.0.0.1:{self.port}/json/new")
                if res_new.status_code == 200:
                    ws_url = res_new.json().get("webSocketDebuggerUrl")

        if not ws_url:
            raise ConnectionError("Gagal menemukan target tab aktif di Chromium.")

        client = CDPWebSocketClient()
        await client.connect(ws_url)

        # Enable essential domains and prevent unauthorized downloads
        await client.send_command("Page.enable")
        await client.send_command("DOM.enable")
        await client.send_command("Runtime.enable")
        await client.send_command("Page.setDownloadBehavior", {"behavior": "deny"})

        return client

    async def stop(self) -> None:
        """Stop browser process and clean up temporary directory."""
        if self.cdp_client:
            try:
                await self.cdp_client.close()
            except Exception:
                pass
            self.cdp_client = None

        if self.process and self.process.returncode is None:
            try:
                self.process.terminate()
                try:
                    await asyncio.wait_for(self.process.wait(), timeout=3.0)
                except asyncio.TimeoutError:
                    self.process.kill()
                    await self.process.wait()
            except Exception as e:
                logger.debug(f"Error terminating Chromium process: {e}")
            self.process = None

        if self.user_data_dir and os.path.exists(self.user_data_dir):
            try:
                shutil.rmtree(self.user_data_dir, ignore_errors=True)
            except Exception:
                pass
            self.user_data_dir = None


# Global singleton instance
browser_session_manager = ChromiumSessionManager()
