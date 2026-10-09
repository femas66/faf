from __future__ import annotations

import asyncio
import datetime
import json
import logging
import urllib.parse
from typing import Any

import httpx

from src.core.android_bridge import bridge
from src.tools.base import BaseTool, ToolContext, ToolResult

logger = logging.getLogger("faf_agent.tools.weather_mgr")

# Default Fallback Location: Lowokwaru, Kota Malang, Jawa Timur
DEFAULT_LOCATION = {
    "name": "Lowokwaru, Kota Malang",
    "district": "Lowokwaru",
    "city": "Kota Malang",
    "province": "Jawa Timur",
    "latitude": -7.9425,
    "longitude": 112.6156,
    "timezone": "Asia/Jakarta",
}

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

# WMO Weather Interpretation Codes (World Meteorological Organization)
WMO_WEATHER_CODES: dict[int, dict[str, Any]] = {
    0: {"label": "Cerah", "emoji": "☀️", "is_rain": False, "rain_risk": "Nihil"},
    1: {"label": "Cerah Berawan", "emoji": "🌤️", "is_rain": False, "rain_risk": "Nihil"},
    2: {"label": "Berawan Sebagian", "emoji": "⛅", "is_rain": False, "rain_risk": "Rendah"},
    3: {"label": "Mendung / Berawan Tebal", "emoji": "☁️", "is_rain": False, "rain_risk": "Sedang"},
    45: {"label": "Berkabut", "emoji": "🌫️", "is_rain": False, "rain_risk": "Rendah"},
    48: {"label": "Kabut Tebal Berembun", "emoji": "🌫️", "is_rain": False, "rain_risk": "Rendah"},
    51: {"label": "Gerimis Ringan", "emoji": "🌦️", "is_rain": True, "rain_risk": "Tinggi"},
    53: {"label": "Gerimis Sedang", "emoji": "🌦️", "is_rain": True, "rain_risk": "Tinggi"},
    55: {"label": "Gerimis Lebat", "emoji": "🌧️", "is_rain": True, "rain_risk": "Sangat Tinggi"},
    56: {"label": "Gerimis Membeku Ringan", "emoji": "🌧️", "is_rain": True, "rain_risk": "Tinggi"},
    57: {"label": "Gerimis Membeku Lebat", "emoji": "🌧️", "is_rain": True, "rain_risk": "Sangat Tinggi"},
    61: {"label": "Hujan Ringan", "emoji": "🌧️", "is_rain": True, "rain_risk": "Tinggi"},
    63: {"label": "Hujan Sedang", "emoji": "🌧️", "is_rain": True, "rain_risk": "Sangat Tinggi"},
    65: {"label": "Hujan Lebat / Deras", "emoji": "⛈️", "is_rain": True, "rain_risk": "Sangat Tinggi"},
    66: {"label": "Hujan Membeku Ringan", "emoji": "🌧️", "is_rain": True, "rain_risk": "Tinggi"},
    67: {"label": "Hujan Membeku Lebat", "emoji": "⛈️", "is_rain": True, "rain_risk": "Sangat Tinggi"},
    71: {"label": "Salju Ringan", "emoji": "🌨️", "is_rain": True, "rain_risk": "Tinggi"},
    73: {"label": "Salju Sedang", "emoji": "🌨️", "is_rain": True, "rain_risk": "Sangat Tinggi"},
    75: {"label": "Salju Lebat", "emoji": "❄️", "is_rain": True, "rain_risk": "Sangat Tinggi"},
    77: {"label": "Butiran Salju", "emoji": "❄️", "is_rain": True, "rain_risk": "Tinggi"},
    80: {"label": "Hujan Rintik-Rintik (Showers)", "emoji": "🌦️", "is_rain": True, "rain_risk": "Tinggi"},
    81: {"label": "Hujan Shower Sedang", "emoji": "🌧️", "is_rain": True, "rain_risk": "Sangat Tinggi"},
    82: {"label": "Hujan Shower Sangat Lebat", "emoji": "⛈️", "is_rain": True, "rain_risk": "Ekstrem"},
    85: {"label": "Hujan Salju Ringan", "emoji": "🌨️", "is_rain": True, "rain_risk": "Tinggi"},
    86: {"label": "Hujan Salju Lebat", "emoji": "❄️", "is_rain": True, "rain_risk": "Sangat Tinggi"},
    95: {"label": "Badai Petir (Thunderstorm)", "emoji": "⛈️", "is_rain": True, "rain_risk": "Ekstrem"},
    96: {"label": "Badai Petir Disertai Hujan Es", "emoji": "⛈️", "is_rain": True, "rain_risk": "Ekstrem"},
    99: {"label": "Badai Petir Ekstrem", "emoji": "⛈️", "is_rain": True, "rain_risk": "Ekstrem"},
}


