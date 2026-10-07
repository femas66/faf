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


def test_episodic_memory_store_crud(temp_memory_store):
    store = temp_memory_store

    # 1. Store episode
    ep1 = store.store_episode(
        title="Setup Root Zram",
        content="Berhasil mengaktifkan modul Zram Magisk 4GB pada perangkat POCO F5.",
        category="task_execution",
        importance=4,
        tags="magisk, root, zram",
    )
    assert ep1["id"] is not None
    assert ep1["title"] == "Setup Root Zram"
    assert ep1["importance"] == 4
    assert ep1["category"] == "task_execution"

    # 2. Get episode
    fetched = store.get_episode(ep1["id"])
    assert fetched is not None
    assert fetched["title"] == "Setup Root Zram"

    # 3. Store another episode
    ep2 = store.store_episode(
        title="Diskusi Liburan",
        content="Pengguna berencana liburan ke Bandung akhir pekan ini.",
        category="conversation",
        importance=3,
        tags="liburan, travel",
    )

    # 4. List episodes
    all_episodes = store.list_episodes()
    assert len(all_episodes) == 2

    # Filter by category
    task_eps = store.list_episodes(category="task_execution")
    assert len(task_eps) == 1
    assert task_eps[0]["title"] == "Setup Root Zram"

    # Filter by min_importance
    high_imp = store.list_episodes(min_importance=4)
    assert len(high_imp) == 1
    assert high_imp[0]["title"] == "Setup Root Zram"

    # 5. Search episodes
    search_res = store.search_episodes("Bandung")
    assert len(search_res) == 1
    assert search_res[0]["id"] == ep2["id"]

    # 6. Delete episode
    del_ok = store.delete_episode(ep1["id"])
    assert del_ok is True
    assert store.get_episode(ep1["id"]) is None
    assert len(store.list_episodes()) == 1

    # 7. Clear all episodes
    count = store.clear_all_episodes()
    assert count == 1
    assert len(store.list_episodes()) == 0


def test_knowledge_graph_store_and_traversal(temp_memory_store):
    store = temp_memory_store

    # 1. Add relations
    rel1 = store.add_relation(
        source="Femas",
        relation="owns",
        target="POCO F5",
        weight=1.0,
        context="Smartphone utama",
    )
    assert rel1["source_entity"] == "Femas"
    assert rel1["relation"] == "owns"
    assert rel1["target_entity"] == "POCO F5"

    store.add_relation(
        source="Femas",
        relation="likes",
        target="Americano",
        weight=0.9,
        context="Minuman kopi pagi",
    )
    store.add_relation(
        source="POCO F5",
        relation="runs",
        target="HyperOS",
        weight=1.0,
        context="OS Android 14",
    )
    store.add_relation(
        source="Budi",
        relation="is_friend_of",
        target="Femas",
        weight=0.8,
        context="Teman kerja",
    )

    # 2. Depth 1 Traversal for "Femas"
    hop1 = store.get_entity_relations(entity="Femas", depth=1)
    # Direct: Femas owns POCO F5, Femas likes Americano, Budi is_friend_of Femas
    assert len(hop1) >= 3
    targets_or_sources = {r["source_entity"] for r in hop1} | {r["target_entity"] for r in hop1}
    assert "POCO F5" in targets_or_sources
    assert "Americano" in targets_or_sources
    assert "Budi" in targets_or_sources
    # HyperOS shouldn't be in depth 1 (it is 2 hops away)
    assert not any(r["target_entity"] == "HyperOS" and r.get("hop") == 1 for r in hop1)

    # 3. Depth 2 Traversal for "Femas"
    hop2 = store.get_entity_relations(entity="Femas", depth=2)
    hop2_targets = {r["target_entity"] for r in hop2}
    assert "HyperOS" in hop2_targets

    # 4. Search graph
    search_rel = store.search_graph("Americano")
    assert len(search_rel) == 1
    assert search_rel[0]["relation"] == "likes"

    # 5. Delete relation
    del_ok = store.delete_relation(source="Femas", relation="likes", target="Americano")
    assert del_ok is True
    assert len(store.search_graph("Americano")) == 0

    # 6. Clear graph
    count = store.clear_graph()
    assert count >= 3
    assert len(store.list_all_relations()) == 0


def test_hybrid_search(temp_memory_store):
    store = temp_memory_store

    # Store across all 3 pillars
    store.store_fact(key="hobi_kopi", content="Suka manual brew dan espresso", category="preference")
    store.store_episode(
        title="Eksplorasi Kafe",
        content="Mencoba beans arabika Gayo di kedai kopi kemarin sore.",
        category="conversation",
    )
    store.add_relation(
        source="Femas",
        relation="drinks",
        target="Espresso",
        context="Kopi tanpa gula",
    )

    # Search term 'kopi' across all 3
    hybrid_res = store.hybrid_search("kopi")
    assert hybrid_res["total_matches"] >= 2
    assert len(hybrid_res["facts"]) >= 1
    assert len(hybrid_res["episodes"]) >= 1

    # Graph expansion test for 'Femas'
    femas_res = store.hybrid_search("Femas")
    assert len(femas_res["relations"]) >= 1
    assert femas_res["relations"][0]["target_entity"] == "Espresso"


