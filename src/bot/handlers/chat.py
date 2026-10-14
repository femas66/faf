from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any
from telegram import Update, Document
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from src.bot.middlewares.auth import authorized_only
from src.bot.ui.keyboards import get_confirmation_keyboard
from src.core.agent import agent, AgentResponse, clean_plain_chat_text
from src.core.permissions import permission_manager
from src.tools.base import ToolContext
from src.tools.path_security import get_default_documents_dir

logger = logging.getLogger("faf_agent.bot.chat")


class StreamingChatUpdater:
    """Manages debounced progressive streaming and in-place message editing for Telegram."""

    def __init__(
        self,
        bot: Any,
        chat_id: int,
        effective_message: Any,
        debounce_interval: float = 1.1,
        typing_stop: asyncio.Event | None = None,
    ) -> None:
        self.bot = bot
        self.chat_id = chat_id
        self.effective_message = effective_message
        self.debounce_interval = debounce_interval
        self.typing_stop = typing_stop
        self.bot_message: Any = None
        self.accumulated_text: str = ""
        self.last_edit_time: float = 0.0
        self.last_rendered_text: str = ""
        self._lock = asyncio.Lock()

    async def on_token(self, chunk: str) -> None:
        """Handle incoming token chunk from LLM streaming."""
        self.accumulated_text += chunk
        clean = clean_plain_chat_text(self.accumulated_text)
        if not clean.strip():
            return

        now = time.monotonic()
        async with self._lock:
            if self.bot_message is None:
                # First chunk: send initial reply message (Bubble 2)
                try:
                    self.bot_message = await self.effective_message.reply_text(clean)
                    self.last_edit_time = now
                    self.last_rendered_text = clean
                    if self.typing_stop:
                        self.typing_stop.set()
                except Exception as e:
                    logger.warning(f"Failed to send initial streaming reply: {e}")
            else:
                # Subsequent chunks: debounced edit to respect Telegram rate limits
                if (now - self.last_edit_time >= self.debounce_interval) and (clean != self.last_rendered_text):
                    try:
                        edit_chunk = clean[:4000] if len(clean) > 4000 else clean
                        await self.bot_message.edit_text(edit_chunk)
                        self.last_edit_time = now
                        self.last_rendered_text = clean
                    except Exception as e:
                        logger.debug(f"Debounced message edit skipped/failed: {e}")

    async def on_status_update(self, text: str) -> None:
        """Handle real-time status update during thinking or tool execution."""
        # 1. Update dynamic Telegram chat action
        action = ChatAction.TYPING
        lower = text.lower()
        if any(w in lower for w in ["pdf", "dokumen", "file", "berkas"]):
            action = ChatAction.UPLOAD_DOCUMENT
        elif any(w in lower for w in ["foto", "gambar", "kamera", "screenshot", "ocr"]):
            action = ChatAction.UPLOAD_PHOTO
        elif any(w in lower for w in ["audio", "suara", "musik", "rekam"]):
            action = ChatAction.RECORD_VOICE
        try:
            await self.bot.send_chat_action(chat_id=self.chat_id, action=action)
        except Exception:
            pass

        # 2. If bot_message is already active in chat, edit in-place
        if self.bot_message is not None:
            async with self._lock:
                try:
                    clean_status = clean_plain_chat_text(text)
                    if clean_status != self.last_rendered_text:
                        await self.bot_message.edit_text(clean_status)
                        self.last_rendered_text = clean_status
                        self.last_edit_time = time.monotonic()
                except Exception:
                    pass

    async def finalize(self, final_text: str) -> None:
        """Finalize message presentation ensuring single reply bubble with complete text."""
        clean = clean_plain_chat_text(final_text) or "(Selesai tanpa tanggapan teks)"
        if len(clean) > 4000:
            clean = clean[:4000] + "\n\n...(respons dipotong karena batas panjang pesan)"

        async with self._lock:
            if self.bot_message is not None:
                if self.last_rendered_text != clean:
                    try:
                        await self.bot_message.edit_text(clean)
                        self.last_rendered_text = clean
                    except Exception as e:
                        logger.debug(f"Final edit_text skipped/failed: {e}")
            else:
                await self.effective_message.reply_text(clean)


