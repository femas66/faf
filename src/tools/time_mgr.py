from __future__ import annotations

import calendar
import datetime
import logging
import os
import time
import zoneinfo
from typing import Any

from src.core.android_bridge import bridge
from src.tools.base import BaseTool, ToolContext, ToolResult

logger = logging.getLogger("faf_agent.tools.time_mgr")

# Indonesian localization names
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

# Major World Timezones
WORLD_TIMEZONES = [
    ("WIB (Jakarta / Indonesia Barat)", "Asia/Jakarta"),
    ("WITA (Makassar / Indonesia Tengah)", "Asia/Makassar"),
    ("WIT (Jayapura / Indonesia Timur)", "Asia/Jayapura"),
    ("UTC / GMT (Waktu Standar Universal)", "UTC"),
    ("Mekkah (Arab Saudi)", "Asia/Riyadh"),
    ("Tokyo (Jepang)", "Asia/Tokyo"),
    ("Singapura", "Asia/Singapore"),
    ("London (Inggris)", "Europe/London"),
    ("New York (Amerika Serikat)", "America/New_York"),
    ("Sydney (Australia)", "Australia/Sydney"),
]


def _parse_datetime(dt_str: str) -> datetime.datetime:
    """Parse string into datetime object with multi-format fallback."""
    dt_str = dt_str.strip()
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%d-%m-%Y %H:%M:%S",
        "%d-%m-%Y",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y",
    ]
    for fmt in formats:
        try:
            return datetime.datetime.strptime(dt_str, fmt)
        except ValueError:
            pass
    try:
        return datetime.datetime.fromisoformat(dt_str)
    except Exception:
        pass
    raise ValueError(f"Format tanggal/waktu tidak dikenali: '{dt_str}'. Gunakan format YYYY-MM-DD atau YYYY-MM-DD HH:MM:SS.")


def _format_duration(seconds: float) -> str:
    """Format seconds into readable days, hours, minutes, seconds."""
    sec = int(abs(seconds))
    days = sec // 86400
    hours = (sec % 86400) // 3600
    minutes = (sec % 3600) // 60
    rem_seconds = sec % 60

    parts = []
    if days > 0:
        parts.append(f"{days} hari")
    if hours > 0 or days > 0:
        parts.append(f"{hours} jam")
    if minutes > 0 or hours > 0 or days > 0:
        parts.append(f"{minutes} menit")
    parts.append(f"{rem_seconds} detik")
    return ", ".join(parts)


