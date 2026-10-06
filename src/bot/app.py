from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from src.config import get_settings
from src.bot.middlewares.auth import WhitelistAuthMiddleware
from src.bot.handlers.commands import commands_router
from src.bot.handlers.chat import chat_router

logger = logging.getLogger("faf_agent")


def create_dispatcher() -> Dispatcher:
    """Create and configure Aiogram Dispatcher with routers and middlewares."""
    dp = Dispatcher()

    # Register Whitelist Auth Middleware
    auth_middleware = WhitelistAuthMiddleware()
    dp.message.middleware(auth_middleware)
    dp.callback_query.middleware(auth_middleware)

    # Register Routers (order matters: commands first, then natural language chat)
    dp.include_router(commands_router)
    dp.include_router(chat_router)

    return dp


async def start_bot() -> None:
    """Initialize bot instance and begin long-polling."""
    settings = get_settings()

    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if not settings.telegram_bot_token:
        logger.error(
            "TELEGRAM_BOT_TOKEN is not configured! Please set it in your .env file."
        )
        sys.exit(1)

    if not settings.allowed_telegram_user_ids:
        logger.warning(
            "ALLOWED_TELEGRAM_USER_IDS is empty! All incoming messages will be rejected by default."
        )

    logger.info("Initializing faf-agent Telegram Bot...")
    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
    )
    dp = create_dispatcher()

    logger.info("Starting Telegram Bot polling loop...")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()


def main() -> None:
    """Synchronous entry point."""
    try:
        asyncio.run(start_bot())
    except (KeyboardInterrupt, SystemExit):
        logger.info("faf-agent stopped by user.")


if __name__ == "__main__":
    main()
