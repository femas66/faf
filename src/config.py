from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any
from dotenv import dotenv_values


def _parse_int_list(val: Any) -> list[int]:
    """Parse comma-separated strings or list of ints into list[int]."""
    if isinstance(val, (list, tuple, set)):
        return [int(x) for x in val]
    if isinstance(val, (int, float)):
        return [int(val)]
    if isinstance(val, str):
        val = val.strip()
        if not val:
            return []
        parts = [p.strip() for p in val.split(",") if p.strip()]
        return [int(p) for p in parts if p.isdigit() or (p.startswith("-") and p[1:].isdigit())]
    return []


@dataclass
class Settings:
    """Pure-Python configuration class loaded from environment or .env without Pydantic/Rust."""

    telegram_bot_token: str = ""
    allowed_telegram_user_ids: list[int] = field(default_factory=list)

    # LLM Settings
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o"

    # Security & System Settings
    security_confirmation_timeout: int = 60
    enable_root_commands: bool = True
    command_timeout: int = 30
    log_level: str = "INFO"
    notes_storage_dir: str = "/sdcard/Notes"
    temp_media_dir: str = "/data/data/com.termux/files/home/faf_media"

    def __init__(self, **kwargs: Any) -> None:
        # Load from .env file if present
        env_file_data = dotenv_values(".env") if os.path.exists(".env") else {}

        def get_val(key: str, default: Any = None) -> Any:
            # Precedence: kwargs > os.environ > .env file > default
            if key in kwargs:
                return kwargs[key]
            if key.upper() in kwargs:
                return kwargs[key.upper()]
            if key.upper() in os.environ:
                return os.environ[key.upper()]
            if key.upper() in env_file_data and env_file_data[key.upper()] is not None:
                return env_file_data[key.upper()]
            return default

        self.telegram_bot_token = str(get_val("telegram_bot_token", "") or "")
        self.allowed_telegram_user_ids = _parse_int_list(
            get_val("allowed_telegram_user_ids", [])
        )
        self.openai_api_key = str(get_val("openai_api_key", "") or "")
        self.openai_base_url = str(
            get_val("openai_base_url", "https://api.openai.com/v1") or "https://api.openai.com/v1"
        )
        self.openai_model = str(get_val("openai_model", "gpt-4o") or "gpt-4o")

        self.security_confirmation_timeout = int(
            get_val("security_confirmation_timeout", 60)
        )
        enable_root = get_val("enable_root_commands", True)
        if isinstance(enable_root, str):
            self.enable_root_commands = enable_root.lower() in ("true", "1", "yes")
        else:
            self.enable_root_commands = bool(enable_root)

        self.command_timeout = int(get_val("command_timeout", 30))
        self.log_level = str(get_val("log_level", "INFO") or "INFO")
        self.notes_storage_dir = str(
            get_val("notes_storage_dir", "/sdcard/Notes") or "/sdcard/Notes"
        )
        self.temp_media_dir = str(
            get_val("temp_media_dir", "/data/data/com.termux/files/home/faf_media")
            or "/data/data/com.termux/files/home/faf_media"
        )


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
