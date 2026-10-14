from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from telegram.constants import ChatAction

from src.bot.handlers.chat import StreamingChatUpdater
from src.config import Settings
from src.core.agent import FafAgent, AgentResponse
from src.core.ai_client import AIClient
from src.tools.base import ToolContext, ToolRegistry, BaseTool, ToolResult


# --- 1. Tests for AIClient.stream_chat_completion ---


@pytest.mark.asyncio
async def test_ai_client_stream_chat_completion_success():
    """Verify that stream_chat_completion parses SSE chunks correctly."""
    settings = Settings(
        openai_api_key="test-key",
        openai_model="test-model",
        openai_base_url="https://api.openai.com/v1",
    )
    client = AIClient(settings=settings)

    sse_lines = [
        'data: {"choices": [{"delta": {"content": "Halo"}}]}\n',
        "\n",
        'data: {"choices": [{"delta": {"content": " dunia"}}]}\n',
        'data: {"choices": [{"delta": {}}]}\n',
        "data: [DONE]\n",
    ]

    mock_response = MagicMock()
    mock_response.status_code = 200

    async def mock_aiter_lines():
        for line in sse_lines:
            yield line

    mock_response.aiter_lines = mock_aiter_lines

    class DummyStreamContext:
        async def __aenter__(self):
            return mock_response

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    mock_http_client = AsyncMock()
    mock_http_client.is_closed = False
    mock_http_client.stream = MagicMock(return_value=DummyStreamContext())
    client._client = mock_http_client

    tokens = []
    async for token in client.stream_chat_completion(
        messages=[{"role": "user", "content": "Hai"}]
    ):
        tokens.append(token)

    assert tokens == ["Halo", " dunia"]


@pytest.mark.asyncio
async def test_ai_client_stream_auth_error():
    """Verify that 401 raises RuntimeError."""
    settings = Settings(
        openai_api_key="bad-key",
        openai_model="test-model",
        openai_base_url="https://api.openai.com/v1",
    )
    client = AIClient(settings=settings)

    mock_response = MagicMock()
    mock_response.status_code = 401

    class DummyStreamContext:
        async def __aenter__(self):
            return mock_response

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    mock_http_client = AsyncMock()
    mock_http_client.is_closed = False
    mock_http_client.stream = MagicMock(return_value=DummyStreamContext())
    client._client = mock_http_client

    with pytest.raises(RuntimeError, match="Autentikasi LLM gagal"):
        async for _ in client.stream_chat_completion(
            messages=[{"role": "user", "content": "Hai"}]
        ):
            pass


@pytest.mark.asyncio
async def test_ai_client_stream_non_200_error():
    """Verify that non-200 status code raises RuntimeError."""
    settings = Settings(
        openai_api_key="test-key",
        openai_model="test-model",
        openai_base_url="https://api.openai.com/v1",
    )
    client = AIClient(settings=settings)

    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.aread = AsyncMock(return_value=b"Internal server error")

    class DummyStreamContext:
        async def __aenter__(self):
            return mock_response

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    mock_http_client = AsyncMock()
    mock_http_client.is_closed = False
    mock_http_client.stream = MagicMock(return_value=DummyStreamContext())
    client._client = mock_http_client

    with pytest.raises(RuntimeError, match="LLM API Streaming Error"):
        async for _ in client.stream_chat_completion(
            messages=[{"role": "user", "content": "Hai"}]
        ):
            pass


# --- 2. Tests for FafAgent with Streaming & Live Status ---


@pytest.mark.asyncio
async def test_agent_run_streams_for_zero_tool_intent():
    """Verify that casual chat triggers streaming and yields tokens via context.on_token."""
    mock_ai_client = AsyncMock()

    async def mock_stream(messages, **kwargs):
        for t in ["Halo", "!", " Ada", " yang", " bisa", " dibantu?"]:
            yield t

    mock_ai_client.stream_chat_completion = mock_stream

    registry = ToolRegistry()
    agent = FafAgent(ai_client=mock_ai_client, registry=registry)

    received_tokens = []

    async def token_cb(token: str):
        received_tokens.append(token)

    context = ToolContext(
        chat_id=101,
        user_id=1,
        on_token=token_cb,
    )

    response = await agent.run(user_message="Halo", context=context)

    assert response.text == "Halo! Ada yang bisa dibantu?"
    assert received_tokens == ["Halo", "!", " Ada", " yang", " bisa", " dibantu?"]


@pytest.mark.asyncio
async def test_agent_run_streaming_cancellation():
    """Verify that setting cancel_event during streaming raises CancelledError."""
    mock_ai_client = AsyncMock()

    cancel_event = asyncio.Event()

    async def mock_stream(messages, **kwargs):
        yield "Mulai"
        cancel_event.set()
        yield " Lanjut"

    mock_ai_client.stream_chat_completion = mock_stream
    agent = FafAgent(ai_client=mock_ai_client, registry=ToolRegistry())

    context = ToolContext(
        chat_id=102,
        user_id=1,
        cancel_event=cancel_event,
        on_token=AsyncMock(),
    )

    with pytest.raises(asyncio.CancelledError):
        await agent.run(user_message="Halo", context=context)


