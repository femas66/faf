from __future__ import annotations

import logging
from typing import Any
import openai
from openai import AsyncOpenAI

from src.config import get_settings

logger = logging.getLogger("faf_agent.ai_client")


class AIClient:
    """Wrapper around AsyncOpenAI supporting OpenAI-compatible endpoints and Function Calling."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._client: AsyncOpenAI | None = None

    @property
    def client(self) -> AsyncOpenAI:
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=self.settings.openai_api_key or "mock-key",
                base_url=self.settings.openai_base_url,
            )
        return self._client

    async def get_chat_completion(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] = "auto",
        temperature: float = 0.2,
    ) -> Any:
        """Call LLM completion endpoint with tool definitions."""
        kwargs: dict[str, Any] = {
            "model": self.settings.openai_model,
            "messages": messages,
            "temperature": temperature,
        }

        if tools and len(tools) > 0:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice

        try:
            response = await self.client.chat.completions.create(**kwargs)
            return response
        except openai.AuthenticationError as e:
            logger.error(f"Authentication error with LLM provider: {e}")
            raise RuntimeError(f"Autentikasi LLM gagal. Periksa OPENAI_API_KEY di .env: {e}")
        except openai.APIConnectionError as e:
            logger.error(f"Cannot reach LLM endpoint: {e}")
            raise RuntimeError(f"Gagal terhubung ke penyedia LLM ({self.settings.openai_base_url}): {e}")
        except openai.APIError as e:
            logger.error(f"OpenAI API Error: {e}")
            raise RuntimeError(f"Kesalahan respons LLM API: {e}")
