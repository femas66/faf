from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, patch

from src.core.android_bridge import CommandResult
from src.tools.base import ToolContext
from src.tools.productivity import ProductivityControlTool
from src.tools.device_interaction import DeviceInteractionTool
from src.tools.process_mgr import ProcessManagerTool


def mk_res(stdout: str = "", stderr: str = "", returncode: int = 0) -> CommandResult:
    return CommandResult(
        stdout=stdout,
        stderr=stderr,
        returncode=returncode,
        command="",
        executed_as_root=False,
    )


@pytest.fixture
def mock_context():
    return ToolContext(
        chat_id=12345,
        user_id=111,
        message_id=999,
        on_status_update=AsyncMock(),
    )


# ---------------------------------------------------------------------------
# 1. Feature 1: list_notifications in ProductivityControlTool
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_notifications_success(mock_context):
    tool = ProductivityControlTool()
    sample_notifs = [
        {
            "id": 1,
            "packageName": "com.whatsapp",
            "title": "Budi Santoso",
            "content": "Halo, rapat jam 10 pagi ya.",
            "when": "2026-10-17 08:30:00",
        },
        {
            "id": 2,
            "packageName": "com.google.android.apps.messaging",
            "title": "Bank BCA",
            "content": "Kode OTP Anda: 729182. Jangan berikan ke siapapun.",
            "when": "2026-10-17 08:31:00",
        },
    ]

    with patch("src.tools.productivity.bridge.execute_shell", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = mk_res(stdout=json.dumps(sample_notifs))

        res = await tool.execute(mock_context, action="list_notifications")
        assert res.success is True
        assert "Daftar Notifikasi Aktif" in res.output
        assert "Whatsapp" in res.output
        assert "Budi Santoso" in res.output
        assert "Kode OTP Anda: 729182" in res.output


@pytest.mark.asyncio
async def test_list_notifications_filtered(mock_context):
    tool = ProductivityControlTool()
    sample_notifs = [
        {
            "id": 1,
            "packageName": "com.whatsapp",
            "title": "Budi Santoso",
            "content": "Halo, apa kabar?",
            "when": "2026-10-17 08:30:00",
        },
        {
            "id": 2,
            "packageName": "com.google.android.apps.messaging",
            "title": "Bank Mandiri",
            "content": "Kode OTP transaksi Anda 551234",
            "when": "2026-10-17 08:31:00",
        },
    ]

    with patch("src.tools.productivity.bridge.execute_shell", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = mk_res(stdout=json.dumps(sample_notifs))

        # Filter by package name
        res_pkg = await tool.execute(
            mock_context,
            action="list_notifications",
            package_name="whatsapp",
        )
        assert res_pkg.success is True
        assert "Budi Santoso" in res_pkg.output
        assert "Bank Mandiri" not in res_pkg.output

        # Filter by search_query OTP
        res_otp = await tool.execute(
            mock_context,
            action="list_notifications",
            search_query="OTP",
        )
        assert res_otp.success is True
        assert "Bank Mandiri" in res_otp.output
        assert "Budi Santoso" not in res_otp.output


@pytest.mark.asyncio
async def test_list_notifications_empty(mock_context):
    tool = ProductivityControlTool()
    with patch("src.tools.productivity.bridge.execute_shell", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = mk_res(stdout="[]")

        res = await tool.execute(mock_context, action="list_notifications")
        assert res.success is True
        assert "Tidak ada notifikasi aktif" in res.output


# ---------------------------------------------------------------------------
# 2. Feature 2: inspect_ui in DeviceInteractionTool
# ---------------------------------------------------------------------------

SAMPLE_UI_XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node index="0" text="" class="android.widget.FrameLayout" bounds="[0,0][1080,2400]">
    <node index="0" text="Check In Harian" resource-id="com.example.app:id/btn_checkin" class="android.widget.Button" bounds="[100,500][500,700]" clickable="true" />
    <node index="1" text="Pengaturan Akun" resource-id="com.example.app:id/menu_settings" class="android.widget.TextView" bounds="[100,800][900,900]" clickable="false" />
  </node>
</hierarchy>
"""

@pytest.mark.asyncio
async def test_inspect_ui_detection(mock_context):
    tool = DeviceInteractionTool()

    async def mock_exec_side_effect(cmd, **kwargs):
        if cmd.startswith("cat "):
            return mk_res(stdout=SAMPLE_UI_XML)
        elif "uiautomator" in cmd:
            return mk_res(stdout="UI hierachy dumped")
        return mk_res(stdout="")

    with patch("src.tools.device_interaction.bridge.execute_shell", side_effect=mock_exec_side_effect):
        res = await tool.execute(mock_context, action="inspect_ui")
        assert res.success is True
        assert "Elemen Antarmuka Layar Terdeteksi" in res.output
        assert "Check In Harian" in res.output
        # center of [100,500][500,700] is (300, 600)
        assert "(300, 600)" in res.output


@pytest.mark.asyncio
async def test_inspect_ui_auto_tap(mock_context):
    tool = DeviceInteractionTool()
    calls = []

    async def mock_exec_side_effect(cmd, **kwargs):
        calls.append(cmd)
        if cmd.startswith("cat "):
            return mk_res(stdout=SAMPLE_UI_XML)
        elif "uiautomator" in cmd:
            return mk_res(stdout="UI hierachy dumped")
        return mk_res(stdout="")

    with patch("src.tools.device_interaction.bridge.execute_shell", side_effect=mock_exec_side_effect):
        res = await tool.execute(
            mock_context,
            action="inspect_ui",
            search_text="Check In",
            auto_tap=True,
        )
        assert res.success is True
        assert "berhasil diketuk" in res.output
        assert "(300, 600)" in res.output
        assert any("input tap 300 600" in c for c in calls)


@pytest.mark.asyncio
async def test_inspect_ui_not_found(mock_context):
    tool = DeviceInteractionTool()

    async def mock_exec_side_effect(cmd, **kwargs):
        if cmd.startswith("cat "):
            return mk_res(stdout=SAMPLE_UI_XML)
        elif "uiautomator" in cmd:
            return mk_res(stdout="UI hierachy dumped")
        return mk_res(stdout="")

    with patch("src.tools.device_interaction.bridge.execute_shell", side_effect=mock_exec_side_effect):
        res = await tool.execute(
            mock_context,
            action="inspect_ui",
            search_text="TombolGaib123",
        )
        assert res.success is True
        assert "Tidak ditemukan elemen antarmuka yang cocok" in res.output


# ---------------------------------------------------------------------------
# 3. Feature 5: RAM management & OOM protection in ProcessManagerTool
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_clean_ram(mock_context):
    tool = ProcessManagerTool()

    meminfo_before = {
        "MemTotal": 6000000,
        "MemFree": 500000,
        "MemAvailable": 1500000,
        "Cached": 1000000,
    }
    meminfo_after = {
        "MemTotal": 6000000,
        "MemFree": 1200000,
        "MemAvailable": 2200000,
        "Cached": 400000,
    }

    with patch("src.tools.process_mgr._parse_meminfo", side_effect=[meminfo_before, meminfo_after]), \
         patch("src.tools.process_mgr.bridge.is_root_available", return_value=True), \
         patch("src.tools.process_mgr.bridge.execute_shell", new_callable=AsyncMock) as mock_exec, \
         patch("asyncio.sleep", new_callable=AsyncMock):

        mock_exec.return_value = mk_res(stdout="")

        res = await tool.execute(mock_context, action="clean_ram")
        assert res.success is True
        assert "Pembersihan Memori RAM Berhasil" in res.output
        assert "Memori Total Perangkat: 5859 MB" in res.output or "Memori Total Perangkat" in res.output
        assert "dibebaskan" in res.output
        assert any("am kill-all" in str(call) for call in mock_exec.call_args_list)


@pytest.mark.asyncio
async def test_memory_pressure(mock_context):
    tool = ProcessManagerTool()

    meminfo_data = {
        "MemTotal": 6000000,
        "MemFree": 800000,
        "MemAvailable": 2000000,
        "Cached": 1200000,
        "Buffers": 100000,
        "SwapTotal": 2000000,
        "SwapFree": 1500000,
    }
    sample_psi = "some avg10=2.30 avg60=1.50 avg300=0.80 total=123456\nfull avg10=0.00 avg60=0.00 avg300=0.00 total=0"

    with patch("src.tools.process_mgr._parse_meminfo", return_value=meminfo_data), \
         patch("src.tools.process_mgr._read_proc_file", return_value=sample_psi):

        res = await tool.execute(mock_context, action="memory_pressure")
        assert res.success is True
        assert "Laporan Tekanan Memori & RAM Perangkat (6GB Class)" in res.output
        assert "Total RAM Fisik" in res.output
        assert "RAM Tersedia" in res.output
        assert "Swap / zRAM" in res.output
        assert "Indikator Tekanan PSI" in res.output


@pytest.mark.asyncio
async def test_protect_process(mock_context):
    tool = ProcessManagerTool()

    with patch("src.tools.process_mgr.bridge.is_root_available", return_value=True), \
         patch("src.tools.process_mgr.bridge.execute_shell", new_callable=AsyncMock) as mock_exec:

        mock_exec.side_effect = [
            mk_res(stdout=""),
            mk_res(stdout="-1000"),
        ]

        res = await tool.execute(mock_context, action="protect_process", pid=1234)
        assert res.success is True
        assert "PID 1234 berhasil diimunisasi" in res.output
        assert "-1000" in res.output


def test_startup_banner_wide_and_compact():
    import io
    from src.bot.ui.banner import print_startup_banner, render_startup_banner
    from src.config import Settings

    cfg = Settings(openai_model="gpt-4o", allowed_telegram_user_ids=[12345])

    wide = render_startup_banner(cfg, width=80, color=False)
    assert "███████╗" in wide
    assert "Autonomous Android AI Agent via Telegram" in wide
    assert "gpt-4o" in wide
    assert "1 whitelisted" in wide
    assert "\033[" not in wide

    compact = render_startup_banner(cfg, width=50, color=False)
    assert "█▀▀ ▄▀█ █▀▀" in compact
    assert "gpt-4o" in compact

    buf = io.StringIO()
    print_startup_banner(cfg, stream=buf, mode_label="Test Mode")
    assert "Test Mode" in buf.getvalue()

