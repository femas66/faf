from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User

from src.config import get_settings

logger = logging.getLogger("faf_agent.bot.auth")


class WhitelistAuthMiddleware(BaseMiddleware):
    """Zero Trust whitelist authentication middleware.

    Silently drops all updates from users whose Telegram ID is not in ALLOWED_TELEGRAM_USER_IDS.
    """

    def __init__(self) -> None:
        super().__init__()
        self.settings = get_settings()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")
        allowed_ids = self.settings.allowed_telegram_user_ids

        # If allowed_ids is empty, warn in logs and allow or deny?
        # Specification says: "Hanya User ID Telegram yang terdaftar di konfigurasi (ALLOWED_TELEGRAM_USER_IDS) yang boleh berinteraksi dengan faf-agent."
        if not allowed_ids:
            logger.warning(
                "ALLOWED_TELEGRAM_USER_IDS is empty! Denying all access for security."
            )
            return None

        if not user or user.id not in allowed_ids:
            user_id = user.id if user else "Unknown"
            username = user.username if user else "Unknown"
            logger.warning(
                f"[SECURITY ALERT] Unauthorized access attempt blocked from Telegram ID: {user_id} (@{username})"
            )
            # Drop silently without responding
            return None

        return await handler(event, data)
