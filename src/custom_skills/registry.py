from __future__ import annotations

import json
import logging
import os
import pathlib
import re
import sqlite3
import threading
from typing import Any

from src.config import get_settings
from src.custom_skills.manifest import SkillManifest, SkillStatus, SkillValidationError
from src.custom_skills.permissions import SkillPermissionValidator

logger = logging.getLogger("faf_agent.custom_skills.registry")


INDONESIAN_STOPWORDS = {
    "dan", "di", "ke", "dari", "ini", "itu", "untuk", "pada", "adalah", "sebagai",
    "dengan", "yang", "oleh", "saat", "atau", "juga", "karena", "jika", "bisa",
    "ada", "apa", "apakah", "bagaimana", "mengapa", "kenapa", "siapa", "dimana",
    "tentang", "secara", "sudah", "sedang", "akan", "belum", "tidak", "bukan",
    "ya", "kah", "lah", "pun", "saya", "kamu", "dia", "mereka", "kita", "kami",
    "tolong", "buatkan", "tuliskan", "cerita", "pantun", "puisi", "dongeng"
}


def _sanitize_fts_query(query: str) -> str:
    """Sanitize query string into safe SQLite FTS5 prefix match syntax."""
    tokens = [
        t for t in re.findall(r"[\w]+", query)
        if len(t) >= 2 and t.lower() not in INDONESIAN_STOPWORDS
    ]
    if not tokens:
        return ""
    return " OR ".join(f'"{t}"*' for t in tokens)


