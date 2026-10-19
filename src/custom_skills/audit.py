from __future__ import annotations

import datetime
import json
import logging
import pathlib
import threading
from typing import Any

from src.config import get_settings

logger = logging.getLogger("faf_agent.custom_skills.audit")


class SkillAuditLogger:
    """Thread-safe structured JSONL audit logger for custom skills lifecycle & execution."""

    def __init__(self, log_path: str | pathlib.Path | None = None) -> None:
        self.settings = get_settings()
        if log_path:
            self.log_path = pathlib.Path(log_path).resolve()
        else:
            base_dir = pathlib.Path(self.settings.custom_skills_dir).resolve()
            self.log_path = base_dir / "audit.jsonl"
        self._lock = threading.Lock()

    def log_event(
        self,
        action: str,
        skill_name: str,
        version: str = "1.0.0",
        user_id: int | None = None,
        status: str = "success",
        duration_ms: float | None = None,
        error: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Append an audit event record to audit.jsonl safely."""
        record = {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "action": action,
            "skill_name": skill_name,
            "version": version,
            "user_id": user_id,
            "status": status,
            "duration_ms": round(duration_ms, 2) if duration_ms is not None else None,
            "error": error,
            "details": details or {},
        }

        try:
            line = json.dumps(record, ensure_ascii=False) + "\n"
            with self._lock:
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.log_path, "a", encoding="utf-8") as f:
                    f.write(line)
        except Exception as e:
            logger.error(f"Failed to write skill audit log: {e}")


# Singleton default audit logger
skill_audit_logger = SkillAuditLogger()
