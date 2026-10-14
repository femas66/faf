from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
import pytest

from src.core.tool_router import (
    ToolRouter,
    CATEGORY_CONVERSATION,
    CATEGORY_SYSTEM,
    CATEGORY_FILES,
    CATEGORY_WEB_MEDIA,
    CATEGORY_DEV_ADVANCED,
    CATEGORY_MEMORY,
    CATEGORY_ALL,
)
from src.tools import default_registry
from src.core.agent import FafAgent
from src.tools.base import ToolContext


@pytest.fixture
def router() -> ToolRouter:
    return ToolRouter(default_registry)


def test_casual_greetings_and_smalltalk(router: ToolRouter):
    casual_queries = [
        "halo",
        "Halo!",
        "hai",
        "hei faf",
        "p",
        "Pagi",
        "selamat siang",
        "assalamualaikum",
        "terima kasih",
        "makasih ya",
        "siapa kamu?",
        "kamu siapa",
        "apa kabar",
        "ok",
        "oke siap",
        "mantap",
        "dadah",
    ]
    for q in casual_queries:
        cats = router.classify_categories(q)
        assert CATEGORY_CONVERSATION in cats, f"Query '{q}' should be classified as conversation, got {cats}"
        tool_names = router.get_tool_names(q)
        assert tool_names == set(), f"Query '{q}' should have 0 tool names"
        tools = router.get_tools_for_message(q)
        assert tools is None, f"Query '{q}' should return None tools schema for zero token overhead"


def test_general_knowledge_and_creative_requests(router: ToolRouter):
    queries = [
        "buatkan puisi tentang pantai dan ombak",
        "tuliskan cerita dongeng kancil dan buaya",
        "jelaskan teori relativitas khusus einstein",
        "apa itu algoritma binary search",
        "kenapa warna langit itu biru",
        "terjemahkan halo dunia ke bahasa jepang",
    ]
    for q in queries:
        cats = router.classify_categories(q)
        assert CATEGORY_CONVERSATION in cats, f"Query '{q}' should be conversation, got {cats}"
        assert router.get_tools_for_message(q) is None


def test_system_intent_routing(router: ToolRouter):
    system_queries = [
        "cek baterai hp saya",
        "nyalakan senter",
        "matikan wifi sekarang",
        "atur volume musik ke 50",
        "berapa suhu cpu dan temperatur baterai",
        "pasang alarm jam 7 pagi",
        "kapan waktu imsak hari ini",
        "ingatkan saya jam 12 siang makan",
        "bagaimana cuaca hari ini di malang",
    ]
    for q in system_queries:
        cats = router.classify_categories(q)
        assert CATEGORY_SYSTEM in cats, f"Query '{q}' should contain CATEGORY_SYSTEM, got {cats}"
        names = router.get_tool_names(q)
        assert names is not None
        assert "system_settings" in names or "productivity_control" in names or "time_manager" in names or "weather_forecast" in names or "reminder_manager" in names
        assert "ask_clarification" in names
        tools = router.get_tools_for_message(q)
        assert tools is not None
        assert 0 < len(tools) < len(default_registry.get_all())


def test_files_intent_routing(router: ToolRouter):
    file_queries = [
        "buatkan file hello.txt di folder documents",
        "baca dokumen /sdcard/Download/skripsi.pdf",
        "tulis catatan belanja ke file list.txt",
        "hapus file log.txt di direktori home",
        "carikan kata kunci anggaran di file laporan.pdf",
    ]
    for q in file_queries:
        cats = router.classify_categories(q)
        assert CATEGORY_FILES in cats, f"Query '{q}' should contain CATEGORY_FILES, got {cats}"
        names = router.get_tool_names(q)
        assert names is not None
        assert "file_manager" in names or "pdf_manager" in names
        assert "ask_clarification" in names
        tools = router.get_tools_for_message(q)
        assert tools is not None
        assert 0 < len(tools) < len(default_registry.get_all())


def test_web_media_intent_routing(router: ToolRouter):
    web_queries = [
        "cari di web berita teknologi terbaru",
        "download video dari https://youtube.com/watch?v=abcd",
        "ambil screenshot web https://google.com",
        "ekstrak teks foto ini menggunakan ocr",
        "putar lagu lofi hip hop",
    ]
    for q in web_queries:
        cats = router.classify_categories(q)
        assert CATEGORY_WEB_MEDIA in cats, f"Query '{q}' should contain CATEGORY_WEB_MEDIA, got {cats}"
        names = router.get_tool_names(q)
        assert names is not None
        assert "web_search" in names or "media_downloader" in names or "web_screenshot" in names or "ocr_extract" in names or "media_control" in names


