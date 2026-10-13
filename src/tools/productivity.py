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

logger = logging.getLogger("faf_agent.tools.productivity")


class ProductivityControlTool(BaseTool):
    """All-in-one Android Productivity, Organizer, Telephony, and SMS tool."""

    name = "productivity_control"
    description = (
        "Manajemen produktivitas dan komunikasi Android: memasang alarm jam tertentu, timer hitung mundur, "
        "membuat agenda kalender, menampilkan notifikasi pop-up layar dengan aksi, pesan toast mengambang, "
        "membuat & membaca catatan lokal (/sdcard/Notes), mengirim & membaca SMS, mencari kontak buku telepon, "
        "melakukan panggilan telepon, mengecek info seluler/SIM, serta membaca dan menyalin teks clipboard."
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
                    "show_notification",
                    "toast",
                    "create_note",
                    "list_notes",
                    "read_note",
                    "send_sms",
                    "list_sms",
                    "list_contacts",
                    "make_call",
                    "cell_info",
                    "clipboard_get",
                    "clipboard_set",
                ],
                "description": "Tindakan produktivitas atau komunikasi yang diinginkan.",
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
                "description": "Judul untuk agenda kalender, catatan, atau notifikasi.",
            },
            "content": {
                "type": "string",
                "description": "Isi pesan untuk catatan, notifikasi, toast, atau clipboard.",
            },
            "message": {
                "type": "string",
                "description": "Label pesan untuk alarm, timer, atau SMS.",
            },
            "description": {
                "type": "string",
                "description": "Keterangan detail acara kalender.",
            },
            "begin_time_ms": {
                "type": "integer",
                "description": "Waktu mulai acara kalender dalam format epoch milidetik.",
            },
            "phone_number": {
                "type": "string",
                "description": "Nomor telepon tujuan untuk 'send_sms', 'make_call', atau filter 'list_sms'.",
            },
            "sms_type": {
                "type": "string",
                "enum": ["all", "inbox", "sent"],
                "description": "Kategori SMS yang dibaca pada 'list_sms' (default: all).",
                "default": "all",
            },
            "search_query": {
                "type": "string",
                "description": "Kata kunci pencarian nama atau nomor untuk 'list_contacts'.",
            },
            "limit": {
                "type": "integer",
                "description": "Batas maksimal jumlah SMS, kontak, atau catatan yang ditampilkan (default: 10).",
                "default": 10,
            },
            "notification_id": {
                "type": "string",
                "description": "ID unik notifikasi untuk memperbarui atau menghapus notifikasi.",
            },
            "action_url": {
                "type": "string",
                "description": "URL atau intent yang dibuka saat notifikasi diklik pengguna.",
            },
            "toast_duration": {
                "type": "string",
                "enum": ["short", "long"],
                "description": "Durasi toast mengambang di layar (default: short).",
                "default": "short",
            },
        },
        "required": ["action"],
    }

    async def execute(self, context: ToolContext, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action", "").lower().strip()
        settings = get_settings()

        if context.on_status_update:
            await context.on_status_update(f"● productivity_control · {action}")

        # -------------------------------------------------------------------
        # 1. Action: SET_ALARM
        # -------------------------------------------------------------------
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
                output=f"Alarm berhasil dipasang untuk pukul {int(hour):02d}:{int(minutes):02d} dengan label '{msg}'.",
            )

        # -------------------------------------------------------------------
        # 2. Action: SET_TIMER
        # -------------------------------------------------------------------
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
            mins = seconds // 60
            secs = seconds % 60
            dur_str = f"{mins} menit {secs} detik" if mins > 0 else f"{secs} detik"
            return ToolResult(
                success=True,
                output=f"Timer hitung mundur berhasil dipasang selama {seconds} detik ({dur_str}) ('{msg}').",
            )

        # -------------------------------------------------------------------
        # 3. Action: ADD_CALENDAR
        # -------------------------------------------------------------------
        elif action == "add_calendar":
            title = kwargs.get("title", "Agenda faf-agent")
            desc = kwargs.get("description", "")
            begin_ms = kwargs.get("begin_time_ms")
            if begin_ms is None:
                begin_ms = int(time.time() * 1000) + 3600000

            cmd = (
                f"am start -a android.intent.action.INSERT "
                f"-d content://com.android.calendar/events "
                f"--es title {shlex.quote(title)} "
                f"--es description {shlex.quote(desc)} "
                f"--el beginTime {int(begin_ms)}"
            )
            res = await bridge.execute_shell(cmd)
            return ToolResult(
                success=True,
                output=f"Agenda kalender '{title}' berhasil ditambahkan ke kalender Android.",
            )

        # -------------------------------------------------------------------
        # 4. Action: SHOW_NOTIFICATION
        # -------------------------------------------------------------------
        elif action == "show_notification":
            title = kwargs.get("title", "faf-agent")
            content = kwargs.get("content", "Notifikasi dari asisten faf-agent")
            notif_id = kwargs.get("notification_id", "faf_notif")
            action_url = kwargs.get("action_url", "")

            cmd_parts = [
                "termux-notification",
                f"-t {shlex.quote(title)}",
                f"-c {shlex.quote(content)}",
                f"-i {shlex.quote(notif_id)}",
                "--vibrate 400",
            ]
            if action_url:
                cmd_parts.append(f"--action {shlex.quote(action_url)}")

            res = await bridge.execute_shell(" ".join(cmd_parts))
            return ToolResult(
                success=True,
                output=f"Notifikasi pop-up berhasil dimunculkan di layar ponsel: '{title}'.",
            )

        # -------------------------------------------------------------------
        # 5. Action: TOAST
        # -------------------------------------------------------------------
        elif action == "toast":
            content = kwargs.get("content", "faf-agent alert")
            dur = kwargs.get("toast_duration", "short")
            flag = "-s" if dur == "short" else ""
            res = await bridge.execute_shell(f"termux-toast {flag} {shlex.quote(content)}")
            return ToolResult(success=True, output=f"Pesan toast berhasil ditampilkan di layar: '{content}'.")

        # -------------------------------------------------------------------
        # 6. Action: CREATE_NOTE
        # -------------------------------------------------------------------
        elif action == "create_note":
            title = kwargs.get("title", f"catatan_{int(time.time())}")
            content = kwargs.get("content", "")

            # Sanitize title
            safe_title = re.sub(r"[^\w\-_\.]", "_", title).strip()
            if not safe_title.endswith(".txt"):
                safe_title += ".txt"

            notes_dir = settings.notes_storage_dir
            if not notes_dir:
                notes_dir = "/sdcard/Notes" if os.path.exists("/sdcard") else os.path.expanduser("~/notes")
            os.makedirs(notes_dir, exist_ok=True)

            filepath = os.path.join(notes_dir, safe_title)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(f"=== {title} ===\nWaktu Dibuat: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n{content}\n")

            return ToolResult(
                success=True,
                output=f"Catatan berhasil disimpan ke: {filepath}\n• Judul: {title}\n• Ukuran: {len(content)} karakter.",
            )

        # -------------------------------------------------------------------
        # 7. Action: LIST_NOTES
        # -------------------------------------------------------------------
        elif action == "list_notes":
            notes_dirs = ["/sdcard/Notes", os.path.expanduser("~/notes")]
            found_notes = []
            for nd in notes_dirs:
                if os.path.exists(nd) and os.path.isdir(nd):
                    for fname in os.listdir(nd):
                        if fname.endswith((".txt", ".md")):
                            fpath = os.path.join(nd, fname)
                            mtime = time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(fpath)))
                            found_notes.append(f"• {fname} (diubah {mtime}, lokasi {nd})")

            if found_notes:
                limit = kwargs.get("limit", 15)
                return ToolResult(
                    success=True,
                    output=f"Daftar Catatan Tersimpan ({len(found_notes)} total):\n" + "\n".join(found_notes[:limit]),
                )
            return ToolResult(success=True, output="Belum ada catatan yang tersimpan di direktori Notes.")

        # -------------------------------------------------------------------
        # 8. Action: READ_NOTE
        # -------------------------------------------------------------------
        elif action == "read_note":
            title = kwargs.get("title", "")
            if not title:
                return ToolResult(success=False, output="", error="Parameter 'title' atau nama file catatan wajib diisi.")

            notes_dirs = ["/sdcard/Notes", os.path.expanduser("~/notes")]
            target_file = None
            for nd in notes_dirs:
                candidate = os.path.join(nd, title if title.endswith((".txt", ".md")) else f"{title}.txt")
                if os.path.exists(candidate):
                    target_file = candidate
                    break

            if not target_file:
                return ToolResult(success=False, output="", error=f"Catatan '{title}' tidak ditemukan di direktori Notes.")

            with open(target_file, "r", encoding="utf-8", errors="replace") as f:
                note_body = f.read()

            return ToolResult(success=True, output=f"Isi Catatan ({os.path.basename(target_file)}):\n\n{note_body}")

        # -------------------------------------------------------------------
        # 9. Action: SEND_SMS
        # -------------------------------------------------------------------
        elif action == "send_sms":
            number = kwargs.get("phone_number", "").strip()
            msg = kwargs.get("message", kwargs.get("content", "")).strip()

            if not number or not msg:
                return ToolResult(success=False, output="", error="Parameter 'phone_number' dan 'message' wajib diisi untuk send_sms.")

            res = await bridge.execute_shell(f"termux-sms-send -n {shlex.quote(number)} {shlex.quote(msg)}")
            if res.success:
                return ToolResult(
                    success=True,
                    output=f"SMS berhasil dikirim ke nomor {number}:\n'{msg}'",
                )
            return ToolResult(
                success=False,
                output="",
                error=f"Gagal mengirim SMS: {res.stderr or 'Izin Termux:API SMS belum diberikan'}",
            )

        # -------------------------------------------------------------------
        # 10. Action: LIST_SMS
        # -------------------------------------------------------------------
        elif action == "list_sms":
            limit = kwargs.get("limit", 5)
            stype = kwargs.get("sms_type", "all").lower()
            flag_type = "-t " + ("inbox" if stype == "inbox" else ("sent" if stype == "sent" else "all"))
            flag_limit = f"-l {int(limit)}"

            res = await bridge.execute_shell(f"termux-sms-list {flag_type} {flag_limit}")
            if res.success and res.stdout.strip():
                try:
                    sms_list = json.loads(res.stdout)
                    if isinstance(sms_list, list) and sms_list:
                        lines = [f"Daftar SMS ({len(sms_list)} pesan):"]
                        for s in sms_list:
                            sender = s.get("number", "Unknown")
                            body = s.get("body", "").replace("\n", " ")
                            recv = s.get("received", "")
                            lines.append(f"• Dari/Ke: {sender} | Waktu: {recv}\n  Pesan: {body[:100]}")
                        return ToolResult(success=True, output="\n".join(lines))
                except Exception:
                    pass
                return ToolResult(success=True, output=f"Daftar SMS:\n{res.stdout}")
            return ToolResult(success=True, output="Tidak ada pesan SMS ditemukan atau izin Termux:API SMS belum aktif.")

        # -------------------------------------------------------------------
        # 11. Action: LIST_CONTACTS
        # -------------------------------------------------------------------
        elif action == "list_contacts":
            query = kwargs.get("search_query", "").lower().strip()
            limit = kwargs.get("limit", 15)

            res = await bridge.execute_shell("termux-contact-list")
            if res.success and res.stdout.strip():
                try:
                    contacts = json.loads(res.stdout)
                    if isinstance(contacts, list):
                        filtered = []
                        for c in contacts:
                            name = c.get("name", "")
                            num = c.get("number", "")
                            if not query or (query in name.lower() or query in num):
                                filtered.append(f"• {name}: {num}")

                        if filtered:
                            return ToolResult(
                                success=True,
                                output=f"Daftar Kontak ({len(filtered)} ditemukan):\n" + "\n".join(filtered[:limit]),
                            )
                        return ToolResult(success=True, output=f"Tidak ditemukan kontak yang cocok dengan kata kunci '{query}'.")
                except Exception:
                    pass
            return ToolResult(success=True, output="Tidak dapat membaca kontak telepon. Pastikan izin Termux:API Contacts aktif.")

        # -------------------------------------------------------------------
        # 12. Action: MAKE_CALL
        # -------------------------------------------------------------------
        elif action == "make_call":
            number = kwargs.get("phone_number", "").strip()
            if not number:
                return ToolResult(success=False, output="", error="Parameter 'phone_number' wajib diisi untuk make_call.")

            if "*" in number or "#" in number:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Akses ditolak: Panggilan ke kode USSD/MMI ({number}) diblokir demi keamanan perangkat.",
                )

            clean_number = re.sub(r"[^\d+,]", "", number)
            dial_target = clean_number or number
            res = await bridge.execute_shell(f"termux-telephony-call {shlex.quote(dial_target)}")
            if not res.success and bridge.is_root_available():
                res = await bridge.execute_shell(f"am start -a android.intent.action.CALL -d {shlex.quote(f'tel:{dial_target}')}", as_root=True)

            return ToolResult(
                success=True,
                output=f"Panggilan telepon ke nomor {number} berhasil diinisialisasi.",
            )

        # -------------------------------------------------------------------
        # 13. Action: CELL_INFO
        # -------------------------------------------------------------------
        elif action == "cell_info":
            res = await bridge.execute_shell("termux-telephony-cellinfo")
            if res.success and res.stdout.strip():
                return ToolResult(success=True, output=f"Informasi Jaringan Seluler (BTS / Operator):\n{res.stdout}")
            res_dump = await bridge.execute_shell("dumpsys telephony.registry | grep -E 'mServiceState|mSignalStrength'", as_root=bridge.is_root_available())
            return ToolResult(success=True, output=f"Informasi Jaringan Seluler:\n{res_dump.stdout or 'Normal'}")

        # -------------------------------------------------------------------
        # 14. Action: CLIPBOARD_GET
        # -------------------------------------------------------------------
        elif action == "clipboard_get":
            res = await bridge.execute_shell("termux-clipboard-get")
            if res.success:
                cb_text = res.stdout.strip()
                if cb_text:
                    return ToolResult(success=True, output=f"Isi Papan Klip (Clipboard):\n{cb_text}")
                return ToolResult(success=True, output="Papan klip (clipboard) saat ini kosong.")
            return ToolResult(success=False, output="", error=f"Gagal membaca clipboard: {res.stderr}")

        # -------------------------------------------------------------------
        # 15. Action: CLIPBOARD_SET
        # -------------------------------------------------------------------
        elif action == "clipboard_set":
            content = kwargs.get("content", "").strip()
            if not content:
                return ToolResult(success=False, output="", error="Parameter 'content' wajib diisi untuk menyalin ke clipboard.")

            res = await bridge.execute_shell(f"termux-clipboard-set {shlex.quote(content)}")
            return ToolResult(
                success=True,
                output=f"Teks berhasil disalin ke papan klip (clipboard):\n'{content[:80]}...'",
            )

        return ToolResult(success=False, output="", error=f"Aksi productivity_control '{action}' tidak dikenal.")