def _get_wmo_info(code: int) -> dict[str, Any]:
    return WMO_WEATHER_CODES.get(
        code, {"label": f"Kondisi Khusus (Kode {code})", "emoji": "🌡️", "is_rain": False, "rain_risk": "Sedang"}
    )


def _format_readable_dt(dt: datetime.datetime) -> str:
    nama_hari = HARI_INDONESIA[dt.weekday()]
    nama_bulan = BULAN_INDONESIA[dt.month]
    return f"{nama_hari}, {dt.day:02d} {nama_bulan} {dt.year} {dt.strftime('%H:%M')}"


def _wind_direction_label(deg: float) -> str:
    dirs = ["Utara", "Timur Laut", "Timur", "Tenggara", "Selatan", "Barat Daya", "Barat", "Barat Laut"]
    idx = round(deg / 45.0) % 8
    return dirs[idx]


async def resolve_location(
    custom_location: str | None = None,
    force_fallback: bool = False,
) -> tuple[float, float, str, str]:
    """
    Resolve coordinates, location name, and source.
    Returns: (latitude, longitude, location_name, source_description)
    """
    # 1. Custom named location if requested
    if custom_location and custom_location.strip():
        loc_query = custom_location.strip()
        try:
            encoded = urllib.parse.quote(loc_query)
            url = f"https://geocoding-api.open-meteo.com/v1/search?name={encoded}&count=1&language=id&format=json"
            async with httpx.AsyncClient(timeout=8) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    results = data.get("results")
                    if results and len(results) > 0:
                        first = results[0]
                        lat = float(first.get("latitude", DEFAULT_LOCATION["latitude"]))
                        lon = float(first.get("longitude", DEFAULT_LOCATION["longitude"]))
                        name_parts = [first.get("name", loc_query)]
                        if first.get("admin1"):
                            name_parts.append(first["admin1"])
                        if first.get("country"):
                            name_parts.append(first["country"])
                        full_name = ", ".join(name_parts)
                        return lat, lon, full_name, "Pencarian Lokasi Kustom"
        except Exception as e:
            logger.warning(f"Geocoding failed for '{loc_query}': {e}")

    # 2. Check if fallback is forced
    if force_fallback or not bridge.is_android_termux:
        return (
            DEFAULT_LOCATION["latitude"],
            DEFAULT_LOCATION["longitude"],
            DEFAULT_LOCATION["name"],
            "Default (Lowokwaru, Kota Malang)",
        )

    # 3. Check Phone GPS/Location status in Android
    try:
        # Check secure location_mode: 0 = OFF, 1-3 = ON
        res_mode = await bridge.execute_shell("settings get secure location_mode", timeout=3)
        mode_val = res_mode.stdout.strip()
        if mode_val == "0":
            # GPS is explicitly turned OFF on the phone
            logger.info("Android location is disabled (location_mode=0). Falling back to Lowokwaru, Kota Malang.")
            return (
                DEFAULT_LOCATION["latitude"],
                DEFAULT_LOCATION["longitude"],
                DEFAULT_LOCATION["name"],
                "Default (Lokasi HP Nonaktif)",
            )

        # GPS is ON: attempt to fetch actual coordinates via termux-location
        if bridge.has_command("termux-location"):
            # Try last cached location first (instant and doesn't wait for GPS satellite lock)
            res_loc = await bridge.execute_shell("termux-location -r last", timeout=4)
            loc_data: dict[str, Any] = {}
            if res_loc.success and res_loc.stdout.strip():
                try:
                    loc_data = json.loads(res_loc.stdout.strip())
                except Exception:
                    pass

            # If last cached location is empty, try single network location with short timeout
            if not loc_data.get("latitude"):
                res_net = await bridge.execute_shell("termux-location -p network -r once", timeout=4)
                if res_net.success and res_net.stdout.strip():
                    try:
                        loc_data = json.loads(res_net.stdout.strip())
                    except Exception:
                        pass

            lat = loc_data.get("latitude")
            lon = loc_data.get("longitude")
            if lat is not None and lon is not None:
                provider = loc_data.get("provider", "gps")
                accuracy = loc_data.get("accuracy", "N/A")
                desc = f"GPS HP Aktif (Provider: {provider}, Akurasi: {accuracy}m)"
                loc_label = f"Lokasi GPS Ponsel ({lat:.4f}, {lon:.4f})"
                return float(lat), float(lon), loc_label, desc

    except Exception as e:
        logger.warning(f"Failed to query Android location: {e}")

    # Fallback to Lowokwaru, Kota Malang
    return (
        DEFAULT_LOCATION["latitude"],
        DEFAULT_LOCATION["longitude"],
        DEFAULT_LOCATION["name"],
        "Default (GPS Tidak Terdeteksi / Timeout)",
    )


