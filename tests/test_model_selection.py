from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
import pytest

from src.bot.handlers.commands import handle_mode
from src.config import Settings
from src.core.agent import FafAgent
from src.core.ai_client import AIClient, LLMResponse, LLMChoice, LLMMessage
from src.tools.base import ToolContext, ToolRegistry


# --- 1. Tests for Settings Dual-Tier Configuration ---


def test_settings_dual_model_defaults():
    settings = Settings()
    assert settings.openai_model == "gpt-4o"
    assert settings.openai_fast_model == "gpt-4o-mini"
    assert settings.openai_smart_model == "gpt-4o"


def test_settings_dual_model_custom_override():
    settings = Settings(
        openai_fast_model="gemini-2.5-flash",
        openai_smart_model="gpt-4o-custom",
    )
    assert settings.openai_fast_model == "gemini-2.5-flash"
    assert settings.openai_smart_model == "gpt-4o-custom"


def test_settings_smart_model_inherits_openai_model():
    settings = Settings(
        openai_model="claude-3-5-sonnet",
    )
    assert settings.openai_smart_model == "claude-3-5-sonnet"
    assert settings.openai_fast_model == "gpt-4o-mini"


# --- 2. Tests for AIClient Model Propagation ---


@pytest.mark.asyncio
async def test_ai_client_model_parameter_propagation():
    settings = Settings(
        openai_api_key="key",
        openai_model="base-model",
        openai_base_url="https://api.openai.com/v1",
    )
    client = AIClient(settings=settings)

    mock_http_client = AsyncMock()
    mock_http_client.is_closed = False
    mock_res = MagicMock()
    mock_res.status_code = 200
    mock_res.json.return_value = {
        "choices": [{"message": {"role": "assistant", "content": "Ok"}}]
    }
    mock_http_client.post = AsyncMock(return_value=mock_res)
    client._client = mock_http_client

    # 1. Without model override: uses settings.openai_model
    await client.get_chat_completion(messages=[{"role": "user", "content": "Hai"}])
    posted_payload = mock_http_client.post.call_args[1]["json"]
    assert posted_payload["model"] == "base-model"

    # 2. With model override: uses overridden model
    await client.get_chat_completion(
        messages=[{"role": "user", "content": "Hai"}],
        model="custom-smart-model",
    )
    posted_payload_2 = mock_http_client.post.call_args[1]["json"]
    assert posted_payload_2["model"] == "custom-smart-model"


# --- 3. Tests for FafAgent Model Selection Logic ---


def test_agent_model_selection_auto_mode():
    settings = Settings(
        openai_fast_model="fast-m",
        openai_smart_model="smart-m",
    )
    agent = FafAgent(settings=settings)

    chat_id = 12345
    assert agent.get_mode(chat_id) == "auto"

    # Casual (0 tools): fast
    assert agent.select_model(chat_id, tools_schema=None) == "fast-m"
    assert agent.select_model(chat_id, tools_schema=[]) == "fast-m"

    # Simple system tools: fast
    simple_tools = [
        {"type": "function", "function": {"name": "system_settings"}},
        {"type": "function", "function": {"name": "device_interaction"}},
    ]
    assert agent.select_model(chat_id, tools_schema=simple_tools) == "fast-m"

    # Complex tools: smart
    complex_repl = [{"type": "function", "function": {"name": "python_repl"}}]
    assert agent.select_model(chat_id, tools_schema=complex_repl) == "smart-m"

    complex_search = [{"type": "function", "function": {"name": "web_search"}}]
    assert agent.select_model(chat_id, tools_schema=complex_search) == "smart-m"

    complex_pdf = [{"type": "function", "function": {"name": "pdf_manager"}}]
    assert agent.select_model(chat_id, tools_schema=complex_pdf) == "smart-m"

    complex_ocr = [{"type": "function", "function": {"name": "ocr_extract"}}]
    assert agent.select_model(chat_id, tools_schema=complex_ocr) == "smart-m"

    complex_root = [{"type": "function", "function": {"name": "root_shell_exec"}}]
    assert agent.select_model(chat_id, tools_schema=complex_root) == "smart-m"

    # Fallback with all tools (>=15): smart
    all_tools = [{"type": "function", "function": {"name": f"t_{i}"}} for i in range(16)]
    assert agent.select_model(chat_id, tools_schema=all_tools) == "smart-m"

    # Synthesis fallback: smart
    assert agent.select_model(chat_id, tools_schema=None, is_synthesis=True) == "smart-m"