def test_dev_advanced_intent_routing(router: ToolRouter):
    dev_queries = [
        "buka aplikasi whatsapp",
        "cek top proses cpu yang jalan",
        "jalankan python repl untuk hitung 2 pangkat 50",
        "eksekusi perintah shell dmesg",
        "buat cronjob cek sensor tiap 10 menit",
    ]
    for q in dev_queries:
        cats = router.classify_categories(q)
        assert CATEGORY_DEV_ADVANCED in cats, f"Query '{q}' should contain CATEGORY_DEV_ADVANCED, got {cats}"
        names = router.get_tool_names(q)
        assert names is not None
        assert "package_manager" in names or "process_manager" in names or "python_repl" in names or "root_shell_exec" in names or "cronjob" in names


def test_memory_intent_routing(router: ToolRouter):
    mem_queries = [
        "ingat nama saya adalah Femas",
        "simpan fakta bahwa saya menyukai kopi arabika",
        "catat preferensi saya selalu gunakan mode gelap",
    ]
    for q in mem_queries:
        cats = router.classify_categories(q)
        assert CATEGORY_MEMORY in cats, f"Query '{q}' should contain CATEGORY_MEMORY, got {cats}"
        names = router.get_tool_names(q)
        assert names is not None
        assert "memory_manager" in names


def test_multi_domain_intent_routing(router: ToolRouter):
    q = "cek sisa baterai saya lalu cari info cuaca dan download video youtube ini https://youtu.be/123"
    cats = router.classify_categories(q)
    assert CATEGORY_SYSTEM in cats
    assert CATEGORY_WEB_MEDIA in cats

    names = router.get_tool_names(q)
    assert names is not None
    assert "system_settings" in names
    assert "media_downloader" in names


def test_ambiguous_action_fallback_to_all(router: ToolRouter):
    # Action verbs present, but domain unclear -> Fallback to ALL
    ambiguous_queries = [
        "tolong bereskan ini secepatnya",
        "lakukan sesuatu sekarang",
        "jalankan tugas itu segera",
        "periksa dan tindak lanjuti semuanya",
    ]
    for q in ambiguous_queries:
        cats = router.classify_categories(q)
        assert CATEGORY_ALL in cats, f"Query '{q}' should fall back to CATEGORY_ALL, got {cats}"
        assert router.get_tool_names(q) is None
        tools = router.get_tools_for_message(q)
        assert tools is not None
        assert len(tools) == len(default_registry.get_all())


def test_history_context_awareness_in_clarification(router: ToolRouter):
    history = [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "buatkan saya file report.txt"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "tc1",
                    "function": {"name": "ask_clarification", "arguments": '{"question": "Di mana simpan?"}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "tc1", "content": "Tanya pengguna"},
    ]

    # User answers simply with a path/folder
    user_reply = "simpan di /tmp ya"
    cats = router.classify_categories(user_reply, history=history)
    assert CATEGORY_FILES in cats

    tools = router.get_tools_for_message(user_reply, history=history)
    assert tools is not None
    tool_names = {t["function"]["name"] for t in tools}
    assert "file_manager" in tool_names


@pytest.mark.asyncio
async def test_agent_run_casual_bypasses_tools_completely():
    mock_ai = MagicMock()
    mock_msg = MagicMock(content="Halo! Ada yang bisa saya bantu hari ini?", tool_calls=None)
    mock_resp = MagicMock(choices=[MagicMock(message=mock_msg)], usage={"prompt_tokens": 150, "completion_tokens": 15, "total_tokens": 165})
    mock_ai.get_chat_completion = AsyncMock(return_value=mock_resp)

    agent = FafAgent(ai_client=mock_ai)
    ctx = ToolContext(chat_id=1234, user_id=5678)

    res = await agent.run("Halo!", context=ctx)
    assert "Halo!" in res.text

    # Verify get_chat_completion was invoked with tools=None!
    mock_ai.get_chat_completion.assert_called_once()
    call_kwargs = mock_ai.get_chat_completion.call_args[1]
    assert call_kwargs.get("tools") is None, "Casual greetings must pass tools=None to eliminate 10k token overhead"
