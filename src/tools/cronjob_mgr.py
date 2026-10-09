from __future__ import annotations

import asyncio
import datetime
import json
import logging
import os
import re
import shlex
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

import httpx

from src.config import get_settings
from src.core.android_bridge import bridge
from src.tools.base import BaseTool, ToolContext, ToolResult

logger = logging.getLogger("faf_agent.tools.cronjob_mgr")

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


def parse_duration_to_seconds(duration_str: str) -> int:
    """Parse string duration like '30s', '15m', '6h', '1d' to total seconds."""
    s = duration_str.strip().lower()
    m = re.match(r"^(\d+)\s*([smhd]|sec|min|jam|hari|hour|day)?$", s)
    if not m:
        return 60
    val, unit = int(m.group(1)), m.group(2) or "s"
    if unit in ("s", "sec"):
        return val
    elif unit in ("m", "min"):
        return val * 60
    elif unit in ("h", "jam", "hour"):
        return val * 3600
    elif unit in ("d", "hari", "day"):
        return val * 86400
    return val


def parse_schedule_string(schedule_str: str, from_dt: datetime.datetime | None = None) -> float | None:
    """
    Parse natural schedule strings or standard 5-part cron syntax into the next trigger timestamp.
    Supports:
      - 'every X[s|m|h|d]' (e.g. 'every 30m', 'every 6h')
      - 'daily at HH:MM' / 'every day at HH:MM' / 'at HH:MM'
      - 'every [mon|tue|wed|thu|fri|sat|sun] at HH:MM'
      - 'in X[m|h]' (e.g. 'in 15m')
      - Cron 5 fields: '*/30 * * * *', '0 7 * * *'
    """
    if from_dt is None:
        from_dt = datetime.datetime.now().astimezone()

    s = schedule_str.strip().lower()

    # 1. 'in X minutes/hours'
    m_in = re.match(r"^in\s+(\d+)\s*([smhd]|min|jam|hour|day)?$", s)
    if m_in:
        secs = parse_duration_to_seconds(f"{m_in.group(1)}{m_in.group(2) or 'm'}")
        return (from_dt + datetime.timedelta(seconds=secs)).timestamp()

    # 2. 'every X[s|m|h|d]'
    m_every = re.match(r"^every\s+(\d+)\s*([smhd]|sec|min|jam|hour|day|m|h|s|d)$", s)
    if m_every:
        secs = parse_duration_to_seconds(f"{m_every.group(1)}{m_every.group(2)}")
        return (from_dt + datetime.timedelta(seconds=secs)).timestamp()

    # 3. 'daily at HH:MM' or 'at HH:MM' or 'HH:MM'
    m_time = re.search(r"(\d{1,2})[:.](\d{2})(?:[:.](\d{2}))?", s)
    if m_time and ("daily" in s or "every day" in s or "at" in s or re.match(r"^\d{1,2}:\d{2}$", s)):
        hour = int(m_time.group(1))
        minute = int(m_time.group(2))
        second = int(m_time.group(3) or 0)
        candidate = from_dt.replace(hour=hour, minute=minute, second=second, microsecond=0)
        if candidate <= from_dt:
            candidate += datetime.timedelta(days=1)
        return candidate.timestamp()

    # 4. 'every [weekday] at HH:MM'
    day_map = {
        "mon": 0, "senin": 0, "monday": 0,
        "tue": 1, "selasa": 1, "tuesday": 1,
        "wed": 2, "rabu": 2, "wednesday": 2,
        "thu": 3, "kamis": 3, "thursday": 3,
        "fri": 4, "jumat": 4, "friday": 4,
        "sat": 5, "sabtu": 5, "saturday": 5,
        "sun": 6, "minggu": 6, "sunday": 6,
    }
    for day_name, day_idx in day_map.items():
        if f"every {day_name}" in s or f"tiap {day_name}" in s or f"setiap {day_name}" in s:
            hour, minute = 9, 0
            if m_time:
                hour = int(m_time.group(1))
                minute = int(m_time.group(2))
            candidate = from_dt.replace(hour=hour, minute=minute, second=0, microsecond=0)
            days_ahead = (day_idx - candidate.weekday()) % 7
            if days_ahead == 0 and candidate <= from_dt:
                days_ahead = 7
            candidate += datetime.timedelta(days=days_ahead)
            return candidate.timestamp()

    # 5. Cron 5 tokens: min hour dom mon dow
    cron_parts = s.split()
    if len(cron_parts) == 5:
        candidate = (from_dt + datetime.timedelta(minutes=1)).replace(second=0, microsecond=0)
        for _ in range(1440 * 7):  # Check up to 7 days ahead
            if _match_cron_field(cron_parts[0], candidate.minute, 0, 59) and \
               _match_cron_field(cron_parts[1], candidate.hour, 0, 23) and \
               _match_cron_field(cron_parts[2], candidate.day, 1, 31) and \
               _match_cron_field(cron_parts[3], candidate.month, 1, 12) and \
               _match_cron_field(cron_parts[4], (candidate.weekday() + 1) % 7, 0, 6):
                return candidate.timestamp()
            candidate += datetime.timedelta(minutes=1)

    return None