def test_agent_model_selection_manual_overrides():
    settings = Settings(
        openai_fast_model="fast-m",
        openai_smart_model="smart-m",
    )
    agent = FafAgent()
    agent.settings = settings

    chat_id = 999

    # Set mode to FAST
    agent.set_mode(chat_id, "fast")
    assert agent.get_mode(chat_id) == "fast"
    # Even with complex tool, fast mode stays fast
    complex_tools = [{"type": "function", "function": {"name": "python_repl"}}]
    assert agent.select_model(chat_id, tools_schema=complex_tools) == "fast-m"
    assert agent.select_model(chat_id, is_synthesis=True) == "fast-m"

    # Set mode to SMART
    agent.set_mode(chat_id, "smart")
    assert agent.get_mode(chat_id) == "smart"
    # Even for casual chat, smart mode stays smart
    assert agent.select_model(chat_id, tools_schema=None) == "smart-m"

    # Set mode back to AUTO
    agent.set_mode(chat_id, "auto")
    assert agent.get_mode(chat_id) == "auto"
    assert agent.select_model(chat_id, tools_schema=None) == "fast-m"


# --- 4. Tests for /mode Slash Command ---


@pytest.mark.asyncio
async def test_handle_mode_command_status(monkeypatch):
    """Verify /mode with no args displays current mode and settings."""
    monkeypatch.setattr("src.bot.middlewares.auth.is_user_authorized", lambda uid: True)
    update = MagicMock()
    msg = AsyncMock()
    update.effective_message = msg
    update.effective_chat.id = 555
    context = MagicMock()
    context.args = []

    await handle_mode(update, context)

    msg.reply_text.assert_called_once()
    reply = msg.reply_text.call_args[0][0]
    assert "Mode Model Saat Ini: AUTO" in reply
    assert "Model Fast:" in reply
    assert "Model Smart:" in reply


@pytest.mark.asyncio
async def test_handle_mode_command_switches(monkeypatch):
    """Verify /mode fast, /mode smart, /mode auto switch modes properly."""
    monkeypatch.setattr("src.bot.middlewares.auth.is_user_authorized", lambda uid: True)
    update = MagicMock()
    msg = AsyncMock()
    update.effective_message = msg
    update.effective_chat.id = 555
    context = MagicMock()

    from src.core.agent import agent

    # 1. Switch to fast
    context.args = ["fast"]
    await handle_mode(update, context)
    assert agent.get_mode(555) == "fast"
    assert "FAST" in msg.reply_text.call_args[0][0]

    # 2. Switch to smart
    context.args = ["smart"]
    await handle_mode(update, context)
    assert agent.get_mode(555) == "smart"
    assert "SMART" in msg.reply_text.call_args[0][0]

    # 3. Switch to auto
    context.args = ["auto"]
    await handle_mode(update, context)
    assert agent.get_mode(555) == "auto"
    assert "AUTO" in msg.reply_text.call_args[0][0]

    # 4. Invalid choice
    context.args = ["super_mega_ultra"]
    await handle_mode(update, context)
    assert "tidak valid" in msg.reply_text.call_args[0][0]


# --- 5. Tests for FafAgent.run Using Selected Model ---


@pytest.mark.asyncio
async def test_agent_run_passes_selected_model_to_ai_client():
    mock_ai_client = AsyncMock()
    mock_ai_client.get_chat_completion.return_value = LLMResponse(
        choices=[LLMChoice(message=LLMMessage(role="assistant", content="Jawaban"))]
    )

    settings = Settings(
        openai_fast_model="model-fast-test",
        openai_smart_model="model-smart-test",
    )
    agent = FafAgent(ai_client=mock_ai_client, registry=ToolRegistry())
    agent.settings = settings

    ctx = ToolContext(chat_id=888, user_id=1)

    # 1. Casual request (zero tools routed) with non-streaming: should pick fast model
    await agent.run("Halo apa kabar", context=ctx)
    call_kwargs = mock_ai_client.get_chat_completion.call_args.kwargs
    assert call_kwargs.get("model") == "model-fast-test"

    # 2. Forced smart mode: should pick smart model
    agent.set_mode(888, "smart")
    await agent.run("Halo apa kabar", context=ctx)
    call_kwargs_2 = mock_ai_client.get_chat_completion.call_args.kwargs
    assert call_kwargs_2.get("model") == "model-smart-test"
