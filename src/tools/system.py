from __future__ import annotations

import json
import logging
import os
import re
import shlex
import time
from typing import Any

from src.config import get_settings
from src.core.android_bridge import bridge
from src.tools.base import BaseTool, ToolContext, ToolResult

logger = logging.getLogger("faf_agent.tools.system")


def _format_size(size_bytes: int) -> str:
    """Format bytes into readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.2f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.2f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


class SystemSettingsTool(BaseTool):
    """Comprehensive Android system control tool: connectivity, display, audio,

    sensors, hardware toggles, power, thermal, and diagnostic metrics.
    """

    name = "system_settings"
    description = (
        "Tool komprehensif kontrol sistem Android: WiFi (status, scan, toggle), Data Seluler, "
        "Bluetooth (status, toggle, paired), Hotspot, Mode Pesawat, GPS/Lokasi, NFC, Volume semua stream, "
        "Mode Dering, DND, Kecerahan layar & Dark Mode, Rotasi layar & Resolusi, Senter (torch), Getar, "
        "Tangkapan layar (screenshot), Sensor hardware, Suhu thermal, Status baterai detail, "
        "serta Diagnostik jaringan & IP. AI WAJIB menggunakan tool ini daripada perintah shell."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "specs",
                    "torch",
                    "wifi",
                    "data",
                    "bluetooth",
                    "hotspot",
                    "airplane",
                    "location",
                    "nfc",
                    "volume",
                    "ringer_mode",
                    "dnd",
                    "brightness",
                    "screen",
                    "vibrate",
                    "screenshot",
                    "sensors",
                    "thermal",
                    "battery",
                    "network",
                    "doctor",
                    "check_tools",
                ],
                "description": "Pengaturan sistem atau diagnosa yang ingin diakses ('doctor' atau 'check_tools' untuk memeriksa kelengkapan instalasi seluruh tools).",
            },
            "sub_action": {
                "type": "string",
                "enum": [
                    "status",
                    "enable",
                    "disable",
                    "scan",
                    "toggle",
                    "wake",
                    "sleep",
                    "metrics",
                    "timeout",
                    "rotation",
                    "dark_mode",
                    "ip_info",
                    "dns_test",
                    "paired_devices",
                ],
                "description": "Sub-aksi untuk modul jaringan, layar, bluetooth, atau wifi.",
                "default": "status",
            },
            "state": {
                "type": "string",
                "enum": ["on", "off"],
                "description": "Digunakan untuk senter (torch) atau toggle on/off.",
            },
            "volume_stream": {
                "type": "string",
                "enum": ["music", "call", "alarm", "ring", "system", "notification"],
                "description": "Tipe stream suara untuk volume (default: music).",
                "default": "music",
            },
            "volume_value": {
                "type": "integer",
                "description": "Nilai volume (0 - 15) atau level persentase.",
            },
            "ringer_mode": {
                "type": "string",
                "enum": ["normal", "vibrate", "silent"],
                "description": "Mode dering ponsel.",
            },
            "brightness_value": {
                "type": "integer",
                "description": "Nilai kecerahan layar manual (0 - 255).",
            },
            "auto_brightness": {
                "type": "boolean",
                "description": "Aktifkan atau nonaktifkan kecerahan otomatis.",
            },
            "screen_timeout_seconds": {
                "type": "integer",
                "description": "Durasi batas waktu layar mati dalam detik (misal: 15, 30, 60, 120, 300).",
            },
            "rotation_mode": {
                "type": "string",
                "enum": ["auto", "portrait", "landscape"],
                "description": "Mode rotasi layar ponsel.",
            },
            "dark_mode_state": {
                "type": "string",
                "enum": ["yes", "no", "auto"],
                "description": "Mode gelap (Dark Theme) Android: 'yes', 'no', atau 'auto'.",
            },
            "dnd_mode": {
                "type": "string",
                "enum": ["off", "priority", "total_silence", "alarms_only"],
                "description": "Mode Jangan Ganggu (Do Not Disturb).",
            },
            "vibrate_duration_ms": {
                "type": "integer",
                "description": "Durasi getar dalam milidetik (default: 500 ms).",
                "default": 500,
            },
            "sensor_name": {
                "type": "string",
                "description": "Nama sensor untuk aksi 'sensors' (misal: 'accelerometer', 'light', 'proximity', 'all').",
                "default": "all",
            },
            "battery_saver_state": {
                "type": "string",
                "enum": ["enable", "disable"],
                "description": "Aktifkan atau matikan mode hemat baterai.",
            },
            "host": {
                "type": "string",
                "description": "Host target untuk aksi 'network' ping atau dns_test (default: 8.8.8.8).",
                "default": "8.8.8.8",
            },
        },
        "required": ["action"],
    }

    async def execute(self, context: ToolContext, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action", "").lower().strip()
        sub_action = kwargs.get("sub_action", "status").lower().strip()
        settings = get_settings()

        if context.on_status_update:
            await context.on_status_update(f"● system_settings · {action} ({sub_action})")

        # -------------------------------------------------------------------
        # 1. Action: SPECS (Full Device Overview)
        # -------------------------------------------------------------------
        if action in ("specs", "status_overview", "device_info"):
            model = await bridge.get_prop("ro.product.model", "Android Device")
            brand = await bridge.get_prop("ro.product.brand", "")
            manufacturer = await bridge.get_prop("ro.product.manufacturer", "")
            android_ver = await bridge.get_prop("ro.build.version.release", "Unknown")
            sdk_ver = await bridge.get_prop("ro.build.version.sdk", "")
            security_patch = await bridge.get_prop("ro.build.version.security_patch", "-")
            board = await bridge.get_prop("ro.board.platform", "-")

            ram = bridge.get_ram_info()
            ram_str = f"{ram['available_mb']} MB bebas dari total {ram['total_mb']} MB ({ram['used_percent']}% digunakan)"

            # Storage via df -h /data or /sdcard
            df_res = await bridge.execute_shell("df -h /data || df -h /sdcard", timeout=3)
            storage_str = "Tersedia"
            if df_res.success and df_res.stdout:
                lines = [l for l in df_res.stdout.splitlines() if l.strip()]
                if len(lines) > 1:
                    parts = lines[-1].split()
                    if len(parts) >= 4:
                        storage_str = f"{parts[3]} bebas dari {parts[1]} ({parts[4]} digunakan)"

            batt = await bridge.get_battery_info()
            batt_str = f"{batt.get('percentage', '?')}% ({batt.get('status', 'Unknown')}, suhu {batt.get('temperature', '?')}°C)"

            is_root = bridge.is_root_available()

            out_lines = [
                f"Informasi Lengkap Perangkat Android:",
                f"• Model Perangkat: {brand} {model} ({manufacturer})",
                f"• Versi Android: Android {android_ver} (API Level {sdk_ver})",
                f"• Patch Keamanan: {security_patch}",
                f"• Chipset / Board: {board}",
                f"• Hak Akses Root: {'Aktif (Superuser Su)' if is_root else 'Tidak Tersedia (Non-Root)'}",
                f"• Memori RAM: {ram_str}",
                f"• Ruang Penyimpanan (/data): {storage_str}",
                f"• Status Baterai: {batt_str}",
            ]
            return ToolResult(success=True, output="\n".join(out_lines))

        # -------------------------------------------------------------------
        # 2. Action: TORCH (Flashlight)
        # -------------------------------------------------------------------
        elif action == "torch":
            state = kwargs.get("state")
            if not state:
                state = "on" if sub_action in ("enable", "on") else ("off" if sub_action in ("disable", "off") else "on")

            res = await bridge.execute_shell(f"termux-torch {state}")
            if not res.success and bridge.is_root_available():
                val = "1" if state == "on" else "0"
                # Sysfs fallback
                res = await bridge.execute_shell(
                    f"for p in /sys/class/leds/*torch*/brightness /sys/class/leds/*flash*/brightness; do [ -f \"$p\" ] && echo {val} > \"$p\"; done",
                    as_root=True,
                )

            return ToolResult(success=True, output=f"Senter (torch) berhasil diatur ke: {state.upper()}.")

        # -------------------------------------------------------------------
        # 3. Action: WIFI
        # -------------------------------------------------------------------
        elif action == "wifi":
            if sub_action in ("enable", "disable"):
                res = await bridge.execute_shell(f"svc wifi {sub_action}", as_root=True)
                if not res.success:
                    res = await bridge.execute_shell(f"cmd wifi set-wifi-enabled {'true' if sub_action == 'enable' else 'false'}", as_root=True)
                if res.success:
                    return ToolResult(success=True, output=f"WiFi berhasil diubah ke: {sub_action.upper()}.")
                return ToolResult(success=False, output="", error=f"Gagal mengubah status WiFi: {res.stderr or 'Akses root diperlukan'}")

            elif sub_action == "scan":
                res = await bridge.execute_shell("termux-wifi-scaninfo")
                if res.success and res.stdout.strip():
                    try:
                        ap_list = json.loads(res.stdout)
                        if isinstance(ap_list, list) and ap_list:
                            lines = [f"Hasil Pindai Jaringan WiFi ({len(ap_list)} AP ditemukan):"]
                            for ap in ap_list[:15]:
                                ssid = ap.get("ssid") or "<Hidden SSID>"
                                rssi = ap.get("rssi", "?")
                                freq = ap.get("frequency_mhz", "?")
                                lines.append(f"• SSID: {ssid} | Sinyal: {rssi} dBm | Frekuensi: {freq} MHz")
                            return ToolResult(success=True, output="\n".join(lines))
                    except Exception:
                        pass
                res_cmd = await bridge.execute_shell("cmd wifi list-scan-results", as_root=bridge.is_root_available())
                return ToolResult(success=True, output=res_cmd.stdout or "Tidak ada hasil pindai WiFi.")

            else:  # status
                res = await bridge.execute_shell("termux-wifi-connectioninfo")
                if res.success and res.stdout.strip():
                    try:
                        info = json.loads(res.stdout)
                        ssid = info.get("ssid") or "Tidak Terhubung"
                        ip = info.get("ip") or "-"
                        rssi = info.get("rssi") or "-"
                        speed = info.get("link_speed_mbps") or "-"
                        bssid = info.get("bssid") or "-"
                        out = (
                            f"Status Koneksi WiFi:\n"
                            f"• SSID: {ssid}\n"
                            f"• IP Address: {ip}\n"
                            f"• Kekuatan Sinyal (RSSI): {rssi} dBm\n"
                            f"• Kecepatan Tautan: {speed} Mbps\n"
                            f"• BSSID: {bssid}"
                        )
                        return ToolResult(success=True, output=out)
                    except Exception:
                        pass

                res_dump = await bridge.execute_shell("dumpsys wifi | grep -E 'mWifiInfo|curState'", as_root=bridge.is_root_available())
                return ToolResult(success=True, output=res_dump.stdout or "WiFi tidak aktif atau tidak terhubung.")

        # -------------------------------------------------------------------
        # 4. Action: DATA (Cellular Mobile Data)
        # -------------------------------------------------------------------
        elif action == "data":
            if sub_action in ("enable", "disable"):
                res = await bridge.execute_shell(f"svc data {sub_action}", as_root=True)
                if res.success:
                    return ToolResult(success=True, output=f"Data seluler berhasil diubah ke: {sub_action.upper()}.")
                return ToolResult(success=False, output="", error=f"Gagal mengatur data seluler: {res.stderr or 'Perlu izin root'}")
            else:
                res = await bridge.execute_shell("dumpsys telephony.registry | grep -E 'mDataConnectionState|mSignalStrength'", as_root=bridge.is_root_available())
                return ToolResult(success=True, output=f"Status Data Seluler:\n{res.stdout or 'Aktif'}")

        # -------------------------------------------------------------------
        # 5. Action: BLUETOOTH
        # -------------------------------------------------------------------
        elif action == "bluetooth":
            if sub_action in ("enable", "disable"):
                res = await bridge.execute_shell(f"cmd bluetooth_manager {sub_action}", as_root=True)
                if not res.success:
                    res = await bridge.execute_shell(f"svc bluetooth {sub_action}", as_root=True)
                return ToolResult(
                    success=res.success,
                    output=f"Bluetooth berhasil diubah ke: {sub_action.upper()}." if res.success else "",
                    error=res.stderr if not res.success else None,
                )
            elif sub_action == "paired_devices":
                res = await bridge.execute_shell("dumpsys bluetooth_manager | grep -A 10 'Bonded devices'", as_root=bridge.is_root_available())
                return ToolResult(success=True, output=res.stdout or "Tidak ada perangkat Bluetooth yang terpasang.")
            else:  # status
                res = await bridge.execute_shell("termux-bluetooth-status")
                if res.success and res.stdout.strip():
                    return ToolResult(success=True, output=f"Status Bluetooth:\n{res.stdout}")
                res = await bridge.execute_shell("cmd bluetooth_manager get-state", as_root=bridge.is_root_available())
                return ToolResult(success=True, output=f"Status Bluetooth: {res.stdout.strip()}")

        # -------------------------------------------------------------------
        # 6. Action: HOTSPOT (Tethering)
        # -------------------------------------------------------------------
        elif action == "hotspot":
            if sub_action in ("enable", "start"):
                res = await bridge.execute_shell("cmd connectivity tethering start wifi", as_root=True)
                return ToolResult(success=res.success, output="Hotspot WiFi berhasil diaktifkan." if res.success else "", error=res.stderr)
            elif sub_action in ("disable", "stop"):
                res = await bridge.execute_shell("cmd connectivity tethering stop wifi", as_root=True)
                return ToolResult(success=res.success, output="Hotspot WiFi berhasil dinonaktifkan." if res.success else "", error=res.stderr)
            else:
                res = await bridge.execute_shell("dumpsys connectivity tethering | grep -E 'mTetherMode|mActiveTethering'", as_root=bridge.is_root_available())
                return ToolResult(success=True, output=res.stdout or "Status Hotspot diperiksa.")

        # -------------------------------------------------------------------
        # 7. Action: AIRPLANE (Airplane Mode)
        # -------------------------------------------------------------------
        elif action == "airplane":
            if sub_action in ("enable", "disable"):
                val = "1" if sub_action == "enable" else "0"
                await bridge.execute_shell(f"settings put global airplane_mode_on {val}", as_root=True)
                res = await bridge.execute_shell(
                    f"am broadcast -a android.intent.action.AIRPLANE_MODE --ez state {'true' if val == '1' else 'false'}",
                    as_root=True,
                )
                return ToolResult(success=True, output=f"Mode Pesawat (Airplane Mode) diatur ke: {sub_action.upper()}.")
            else:
                res = await bridge.execute_shell("settings get global airplane_mode_on")
                is_on = res.stdout.strip() == "1"
                return ToolResult(success=True, output=f"Mode Pesawat saat ini: {'AKTIF' if is_on else 'TIDAK AKTIF'}.")

        # -------------------------------------------------------------------
        # 8. Action: LOCATION / GPS
        # -------------------------------------------------------------------
        elif action in ("location", "gps"):
            if sub_action in ("enable", "disable"):
                # mode 3 = HIGH_ACCURACY, 0 = OFF
                val = "3" if sub_action == "enable" else "0"
                res = await bridge.execute_shell(f"settings put secure location_mode {val}", as_root=True)
                return ToolResult(success=True, output=f"Layanan Lokasi / GPS diatur ke: {sub_action.upper()}.")
            else:
                res = await bridge.execute_shell("settings get secure location_mode")
                mode_val = res.stdout.strip()
                label = "AKTIF (High Accuracy)" if mode_val in ("3", "1", "2") else "NONAKTIF"
                return ToolResult(success=True, output=f"Status Lokasi (GPS): {label} (mode {mode_val}).")

        # -------------------------------------------------------------------
        # 9. Action: NFC
        # -------------------------------------------------------------------
        elif action == "nfc":
            if sub_action in ("enable", "disable"):
                res = await bridge.execute_shell(f"svc nfc {sub_action}", as_root=True)
                return ToolResult(success=res.success, output=f"NFC diatur ke: {sub_action.upper()}." if res.success else "", error=res.stderr)
            else:
                res = await bridge.execute_shell("dumpsys nfc | grep -E 'mState|NfcState'", as_root=bridge.is_root_available())
                return ToolResult(success=True, output=res.stdout or "Status NFC diperiksa.")

        # -------------------------------------------------------------------
        # 10. Action: VOLUME
        # -------------------------------------------------------------------
        elif action == "volume":
            stream = kwargs.get("volume_stream", "music").lower()
            val = kwargs.get("volume_value")

            if val is not None:
                val = max(0, min(15, int(val)))
                res = await bridge.execute_shell(f"termux-volume {stream} {val}")
                if not res.success and bridge.is_root_available():
                    res = await bridge.execute_shell(f"cmd media_session volume --stream {stream} --set {val}", as_root=True)
                return ToolResult(success=True, output=f"Volume stream '{stream}' berhasil diatur ke: {val}/15.")
            else:
                # Get current volume info
                res = await bridge.execute_shell("termux-volume")
                if res.success and res.stdout.strip():
                    try:
                        vol_list = json.loads(res.stdout)
                        lines = ["Status Volume Suara Perangkat:"]
                        for v in vol_list:
                            lines.append(f"• Stream {v.get('stream')}: {v.get('volume')}/{v.get('max_volume')}")
                        return ToolResult(success=True, output="\n".join(lines))
                    except Exception:
                        pass
                res_dump = await bridge.execute_shell("dumpsys audio | grep -A 4 'STREAM_MUSIC'", as_root=bridge.is_root_available())
                return ToolResult(success=True, output=res_dump.stdout or "Volume diperiksa.")

        # -------------------------------------------------------------------
        # 11. Action: RINGER_MODE
        # -------------------------------------------------------------------
        elif action == "ringer_mode":
            mode = kwargs.get("ringer_mode", "normal").lower()
            # Try termux-volume ringer
            res = await bridge.execute_shell(f"termux-volume ringer {mode}")
            if not res.success and bridge.is_root_available():
                # cmd audio set-ringer-mode 2 (normal), 1 (vibrate), 0 (silent)
                mode_int = "2" if mode == "normal" else ("1" if mode == "vibrate" else "0")
                res = await bridge.execute_shell(f"cmd audio set-ringer-mode {mode_int}", as_root=True)
            return ToolResult(success=True, output=f"Mode dering ponsel diatur ke: {mode.upper()}.")

        # -------------------------------------------------------------------
        # 12. Action: DND (Do Not Disturb)
        # -------------------------------------------------------------------
        elif action == "dnd":
            mode = kwargs.get("dnd_mode", "off").lower()
            res = await bridge.execute_shell(f"cmd notification set_dnd {mode}", as_root=True)
            if res.success:
                return ToolResult(success=True, output=f"Mode Jangan Ganggu (DND) berhasil diubah ke: {mode.upper()}.")
            return ToolResult(success=False, output="", error=f"Gagal mengatur mode DND: {res.stderr or 'Izin root diperlukan'}")

        # -------------------------------------------------------------------
        # 13. Action: BRIGHTNESS
        # -------------------------------------------------------------------
        elif action == "brightness":
            auto_b = kwargs.get("auto_brightness")
            if auto_b is not None:
                val_auto = "1" if auto_b else "0"
                await bridge.execute_shell(f"settings put system screen_brightness_mode {val_auto}", as_root=bridge.is_root_available())
                return ToolResult(success=True, output=f"Kecerahan otomatis diatur ke: {'AKTIF' if auto_b else 'NONAKTIF'}.")

            val = kwargs.get("brightness_value")
            if val is not None:
                val = max(0, min(255, int(val)))
                res = await bridge.execute_shell(f"termux-brightness {val}")
                if not res.success and bridge.is_root_available():
                    res = await bridge.execute_shell(f"settings put system screen_brightness {val}", as_root=True)
                return ToolResult(success=True, output=f"Kecerahan layar (brightness) berhasil diatur ke {val}/255.")
            else:
                res = await bridge.execute_shell("settings get system screen_brightness")
                b_val = res.stdout.strip()
                return ToolResult(success=True, output=f"Kecerahan layar saat ini: {b_val}/255.")

        # -------------------------------------------------------------------
        # 14. Action: SCREEN (Display & Window Control)
        # -------------------------------------------------------------------
        elif action == "screen":
            if sub_action == "wake":
                await bridge.execute_shell("input keyevent 224")  # KEYCODE_WAKEUP
                return ToolResult(success=True, output="Layar ponsel berhasil dibangunkan (Wake).")

            elif sub_action == "sleep":
                await bridge.execute_shell("input keyevent 223")  # KEYCODE_SLEEP
                return ToolResult(success=True, output="Layar ponsel berhasil dimatikan (Sleep).")

            elif sub_action == "metrics":
                res_size = await bridge.execute_shell("wm size")
                res_density = await bridge.execute_shell("wm density")
                return ToolResult(
                    success=True,
                    output=f"Metrik Layar Ponsel:\n• Resolusi: {res_size.stdout.strip()}\n• Kerapatan (DPI): {res_density.stdout.strip()}",
                )

            elif sub_action == "timeout":
                secs = kwargs.get("screen_timeout_seconds")
                if secs is not None:
                    ms = int(secs) * 1000
                    await bridge.execute_shell(f"settings put system screen_off_timeout {ms}", as_root=bridge.is_root_available())
                    return ToolResult(success=True, output=f"Batas waktu layar mati (screen timeout) diatur ke {secs} detik.")
                else:
                    res = await bridge.execute_shell("settings get system screen_off_timeout")
                    ms_val = int(res.stdout.strip()) if res.stdout.strip().isdigit() else 30000
                    return ToolResult(success=True, output=f"Screen timeout saat ini: {ms_val // 1000} detik.")

            elif sub_action == "rotation":
                rot = kwargs.get("rotation_mode", "auto").lower()
                if rot == "auto":
                    await bridge.execute_shell("settings put system accelerometer_rotation 1", as_root=bridge.is_root_available())
                    return ToolResult(success=True, output="Rotasi layar diatur ke: OTOMATIS (Auto-Rotate ON).")
                else:
                    await bridge.execute_shell("settings put system accelerometer_rotation 0", as_root=bridge.is_root_available())
                    val_user = "0" if rot == "portrait" else "1"
                    await bridge.execute_shell(f"settings put system user_rotation {val_user}", as_root=bridge.is_root_available())
                    return ToolResult(success=True, output=f"Rotasi layar dikunci ke: {rot.upper()}.")

            elif sub_action == "dark_mode":
                dm_state = kwargs.get("dark_mode_state", "yes").lower()
                res = await bridge.execute_shell(f"cmd uimode night {dm_state}", as_root=True)
                return ToolResult(success=res.success, output=f"Mode Gelap (Dark Mode) diatur ke: {dm_state.upper()}." if res.success else "", error=res.stderr)

            else:  # check screen interactive state
                res = await bridge.execute_shell("dumpsys power | grep 'mIsPowered'", as_root=bridge.is_root_available())
                res_wake = await bridge.execute_shell("dumpsys power | grep 'mHoldingDisplaySuspendBlocker'", as_root=bridge.is_root_available())
                return ToolResult(success=True, output=f"Status Layar:\n{res.stdout}\n{res_wake.stdout}".strip())

        # -------------------------------------------------------------------
        # 15. Action: VIBRATE
        # -------------------------------------------------------------------
        elif action == "vibrate":
            dur = kwargs.get("vibrate_duration_ms", 500)
            res = await bridge.execute_shell(f"termux-vibrate -d {int(dur)}")
            if not res.success and bridge.is_root_available():
                res = await bridge.execute_shell(f"cmd vibrator vibrate {int(dur)}", as_root=True)
            return ToolResult(success=True, output=f"Perangkat digetarkan selama {dur} milidetik.")

        # -------------------------------------------------------------------
        # 16. Action: SCREENSHOT
        # -------------------------------------------------------------------
        elif action == "screenshot":
            os.makedirs(settings.temp_media_dir, exist_ok=True)
            filename = f"screenshot_{int(time.time())}.png"
            filepath = os.path.join(settings.temp_media_dir, filename)

            res = await bridge.execute_shell(f"screencap -p '{filepath}'", as_root=bridge.is_root_available())
            if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                return ToolResult(
                    success=True,
                    output=f"Tangkapan layar (screenshot) berhasil diambil.",
                    media_path=filepath,
                    media_type="photo",
                )
            return ToolResult(success=False, output="", error=f"Gagal mengambil screenshot: {res.stderr or 'File gambar kosong'}")

        # -------------------------------------------------------------------
        # 17. Action: SENSORS
        # -------------------------------------------------------------------
        elif action == "sensors":
            s_name = kwargs.get("sensor_name", "all")
            flag = f"-s {shlex.quote(s_name)} -n 1" if s_name != "all" else "-l"
            res = await bridge.execute_shell(f"termux-sensor {flag}", timeout=6)
            if res.success and res.stdout.strip():
                return ToolResult(success=True, output=f"Data Sensor ({s_name}):\n{res.stdout.strip()}")
            return ToolResult(success=True, output="Informasi sensor tidak tersedia atau izin Termux:API sensor belum diberikan.")

        # -------------------------------------------------------------------
        # 18. Action: THERMAL (Temperature)
        # -------------------------------------------------------------------
        elif action == "thermal":
            res = await bridge.execute_shell(
                "cat /sys/class/thermal/thermal_zone*/type 2>/dev/null; echo '---'; cat /sys/class/thermal/thermal_zone*/temp 2>/dev/null",
                as_root=bridge.is_root_available(),
            )
            if res.success and "---" in res.stdout:
                parts = res.stdout.split("---")
                types = [t.strip() for t in parts[0].splitlines() if t.strip()]
                temps = [t.strip() for t in parts[1].splitlines() if t.strip()]
                lines = ["Suhu Sensor Termal Perangkat:"]
                for i in range(min(len(types), len(temps))):
                    try:
                        deg_c = float(temps[i]) / 1000.0 if float(temps[i]) > 1000 else float(temps[i])
                        if 10.0 <= deg_c <= 110.0:
                            lines.append(f"• {types[i]}: {deg_c:.1f}°C")
                    except Exception:
                        pass
                if len(lines) > 1:
                    return ToolResult(success=True, output="\n".join(lines[:12]))

            res_batt = await bridge.get_battery_info()
            return ToolResult(success=True, output=f"Suhu Baterai: {res_batt.get('temperature', '?')}°C.")

        # -------------------------------------------------------------------
        # 19. Action: BATTERY
        # -------------------------------------------------------------------
        elif action == "battery":
            bs_state = kwargs.get("battery_saver_state")
            if bs_state:
                val = "1" if bs_state == "enable" else "0"
                res = await bridge.execute_shell(f"cmd power set-mode {val}", as_root=True)
                return ToolResult(success=res.success, output=f"Mode Hemat Baterai (Battery Saver) diatur ke: {bs_state.upper()}." if res.success else "", error=res.stderr)

            info = await bridge.get_battery_info()
            out = (
                f"Status Rinci Baterai Ponsel:\n"
                f"• Persentase Daya: {info.get('percentage', '?')}%\n"
                f"• Status Pengisian: {info.get('status', 'Unknown')}\n"
                f"• Sumber Daya: {info.get('plugged', 'None')}\n"
                f"• Suhu Baterai: {info.get('temperature', '?')}°C\n"
                f"• Kesehatan Baterai: {info.get('health', 'Good')}"
            )
            return ToolResult(success=True, output=out)

        # -------------------------------------------------------------------
        # 20. Action: NETWORK (Diagnostics & IP Info)
        # -------------------------------------------------------------------
        elif action == "network":
            if sub_action == "ip_info":
                res = await bridge.execute_shell("ip -br addr || ifconfig", timeout=4)
                return ToolResult(success=True, output=f"Daftar Alamat IP & Antarmuka Jaringan:\n{res.stdout}")

            elif sub_action == "dns_test":
                host = kwargs.get("host", "google.com")
                res = await bridge.execute_shell(f"nslookup {shlex.quote(host)} || getent hosts {shlex.quote(host)}", timeout=5)
                return ToolResult(success=True, output=f"Hasil Uji DNS ke {host}:\n{res.stdout}")

            else:  # ping
                host = kwargs.get("host", "8.8.8.8")
                res = await bridge.execute_shell(f"ping -c 3 {shlex.quote(host)}", timeout=10)
                if res.success:
                    return ToolResult(success=True, output=f"Hasil Ping ke {host}:\n{res.stdout}")
                return ToolResult(success=False, output=res.stdout, error=f"Ping gagal ke {host}: {res.stderr}")

        # -------------------------------------------------------------------
        # 21. Action: DOCTOR / CHECK_TOOLS (System Tool Diagnostics)
        # -------------------------------------------------------------------
        elif action in ("doctor", "check_tools", "check_dependencies", "check_deps"):
            from src.core.diagnostics import check_all_dependencies, format_dependency_report
            diag_results = check_all_dependencies()
            return ToolResult(success=True, output=format_dependency_report(diag_results))

        return ToolResult(success=False, output="", error=f"Aksi system_settings '{action}' tidak dikenal.")
