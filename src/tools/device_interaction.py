from __future__ import annotations

import logging
import re
import shlex
import xml.etree.ElementTree as ET
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
        "menginspeksi elemen hierarki UI layar dan mencari tombol/teks untuk tap otomatis (inspect_ui), "
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
                    "inspect_ui",
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
            "search_text": {
                "type": "string",
                "description": "Kata kunci teks atau label elemen antarmuka yang dicari untuk aksi 'inspect_ui' (contoh: 'Check In', 'Kirim', 'Beli').",
            },
            "resource_id": {
                "type": "string",
                "description": "Resource ID elemen antarmuka yang dicari untuk aksi 'inspect_ui' (contoh: 'com.whatsapp:id/send').",
            },
            "auto_tap": {
                "type": "boolean",
                "description": "Jika true pada aksi 'inspect_ui', langsung ketuk (tap) elemen pertama yang cocok secara otomatis.",
                "default": False,
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

        # -------------------------------------------------------------------
        # 11. Action: INSPECT_UI
        # -------------------------------------------------------------------
        elif action == "inspect_ui":
            search_text = kwargs.get("search_text", "").strip().lower()
            resource_id = kwargs.get("resource_id", "").strip().lower()
            auto_tap = kwargs.get("auto_tap", False)

            dump_path = "/data/local/tmp/faf_window_dump.xml"
            # 1. Run uiautomator dump
            res_dump = await bridge.execute_shell(
                f"uiautomator dump {dump_path} || cmd uiautomator dump {dump_path}",
                as_root=bridge.is_root_available(),
                timeout=12,
            )

            # 2. Read dump file
            res_cat = await bridge.execute_shell(
                f"cat {dump_path}",
                as_root=bridge.is_root_available(),
                timeout=5,
            )
            xml_content = res_cat.stdout.strip() if res_cat.success else ""

            if not xml_content or "<hierarchy" not in xml_content:
                return ToolResult(
                    success=False,
                    output="",
                    error="Gagal mengambil hierarki antarmuka layar (UI dump). Pastikan layar aktif atau berikan izin Root/ADB.",
                )

            try:
                root = ET.fromstring(xml_content)
            except Exception as e:
                logger.warning(f"Failed to parse uiautomator XML: {e}")
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Gagal mem-parse XML hierarki UI layar: {e}",
                )

            matched_elements: list[dict[str, Any]] = []
            bounds_pattern = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")

            for node in root.iter("node"):
                text = node.attrib.get("text", "")
                content_desc = node.attrib.get("content-desc", "")
                res_id = node.attrib.get("resource-id", "")
                cls_name = node.attrib.get("class", "").split(".")[-1]
                bounds_str = node.attrib.get("bounds", "")
                clickable = node.attrib.get("clickable", "false") == "true"

                m = bounds_pattern.match(bounds_str)
                if not m:
                    continue

                x1, y1, x2, y2 = map(int, m.groups())
                if x2 <= x1 or y2 <= y1:
                    continue

                cx = (x1 + x2) // 2
                cy = (y1 + y2) // 2

                is_match = False
                if search_text:
                    if (search_text in text.lower()) or (search_text in content_desc.lower()):
                        is_match = True
                elif resource_id:
                    if resource_id in res_id.lower():
                        is_match = True
                else:
                    if text or content_desc or clickable:
                        is_match = True

                if is_match:
                    display_label = text or content_desc or (res_id.split("/")[-1] if "/" in res_id else res_id) or cls_name
                    matched_elements.append({
                        "label": display_label,
                        "text": text,
                        "content_desc": content_desc,
                        "resource_id": res_id,
                        "class": cls_name,
                        "center": (cx, cy),
                        "bounds": (x1, y1, x2, y2),
                        "clickable": clickable,
                    })

            if not matched_elements:
                query_desc = f"dengan filter '{search_text or resource_id}'" if (search_text or resource_id) else ""
                return ToolResult(
                    success=True,
                    output=f"Tidak ditemukan elemen antarmuka yang cocok pada layar saat ini {query_desc}.".strip(),
                )

            if auto_tap:
                target = matched_elements[0]
                tcx, tcy = target["center"]
                res_tap = await bridge.execute_shell(f"input tap {tcx} {tcy}")
                target_label = target["label"]
                return ToolResult(
                    success=True,
                    output=f"Elemen '{target_label}' ditemukan pada posisi ({tcx}, {tcy}) dan berhasil diketuk (tap otomatis).",
                )

            lines = [f"Elemen Antarmuka Layar Terdeteksi ({len(matched_elements)} elemen):"]
            for el in matched_elements[:20]:
                cx, cy = el["center"]
                clk = " [dapat diklik]" if el["clickable"] else ""
                lines.append(f"• {el['label']} ({el['class']}){clk} -> Koordinat: ({cx}, {cy})")

            return ToolResult(success=True, output="\n".join(lines))

        return ToolResult(success=False, output="", error=f"Aksi device_interaction '{action}' tidak dikenal.")
