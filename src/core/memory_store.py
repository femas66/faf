from __future__ import annotations

import datetime
import logging
import os
import sqlite3
import threading
from typing import Any

from src.config import get_settings

logger = logging.getLogger("faf_agent.memory")

VALID_CATEGORIES = {
    "user_profile",
    "device",
    "preference",
    "routine",
    "alias",
    "rule",
    "general",
}


class MemoryStore:
    """Manajer memori permanen berbasis SQLite untuk menyimpan fakta pengguna dan perangkat."""

    def __init__(self, db_path: str | None = None) -> None:
        self.settings = get_settings()
        self._target_path = db_path or self.settings.memory_db_path
        self._actual_path: str | None = None
        self._lock = threading.Lock()
        self._init_db()

    def _resolve_db_path(self) -> str:
        if self._actual_path:
            return self._actual_path

        path = self._target_path
        parent = os.path.dirname(path)

        if parent:
            try:
                os.makedirs(parent, exist_ok=True)
                # Test write access
                test_file = os.path.join(parent, ".perm_test")
                with open(test_file, "w") as f:
                    f.write("ok")
                os.remove(test_file)
                self._actual_path = path
                return self._actual_path
            except OSError:
                logger.debug("Cannot write to %s, falling back to local home directory", parent)

        # Fallback to user home or current directory
        home_fallback = os.path.expanduser("~/.faf_memory.db")
        try:
            with open(home_fallback, "a"):
                pass
            self._actual_path = home_fallback
        except OSError:
            self._actual_path = os.path.abspath("faf_memory.db")

        return self._actual_path

    def _get_connection(self) -> sqlite3.Connection:
        path = self._resolve_db_path()
        conn = sqlite3.connect(path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS facts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        key TEXT UNIQUE NOT NULL,
                        category TEXT NOT NULL,
                        content TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_facts_key ON facts(key);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_facts_category ON facts(category);")
                conn.commit()

    def store_fact(self, key: str, content: str, category: str = "general") -> dict[str, Any]:
        """Simpan atau perbarui (upsert) fakta ke dalam basis data."""
        clean_key = key.strip().lower()
        clean_content = content.strip()
        cat = category.strip().lower()
        if cat not in VALID_CATEGORIES:
            cat = "general"

        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

        with self._lock:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO facts (key, category, content, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        content = excluded.content,
                        category = excluded.category,
                        updated_at = excluded.updated_at;
                    """,
                    (clean_key, cat, clean_content, now, now),
                )
                conn.commit()

        return self.get_fact(clean_key) or {}

    def get_fact(self, key: str) -> dict[str, Any] | None:
        """Ambil satu fakta berdasarkan kunci."""
        clean_key = key.strip().lower()
        with self._lock:
            with self._get_connection() as conn:
                row = conn.execute(
                    "SELECT id, key, category, content, created_at, updated_at FROM facts WHERE key = ?;",
                    (clean_key,),
                ).fetchone()
                if row:
                    return dict(row)
        return None

    def update_fact(
        self, key: str, content: str, category: str | None = None
    ) -> dict[str, Any] | None:
        """Perbarui isi fakta yang sudah ada."""
        clean_key = key.strip().lower()
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

        with self._lock:
            with self._get_connection() as conn:
                existing = conn.execute(
                    "SELECT category FROM facts WHERE key = ?;", (clean_key,)
                ).fetchone()
                if not existing:
                    return None

                cat = category.strip().lower() if category else existing["category"]
                if cat not in VALID_CATEGORIES:
                    cat = existing["category"]

                conn.execute(
                    """
                    UPDATE facts
                    SET content = ?, category = ?, updated_at = ?
                    WHERE key = ?;
                    """,
                    (content.strip(), cat, now, clean_key),
                )
                conn.commit()

        return self.get_fact(clean_key)

    def delete_fact(self, key: str) -> bool:
        """Hapus fakta berdasarkan kunci."""
        clean_key = key.strip().lower()
        with self._lock:
            with self._get_connection() as conn:
                cur = conn.execute("DELETE FROM facts WHERE key = ?;", (clean_key,))
                conn.commit()
                return cur.rowcount > 0

    def search_facts(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Cari fakta berdasarkan kata kunci di key, category, atau content."""
        q = f"%{query.strip().lower()}%"
        with self._lock:
            with self._get_connection() as conn:
                rows = conn.execute(
                    """
                    SELECT id, key, category, content, created_at, updated_at
                    FROM facts
                    WHERE key LIKE ? OR content LIKE ? OR category LIKE ?
                    ORDER BY updated_at DESC
                    LIMIT ?;
                    """,
                    (q, q, q, limit),
                ).fetchall()
                return [dict(r) for r in rows]

    def list_all_facts(self, category: str | None = None) -> list[dict[str, Any]]:
        """Daftar semua fakta yang tersimpan, opsional filter per kategori."""
        with self._lock:
            with self._get_connection() as conn:
                if category:
                    rows = conn.execute(
                        """
                        SELECT id, key, category, content, created_at, updated_at
                        FROM facts
                        WHERE category = ?
                        ORDER BY key ASC;
                        """,
                        (category.strip().lower(),),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT id, key, category, content, created_at, updated_at
                        FROM facts
                        ORDER BY category ASC, key ASC;
                        """
                    ).fetchall()
                return [dict(r) for r in rows]

    def clear_all_facts(self) -> int:
        """Hapus seluruh fakta dari memori."""
        with self._lock:
            with self._get_connection() as conn:
                cur = conn.execute("DELETE FROM facts;")
                conn.commit()
                return cur.rowcount

    def format_for_system_prompt(self, max_facts: int = 30) -> str:
        """Format fakta tersimpan ke dalam format teks yang siap diinjeksikan ke System Prompt LLM."""
        facts = self.list_all_facts()
        if not facts:
            return ""

        facts = facts[:max_facts]
        lines = [
            "[MEMORI PERMANEN & FAKTA PENGGUNA TERVERIFIKASI]",
            "Fakta, profil, dan preferensi pengguna yang tersimpan di memori jangka panjang lokal:",
        ]

        for f in facts:
            lines.append(f"• [{f['category']}] {f['key']}: {f['content']}")

        lines.append(
            "(Gunakan fakta permanen di atas secara alami dalam menjawab tanpa perlu bertanya ulang.)"
        )
        return "\n".join(lines)


# Global singleton instance
memory_store = MemoryStore()
