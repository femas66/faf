from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from aiogram import Router, F, Bot
from aiogram.types import Message, FSInputFile

from src.bot.ui.keyboards import get_cancel_keyboard, get_confirmation_keyboard
from src.core.agent import agent, AgentResponse
from src.core.permissions import permission_manager
from src.tools.base import ToolContext

logger = logging.getLogger("faf_agent.bot.chat")

chat_router = Router(name="chat_router")


@chat_router.message(F.text & ~F.text.startswith("/"))
async def handle_chat_message(message: Message, bot: Bot) -> None:
    """Natural language agent handler with streaming status, media dispatch, and cancellation."""
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else 0
    prompt = message.text or ""

    # Send initial typing action & status indicator message
    try:
        await bot.send_chat_action(chat_id=chat_id, action="typing")
    except Exception:
        pass

    status_msg = await message.answer(
        "● faf-agent sedang menganalisis...",
        reply_markup=get_cancel_keyboard(),
    )

    cancel_event = asyncio.Event()

    # Callback for real-time status updates in Telegram
    async def update_status(text: str) -> None:
        try:
            await status_msg.edit_text(text, reply_markup=get_cancel_keyboard())
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
        confirm_msg = await message.answer(
            f"**{title}**\n\n{details}\n\nApakah Anda menyetujui tindakan ini?",
            reply_markup=kb,
            parse_mode="Markdown",
        )
        try:
            approved = await future
            return approved
        except Exception:
            return False

    context = ToolContext(
        chat_id=chat_id,
        user_id=user_id,
        message_id=status_msg.message_id,
        cancel_event=cancel_event,
        on_status_update=update_status,
        on_request_confirmation=request_confirmation,
    )

    # Wrap agent execution in an active task so it can be cancelled via /cancel
    task = asyncio.create_task(agent.run(user_message=prompt, context=context))
    agent._active_tasks[chat_id] = task

    try:
        response: AgentResponse = await task
    except asyncio.CancelledError:
        response = AgentResponse(
            text="⎿ Interrupted · What should faf-agent do instead?",
            interrupted=True,
        )
    finally:
        agent._active_tasks.pop(chat_id, None)

    # 1. Send media files if generated (e.g. photos, screenshots)
    if response.media_files:
        for media in response.media_files:
            file_path = media.get("path", "")
            media_type = media.get("type", "photo")
            if file_path and os.path.exists(file_path):
                try:
                    input_file = FSInputFile(file_path)
                    if media_type == "photo":
                        await message.answer_photo(
                            photo=input_file,
                            caption=f"📷 Berkas media: `{os.path.basename(file_path)}`",
                            parse_mode="Markdown",
                        )
                    else:
                        await message.answer_document(
                            document=input_file,
                            caption=f"📎 Berkas: `{os.path.basename(file_path)}`",
                            parse_mode="Markdown",
                        )
                except Exception as e:
                    logger.error(f"Failed to send media file {file_path}: {e}")

    # 2. Update status message or send final text
    final_text = response.text or "(Selesai tanpa tanggapan teks)"

    # Truncate if exceeding Telegram limit of 4096 characters
    if len(final_text) > 4000:
        final_text = final_text[:4000] + "\n\n...(respons dipotong karena batas panjang pesan)"

    try:
        await status_msg.edit_text(final_text, reply_markup=None, parse_mode="Markdown")
    except Exception:
        # Fallback if markdown parsing fails or other edit error
        try:
            await status_msg.edit_text(final_text, reply_markup=None)
        except Exception:
            await message.answer(final_text)
