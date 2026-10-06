from __future__ import annotations

import os
from typing import Any
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Telegram Bot
    telegram_bot_token: str = Field(
        default="",
        alias="TELEGRAM_BOT_TOKEN",
        description="Telegram Bot API token from @BotFather",
    )
    allowed_telegram_user_ids: list[int] = Field(
        default_factory=list,
        alias="ALLOWED_TELEGRAM_USER_IDS",
        description="List of Telegram user IDs permitted to interact with the bot",
    )

    # LLM Settings (OpenAI spec)
    openai_api_key: str = Field(
        default="",
        alias="OPENAI_API_KEY",
        description="API key for LLM provider",
    )
    openai_base_url: str = Field(
        default="https://api.openai.com/v1",
        alias="OPENAI_BASE_URL",
        description="Base URL for OpenAI-compatible endpoint",
    )
    openai_model: str = Field(
        default="gpt-4o",
        alias="OPENAI_MODEL",
        description="Target model identifier",
    )

    # Security & System Settings
    security_confirmation_timeout: int = Field(
        default=60,
        alias="SECURITY_CONFIRMATION_TIMEOUT",
        description="Timeout in seconds for interactive confirmation of dangerous actions",
    )
    enable_root_commands: bool = Field(
        default=True,
        alias="ENABLE_ROOT_COMMANDS",
        description="Whether superuser root commands are permitted",
    )
    command_timeout: int = Field(
        default=30,
        alias="COMMAND_TIMEOUT",
        description="Subprocess command timeout in seconds",
    )
    log_level: str = Field(
        default="INFO",
        alias="LOG_LEVEL",
        description="Logging level (DEBUG, INFO, WARNING, ERROR)",
    )
    notes_storage_dir: str = Field(
        default="/sdcard/Notes",
        alias="NOTES_STORAGE_DIR",
        description="Storage path for quick notes",
    )
    temp_media_dir: str = Field(
        default="/data/data/com.termux/files/home/faf_media",
        alias="TEMP_MEDIA_DIR",
        description="Temporary directory for screenshots and photos",
    )

    @field_validator("allowed_telegram_user_ids", mode="before")
    @classmethod
    def parse_allowed_user_ids(cls, v: Any) -> list[int]:
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return []
            # Split comma-separated string
            parts = [p.strip() for p in v.split(",") if p.strip()]
            return [int(p) for p in parts]
        elif isinstance(v, (int, float)):
            return [int(v)]
        elif isinstance(v, (list, tuple, set)):
            return [int(item) for item in v]
        return []


# Global cached settings instance
_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def set_settings(settings: Settings) -> None:
    global _settings
    _settings = settings
