from __future__ import annotations

import logging
from telegram import Update
from telegram.ext import ContextTypes

from src.core.android_bridge import bridge
from src.core.permissions import permission_manager
from src.core.agent import agent, clean_plain_chat_text
from src.bot.middlewares.auth import authorized_only
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


@authorized_only
async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    if not update.effective_message:
        return
    user = update.effective_user
    user_name = user.first_name if user else "Admin"
    await update.effective_message.reply_text(format_start_message(user_name))


@authorized_only
async def handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command."""
    if not update.effective_message:
        return
    await update.effective_message.reply_text(format_help_message())


@authorized_only
async def handle_device(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /device: shows model, Android OS, RAM, root status."""
    if not update.effective_message:
        return
    status_msg = await update.effective_message.reply_text("● Mengambil informasi perangkat...")
    info = await bridge.get_device_info()
    await status_msg.edit_text(format_device_info(info))


@authorized_only
async def handle_battery(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /battery: shows percentage, charging state, temperature."""
    if not update.effective_message:
        return
    status_msg = await update.effective_message.reply_text("● Mengambil status baterai...")
    info = await bridge.get_battery_info()
    await status_msg.edit_text(format_battery_info(info))


@authorized_only
async def handle_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /time: shows current detailed time, date, and timezone."""
    if not update.effective_message:
        return
    status_msg = await update.effective_message.reply_text("● Mengambil informasi waktu...")
    tool = default_registry.get("time_manager")
    if tool:
        ctx = ToolContext(
            chat_id=update.effective_chat.id if update.effective_chat else 0,
            user_id=update.effective_user.id if update.effective_user else 0,
        )
        res = await tool.execute(ctx, action="now")
        await status_msg.edit_text(res.output)
    else:
        await status_msg.edit_text("Tool time_manager tidak ditemukan.")


@authorized_only
async def handle_top(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /top: shows top processes by CPU and RAM in clean plain text."""
    if not update.effective_message:
        return
    status_msg = await update.effective_message.reply_text("● Membaca proses sistem...")
    tool = default_registry.get("process_manager")
    if tool:
        ctx = ToolContext(
            chat_id=update.effective_chat.id if update.effective_chat else 0,
            user_id=update.effective_user.id if update.effective_user else 0,
        )
        res = await tool.execute(ctx, action="list_processes", limit=10)
        await status_msg.edit_text(res.output)
    else:
        await status_msg.edit_text("Tool process_manager tidak ditemukan.")


@authorized_only
async def handle_apps(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /apps: list 3rd party apps."""
    if not update.effective_message:
        return
    status_msg = await update.effective_message.reply_text("● Mengambil daftar aplikasi...")
    tool = default_registry.get("package_manager")
    if tool:
        ctx = ToolContext(
            chat_id=update.effective_chat.id if update.effective_chat else 0,
            user_id=update.effective_user.id if update.effective_user else 0,
        )
        res = await tool.execute(ctx, action="list_apps", filter_type="3rd_party")
        clean_out = clean_plain_chat_text(res.output)
        await status_msg.edit_text(clean_out)
    else:
        await status_msg.edit_text("Tool package_manager tidak ditemukan.")


@authorized_only
async def handle_wifi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /wifi: check current wifi status."""
    if not update.effective_message:
        return
    status_msg = await update.effective_message.reply_text("● Memeriksa status WiFi...")
    tool = default_registry.get("system_settings")
    if tool:
        ctx = ToolContext(
            chat_id=update.effective_chat.id if update.effective_chat else 0,
            user_id=update.effective_user.id if update.effective_user else 0,
        )
        res = await tool.execute(ctx, action="wifi", sub_action="status")
        output = f"Status WiFi:\n{clean_plain_chat_text(res.output)}"
        await status_msg.edit_text(output)
    else:
        await status_msg.edit_text("Tool system_settings tidak ditemukan.")


@authorized_only
async def handle_ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /ping: test internet connectivity."""
    if not update.effective_message:
        return
    status_msg = await update.effective_message.reply_text("● Menguji latensi internet (8.8.8.8)...")
    res = await bridge.execute_shell("ping -c 2 8.8.8.8", timeout=10)
    if res.success:
        await status_msg.edit_text(f"Hasil Ping:\n{res.stdout}")
    else:
        await status_msg.edit_text(f"Ping gagal:\n{res.stderr or res.stdout}")


@authorized_only
async def handle_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /cancel: cancel running task and terminate active subprocesses."""
    if not update.effective_message or not update.effective_chat:
        return
    chat_id = update.effective_chat.id
    await agent.cancel_task(chat_id)
    await bridge.cancel_all_subprocesses()
    await update.effective_message.reply_text("⎿ Interrupted · What should faf-agent do instead?")


@authorized_only
async def handle_clear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /clear: reset AI conversation history."""
    if not update.effective_message or not update.effective_chat:
        return
    agent.clear_history(update.effective_chat.id)
    await update.effective_message.reply_text("Riwayat percakapan sesi AI telah dibersihkan.")


@authorized_only
async def handle_su_direct(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /su <command>: direct root command execution without LLM."""
    if not update.effective_message:
        return

    text = update.effective_message.text or ""
    parts = text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await update.effective_message.reply_text(
            "Penggunaan: /su <perintah>\nContoh: /su id atau /su ls /data"
        )
        return

    cmd = parts[1].strip()

    # 1. Credential Exfiltration Check
    is_exfil, exfil_reason = permission_manager.check_credential_exfiltration(cmd)
    if is_exfil:
        await update.effective_message.reply_text(f"Peringatan: {exfil_reason}")
        return

    # 2. Process Immunity Check
    is_term, term_reason = permission_manager.check_self_termination(cmd)
    if is_term:
        await update.effective_message.reply_text(f"Peringatan: {term_reason}")
        return

    # 3. Destructive Command Check
    is_destr, destr_reason = permission_manager.check_destructive(cmd)
    if is_destr:
        chat_id = update.effective_chat.id if update.effective_chat else 0
        req_id, future = await permission_manager.create_confirmation_request(
            chat_id=chat_id,
            title="Konfirmasi Eksekusi Root Berbahaya",
            details=f"Alasan: {destr_reason}\nPerintah: {cmd}",
        )
        kb = get_confirmation_keyboard(req_id)
        await update.effective_message.reply_text(
            f"Tindakan Kritis Terdeteksi!\n{destr_reason}\n\n"
            f"Perintah: {cmd}\nApakah Anda yakin ingin mengeksekusi dengan Superuser?",
            reply_markup=kb,
        )
        approved = await future
        if not approved:
            await update.effective_message.reply_text(
                "Eksekusi dibatalkan: Konfirmasi ditolak atau batas waktu habis."
            )
            return

    status_msg = await update.effective_message.reply_text(f"● Menjalankan root shell: {cmd}...")
    res = await bridge.execute_shell(cmd, as_root=True)

    if res.success:
        out = res.stdout if res.stdout else "(Perintah selesai tanpa output)"
        if len(out) > 3800:
            out = out[:3800] + "\n...(dipotong karena batas pesan Telegram)"
        await status_msg.edit_text(out)
    else:
        err = res.stderr if res.stderr else f"Exit code {res.returncode}"
        if len(err) > 3800:
            err = err[:3800] + "\n...(dipotong)"
        await status_msg.edit_text(f"Error (code {res.returncode}):\n{err}")


@authorized_only
async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline button clicks (approve, reject, cancel_task)."""
    query = update.callback_query
    if not query:
        return

    data = query.data or ""

    if data.startswith("approve:"):
        req_id = data.split(":", 1)[1]
        success = await permission_manager.resolve_confirmation(req_id, approved=True)
        if success:
            await query.answer("Operasi disetujui. Melanjutkan...")
            if query.message:
                await query.edit_message_text(
                    f"{clean_plain_chat_text(query.message.text or '')}\n\nStatus: Telah Disetujui."
                )
        else:
            await query.answer("Permintaan sudah kedaluwarsa atau telah diproses.", show_alert=True)

    elif data.startswith("reject:"):
        req_id = data.split(":", 1)[1]
        success = await permission_manager.resolve_confirmation(req_id, approved=False)
        if success:
            await query.answer("Operasi ditolak dan dihentikan.")
            if query.message:
                await query.edit_message_text(
                    f"{clean_plain_chat_text(query.message.text or '')}\n\nStatus: Telah Ditolak."
                )
        else:
            await query.answer("Permintaan sudah kedaluwarsa atau telah diproses.", show_alert=True)

    elif data == "cancel_task":
        if query.message and query.message.chat:
            await agent.cancel_task(query.message.chat.id)
        await bridge.cancel_all_subprocesses()
        await query.answer("Tugas dibatalkan.")
        if query.message:
            await query.message.reply_text("⎿ Interrupted · What should faf-agent do instead?")
