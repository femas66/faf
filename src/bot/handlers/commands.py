from __future__ import annotations

import logging
from aiogram import Router, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery

from src.core.android_bridge import bridge
from src.core.permissions import permission_manager
from src.core.agent import agent
from src.bot.ui.formatters import (
    format_device_info,
    format_battery_info,
    format_help_message,
    format_start_message,
)
from src.bot.ui.keyboards import get_confirmation_keyboard
from src.tools import default_registry
from src.tools.base import ToolContext

logger = logging.getLogger("faf_agent.bot.commands")

commands_router = Router(name="commands_router")


@commands_router.message(CommandStart())
async def handle_start(message: Message) -> None:
    """Handle /start command."""
    user_name = message.from_user.first_name if message.from_user else "Admin"
    await message.answer(format_start_message(user_name), parse_mode="Markdown")


@commands_router.message(Command("help"))
async def handle_help(message: Message) -> None:
    """Handle /help command."""
    await message.answer(format_help_message(), parse_mode="Markdown")


@commands_router.message(Command("device"))
async def handle_device(message: Message) -> None:
    """Handle /device: shows model, Android OS, RAM, root status."""
    status_msg = await message.answer("● Mengambil informasi perangkat...")
    info = await bridge.get_device_info()
    await status_msg.edit_text(format_device_info(info), parse_mode="Markdown")


@commands_router.message(Command("battery"))
async def handle_battery(message: Message) -> None:
    """Handle /battery: shows percentage, charging state, temperature."""
    status_msg = await message.answer("● Mengambil status baterai...")
    info = await bridge.get_battery_info()
    await status_msg.edit_text(format_battery_info(info), parse_mode="Markdown")


@commands_router.message(Command("top"))
async def handle_top(message: Message) -> None:
    """Handle /top: shows top processes by CPU and RAM."""
    status_msg = await message.answer("● Membaca ringkasan proses...")
    tool = default_registry.get("process_manager")
    if tool:
        ctx = ToolContext(chat_id=message.chat.id, user_id=message.from_user.id if message.from_user else 0)
        res = await tool.execute(ctx, action="list_processes", limit=10)
        output = f"📊 **Top 10 Proses Sistem:**\n```\n{res.output}\n```"
        await status_msg.edit_text(output, parse_mode="Markdown")
    else:
        await status_msg.edit_text("Tool process_manager tidak ditemukan.")


@commands_router.message(Command("apps"))
async def handle_apps(message: Message) -> None:
    """Handle /apps: list 3rd party apps."""
    status_msg = await message.answer("● Mengambil daftar aplikasi...")
    tool = default_registry.get("package_manager")
    if tool:
        ctx = ToolContext(chat_id=message.chat.id, user_id=message.from_user.id if message.from_user else 0)
        res = await tool.execute(ctx, action="list_apps", filter_type="3rd_party")
        await status_msg.edit_text(res.output)
    else:
        await status_msg.edit_text("Tool package_manager tidak ditemukan.")


@commands_router.message(Command("wifi"))
async def handle_wifi(message: Message) -> None:
    """Handle /wifi: check current wifi status."""
    status_msg = await message.answer("● Memeriksa status WiFi...")
    tool = default_registry.get("system_settings")
    if tool:
        ctx = ToolContext(chat_id=message.chat.id, user_id=message.from_user.id if message.from_user else 0)
        res = await tool.execute(ctx, action="wifi", sub_action="status")
        await status_msg.edit_text(f"📶 **Status WiFi:**\n```\n{res.output}\n```", parse_mode="Markdown")
    else:
        await status_msg.edit_text("Tool system_settings tidak ditemukan.")


@commands_router.message(Command("ping"))
async def handle_ping(message: Message) -> None:
    """Handle /ping: test internet connectivity."""
    status_msg = await message.answer("● Menguji latensi internet (8.8.8.8)...")
    res = await bridge.execute_shell("ping -c 2 8.8.8.8", timeout=10)
    if res.success:
        await status_msg.edit_text(f"🌐 **Hasil Ping:**\n```\n{res.stdout}\n```", parse_mode="Markdown")
    else:
        await status_msg.edit_text(f"❌ Ping gagal:\n```\n{res.stderr or res.stdout}\n```", parse_mode="Markdown")


@commands_router.message(Command("cancel"))
async def handle_cancel(message: Message) -> None:
    """Handle /cancel: cancel running task and terminate active subprocesses."""
    chat_id = message.chat.id
    await agent.cancel_task(chat_id)
    await bridge.cancel_all_subprocesses()
    await message.answer("⎿ Interrupted · What should faf-agent do instead?")


