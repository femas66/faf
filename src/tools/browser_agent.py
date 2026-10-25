"""Interactive Headless Browser Agent via Chrome DevTools Protocol (CDP).

Supports JavaScript/SPA rendering, DOM element indexing [1..N], clicking,
form typing, scrolling, structured data extraction, annotated screenshots, and PDF export.
100% Pure Python & Zero Native Compilation.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import shlex
import tempfile
import time
import urllib.parse
from typing import Any

from src.config import get_settings
from src.tools.base import BaseTool, ToolContext, ToolResult
from src.tools.cdp_client import (
    CDPWebSocketClient,
    _find_browser_binary,
    browser_session_manager,
)
from src.tools.web_search import _check_url_safety

logger = logging.getLogger("faf_agent.tools.browser_agent")

# Viewport presets
VIEWPORT_PRESETS = {
    "desktop": {
        "width": 1920,
        "height": 1080,
        "device_scale_factor": 1,
        "mobile": False,
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
    },
    "mobile": {
        "width": 412,
        "height": 915,
        "device_scale_factor": 2.6,
        "mobile": True,
        "user_agent": (
            "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36"
        ),
    },
}

# JavaScript to scan and number visible interactive elements [1..N]
DOM_INDEXING_SCRIPT = """
(() => {
    const isVisible = (elem) => {
        if (!elem) return false;
        const style = window.getComputedStyle(elem);
        if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
        const rect = elem.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0 && rect.bottom >= 0 && rect.top <= (window.innerHeight || document.documentElement.clientHeight);
    };

    // Remove existing attributes
    document.querySelectorAll('[data-faf-id]').forEach(el => el.removeAttribute('data-faf-id'));

    const selectors = 'a[href], button, input, textarea, select, [role="button"], [role="link"], [onclick]';
    const elements = Array.from(document.querySelectorAll(selectors));
    const items = [];
    let idx = 1;

    for (const el of elements) {
        if (!isVisible(el)) continue;
        el.setAttribute('data-faf-id', String(idx));

        const tag = el.tagName.toLowerCase();
        let desc = '';
        if (tag === 'input' || tag === 'textarea') {
            const type = el.getAttribute('type') || 'text';
            const placeholder = el.getAttribute('placeholder') || '';
            const val = el.value || '';
            const label = el.labels && el.labels[0] ? el.labels[0].innerText.trim() : '';
            desc = `${tag}[${type}]` + (placeholder ? ` placeholder="${placeholder}"` : '') + (val ? ` value="${val}"` : '') + (label ? ` label="${label}"` : '');
        } else if (tag === 'button' || el.getAttribute('role') === 'button') {
            const txt = (el.innerText || el.getAttribute('aria-label') || el.getAttribute('title') || '').trim().replace(/\\s+/g, ' ');
            desc = `button "${txt.slice(0, 50)}"`;
        } else if (tag === 'a') {
            const txt = (el.innerText || el.getAttribute('aria-label') || '').trim().replace(/\\s+/g, ' ');
            const href = el.getAttribute('href') || '';
            desc = `a "${txt.slice(0, 50)}"` + (href ? ` -> ${href.slice(0, 60)}` : '');
        } else if (tag === 'select') {
            const selected = el.options && el.selectedIndex >= 0 ? el.options[el.selectedIndex].text : '';
            desc = `select "${selected}"`;
        } else {
            const txt = (el.innerText || '').trim().replace(/\\s+/g, ' ');
            desc = `${tag} "${txt.slice(0, 50)}"`;
        }

        items.push({
            id: idx,
            tag: tag,
            description: desc
        });
        idx++;
        if (idx > 40) break;
    }

    return {
        title: document.title || 'Tanpa Judul',
        url: window.location.href,
        elements: items,
        innerText: document.body ? document.body.innerText.slice(0, 2500) : ''
    };
})()
"""

# JavaScript to draw temporary visual badges before taking annotated screenshot
DRAW_BADGES_SCRIPT = """
(() => {
    document.querySelectorAll('.faf-badge-overlay').forEach(b => b.remove());
    const badges = [];
    document.querySelectorAll('[data-faf-id]').forEach(el => {
        const rect = el.getBoundingClientRect();
        if (rect.width > 0 && rect.height > 0) {
            const badge = document.createElement('div');
            badge.className = 'faf-badge-overlay';
            badge.innerText = el.getAttribute('data-faf-id');
            badge.style.position = 'fixed';
            badge.style.left = (Math.max(0, rect.left)) + 'px';
            badge.style.top = (Math.max(0, rect.top)) + 'px';
            badge.style.backgroundColor = '#d32f2f';
            badge.style.color = '#ffffff';
            badge.style.fontSize = '12px';
            badge.style.fontWeight = 'bold';
            badge.style.padding = '1px 5px';
            badge.style.borderRadius = '4px';
            badge.style.boxShadow = '0 1px 3px rgba(0,0,0,0.5)';
            badge.style.border = '1px solid #ffffff';
            badge.style.zIndex = '2147483647';
            badge.style.pointerEvents = 'none';
            document.body.appendChild(badge);
            badges.push(badge);
        }
    });
    return badges.length;
})()
"""

REMOVE_BADGES_SCRIPT = """
(() => {
    document.querySelectorAll('.faf-badge-overlay').forEach(b => b.remove());
})()
"""


class BrowserAgentTool(BaseTool):
    """Interactive Headless Browser Agent via Chrome DevTools Protocol (CDP)."""

    name = "browser_agent"
    description = (
        "Interactive Browser Agent untuk menjelajahi situs web modern (SPA/React/Vue), "
        "mengklik elemen tombol/link bernomor [1..N], mengetik form, scroll, mengekstrak data teks/link/tabel, "
        "mengambil tangkapan layar (opsional beranotasi), serta mengekspor halaman ke berkas PDF. "
        "Gunakan tool ini ketika web_search tidak bisa membaca JavaScript atau saat perlu berinteraksi multi-langkah."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "open",
                    "click",
                    "type",
                    "scroll",
                    "extract",
                    "screenshot",
                    "save_pdf",
                    "back",
                    "close",
                ],
                "description": "Aksi browser yang ingin dilakukan.",
            },
            "url": {
                "type": "string",
                "description": "Alamat URL website yang ingin dibuka (untuk action 'open').",
            },
            "element_id": {
                "type": "integer",
                "description": "Nomor elemen interaktif [1..N] dari halaman saat ini (untuk 'click' atau 'type').",
            },
            "selector": {
                "type": "string",
                "description": "Alternatif CSS selector jika tidak menggunakan nomor element_id.",
            },
            "text": {
                "type": "string",
                "description": "Teks yang ingin diketik ke dalam input (untuk action 'type').",
            },
            "submit": {
                "type": "boolean",
                "description": "Tekan Enter / submit form setelah mengetik (default: True).",
                "default": True,
            },
            "direction": {
                "type": "string",
                "enum": ["down", "up", "top", "bottom"],
                "description": "Arah scroll (default: down).",
                "default": "down",
            },
            "amount_px": {
                "type": "integer",
                "description": "Jarak scroll dalam piksel (default: 600).",
                "default": 600,
            },
            "mode": {
                "type": "string",
                "enum": ["text", "links", "tables", "selector"],
                "description": "Mode ekstraksi untuk action 'extract' (default: text).",
                "default": "text",
            },
            "wait_seconds": {
                "type": "integer",
                "description": "Waktu tunggu rendering ekstra dalam detik (default: 2, maks: 10).",
                "default": 2,
            },
            "screenshot": {
                "type": "boolean",
                "description": "Ambil tangkapan layar foto dan kirim ke Telegram setelah aksi ini (default: False).",
                "default": False,
            },
            "annotate": {
                "type": "boolean",
                "description": "Tampilkan nomor elemen [1..N] langsung di atas gambar screenshot (default: False).",
                "default": False,
            },
            "full_page": {
                "type": "boolean",
                "description": "Ambil screenshot memanjang seluruh halaman (default: False).",
                "default": False,
            },
            "filename": {
                "type": "string",
                "description": "Nama file kustom untuk berkas PDF atau screenshot.",
            },
            "device_type": {
                "type": "string",
                "enum": ["desktop", "mobile"],
                "description": "Ukuran viewport layar browser (default: desktop).",
                "default": "desktop",
            },
        },
        "required": ["action"],
    }

    def __init__(self, session_manager: Any = None) -> None:
        self.session_manager = session_manager or browser_session_manager

    def _get_media_dir(self) -> str:
        settings = get_settings()
        media_dir = settings.temp_media_dir
        try:
            os.makedirs(media_dir, exist_ok=True)
            return media_dir
        except OSError:
            tmp = os.path.join(tempfile.gettempdir(), "faf_media")
            os.makedirs(tmp, exist_ok=True)
            return tmp

    async def execute(self, context: ToolContext, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action", "open").lower().strip()
        settings = get_settings()

        if action == "close":
            await self.session_manager.stop()
            return ToolResult(
                success=True,
                output="Sesi browser headless ditutup dan RAM perangkat telah dibebaskan.",
            )

        # Early URL safety check for 'open' before spinning up browser
        if action == "open":
            raw_url = str(kwargs.get("url") or "").strip()
            if not raw_url:
                return ToolResult(success=False, output="", error="Parameter 'url' wajib diisi untuk action 'open'.")
            if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", raw_url):
                raw_url = "https://" + raw_url
                kwargs["url"] = raw_url
            is_safe, safety_msg, _ = _check_url_safety(raw_url)
            if not is_safe:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Akses ditolak karena URL tidak aman: {safety_msg}",
                )

        # Check binary availability
        if not _find_browser_binary():
            return ToolResult(
                success=False,
                output="",
                error=(
                    "Browser Chromium headless belum terpasang di Termux.\n"
                    "Pasang dengan menjalankan:\n"
                    "pkg install x11-repo -y && pkg install chromium -y"
                ),
            )

        try:
            if context.on_status_update:
                await context.on_status_update(f"● browser_agent · {action}...")

            cdp = await self.session_manager.get_cdp_client()

            # Set viewport if needed
            device_type = kwargs.get("device_type") or settings.browser_default_viewport
            preset = VIEWPORT_PRESETS.get(device_type, VIEWPORT_PRESETS["desktop"])
            try:
                await cdp.send_command(
                    "Emulation.setDeviceMetricsOverride",
                    {
                        "width": preset["width"],
                        "height": preset["height"],
                        "deviceScaleFactor": preset["device_scale_factor"],
                        "mobile": preset["mobile"],
                    },
                )
                await cdp.send_command(
                    "Network.setUserAgentOverride",
                    {"userAgent": preset["user_agent"]},
                )
            except Exception as e:
                logger.debug(f"Could not set device metrics: {e}")

            if action == "open":
                return await self._action_open(context, cdp, kwargs)
            elif action == "click":
                return await self._action_click(context, cdp, kwargs)
            elif action == "type":
                return await self._action_type(context, cdp, kwargs)
            elif action == "scroll":
                return await self._action_scroll(context, cdp, kwargs)
            elif action == "extract":
                return await self._action_extract(context, cdp, kwargs)
            elif action == "screenshot":
                return await self._action_screenshot(context, cdp, kwargs)
            elif action == "save_pdf":
                return await self._action_save_pdf(context, cdp, kwargs)
            elif action == "back":
                return await self._action_back(context, cdp, kwargs)
            else:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Aksi '{action}' tidak dikenal. Pilihan: open, click, type, scroll, extract, screenshot, save_pdf, back, close.",
                )

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception("Error in browser_agent execution: %s", e)
            return ToolResult(
                success=False,
                output="",
                error=f"Kendala browser: {e}",
            )

    async def _evaluate_script(self, cdp: CDPWebSocketClient, script: str) -> Any:
        res = await cdp.send_command(
            "Runtime.evaluate",
            {
                "expression": script,
                "returnByValue": True,
                "awaitPromise": True,
            },
        )
        return res.get("result", {}).get("value")

    async def _index_dom(self, cdp: CDPWebSocketClient) -> dict[str, Any]:
        """Index visible interactive elements on page and return metadata."""
        val = await self._evaluate_script(cdp, DOM_INDEXING_SCRIPT)
        if isinstance(val, dict):
            return val
        return {"title": "Unknown", "url": "", "elements": [], "innerText": ""}

    def _format_elements_list(self, elements: list[dict[str, Any]]) -> str:
        if not elements:
            return "Tidak ditemukan elemen interaktif yang terlihat di viewport."
        lines = ["Elemen Interaktif di Halaman (sebutkan [id] untuk klik/ketik):"]
        for el in elements:
            lines.append(f"[{el.get('id')}] {el.get('description')}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Action Handlers
    # ------------------------------------------------------------------
    async def _action_open(self, context: ToolContext, cdp: CDPWebSocketClient, kwargs: dict[str, Any]) -> ToolResult:
        raw_url = str(kwargs.get("url") or "").strip()
        if not raw_url:
            return ToolResult(success=False, output="", error="Parameter 'url' wajib diisi untuk action 'open'.")

        if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", raw_url):
            raw_url = "https://" + raw_url

        is_safe, safety_msg, _ = _check_url_safety(raw_url)
        if not is_safe:
            return ToolResult(
                success=False,
                output="",
                error=f"Akses ditolak karena URL tidak aman: {safety_msg}",
            )

        wait_sec = max(1, min(10, int(kwargs.get("wait_seconds") or 2)))
        await cdp.send_command("Page.navigate", {"url": raw_url})
        await asyncio.sleep(wait_sec)

        dom_info = await self._index_dom(cdp)
        title = dom_info.get("title", "")
        current_url = dom_info.get("url", raw_url)
        elements = dom_info.get("elements", [])
        inner_text = dom_info.get("innerText", "").strip()
        if len(inner_text) > 1500:
            inner_text = inner_text[:1500] + "\n...(konten panjang dipotong)"

        out_lines = [
            f"Halaman Berhasil Dimuat",
            f"• Judul : {title}",
            f"• URL   : {current_url}",
            "",
            "Ringkasan Konten Teks:",
            inner_text or "(Konten teks kosong / visual murni)",
            "",
            self._format_elements_list(elements),
        ]

        media_path = None
        media_type = None
        if kwargs.get("screenshot"):
            media_path = await self._capture_screenshot_file(cdp, kwargs)
            if media_path:
                media_type = "photo"

        return ToolResult(
            success=True,
            output="\n".join(out_lines),
            media_path=media_path,
            media_type=media_type,
        )

    async def _action_click(self, context: ToolContext, cdp: CDPWebSocketClient, kwargs: dict[str, Any]) -> ToolResult:
        element_id = kwargs.get("element_id")
        selector = kwargs.get("selector")

        if element_id is not None:
            target_sel = f'[data-faf-id="{int(element_id)}"]'
            label = f"elemen [{element_id}]"
        elif selector:
            target_sel = str(selector).strip()
            label = f"selector '{target_sel}'"
        else:
            return ToolResult(
                success=False,
                output="",
                error="Sertakan 'element_id' (nomor [1..N]) atau 'selector' untuk melakukan klik.",
            )

        click_js = f"""
        (() => {{
            const el = document.querySelector({json.dumps(target_sel)});
            if (!el) return {{success: false, error: 'Elemen {target_sel} tidak ditemukan.'}};
            el.scrollIntoView({{behavior: 'instant', block: 'center'}});
            el.click();
            return {{success: true}};
        }})()
        """
        res = await self._evaluate_script(cdp, click_js)
        if isinstance(res, dict) and not res.get("success"):
            return ToolResult(success=False, output="", error=res.get("error", "Gagal mengklik elemen."))

        wait_sec = max(1, min(5, int(kwargs.get("wait_seconds") or 2)))
        await asyncio.sleep(wait_sec)

        dom_info = await self._index_dom(cdp)
        out_lines = [
            f"Berhasil mengklik {label}.",
            f"• Judul Halaman : {dom_info.get('title')}",
            f"• URL Saat Ini   : {dom_info.get('url')}",
            "",
            self._format_elements_list(dom_info.get("elements", [])),
        ]

        media_path = None
        media_type = None
        if kwargs.get("screenshot"):
            media_path = await self._capture_screenshot_file(cdp, kwargs)
            if media_path:
                media_type = "photo"

        return ToolResult(
            success=True,
            output="\n".join(out_lines),
            media_path=media_path,
            media_type=media_type,
        )

    async def _action_type(self, context: ToolContext, cdp: CDPWebSocketClient, kwargs: dict[str, Any]) -> ToolResult:
        element_id = kwargs.get("element_id")
        selector = kwargs.get("selector")
        text = str(kwargs.get("text") or "")
        submit = bool(kwargs.get("submit", True))

        if element_id is not None:
            target_sel = f'[data-faf-id="{int(element_id)}"]'
            label = f"elemen [{element_id}]"
        elif selector:
            target_sel = str(selector).strip()
            label = f"selector '{target_sel}'"
        else:
            return ToolResult(
                success=False,
                output="",
                error="Sertakan 'element_id' atau 'selector' untuk mengetik teks.",
            )

        type_js = f"""
        (() => {{
            const el = document.querySelector({json.dumps(target_sel)});
            if (!el) return {{success: false, error: 'Elemen {target_sel} tidak ditemukan.'}};
            el.scrollIntoView({{behavior: 'instant', block: 'center'}});
            el.focus();
            el.value = {json.dumps(text)};
            el.dispatchEvent(new Event('input', {{bubbles: true}}));
            el.dispatchEvent(new Event('change', {{bubbles: true}}));
            if ({json.dumps(submit)}) {{
                if (el.form) {{
                    el.form.dispatchEvent(new Event('submit', {{bubbles: true, cancelable: true}}));
                }} else {{
                    const enterEv = new KeyboardEvent('keydown', {{bubbles: true, cancelable: true, key: 'Enter', code: 'Enter', keyCode: 13}});
                    el.dispatchEvent(enterEv);
                }}
            }}
            return {{success: true}};
        }})()
        """
        res = await self._evaluate_script(cdp, type_js)
        if isinstance(res, dict) and not res.get("success"):
            return ToolResult(success=False, output="", error=res.get("error", "Gagal mengetik pada elemen."))

        wait_sec = max(1, min(5, int(kwargs.get("wait_seconds") or 2)))
        await asyncio.sleep(wait_sec)

        dom_info = await self._index_dom(cdp)
        out_lines = [
            f"Berhasil mengetikkan '{text}' ke dalam {label} (Submit: {submit}).",
            f"• Judul Halaman : {dom_info.get('title')}",
            f"• URL Saat Ini   : {dom_info.get('url')}",
            "",
            self._format_elements_list(dom_info.get("elements", [])),
        ]

        media_path = None
        media_type = None
        if kwargs.get("screenshot"):
            media_path = await self._capture_screenshot_file(cdp, kwargs)
            if media_path:
                media_type = "photo"

        return ToolResult(
            success=True,
            output="\n".join(out_lines),
            media_path=media_path,
            media_type=media_type,
        )

    async def _action_scroll(self, context: ToolContext, cdp: CDPWebSocketClient, kwargs: dict[str, Any]) -> ToolResult:
        direction = str(kwargs.get("direction") or "down").lower().strip()
        amount_px = int(kwargs.get("amount_px") or 600)

        if direction == "top":
            scroll_js = "window.scrollTo({top: 0, behavior: 'instant'});"
        elif direction == "bottom":
            scroll_js = "window.scrollTo({top: document.body.scrollHeight, behavior: 'instant'});"
        elif direction == "up":
            scroll_js = f"window.scrollBy({{top: -{amount_px}, behavior: 'instant'}});"
        else:
            scroll_js = f"window.scrollBy({{top: {amount_px}, behavior: 'instant'}});"

        await self._evaluate_script(cdp, scroll_js)
        await asyncio.sleep(1)

        dom_info = await self._index_dom(cdp)
        out_lines = [
            f"Halaman digulir ({direction}, {amount_px}px).",
            "",
            self._format_elements_list(dom_info.get("elements", [])),
        ]

        media_path = None
        media_type = None
        if kwargs.get("screenshot"):
            media_path = await self._capture_screenshot_file(cdp, kwargs)
            if media_path:
                media_type = "photo"

        return ToolResult(
            success=True,
            output="\n".join(out_lines),
            media_path=media_path,
            media_type=media_type,
        )

    async def _action_extract(self, context: ToolContext, cdp: CDPWebSocketClient, kwargs: dict[str, Any]) -> ToolResult:
        mode = str(kwargs.get("mode") or "text").lower().strip()

        if mode == "links":
            links_js = """
            (() => {
                const links = Array.from(document.querySelectorAll('a[href]'));
                return links.map(a => ({
                    text: (a.innerText || a.getAttribute('title') || '').trim().replace(/\\s+/g, ' '),
                    href: a.href
                })).filter(l => l.href && !l.href.startsWith('javascript:'));
            })()
            """
            data = await self._evaluate_script(cdp, links_js) or []
            lines = [f"Daftar Tautan Halaman ({len(data)} ditemukan):"]
            for i, l in enumerate(data[:50], 1):
                lines.append(f"{i}. {l.get('text') or 'Tautan'} -> {l.get('href')}")
            return ToolResult(success=True, output="\n".join(lines))

        elif mode == "tables":
            tables_js = """
            (() => {
                const tables = Array.from(document.querySelectorAll('table'));
                return tables.map(t => {
                    const rows = Array.from(t.querySelectorAll('tr'));
                    return rows.map(r => Array.from(r.querySelectorAll('th, td')).map(c => c.innerText.trim()));
                });
            })()
            """
            tables_data = await self._evaluate_script(cdp, tables_js) or []
            if not tables_data:
                return ToolResult(success=True, output="Tidak ditemukan tabel pada halaman ini.")
            lines = [f"Tabel Ditemukan ({len(tables_data)} tabel):"]
            for t_idx, tbl in enumerate(tables_data, 1):
                lines.append(f"\n--- Tabel {t_idx} ---")
                for row in tbl:
                    lines.append("• " + " | ".join(row))
            return ToolResult(success=True, output="\n".join(lines))

        elif mode == "selector":
            sel = kwargs.get("selector")
            if not sel:
                return ToolResult(success=False, output="", error="Parameter 'selector' wajib diisi untuk mode 'selector'.")
            extract_js = f"""
            (() => {{
                const el = document.querySelector({json.dumps(sel)});
                return el ? el.innerText.trim() : null;
            }})()
            """
            val = await self._evaluate_script(cdp, extract_js)
            if val is None:
                return ToolResult(success=False, output="", error=f"Elemen '{sel}' tidak ditemukan.")
            return ToolResult(success=True, output=f"Hasil Ekstraksi [{sel}]:\n\n{val}")

        else:  # default 'text'
            text = await self._evaluate_script(cdp, "document.body ? document.body.innerText : ''")
            return ToolResult(
                success=True,
                output=f"Konten Teks Lengkap Halaman ({len(text)} karakter):\n\n{text[:4000]}",
            )

    async def _action_screenshot(self, context: ToolContext, cdp: CDPWebSocketClient, kwargs: dict[str, Any]) -> ToolResult:
        media_path = await self._capture_screenshot_file(cdp, kwargs)
        if not media_path:
            return ToolResult(success=False, output="", error="Gagal mengambil tangkapan layar browser.")
        return ToolResult(
            success=True,
            output=f"Tangkapan layar halaman aktif berhasil diambil ({os.path.basename(media_path)}).",
            media_path=media_path,
            media_type="photo",
        )

    async def _action_save_pdf(self, context: ToolContext, cdp: CDPWebSocketClient, kwargs: dict[str, Any]) -> ToolResult:
        custom_name = kwargs.get("filename")
        if custom_name:
            fname = re.sub(r"[^a-zA-Z0-9._-]", "_", str(custom_name).strip())
            if not fname.lower().endswith(".pdf"):
                fname += ".pdf"
        else:
            fname = f"webpage_{int(time.time())}.pdf"

        media_dir = self._get_media_dir()
        pdf_path = os.path.join(media_dir, fname)

        pdf_data = await cdp.send_command(
            "Page.printToPDF",
            {
                "printBackground": True,
                "preferCSSPageSize": True,
            },
        )
        data_b64 = pdf_data.get("data")
        if not data_b64:
            return ToolResult(success=False, output="", error="Gagal menghasilkan dokumen PDF dari halaman web.")

        raw_bytes = base64.b64decode(data_b64)
        with open(pdf_path, "wb") as f:
            f.write(raw_bytes)

        return ToolResult(
            success=True,
            output=f"Halaman web berhasil dikonversi ke dokumen PDF: {fname} ({len(raw_bytes) / 1024:.1f} KB).",
            media_path=pdf_path,
            media_type="document",
        )

    async def _action_back(self, context: ToolContext, cdp: CDPWebSocketClient, kwargs: dict[str, Any]) -> ToolResult:
        await self._evaluate_script(cdp, "window.history.back()")
        await asyncio.sleep(2)
        dom_info = await self._index_dom(cdp)
        out_lines = [
            "Kembali ke halaman sebelumnya.",
            f"• Judul : {dom_info.get('title')}",
            f"• URL   : {dom_info.get('url')}",
            "",
            self._format_elements_list(dom_info.get("elements", [])),
        ]
        return ToolResult(success=True, output="\n".join(out_lines))

    async def _capture_screenshot_file(self, cdp: CDPWebSocketClient, kwargs: dict[str, Any]) -> str | None:
        """Capture screenshot via CDP and write to media_dir."""
        annotate = bool(kwargs.get("annotate", False))
        full_page = bool(kwargs.get("full_page", False))

        if annotate:
            try:
                await self._evaluate_script(cdp, DRAW_BADGES_SCRIPT)
                await asyncio.sleep(0.3)
            except Exception:
                pass

        try:
            params: dict[str, Any] = {"format": "png"}
            if full_page:
                params["captureBeyondViewport"] = True

            res = await cdp.send_command("Page.captureScreenshot", params)
            data_b64 = res.get("data")
            if not data_b64:
                return None

            raw_bytes = base64.b64decode(data_b64)
            media_dir = self._get_media_dir()
            fname = kwargs.get("filename")
            if fname:
                fname = re.sub(r"[^a-zA-Z0-9._-]", "_", str(fname).strip())
                if not fname.lower().endswith(".png"):
                    fname += ".png"
            else:
                annot_suffix = "_annotated" if annotate else ""
                fname = f"browser_{int(time.time())}{annot_suffix}.png"

            out_path = os.path.join(media_dir, fname)
            with open(out_path, "wb") as f:
                f.write(raw_bytes)
            return out_path
        finally:
            if annotate:
                try:
                    await self._evaluate_script(cdp, REMOVE_BADGES_SCRIPT)
                except Exception:
                    pass