def test_memory_reflection_consolidation(temp_memory_store):
    store = temp_memory_store

    store.store_fact(key="nama_user", content="Femas", category="user_profile")
    store.store_fact(key="kopi_favorit", content="Americano", category="preference")
    store.store_episode(title="Review Harian", content="Hari ini menyelesaikan modul agent.")
    store.add_relation(source="Femas", relation="owns", target="POCO F5")
    store.add_relation(source="Femas", relation="works_on", target="faf-agent")

    report = store.consolidate_memories()
    assert report["total_facts"] == 2
    assert report["total_episodes"] == 1
    assert report["total_relations"] == 2
    assert "Femas" in report["top_entities"]
    assert len(report["insights"]) >= 1


def test_full_system_prompt_cognitive_injection(temp_memory_store):
    store = temp_memory_store

    store.store_fact(key="nama_lengkap", content="Femas Akbar", category="user_profile")
    store.store_episode(
        title="Setup Agent Berhasil",
        content="Bot faf-agent aktif dengan Termux:API.",
        importance=4,
    )
    store.add_relation(
        source="Femas",
        relation="uses",
        target="Telegram Bot",
        context="Antarmuka chat",
    )

    prompt = store.format_for_system_prompt()
    assert "[MEMORI PERMANEN & FAKTA PENGGUNA TERVERIFIKASI]" in prompt
    assert "nama_lengkap: Femas Akbar" in prompt
    assert "[GRAF PENGETAHUAN & RELASI ENTITAS]" in prompt
    assert "Femas -> [uses] -> Telegram Bot" in prompt
    assert "[REKAMAN EPISODE & PENGALAMAN TERBARU]" in prompt
    assert "Setup Agent Berhasil" in prompt


async def test_memory_manager_tool_all_actions(temp_memory_store, monkeypatch):
    monkeypatch.setattr("src.tools.memory_mgr.memory_store", temp_memory_store)
    tool = MemoryManagerTool()

    # 1. Episodic actions
    res_ep = await tool.execute(
        _ctx(),
        action="store_episode",
        title="Uji Coba Root",
        content="Pengujian su bypass Magisk berhasil.",
        category="task_execution",
        importance=4,
        tags="root, magisk",
    )
    assert res_ep.success
    assert "Episode Riwayat Berhasil Dicatat" in res_ep.output

    res_ep_list = await tool.execute(_ctx(), action="list_episodes")
    assert res_ep_list.success
    assert "Uji Coba Root" in res_ep_list.output

    res_ep_search = await tool.execute(_ctx(), action="search_episodes", query="Magisk")
    assert res_ep_search.success
    assert "Uji Coba Root" in res_ep_search.output

    res_ep_del = await tool.execute(_ctx(), action="delete_episode", episode_id=1)
    assert res_ep_del.success
    assert "berhasil dihapus" in res_ep_del.output

    # 2. Graph actions
    res_graph_add = await tool.execute(
        _ctx(),
        action="add_relation",
        source="Femas",
        relation="developer_of",
        target="faf-agent",
        context_text="Proyek AI Agent",
    )
    assert res_graph_add.success
    assert "Relasi Berhasil Ditambahkan" in res_graph_add.output

    res_graph_query = await tool.execute(
        _ctx(),
        action="query_graph",
        entity="Femas",
        depth=1,
    )
    assert res_graph_query.success
    assert "developer_of" in res_graph_query.output

    res_graph_search = await tool.execute(_ctx(), action="search_graph", query="developer")
    assert res_graph_search.success
    assert "faf-agent" in res_graph_search.output

    res_graph_del = await tool.execute(
        _ctx(),
        action="delete_relation",
        source="Femas",
        relation="developer_of",
        target="faf-agent",
    )
    assert res_graph_del.success
    assert "berhasil dihapus" in res_graph_del.output

    # 3. Hybrid Search
    await tool.execute(
        _ctx(), action="store", key="nama_proyek", content="faf-agent AI Assistant"
    )
    res_hybrid = await tool.execute(_ctx(), action="hybrid_search", query="agent")
    assert res_hybrid.success
    assert "Pencarian Memori Terpadu" in res_hybrid.output
    assert "faf-agent AI Assistant" in res_hybrid.output

    # 4. Reflect
    res_reflect = await tool.execute(_ctx(), action="reflect")
    assert res_reflect.success
    assert "Laporan Refleksi & Konsolidasi" in res_reflect.output

