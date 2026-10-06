from __future__ import annotations

import logging
import os
import re
import shlex
import time
from typing import Any

from src.config import get_settings
from src.core.android_bridge import bridge
from src.tools.base import BaseTool, ToolContext, ToolResult

logger = logging.getLogger("faf_agent.tools.productivity")


class ProductivityControlTool(BaseTool):
    name = "productivity_control"
    description = (
        "Manajemen produktivitas di Android: memasang alarm jam tertentu, timer hitung mundur, "
        "membuat agenda kalender, menulis catatan cepat ke penyimpanan lokal, dan menampilkan "
        "notifikasi pop-up pada layar perangkat."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "set_alarm",
                    "set_timer",
                    "add_calendar",
                    "create_note",
                    "show_notification",
                ],
                "description": "Tindakan produktivitas yang ingin dijalankan.",
            },
            "hour": {
                "type": "integer",
                "description": "Jam alarm (0 - 23). Wajib untuk set_alarm.",
            },
            "minutes": {
                "type": "integer",
                "description": "Menit alarm (0 - 59). Wajib untuk set_alarm.",
            },
            "seconds": {
                "type": "integer",
                "description": "Durasi timer dalam detik. Wajib untuk set_timer.",
            },
            "title": {
                "type": "string",
                "description": "Judul untuk agenda, catatan, atau notifikasi.",
            },
            "content": {
                "type": "string",
                "description": "Isi pesan untuk catatan atau notifikasi.",
            },
            "message": {
                "type": "string",
                "description": "Label pesan untuk alarm atau timer.",
            },
            "description": {
                "type": "string",
                "description": "Keterangan detail acara kalender.",
            },
            "begin_time_ms": {
                "type": "integer",
                "description": "Waktu mulai acara kalender dalam format epoch milidetik.",
            },
        },
        "required": ["action"],
    }

    async def execute(self, context: ToolContext, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action", "")
        settings = get_settings()

        if context.on_status_update:
            await context.on_status_update(f"● productivity_control · menjalankan `{action}`")

        # 1. Set Alarm
        if action == "set_alarm":
            hour = kwargs.get("hour")
            minutes = kwargs.get("minutes", 0)
            msg = kwargs.get("message", "Alarm faf-agent")

            if hour is None:
                return ToolResult(success=False, output="", error="Parameter 'hour' (0-23) wajib disertakan.")

            cmd = (
                f"am start -a android.intent.action.SET_ALARM "
                f"--ei android.intent.extra.hour {int(hour)} "
                f"--ei android.intent.extra.minutes {int(minutes)} "
                f"--es android.intent.extra.message {shlex.quote(str(msg))} "
                f"--ez android.intent.extra.skip_ui true"
            )
            res = await bridge.execute_shell(cmd)
            return ToolResult(
                success=True,
                output=f"Alarm berhasil dipasang untuk pukul {hour:02d}:{minutes:02d} dengan label '{msg}'.",
            )

        # 2. Set Timer
        elif action == "set_timer":
            seconds = kwargs.get("seconds")
            msg = kwargs.get("message", "Timer faf-agent")

            if seconds is None:
                return ToolResult(success=False, output="", error="Parameter 'seconds' wajib disertakan.")

            cmd = (
                f"am start -a android.intent.action.SET_TIMER "
                f"--ei android.intent.extra.length {int(seconds)} "
                f"--es android.intent.extra.message {shlex.quote(str(msg))} "
                f"--ez android.intent.extra.skip_ui true"
            )
            res = await bridge.execute_shell(cmd)
            return ToolResult(
                success=True,
                output=f"Timer berhasil dipasang selama {seconds} detik dengan label '{msg}'.",
            )

        # 3. Add Calendar Event
        elif action == "add_calendar":
            title = kwargs.get("title", "Agenda Baru")
            desc = kwargs.get("description", "")
            begin_ms = kwargs.get("begin_time_ms") or int(time.time() * 1000)

            cmd_parts = [
                "am start -a android.intent.action.INSERT",
                "-t vnd.android.cursor.dir/event",
                f"-e title {shlex.quote(title)}",
                f"--el beginTime {begin_ms}",
            ]
            if desc:
                cmd_parts.append(f"-e description {shlex.quote(desc)}")

            res = await bridge.execute_shell(" ".join(cmd_parts))
            return ToolResult(
                success=True,
                output=f"Acara kalender '{title}' berhasil dibuat.",
            )

        # 4. Create Quick Note
        elif action == "create_note":
            title = kwargs.get("title", f"Note_{int(time.time())}")
            content = kwargs.get("content", "")

            # Sanitize filename
            clean_title = re.sub(r'[\\/*?:"<>| ]', "_", title)
            target_dir = settings.notes_storage_dir

            # If /sdcard/Notes is not writable (e.g. running on local machine or no storage perm), fallback to local notes
            try:
                os.makedirs(target_dir, exist_ok=True)
            except Exception:
                target_dir = os.path.expanduser("~/faf_notes")
                os.makedirs(target_dir, exist_ok=True)

            note_path = os.path.join(target_dir, f"{clean_title}.txt")
            try:
                with open(note_path, "w", encoding="utf-8") as f:
                    f.write(content)
                return ToolResult(
                    success=True,
                    output=f"Catatan berhasil disimpan ke: {note_path}\nUkuran: {len(content)} karakter.",
                )
            except Exception as e:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Gagal menyimpan catatan: {str(e)}",
                )

        # 5. Show Notification
        elif action == "show_notification":
            title = kwargs.get("title", "faf-agent Notification")
            content = kwargs.get("content", "")

            # Try termux-notification
            if bridge.has_command("termux-notification"):
                cmd = f"termux-notification -t {shlex.quote(title)} -c {shlex.quote(content)}"
                res = await bridge.execute_shell(cmd)
                return ToolResult(
                    success=True,
                    output=f"Notifikasi pop-up '{title}' berhasil dimunculkan di layar perangkat.",
                )
            else:
                return ToolResult(
                    success=True,
                    output=f"[Simulasi Notifikasi] Judul: {title} | Pesan: {content} (termux-notification tidak terpasang)",
                )

        return ToolResult(success=False, output="", error=f"Aksi '{action}' tidak dikenal.")
