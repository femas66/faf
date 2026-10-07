from __future__ import annotations

import asyncio
import datetime
import json
import logging
import os
import re
import time
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Callable, Awaitable

import httpx

from src.config import get_settings
from src.tools.base import BaseTool, ToolContext, ToolResult

logger = logging.getLogger("faf_agent.tools.reminder_mgr")

HARI_INDONESIA = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
BULAN_INDONESIA = [
    "",
    "Januari",
    "Februari",
    "Maret",
    "April",
    "Mei",
    "Juni",
    "Juli",
    "Agustus",
    "September",
    "Oktober",
    "November",
    "Desember",
]


def _format_readable_dt(dt: datetime.datetime) -> str:
    """Format datetime into readable Indonesian string."""
    nama_hari = HARI_INDONESIA[dt.weekday()]
    nama_bulan = BULAN_INDONESIA[dt.month]
    return f"{nama_hari}, {dt.day:02d} {nama_bulan} {dt.year} {dt.strftime('%H:%M:%S')}"


def _format_duration_remaining(seconds_diff: float) -> str:
    """Format remaining seconds until trigger into human readable string."""
    sec = int(max(0, seconds_diff))
    days = sec // 86400
    hours = (sec % 86400) // 3600
    minutes = (sec % 3600) // 60
    rem_sec = sec % 60

    parts = []
    if days > 0:
        parts.append(f"{days} hari")
    if hours > 0 or days > 0:
        parts.append(f"{hours} jam")
    if minutes > 0 or hours > 0 or days > 0:
        parts.append(f"{minutes} menit")
    parts.append(f"{rem_sec} detik lagi")
    return " ".join(parts)


@dataclass
class ReminderItem:
    id: str
    chat_id: int
    message: str
    schedule_type: str  # "once", "daily", "weekly", "interval"
    time_str: str  # "12:00", "07:00", or datetime string
    created_at: str
    next_run_timestamp: float
    next_run_readable: str
    interval_minutes: int = 0
    days_of_week: list[int] | None = None  # 0=Monday, 6=Sunday
    is_active: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReminderItem:
        return cls(**data)