class CustomSkillRegistry:
    """Registry managing storage, FTS5 indexing, and retrieval of custom skills."""

    def __init__(self, skills_dir: str | pathlib.Path | None = None) -> None:
        self.settings = get_settings()
        self.skills_dir = pathlib.Path(skills_dir or self.settings.custom_skills_dir).resolve()
        self._skills: dict[str, SkillManifest] = {}
        self._lock = threading.RLock()
        self._db_conn: sqlite3.Connection | None = None
        self._init_fts()

    def _init_fts(self) -> None:
        """Initialize in-memory SQLite FTS5 index for rapid keyword/BM25 matching."""
        with self._lock:
            if self._db_conn is None:
                self._db_conn = sqlite3.connect(":memory:", check_same_thread=False)
                self._db_conn.execute("PRAGMA foreign_keys = ON;")
                self._db_conn.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS custom_skills_fts USING fts5(
                        name,
                        description,
                        status,
                        tokenize = 'unicode61'
                    );
                    """
                )

    def load_skills(self) -> int:
        """Scan skills_dir for subdirectories containing manifest.json and load them."""
        with self._lock:
            self._skills.clear()
            if self._db_conn:
                self._db_conn.execute("DELETE FROM custom_skills_fts;")

            if not self.skills_dir.exists():
                try:
                    self.skills_dir.mkdir(parents=True, exist_ok=True)
                except Exception as e:
                    logger.warning(f"Could not create custom_skills directory: {e}")
                    return 0

            loaded_count = 0
            for child in self.skills_dir.iterdir():
                if not child.is_dir() or child.name.startswith("."):
                    continue

                manifest_file = child / "manifest.json"
                if not manifest_file.exists():
                    continue

                try:
                    with open(manifest_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    manifest = SkillManifest.from_dict(data)

                    # Validate permissions
                    violations = SkillPermissionValidator.validate(
                        manifest.permissions, created_by=manifest.created_by
                    )
                    if violations:
                        logger.warning(
                            f"Skill '{manifest.name}' memiliki pelanggaran izin: {violations}. "
                            f"Status dinonaktifkan."
                        )
                        manifest.status = SkillStatus.DEPRECATED.value

                    self._skills[manifest.name] = manifest

                    # Index in FTS5
                    if self._db_conn:
                        self._db_conn.execute(
                            "INSERT INTO custom_skills_fts (name, description, status) VALUES (?, ?, ?);",
                            (manifest.name, manifest.description, manifest.status),
                        )

                    if manifest.status == SkillStatus.ACTIVE.value:
                        loaded_count += 1
                except Exception as e:
                    logger.error(f"Error loading skill from {manifest_file}: {e}")

            if self._db_conn:
                self._db_conn.commit()

            logger.info(f"Loaded {loaded_count} active custom skills out of {len(self._skills)} total.")
            self.sync_to_tool_registry()
            return loaded_count

    def sync_to_tool_registry(self, tool_registry: Any = None) -> None:
        """Register active skills as BaseTool adapters into ToolRegistry."""
        try:
            from src.tools.custom_skill_adapter import CustomSkillToolAdapter
            from src.tools import default_registry

            target_reg = tool_registry or default_registry
            with self._lock:
                all_known_names = set(self._skills.keys())
                active_skills = self.get_active_skills()
                active_names = {s.name for s in active_skills}

                for name in all_known_names - active_names:
                    target_reg.unregister(name)

                for s in active_skills:
                    skill_dir = self.skills_dir / s.name
                    adapter = CustomSkillToolAdapter(manifest=s, skill_dir=skill_dir)
                    target_reg.register(adapter)
        except Exception as e:
            logger.warning(f"Could not sync custom skills to ToolRegistry: {e}")

    def get_skill(self, name: str) -> SkillManifest | None:
        """Get manifest by skill name."""
        with self._lock:
            return self._skills.get(name)

    def get_all(self) -> list[SkillManifest]:
        """Get all loaded manifests."""
        with self._lock:
            return list(self._skills.values())

    def get_active_skills(self) -> list[SkillManifest]:
        """Get only active manifests."""
        with self._lock:
            return [s for s in self._skills.values() if s.status == SkillStatus.ACTIVE.value]

    def get_top_k(self, query: str, k: int = 3) -> list[SkillManifest]:
        """Search and retrieve top-k active skills matching the user message.

        Uses FTS5 BM25 ranking combined with token overlap fallback for high accuracy.
        """
        with self._lock:
            if not self._skills and self.skills_dir.exists():
                self.load_skills()
            active_skills = [s for s in self._skills.values() if s.status == SkillStatus.ACTIVE.value]

        if not active_skills or not query.strip():
            return []

        matched_names: list[str] = []
        with self._lock:
            fts_q = _sanitize_fts_query(query)
            if self._db_conn and fts_q:
                try:
                    cursor = self._db_conn.execute(
                        """
                        SELECT name, rank
                        FROM custom_skills_fts
                        WHERE custom_skills_fts MATCH ? AND status = 'active'
                        ORDER BY rank
                        LIMIT ?;
                        """,
                        (fts_q, k),
                    )
                    matched_names = [row[0] for row in cursor.fetchall()]
                except Exception as e:
                    logger.debug(f"FTS5 query failed ({e}), using token overlap fallback.")

        # Fallback / Rank booster: simple word overlap
        if not matched_names:
            query_tokens = set(re.findall(r"[\w]+", query.lower())) - INDONESIAN_STOPWORDS
            if not query_tokens:
                return []
            scored: list[tuple[float, SkillManifest]] = []
            for s in active_skills:
                s_tokens = set(re.findall(r"[\w]+", f"{s.name} {s.description}".lower())) - INDONESIAN_STOPWORDS
                overlap = len(query_tokens & s_tokens)
                if overlap > 0:
                    scored.append((float(overlap), s))
            scored.sort(key=lambda x: x[0], reverse=True)
            return [s for _, s in scored[:k]]

        results: list[SkillManifest] = []
        for name in matched_names:
            skill = self.get_skill(name)
            if skill and skill.status == SkillStatus.ACTIVE.value:
                results.append(skill)
        return results[:k]

    def save_skill(
        self,
        manifest: SkillManifest,
        code: str,
        tests: list[dict[str, Any]],
        changelog: str = "",
    ) -> bool:
        """Save a new skill or update existing skill files to disk and refresh registry."""
        with self._lock:
            errors = manifest.validate()
            if errors:
                raise SkillValidationError("; ".join(errors))

            violations = SkillPermissionValidator.validate(
                manifest.permissions, created_by=manifest.created_by
            )
            if violations:
                raise SkillValidationError(f"Izin dilarang: {'; '.join(violations)}")

            skill_folder = self.skills_dir / manifest.name
            skill_folder.mkdir(parents=True, exist_ok=True)

            # Write manifest.json
            with open(skill_folder / "manifest.json", "w", encoding="utf-8") as f:
                json.dump(manifest.to_dict(), f, indent=2, ensure_ascii=False)

            # Write main.py
            with open(skill_folder / "main.py", "w", encoding="utf-8") as f:
                f.write(code)

            # Write tests.json
            with open(skill_folder / "tests.json", "w", encoding="utf-8") as f:
                json.dump(tests, f, indent=2, ensure_ascii=False)

            # Write CHANGELOG.md
            if changelog:
                with open(skill_folder / "CHANGELOG.md", "w", encoding="utf-8") as f:
                    f.write(changelog)

            self.load_skills()
            return True

    def update_status(self, name: str, new_status: SkillStatus | str) -> bool:
        """Update skill status on disk and memory."""
        with self._lock:
            status_val = new_status.value if isinstance(new_status, SkillStatus) else str(new_status).strip().lower()
            valid_statuses = {s.value for s in SkillStatus}
            if status_val not in valid_statuses:
                raise ValueError(f"Status '{status_val}' tidak valid.")

            skill = self.get_skill(name)
            if not skill:
                return False

            manifest_file = self.skills_dir / name / "manifest.json"
            if not manifest_file.exists():
                return False

            skill.status = status_val
            with open(manifest_file, "w", encoding="utf-8") as f:
                json.dump(skill.to_dict(), f, indent=2, ensure_ascii=False)

            self.load_skills()
            return True


# Default singleton instance
custom_skill_registry = CustomSkillRegistry()
