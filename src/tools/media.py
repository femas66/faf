from __future__ import annotations

import logging
import os
import time
import urllib.parse
from typing import Any

from src.config import get_settings
from src.core.android_bridge import bridge
from src.tools.base import BaseTool, ToolContext, ToolResult

logger = logging.getLogger("faf_agent.tools.media")


class MediaControlTool(BaseTool):
    name = "media_control"
    description = (
        "Kontrol media pemutar musik (play, pause, next, previous, stop), pencarian video YouTube, "
        "membuka aplikasi kamera default, dan mengambil foto langsung secara instan via Termux "
        "(kamera depan/belakang) untuk dikirim langsung ke chat Telegram."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "playback",
                    "youtube_search",
                    "open_camera",
                    "take_photo",
                ],
                "description": "Aksi media yang akan dilakukan.",
            },
            "playback_command": {
                "type": "string",
                "enum": ["play", "pause", "play_pause", "next", "previous", "stop"],
                "description": "Perintah pemutar musik.",
            },
            "query": {
                "type": "string",
                "description": "Kata kunci pencarian untuk YouTube.",
            },
            "camera_id": {
                "type": "integer",
                "enum": [0, 1],
                "description": "Kamera yang digunakan: 0 untuk kamera belakang (default), 1 untuk kamera depan.",
                "default": 0,
            },
        },
        "required": ["action"],
    }

    KEYEVENT_MAP = {
        "play": 126,
        "pause": 127,
        "play_pause": 85,
        "next": 87,
        "previous": 88,
        "stop": 86,
    }

    async def execute(self, context: ToolContext, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action", "")
        settings = get_settings()

        if context.on_status_update:
            await context.on_status_update(f"● media_control · {action}")

        # 1. Playback Control
        if action == "playback":
            cmd_type = kwargs.get("playback_command", "play_pause").lower()
            key_code = self.KEYEVENT_MAP.get(cmd_type, 85)
            res = await bridge.execute_shell(f"input keyevent {key_code}")
            return ToolResult(
                success=True,
                output=f"Perintah playback '{cmd_type}' (keyevent {key_code}) berhasil dikirim ke pemutar media.",
            )

        # 2. YouTube Search
        elif action == "youtube_search":
            query = kwargs.get("query", "").strip()
            if not query:
                return ToolResult(success=False, output="", error="Query pencarian YouTube tidak boleh kosong.")

            encoded_q = urllib.parse.quote_plus(query)
            url = f"https://www.youtube.com/results?search_query={encoded_q}"
            cmd = f'am start -a android.intent.action.VIEW "{url}"'
            res = await bridge.execute_shell(cmd)
            return ToolResult(
                success=True,
                output=f"Aplikasi YouTube dibuka dengan pencarian '{query}'.",
            )

        # 3. Open Camera UI
        elif action == "open_camera":
            cmd = "am start -a android.media.action.IMAGE_CAPTURE"
            res = await bridge.execute_shell(cmd)
            return ToolResult(
                success=True,
                output="Aplikasi kamera sistem berhasil dibuka.",
            )

        # 4. Take Photo Directly via Termux Camera
        elif action == "take_photo":
            camera_id = kwargs.get("camera_id", 0)
            camera_name = "kamera depan" if camera_id == 1 else "kamera belakang"

            if context.on_status_update:
                await context.on_status_update(f"● media_control · mengambil foto {camera_name}...")

            os.makedirs(settings.temp_media_dir, exist_ok=True)
            filename = f"photo_{int(time.time())}.jpg"
            filepath = os.path.join(settings.temp_media_dir, filename)

            cmd = f"termux-camera-photo -c {camera_id} '{filepath}'"
            res = await bridge.execute_shell(cmd, timeout=20)

            if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                return ToolResult(
                    success=True,
                    output=f"Foto berhasil diambil menggunakan {camera_name}.",
                    media_path=filepath,
                    media_type="photo",
                )
            else:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Gagal mengambil foto dari {camera_name}: {res.stderr or 'File foto tidak tercipta. Pastikan izin kamera Termux:API aktif.'}",
                )

        return ToolResult(success=False, output="", error=f"Aksi '{action}' tidak dikenal.")
