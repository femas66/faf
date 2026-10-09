from __future__ import annotations

import pytest
from unittest.mock import patch, AsyncMock

from src.tools.base import ToolContext
from src.tools.weather_mgr import (
    WeatherForecastTool,
    resolve_location,
    _get_wmo_info,
    DEFAULT_LOCATION,
)

SAMPLE_WEATHER_API_RESPONSE = {
    "current": {
        "time": "2026-10-09T10:00",
        "temperature_2m": 28.5,
        "relative_humidity_2m": 65,
        "apparent_temperature": 31.0,
        "precipitation": 0.0,
        "weather_code": 2,
        "cloud_cover": 40,
        "wind_speed_10m": 5.5,
        "wind_direction_10m": 120,
        "pressure_msl": 1012.0,
    },
    "hourly": {
        "time": [
            "2026-10-09T10:00",
            "2026-10-09T11:00",
            "2026-10-09T12:00",
            "2026-10-09T13:00",
            "2026-10-09T14:00",
            "2026-10-09T15:00",
        ],
        "temperature_2m": [28.5, 29.0, 30.2, 29.5, 27.0, 25.5],
        "precipitation_probability": [10, 15, 20, 65, 80, 40],
        "precipitation": [0.0, 0.0, 0.0, 1.5, 4.2, 0.5],
        "weather_code": [2, 2, 3, 61, 65, 80],
        "cloud_cover": [40, 50, 70, 90, 95, 60],
        "wind_speed_10m": [5.5, 6.0, 7.2, 8.5, 10.0, 6.0],
    },
    "daily": {
        "time": ["2026-10-09", "2026-10-10", "2026-10-11"],
        "weather_code": [63, 2, 0],
        "temperature_2m_max": [30.5, 31.0, 32.0],
        "temperature_2m_min": [21.0, 22.0, 21.5],
        "precipitation_probability_max": [85, 20, 5],
        "uv_index_max": [8.5, 9.0, 9.2],
        "sunrise": ["2026-10-09T05:22", "2026-10-10T05:21", "2026-10-11T05:21"],
        "sunset": ["2026-10-09T17:35", "2026-10-10T17:35", "2026-10-11T17:35"],
    },
}


def test_wmo_code_mappings():
    clear = _get_wmo_info(0)
    assert clear["label"] == "Cerah"
    assert clear["is_rain"] is False

    drizzle = _get_wmo_info(51)
    assert drizzle["is_rain"] is True

    heavy_rain = _get_wmo_info(65)
    assert heavy_rain["is_rain"] is True
    assert "Deras" in heavy_rain["label"] or "Lebat" in heavy_rain["label"]

    thunder = _get_wmo_info(95)
    assert "Petir" in thunder["label"]


@pytest.mark.asyncio
async def test_resolve_location_fallback():
    # Force fallback or desktop environment
    lat, lon, name, source = await resolve_location(force_fallback=True)
    assert lat == DEFAULT_LOCATION["latitude"]
    assert lon == DEFAULT_LOCATION["longitude"]
    assert "Lowokwaru" in name
    assert "Malang" in name


@pytest.mark.asyncio
async def test_weather_tool_current_action():
    tool = WeatherForecastTool()
    ctx = ToolContext(chat_id=123, user_id=123)

    with patch("src.tools.weather_mgr.fetch_weather_data", new=AsyncMock(return_value=SAMPLE_WEATHER_API_RESPONSE)):
        res = await tool.execute(ctx, action="current", force_fallback_location=True)
        assert res.success is True
        assert "KONDISI CUACA TERKINI" in res.output
        assert "Lowokwaru, Kota Malang" in res.output
        assert "28.5 °C" in res.output
        assert "Berawan Sebagian" in res.output


@pytest.mark.asyncio
async def test_weather_tool_hourly_action():
    tool = WeatherForecastTool()
    ctx = ToolContext(chat_id=123, user_id=123)

    with patch("src.tools.weather_mgr.fetch_weather_data", new=AsyncMock(return_value=SAMPLE_WEATHER_API_RESPONSE)):
        res = await tool.execute(ctx, action="hourly", hours_ahead=5, force_fallback_location=True)
        assert res.success is True
        assert "PRAKIRAAN CUACA PER JAM" in res.output
        assert "Peluang Hujan:" in res.output


@pytest.mark.asyncio
async def test_weather_tool_daily_action():
    tool = WeatherForecastTool()
    ctx = ToolContext(chat_id=123, user_id=123)

    with patch("src.tools.weather_mgr.fetch_weather_data", new=AsyncMock(return_value=SAMPLE_WEATHER_API_RESPONSE)):
        res = await tool.execute(ctx, action="daily", days_ahead=3, force_fallback_location=True)
        assert res.success is True
        assert "PRAKIRAAN CUACA HARIAN" in res.output
        assert "Rentang Suhu:" in res.output
        assert "Matahari:" in res.output


@pytest.mark.asyncio
async def test_weather_tool_check_rain_cronjob():
    tool = WeatherForecastTool()
    ctx = ToolContext(chat_id=123, user_id=123)

    with patch("src.tools.weather_mgr.fetch_weather_data", new=AsyncMock(return_value=SAMPLE_WEATHER_API_RESPONSE)):
        res = await tool.execute(ctx, action="check_rain", hours_ahead=6, force_fallback_location=True)
        assert res.success is True
        assert "EVALUASI DETEKSI HUJAN" in res.output
        assert "POTENSI HUJAN TERDETEKSI" in res.output
        assert "will_rain): TRUE" in res.output
        assert "Peluang Hujan Maksimal: 80%" in res.output
        assert "Lebat / Deras" in res.output


@pytest.mark.asyncio
async def test_weather_tool_full_report():
    tool = WeatherForecastTool()
    ctx = ToolContext(chat_id=123, user_id=123)

    with patch("src.tools.weather_mgr.fetch_weather_data", new=AsyncMock(return_value=SAMPLE_WEATHER_API_RESPONSE)):
        res = await tool.execute(ctx, action="full_report", force_fallback_location=True)
        assert res.success is True
        assert "LAPORAN CUACA LENGKAP & PREDIKSI" in res.output
        assert "1. Kondisi Saat Ini:" in res.output
        assert "2. Ringkasan 6 Jam ke Depan:" in res.output
        assert "3. Ramalan 3 Hari ke Depan:" in res.output