async def fetch_weather_data(
    latitude: float,
    longitude: float,
    forecast_days: int = 3,
) -> dict[str, Any] | None:
    """Fetch live and forecast weather data from Open-Meteo API."""
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "current": (
            "temperature_2m,relative_humidity_2m,apparent_temperature,is_day,"
            "precipitation,rain,showers,weather_code,cloud_cover,pressure_msl,"
            "wind_speed_10m,wind_direction_10m"
        ),
        "hourly": (
            "temperature_2m,relative_humidity_2m,precipitation_probability,"
            "precipitation,rain,weather_code,cloud_cover,wind_speed_10m"
        ),
        "daily": (
            "weather_code,temperature_2m_max,temperature_2m_min,"
            "apparent_temperature_max,apparent_temperature_min,sunrise,sunset,"
            "uv_index_max,precipitation_sum,rain_sum,precipitation_probability_max,"
            "wind_speed_10m_max"
        ),
        "timezone": "Asia/Jakarta",
        "forecast_days": max(1, min(7, forecast_days)),
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, params=params)
            if resp.status_code == 200:
                return resp.json()
            else:
                logger.error(f"Open-Meteo API error {resp.status_code}: {resp.text}")
    except Exception as e:
        logger.error(f"Failed to request weather data: {e}")
    return None