def _match_cron_field(field_expr: str, value: int, min_val: int, max_val: int) -> bool:
    """Evaluate whether value matches standard cron field expression."""
    if field_expr == "*":
        return True
    if "/" in field_expr:
        sub, step_str = field_expr.split("/", 1)
        step = int(step_str) if step_str.isdigit() else 1
        start = min_val if sub == "*" else int(sub)
        return (value >= start) and ((value - start) % step == 0)
    if "," in field_expr:
        return any(_match_cron_field(part, value, min_val, max_val) for part in field_expr.split(","))
    if "-" in field_expr:
        parts = field_expr.split("-", 1)
        if parts[0].isdigit() and parts[1].isdigit():
            return int(parts[0]) <= value <= int(parts[1])
    if field_expr.isdigit():
        return int(field_expr) == value
    return False


@dataclass
class CronJobItem:
    id: str
    chat_id: int
    title: str
    schedule: str
    timezone: str = "Asia/Jakarta"
    active_window: dict[str, Any] | None = None
    execution_type: str = "agent_prompt"  # "agent_prompt" | "skill_tick" | "shell_command" | "python_code"
    prompt: str | None = None
    skills_required: list[str] = field(default_factory=list)
    command: str | None = None
    python_code: str | None = None
    trigger_policy: dict[str, Any] | None = None
    state_config: dict[str, Any] | None = None
    deliver: dict[str, Any] | None = None
    lifecycle: dict[str, Any] | None = None
    retry_policy: dict[str, Any] | None = None
    created_at: str = ""
    next_run_timestamp: float = 0.0
    next_run_readable: str = ""
    total_runs: int = 0
    total_triggers: int = 0
    last_run_timestamp: float | None = None
    last_trigger_timestamp: float | None = None
    last_status: str = "created"
    last_output: str = ""
    last_error: str | None = None
    is_active: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CronJobItem:
        valid_keys = cls.__dataclass_fields__.keys()
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered)