@authorized_only
async def handle_chat_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Natural language agent handler with streaming status, media dispatch, and clean plain text output."""
    if not update.effective_message or not update.effective_chat:
        return

    message = update.effective_message
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id if update.effective_user else 0
    prompt = message.text or message.caption or ""

    # Handle uploaded document (PDF and others)
    doc = getattr(message, "document", None)
    if isinstance(doc, Document) and hasattr(doc, "get_file"):
        raw_name = doc.file_name if isinstance(getattr(doc, "file_name", None), str) else "document.pdf"
        safe_file_name = os.path.basename(raw_name) if raw_name else "document.pdf"
        if not safe_file_name:
            safe_file_name = "document.pdf"

        mime_type = doc.mime_type if isinstance(getattr(doc, "mime_type", None), str) else ""
        is_pdf = safe_file_name.lower().endswith(".pdf") or ("pdf" in mime_type.lower())

        docs_dir = get_default_documents_dir()
        docs_dir.mkdir(parents=True, exist_ok=True)
        dest_path = docs_dir / safe_file_name

        try:
            tg_file = await doc.get_file()
            await tg_file.download_to_drive(custom_path=str(dest_path))

            num_pages = None
            if is_pdf:
                try:
                    import pypdf
                    reader = pypdf.PdfReader(str(dest_path))
                    num_pages = len(reader.pages)
                except Exception:
                    pass

            page_info = f" ({num_pages} halaman)" if num_pages is not None else ""

            if prompt.strip():
                prompt = (
                    f"[Dokumen PDF '{safe_file_name}'{page_info} tersimpan di {dest_path}]\n\n"
                    f"Pertanyaan/Instruksi pengguna:\n{prompt.strip()}"
                )
            else:
                await message.reply_text(
                    f"📄 Dokumen '{safe_file_name}'{page_info} berhasil disimpan ke perpustakaan dokumen (~/.faf_agent/documents/).\n\n"
                    "Anda dapat menanyakan isi, ringkasan, atau mencari topik di dalam dokumen ini kapan saja!"
                )
                return
        except Exception as e:
            logger.error(f"Gagal mengunduh dokumen Telegram {safe_file_name}: {e}")
            await message.reply_text(f"❌ Gagal memproses dokumen '{safe_file_name}': {e}")
            return

    if not prompt.strip():
        return

    existing_task = agent._active_tasks.get(chat_id)
    if existing_task and not existing_task.done():
        await message.reply_text(
            "⏳ Perintah sebelumnya masih diproses. Ketik /cancel jika ingin membatalkannya terlebih dahulu.",
        )
        return

    # Continuous typing action indicator while agent is thinking
    typing_stop = asyncio.Event()

    async def _keep_typing() -> None:
        while not typing_stop.is_set():
            try:
                await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
            except Exception:
                pass
            try:
                await asyncio.wait_for(typing_stop.wait(), timeout=4.0)
            except asyncio.TimeoutError:
                pass

    typing_task = asyncio.create_task(_keep_typing())
    cancel_event = asyncio.Event()

    updater = StreamingChatUpdater(
        bot=context.bot,
        chat_id=chat_id,
        effective_message=update.effective_message,
        debounce_interval=1.1,
        typing_stop=typing_stop,
    )

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
        message_id=update.effective_message.message_id,
        cancel_event=cancel_event,
        on_status_update=updater.on_status_update,
        on_request_confirmation=request_confirmation,
        on_token=updater.on_token,
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
        typing_stop.set()
        typing_task.cancel()
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

    # 2. Finalize plain text response directly (exactly 2 chat bubbles total: user prompt + bot reply)
    await updater.finalize(response.text)
