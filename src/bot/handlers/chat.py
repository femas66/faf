from __future__ import annotations

import asyncio
import logging
import os
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from src.bot.middlewares.auth import authorized_only
from src.bot.ui.keyboards import get_cancel_keyboard, get_confirmation_keyboard
from src.core.agent import agent, AgentResponse, clean_plain_chat_text
from src.core.permissions import permission_manager
from src.tools.base import ToolContext

logger = logging.getLogger("faf_agent.bot.chat")


@authorized_only
async def handle_chat_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Natural language agent handler with streaming status, media dispatch, and clean plain text output."""
    if not update.effective_message or not update.effective_chat:
        return

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id if update.effective_user else 0
    prompt = update.effective_message.text or ""

    existing_task = agent._active_tasks.get(chat_id)
    if existing_task and not existing_task.done():
        await update.effective_message.reply_text(
            "⏳ Perintah sebelumnya masih diproses. Ketik /cancel jika ingin membatalkannya terlebih dahulu.",
        )
        return

    # Send typing action
    try:
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    except Exception:
        pass

    status_msg = await update.effective_message.reply_text(
        "● faf-agent sedang menganalisis...",
        reply_markup=get_cancel_keyboard(),
    )

    cancel_event = asyncio.Event()

    # Callback for real-time status updates in Telegram
    async def update_status(text: str) -> None:
        try:
            clean_status = clean_plain_chat_text(text)
            await status_msg.edit_text(clean_status, reply_markup=get_cancel_keyboard())
        except Exception:
            pass

    # Callback for destructive confirmation request
    async def request_confirmation(title: str, details: str) -> bool:
        req_id, future = await permission_manager.create_confirmation_request(
            chat_id=chat_id,
            title=title,
            details=details,
        )
        kb = get_confirmation_keyboard(req_id)
        if update.effective_message:
            clean_title = clean_plain_chat_text(title)
            clean_details = clean_plain_chat_text(details)
            await update.effective_message.reply_text(
                f"{clean_title}\n\n{clean_details}\n\nApakah Anda menyetujui tindakan ini?",
                reply_markup=kb,
            )
        try:
            approved = await future
            return approved
        except Exception:
            return False

    tool_context = ToolContext(
        chat_id=chat_id,
        user_id=user_id,
        message_id=status_msg.message_id,
        cancel_event=cancel_event,
        on_status_update=update_status,
        on_request_confirmation=request_confirmation,
    )

    # Wrap agent execution in an active task so it can be cancelled via /cancel
    task = asyncio.create_task(agent.run(user_message=prompt, context=tool_context))
    agent._active_tasks[chat_id] = task

    try:
        response: AgentResponse = await task
    except asyncio.CancelledError:
        response = AgentResponse(
            text="⎿ Interrupted · What should faf-agent do instead?",
            interrupted=True,
        )
    finally:
        if agent._active_tasks.get(chat_id) is task:
            agent._active_tasks.pop(chat_id, None)

    # 1. Send media files if generated (e.g. photos, screenshots)
    if response.media_files:
        for media in response.media_files:
            file_path = media.get("path", "")
            media_type = media.get("type", "photo")
            if file_path and os.path.exists(file_path):
                try:
                    with open(file_path, "rb") as f:
                        fname = os.path.basename(file_path)
                        if media_type == "photo":
                            await context.bot.send_photo(
                                chat_id=chat_id,
                                photo=f,
                                caption=f"📷 Berkas foto: {fname}",
                            )
                        else:
                            await context.bot.send_document(
                                chat_id=chat_id,
                                document=f,
                                caption=f"📎 Berkas dokumen: {fname}",
                            )
                except Exception as e:
                    logger.error(f"Failed to send media file {file_path}: {e}")

    # 2. Update status message or send final plain text (no markdown, no tables)
    final_text = clean_plain_chat_text(response.text) or "(Selesai tanpa tanggapan teks)"

    if len(final_text) > 4000:
        final_text = final_text[:4000] + "\n\n...(respons dipotong karena batas panjang pesan)"

    try:
        await status_msg.edit_text(final_text, reply_markup=None)
    except Exception:
        if update.effective_message:
            await update.effective_message.reply_text(final_text)