class TimeManagerTool(BaseTool):
    """Dedicated all-in-one tool for comprehensive time, date, timezone, uptime, and calendar operations."""

    name = "time_manager"
    description = (
        "Tool khusus dan lengkap untuk mengecek serta menghitung semua tentang waktu, jam, tanggal, "
        "hari, zona waktu (timezone), uptime perangkat Android, waktu dunia (world clock), hitung mundur "
        "(countdown), selisih durasi, dan kalender. AI WAJIB menggunakan tool ini daripada perintah shell."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "now",
                    "uptime",
                    "world_clock",
                    "timezone_info",
                    "time_diff",
                    "add_subtract",
                    "calendar_info",
                ],
                "description": (
                    "Aksi waktu yang diinginkan: "
                    "'now' (waktu & tanggal lokal lengkap), "
                    "'uptime' (durasi aktif perangkat sejak boot), "
                    "'world_clock' (waktu di berbagai kota dunia atau zona tertentu), "
                    "'timezone_info' (informasi detail zona waktu lokal & konfigurasi Android), "
                    "'time_diff' (selisih durasi atau countdown menuju tanggal tertentu), "
                    "'add_subtract' (tambah/kurang hari/jam/menit dari waktu saat ini), "
                    "'calendar_info' (detail kalender bulan, tahun kabisat, sisa hari)."
                ),
            },
            "target_timezone": {
                "type": "string",
                "description": (
                    "Nama zona waktu spesifik untuk 'world_clock' (contoh: 'Asia/Tokyo', 'Asia/Jayapura', "
                    "'America/New_York', 'UTC', 'Europe/London'). Opsional."
                ),
            },
            "target_datetime": {
                "type": "string",
                "description": (
                    "Tanggal/waktu tujuan untuk 'time_diff' (contoh: '2026-12-31 23:59:59' atau '2027-01-01')."
                ),
            },
            "source_datetime": {
                "type": "string",
                "description": (
                    "Tanggal/waktu asal untuk 'time_diff'. Jika dikosongkan, menggunakan waktu sekarang."
                ),
            },
            "operation": {
                "type": "string",
                "enum": ["add", "subtract"],
                "description": "Operasi penambahan ('add') atau pengurangan ('subtract') untuk 'add_subtract'.",
                "default": "add",
            },
            "days": {
                "type": "integer",
                "description": "Jumlah hari yang ingin ditambah/dikurang pada 'add_subtract'.",
                "default": 0,
            },
            "hours": {
                "type": "integer",
                "description": "Jumlah jam yang ingin ditambah/dikurang pada 'add_subtract'.",
                "default": 0,
            },
            "minutes": {
                "type": "integer",
                "description": "Jumlah menit yang ingin ditambah/dikurang pada 'add_subtract'.",
                "default": 0,
            },
            "base_datetime": {
                "type": "string",
                "description": (
                    "Tanggal/waktu acuan untuk 'add_subtract'. Jika kosong, menggunakan waktu saat ini."
                ),
            },
        },
        "required": ["action"],
    }

    async def execute(self, context: ToolContext, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action", "now").lower()

        if context.on_status_update:
            await context.on_status_update(f"● time_manager · {action}")

        # -------------------------------------------------------------------
        # 1. Action: NOW (Current Detailed Time & Date)
        # -------------------------------------------------------------------
        if action in ("now", "current_time"):
            now_local = datetime.datetime.now().astimezone()
            now_utc = datetime.datetime.now(datetime.timezone.utc)

            weekday_num = now_local.weekday()
            nama_hari = HARI_INDONESIA[weekday_num]
            nama_bulan = BULAN_INDONESIA[now_local.month]

            day_of_year = now_local.timetuple().tm_yday
            is_leap = calendar.isleap(now_local.year)
            total_days_year = 366 if is_leap else 365
            week_number = now_local.isocalendar().week

            tz_name = now_local.tzname() or "Lokal"
            tz_offset = now_local.strftime("%z")
            formatted_offset = f"UTC{tz_offset[:3]}:{tz_offset[3:]}" if len(tz_offset) == 5 else tz_offset

            epoch_sec = int(time.time())
            epoch_ms = int(time.time() * 1000)

            output = (
                "Informasi Waktu & Tanggal Saat Ini:\n\n"
                f"• Tanggal Lengkap: {nama_hari}, {now_local.day:02d} {nama_bulan} {now_local.year}\n"
                f"• Jam (24 Jam): {now_local.strftime('%H:%M:%S')}\n"
                f"• Jam (12 Jam): {now_local.strftime('%I:%M:%S %p')}\n"
                f"• Zona Waktu: {tz_name} ({formatted_offset})\n"
                f"• Waktu Standar UTC/GMT: {now_utc.strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
                f"• Hari ke-: {now_local.day} (Hari ke-{day_of_year} dari {total_days_year} dalam tahun ini)\n"
                f"• Minggu ke-: {week_number} dari 52/53 minggu\n"
                f"• Unix Epoch: {epoch_sec} detik ({epoch_ms} ms)\n"
                f"• Format Standar ISO 8601: {now_local.isoformat()}\n"
                f"• Tahun Kabisat: {'Ya' if is_leap else 'Bukan tahun kabisat'}"
            )
            return ToolResult(success=True, output=output)

        # -------------------------------------------------------------------
        # 2. Action: UPTIME (Android System Uptime & Boot Time)
        # -------------------------------------------------------------------
        elif action == "uptime":
            uptime_sec: float | None = None
            idle_sec: float | None = None

            # Read /proc/uptime (standard Linux & Android)
            if os.path.exists("/proc/uptime"):
                try:
                    with open("/proc/uptime", "r") as f:
                        parts = f.read().split()
                        if len(parts) >= 2:
                            uptime_sec = float(parts[0])
                            idle_sec = float(parts[1])
                except Exception:
                    pass

            # Fallback via shell if /proc/uptime is unreadable
            if uptime_sec is None:
                res = await bridge.execute_shell("cat /proc/uptime || uptime", timeout=5)
                if res.success and res.stdout:
                    parts = res.stdout.split()
                    try:
                        uptime_sec = float(parts[0])
                    except (ValueError, IndexError):
                        pass

            if uptime_sec is not None:
                duration_str = _format_duration(uptime_sec)
                now_dt = datetime.datetime.now()
                boot_dt = now_dt - datetime.timedelta(seconds=uptime_sec)
                boot_day = HARI_INDONESIA[boot_dt.weekday()]
                boot_month = BULAN_INDONESIA[boot_dt.month]

                output_parts = [
                    "Informasi Uptime & Aktivitas Perangkat:\n",
                    f"• Durasi Aktif (Uptime): {duration_str}",
                    f"• Waktu Terakhir Dinyalakan (Boot Time): {boot_day}, {boot_dt.day:02d} {boot_month} {boot_dt.year} {boot_dt.strftime('%H:%M:%S')}",
                    f"• Total Detik Aktif: {int(uptime_sec)} detik",
                ]

                if idle_sec is not None and uptime_sec > 0:
                    idle_str = _format_duration(idle_sec)
                    output_parts.append(f"• Total Waktu Idle/Tidur: {idle_str}")

                return ToolResult(success=True, output="\n".join(output_parts))
            else:
                return ToolResult(
                    success=True,
                    output="Tidak dapat membaca /proc/uptime secara langsung pada lingkungan sistem ini.",
                )

        # -------------------------------------------------------------------
        # 3. Action: WORLD_CLOCK (Major Cities / Custom Timezone)
        # -------------------------------------------------------------------
        elif action == "world_clock":
            target_tz = kwargs.get("target_timezone", "").strip()

            if target_tz:
                # Query specific timezone
                try:
                    tz_obj = zoneinfo.ZoneInfo(target_tz)
                    dt_target = datetime.datetime.now(tz_obj)
                    day_name = HARI_INDONESIA[dt_target.weekday()]
                    month_name = BULAN_INDONESIA[dt_target.month]
                    out = (
                        f"Waktu di Zona '{target_tz}':\n\n"
                        f"• Tanggal: {day_name}, {dt_target.day:02d} {month_name} {dt_target.year}\n"
                        f"• Jam: {dt_target.strftime('%H:%M:%S')} ({dt_target.strftime('%I:%M:%S %p')})\n"
                        f"• Zona: {dt_target.tzname()} (UTC{dt_target.strftime('%z')})\n"
                        f"• Format ISO: {dt_target.isoformat()}"
                    )
                    return ToolResult(success=True, output=out)
                except Exception as e:
                    return ToolResult(
                        success=False,
                        output="",
                        error=f"Zona waktu '{target_tz}' tidak valid atau tidak ditemukan dalam database tz: {str(e)}",
                    )
            else:
                # Summary of major global cities & Indonesia regions
                items = []
                for label, tz_name in WORLD_TIMEZONES:
                    try:
                        tz_obj = zoneinfo.ZoneInfo(tz_name)
                        dt = datetime.datetime.now(tz_obj)
                        time_str = dt.strftime("%H:%M:%S")
                        date_str = dt.strftime("%d-%m-%Y")
                        items.append(f"• {label}: {time_str} ({date_str})")
                    except Exception:
                        pass

                output = "Waktu Dunia Saat Ini:\n\n" + "\n".join(items)
                return ToolResult(success=True, output=output)

        # -------------------------------------------------------------------
        # 4. Action: TIMEZONE_INFO (Detailed Android / System Timezone)
        # -------------------------------------------------------------------
        elif action == "timezone_info":
            now_local = datetime.datetime.now().astimezone()
            tz_name = now_local.tzname() or "Unknown"
            tz_offset = now_local.strftime("%z")
            formatted_offset = f"UTC{tz_offset[:3]}:{tz_offset[3:]}" if len(tz_offset) == 5 else tz_offset
            is_dst = bool(now_local.dst())

            # Read Android system properties via getprop or settings
            android_tz = "Tidak terdeteksi"
            auto_time = "Tidak terdeteksi"
            auto_tz = "Tidak terdeteksi"

            res_prop = await bridge.execute_shell("getprop persist.sys.timezone", timeout=4)
            if res_prop.success and res_prop.stdout:
                android_tz = res_prop.stdout.strip()

            res_autotime = await bridge.execute_shell("settings get global auto_time", timeout=4)
            if res_autotime.success and res_autotime.stdout:
                val = res_autotime.stdout.strip()
                auto_time = "Aktif (Otomatis dari Jaringan Seluler/NTP)" if val == "1" else "Manual"

            res_autotz = await bridge.execute_shell("settings get global auto_time_zone", timeout=4)
            if res_autotz.success and res_autotz.stdout:
                val = res_autotz.stdout.strip()
                auto_tz = "Aktif (Otomatis dari Jaringan Seluler)" if val == "1" else "Manual"

            output = (
                "Informasi Zona Waktu & Sinkronisasi Jam Sistem:\n\n"
                f"• Zona Waktu Lokal: {tz_name}\n"
                f"• Selisih Waktu UTC: {formatted_offset}\n"
                f"• Status Daylight Saving (DST): {'Aktif' if is_dst else 'Tidak Aktif'}\n"
                f"• Properti Zona Android (persist.sys.timezone): {android_tz}\n"
                f"• Sinkronisasi Jam Otomatis (auto_time): {auto_time}\n"
                f"• Zona Waktu Otomatis (auto_time_zone): {auto_tz}\n"
                f"• Variabel Lingkungan TZ: {os.environ.get('TZ', 'Mengikuti sistem')}"
            )
            return ToolResult(success=True, output=output)

        # -------------------------------------------------------------------
        # 5. Action: TIME_DIFF (Countdown / Duration Between Dates)
        # -------------------------------------------------------------------
        elif action in ("time_diff", "countdown"):
            target_str = kwargs.get("target_datetime", "").strip()
            if not target_str:
                return ToolResult(
                    success=False,
                    output="",
                    error="Parameter 'target_datetime' wajib diisi (contoh: '2026-12-31' atau '2026-12-31 23:59:59').",
                )

            try:
                target_dt = _parse_datetime(target_str)
            except ValueError as e:
                return ToolResult(success=False, output="", error=str(e))

            source_str = kwargs.get("source_datetime", "").strip()
            if source_str:
                try:
                    source_dt = _parse_datetime(source_str)
                except ValueError as e:
                    return ToolResult(success=False, output="", error=str(e))
            else:
                source_dt = datetime.datetime.now()

            delta = target_dt - source_dt
            total_sec = delta.total_seconds()
            is_past = total_sec < 0

            dur_str = _format_duration(total_sec)
            status_relatif = "telah berlalu sejak" if is_past else "menuju ke"

            total_hari = abs(int(total_sec // 86400))
            total_jam = abs(int(total_sec // 3600))
            total_menit = abs(int(total_sec // 60))

            output = (
                f"Perhitungan Selisih Waktu & Countdown:\n\n"
                f"• Waktu Acuan: {source_dt.strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"• Waktu Target: {target_dt.strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"• Status: {status_relatif.capitalize()} waktu target ({'Sudah lewat' if is_past else 'Akan datang'})\n"
                f"• Durasi Selisih: {dur_str}\n"
                f"• Rincian Total Hari: {total_hari} hari\n"
                f"• Rincian Total Jam: {total_jam} jam\n"
                f"• Rincian Total Menit: {total_menit} menit\n"
                f"• Rincian Total Detik: {abs(int(total_sec))} detik"
            )
            return ToolResult(success=True, output=output)

        # -------------------------------------------------------------------
        # 6. Action: ADD_SUBTRACT (Add or Subtract Duration)
        # -------------------------------------------------------------------
        elif action in ("add_subtract", "calculate"):
            op = kwargs.get("operation", "add").lower()
            days = kwargs.get("days", 0)
            hours = kwargs.get("hours", 0)
            minutes = kwargs.get("minutes", 0)

            base_str = kwargs.get("base_datetime", "").strip()
            if base_str:
                try:
                    base_dt = _parse_datetime(base_str)
                except ValueError as e:
                    return ToolResult(success=False, output="", error=str(e))
            else:
                base_dt = datetime.datetime.now()

            delta = datetime.timedelta(days=days, hours=hours, minutes=minutes)
            if op == "subtract":
                result_dt = base_dt - delta
                op_label = "Pengurangan"
            else:
                result_dt = base_dt + delta
                op_label = "Penambahan"

            res_day = HARI_INDONESIA[result_dt.weekday()]
            res_month = BULAN_INDONESIA[result_dt.month]

            output = (
                f"Hasil Perhitungan Waktu ({op_label}):\n\n"
                f"• Waktu Awal: {base_dt.strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"• Perubahan Durasi: {days} hari, {hours} jam, {minutes} menit\n"
                f"• Hasil Tanggal & Waktu Baru: {res_day}, {result_dt.day:02d} {res_month} {result_dt.year} {result_dt.strftime('%H:%M:%S')}\n"
                f"• Format ISO 8601: {result_dt.isoformat()}"
            )
            return ToolResult(success=True, output=output)

        # -------------------------------------------------------------------
        # 7. Action: CALENDAR_INFO (Calendar & Days Details)
        # -------------------------------------------------------------------
        elif action == "calendar_info":
            now = datetime.datetime.now()
            year = now.year
            month = now.month

            is_leap = calendar.isleap(year)
            month_days = calendar.monthrange(year, month)[1]
            first_weekday = calendar.monthrange(year, month)[0]

            sisa_hari_bulan = month_days - now.day
            day_of_year = now.timetuple().tm_yday
            total_days_year = 366 if is_leap else 365
            sisa_hari_tahun = total_days_year - day_of_year

            quarter = (month - 1) // 3 + 1

            output = (
                f"Informasi Kalender ({BULAN_INDONESIA[month]} {year}):\n\n"
                f"• Bulan: {BULAN_INDONESIA[month]} (Bulan ke-{month})\n"
                f"• Tahun: {year} ({'Tahun Kabisat - 366 hari' if is_leap else 'Bukan Tahun Kabisat - 365 hari'})\n"
                f"• Kuartal: Q{quarter} (Kuartal ke-{quarter})\n"
                f"• Jumlah Hari Bulan Ini: {month_days} hari\n"
                f"• Hari Pertama Bulan Ini: {HARI_INDONESIA[first_weekday]}\n"
                f"• Posisi Hari Ini: Tanggal {now.day}\n"
                f"• Sisa Hari Bulan Ini: {sisa_hari_bulan} hari lagi\n"
                f"• Sisa Hari Tahun Ini: {sisa_hari_tahun} hari lagi menuju tahun baru {year + 1}"
            )
            return ToolResult(success=True, output=output)

        return ToolResult(
            success=False,
            output="",
            error=f"Aksi waktu '{action}' tidak dikenal. Pilih salah satu dari: now, uptime, world_clock, timezone_info, time_diff, add_subtract, calendar_info.",
        )