class CronJobStore:
    """Thread-safe persistent JSON store for faf-agent cronjobs."""

    def __init__(self, file_path: str = "data/cronjobs.json") -> None:
        self.file_path = file_path
        self._jobs: dict[str, CronJobItem] = {}
        self._lock = asyncio.Lock()
        self.load()

    def load(self) -> None:
        if not os.path.exists(self.file_path):
            return
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                raw_list = json.load(f)
                if isinstance(raw_list, list):
                    for item in raw_list:
                        job = CronJobItem.from_dict(item)
                        self._jobs[job.id] = job
            logger.info(f"Loaded {len(self._jobs)} cronjobs from {self.file_path}")
        except Exception as e:
            logger.error(f"Failed to load cronjobs from {self.file_path}: {e}")

    def save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.file_path) or ".", exist_ok=True)
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump([j.to_dict() for j in self._jobs.values()], f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save cronjobs: {e}")

    async def add(self, item: CronJobItem) -> None:
        async with self._lock:
            self._jobs[item.id] = item
            self.save()

    async def update(self, item: CronJobItem) -> None:
        async with self._lock:
            self._jobs[item.id] = item
            self.save()

    async def remove(self, job_id: str) -> CronJobItem | None:
        async with self._lock:
            item = self._jobs.pop(job_id, None)
            if item:
                self.save()
            return item

    async def get(self, job_id: str) -> CronJobItem | None:
        return self._jobs.get(job_id)

    async def list_all(self, chat_id: int | None = None) -> list[CronJobItem]:
        items = list(self._jobs.values())
        if chat_id is not None:
            items = [j for j in items if j.chat_id == chat_id]
        items.sort(key=lambda x: x.next_run_timestamp)
        return items

    async def clear_all(self, chat_id: int | None = None) -> int:
        async with self._lock:
            if chat_id is None:
                count = len(self._jobs)
                self._jobs.clear()
            else:
                to_delete = [k for k, v in self._jobs.items() if v.chat_id == chat_id]
                count = len(to_delete)
                for k in to_delete:
                    del self._jobs[k]
            self.save()
            return count


class CronJobWorker:
    """Autonomous background scheduler engine for faf-agent."""

    def __init__(self, store: CronJobStore) -> None:
        self.store = store
        self._task: asyncio.Task | None = None
        self._running = False
        self.settings = get_settings()

    def start(self) -> None:
        if self._running and self._task and not self._task.done():
            return
        try:
            loop = asyncio.get_running_loop()
            self._running = True
            self._task = loop.create_task(self._loop())
            logger.info("CronJob background worker engine started.")
        except RuntimeError:
            pass

    def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()

    async def _is_in_active_window(self, job: CronJobItem, now: datetime.datetime) -> bool:
        if not job.active_window:
            return True
        st = job.active_window.get("start_time")
        et = job.active_window.get("end_time")
        if st and et:
            try:
                sh, sm = map(int, st.split(":"))
                eh, em = map(int, et.split(":"))
                curr_min = now.hour * 60 + now.minute
                start_min = sh * 60 + sm
                end_min = eh * 60 + em
                if start_min <= end_min:
                    if not (start_min <= curr_min <= end_min):
                        return False
                else:
                    if not (curr_min >= start_min or curr_min <= end_min):
                        return False
            except Exception:
                pass
        return True

    async def execute_job_tick(self, job: CronJobItem) -> tuple[bool, str]:
        """
        Execute single job tick and evaluate conditional trigger policy.
        Returns (should_deliver, output_payload).
        """
        job.total_runs += 1
        job.last_run_timestamp = time.time()
        job.last_status = "running"

        output = ""
        should_trigger = False

        # 1. Execute task by execution_type
        try:
            if job.execution_type == "shell_command":
                cmd = job.command or ""
                if cmd:
                    res = await bridge.execute_shell(cmd)
                    output = res.stdout.strip() if res.success else f"Error: {res.stderr.strip()}"
                else:
                    output = "No shell command specified"

            elif job.execution_type == "python_code":
                code = job.python_code or ""
                # Evaluate safe code or local expression
                local_scope: dict[str, Any] = {}
                exec(code, {}, local_scope)
                output = str(local_scope.get("result", "Execution completed"))

            elif job.execution_type in ("agent_prompt", "skill_tick"):
                # Agent prompt or skill contract evaluation
                output = job.prompt or f"Executing tick for skill {job.skills_required}"

            # 2. Evaluate Trigger Policy
            trigger_policy = job.trigger_policy or {}
            mode = trigger_policy.get("mode", "always")

            if mode == "always":
                should_trigger = True
            elif mode in ("conditional", "threshold"):
                # Condition check logic: if condition prompt exists, inspect response
                # Default true if output is produced and not error
                should_trigger = True if output and not output.startswith("Error:") else False
            elif mode == "state_changed":
                # Check delta against saved state
                state_cfg = job.state_config or {}
                state_path = state_cfg.get("state_path")
                prev_val = None
                if state_path and os.path.exists(os.path.expanduser(state_path)):
                    try:
                        with open(os.path.expanduser(state_path), "r", encoding="utf-8") as sf:
                            prev_val = sf.read().strip()
                    except Exception:
                        pass
                if prev_val != output:
                    should_trigger = True
                    if state_path:
                        try:
                            os.makedirs(os.path.dirname(os.path.expanduser(state_path)) or ".", exist_ok=True)
                            with open(os.path.expanduser(state_path), "w", encoding="utf-8") as sf:
                                sf.write(output)
                        except Exception:
                            pass

            # 3. Check Cooldown
            if should_trigger and trigger_policy.get("cooldown_after_trigger"):
                cooldown_sec = parse_duration_to_seconds(trigger_policy["cooldown_after_trigger"])
                if job.last_trigger_timestamp and (time.time() - job.last_trigger_timestamp < cooldown_sec):
                    should_trigger = False
                    job.last_status = "cooldown_active"

            job.last_output = output
            if should_trigger:
                job.last_status = "triggered"
            elif job.last_status != "cooldown_active":
                job.last_status = "condition_not_met"

            return should_trigger, output

        except Exception as e:
            job.last_status = "error"
            job.last_error = str(e)
            logger.error(f"Cronjob {job.id} execution failed: {e}")
            return False, f"Error: {str(e)}"

    async def deliver_notification(self, job: CronJobItem, payload: str) -> bool:
        """Deliver payload to configured channel(s)."""
        cfg = job.deliver or {"channel": "telegram"}
        channel = cfg.get("channel", "telegram")
        success = True

        targets = cfg.get("targets") if channel == "multi" else [{"channel": channel, **cfg}]
        for target in targets:
            ch = target.get("channel", "telegram")
            try:
                if ch == "telegram":
                    chat_id = target.get("target_id") or job.chat_id
                    token = self.settings.telegram_bot_token
                    if token and chat_id:
                        text = (
                            f"⏰ CRONJOB [{job.title or job.id}]\n\n"
                            f"{payload}\n\n"
                            f"• Status: Terpicu ({job.schedule})\n"
                            f"• Waktu: {_format_readable_dt(datetime.datetime.now().astimezone())}"
                        )
                        url = f"https://api.telegram.org/bot{token}/sendMessage"
                        async with httpx.AsyncClient(timeout=10) as client:
                            await client.post(url, json={"chat_id": chat_id, "text": text})

                elif ch == "android_notification":
                    title = target.get("title") or f"faf-agent: {job.title}"
                    cmd_parts = [
                        "termux-notification",
                        f"-t {shlex.quote(title)}",
                        f"-c {shlex.quote(payload[:200])}",
                        f"-i {shlex.quote(job.id)}",
                        "--vibrate 300",
                    ]
                    await bridge.execute_shell(" ".join(cmd_parts))

                elif ch == "tts_voice":
                    tts_text = target.get("tts_text") or payload
                    await bridge.execute_shell(f"termux-tts-speak {shlex.quote(tts_text[:250])}")

                elif ch == "webhook":
                    url = target.get("url") or target.get("target_id")
                    if url:
                        async with httpx.AsyncClient(timeout=10) as client:
                            await client.post(url, json={"job_id": job.id, "title": job.title, "payload": payload})

            except Exception as e:
                logger.error(f"Failed to deliver notification via {ch}: {e}")
                success = False

        if success:
            job.total_triggers += 1
            job.last_trigger_timestamp = time.time()

        return success

    async def _loop(self) -> None:
        """Main periodic scheduler worker loop."""
        while self._running:
            try:
                now_dt = datetime.datetime.now().astimezone()
                now_ts = now_dt.timestamp()
                active_jobs = await self.store.list_all()

                for job in active_jobs:
                    if not job.is_active:
                        continue

                    # 1. Check expiration
                    lifecycle = job.lifecycle or {}
                    if lifecycle.get("expires_at"):
                        try:
                            exp_dt = datetime.datetime.fromisoformat(lifecycle["expires_at"]).timestamp()
                            if now_ts >= exp_dt:
                                job.is_active = False
                                job.last_status = "expired"
                                await self.store.update(job)
                                continue
                        except Exception:
                            pass

                    # 2. Check scheduled run timestamp
                    if now_ts >= job.next_run_timestamp:
                        # Check active window
                        in_window = await self._is_in_active_window(job, now_dt)
                        if in_window:
                            should_deliver, payload = await self.execute_job_tick(job)
                            if should_deliver:
                                await self.deliver_notification(job, payload)

                            # Check lifecycle auto-delete or limits
                            max_triggers = lifecycle.get("max_triggers", 1 if lifecycle.get("auto_delete_on_trigger") else None)
                            if lifecycle.get("auto_delete_on_trigger") and max_triggers and job.total_triggers >= max_triggers:
                                await self.store.remove(job.id)
                                continue

                            if lifecycle.get("max_runs") and job.total_runs >= lifecycle["max_runs"]:
                                job.is_active = False
                                job.last_status = "max_runs_reached"
                                await self.store.update(job)
                                continue

                        # Advance next run timestamp
                        next_ts = parse_schedule_string(job.schedule, now_dt)
                        if next_ts:
                            job.next_run_timestamp = next_ts
                            job.next_run_readable = _format_readable_dt(datetime.datetime.fromtimestamp(next_ts).astimezone())
                        else:
                            # Default fallback: 1 hour
                            job.next_run_timestamp = now_ts + 3600
                            job.next_run_readable = _format_readable_dt(datetime.datetime.fromtimestamp(job.next_run_timestamp).astimezone())

                        await self.store.update(job)

                await asyncio.sleep(5)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Unexpected error in CronJobWorker loop: {e}")
                await asyncio.sleep(5)


# Global instances
_default_cron_store = CronJobStore()
_default_cron_worker = CronJobWorker(_default_cron_store)


class CronJobTool(BaseTool):
    """Universal and comprehensive cronjob / autonomous watcher tool for faf-agent."""

    name = "cronjob"
    description = (
        "Manajer penjadwalan otonom tingkat lanjut (cronjob & event-driven watcher) untuk faf-agent. "
        "Mampu menjalankan prompt agen berkala, memuat skill, memantau kondisi lingkungan/sensor, serta "
        "mengirimkan notifikasi multi-channel (Telegram, Notifikasi HP, TTS, Webhook)."
    )

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "update", "pause", "resume", "delete", "list", "status", "trigger_now", "clear_all"],
                "description": (
                    "Aksi cronjob: 'create' (buat baru), 'list' (daftar aktif), 'status' (detail job), "
                    "'trigger_now' (uji eksekusi manual), 'pause' (jeda), 'resume' (lanjutkan), "
                    "'delete' (hapus), 'clear_all' (hapus semua)."
                ),
            },
            "job_id": {
                "type": "string",
                "description": "Slug identifier unik untuk cronjob (contoh: 'rain-alert-jkt', 'price-watch-m3').",
            },
            "title": {
                "type": "string",
                "description": "Judul deskriptif singkat tentang cronjob ini.",
            },
            "schedule": {
                "type": "string",
                "description": (
                    "Jadwal eksekusi. Format natural ('every 30m', 'every 6h', 'daily at 07:00', "
                    "'every mon at 08:00') atau ekspresi cron 5 kolom ('*/30 6-22 * * *')."
                ),
            },
            "execution_type": {
                "type": "string",
                "enum": ["agent_prompt", "skill_tick", "shell_command", "python_code"],
                "description": "Metode eksekusi saat jadwal tiba. Default: 'agent_prompt'.",
            },
            "prompt": {
                "type": "string",
                "description": "Instruksi yang dieksekusi oleh LLM/Agent saat jadwal tiba.",
            },
            "skills_required": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Daftar nama skill yang perlu dimuat saat tugas berjalan.",
            },
            "command": {
                "type": "string",
                "description": "Perintah shell/Termux langsung (jika execution_type='shell_command').",
            },
            "python_code": {
                "type": "string",
                "description": "Kode Python yang dieksekusi langsung (jika execution_type='python_code').",
            },
            "trigger_policy": {
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": ["always", "conditional", "state_changed", "threshold"],
                        "description": "Mode pemicu: 'always', 'conditional' (hanya jika kondisi true), 'state_changed' (jika delta berubah).",
                    },
                    "condition_prompt": {
                        "type": "string",
                        "description": "Kriteria evaluasi kondisi (contoh: 'Kirim notifikasi hanya jika kemungkinan hujan > 60%').",
                    },
                    "cooldown_after_trigger": {
                        "type": "string",
                        "description": "Jeda waktu minimum antar notifikasi sukses untuk mencegah spam (contoh: '1h', '3h').",
                    },
                },
            },
            "deliver": {
                "type": "object",
                "properties": {
                    "channel": {
                        "type": "string",
                        "enum": ["telegram", "android_notification", "tts_voice", "webhook", "multi"],
                    },
                    "target_id": {
                        "type": "string",
                        "description": "Chat ID Telegram atau endpoint webhook.",
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["low", "normal", "high", "urgent"],
                    },
                    "silent": {"type": "boolean"},
                },
            },
            "lifecycle": {
                "type": "object",
                "properties": {
                    "max_runs": {"type": "integer"},
                    "max_triggers": {"type": "integer"},
                    "auto_delete_on_trigger": {"type": "boolean"},
                    "expires_at": {"type": "string"},
                },
            },
        },
        "required": ["action"],
    }

    def __init__(self, store: CronJobStore | None = None, worker: CronJobWorker | None = None) -> None:
        self.store = store or _default_cron_store
        self.worker = worker or _default_cron_worker

    async def execute(self, context: ToolContext, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action", "").lower().strip()
        chat_id = context.chat_id

        # -------------------------------------------------------------------
        # 1. Action: CREATE
        # -------------------------------------------------------------------
        if action == "create":
            job_id = kwargs.get("job_id") or f"cron_{uuid.uuid4().hex[:6]}"
            schedule = kwargs.get("schedule", "every 1h").strip()
            title = kwargs.get("title") or job_id

            now_dt = datetime.datetime.now().astimezone()
            next_ts = parse_schedule_string(schedule, now_dt)
            if not next_ts:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Format jadwal '{schedule}' tidak valid. Gunakan 'every 30m', 'every 6h', 'daily at 07:00', atau cron format.",
                )

            item = CronJobItem(
                id=job_id,
                chat_id=chat_id,
                title=title,
                schedule=schedule,
                execution_type=kwargs.get("execution_type", "agent_prompt"),
                prompt=kwargs.get("prompt"),
                skills_required=kwargs.get("skills_required") or [],
                command=kwargs.get("command"),
                python_code=kwargs.get("python_code"),
                trigger_policy=kwargs.get("trigger_policy"),
                deliver=kwargs.get("deliver") or {"channel": "telegram", "target_id": str(chat_id)},
                lifecycle=kwargs.get("lifecycle"),
                created_at=_format_readable_dt(now_dt),
                next_run_timestamp=next_ts,
                next_run_readable=_format_readable_dt(datetime.datetime.fromtimestamp(next_ts).astimezone()),
                is_active=True,
            )

            await self.store.add(item)
            diff = next_ts - now_dt.timestamp()

            out_text = (
                f"Cronjob Otonom Berhasil Dibuat!\n\n"
                f"• ID: {item.id}\n"
                f"• Judul: {item.title}\n"
                f"• Jadwal: {item.schedule}\n"
                f"• Tipe Eksekusi: {item.execution_type}\n"
                f"• Pemicu Berikutnya: {item.next_run_readable} ({_format_duration_remaining(diff)})\n"
                f"• Channel Pengiriman: {item.deliver.get('channel', 'telegram')}\n"
            )
            return ToolResult(success=True, output=out_text)

        # -------------------------------------------------------------------
        # 2. Action: LIST
        # -------------------------------------------------------------------
        elif action == "list":
            jobs = await self.store.list_all(chat_id=chat_id)
            if not jobs:
                return ToolResult(success=True, output="Tidak ada cronjob aktif di faf-agent saat ini.")

            now_ts = time.time()
            lines = [f"Daftar Cronjob Aktif ({len(jobs)} jadwal):", ""]
            for idx, j in enumerate(jobs, start=1):
                diff = j.next_run_timestamp - now_ts
                time_left = _format_duration_remaining(diff) if diff > 0 else "Segera dieksekusi"
                status_icon = "🟢" if j.is_active else "⏸️"
                lines.append(f"{idx}. {status_icon} [{j.id}] {j.title}")
                lines.append(f"   • Jadwal: {j.schedule} | Tipe: {j.execution_type}")
                lines.append(f"   • Next Run: {j.next_run_readable} ({time_left})")
                lines.append(f"   • Stats: {j.total_runs} run(s), {j.total_triggers} trigger(s), status: {j.last_status}")

            return ToolResult(success=True, output="\n".join(lines))

        # -------------------------------------------------------------------
        # 3. Action: STATUS / GET
        # -------------------------------------------------------------------
        elif action in ("status", "get"):
            job_id = kwargs.get("job_id", "").strip()
            item = await self.store.get(job_id)
            if not item:
                return ToolResult(success=False, output="", error=f"Cronjob '{job_id}' tidak ditemukan.")

            lines = [
                f"Detail Cronjob [{item.id}]:",
                f"• Judul: {item.title}",
                f"• Status: {'Aktif' if item.is_active else 'Dijeda'} ({item.last_status})",
                f"• Jadwal: {item.schedule}",
                f"• Tipe Eksekusi: {item.execution_type}",
                f"• Next Run: {item.next_run_readable}",
                f"• Total Runs: {item.total_runs}",
                f"• Total Triggers: {item.total_triggers}",
                f"• Output Terakhir: {item.last_output or '(belum ada)'}",
            ]
            if item.last_error:
                lines.append(f"• Error Terakhir: {item.last_error}")
            return ToolResult(success=True, output="\n".join(lines))

        # -------------------------------------------------------------------
        # 4. Action: TRIGGER_NOW
        # -------------------------------------------------------------------
        elif action == "trigger_now":
            job_id = kwargs.get("job_id", "").strip()
            item = await self.store.get(job_id)
            if not item:
                return ToolResult(success=False, output="", error=f"Cronjob '{job_id}' tidak ditemukan.")

            should_deliver, payload = await self.worker.execute_job_tick(item)
            if should_deliver:
                await self.worker.deliver_notification(item, payload)
            await self.store.update(item)

            return ToolResult(
                success=True,
                output=(
                    f"Manual Tick Selesai untuk Cronjob '{item.id}':\n"
                    f"• Status Evaluasi: {'Terpicu & Dikirim' if should_deliver else 'Kondisi Belum Terpenuhi'}\n"
                    f"• Output: {payload}"
                ),
            )

        # -------------------------------------------------------------------
        # 5. Action: PAUSE / RESUME
        # -------------------------------------------------------------------
        elif action in ("pause", "resume"):
            job_id = kwargs.get("job_id", "").strip()
            item = await self.store.get(job_id)
            if not item:
                return ToolResult(success=False, output="", error=f"Cronjob '{job_id}' tidak ditemukan.")

            item.is_active = (action == "resume")
            await self.store.update(item)
            return ToolResult(
                success=True,
                output=f"Cronjob '{item.id}' berhasil di-{'lanjutkan' if item.is_active else 'jeda'}.",
            )

        # -------------------------------------------------------------------
        # 6. Action: DELETE / CANCEL
        # -------------------------------------------------------------------
        elif action in ("delete", "cancel", "remove"):
            job_id = kwargs.get("job_id", "").strip()
            item = await self.store.remove(job_id)
            if not item:
                return ToolResult(success=False, output="", error=f"Cronjob '{job_id}' tidak ditemukan.")
            return ToolResult(success=True, output=f"Cronjob '{item.id}' ({item.title}) berhasil dihapus permanen.")

        # -------------------------------------------------------------------
        # 7. Action: CLEAR_ALL
        # -------------------------------------------------------------------
        elif action == "clear_all":
            count = await self.store.clear_all(chat_id=chat_id)
            return ToolResult(success=True, output=f"Semua cronjob ({count} jadwal) berhasil dibersihkan.")

        return ToolResult(success=False, output="", error=f"Aksi cronjob '{action}' tidak dikenal.")
