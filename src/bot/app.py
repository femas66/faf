from __future__ import annotations

import logging
import sys
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

from src.config import get_settings
from src.bot.handlers.commands import (
    handle_start,
    handle_help,
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
)
from src.bot.handlers.chat import handle_chat_message

logger = logging.getLogger("faf_agent")


def create_application() -> Application:
    """Create and configure python-telegram-bot Application instance."""
    settings = get_settings()

    if not settings.telegram_bot_token:
        logger.error("TELEGRAM_BOT_TOKEN is not configured! Please set it in your .env file.")
        sys.exit(1)

    app = ApplicationBuilder().token(settings.telegram_bot_token).build()

    # Register Slash Command Handlers
    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(CommandHandler("help", handle_help))
    app.add_handler(CommandHandler("device", handle_device))
    app.add_handler(CommandHandler("battery", handle_battery))
    app.add_handler(CommandHandler("top", handle_top))
    app.add_handler(CommandHandler("apps", handle_apps))
    app.add_handler(CommandHandler("wifi", handle_wifi))
    app.add_handler(CommandHandler("ping", handle_ping))
    app.add_handler(CommandHandler("su", handle_su_direct))
    app.add_handler(CommandHandler("cancel", handle_cancel))
    app.add_handler(CommandHandler("clear", handle_clear))

    # Register Callback Query Handler (Inline buttons)
    app.add_handler(CallbackQueryHandler(handle_callback_query))

    # Register Natural Language Chat Handler
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_chat_message))

    return app


def main() -> None:
    """Synchronous entry point for running the bot."""
    settings = get_settings()

    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if not settings.allowed_telegram_user_ids:
        logger.warning(
            "ALLOWED_TELEGRAM_USER_IDS is empty! All incoming messages will be rejected by default."
        )

    logger.info("Initializing faf-agent Telegram Bot (Pure Python / Zero Maturin)...")
    app = create_application()

    logger.info("Starting Telegram Bot polling loop...")
    try:
        app.run_polling()
    except (KeyboardInterrupt, SystemExit):
        logger.info("faf-agent stopped by user.")


if __name__ == "__main__":
    main()
