from __future__ import annotations

import logging
from typing import Any

from src.core.memory_store import memory_store, VALID_CATEGORIES, VALID_EPISODE_CATEGORIES
from src.tools.base import BaseTool, ToolContext, ToolResult

logger = logging.getLogger("faf_agent.tools.memory")


class MemoryManagerTool(BaseTool):
    """Tool Arsitektur Memori Kognitif Hermes (Persistent Facts, Episodic Memory, & Knowledge Graph RAG)."""

    name = "memory_manager"
    description = (
        "Tool Arsitektur Memori Kognitif Hermes (Hermes Cognitive Architecture). "
        "Mengelola 3 lapisan memori cerdas: "
        "1. Fakta Permanen (store, update, get, search, list, delete, clear_all): Profil user, device, preferensi, aturan. "
        "2. Memori Episodik (store_episode, list_episodes, search_episodes, delete_episode): Catatan peristiwa, tugas, pengalaman masa lalu. "
        "3. Graf Pengetahuan (add_relation, query_graph, search_graph, delete_relation): Relasi subjek-predikat-objek dan multi-hop Graph RAG. "
        "4. Pencarian Terpadu (hybrid_search): Temukan informasi melintasi fakta, episode, dan graf secara simultan. "
        "5. Refleksi Memori (reflect): Jalankan konsolidasi dan analisis pola kebiasaan pengguna."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "store",
                    "update",
                    "get",
                    "search",
                    "list",
                    "delete",
                    "clear_all",
                    "store_episode",
                    "list_episodes",
                    "search_episodes",
                    "delete_episode",
                    "add_relation",
                    "query_graph",
                    "search_graph",
                    "delete_relation",
                    "hybrid_search",
                    "reflect",
                ],
                "description": (
                    "Aksi memori: "
                    "'store'/'update'/'get'/'search'/'list'/'delete' (fakta permanen), "
                    "'store_episode'/'list_episodes'/'search_episodes'/'delete_episode' (memori autobiografis peristiwa), "
                    "'add_relation'/'query_graph'/'search_graph'/'delete_relation' (graf pengetahuan entitas), "
                    "'hybrid_search' (pencarian terpadu RAG), "
                    "'reflect' (konsolidasi memori kognitif)."
                ),
                "default": "store",
            },
            # Parameter Fakta
            "key": {
                "type": "string",
                "description": "Kunci fakta singkat (contoh: 'nama_panggilan', 'kopi_favorit', 'model_hp').",
            },
            "content": {
                "type": "string",
                "description": "Isi detail fakta atau deskripsi peristiwa episode yang ingin disimpan.",
            },
            "category": {
                "type": "string",
                "description": "Kategori fakta ('user_profile', 'device', 'preference', 'routine', 'rule', 'general') atau kategori episode ('conversation', 'task_execution', 'system_event', 'milestone').",
                "default": "general",
            },
            "query": {
                "type": "string",
                "description": "Kata kunci pencarian (wajib untuk 'search', 'search_episodes', 'search_graph', 'hybrid_search').",
            },
            # Parameter Episodik
            "title": {
                "type": "string",
                "description": "Judul ringkas peristiwa atau episode (wajib untuk 'store_episode').",
            },
            "importance": {
                "type": "integer",
                "description": "Tingkat kepentingan peristiwa (skala 1-5, default 3).",
                "default": 3,
            },
            "tags": {
                "type": "string",
                "description": "Tag atau label penanda episode, dipisahkan koma (contoh: 'magisk, root, zram').",
            },
            "episode_id": {
                "type": "integer",
                "description": "ID episode untuk aksi 'delete_episode'.",
            },
            # Parameter Graf Pengetahuan
            "source": {
                "type": "string",
                "description": "Entitas sumber (subjek) dalam relasi graf (contoh: 'Femas', 'POCO F5').",
            },
            "relation": {
                "type": "string",
                "description": "Nama relasi/predikat penghubung (contoh: 'owns', 'likes', 'works_as', 'runs').",
            },
            "target": {
                "type": "string",
                "description": "Entitas target (objek) dalam relasi graf (contoh: 'POCO F5', 'Americano', 'Software Engineer').",
            },
            "weight": {
                "type": "number",
                "description": "Bobot kekuatan relasi graf (default 1.0).",
                "default": 1.0,
            },
            "context_text": {
                "type": "string",
                "description": "Keterangan kontekstual tambahan pada relasi graf.",
            },
            "entity": {
                "type": "string",
                "description": "Nama entitas yang ingin dieksplorasi koneksi graf-nya (wajib untuk 'query_graph').",
            },
            "depth": {
                "type": "integer",
                "description": "Kedalaman penjelajahan graf multi-hop (1: tetangga langsung, 2: 2-hop subgraph). Default 1.",
                "default": 1,
            },
            "limit": {
                "type": "integer",
                "description": "Batas jumlah hasil yang ditampilkan (default 10).",
                "default": 10,
            },
        },
        "required": [],
    }

    async def execute(self, context: ToolContext, **kwargs: Any) -> ToolResult:
        action = str(kwargs.get("action") or "store").lower().strip()

        # ==================================================================
        # 1. AKSI FAKTA PERMANEN: STORE, UPDATE, GET, SEARCH, LIST, DELETE, CLEAR_ALL
        # ==================================================================
        if action == "store":
            key = str(kwargs.get("key") or "").strip()
            content = str(kwargs.get("content") or "").strip()
            category = str(kwargs.get("category") or "general").strip()

            if not key or not content:
                return ToolResult(
                    success=False,
                    output="",
                    error="Parameter 'key' dan 'content' wajib diisi untuk menyimpan fakta baru.",
                )

            fact = memory_store.store_fact(key=key, content=content, category=category)
            return ToolResult(
                success=True,
                output=(
                    "Fakta Berhasil Disimpan ke Memori Jangka Panjang\n"
                    f"• Kunci     : {fact.get('key')}\n"
                    f"• Kategori  : {fact.get('category')}\n"
                    f"• Isi Fakta : {fact.get('content')}\n\n"
                    "Catatan: Fakta ini permanen dan otomatis dimuat pada setiap percakapan baru."
                ),
            )

        elif action == "update":
            key = str(kwargs.get("key") or "").strip()
            content = str(kwargs.get("content") or "").strip()
            category = kwargs.get("category")

            if not key or not content:
                return ToolResult(
                    success=False,
                    output="",
                    error="Parameter 'key' dan 'content' wajib diisi untuk memperbarui fakta.",
                )

            fact = memory_store.update_fact(key=key, content=content, category=category)
            if not fact:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Fakta dengan kunci '{key}' tidak ditemukan. Gunakan action='store' jika ingin membuat baru.",
                )

            return ToolResult(
                success=True,
                output=(
                    "Fakta Berhasil Diperbarui\n"
                    f"• Kunci     : {fact.get('key')}\n"
                    f"• Kategori  : {fact.get('category')}\n"
                    f"• Isi Baru  : {fact.get('content')}\n"
                    f"• Diperbarui: {fact.get('updated_at')}"
                ),
            )

        elif action == "get":
            key = str(kwargs.get("key") or "").strip()
            if not key:
                return ToolResult(success=False, output="", error="Parameter 'key' wajib diisi.")

            fact = memory_store.get_fact(key)
            if not fact:
                return ToolResult(
                    success=True,
                    output=f"Tidak ditemukan fakta dengan kunci '{key}' di memori jangka panjang.",
                )

            return ToolResult(
                success=True,
                output=(
                    "Detail Fakta Memori\n"
                    f"• Kunci     : {fact['key']}\n"
                    f"• Kategori  : {fact['category']}\n"
                    f"• Isi Fakta : {fact['content']}\n"
                    f"• Tersimpan : {fact['created_at']}\n"
                    f"• Update    : {fact['updated_at']}"
                ),
            )

        elif action == "search":
            query = str(kwargs.get("query") or "").strip()
            if not query:
                return ToolResult(success=False, output="", error="Parameter 'query' wajib diisi.")

            limit = int(kwargs.get("limit") or 10)
            matches = memory_store.search_facts(query, limit=limit)
            if not matches:
                return ToolResult(
                    success=True,
                    output=f"Tidak ada fakta di memori yang cocok dengan pencarian: '{query}'.",
                )

            lines = [f"Hasil Pencarian Memori Fakta ({len(matches)} ditemukan):", ""]
            for i, f in enumerate(matches, 1):
                lines.append(f"{i}. [{f['category']}] {f['key']}")
                lines.append(f"   Isi: {f['content']}")
            return ToolResult(success=True, output="\n".join(lines))

        elif action == "list":
            cat = kwargs.get("category")
            facts = memory_store.list_all_facts(category=cat)
            if not facts:
                msg = f"Belum ada fakta yang tersimpan di memori{' untuk kategori ' + cat if cat else ''}."
                return ToolResult(success=True, output=msg)

            lines = [f"Daftar Seluruh Memori Jangka Panjang ({len(facts)} fakta):", ""]
            current_cat = ""
            for f in facts:
                if f["category"] != current_cat:
                    current_cat = f["category"]
                    lines.append(f"\n📂 Kategori: {current_cat.upper()}")
                lines.append(f"• {f['key']}: {f['content']}")

            return ToolResult(success=True, output="\n".join(lines).strip())

        elif action == "delete":
            key = str(kwargs.get("key") or "").strip()
            if not key:
                return ToolResult(success=False, output="", error="Parameter 'key' wajib diisi.")

            deleted = memory_store.delete_fact(key)
            if deleted:
                return ToolResult(
                    success=True,
                    output=f"Fakta '{key}' berhasil dihapus dari memori permanen.",
                )
            return ToolResult(
                success=False,
                output="",
                error=f"Fakta '{key}' tidak ditemukan di memori.",
            )

        elif action == "clear_all":
            count = memory_store.clear_all_facts()
            return ToolResult(
                success=True,
                output=f"Seluruh fakta permanen telah dikosongkan ({count} fakta dihapus).",
            )

        # ==================================================================
        # 2. AKSI MEMORI EPISODIK: STORE_EPISODE, LIST_EPISODES, SEARCH_EPISODES, DELETE_EPISODE
        # ==================================================================
        elif action == "store_episode":
            title = str(kwargs.get("title") or "").strip()
            content = str(kwargs.get("content") or "").strip()
            category = str(kwargs.get("category") or "conversation").strip()
            importance = int(kwargs.get("importance") or 3)
            tags = str(kwargs.get("tags") or "").strip()

            if not title or not content:
                return ToolResult(
                    success=False,
                    output="",
                    error="Parameter 'title' dan 'content' wajib diisi untuk mencatat episode baru.",
                )

            ep = memory_store.store_episode(
                title=title,
                content=content,
                category=category,
                importance=importance,
                tags=tags,
            )

            return ToolResult(
                success=True,
                output=(
                    "Episode Riwayat Berhasil Dicatat ke Memori Episodik\n"
                    f"• ID          : {ep.get('id')}\n"
                    f"• Judul       : {ep.get('title')}\n"
                    f"• Kategori    : {ep.get('category')}\n"
                    f"• Kepentingan : {ep.get('importance')}/5\n"
                    f"• Tags        : {ep.get('tags') or '-'}\n"
                    f"• Deskripsi   : {ep.get('content')}"
                ),
            )

        elif action == "list_episodes":
            limit = int(kwargs.get("limit") or 10)
            category = kwargs.get("category")
            episodes = memory_store.list_episodes(limit=limit, category=category)

            if not episodes:
                return ToolResult(
                    success=True,
                    output="Belum ada rekaman episode yang tersimpan di memori autobiografis.",
                )

            lines = [f"Daftar Rekaman Episode Terkini ({len(episodes)} episode):", ""]
            for ep in episodes:
                ts_short = ep.get("event_timestamp", "")[:16].replace("T", " ")
                lines.append(f"• [ID {ep['id']}] [{ep['category']}] ({ts_short}) - {ep['title']}")
                lines.append(f"  Kepentingan: {ep['importance']}/5 | Tags: {ep.get('tags') or '-'}")
                lines.append(f"  Ringkasan  : {ep['content']}")
                lines.append("")
            return ToolResult(success=True, output="\n".join(lines).strip())

        elif action == "search_episodes":
            query = str(kwargs.get("query") or "").strip()
            if not query:
                return ToolResult(success=False, output="", error="Parameter 'query' wajib diisi.")

            limit = int(kwargs.get("limit") or 10)
            matches = memory_store.search_episodes(query, limit=limit)
            if not matches:
                return ToolResult(
                    success=True,
                    output=f"Tidak ditemukan episode yang cocok dengan pencarian: '{query}'.",
                )

            lines = [f"Hasil Pencarian Memori Episodik ({len(matches)} episode ditemukan):", ""]
            for ep in matches:
                ts_short = ep.get("event_timestamp", "")[:16].replace("T", " ")
                lines.append(f"• [ID {ep['id']}] ({ts_short}) {ep['title']}")
                lines.append(f"  Isi: {ep['content']}")
            return ToolResult(success=True, output="\n".join(lines))

        elif action == "delete_episode":
            ep_id = kwargs.get("episode_id")
            if ep_id is None:
                return ToolResult(success=False, output="", error="Parameter 'episode_id' wajib diisi.")

            deleted = memory_store.delete_episode(int(ep_id))
            if deleted:
                return ToolResult(
                    success=True,
                    output=f"Episode ID {ep_id} berhasil dihapus dari memori episodik.",
                )
            return ToolResult(
                success=False,
                output="",
                error=f"Episode ID {ep_id} tidak ditemukan di memori.",
            )

        # ==================================================================
        # 3. AKSI GRAF PENGETAHUAN: ADD_RELATION, QUERY_GRAPH, SEARCH_GRAPH, DELETE_RELATION
        # ==================================================================
        elif action == "add_relation":
            source = str(kwargs.get("source") or "").strip()
            relation = str(kwargs.get("relation") or "").strip()
            target = str(kwargs.get("target") or "").strip()
            weight = float(kwargs.get("weight") or 1.0)
            context_text = str(kwargs.get("context_text") or "").strip()

            if not source or not relation or not target:
                return ToolResult(
                    success=False,
                    output="",
                    error="Parameter 'source', 'relation', dan 'target' wajib diisi untuk membuat relasi graf.",
                )

            rel_data = memory_store.add_relation(
                source=source,
                relation=relation,
                target=target,
                weight=weight,
                context=context_text,
            )

            return ToolResult(
                success=True,
                output=(
                    "Relasi Berhasil Ditambahkan ke Graf Pengetahuan\n"
                    f"• Hubungan : {rel_data.get('source_entity')} -> [{rel_data.get('relation')}] -> {rel_data.get('target_entity')}\n"
                    f"• Bobot    : {rel_data.get('weight')}\n"
                    f"• Konteks  : {rel_data.get('context') or '-'}\n\n"
                    "Catatan: Relasi ini kini terhubung dalam memori Graph RAG asosiatif agen."
                ),
            )

        elif action == "query_graph":
            entity = str(kwargs.get("entity") or "").strip()
            if not entity:
                return ToolResult(
                    success=False,
                    output="",
                    error="Parameter 'entity' wajib diisi untuk menjelajahi koneksi graf.",
                )

            depth = max(1, min(2, int(kwargs.get("depth") or 1)))
            limit = int(kwargs.get("limit") or 20)
            relations = memory_store.get_entity_relations(entity=entity, depth=depth, max_results=limit)

            if not relations:
                return ToolResult(
                    success=True,
                    output=f"Tidak ditemukan koneksi graf yang terhubung dengan entitas: '{entity}'.",
                )

            lines = [f"Eksplorasi Graf Pengetahuan untuk '{entity}' (Kedalaman: {depth}-Hop):", ""]
            for r in relations:
                hop_badge = f"[Hop {r.get('hop', 1)}]"
                ctx_note = f" (Konteks: {r['context']})" if r.get("context") else ""
                lines.append(
                    f"• {hop_badge} {r['source_entity']} -> [{r['relation']}] -> {r['target_entity']}{ctx_note}"
                )
            return ToolResult(success=True, output="\n".join(lines))

        elif action == "search_graph":
            query = str(kwargs.get("query") or "").strip()
            if not query:
                return ToolResult(success=False, output="", error="Parameter 'query' wajib diisi.")

            limit = int(kwargs.get("limit") or 15)
            relations = memory_store.search_graph(query, limit=limit)
            if not relations:
                return ToolResult(
                    success=True,
                    output=f"Tidak ditemukan relasi graf yang cocok dengan kata kunci: '{query}'.",
                )

            lines = [f"Hasil Pencarian Graf Pengetahuan ({len(relations)} relasi):", ""]
            for r in relations:
                ctx_note = f" | Konteks: {r['context']}" if r.get("context") else ""
                lines.append(
                    f"• {r['source_entity']} -> [{r['relation']}] -> {r['target_entity']}{ctx_note}"
                )
            return ToolResult(success=True, output="\n".join(lines))

        elif action == "delete_relation":
            source = str(kwargs.get("source") or "").strip()
            relation = str(kwargs.get("relation") or "").strip()
            target = str(kwargs.get("target") or "").strip()

            if not source or not relation or not target:
                return ToolResult(
                    success=False,
                    output="",
                    error="Parameter 'source', 'relation', dan 'target' wajib diisi untuk menghapus relasi graf.",
                )

            deleted = memory_store.delete_relation(source=source, relation=relation, target=target)
            if deleted:
                return ToolResult(
                    success=True,
                    output=f"Relasi '{source} -> [{relation}] -> {target}' berhasil dihapus dari graf.",
                )
            return ToolResult(
                success=False,
                output="",
                error=f"Relasi '{source} -> [{relation}] -> {target}' tidak ditemukan di graf.",
            )

        # ==================================================================
        # 4. AKSI HYBRID SEARCH (UNIFIED MULTI-LAYER RAG)
        # ==================================================================
        elif action == "hybrid_search":
            query = str(kwargs.get("query") or "").strip()
            if not query:
                return ToolResult(success=False, output="", error="Parameter 'query' wajib diisi.")

            limit = int(kwargs.get("limit") or 10)
            res = memory_store.hybrid_search(query=query, limit=limit)

            lines = [
                f"Pencarian Memori Terpadu (Hybrid RAG) untuk: '{query}'",
                f"Total Temuan: {res['total_matches']}",
                "",
            ]

            if res["facts"]:
                lines.append("📌 FAKTA PERMANEN:")
                for f in res["facts"]:
                    lines.append(f"• [{f['category']}] {f['key']}: {f['content']}")
                lines.append("")

            if res["relations"]:
                lines.append("🕸️ GRAF PENGETAHUAN:")
                for r in res["relations"]:
                    ctx = f" ({r['context']})" if r.get("context") else ""
                    lines.append(f"• {r['source_entity']} -> [{r['relation']}] -> {r['target_entity']}{ctx}")
                lines.append("")

            if res["episodes"]:
                lines.append("📖 RIWAYAT EPISODIK:")
                for e in res["episodes"]:
                    lines.append(f"• {e['title']}: {e['content']}")
                lines.append("")

            if res["total_matches"] == 0:
                return ToolResult(
                    success=True,
                    output=f"Tidak ada temuan memori (fakta, graf, maupun episode) untuk kueri: '{query}'.",
                )

            return ToolResult(success=True, output="\n".join(lines).strip())

        # ==================================================================
        # 5. AKSI REFLEKSI & KONSOLIDASI (DREAM ROUTINE)
        # ==================================================================
        elif action == "reflect":
            report = memory_store.consolidate_memories()

            lines = [
                "Laporan Refleksi & Konsolidasi Memori Kognitif Hermes",
                f"• Waktu Refleksi : {report['timestamp'][:19].replace('T', ' ')} UTC",
                f"• Total Fakta    : {report['total_facts']}",
                f"• Total Episode  : {report['total_episodes']}",
                f"• Total Relasi   : {report['total_relations']}",
                "",
                "Distribusi Kategori Fakta:",
            ]
            for cat, count in report["category_distribution"].items():
                lines.append(f"• {cat}: {count}")

            lines.append("")
            if report["top_entities"]:
                lines.append(f"Entitas Utama: {', '.join(report['top_entities'])}")

            if report["insights"]:
                lines.append("")
                lines.append("Insight Terkonsolidasi:")
                for ins in report["insights"]:
                    lines.append(f"• {ins}")

            return ToolResult(success=True, output="\n".join(lines).strip())

        return ToolResult(
            success=False,
            output="",
            error=(
                f"Aksi '{action}' tidak dikenal. Pilihan: store, update, get, search, list, delete, clear_all, "
                "store_episode, list_episodes, search_episodes, delete_episode, add_relation, query_graph, "
                "search_graph, delete_relation, hybrid_search, reflect."
            ),
        )

