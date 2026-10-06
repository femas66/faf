from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def get_confirmation_keyboard(request_id: str) -> InlineKeyboardMarkup:
    """Inline confirmation keyboard for destructive actions."""
    buttons = [
        [
            InlineKeyboardButton(
                text="✅ Setujui",
                callback_data=f"approve:{request_id}",
            ),
            InlineKeyboardButton(
                text="❌ Tolak & Hentikan",
                callback_data=f"reject:{request_id}",
            ),
        ]
    ]
    return InlineKeyboardMarkup(buttons)


def get_cancel_keyboard() -> InlineKeyboardMarkup:
    """Inline cancel keyboard during active agent execution."""
    buttons = [
        [
            InlineKeyboardButton(
                text="⎿ Batalkan",
                callback_data="cancel_task",
            )
        ]
    ]
    return InlineKeyboardMarkup(buttons)
