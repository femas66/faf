from __future__ import annotations

import datetime
import json
import logging
import os
import re
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

VALID_EPISODE_CATEGORIES = {
    "conversation",
    "task_execution",
    "system_event",
    "milestone",
    "preference_change",
    "general",
}


def _clean_fts_query(query: str) -> str:
    """Sanitize and tokenize input string into safe FTS5 prefix match syntax."""
    tokens = re.findall(r"[\w]+", query)
    if not tokens:
        return ""
    return " ".join(f'"{t}"*' for t in tokens)


class MemoryStore:
    """Arsitektur Memori Kognitif Hermes (Hermes Cognitive Architecture).

    Mencakup 3 pilar utama:
    1. Memori Deklaratif/Fakta Permanen (User Profile, Device, Preferences, Rules).
    2. Memori Episodik (Riwayat peristiwa, pengalaman tugas, milestone, dan konteks waktu).
    3. Graf Pengetahuan & Relasi Entitas (Graph RAG dengan multi-hop associative traversal).
    Dilengkapi pencarian terpadu Hybrid FTS5 (BM25) dan konsolidasi refleksi berkala.
    """

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
                test_file = os.path.join(parent, ".perm_test")
                with open(test_file, "w") as f:
                    f.write("ok")
                os.remove(test_file)
                self._actual_path = path
                return self._actual_path
            except OSError:
                logger.debug("Cannot write to %s, falling back to local home directory", parent)

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
        conn = sqlite3.connect(path, timeout=15.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock:
            with self._get_connection() as conn:
                # 1. Tabel Fakta Permanen
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

                # 2. Tabel Memori Episodik (Episodic Experiences & Events)
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS episodes (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        title TEXT NOT NULL,
                        content TEXT NOT NULL,
                        category TEXT NOT NULL DEFAULT 'conversation',
                        importance INTEGER NOT NULL DEFAULT 3,
                        tags TEXT DEFAULT '',
                        event_timestamp TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_episodes_category ON episodes(category);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_episodes_importance ON episodes(importance);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_episodes_timestamp ON episodes(event_timestamp);")

                # 3. Tabel Graf Pengetahuan (Knowledge Graph Entities & Relations)
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS graph_entities (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT UNIQUE NOT NULL,
                        entity_type TEXT NOT NULL DEFAULT 'concept',
                        attributes TEXT DEFAULT '{}',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_graph_entities_name ON graph_entities(name);")

                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS graph_relations (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        source_entity TEXT NOT NULL,
                        relation TEXT NOT NULL,
                        target_entity TEXT NOT NULL,
                        weight REAL NOT NULL DEFAULT 1.0,
                        context TEXT DEFAULT '',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        UNIQUE(source_entity, relation, target_entity)
                    );
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_graph_rel_source ON graph_relations(source_entity);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_graph_rel_target ON graph_relations(target_entity);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_graph_rel_relation ON graph_relations(relation);")

                # 4. Tabel Virtual FTS5 Terpadu untuk Hybrid BM25 Search
                try:
                    conn.execute(
                        """
                        CREATE VIRTUAL TABLE IF NOT EXISTS fts_unified USING fts5(
                            source_type,
                            source_id UNINDEXED,
                            title,
                            content,
                            tags
                        );
                        """
                    )
                    # Migrasi data awal ke FTS jika tabel FTS masih kosong tapi facts sudah ada
                    fts_count = conn.execute("SELECT count(*) FROM fts_unified;").fetchone()[0]
                    facts_count = conn.execute("SELECT count(*) FROM facts;").fetchone()[0]
                    if fts_count == 0 and facts_count > 0:
                        conn.execute(
                            """
                            INSERT INTO fts_unified (source_type, source_id, title, content, tags)
                            SELECT 'fact', id, key, content, category FROM facts;
                            """
                        )
                except sqlite3.OperationalError as e:
                    logger.warning("FTS5 table initialization skipped or failed: %s", e)

                conn.commit()

    # =========================================================================
    # PILAR 1: MEMORI FAKTA PERMANEN (DECLARATIVE FACTS)
    # =========================================================================

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
                row = conn.execute("SELECT id FROM facts WHERE key = ?;", (clean_key,)).fetchone()
                fact_id = row["id"] if row else 0

                # Sinkronkan FTS5
                try:
                    conn.execute(
                        "DELETE FROM fts_unified WHERE source_type = 'fact' AND source_id = ?;",
                        (fact_id,),
                    )
                    conn.execute(
                        "INSERT INTO fts_unified (source_type, source_id, title, content, tags) VALUES ('fact', ?, ?, ?, ?);",
                        (fact_id, clean_key, clean_content, cat),
                    )
                except sqlite3.OperationalError:
                    pass

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
                    "SELECT id, category FROM facts WHERE key = ?;", (clean_key,)
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

                # Sinkronkan FTS5
                try:
                    conn.execute(
                        "DELETE FROM fts_unified WHERE source_type = 'fact' AND source_id = ?;",
                        (existing["id"],),
                    )
                    conn.execute(
                        "INSERT INTO fts_unified (source_type, source_id, title, content, tags) VALUES ('fact', ?, ?, ?, ?);",
                        (existing["id"], clean_key, content.strip(), cat),
                    )
                except sqlite3.OperationalError:
                    pass

                conn.commit()

        return self.get_fact(clean_key)

    def delete_fact(self, key: str) -> bool:
        """Hapus fakta berdasarkan kunci."""
        clean_key = key.strip().lower()
        with self._lock:
            with self._get_connection() as conn:
                row = conn.execute("SELECT id FROM facts WHERE key = ?;", (clean_key,)).fetchone()
                if not row:
                    return False
                fact_id = row["id"]
                conn.execute("DELETE FROM facts WHERE key = ?;", (clean_key,))
                try:
                    conn.execute(
                        "DELETE FROM fts_unified WHERE source_type = 'fact' AND source_id = ?;",
                        (fact_id,),
                    )
                except sqlite3.OperationalError:
                    pass
                conn.commit()
                return True

    def search_facts(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Cari fakta berdasarkan pencarian teks."""
        q_fts = _clean_fts_query(query)
        with self._lock:
            with self._get_connection() as conn:
                if q_fts:
                    try:
                        rows = conn.execute(
                            """
                            SELECT f.id, f.key, f.category, f.content, f.created_at, f.updated_at
                            FROM fts_unified u
                            JOIN facts f ON f.id = u.source_id
                            WHERE u.source_type = 'fact' AND fts_unified MATCH ?
                            ORDER BY rank
                            LIMIT ?;
                            """,
                            (q_fts, limit),
                        ).fetchall()
                        if rows:
                            return [dict(r) for r in rows]
                    except sqlite3.OperationalError:
                        pass

                # Fallback ke LIKE jika FTS5 tidak menghasilkan data atau gagal
                like_q = f"%{query.strip().lower()}%"
                rows = conn.execute(
                    """
                    SELECT id, key, category, content, created_at, updated_at
                    FROM facts
                    WHERE key LIKE ? OR content LIKE ? OR category LIKE ?
                    ORDER BY updated_at DESC
                    LIMIT ?;
                    """,
                    (like_q, like_q, like_q, limit),
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
                try:
                    conn.execute("DELETE FROM fts_unified WHERE source_type = 'fact';")
                except sqlite3.OperationalError:
                    pass
                conn.commit()
                return cur.rowcount

    # =========================================================================
    # PILAR 2: MEMORI EPISODIK (EPISODIC MEMORY & EVENTS)
    # =========================================================================

    def store_episode(
        self,
        title: str,
        content: str,
        category: str = "conversation",
        importance: int = 3,
        tags: str = "",
        event_timestamp: str | None = None,
    ) -> dict[str, Any]:
        """Catat episode atau rekaman peristiwa baru ke dalam memori autobiografis agen."""
        clean_title = title.strip()
        clean_content = content.strip()
        cat = category.strip().lower()
        if cat not in VALID_EPISODE_CATEGORIES:
            cat = "conversation"

        imp = max(1, min(5, int(importance)))
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        ts = event_timestamp or now

        with self._lock:
            with self._get_connection() as conn:
                cur = conn.execute(
                    """
                    INSERT INTO episodes (title, content, category, importance, tags, event_timestamp, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (clean_title, clean_content, cat, imp, tags.strip(), ts, now, now),
                )
                episode_id = cur.lastrowid

                # Sinkronkan FTS5
                try:
                    conn.execute(
                        "INSERT INTO fts_unified (source_type, source_id, title, content, tags) VALUES ('episode', ?, ?, ?, ?);",
                        (episode_id, clean_title, clean_content, f"{cat}, {tags}".strip()),
                    )
                except sqlite3.OperationalError:
                    pass

                conn.commit()

                row = conn.execute("SELECT * FROM episodes WHERE id = ?;", (episode_id,)).fetchone()
                return dict(row) if row else {}

    def get_episode(self, episode_id: int) -> dict[str, Any] | None:
        """Ambil satu rekaman episode berdasarkan ID."""
        with self._lock:
            with self._get_connection() as conn:
                row = conn.execute("SELECT * FROM episodes WHERE id = ?;", (episode_id,)).fetchone()
                return dict(row) if row else None

    def list_episodes(
        self,
        limit: int = 20,
        category: str | None = None,
        min_importance: int = 1,
    ) -> list[dict[str, Any]]:
        """Daftar riwayat episode terurut dari yang paling terkini."""
        with self._lock:
            with self._get_connection() as conn:
                query = "SELECT * FROM episodes WHERE importance >= ?"
                params: list[Any] = [min_importance]
                if category:
                    query += " AND category = ?"
                    params.append(category.strip().lower())
                query += " ORDER BY event_timestamp DESC LIMIT ?;"
                params.append(limit)

                rows = conn.execute(query, tuple(params)).fetchall()
                return [dict(r) for r in rows]

    def search_episodes(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Cari rekaman episode menggunakan pencarian BM25 atau LIKE."""
        q_fts = _clean_fts_query(query)
        with self._lock:
            with self._get_connection() as conn:
                if q_fts:
                    try:
                        rows = conn.execute(
                            """
                            SELECT e.*
                            FROM fts_unified u
                            JOIN episodes e ON e.id = u.source_id
                            WHERE u.source_type = 'episode' AND fts_unified MATCH ?
                            ORDER BY rank
                            LIMIT ?;
                            """,
                            (q_fts, limit),
                        ).fetchall()
                        if rows:
                            return [dict(r) for r in rows]
                    except sqlite3.OperationalError:
                        pass

                like_q = f"%{query.strip().lower()}%"
                rows = conn.execute(
                    """
                    SELECT * FROM episodes
                    WHERE title LIKE ? OR content LIKE ? OR tags LIKE ?
                    ORDER BY event_timestamp DESC
                    LIMIT ?;
                    """,
                    (like_q, like_q, like_q, limit),
                ).fetchall()
                return [dict(r) for r in rows]

    def delete_episode(self, episode_id: int) -> bool:
        """Hapus satu episode berdasarkan ID."""
        with self._lock:
            with self._get_connection() as conn:
                cur = conn.execute("DELETE FROM episodes WHERE id = ?;", (episode_id,))
                try:
                    conn.execute(
                        "DELETE FROM fts_unified WHERE source_type = 'episode' AND source_id = ?;",
                        (episode_id,),
                    )
                except sqlite3.OperationalError:
                    pass
                conn.commit()
                return cur.rowcount > 0

    def clear_all_episodes(self) -> int:
        """Kosongkan seluruh riwayat episode."""
        with self._lock:
            with self._get_connection() as conn:
                cur = conn.execute("DELETE FROM episodes;")
                try:
                    conn.execute("DELETE FROM fts_unified WHERE source_type = 'episode';")
                except sqlite3.OperationalError:
                    pass
                conn.commit()
                return cur.rowcount

    # =========================================================================
    # PILAR 3: GRAF PENGETAHUAN & GRAPH RAG (KNOWLEDGE GRAPH)
    # =========================================================================

    def add_relation(
        self,
        source: str,
        relation: str,
        target: str,
        weight: float = 1.0,
        context: str = "",
    ) -> dict[str, Any]:
        """Tambahkan relasi subjek-predikat-objek (triple) ke dalam graf pengetahuan."""
        src = source.strip()
        rel = relation.strip().lower().replace(" ", "_")
        tgt = target.strip()
        ctx = context.strip()
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

        with self._lock:
            with self._get_connection() as conn:
                # Daftarkan entitas sumber & target jika belum ada
                conn.execute(
                    """
                    INSERT INTO graph_entities (name, entity_type, created_at, updated_at)
                    VALUES (?, 'concept', ?, ?)
                    ON CONFLICT(name) DO NOTHING;
                    """,
                    (src, now, now),
                )
                conn.execute(
                    """
                    INSERT INTO graph_entities (name, entity_type, created_at, updated_at)
                    VALUES (?, 'concept', ?, ?)
                    ON CONFLICT(name) DO NOTHING;
                    """,
                    (tgt, now, now),
                )

                # Simpan relasi triple
                conn.execute(
                    """
                    INSERT INTO graph_relations (source_entity, relation, target_entity, weight, context, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(source_entity, relation, target_entity) DO UPDATE SET
                        weight = excluded.weight,
                        context = excluded.context,
                        updated_at = excluded.updated_at;
                    """,
                    (src, rel, tgt, float(weight), ctx, now, now),
                )
                rel_row = conn.execute(
                    "SELECT id FROM graph_relations WHERE source_entity = ? AND relation = ? AND target_entity = ?;",
                    (src, rel, tgt),
                ).fetchone()
                rel_id = rel_row["id"] if rel_row else 0

                # Sinkronkan FTS5
                try:
                    conn.execute(
                        "DELETE FROM fts_unified WHERE source_type = 'relation' AND source_id = ?;",
                        (rel_id,),
                    )
                    conn.execute(
                        "INSERT INTO fts_unified (source_type, source_id, title, content, tags) VALUES ('relation', ?, ?, ?, ?);",
                        (rel_id, f"{src} -> {rel} -> {tgt}", ctx, "relation"),
                    )
                except sqlite3.OperationalError:
                    pass

                conn.commit()

                row = conn.execute("SELECT * FROM graph_relations WHERE id = ?;", (rel_id,)).fetchone()
                return dict(row) if row else {}

    def get_entity_relations(
        self,
        entity: str,
        depth: int = 1,
        max_results: int = 30,
    ) -> list[dict[str, Any]]:
        """Multi-Hop Graph Traversal: Ambil semua koneksi graf yang terhubung dengan entitas.

        Mendukung kedalaman multi-hop (depth=1 direct neighbors, depth=2 expanded 2-hop subgraph).
        """
        clean_ent = entity.strip()
        visited_ids: set[int] = set()
        results: list[dict[str, Any]] = []

        with self._lock:
            with self._get_connection() as conn:
                # Hop 1: Relasi langsung
                rows_hop1 = conn.execute(
                    """
                    SELECT id, source_entity, relation, target_entity, weight, context, updated_at
                    FROM graph_relations
                    WHERE source_entity LIKE ? OR target_entity LIKE ?
                    ORDER BY weight DESC, updated_at DESC
                    LIMIT ?;
                    """,
                    (f"%{clean_ent}%", f"%{clean_ent}%", max_results),
                ).fetchall()

                neighbors: set[str] = set()
                for r in rows_hop1:
                    row_dict = dict(r)
                    row_dict["hop"] = 1
                    visited_ids.add(row_dict["id"])
                    results.append(row_dict)
                    if row_dict["source_entity"].lower() != clean_ent.lower():
                        neighbors.add(row_dict["source_entity"])
                    if row_dict["target_entity"].lower() != clean_ent.lower():
                        neighbors.add(row_dict["target_entity"])

                # Hop 2 (jika depth >= 2): Ekspansi tetangga
                if depth >= 2 and neighbors and len(results) < max_results:
                    remaining = max_results - len(results)
                    placeholders = ",".join(["?"] * len(neighbors))
                    query_hop2 = f"""
                        SELECT id, source_entity, relation, target_entity, weight, context, updated_at
                        FROM graph_relations
                        WHERE (source_entity IN ({placeholders}) OR target_entity IN ({placeholders}))
                        ORDER BY weight DESC, updated_at DESC
                        LIMIT ?;
                    """
                    params = list(neighbors) + list(neighbors) + [remaining]
                    rows_hop2 = conn.execute(query_hop2, params).fetchall()

                    for r in rows_hop2:
                        if r["id"] not in visited_ids:
                            row_dict = dict(r)
                            row_dict["hop"] = 2
                            visited_ids.add(row_dict["id"])
                            results.append(row_dict)

        return results

    def search_graph(self, query: str, limit: int = 15) -> list[dict[str, Any]]:
        """Cari relasi di dalam graf pengetahuan berdasarkan teks."""
        q_fts = _clean_fts_query(query)
        with self._lock:
            with self._get_connection() as conn:
                if q_fts:
                    try:
                        rows = conn.execute(
                            """
                            SELECT r.*
                            FROM fts_unified u
                            JOIN graph_relations r ON r.id = u.source_id
                            WHERE u.source_type = 'relation' AND fts_unified MATCH ?
                            ORDER BY rank
                            LIMIT ?;
                            """,
                            (q_fts, limit),
                        ).fetchall()
                        if rows:
                            return [dict(r) for r in rows]
                    except sqlite3.OperationalError:
                        pass

                like_q = f"%{query.strip().lower()}%"
                rows = conn.execute(
                    """
                    SELECT * FROM graph_relations
                    WHERE source_entity LIKE ? OR relation LIKE ? OR target_entity LIKE ? OR context LIKE ?
                    ORDER BY weight DESC, updated_at DESC
                    LIMIT ?;
                    """,
                    (like_q, like_q, like_q, like_q, limit),
                ).fetchall()
                return [dict(r) for r in rows]

    def delete_relation(self, source: str, relation: str, target: str) -> bool:
        """Hapus relasi spesifik dari graf pengetahuan."""
        src = source.strip()
        rel = relation.strip().lower().replace(" ", "_")
        tgt = target.strip()
        with self._lock:
            with self._get_connection() as conn:
                rel_row = conn.execute(
                    "SELECT id FROM graph_relations WHERE source_entity = ? AND relation = ? AND target_entity = ?;",
                    (src, rel, tgt),
                ).fetchone()
                if not rel_row:
                    return False
                rel_id = rel_row["id"]
                conn.execute("DELETE FROM graph_relations WHERE id = ?;", (rel_id,))
                try:
                    conn.execute(
                        "DELETE FROM fts_unified WHERE source_type = 'relation' AND source_id = ?;",
                        (rel_id,),
                    )
                except sqlite3.OperationalError:
                    pass
                conn.commit()
                return True

    def list_all_relations(self, limit: int = 50) -> list[dict[str, Any]]:
        """Daftar semua relasi dalam graf pengetahuan."""
        with self._lock:
            with self._get_connection() as conn:
                rows = conn.execute(
                    "SELECT * FROM graph_relations ORDER BY weight DESC, updated_at DESC LIMIT ?;",
                    (limit,),
                ).fetchall()
                return [dict(r) for r in rows]

    def clear_graph(self) -> int:
        """Kosongkan seluruh graf pengetahuan."""
        with self._lock:
            with self._get_connection() as conn:
                cur = conn.execute("DELETE FROM graph_relations;")
                conn.execute("DELETE FROM graph_entities;")
                try:
                    conn.execute("DELETE FROM fts_unified WHERE source_type = 'relation';")
                except sqlite3.OperationalError:
                    pass
                conn.commit()
                return cur.rowcount

    # =========================================================================
    # PILAR 4: HYBRID SEARCH & GRAPH RAG RETRIEVAL
    # =========================================================================

    def hybrid_search(
        self,
        query: str,
        limit: int = 10,
        include_facts: bool = True,
        include_episodes: bool = True,
        include_graph: bool = True,
    ) -> dict[str, Any]:
        """Pencarian Semantik Terpadu (Hybrid RAG) lintas Fakta, Episodik, dan Graf.

        Menggabungkan lexical BM25 ranking dengan automatic multi-hop graph expansion.
        """
        matched_facts: list[dict[str, Any]] = []
        matched_episodes: list[dict[str, Any]] = []
        matched_relations: list[dict[str, Any]] = []

        q_fts = _clean_fts_query(query)
        with self._lock:
            with self._get_connection() as conn:
                # 1. Unified FTS Search
                if q_fts:
                    try:
                        rows = conn.execute(
                            """
                            SELECT source_type, source_id, rank
                            FROM fts_unified
                            WHERE fts_unified MATCH ?
                            ORDER BY rank
                            LIMIT ?;
                            """,
                            (q_fts, limit * 2),
                        ).fetchall()

                        fact_ids = [r["source_id"] for r in rows if r["source_type"] == "fact"]
                        episode_ids = [r["source_id"] for r in rows if r["source_type"] == "episode"]
                        relation_ids = [r["source_id"] for r in rows if r["source_type"] == "relation"]

                        if include_facts and fact_ids:
                            placeholders = ",".join(["?"] * len(fact_ids))
                            f_rows = conn.execute(
                                f"SELECT * FROM facts WHERE id IN ({placeholders});", fact_ids
                            ).fetchall()
                            matched_facts.extend([dict(r) for r in f_rows])

                        if include_episodes and episode_ids:
                            placeholders = ",".join(["?"] * len(episode_ids))
                            e_rows = conn.execute(
                                f"SELECT * FROM episodes WHERE id IN ({placeholders});", episode_ids
                            ).fetchall()
                            matched_episodes.extend([dict(r) for r in e_rows])

                        if include_graph and relation_ids:
                            placeholders = ",".join(["?"] * len(relation_ids))
                            r_rows = conn.execute(
                                f"SELECT * FROM graph_relations WHERE id IN ({placeholders});", relation_ids
                            ).fetchall()
                            matched_relations.extend([dict(r) for r in r_rows])
                    except sqlite3.OperationalError:
                        pass

        # 2. Fallback / Augmentasi jika FTS kosong
        if include_facts and not matched_facts:
            matched_facts = self.search_facts(query, limit=limit)
        if include_episodes and not matched_episodes:
            matched_episodes = self.search_episodes(query, limit=limit)
        if include_graph and not matched_relations:
            matched_relations = self.search_graph(query, limit=limit)

        # 3. Graph Expansion: Jika query menyebut entitas tertentu, perluas relasi graf
        if include_graph:
            expanded = self.get_entity_relations(query, depth=1, max_results=5)
            existing_rel_ids = {r["id"] for r in matched_relations if "id" in r}
            for ex in expanded:
                if ex["id"] not in existing_rel_ids:
                    matched_relations.append(ex)

        return {
            "query": query,
            "facts": matched_facts[:limit],
            "episodes": matched_episodes[:limit],
            "relations": matched_relations[:limit],
            "total_matches": len(matched_facts) + len(matched_episodes) + len(matched_relations),
        }

    # =========================================================================
    # PILAR 5: REFLEKSI & KONSOLIDASI MEMORI (DREAM / SLEEP CYCLE)
    # =========================================================================

    def consolidate_memories(self) -> dict[str, Any]:
        """Proses Refleksi Kognitif & Konsolidasi Memori.

        Menjalankan sintesis analitik pada rekaman memori:
        - Mendeteksi entitas terpopuler dan pola interaksi pengguna.
        - Memetakan kluster hubungan antarentitas.
        - Menyusun ringkasan status kesehatan memori jangka panjang.
        """
        all_facts = self.list_all_facts()
        all_episodes = self.list_episodes(limit=50)
        all_relations = self.list_all_relations(limit=100)

        # Hitung frekuensi kemunculan entitas dalam graf
        entity_freq: dict[str, int] = {}
        for r in all_relations:
            src = r["source_entity"]
            tgt = r["target_entity"]
            entity_freq[src] = entity_freq.get(src, 0) + 1
            entity_freq[tgt] = entity_freq.get(tgt, 0) + 1

        top_entities = sorted(entity_freq.items(), key=lambda x: x[1], reverse=True)[:5]

        # Ringkasan insight
        insights: list[str] = []
        if top_entities:
            ent_summary = ", ".join(f"{name} ({count} relasi)" for name, count in top_entities)
            insights.append(f"Entitas sentral utama pengguna: {ent_summary}")

        if all_episodes:
            insights.append(
                f"Terdapat {len(all_episodes)} riwayat episode tercatat; episode terakhir: '{all_episodes[0]['title']}'"
            )

        categories_count: dict[str, int] = {}
        for f in all_facts:
            cat = f["category"]
            categories_count[cat] = categories_count.get(cat, 0) + 1

        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

        return {
            "timestamp": now,
            "total_facts": len(all_facts),
            "total_episodes": len(all_episodes),
            "total_relations": len(all_relations),
            "top_entities": [e[0] for e in top_entities],
            "category_distribution": categories_count,
            "insights": insights,
        }

    # =========================================================================
    # SYSTEM PROMPT INJECTION FORMATTER
    # =========================================================================

    def format_for_system_prompt(
        self,
        max_facts: int = 30,
        max_relations: int = 8,
        max_episodes: int = 3,
    ) -> str:
        """Format memori kognitif lengkap (Fakta, Graf, Episodik) untuk diinjeksikan ke System Prompt."""
        facts = self.list_all_facts()
        episodes = self.list_episodes(limit=max_episodes, min_importance=2)
        relations = self.list_all_relations(limit=max_relations)

        if not facts and not episodes and not relations:
            return ""

        sections: list[str] = []

        # 1. Fakta Terverifikasi
        if facts:
            facts_subset = facts[:max_facts]
            lines = [
                "[MEMORI PERMANEN & FAKTA PENGGUNA TERVERIFIKASI]",
                "Fakta, profil, dan preferensi pengguna yang tersimpan di memori jangka panjang lokal:",
            ]
            for f in facts_subset:
                lines.append(f"• [{f['category']}] {f['key']}: {f['content']}")
            sections.append("\n".join(lines))

        # 2. Graf Pengetahuan & Relasi Entitas
        if relations:
            rel_lines = [
                "[GRAF PENGETAHUAN & RELASI ENTITAS]",
                "Hubungan terhubung antar entitas pengguna dan sistem:",
            ]
            for r in relations:
                ctx_note = f" ({r['context']})" if r.get("context") else ""
                rel_lines.append(f"• {r['source_entity']} -> [{r['relation']}] -> {r['target_entity']}{ctx_note}")
            sections.append("\n".join(rel_lines))

        # 3. Episode & Pengalaman Terkini
        if episodes:
            ep_lines = [
                "[REKAMAN EPISODE & PENGALAMAN TERBARU]",
                "Peristiwa dan interaksi signifikan yang baru saja terjadi:",
            ]
            for ep in episodes:
                ts_short = ep.get("event_timestamp", "")[:10]
                ep_lines.append(f"• [{ts_short}] {ep['title']}: {ep['content']}")
            sections.append("\n".join(ep_lines))

        sections.append(
            "(Gunakan fakta dan memori di atas secara alami dalam menjawab tanpa perlu bertanya ulang.)"
        )
        return "\n\n".join(sections)


# Global singleton instance
memory_store = MemoryStore()