@commands_router.message(Command("clear"))
async def handle_clear(message: Message) -> None:
    """Handle /clear: reset AI conversation history."""
    agent.clear_history(message.chat.id)
    await message.answer("🧹 Riwayat percakapan sesi AI telah dibersihkan.")


@commands_router.message(Command("su"))
async def handle_su_direct(message: Message) -> None:
    """Handle /su <command>: direct root command execution without LLM."""
    text = message.text or ""
    parts = text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.answer("Penggunaan: `/su <perintah>`\nContoh: `/su id` atau `/su ls /data`", parse_mode="Markdown")
        return

    cmd = parts[1].strip()

    # 1. Credential Exfiltration Check
    is_exfil, exfil_reason = permission_manager.check_credential_exfiltration(cmd)
    if is_exfil:
        await message.answer(f"🛑 {exfil_reason}")
        return

    # 2. Process Immunity Check
    is_term, term_reason = permission_manager.check_self_termination(cmd)
    if is_term:
        await message.answer(f"🛑 {term_reason}")
        return

    # 3. Destructive Command Check
    is_destr, destr_reason = permission_manager.check_destructive(cmd)
    if is_destr:
        req_id, future = await permission_manager.create_confirmation_request(
            chat_id=message.chat.id,
            title="⚠️ Konfirmasi Eksekusi Root Destruktif",
            details=f"**Alasan:** {destr_reason}\n**Perintah:** `{cmd}`",
        )
        kb = get_confirmation_keyboard(req_id)
        await message.answer(
            f"⚠️ **Tindakan Kritis Terdeteksi!**\n{destr_reason}\n\n"
            f"Perintah: `{cmd}`\nApakah Anda yakin ingin mengeksekusi dengan Superuser?",
            reply_markup=kb,
            parse_mode="Markdown",
        )
        approved = await future
        if not approved:
            await message.answer("❌ Eksekusi dibatalkan: Konfirmasi ditolak atau batas waktu habis.")
            return

    status_msg = await message.answer(f"● Menjalankan root shell: `{cmd}`...", parse_mode="Markdown")
    res = await bridge.execute_shell(cmd, as_root=True)

    if res.success:
        out = res.stdout if res.stdout else "(Perintah selesai tanpa output)"
        # Truncate if too long for Telegram message limit (4096)
        if len(out) > 3800:
            out = out[:3800] + "\n...(dipotong karena batas pesan Telegram)"
        await status_msg.edit_text(f"```\n{out}\n```", parse_mode="Markdown")
    else:
        err = res.stderr if res.stderr else f"Exit code {res.returncode}"
        if len(err) > 3800:
            err = err[:3800] + "\n...(dipotong)"
        await status_msg.edit_text(f"❌ **Error (code {res.returncode}):**\n```\n{err}\n```", parse_mode="Markdown")


# Callback Query Handlers
@commands_router.callback_query(F.data.startswith("approve:"))
async def handle_callback_approve(callback: CallbackQuery) -> None:
    """Handle approval button click."""
    req_id = callback.data.split(":", 1)[1] if callback.data else ""
    success = await permission_manager.resolve_confirmation(req_id, approved=True)
    if success:
        await callback.answer("✅ Operasi disetujui. Melanjutkan...")
        if callback.message:
            await callback.message.edit_text(
                f"{callback.message.text}\n\n**Status:** ✅ Telah Disetujui.",
                reply_markup=None,
                parse_mode="Markdown",
            )
    else:
        await callback.answer("Permintaan sudah kedaluwarsa atau telah diproses.", show_alert=True)


@commands_router.callback_query(F.data.startswith("reject:"))
async def handle_callback_reject(callback: CallbackQuery) -> None:
    """Handle rejection button click."""
    req_id = callback.data.split(":", 1)[1] if callback.data else ""
    success = await permission_manager.resolve_confirmation(req_id, approved=False)
    if success:
        await callback.answer("❌ Operasi ditolak dan dihentikan.")
        if callback.message:
            await callback.message.edit_text(
                f"{callback.message.text}\n\n**Status:** ❌ Telah Ditolak.",
                reply_markup=None,
                parse_mode="Markdown",
            )
    else:
        await callback.answer("Permintaan sudah kedaluwarsa atau telah diproses.", show_alert=True)


@commands_router.callback_query(F.data == "cancel_task")
async def handle_callback_cancel(callback: CallbackQuery) -> None:
    """Handle inline cancel button."""
    if callback.message:
        await agent.cancel_task(callback.message.chat.id)
    await bridge.cancel_all_subprocesses()
    await callback.answer("Tugas dibatalkan.")
    if callback.message:
        await callback.message.answer("⎿ Interrupted · What should faf-agent do instead?")
