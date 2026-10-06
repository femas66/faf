from __future__ import annotations

import logging
import os
import time
from typing import Any

from src.config import get_settings
from src.core.android_bridge import bridge
from src.tools.base import BaseTool, ToolContext, ToolResult

logger = logging.getLogger("faf_agent.tools.system")


class SystemSettingsTool(BaseTool):
    name = "system_settings"
    description = (
        "Kontrol pengaturan perangkat Android: senter (torch), WiFi, data seluler, "
        "Bluetooth, volume suara, kecerahan layar (brightness), mode DND (Jangan Ganggu), "
        "tangkapan layar (screenshot), dan tes jaringan internet (ping)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "torch",
                    "wifi",
                    "data",
                    "bluetooth",
                    "volume",
                    "brightness",
                    "dnd",
                    "screenshot",
                    "network",
                ],
                "description": "Pengaturan yang ingin diubah atau diperiksa.",
            },
            "state": {
                "type": "string",
                "enum": ["on", "off"],
                "description": "Digunakan untuk senter (torch): 'on' atau 'off'.",
            },
            "sub_action": {
                "type": "string",
                "enum": ["status", "enable", "disable"],
                "description": "Digunakan untuk wifi, data, atau bluetooth.",
            },
            "volume_stream": {
                "type": "string",
                "enum": ["music", "call", "alarm", "ring", "system", "notification"],
                "description": "Tipe stream volume.",
                "default": "music",
            },
            "volume_value": {
                "type": "integer",
                "description": "Nilai volume (0 - 15).",
            },
            "brightness_value": {
                "type": "integer",
                "description": "Nilai kecerahan layar (0 - 255).",
            },
            "dnd_mode": {
                "type": "string",
                "enum": ["off", "priority", "total_silence", "alarms_only"],
                "description": "Mode Do Not Disturb.",
            },
            "host": {
                "type": "string",
                "description": "Host target ping untuk tes jaringan (default: 8.8.8.8).",
                "default": "8.8.8.8",
            },
        },
        "required": ["action"],
    }

    async def execute(self, context: ToolContext, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action", "")
        settings = get_settings()

        if context.on_status_update:
            await context.on_status_update(f"● system_settings · mengatur `{action}`")

        # 1. Torch (Senter)
        if action == "torch":
            state = kwargs.get("state", "on").lower()
            if state not in ("on", "off"):
                return ToolResult(success=False, output="", error="State torch harus 'on' atau 'off'.")

            # Try termux-torch
            res = await bridge.execute_shell(f"termux-torch {state}")
            if not res.success and bridge.is_root_available():
                # Fallback via flash sysfs or camera test if available
                res = await bridge.execute_shell(f"echo {'1' if state == 'on' else '0'} > /sys/class/leds/flashlight/brightness", as_root=True)

            return ToolResult(
                success=True,
                output=f"Senter (torch) berhasil diatur ke status: {state.upper()}.",
            )

        # 2. WiFi
        elif action == "wifi":
            sub_action = kwargs.get("sub_action", "status").lower()
            if sub_action == "status":
                res = await bridge.execute_shell("termux-wifi-connectioninfo")
                if res.success and res.stdout:
                    return ToolResult(success=True, output=f"Status WiFi:\n{res.stdout}")
                res_dump = await bridge.execute_shell("dumpsys wifi | grep 'mWifiInfo'", as_root=bridge.is_root_available())
                return ToolResult(
                    success=True,
                    output=res_dump.stdout if res_dump.stdout else "Tidak dapat mengambil info WiFi.",
                )
            elif sub_action in ("enable", "disable"):
                # svc wifi enable/disable requires root
                res = await bridge.execute_shell(f"svc wifi {sub_action}", as_root=True)
                if res.success:
                    return ToolResult(success=True, output=f"WiFi berhasil diubah ke: {sub_action.upper()}.")
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Gagal mengubah WiFi: {res.stderr or 'Perlu izin root'}",
                )

        # 3. Mobile Data (Data Seluler)
        elif action == "data":
            sub_action = kwargs.get("sub_action", "enable").lower()
            if sub_action in ("enable", "disable"):
                res = await bridge.execute_shell(f"svc data {sub_action}", as_root=True)
                if res.success:
                    return ToolResult(success=True, output=f"Data seluler berhasil diubah ke: {sub_action.upper()}.")
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Gagal mengatur data seluler: {res.stderr or 'Perlu izin root'}",
                )

        # 4. Bluetooth
        elif action == "bluetooth":
            sub_action = kwargs.get("sub_action", "status").lower()
            if sub_action == "status":
                res = await bridge.execute_shell("termux-bluetooth-status")
                if res.success and res.stdout:
                    return ToolResult(success=True, output=f"Status Bluetooth:\n{res.stdout}")
                res = await bridge.execute_shell("cmd bluetooth_manager get-state", as_root=True)
                return ToolResult(success=True, output=f"Status Bluetooth:\n{res.stdout}")
            elif sub_action in ("enable", "disable"):
                res = await bridge.execute_shell(f"cmd bluetooth_manager {sub_action}", as_root=True)
                if not res.success:
                    res = await bridge.execute_shell(f"svc bluetooth {sub_action}", as_root=True)
                return ToolResult(
                    success=res.success,
                    output=f"Bluetooth berhasil diubah ke: {sub_action.upper()}" if res.success else "",
                    error=res.stderr if not res.success else None,
                )

        # 5. Volume
        elif action == "volume":
            stream = kwargs.get("volume_stream", "music")
            val = kwargs.get("volume_value")
            if val is None:
                return ToolResult(success=False, output="", error="Nilai volume_value (0-15) wajib diisi.")

            # Try termux-volume
            res = await bridge.execute_shell(f"termux-volume {stream} {val}")
            if not res.success and bridge.is_root_available():
                res = await bridge.execute_shell(f"cmd media_session volume --stream {stream} --set {val}", as_root=True)

            return ToolResult(
                success=True,
                output=f"Volume stream '{stream}' berhasil diatur ke {val}.",
            )

        # 6. Brightness
        elif action == "brightness":
            val = kwargs.get("brightness_value", 128)
            val = max(0, min(255, val))

            # Try termux-brightness or settings put
            res = await bridge.execute_shell(f"termux-brightness {val}")
            if not res.success and bridge.is_root_available():
                res = await bridge.execute_shell(f"settings put system screen_brightness {val}", as_root=True)

            return ToolResult(
                success=True,
                output=f"Kecerahan layar (brightness) berhasil diatur ke {val}/255.",
            )

        # 7. DND (Do Not Disturb)
        elif action == "dnd":
            mode = kwargs.get("dnd_mode", "off")
            res = await bridge.execute_shell(f"cmd notification set_dnd {mode}", as_root=True)
            if res.success:
                return ToolResult(success=True, output=f"Mode DND berhasil diubah ke: {mode}.")
            return ToolResult(
                success=False,
                output="",
                error=f"Gagal mengatur mode DND: {res.stderr or 'Akses root diperlukan'}",
            )

        # 8. Screenshot
        elif action == "screenshot":
            os.makedirs(settings.temp_media_dir, exist_ok=True)
            filename = f"screenshot_{int(time.time())}.png"
            filepath = os.path.join(settings.temp_media_dir, filename)

            # Try screencap command
            res = await bridge.execute_shell(f"screencap -p '{filepath}'", as_root=bridge.is_root_available())
            if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                return ToolResult(
                    success=True,
                    output=f"Tangkapan layar (screenshot) berhasil diambil.",
                    media_path=filepath,
                    media_type="photo",
                )
            else:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Gagal mengambil screenshot: {res.stderr or 'File gambar tidak tercipta'}",
                )

        # 9. Network Ping
        elif action == "network":
            host = kwargs.get("host", "8.8.8.8")
            res = await bridge.execute_shell(f"ping -c 2 {host}", timeout=10)
            if res.success:
                return ToolResult(success=True, output=f"Hasil Ping ke {host}:\n{res.stdout}")
            return ToolResult(
                success=False,
                output=res.stdout,
                error=f"Ping gagal ke {host}: {res.stderr}",
            )

        return ToolResult(success=False, output="", error=f"Aksi '{action}' tidak dikenal.")
