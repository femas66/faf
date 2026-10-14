from __future__ import annotations

import fcntl
import logging
import os
import sys
import tempfile
import telegram.error
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

from src.config import get_settings
from src.bot.handlers.commands import (
    handle_start,
    handle_help,
    handle_time,
    handle_reminders,
    handle_device,
    handle_battery,
    handle_top,
    handle_apps,
    handle_wifi,
    handle_ping,
    handle_su_direct,
    handle_cancel,
    handle_clear,
    handle_callback_query,
    handle_doctor,
    handle_mode,
)
from src.bot.handlers.chat import handle_chat_message
from src.tools.reminder_mgr import _default_worker
from src.tools.cronjob_mgr import _default_cron_worker
from src.core.agent import agent

logger = logging.getLogger("faf_agent")



class SingleInstanceLock:
    """Mencegah multiple instance faf-agent berjalan bersamaan di satu perangkat."""

    def __init__(self, lock_file: str | None = None) -> None:
        temp_dir = tempfile.gettempdir()
        self.lock_file = lock_file or os.path.join(temp_dir, "faf_agent.lock")
        self.fd: int | None = None

    def acquire(self) -> bool:
        try:
            self.fd = os.open(self.lock_file, os.O_CREAT | os.O_RDWR, 0o600)
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            os.ftruncate(self.fd, 0)
            os.write(self.fd, f"{os.getpid()}\n".encode("utf-8"))
            return True
        except (BlockingIOError, OSError):
            return False

    def get_running_pid(self) -> int | None:
        try:
            with open(self.lock_file, "r") as f:
                content = f.read().strip()
                if content.isdigit():
                    return int(content)
        except Exception:
            pass
        return None

    def release(self) -> None:
        if self.fd is not None:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_UN)
                os.close(self.fd)
            except Exception:
                pass
            self.fd = None
        try:
            if os.path.exists(self.lock_file):
                os.unlink(self.lock_file)
        except Exception:
            pass


async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Tangani error tak terduga dari polling Telegram."""
    error = context.error
    if isinstance(error, telegram.error.Conflict):
        logger.critical(
            "❌ [409 CONFLICT] Instance bot lain terdeteksi sedang polling dengan token yang sama! "
            "Telegram membatalkan getUpdates. Pastikan Anda hanya menjalankan bot di 1 tempat (cek tmux, background terminal, atau perangkat lain)."
        )
    elif isinstance(error, telegram.error.NetworkError):
        logger.warning(f"Koneksi jaringan Telegram terganggu: {error}")
    else:
        logger.error(f"Telegram Application Error: {error}", exc_info=error)


def create_application() -> Application:
    """Create and configure python-telegram-bot Application instance."""
    settings = get_settings()

    if not settings.telegram_bot_token:
        logger.error("TELEGRAM_BOT_TOKEN is not configured! Please set it in your .env file.")
        sys.exit(1)

    async def on_startup(application: Application) -> None:
        _default_worker.start()
        _default_cron_worker.start()
        logger.info("Reminder and CronJob background workers activated in application.")

    async def on_shutdown(application: Application) -> None:
        _default_worker.stop()
        _default_cron_worker.stop()
        await agent.close()
        logger.info("Reminder, CronJob workers, and Agent AIClient connection pool stopped.")

    app = (
        ApplicationBuilder()
        .token(settings.telegram_bot_token)
        .post_init(on_startup)
        .post_shutdown(on_shutdown)
        .concurrent_updates(True)
        .build()
    )

    # Register Global Error Handler
    app.add_error_handler(global_error_handler)

    # Register Slash Command Handlers
    app.add_handler(CommandHandler("start", handle_start, block=False))
    app.add_handler(CommandHandler("help", handle_help, block=False))
    app.add_handler(CommandHandler("time", handle_time, block=False))
    app.add_handler(CommandHandler("jam", handle_time, block=False))
    app.add_handler(CommandHandler("reminders", handle_reminders, block=False))
    app.add_handler(CommandHandler("pengingat", handle_reminders, block=False))
    app.add_handler(CommandHandler("device", handle_device, block=False))
    app.add_handler(CommandHandler("battery", handle_battery, block=False))
    app.add_handler(CommandHandler("top", handle_top, block=False))
    app.add_handler(CommandHandler("apps", handle_apps, block=False))
    app.add_handler(CommandHandler("wifi", handle_wifi, block=False))
    app.add_handler(CommandHandler("ping", handle_ping, block=False))
    app.add_handler(CommandHandler("su", handle_su_direct, block=False))
    app.add_handler(CommandHandler("cancel", handle_cancel, block=False))
    app.add_handler(CommandHandler("clear", handle_clear, block=False))
    app.add_handler(CommandHandler("doctor", handle_doctor, block=False))
    app.add_handler(CommandHandler("check", handle_doctor, block=False))
    app.add_handler(CommandHandler("mode", handle_mode, block=False))
    app.add_handler(CommandHandler("model", handle_mode, block=False))

    # Register Callback Query Handler (Inline buttons)
    app.add_handler(CallbackQueryHandler(handle_callback_query, block=False))

    # Register Natural Language Chat & Document Handler
    app.add_handler(MessageHandler((filters.TEXT | filters.Document.ALL) & (~filters.COMMAND), handle_chat_message, block=False))

    return app


def main() -> None:
    """Synchronous entry point for running the bot."""
    settings = get_settings()

    log_level = getattr(logging, settings.log_level.upper(), logging.WARNING)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    for noisy in ("httpx", "httpcore", "telegram", "telegram.ext", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    if not settings.allowed_telegram_user_ids:
        logger.warning(
            "ALLOWED_TELEGRAM_USER_IDS is empty! All incoming messages will be rejected by default."
        )

    lock = SingleInstanceLock()
    if not lock.acquire():
        running_pid = lock.get_running_pid()
        pid_info = f" (PID: {running_pid})" if running_pid else ""
        logger.critical(
            f"❌ GAGAL MEMULAI: Instance faf-agent lain sudah aktif di perangkat ini{pid_info}!\n"
            "Menjalankan 2 instance bot bersamaan menyebabkan error '409 Conflict' dari Telegram "
            "dan membuat tombol konfirmasi (Setujui/Tolak) tidak merespons.\n"
            "Solusi: Hentikan instance lama terlebih dahulu dengan perintah:\n"
            f"  kill -9 {running_pid if running_pid else '<PID>'}\n"
            "atau:\n"
            "  pkill -f main.py"
        )
        sys.exit(1)

    logger.info("Initializing faf-agent Telegram Bot (Pure Python / Zero Maturin)...")
    app = create_application()

    logger.info("Starting Telegram Bot polling loop...")
    try:
        app.run_polling()
    except (KeyboardInterrupt, SystemExit):
        logger.info("faf-agent stopped by user.")
    finally:
        lock.release()


if __name__ == "__main__":
    main()
