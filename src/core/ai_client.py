from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from src.config import get_settings

logger = logging.getLogger("faf_agent.ai_client")


@dataclass
class LLMFunction:
    name: str
    arguments: str


@dataclass
class LLMToolCall:
    id: str
    type: str
    function: LLMFunction


@dataclass
class LLMMessage:
    role: str = "assistant"
    content: str | None = None
    tool_calls: list[LLMToolCall] | None = None


@dataclass
class LLMChoice:
    message: LLMMessage


@dataclass
class LLMResponse:
    choices: list[LLMChoice]


class AIClient:
    """Pure-Python OpenAI-compatible client using httpx (zero Rust/maturin dependencies)."""

    def __init__(self) -> None:
        self.settings = get_settings()

    async def get_chat_completion(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] = "auto",
        temperature: float = 0.2,
    ) -> LLMResponse:
        """Call LLM completion endpoint with OpenAI tool calling protocol."""
        base_url = self.settings.openai_base_url.rstrip("/")
        if not base_url.endswith("/v1"):
            url = f"{base_url}/v1/chat/completions"
        else:
            url = f"{base_url}/chat/completions"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.settings.openai_api_key or 'no-key'}",
        }

        payload: dict[str, Any] = {
            "model": self.settings.openai_model,
            "messages": messages,
            "temperature": temperature,
        }

        if tools and len(tools) > 0:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                res = await client.post(url, headers=headers, json=payload)

            if res.status_code == 401:
                raise RuntimeError(
                    f"Autentikasi LLM gagal (401 Unauthorized). Periksa OPENAI_API_KEY di .env: {res.text}"
                )
            elif res.status_code != 200:
                raise RuntimeError(
                    f"LLM API Error ({res.status_code}): {res.text}"
                )

            data = res.json()
            raw_choice = data["choices"][0]
            raw_msg = raw_choice["message"]

            content = raw_msg.get("content")
            raw_tool_calls = raw_msg.get("tool_calls")
            parsed_tool_calls: list[LLMToolCall] | None = None

            if raw_tool_calls:
                parsed_tool_calls = []
                for tc in raw_tool_calls:
                    fn_data = tc.get("function", {})
                    fn_name = fn_data.get("name", "")
                    fn_args = fn_data.get("arguments", "{}")
                    if isinstance(fn_args, dict):
                        fn_args = json.dumps(fn_args)
                    parsed_tool_calls.append(
                        LLMToolCall(
                            id=tc.get("id", ""),
                            type=tc.get("type", "function"),
                            function=LLMFunction(name=fn_name, arguments=fn_args),
                        )
                    )

            msg_obj = LLMMessage(
                role=raw_msg.get("role", "assistant"),
                content=content,
                tool_calls=parsed_tool_calls,
            )
            return LLMResponse(choices=[LLMChoice(message=msg_obj)])

        except httpx.ConnectError as e:
            logger.error(f"Cannot connect to LLM endpoint: {e}")
            raise RuntimeError(f"Gagal terhubung ke endpoint LLM ({url}): {e}")
        except httpx.TimeoutException as e:
            logger.error(f"LLM request timed out: {e}")
            raise RuntimeError(f"Permintaan ke LLM melebihi batas waktu (timeout): {e}")
        except Exception as e:
            logger.exception(f"Unexpected error calling LLM: {e}")
            raise
