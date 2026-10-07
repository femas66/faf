from __future__ import annotations

import os
import pytest

from src.core.agent import FafAgent
from src.core.memory_store import MemoryStore, memory_store
from src.tools.base import ToolContext
from src.tools.memory_mgr import MemoryManagerTool


def _ctx() -> ToolContext:
    return ToolContext(chat_id=1, user_id=1)


@pytest.fixture
def temp_memory_store(tmp_path):
    db_file = str(tmp_path / "test_memory.db")
    store = MemoryStore(db_path=db_file)
    return store


def test_memory_store_crud(temp_memory_store):
    store = temp_memory_store

    # 1. Store
    fact1 = store.store_fact(
        key="nama_user", content="Femas", category="user_profile"
    )
    assert fact1["key"] == "nama_user"
    assert fact1["content"] == "Femas"
    assert fact1["category"] == "user_profile"

    # 2. Get
    fetched = store.get_fact("nama_user")
    assert fetched is not None
    assert fetched["content"] == "Femas"

    # 3. Upsert
    fact1_updated = store.store_fact(
        key="nama_user", content="Femas Akbar", category="user_profile"
    )
    assert fact1_updated["content"] == "Femas Akbar"

    # 4. Store another
    store.store_fact(
        key="model_hp", content="POCO F5 Root KSU", category="device"
    )
    store.store_fact(
        key="kopi_favorit", content="Americano tanpa gula", category="preference"
    )

    # 5. Search
    results = store.search_facts("kopi")
    assert len(results) == 1
    assert results[0]["key"] == "kopi_favorit"

    results_broad = store.search_facts("femas")
    assert len(results_broad) == 1

    # 6. List all & by category
    all_facts = store.list_all_facts()
    assert len(all_facts) == 3

    device_facts = store.list_all_facts(category="device")
    assert len(device_facts) == 1
    assert device_facts[0]["key"] == "model_hp"

    # 7. Update fact
    up = store.update_fact("model_hp", "POCO F5 Android 14 HyperOS")
    assert up is not None
    assert up["content"] == "POCO F5 Android 14 HyperOS"

    # 8. Format for system prompt
    prompt_snippet = store.format_for_system_prompt()
    assert "[MEMORI PERMANEN & FAKTA PENGGUNA TERVERIFIKASI]" in prompt_snippet
    assert "• [device] model_hp: POCO F5 Android 14 HyperOS" in prompt_snippet
    assert "• [preference] kopi_favorit: Americano tanpa gula" in prompt_snippet

    # 9. Delete
    deleted = store.delete_fact("kopi_favorit")
    assert deleted is True
    assert store.get_fact("kopi_favorit") is None

    # 10. Clear all
    count = store.clear_all_facts()
    assert count == 2
    assert len(store.list_all_facts()) == 0


async def test_memory_manager_tool_actions(temp_memory_store, monkeypatch):
    # Patch global memory_store to use our isolated fixture
    monkeypatch.setattr("src.tools.memory_mgr.memory_store", temp_memory_store)

    tool = MemoryManagerTool()

    # Store
    res = await tool.execute(
        _ctx(),
        action="store",
        key="jam_bangun",
        content="Pukul 06.00 WIB setiap pagi",
        category="routine",
    )
    assert res.success
    assert "Fakta Berhasil Disimpan" in res.output
    assert "jam_bangun" in res.output

    # Get
    res_get = await tool.execute(_ctx(), action="get", key="jam_bangun")
    assert res_get.success
    assert "Pukul 06.00 WIB" in res_get.output

    # Search
    res_search = await tool.execute(_ctx(), action="search", query="bangun")
    assert res_search.success
    assert "jam_bangun" in res_search.output

    # Update
    res_update = await tool.execute(
        _ctx(), action="update", key="jam_bangun", content="Pukul 05.30 WIB"
    )
    assert res_update.success
    assert "Pukul 05.30 WIB" in res_update.output

    # List
    res_list = await tool.execute(_ctx(), action="list")
    assert res_list.success
    assert "jam_bangun" in res_list.output

    # Delete
    res_del = await tool.execute(_ctx(), action="delete", key="jam_bangun")
    assert res_del.success
    assert "berhasil dihapus" in res_del.output

    # Clear all
    res_clear = await tool.execute(_ctx(), action="clear_all")
    assert res_clear.success


async def test_memory_manager_validation_errors(temp_memory_store, monkeypatch):
    monkeypatch.setattr("src.tools.memory_mgr.memory_store", temp_memory_store)
    tool = MemoryManagerTool()

    res = await tool.execute(_ctx(), action="store", key="", content="")
    assert not res.success
    assert "wajib diisi" in res.error

    res_del = await tool.execute(_ctx(), action="delete", key="tidak_ada")
    assert not res_del.success
    assert "tidak ditemukan" in res_del.error

    res_unknown = await tool.execute(_ctx(), action="invalid_action")
    assert not res_unknown.success
    assert "tidak dikenal" in res_unknown.error


def test_agent_dynamic_memory_prompt_injection(temp_memory_store, monkeypatch):
    # Patch global memory_store used in agent
    monkeypatch.setattr("src.core.agent.memory_store", temp_memory_store)

    agent = FafAgent()

    # Initial prompt without memories
    initial_prompt = agent.build_system_prompt()
    assert "• [user_profile]" not in initial_prompt

    # Store a fact
    temp_memory_store.store_fact(
        key="nama_panggilan", content="Femas", category="user_profile"
    )

    # Prompt now automatically includes the fact
    updated_prompt = agent.build_system_prompt()
    assert "• [user_profile] nama_panggilan: Femas" in updated_prompt

    # Verify history maintains this memory after clear_history
    history = agent.get_history(chat_id=999)
    assert "nama_panggilan: Femas" in history[0]["content"]

    agent.clear_history(chat_id=999)
    cleared_history = agent.get_history(chat_id=999)
    assert "nama_panggilan: Femas" in cleared_history[0]["content"]


def test_memory_manager_registered_in_default_registry():
    from src.tools import create_default_registry

    reg = create_default_registry()
    assert reg.get("memory_manager") is not None
