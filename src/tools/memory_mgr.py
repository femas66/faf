from __future__ import annotations

import logging
from typing import Any

from src.core.memory_store import memory_store, VALID_CATEGORIES
from src.tools.base import BaseTool, ToolContext, ToolResult

logger = logging.getLogger("faf_agent.tools.memory")


class MemoryManagerTool(BaseTool):
    """Tool memori jangka panjang permanen untuk menyimpan dan mengelola fakta pengguna & perangkat."""

    name = "memory_manager"
    description = (
        "Tool memori jangka panjang permanen (Hermes-grade Persistent Memory). "
        "Gunakan tool ini untuk MENYIMPAN dan MENGINGAT fakta penting tentang pengguna "
        "(nama, pekerjaan, preferensi, kopi/makanan kesukaan, kebiasaan harian, jam rutin), "
        "info perangkat fisik (model HP, ROM, modul root, konfigurasi khusus), serta aturan tetap. "
        "Fakta yang tersimpan TIDAK AKAN HILANG saat bot direstart atau riwayat chat direset (/clear), "
        "karena otomatis dimuat ke dalam memori sistem AI pada setiap sesi percakapan. "
        "Aksi: 'store' (simpan fakta), 'update' (perbarui fakta), 'get' (lihat 1 fakta), "
        "'search' (cari kata kunci), 'list' (daftar semua fakta), 'delete' (hapus fakta)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["store", "update", "get", "search", "list", "delete", "clear_all"],
                "description": (
                    "Aksi memori: 'store' (simpan fakta baru), 'update' (perbarui fakta ada), "
                    "'get' (ambil per key), 'search' (cari kata kunci), 'list' (lihat semua memori), "
                    "'delete' (hapus fakta), 'clear_all' (kosongkan seluruh memori)."
                ),
                "default": "store",
            },
            "key": {
                "type": "string",
                "description": "Kunci/label fakta singkat (contoh: 'nama_panggilan', 'kopi_favorit', 'model_hp', 'jam_tidur').",
            },
            "content": {
                "type": "string",
                "description": "Isi detail fakta lengkap yang ingin diingat.",
            },
            "category": {
                "type": "string",
                "enum": [
                    "user_profile",
                    "device",
                    "preference",
                    "routine",
                    "alias",
                    "rule",
                    "general",
                ],
                "description": "Kategori fakta: 'user_profile' (data diri), 'device' (HP/sistem), 'preference' (selera/kesukaan), 'routine' (kebiasaan/jadwal), 'rule' (aturan khusus).",
                "default": "general",
            },
            "query": {
                "type": "string",
                "description": "Kata kunci pencarian memori (wajib jika action='search').",
            },
        },
        "required": [],
    }

    async def execute(self, context: ToolContext, **kwargs: Any) -> ToolResult:
        action = str(kwargs.get("action") or "store").lower().strip()

        # ------------------------------------------------------------------
        # 1. Action: STORE
        # ------------------------------------------------------------------
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
                    f"Fakta Berhasil Disimpan ke Memori Jangka Panjang\n"
                    f"• Kunci     : {fact.get('key')}\n"
                    f"• Kategori  : {fact.get('category')}\n"
                    f"• Isi Fakta : {fact.get('content')}\n\n"
                    f"Catatan: Fakta ini kini permanen dan akan selalu diingat oleh faf-agent di setiap percakapan."
                ),
            )

        # ------------------------------------------------------------------
        # 2. Action: UPDATE
        # ------------------------------------------------------------------
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
                    error=f"Fakta dengan kunci '{key}' tidak ditemukan untuk diperbarui. Gunakan action='store' jika ingin membuat baru.",
                )

            return ToolResult(
                success=True,
                output=(
                    f"Fakta Berhasil Diperbarui\n"
                    f"• Kunci     : {fact.get('key')}\n"
                    f"• Kategori  : {fact.get('category')}\n"
                    f"• Isi Baru  : {fact.get('content')}\n"
                    f"• Diperbarui: {fact.get('updated_at')}"
                ),
            )

        # ------------------------------------------------------------------
        # 3. Action: GET
        # ------------------------------------------------------------------
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
                    f"Detail Fakta Memori\n"
                    f"• Kunci     : {fact['key']}\n"
                    f"• Kategori  : {fact['category']}\n"
                    f"• Isi Fakta : {fact['content']}\n"
                    f"• Tersimpan : {fact['created_at']}\n"
                    f"• Update    : {fact['updated_at']}"
                ),
            )

        # ------------------------------------------------------------------
        # 4. Action: SEARCH
        # ------------------------------------------------------------------
        elif action == "search":
            query = str(kwargs.get("query") or "").strip()
            if not query:
                return ToolResult(success=False, output="", error="Parameter 'query' wajib diisi.")

            matches = memory_store.search_facts(query)
            if not matches:
                return ToolResult(
                    success=True,
                    output=f"Tidak ada fakta di memori yang cocok dengan pencarian: '{query}'.",
                )

            lines = [f"Hasil Pencarian Memori ({len(matches)} fakta ditemukan):", ""]
            for i, f in enumerate(matches, 1):
                lines.append(f"{i}. [{f['category']}] {f['key']}")
                lines.append(f"   Isi: {f['content']}")
            return ToolResult(success=True, output="\n".join(lines))

        # ------------------------------------------------------------------
        # 5. Action: LIST
        # ------------------------------------------------------------------
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

        # ------------------------------------------------------------------
        # 6. Action: DELETE
        # ------------------------------------------------------------------
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
            else:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Fakta '{key}' tidak ditemukan di memori.",
                )

        # ------------------------------------------------------------------
        # 7. Action: CLEAR_ALL
        # ------------------------------------------------------------------
        elif action == "clear_all":
            count = memory_store.clear_all_facts()
            return ToolResult(
                success=True,
                output=f"Seluruh memori permanen telah dikosongkan ({count} fakta dihapus).",
            )

        return ToolResult(
            success=False,
            output="",
            error=f"Aksi '{action}' tidak dikenal. Pilihan: store, update, get, search, list, delete, clear_all.",
        )
