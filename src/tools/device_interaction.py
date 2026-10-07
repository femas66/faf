from __future__ import annotations

import logging
import re
import shlex
from typing import Any

from src.core.android_bridge import bridge
from src.tools.base import BaseTool, ToolContext, ToolResult

logger = logging.getLogger("faf_agent.tools.device_interaction")

COMMON_KEYCODES: dict[str, int] = {
    "home": 3,
    "back": 4,
    "call": 5,
    "endcall": 6,
    "volume_up": 24,
    "volume_down": 25,
    "power": 26,
    "camera": 27,
    "enter": 66,
    "backspace": 67,
    "tab": 61,
    "space": 62,
    "notification": 83,
    "menu": 82,
    "app_switch": 187,
    "recents": 187,
    "escape": 111,
    "wakeup": 224,
    "sleep": 223,
    "media_play": 126,
    "media_pause": 127,
    "media_next": 87,
    "media_previous": 88,
}


class DeviceInteractionTool(BaseTool):
    """Deep Android UI Automation, Touch, Tap, Gestures, Keyevents, and Screen Navigation Tool."""

    name = "device_interaction"
    description = (
        "Kontrol interaksi antarmuka layar sentuh Android fisik: mengetuk koordinat layar (tap x y), "
        "mengusap/menggulir layar (swipe/scroll dari x1 y1 ke x2 y2), menekan tombol navigasi hardware/virtual "
        "(HOME, BACK, RECENTS, POWER, VOLUME, ENTER), mengetik teks langsung ke input aktif di layar (type_text), "
        "membangunkan/mematikan layar (wake/sleep), menarik tirai notifikasi (expand_notifications), "
        "membuka panel quick settings, serta mengecek resolusi layar untuk perhitungan koordinat sentuhan."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "tap",
                    "swipe",
                    "keyevent",
                    "type_text",
                    "wake",
                    "sleep",
                    "expand_notifications",
                    "collapse_notifications",
                    "expand_settings",
                    "screen_size",
                ],
                "description": "Tindakan interaksi layar yang diinginkan.",
            },
            "x": {
                "type": "integer",
                "description": "Koordinat horizontal X untuk aksi 'tap'.",
            },
            "y": {
                "type": "integer",
                "description": "Koordinat vertikal Y untuk aksi 'tap'.",
            },
            "x1": {
                "type": "integer",
                "description": "Koordinat awal X1 untuk aksi 'swipe'.",
            },
            "y1": {
                "type": "integer",
                "description": "Koordinat awal Y1 untuk aksi 'swipe'.",
            },
            "x2": {
                "type": "integer",
                "description": "Koordinat akhir X2 untuk aksi 'swipe'.",
            },
            "y2": {
                "type": "integer",
                "description": "Koordinat akhir Y2 untuk aksi 'swipe'.",
            },
            "duration_ms": {
                "type": "integer",
                "description": "Durasi usapan swipe dalam milidetik (default: 300 ms).",
                "default": 300,
            },
            "key": {
                "type": "string",
                "description": "Nama tombol (home, back, recents, power, enter, volume_up, volume_down) atau kode integer.",
            },
            "text": {
                "type": "string",
                "description": "Teks yang akan diketikkan secara otomatis ke kolom input yang aktif di layar.",
            },
        },
        "required": ["action"],
    }

    async def execute(self, context: ToolContext, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action", "").lower().strip()

        if context.on_status_update:
            await context.on_status_update(f"● device_interaction · {action}")

        # -------------------------------------------------------------------
        # 1. Action: TAP
        # -------------------------------------------------------------------
        if action == "tap":
            x = kwargs.get("x")
            y = kwargs.get("y")
            if x is None or y is None:
                return ToolResult(success=False, output="", error="Parameter 'x' dan 'y' wajib diisi untuk tap.")

            res = await bridge.execute_shell(f"input tap {int(x)} {int(y)}")
            return ToolResult(
                success=True,
                output=f"Sentuhan layar (tap) berhasil dieksekusi pada koordinat ({int(x)}, {int(y)}).",
            )

        # -------------------------------------------------------------------
        # 2. Action: SWIPE
        # -------------------------------------------------------------------
        elif action == "swipe":
            x1 = kwargs.get("x1")
            y1 = kwargs.get("y1")
            x2 = kwargs.get("x2")
            y2 = kwargs.get("y2")
            dur = kwargs.get("duration_ms", 300)

            if None in (x1, y1, x2, y2):
                return ToolResult(success=False, output="", error="Parameter 'x1', 'y1', 'x2', 'y2' wajib diisi untuk swipe.")

            res = await bridge.execute_shell(
                f"input swipe {int(x1)} {int(y1)} {int(x2)} {int(y2)} {int(dur)}"
            )
            return ToolResult(
                success=True,
                output=f"Usapan layar (swipe) berhasil dieksekusi dari ({int(x1)}, {int(y1)}) menuju ({int(x2)}, {int(y2)}) selama {dur} ms.",
            )

        # -------------------------------------------------------------------
        # 3. Action: KEYEVENT
        # -------------------------------------------------------------------
        elif action == "keyevent":
            key_val = str(kwargs.get("key", "")).strip().lower()
            if not key_val:
                return ToolResult(success=False, output="", error="Parameter 'key' wajib diisi (misal: 'home', 'back', 'power').")

            keycode = COMMON_KEYCODES.get(key_val)
            if keycode is None:
                if key_val.isdigit():
                    keycode = int(key_val)
                else:
                    return ToolResult(
                        success=False,
                        output="",
                        error=f"Tombol '{key_val}' tidak dikenal. Contoh: home, back, recents, power, enter, volume_up, volume_down.",
                    )

            res = await bridge.execute_shell(f"input keyevent {keycode}")
            return ToolResult(
                success=True,
                output=f"Tombol navigasi '{key_val}' (keycode {keycode}) berhasil ditekan.",
            )

        # -------------------------------------------------------------------
        # 4. Action: TYPE_TEXT
        # -------------------------------------------------------------------
        elif action == "type_text":
            text_val = kwargs.get("text", "")
            if not text_val:
                return ToolResult(success=False, output="", error="Parameter 'text' tidak boleh kosong untuk type_text.")

            # Replace spaces with %s for Android input text tool
            safe_text = text_val.replace(" ", "%s")
            # Escape quotes
            safe_text = re.sub(r'([\"\'\$\`\\])', r"\\\1", safe_text)

            res = await bridge.execute_shell(f'input text "{safe_text}"')
            return ToolResult(
                success=True,
                output=f"Teks berhasil diketikkan ke layar aktif:\n\"{text_val}\"",
            )

        # -------------------------------------------------------------------
        # 5. Action: WAKE
        # -------------------------------------------------------------------
        elif action == "wake":
            await bridge.execute_shell("input keyevent 224")  # KEYCODE_WAKEUP
            return ToolResult(success=True, output="Layar ponsel berhasil dibangunkan (Wake).")

        # -------------------------------------------------------------------
        # 6. Action: SLEEP
        # -------------------------------------------------------------------
        elif action == "sleep":
            await bridge.execute_shell("input keyevent 223")  # KEYCODE_SLEEP
            return ToolResult(success=True, output="Layar ponsel berhasil dimatikan ke mode tidur (Sleep).")

        # -------------------------------------------------------------------
        # 7. Action: EXPAND_NOTIFICATIONS
        # -------------------------------------------------------------------
        elif action == "expand_notifications":
            res = await bridge.execute_shell("cmd statusbar expand-notifications", as_root=bridge.is_root_available())
            return ToolResult(success=True, output="Tirai bilah notifikasi berhasil dibuka/ditarik ke bawah.")

        # -------------------------------------------------------------------
        # 8. Action: COLLAPSE_NOTIFICATIONS
        # -------------------------------------------------------------------
        elif action == "collapse_notifications":
            res = await bridge.execute_shell("cmd statusbar collapse", as_root=bridge.is_root_available())
            return ToolResult(success=True, output="Bilah notifikasi berhasil ditutup kembali.")

        # -------------------------------------------------------------------
        # 9. Action: EXPAND_SETTINGS
        # -------------------------------------------------------------------
        elif action == "expand_settings":
            res = await bridge.execute_shell("cmd statusbar expand-settings", as_root=bridge.is_root_available())
            return ToolResult(success=True, output="Panel Pengaturan Cepat (Quick Settings) berhasil dibuka.")

        # -------------------------------------------------------------------
        # 10. Action: SCREEN_SIZE
        # -------------------------------------------------------------------
        elif action == "screen_size":
            res = await bridge.execute_shell("wm size")
            res_den = await bridge.execute_shell("wm density")
            return ToolResult(
                success=True,
                output=f"Ukuran & Resolusi Layar Ponsel:\n• Resolusi: {res.stdout.strip()}\n• Kerapatan: {res_den.stdout.strip()}",
            )

        return ToolResult(success=False, output="", error=f"Aksi device_interaction '{action}' tidak dikenal.")