class ReminderStore:
    """Persistent JSON storage for scheduled reminders and cronjobs."""

    def __init__(self, file_path: str = "data/reminders.json") -> None:
        self.file_path = file_path
        self._reminders: dict[str, ReminderItem] = {}
        self._lock = asyncio.Lock()
        self.load()

    def load(self) -> None:
        """Load stored reminders from JSON file if exists."""
        if not os.path.exists(self.file_path):
            return
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                raw_list = json.load(f)
                if isinstance(raw_list, list):
                    for item in raw_list:
                        rem = ReminderItem.from_dict(item)
                        self._reminders[rem.id] = rem
            logger.info(f"Loaded {len(self._reminders)} reminders from {self.file_path}")
        except Exception as e:
            logger.error(f"Failed to load reminders from {self.file_path}: {e}")

    def save(self) -> None:
        """Persist reminders to disk."""
        try:
            os.makedirs(os.path.dirname(self.file_path) or ".", exist_ok=True)
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump([rem.to_dict() for rem in self._reminders.values()], f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save reminders: {e}")

    async def add(self, item: ReminderItem) -> None:
        async with self._lock:
            self._reminders[item.id] = item
            self.save()

    async def remove(self, reminder_id: str) -> ReminderItem | None:
        async with self._lock:
            item = self._reminders.pop(reminder_id, None)
            if item:
                self.save()
            return item

    async def get(self, reminder_id: str) -> ReminderItem | None:
        return self._reminders.get(reminder_id)

    async def list_all(self, chat_id: int | None = None) -> list[ReminderItem]:
        items = list(self._reminders.values())
        if chat_id is not None:
            items = [i for i in items if i.chat_id == chat_id]
        # Sort by next run timestamp
        items.sort(key=lambda x: x.next_run_timestamp)
        return items

    async def find_by_query(self, query: str, chat_id: int | None = None) -> list[ReminderItem]:
        q_lower = query.lower().strip()
        matches = []
        for rem in self._reminders.values():
            if chat_id is not None and rem.chat_id != chat_id:
                continue
            if q_lower in rem.id.lower() or q_lower in rem.message.lower() or q_lower in rem.time_str.lower():
                matches.append(rem)
        return matches

    async def clear_all(self, chat_id: int | None = None) -> int:
        async with self._lock:
            if chat_id is None:
                count = len(self._reminders)
                self._reminders.clear()
            else:
                to_delete = [k for k, v in self._reminders.items() if v.chat_id == chat_id]
                count = len(to_delete)
                for k in to_delete:
                    del self._reminders[k]
            self.save()
            return count


class ReminderWorker:
    """Background task runner that polls active reminders and dispatches Telegram notifications."""

    def __init__(self, store: ReminderStore) -> None:
        self.store = store
        self._task: asyncio.Task | None = None
        self._running = False
        self.settings = get_settings()

    def start(self) -> None:
        """Start background loop if not already running."""
        if self._running and self._task and not self._task.done():
            return
        try:
            loop = asyncio.get_running_loop()
            self._running = True
            self._task = loop.create_task(self._loop())
            logger.info("Reminder background worker started.")
        except RuntimeError:
            pass

    def stop(self) -> None:
        """Stop background worker loop."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()

    async def _send_telegram_notification(self, chat_id: int, rem: ReminderItem) -> bool:
        """Send reminder message via Telegram Bot API."""
        token = self.settings.telegram_bot_token
        if not token:
            logger.warning("Cannot send reminder: TELEGRAM_BOT_TOKEN is not set.")
            return False

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        now_str = _format_readable_dt(datetime.datetime.now().astimezone())

        type_label = "Sekali Jalan" if rem.schedule_type == "once" else f"Berulang ({rem.schedule_type.upper()})"
        text = (
            f"🔔 PENGINGAT TELEGRAM!\n\n"
            f"• Pesan: {rem.message}\n"
            f"• Waktu: {now_str}\n"
            f"• Jadwal: {type_label}\n"
            f"• ID: {rem.id}"
        )

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, json={"chat_id": chat_id, "text": text})
                if resp.status_code == 200:
                    logger.info(f"Dispatched reminder {rem.id} to chat {chat_id}")
                    return True
                else:
                    logger.error(f"Failed to dispatch reminder to Telegram: {resp.text}")
        except Exception as e:
            logger.error(f"Error sending reminder to chat {chat_id}: {e}")
        return False

    async def _loop(self) -> None:
        """Periodic background evaluation loop."""
        while self._running:
            try:
                now_ts = time.time()
                active_items = await self.store.list_all()

                for rem in active_items:
                    if not rem.is_active:
                        continue

                    if now_ts >= rem.next_run_timestamp:
                        # Time reached: fire notification!
                        await self._send_telegram_notification(rem.chat_id, rem)

                        # Handle schedule recurrence
                        if rem.schedule_type == "once":
                            # Remove once-off reminder
                            await self.store.remove(rem.id)
                        else:
                            # Advance next run timestamp for recurring schedules
                            self._advance_recurring(rem)
                            self.store.save()

                await asyncio.sleep(5)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Unexpected error in reminder loop: {e}", exc_info=True)
                await asyncio.sleep(5)

    def _advance_recurring(self, rem: ReminderItem) -> None:
        """Advance recurring schedule to next trigger time."""
        now = datetime.datetime.now().astimezone()

        if rem.schedule_type == "daily":
            # Advance by 1 day at the same time
            try:
                parts = rem.time_str.replace(".", ":").split(":")
                hour, minute = int(parts[0]), int(parts[1])
                target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                # Next occurrence must be in the future
                if target <= now:
                    target += datetime.timedelta(days=1)
                rem.next_run_timestamp = target.timestamp()
                rem.next_run_readable = _format_readable_dt(target)
            except Exception:
                rem.next_run_timestamp += 86400

        elif rem.schedule_type == "interval":
            interval_sec = max(60, rem.interval_minutes * 60)
            rem.next_run_timestamp += interval_sec
            next_dt = datetime.datetime.fromtimestamp(rem.next_run_timestamp).astimezone()
            rem.next_run_readable = _format_readable_dt(next_dt)

        elif rem.schedule_type == "weekly":
            rem.next_run_timestamp += 7 * 86400
            next_dt = datetime.datetime.fromtimestamp(rem.next_run_timestamp).astimezone()
            rem.next_run_readable = _format_readable_dt(next_dt)


# Global Store & Worker Instances
_default_store = ReminderStore()
_default_worker = ReminderWorker(_default_store)


class ReminderManagerTool(BaseTool):
    """Dedicated tool for managing Telegram reminder messages and recurring cronjobs."""

    name = "reminder_manager"
    description = (
        "Tool khusus untuk menjadwalkan pengingat pesan ke chat Telegram (BUKAN alarm ponsel fisik). "
        "Mendukung pengingat sekali jalan (misal jam 12:00 untuk makan siang) maupun pengingat berulang berkala "
        "/ cronjob harian (misal setiap jam 7 pagi untuk mandi). Juga dapat melihat daftar pengingat yang aktif "
        "dan mematikan/menghapus pengingat tertentu."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "list", "cancel", "clear_all"],
                "description": (
                    "Aksi pengingat: 'create' (buat jadwal pengingat baru), "
                    "'list' (lihat daftar jadwal pengingat aktif), "
                    "'cancel' (matikan/hapus pengingat tertentu), "
                    "'clear_all' (hapus semua pengingat)."
                ),
            },
            "message": {
                "type": "string",
                "description": "Isi pesan pengingat yang akan dikirimkan ke Telegram (contoh: 'Memberi makan kucing', 'Waktunya mandi pagi').",
            },
            "time": {
                "type": "string",
                "description": (
                    "Jam atau waktu target pemicu. Contoh: '12:00', '07:00', '19:30', atau "
                    "tanggal spesifik '2026-10-08 07:00'. Jika hanya jam dan sudah lewat hari ini, otomatis dijadwalkan besok."
                ),
            },
            "is_recurring": {
                "type": "boolean",
                "description": "Setel True jika pengingat ini adalah jadwal berulang / cronjob (misal: 'setiap jam 7 pagi'), False jika sekali jalan.",
                "default": False,
            },
            "frequency": {
                "type": "string",
                "enum": ["once", "daily", "weekly", "interval"],
                "description": "Frekuensi pengulangan: 'once' (sekali), 'daily' (setiap hari), 'weekly' (setiap minggu), 'interval' (setiap X menit).",
                "default": "once",
            },
            "in_minutes": {
                "type": "integer",
                "description": "Menit relatif dari sekarang untuk pengingat sekali jalan (contoh: 15 untuk 'ingatkan 15 menit lagi').",
            },
            "interval_minutes": {
                "type": "integer",
                "description": "Interval waktu dalam menit untuk pengingat tipe 'interval' (contoh: 60 untuk setiap 1 jam).",
            },
            "reminder_id": {
                "type": "string",
                "description": "ID pengingat yang ingin dibatalkan/dihapus pada aksi 'cancel' (contoh: 'rem_a1b2c3').",
            },
            "search_query": {
                "type": "string",
                "description": "Kata kunci pencarian untuk membatalkan pengingat jika ID tidak diketahui (contoh: 'mandi', 'kucing').",
            },
        },
        "required": ["action"],
    }

    def __init__(self, store: ReminderStore | None = None, worker: ReminderWorker | None = None) -> None:
        self.store = store or _default_store
        self.worker = worker or _default_worker
        self.worker.start()

    async def execute(self, context: ToolContext, **kwargs: Any) -> ToolResult:
        self.worker.start()
        action = kwargs.get("action", "list").lower().strip()
        chat_id = context.chat_id

        if context.on_status_update:
            await context.on_status_update(f"● reminder_manager · {action}")

        # -------------------------------------------------------------------
        # 1. Action: CREATE (Schedule new reminder or cronjob)
        # -------------------------------------------------------------------
        if action in ("create", "add", "set"):
            msg = kwargs.get("message", "").strip()
            if not msg:
                return ToolResult(success=False, output="", error="Parameter 'message' (isi pengingat) wajib diisi.")

            time_str = kwargs.get("time", "").strip()
            in_minutes = kwargs.get("in_minutes")
            is_recurring = kwargs.get("is_recurring", False)
            frequency = kwargs.get("frequency", "daily" if is_recurring else "once").lower()

            now = datetime.datetime.now().astimezone()
            target_dt: datetime.datetime | None = None

            # 1. Check relative minutes
            if in_minutes is not None and in_minutes > 0:
                target_dt = now + datetime.timedelta(minutes=in_minutes)
                time_str = target_dt.strftime("%H:%M")
            # 2. Check time string
            elif time_str:
                # Clean time string (replace dot with colon, e.g. "12.00" -> "12:00")
                cleaned_time = time_str.replace(".", ":")

                # Pattern HH:MM or HH:MM:SS
                time_match = re.search(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$", cleaned_time)
                if time_match:
                    hour = int(time_match.group(1))
                    minute = int(time_match.group(2))
                    second = int(time_match.group(3)) if time_match.group(3) else 0

                    candidate = now.replace(hour=hour, minute=minute, second=second, microsecond=0)
                    # If time already passed today, schedule for tomorrow
                    if candidate <= now:
                        candidate += datetime.timedelta(days=1)
                    target_dt = candidate
                else:
                    # Pattern full date: YYYY-MM-DD HH:MM
                    for fmt in ["%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%d-%m-%Y %H:%M", "%d/%m/%Y %H:%M"]:
                        try:
                            target_dt = datetime.datetime.strptime(cleaned_time, fmt).astimezone()
                            break
                        except Exception:
                            pass

            if target_dt is None:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Format waktu '{time_str}' tidak valid. Gunakan format jam 'HH:MM' (contoh: '12:00', '07:00') atau menit relatif.",
                )

            # Determine schedule type
            if is_recurring or frequency in ("daily", "weekly", "interval"):
                sched_type = frequency if frequency in ("daily", "weekly", "interval") else "daily"
            else:
                sched_type = "once"

            rem_id = f"rem_{uuid.uuid4().hex[:6]}"
            interval_mins = kwargs.get("interval_minutes", 0)

            rem_item = ReminderItem(
                id=rem_id,
                chat_id=chat_id,
                message=msg,
                schedule_type=sched_type,
                time_str=time_str or target_dt.strftime("%H:%M"),
                created_at=_format_readable_dt(now),
                next_run_timestamp=target_dt.timestamp(),
                next_run_readable=_format_readable_dt(target_dt),
                interval_minutes=interval_mins,
                is_active=True,
            )

            await self.store.add(rem_item)

            remaining_sec = target_dt.timestamp() - now.timestamp()
            remaining_str = _format_duration_remaining(remaining_sec)

            if sched_type == "once":
                title_label = "Pengingat Telegram Berhasil Dibuat"
                type_label = f"Sekali jalan pada {rem_item.time_str}"
            else:
                title_label = "Jadwal Pengingat Berulang (Cronjob) Berhasil Dibuat"
                type_label = f"Berulang ({sched_type.upper()}) setiap pukul {rem_item.time_str}"

            out_text = (
                f"{title_label}\n\n"
                f"• ID: {rem_id}\n"
                f"• Pesan: {msg}\n"
                f"• Jadwal: {type_label}\n"
                f"• Waktu Pemicu: {_format_readable_dt(target_dt)} ({remaining_str})\n"
                f"• Notifikasi: Pesan akan otomatis dikirimkan ke Telegram ini saat waktunya tiba."
            )
            return ToolResult(success=True, output=out_text)

        # -------------------------------------------------------------------
        # 2. Action: LIST (View all active schedules)
        # -------------------------------------------------------------------
        elif action in ("list", "view", "status"):
            reminders = await self.store.list_all(chat_id=chat_id)
            if not reminders:
                return ToolResult(
                    success=True,
                    output="Saat ini tidak ada jadwal pengingat atau cronjob yang aktif di Telegram Anda.",
                )

            now_ts = time.time()
            lines = [
                f"Daftar Penjadwalan & Pengingat Telegram Aktif ({len(reminders)} jadwal):",
                "",
            ]

            for idx, rem in enumerate(reminders, start=1):
                diff = rem.next_run_timestamp - now_ts
                time_left = _format_duration_remaining(diff) if diff > 0 else "Segera terpicu"
                t_label = "Sekali jalan" if rem.schedule_type == "once" else f"Berulang {rem.schedule_type.upper()}"

                lines.append(f"{idx}. [{rem.id}] {rem.message}")
                lines.append(f"   • Tipe: {t_label}")
                lines.append(f"   • Waktu Pemicu Berikutnya: {rem.next_run_readable} ({time_left})")

            lines.append("")
            lines.append("Untuk membatalkan pengingat, ketik 'Hapus pengingat [nama/ID]'.")
            return ToolResult(success=True, output="\n".join(lines))

        # -------------------------------------------------------------------
        # 3. Action: CANCEL (Cancel / Delete specific reminder)
        # -------------------------------------------------------------------
        elif action in ("cancel", "delete", "remove", "stop"):
            target_id = kwargs.get("reminder_id", "").strip()
            query = kwargs.get("search_query", "").strip()

            item_to_remove: ReminderItem | None = None

            # 1. Match by explicit ID
            if target_id:
                item_to_remove = await self.store.get(target_id)

            # 2. Match by query search in message
            if not item_to_remove and query:
                matches = await self.store.find_by_query(query, chat_id=chat_id)
                if len(matches) == 1:
                    item_to_remove = matches[0]
                elif len(matches) > 1:
                    match_list = [f"• [{m.id}] {m.message} ({m.schedule_type})" for m in matches]
                    return ToolResult(
                        success=False,
                        output="",
                        error=(
                            f"Ditemukan beberapa pengingat dengan kata kunci '{query}':\n"
                            + "\n".join(match_list)
                            + "\nSilakan sebutkan ID pengingat yang spesifik untuk dihapus."
                        ),
                    )

            # 3. Fallback: query in target_id string
            if not item_to_remove and target_id:
                matches = await self.store.find_by_query(target_id, chat_id=chat_id)
                if len(matches) == 1:
                    item_to_remove = matches[0]

            if not item_to_remove:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Pengingat dengan ID atau kata kunci '{target_id or query}' tidak ditemukan.",
                )

            await self.store.remove(item_to_remove.id)
            out_text = (
                f"Pengingat Telegram Berhasil Dibatalkan & Dihapus\n\n"
                f"• ID: {item_to_remove.id}\n"
                f"• Pesan: {item_to_remove.message}\n"
                f"• Jadwal Sebelumnya: {item_to_remove.schedule_type.upper()} ({item_to_remove.time_str})\n"
                f"• Status: Pengingat telah dimatikan permanen dan tidak akan mengirim pesan lagi."
            )
            return ToolResult(success=True, output=out_text)

        # -------------------------------------------------------------------
        # 4. Action: CLEAR_ALL (Cancel all active reminders)
        # -------------------------------------------------------------------
        elif action in ("clear_all", "delete_all"):
            count = await self.store.clear_all(chat_id=chat_id)
            return ToolResult(
                success=True,
                output=f"Seluruh jadwal pengingat ({count} pengingat) berhasil dibatalkan dan dihapus.",
            )

        return ToolResult(success=False, output="", error=f"Aksi reminder_manager '{action}' tidak dikenal.")
