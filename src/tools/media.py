from __future__ import annotations

import asyncio
import logging
import os
import shlex
import time
import urllib.parse
from typing import Any

from src.config import get_settings
from src.core.android_bridge import bridge
from src.tools.base import BaseTool, ToolContext, ToolResult

logger = logging.getLogger("faf_agent.tools.media")


class MediaControlTool(BaseTool):
    """All-in-one Multimedia, Camera, Voice Recording, TTS, and Audio Player Tool."""

    name = "media_control"
    description = (
        "Kontrol multimedia lengkap: pemutar musik (play, pause, next, previous, stop), "
        "pencarian video YouTube, membuka URL situs di browser Android, mengambil foto kamera depan/belakang "
        "langsung ke Telegram, merekam audio mikrofon fisik dan mengirimkan rekaman suara ke Telegram, "
        "Text-to-Speech (berbicara lantang lewat speaker ponsel fisik via termux-tts-speak), "
        "serta memutar file audio lokal di perangkat."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "playback",
                    "youtube_search",
                    "open_url",
                    "open_camera",
                    "take_photo",
                    "record_audio",
                    "tts_speak",
                    "play_audio_file",
                    "player_status",
                ],
                "description": "Aksi media yang akan dilakukan.",
            },
            "playback_command": {
                "type": "string",
                "enum": ["play", "pause", "play_pause", "next", "previous", "stop", "fast_forward", "rewind"],
                "description": "Perintah kontrol pemutar musik (default: play_pause).",
                "default": "play_pause",
            },
            "query": {
                "type": "string",
                "description": "Kata kunci pencarian untuk YouTube.",
            },
            "url": {
                "type": "string",
                "description": "Tautan URL web yang ingin dibuka di browser perangkat.",
            },
            "camera_id": {
                "type": "integer",
                "enum": [0, 1],
                "description": "Kamera yang digunakan: 0 untuk kamera belakang (default), 1 untuk kamera depan (selfie).",
                "default": 0,
            },
            "duration_seconds": {
                "type": "integer",
                "description": "Durasi perekaman mikrofon dalam detik untuk 'record_audio' (default: 5 detik).",
                "default": 5,
            },
            "text": {
                "type": "string",
                "description": "Kalimat atau teks yang akan diucapkan dengan keras lewat speaker HP untuk 'tts_speak'.",
            },
            "speech_rate": {
                "type": "number",
                "description": "Kecepatan suara bicara TTS (0.5 sampai 2.0, default: 1.0).",
                "default": 1.0,
            },
            "file_path": {
                "type": "string",
                "description": "Path file audio lokal untuk 'play_audio_file' (contoh: '/sdcard/Music/lagu.mp3').",
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
        "fast_forward": 90,
        "rewind": 89,
    }

    async def execute(self, context: ToolContext, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action", "").lower().strip()
        settings = get_settings()

        if context.on_status_update:
            await context.on_status_update(f"● media_control · {action}")

        # -------------------------------------------------------------------
        # 1. Action: PLAYBACK
        # -------------------------------------------------------------------
        if action == "playback":
            cmd_type = kwargs.get("playback_command", "play_pause").lower()
            key_code = self.KEYEVENT_MAP.get(cmd_type, 85)
            await bridge.execute_shell(f"input keyevent {key_code}")
            return ToolResult(
                success=True,
                output=f"Perintah playback '{cmd_type}' (keyevent {key_code}) berhasil dikirim ke pemutar media.",
            )

        # -------------------------------------------------------------------
        # 2. Action: YOUTUBE_SEARCH
        # -------------------------------------------------------------------
        elif action == "youtube_search":
            query = kwargs.get("query", "").strip()
            if not query:
                return ToolResult(success=False, output="", error="Query pencarian YouTube tidak boleh kosong.")

            encoded_q = urllib.parse.quote_plus(query)
            url = f"https://www.youtube.com/results?search_query={encoded_q}"
            cmd = f'am start -a android.intent.action.VIEW -d "{url}"'
            await bridge.execute_shell(cmd)
            return ToolResult(
                success=True,
                output=f"Aplikasi YouTube dibuka dengan pencarian '{query}'.",
            )

        # -------------------------------------------------------------------
        # 3. Action: OPEN_URL
        # -------------------------------------------------------------------
        elif action == "open_url":
            url = kwargs.get("url", "").strip()
            if not url:
                return ToolResult(success=False, output="", error="Parameter 'url' wajib diisi.")
            if not url.startswith(("http://", "https://")):
                url = "https://" + url

            res = await bridge.execute_shell(f"termux-open-url {shlex.quote(url)}")
            if not res.success:
                res = await bridge.execute_shell(f"am start -a android.intent.action.VIEW -d {shlex.quote(url)}")
            return ToolResult(
                success=True,
                output=f"Tautan URL berhasil dibuka di peramban ponsel: {url}",
            )

        # -------------------------------------------------------------------
        # 4. Action: OPEN_CAMERA (Launch default camera app)
        # -------------------------------------------------------------------
        elif action == "open_camera":
            cmd = "am start -a android.media.action.IMAGE_CAPTURE"
            res = await bridge.execute_shell(cmd)
            return ToolResult(
                success=True,
                output="Aplikasi kamera bawaan berhasil dibuka di layar ponsel.",
            )

        # -------------------------------------------------------------------
        # 5. Action: TAKE_PHOTO (Front or Back Camera -> Telegram Media)
        # -------------------------------------------------------------------
        elif action == "take_photo":
            cam_id = kwargs.get("camera_id", 0)
            cam_label = "Depan (Selfie)" if cam_id == 1 else "Belakang (Utama)"
            os.makedirs(settings.temp_media_dir, exist_ok=True)
            filename = f"photo_{int(time.time())}.jpg"
            filepath = os.path.join(settings.temp_media_dir, filename)

            res = await bridge.execute_shell(
                f"termux-camera-photo -c {cam_id} '{filepath}'",
                timeout=15,
            )

            if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                return ToolResult(
                    success=True,
                    output=f"Foto kamera {cam_label} berhasil diambil.",
                    media_path=filepath,
                    media_type="photo",
                )
            return ToolResult(
                success=False,
                output="",
                error=f"Gagal mengambil foto kamera: {res.stderr or 'Pastikan izin kamera Termux:API aktif.'}",
            )

        # -------------------------------------------------------------------
        # 5. Action: RECORD_AUDIO (Microphone -> Telegram Voice Document)
        # -------------------------------------------------------------------
        elif action == "record_audio":
            dur = max(1, min(60, kwargs.get("duration_seconds", 5)))
            os.makedirs(settings.temp_media_dir, exist_ok=True)
            filename = f"record_{int(time.time())}.m4a"
            filepath = os.path.join(settings.temp_media_dir, filename)

            # Start recording
            res_start = await bridge.execute_shell(
                f"termux-microphone-record -f '{filepath}' -l {dur} -e m4a",
                timeout=5,
            )

            # Wait for recording to complete
            await asyncio.sleep(dur + 1)

            if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                return ToolResult(
                    success=True,
                    output=f"Perekaman suara mikrofon selama {dur} detik berhasil diselesaikan.",
                    media_path=filepath,
                    media_type="document",
                )

            # Try stop explicitly if still running
            await bridge.execute_shell("termux-microphone-record -q")
            if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                return ToolResult(
                    success=True,
                    output=f"Perekaman suara mikrofon berhasil.",
                    media_path=filepath,
                    media_type="document",
                )

            return ToolResult(
                success=False,
                output="",
                error=f"Gagal merekam suara: {res_start.stderr or 'Izin mikrofon Termux:API diperlukan.'}",
            )

        # -------------------------------------------------------------------
        # 6. Action: TTS_SPEAK (Text-to-Speech via Phone Speaker)
        # -------------------------------------------------------------------
        elif action in ("tts_speak", "speak"):
            speak_text = kwargs.get("text", "").strip()
            if not speak_text:
                return ToolResult(success=False, output="", error="Parameter 'text' tidak boleh kosong untuk TTS.")

            rate = kwargs.get("speech_rate", 1.0)
            res = await bridge.execute_shell(
                f"termux-tts-speak -r {float(rate)} {shlex.quote(speak_text)}",
                timeout=12,
            )
            return ToolResult(
                success=True,
                output=f"Suara TTS berhasil diperdengarkan melalui speaker ponsel:\n\"{speak_text}\"",
            )

        # -------------------------------------------------------------------
        # 7. Action: PLAY_AUDIO_FILE
        # -------------------------------------------------------------------
        elif action == "play_audio_file":
            fpath = kwargs.get("file_path", "").strip()
            if not fpath or not os.path.exists(fpath):
                return ToolResult(success=False, output="", error=f"Berkas audio tidak ditemukan: {fpath}")

            res = await bridge.execute_shell(f"termux-media-player play {shlex.quote(fpath)}")
            if res.success:
                return ToolResult(
                    success=True,
                    output=f"Berkas audio '{os.path.basename(fpath)}' sedang diputar melalui pemutar media perangkat.",
                )
            return ToolResult(success=False, output="", error=f"Gagal memutar audio: {res.stderr}")

        # -------------------------------------------------------------------
        # 8. Action: PLAYER_STATUS
        # -------------------------------------------------------------------
        elif action == "player_status":
            res = await bridge.execute_shell("termux-media-player info")
            if res.success and res.stdout.strip():
                return ToolResult(success=True, output=f"Status Pemutar Audio Lokal:\n{res.stdout}")
            return ToolResult(success=True, output="Tidak ada pemutar audio aktif saat ini.")

        return ToolResult(success=False, output="", error=f"Aksi media_control '{action}' tidak dikenal.")