class WeatherForecastTool(BaseTool):
    """Hermes-grade comprehensive weather detection and forecasting tool for faf-agent."""

    name = "weather_forecast"
    description = (
        "Tool komprehensif untuk mendeteksi cuaca saat ini, perkiraan cuaca per jam yang akan datang, "
        "ramalan harian multi-hari, serta evaluasi potensi hujan untuk cronjob. Secara cerdas menggunakan "
        "GPS perangkat fisik jika aktif, atau otomatis fallback ke Lowokwaru, Kota Malang jika lokasi HP nonaktif."
    )

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["current", "hourly", "daily", "check_rain", "full_report"],
                "description": (
                    "Aksi cuaca: 'current' (cuaca terkini), 'hourly' (perkiraan per jam yang akan datang), "
                    "'daily' (ramalan harian 3-7 hari ke depan), 'check_rain' (evaluasi khusus cronjob untuk "
                    "potensi hujan dalam beberapa jam ke depan), 'full_report' (laporan menyeluruh)."
                ),
            },
            "location": {
                "type": "string",
                "description": (
                    "Nama lokasi kustom opsional (contoh: 'Surabaya', 'Jakarta', 'Batu'). Jika dikosongkan, "
                    "sistem otomatis memakai GPS ponsel jika aktif, atau fallback ke Lowokwaru, Kota Malang jika mati."
                ),
            },
            "hours_ahead": {
                "type": "integer",
                "description": "Jumlah jam ke depan untuk perkiraan per jam atau evaluasi hujan (default: 12, range: 1-48).",
                "default": 12,
            },
            "days_ahead": {
                "type": "integer",
                "description": "Jumlah hari ke depan untuk ramalan harian (default: 3, range: 1-7).",
                "default": 3,
            },
            "force_fallback_location": {
                "type": "boolean",
                "description": "Setel True jika ingin langsung menggunakan Lowokwaru, Kota Malang tanpa memeriksa GPS ponsel.",
                "default": False,
            },
        },
        "required": ["action"],
    }

    async def execute(self, context: ToolContext, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action", "current").lower().strip()
        custom_loc = kwargs.get("location")
        hours_ahead = max(1, min(48, kwargs.get("hours_ahead", 12)))
        days_ahead = max(1, min(7, kwargs.get("days_ahead", 3)))
        force_fallback = kwargs.get("force_fallback_location", False)

        # 1. Resolve Location (GPS vs Lowokwaru, Malang vs Custom)
        lat, lon, loc_name, loc_source = await resolve_location(
            custom_location=custom_loc,
            force_fallback=force_fallback,
        )

        # 2. Fetch Live Weather Data from Open-Meteo
        weather_data = await fetch_weather_data(lat, lon, forecast_days=days_ahead)
        if not weather_data:
            return ToolResult(
                success=False,
                output="",
                error=(
                    f"Gagal mengambil data cuaca untuk lokasi '{loc_name}'. "
                    "Pastikan perangkat memiliki koneksi internet aktif."
                ),
            )

        current = weather_data.get("current", {})
        hourly = weather_data.get("hourly", {})
        daily = weather_data.get("daily", {})

        now_dt = datetime.datetime.now().astimezone()
        curr_code = current.get("weather_code", 0)
        curr_wmo = _get_wmo_info(curr_code)

        # -------------------------------------------------------------------
        # A. Action: CURRENT (Cuaca Saat Ini)
        # -------------------------------------------------------------------
        if action == "current":
            lines = [
                f"KONDISI CUACA TERKINI",
                f"• Lokasi: {loc_name}",
                f"• Sumber Koordinat: {loc_source}",
                f"• Waktu Pantau: {_format_readable_dt(now_dt)}",
                f"• Status Cuaca: {curr_wmo['emoji']} {curr_wmo['label']}",
                f"• Suhu Aktual: {current.get('temperature_2m', 'N/A')} °C",
                f"• Suhu Terasa: {current.get('apparent_temperature', 'N/A')} °C",
                f"• Kelembaban Udara: {current.get('relative_humidity_2m', 'N/A')} %",
                f"• Tutupan Awan: {current.get('cloud_cover', 'N/A')} %",
                f"• Curah Hujan Saat Ini: {current.get('precipitation', 0.0)} mm",
                f"• Kecepatan Angin: {current.get('wind_speed_10m', 'N/A')} km/jam ({_wind_direction_label(current.get('wind_direction_10m', 0))})",
                f"• Tekanan Udara: {current.get('pressure_msl', 'N/A')} hPa",
            ]
            if curr_wmo["is_rain"]:
                lines.append("• Peringatan: Saat ini sedang berlangsung hujan/gerimis.")
            return ToolResult(success=True, output="\n".join(lines))

        # -------------------------------------------------------------------
        # B. Action: HOURLY (Prakiraan Jam ke Jam)
        # -------------------------------------------------------------------
        elif action == "hourly":
            times = hourly.get("time", [])
            temps = hourly.get("temperature_2m", [])
            probs = hourly.get("precipitation_probability", [])
            rains = hourly.get("precipitation", [])
            codes = hourly.get("weather_code", [])

            lines = [
                f"PRAKIRAAN CUACA PER JAM ({hours_ahead} JAM KE DEPAN)",
                f"• Lokasi: {loc_name}",
                f"• Sumber Koordinat: {loc_source}",
                "",
            ]

            curr_iso_prefix = now_dt.strftime("%Y-%m-%dT%H")
            start_idx = 0
            for idx, t_str in enumerate(times):
                if t_str.startswith(curr_iso_prefix):
                    start_idx = idx
                    break

            displayed = 0
            for i in range(start_idx, min(len(times), start_idx + hours_ahead)):
                t_raw = times[i]
                t_dt = datetime.datetime.fromisoformat(t_raw)
                w_info = _get_wmo_info(codes[i] if i < len(codes) else 0)
                temp = temps[i] if i < len(temps) else "-"
                prob = probs[i] if i < len(probs) else 0
                rain_mm = rains[i] if i < len(rains) else 0.0

                time_label = t_dt.strftime("%H:%M")
                day_label = HARI_INDONESIA[t_dt.weekday()]
                lines.append(
                    f"• {day_label} {time_label}: {w_info['emoji']} {w_info['label']} | {temp}°C | Peluang Hujan: {prob}% ({rain_mm} mm)"
                )
                displayed += 1

            return ToolResult(success=True, output="\n".join(lines))

        # -------------------------------------------------------------------
        # C. Action: DAILY (Ramalan Harian)
        # -------------------------------------------------------------------
        elif action == "daily":
            d_times = daily.get("time", [])
            d_codes = daily.get("weather_code", [])
            t_max = daily.get("temperature_2m_max", [])
            t_min = daily.get("temperature_2m_min", [])
            p_max = daily.get("precipitation_probability_max", [])
            uv_max = daily.get("uv_index_max", [])
            sunrises = daily.get("sunrise", [])
            sunsets = daily.get("sunset", [])

            lines = [
                f"PRAKIRAAN CUACA HARIAN ({len(d_times)} HARI KE DEPAN)",
                f"• Lokasi: {loc_name}",
                f"• Sumber Koordinat: {loc_source}",
                "",
            ]

            for i in range(len(d_times)):
                d_dt = datetime.date.fromisoformat(d_times[i])
                day_name = HARI_INDONESIA[d_dt.weekday()]
                w_info = _get_wmo_info(d_codes[i] if i < len(d_codes) else 0)
                t_hi = t_max[i] if i < len(t_max) else "-"
                t_lo = t_min[i] if i < len(t_min) else "-"
                p_hi = p_max[i] if i < len(p_max) else 0
                uv = uv_max[i] if i < len(uv_max) else "-"

                sr = sunrises[i].split("T")[1][:5] if i < len(sunrises) and "T" in sunrises[i] else "-"
                ss = sunsets[i].split("T")[1][:5] if i < len(sunsets) and "T" in sunsets[i] else "-"

                lines.append(f"{i + 1}. {day_name}, {d_dt.day:02d} {BULAN_INDONESIA[d_dt.month]} {d_dt.year}:")
                lines.append(f"   • Cuaca Dominan: {w_info['emoji']} {w_info['label']}")
                lines.append(f"   • Rentang Suhu: {t_lo}°C s/d {t_hi}°C")
                lines.append(f"   • Peluang Hujan Puncak: {p_hi}%")
                lines.append(f"   • Indeks UV Maksimal: {uv}")
                lines.append(f"   • Matahari: Terbit {sr} | Terbenam {ss}")
                lines.append("")

            return ToolResult(success=True, output="\n".join(lines).strip())

        # -------------------------------------------------------------------
        # D. Action: CHECK_RAIN / RAIN_ALERT (Khusus Cronjob & Deteksi Hujan Cepat)
        # -------------------------------------------------------------------
        elif action in ("check_rain", "rain_alert"):
            times = hourly.get("time", [])
            probs = hourly.get("precipitation_probability", [])
            rains = hourly.get("precipitation", [])
            codes = hourly.get("weather_code", [])

            curr_iso_prefix = now_dt.strftime("%Y-%m-%dT%H")
            start_idx = 0
            for idx, t_str in enumerate(times):
                if t_str.startswith(curr_iso_prefix):
                    start_idx = idx
                    break

            check_window = min(len(times) - start_idx, max(1, hours_ahead))
            will_rain = False
            max_prob = 0
            rain_hours: list[str] = []
            highest_intensity = "Nihil"
            first_rain_time: str | None = None

            for i in range(start_idx, start_idx + check_window):
                prob = probs[i] if i < len(probs) else 0
                rain_mm = rains[i] if i < len(rains) else 0.0
                code = codes[i] if i < len(codes) else 0
                w_info = _get_wmo_info(code)

                if prob > max_prob:
                    max_prob = prob

                # Rain detected if probability >= 50% or precipitation >= 0.2mm or code indicates rain
                if prob >= 50 or rain_mm >= 0.2 or w_info["is_rain"]:
                    will_rain = True
                    t_lbl = times[i].split("T")[1][:5]
                    rain_hours.append(f"{t_lbl} ({prob}%, {w_info['label']})")
                    if not first_rain_time:
                        first_rain_time = t_lbl

                    if "Lebat" in w_info["label"] or "Deras" in w_info["label"] or "Petir" in w_info["label"]:
                        highest_intensity = "Lebat / Deras"
                    elif "Sedang" in w_info["label"] and highest_intensity != "Lebat / Deras":
                        highest_intensity = "Sedang"
                    elif highest_intensity == "Nihil":
                        highest_intensity = "Ringan / Gerimis"

            # Machine & Human Readable output for cronjob condition evaluation
            lines = [
                f"EVALUASI DETEKSI HUJAN (Jendela: {check_window} Jam ke Depan)",
                f"• Lokasi: {loc_name} ({loc_source})",
                f"• Status Deteksi: {'POTENSI HUJAN TERDETEKSI' if will_rain else 'CUACA AMAN / TIDAK ADA HUJAN'}",
                f"• Nilai Evaluasi (will_rain): {'TRUE' if will_rain else 'FALSE'}",
                f"• Peluang Hujan Maksimal: {max_prob}%",
                f"• Perkiraan Jam Mulai Hujan: {first_rain_time or 'Tidak ada dalam rentang ini'}",
                f"• Tingkat Intensitas: {highest_intensity}",
            ]

            if rain_hours:
                lines.append(f"• Rincian Jam Berpotensi: {', '.join(rain_hours[:4])}")

            if will_rain:
                lines.append(
                    f"• Rekomendasi Agen: Bawa payung/jas hujan dan amankan jemuran sebelum pukul {first_rain_time or 'siang'}."
                )
            else:
                lines.append("• Rekomendasi Agen: Kondisi cerah/berawan, aman untuk beraktivitas luar ruangan.")

            return ToolResult(success=True, output="\n".join(lines))

        # -------------------------------------------------------------------
        # E. Action: FULL_REPORT (Laporan Lengkap)
        # -------------------------------------------------------------------
        elif action == "full_report":
            # Current
            lines = [
                f"LAPORAN CUACA LENGKAP & PREDIKSI",
                f"• Lokasi: {loc_name}",
                f"• Sumber Koordinat: {loc_source}",
                f"• Waktu Pantau: {_format_readable_dt(now_dt)}",
                "",
                f"1. Kondisi Saat Ini:",
                f"   • Status: {curr_wmo['emoji']} {curr_wmo['label']}",
                f"   • Suhu: {current.get('temperature_2m')} °C (Terasa seperti {current.get('apparent_temperature')} °C)",
                f"   • Kelembaban: {current.get('relative_humidity_2m')} %",
                f"   • Angin: {current.get('wind_speed_10m')} km/jam ({_wind_direction_label(current.get('wind_direction_10m', 0))})",
                "",
                f"2. Ringkasan 6 Jam ke Depan:",
            ]

            # Next 6 hours
            times = hourly.get("time", [])
            temps = hourly.get("temperature_2m", [])
            probs = hourly.get("precipitation_probability", [])
            codes = hourly.get("weather_code", [])
            curr_iso_prefix = now_dt.strftime("%Y-%m-%dT%H")
            start_idx = 0
            for idx, t_str in enumerate(times):
                if t_str.startswith(curr_iso_prefix):
                    start_idx = idx
                    break

            for i in range(start_idx, min(len(times), start_idx + 6)):
                t_lbl = times[i].split("T")[1][:5]
                w_info = _get_wmo_info(codes[i] if i < len(codes) else 0)
                temp = temps[i] if i < len(temps) else "-"
                prob = probs[i] if i < len(probs) else 0
                lines.append(f"   • Pukul {t_lbl}: {w_info['emoji']} {w_info['label']}, {temp}°C, Hujan {prob}%")

            # 3 Days ahead
            d_times = daily.get("time", [])
            d_codes = daily.get("weather_code", [])
            t_max = daily.get("temperature_2m_max", [])
            t_min = daily.get("temperature_2m_min", [])
            p_max = daily.get("precipitation_probability_max", [])

            lines.append("")
            lines.append(f"3. Ramalan 3 Hari ke Depan:")
            for i in range(min(3, len(d_times))):
                d_dt = datetime.date.fromisoformat(d_times[i])
                day_name = HARI_INDONESIA[d_dt.weekday()]
                w_info = _get_wmo_info(d_codes[i] if i < len(d_codes) else 0)
                t_hi = t_max[i] if i < len(t_max) else "-"
                t_lo = t_min[i] if i < len(t_min) else "-"
                p_hi = p_max[i] if i < len(p_max) else 0
                lines.append(
                    f"   • {day_name} ({d_dt.day:02d}/{d_dt.month:02d}): {w_info['emoji']} {w_info['label']} | {t_lo}°C - {t_hi}°C | Peluang Hujan {p_hi}%"
                )

            return ToolResult(success=True, output="\n".join(lines))

        return ToolResult(
            success=False,
            output="",
            error=f"Aksi weather_forecast '{action}' tidak dikenal. Pilihan: 'current', 'hourly', 'daily', 'check_rain', 'full_report'.",
        )