@pytest.mark.asyncio
async def test_agent_run_streaming_fallback_on_error():
    """Verify fallback to get_chat_completion if streaming encounters an error."""
    mock_ai_client = AsyncMock()

    async def bad_stream(messages, **kwargs):
        raise RuntimeError("Stream disconnect")
        yield "Never"

    mock_ai_client.stream_chat_completion = bad_stream

    from src.core.ai_client import LLMResponse, LLMChoice, LLMMessage

    mock_ai_client.get_chat_completion.return_value = LLMResponse(
        choices=[
            LLMChoice(message=LLMMessage(role="assistant", content="Respon fallback"))
        ]
    )

    agent = FafAgent(ai_client=mock_ai_client, registry=ToolRegistry())
    context = ToolContext(
        chat_id=103,
        user_id=1,
        on_token=AsyncMock(),
    )

    response = await agent.run(user_message="Halo", context=context)
    assert response.text == "Respon fallback"
    mock_ai_client.get_chat_completion.assert_called_once()


@pytest.mark.asyncio
async def test_agent_tool_status_formatting():
    """Verify that _format_tools_status produces human-friendly descriptions."""
    assert "internet" in FafAgent._format_tools_status(["web_search"])
    assert "PDF" in FafAgent._format_tools_status(["pdf_manager"])
    assert "OCR" in FafAgent._format_tools_status(["ocr_extract"])
    assert "media" in FafAgent._format_tools_status(["media_downloader"])
    assert "setelan" in FafAgent._format_tools_status(["system_settings"])
    assert "berkas" in FafAgent._format_tools_status(["file_manager"])
    assert "komputasi" in FafAgent._format_tools_status(["python_repl"])
    assert "tindakan" in FafAgent._format_tools_status(["unknown_tool"])


# --- 3. Tests for StreamingChatUpdater ---


@pytest.mark.asyncio
async def test_streaming_updater_initial_and_debounced_edit():
    """Verify that first token calls reply_text and subsequent debounced chunks call edit_text."""
    bot = AsyncMock()
    msg = AsyncMock()
    bot_reply_msg = AsyncMock()
    msg.reply_text.return_value = bot_reply_msg

    typing_stop = asyncio.Event()
    updater = StreamingChatUpdater(
        bot=bot,
        chat_id=999,
        effective_message=msg,
        debounce_interval=0.1,  # Short interval for test speed
        typing_stop=typing_stop,
    )

    # 1. First chunk: creates reply message
    await updater.on_token("Halo")
    msg.reply_text.assert_called_once_with("Halo")
    assert typing_stop.is_set()
    assert updater.bot_message is bot_reply_msg

    # 2. Second chunk before debounce: should be skipped
    await updater.on_token(" semua")
    bot_reply_msg.edit_text.assert_not_called()

    # 3. Wait past debounce interval
    await asyncio.sleep(0.12)
    await updater.on_token(" orang")
    bot_reply_msg.edit_text.assert_called_once_with("Halo semua orang")

    # 4. Finalize
    await updater.finalize("Halo semua orang!")
    assert bot_reply_msg.edit_text.call_count == 2
    bot_reply_msg.edit_text.assert_called_with("Halo semua orang!")


@pytest.mark.asyncio
async def test_streaming_updater_finalize_without_tokens():
    """Verify that if on_token was never called, finalize uses reply_text directly."""
    bot = AsyncMock()
    msg = AsyncMock()

    updater = StreamingChatUpdater(
        bot=bot,
        chat_id=999,
        effective_message=msg,
    )

    await updater.finalize("Jawaban langsung.")
    msg.reply_text.assert_called_once_with("Jawaban langsung.")


@pytest.mark.asyncio
async def test_streaming_updater_status_update():
    """Verify on_status_update dispatches specialized ChatAction and edits active message."""
    bot = AsyncMock()
    msg = AsyncMock()
    bot_reply_msg = AsyncMock()
    msg.reply_text.return_value = bot_reply_msg

    updater = StreamingChatUpdater(
        bot=bot,
        chat_id=999,
        effective_message=msg,
    )

    # Status without active bot_message: only sends chat action
    await updater.on_status_update("Sedang membaca PDF dokumen...")
    bot.send_chat_action.assert_called_with(
        chat_id=999, action=ChatAction.UPLOAD_DOCUMENT
    )
    bot_reply_msg.edit_text.assert_not_called()

    # Status with image keyword
    await updater.on_status_update("Memproses teks OCR foto...")
    bot.send_chat_action.assert_called_with(chat_id=999, action=ChatAction.UPLOAD_PHOTO)

    # Once bot_message is created, status updates edit the message in-place
    await updater.on_token("Mulai")
    await updater.on_status_update("Sedang mencari data...")
    bot_reply_msg.edit_text.assert_called_with("Sedang mencari data...")


@pytest.mark.asyncio
async def test_streaming_updater_long_text_truncation():
    """Verify that texts longer than 4000 characters are safely truncated."""
    bot = AsyncMock()
    msg = AsyncMock()

    updater = StreamingChatUpdater(
        bot=bot,
        chat_id=999,
        effective_message=msg,
    )

    very_long_text = "A" * 4500
    await updater.finalize(very_long_text)

    msg.reply_text.assert_called_once()
    called_text = msg.reply_text.call_args[0][0]
    assert len(called_text) <= 4100
    assert "...(respons dipotong karena batas panjang pesan)" in called_text
