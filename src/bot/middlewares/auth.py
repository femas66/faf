from __future__ import annotations

import functools
import logging
from typing import Any, Callable
from telegram import Update
from telegram.ext import ContextTypes, filters

from src.config import get_settings

logger = logging.getLogger("faf_agent.bot.auth")


def is_user_authorized(user_id: int | None) -> bool:
    """Check if a Telegram user ID is whitelisted."""
    settings = get_settings()
    allowed = settings.allowed_telegram_user_ids
    if not allowed or user_id is None:
        return False
    return user_id in allowed


def authorized_only(handler_fn: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator for Telegram handlers: silently drops unauthorized updates."""
    @functools.wraps(handler_fn)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args: Any, **kwargs: Any) -> Any:
        user = update.effective_user
        user_id = user.id if user else None
        username = user.username if user else "Unknown"

        if not is_user_authorized(user_id):
            logger.warning(
                f"[SECURITY ALERT] Unauthorized access dropped: Telegram ID {user_id} (@{username})"
            )
            # Drop silently without responding
            return None

        return await handler_fn(update, context, *args, **kwargs)

    return wrapper


class WhitelistFilter(filters.MessageFilter):
    """Filter that matches only messages from whitelisted users."""

    def filter(self, message: Any) -> bool:
        if not message or not message.from_user:
            return False
        return is_user_authorized(message.from_user.id)
