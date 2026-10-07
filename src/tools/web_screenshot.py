from __future__ import annotations

import logging
import os
import re
import shlex
import shutil
import tempfile
import time
import urllib.parse
from typing import Any

from src.config import get_settings
from src.core.android_bridge import bridge
from src.tools.base import BaseTool, ToolContext, ToolResult

logger = logging.getLogger("faf_agent.tools.web_screenshot")

# Viewport presets
VIEWPORT_PRESETS = {
    "desktop": {
        "width": 1920,
        "height": 1080,
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "label": "Desktop (1920x1080 FHD)",
    },
    "mobile": {
        "width": 412,
        "height": 915,
        "user_agent": (
            "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36"
        ),
        "label": "Mobile Android (412x915 Portrait)",
    },
}

# Candidate browser binaries in Termux / Linux
BROWSER_CANDIDATES = [
    "chromium",
    "chromium-browser",
    "google-chrome-stable",
    "google-chrome",
    "chrome",
]


def _format_size(size_bytes: int) -> str:
    """Format bytes into readable size."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.2f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.2f} MB"


def _find_browser_binary() -> str | None:
    """Find installed Chromium or Chrome binary path."""
    for candidate in BROWSER_CANDIDATES:
        p = shutil.which(candidate)
        if p:
            return p

    # Standard Termux paths
    termux_paths = [
        "/data/data/com.termux/files/usr/bin/chromium",
        "/data/data/com.termux/files/usr/bin/chromium-browser",
        "/data/data/com.termux/files/usr/bin/chrome",
    ]
    for tp in termux_paths:
        if os.path.exists(tp) and os.access(tp, os.X_OK):
            return tp

    return None


class WebScreenshotTool(BaseTool):
    """Dedicated tool to take realistic website screenshots via headless Chromium

    supporting desktop and mobile viewports.
    """

    name = "web_screenshot"
    description = (
        "Tool khusus untuk mengambil tangkapan layar (screenshot) halaman website secara sempurna "
        "menggunakan Chromium mode headless di Termux. Mendukung tampilan desktop (default, 1920x1080) "
        "maupun tampilan mobile Android (412x915). Gambar screenshot akan langsung dikirimkan ke chat Telegram."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["capture", "check_browser"],
                "description": (
                    "Aksi yang diinginkan: 'capture' (ambil screenshot website), "
                    "'check_browser' (cek kesiapan instalasi Chromium di Termux)."
                ),
                "default": "capture",
            },
            "url": {
                "type": "string",
                "description": "Tautan URL situs web yang ingin di-screenshot (contoh: 'https://github.com' atau 'detik.com').",
            },
            "device_type": {
                "type": "string",
                "enum": ["desktop", "mobile"],
                "description": (
                    "Tipe tampilan perangkat: 'desktop' (default: 1920x1080) "
                    "atau 'mobile' (tampilan ponsel Android 412x915)."
                ),
                "default": "desktop",
            },
            "width": {
                "type": "integer",
                "description": "Lebar kustom layar dalam piksel (opsional, default 1920 desktop / 412 mobile).",
            },
            "height": {
                "type": "integer",
                "description": "Tinggi kustom layar dalam piksel (opsional, default 1080 desktop / 915 mobile).",
            },
            "delay_seconds": {
                "type": "integer",
                "description": (
                    "Waktu tunggu dalam detik agar JavaScript/SPA selesai me-render konten "
                    "sebelum screenshot diambil (default: 3 detik, maksimal 15 detik)."
                ),
                "default": 3,
            },
            "full_page": {
                "type": "boolean",
                "description": "Setel True jika ingin menangkap halaman penuh secara memanjang ke bawah.",
                "default": False,
            },
        },
        "required": ["url"],
    }

    async def execute(self, context: ToolContext, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action", "capture").lower().strip()
        settings = get_settings()

        # -------------------------------------------------------------------
        # 1. Action: CHECK_BROWSER
        # -------------------------------------------------------------------
        if action == "check_browser":
            browser_bin = _find_browser_binary()
            if browser_bin:
                ver_res = await bridge.execute_shell(f"{shlex.quote(browser_bin)} --version", timeout=5)
                ver_str = ver_res.stdout.strip() if ver_res.success else "Tersedia"
                return ToolResult(
                    success=True,
                    output=(
                        f"Status Headless Browser:\n"
                        f"• Binary: {browser_bin}\n"
                        f"• Versi: {ver_str}\n"
                        f"• Status: Siap digunakan untuk screenshot website."
                    ),
                )
            else:
                return ToolResult(
                    success=False,
                    output="",
                    error=(
                        "Chromium belum terpasang di Termux.\n"
                        "Untuk menginstalnya, jalankan perintah berikut di Termux Anda:\n"
                        "pkg install tur-repo && pkg install chromium\n"
                        "atau:\n"
                        "pkg install x11-repo && pkg install chromium"
                    ),
                )

        # -------------------------------------------------------------------
        # 2. Action: CAPTURE
        # -------------------------------------------------------------------
        raw_url = kwargs.get("url", "").strip()
        if not raw_url:
            return ToolResult(success=False, output="", error="Parameter 'url' wajib disertakan.")

        # Ensure scheme is present
        if not re.match(r"^https?://", raw_url, re.IGNORECASE):
            target_url = "https://" + raw_url
        else:
            target_url = raw_url

        # Check for valid URL format
        try:
            parsed = urllib.parse.urlparse(target_url)
            if not parsed.netloc:
                return ToolResult(success=False, output="", error=f"Alamat URL '{target_url}' tidak valid.")
        except Exception:
            return ToolResult(success=False, output="", error=f"Alamat URL '{target_url}' tidak valid.")

        device_type = kwargs.get("device_type", "desktop").lower().strip()
        if device_type not in ("desktop", "mobile"):
            device_type = "desktop"

        preset = VIEWPORT_PRESETS[device_type]
        width = kwargs.get("width") or preset["width"]
        height = kwargs.get("height") or preset["height"]
        user_agent = preset["user_agent"]
        delay_sec = max(1, min(15, kwargs.get("delay_seconds", 3)))
        virtual_time_budget_ms = delay_sec * 1000

        full_page = kwargs.get("full_page", False)
        if full_page:
            height = max(height, 3000)

        browser_bin = _find_browser_binary()
        if not browser_bin:
            return ToolResult(
                success=False,
                output="",
                error=(
                    "Browser Chromium headless tidak ditemukan di lingkungan Termux.\n"
                    "Silakan pasang Chromium terlebih dahulu dengan menjalankan:\n"
                    "pkg install tur-repo && pkg install chromium"
                ),
            )

        if context.on_status_update:
            await context.on_status_update(f"● web_screenshot · memuat {target_url} ({device_type})")

        media_dir = settings.temp_media_dir
        try:
            os.makedirs(media_dir, exist_ok=True)
        except OSError:
            media_dir = os.path.join(tempfile.gettempdir(), "faf_media")
            os.makedirs(media_dir, exist_ok=True)

        filename = f"web_{device_type}_{int(time.time())}.png"
        output_filepath = os.path.join(media_dir, filename)

        # Construct Chromium headless command
        # Use modern --headless=new with fallback to --headless
        cmd_args = [
            shlex.quote(browser_bin),
            "--headless=new",
            "--no-sandbox",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--disable-software-rasterizer",
            "--hide-scrollbars",
            f"--window-size={int(width)},{int(height)}",
            f"--virtual-time-budget={int(virtual_time_budget_ms)}",
            "--run-all-compositor-stages-before-draw",
            f"--user-agent={shlex.quote(user_agent)}",
            f"--screenshot={shlex.quote(output_filepath)}",
            shlex.quote(target_url),
        ]
        cmd = " ".join(cmd_args)

        timeout = delay_sec + 20
        res = await bridge.execute_shell(cmd, timeout=timeout)

        # Fallback to classic --headless if --headless=new failed
        if not (os.path.exists(output_filepath) and os.path.getsize(output_filepath) > 0):
            cmd_fallback = cmd.replace("--headless=new", "--headless")
            res = await bridge.execute_shell(cmd_fallback, timeout=timeout)

        if os.path.exists(output_filepath) and os.path.getsize(output_filepath) > 0:
            file_size_str = _format_size(os.path.getsize(output_filepath))
            out_text = (
                f"Tangkapan Layar Website Berhasil Diambil\n\n"
                f"• URL: {target_url}\n"
                f"• Tampilan: {preset['label']}\n"
                f"• Resolusi Render: {width} x {height} px\n"
                f"• Waktu Render (Delay): {delay_sec} detik\n"
                f"• Ukuran Berkas: {file_size_str}\n"
                f"• Berkas gambar telah dikirimkan langsung ke chat Telegram ini."
            )
            return ToolResult(
                success=True,
                output=out_text,
                media_path=output_filepath,
                media_type="photo",
            )
        else:
            err_msg = res.stderr or res.stdout or "Gagal membuat gambar tangkapan layar."
            return ToolResult(
                success=False,
                output="",
                error=f"Gagal mengambil screenshot dari {target_url}: {err_msg[:300]}",
            )
