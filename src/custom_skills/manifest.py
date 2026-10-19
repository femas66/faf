from __future__ import annotations

import datetime
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SkillStatus(str, Enum):
    DRAFT = "draft"
    TESTED = "tested"
    PENDING_APPROVAL = "pending_approval"
    ACTIVE = "active"
    DEPRECATED = "deprecated"


class SkillValidationError(ValueError):
    """Raised when skill manifest or parameter schema fails validation."""
    pass


NAME_REGEX = re.compile(r"^[a-z][a-z0-9_]{2,39}$")
SEMVER_REGEX = re.compile(r"^\d+\.\d+\.\d+$")


@dataclass
class SkillPermissions:
    """Declarative permissions requested by a skill (default: all closed)."""

    termux_api: list[str] = field(default_factory=list)
    network: list[str] = field(default_factory=list)
    fs_read: list[str] = field(default_factory=list)
    fs_write: list[str] = field(default_factory=list)
    shell: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "termux_api": list(self.termux_api),
            "network": list(self.network),
            "fs_read": list(self.fs_read),
            "fs_write": list(self.fs_write),
            "shell": bool(self.shell),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> SkillPermissions:
        if not data or not isinstance(data, dict):
            return cls()
        return cls(
            termux_api=[str(x).strip() for x in data.get("termux_api", []) if str(x).strip()],
            network=[str(x).strip().lower() for x in data.get("network", []) if str(x).strip()],
            fs_read=[str(x).strip() for x in data.get("fs_read", []) if str(x).strip()],
            fs_write=[str(x).strip() for x in data.get("fs_write", []) if str(x).strip()],
            shell=bool(data.get("shell", False)),
        )

    def is_sensitive(self) -> bool:
        """Check if any high-risk/sensitive permission is requested."""
        if self.shell:
            return True
        sensitive_api = {"termux-sms-send", "termux-telephony-call", "termux-contact-list"}
        if any(cmd in sensitive_api for cmd in self.termux_api):
            return True
        if self.network:
            return True
        return False


@dataclass
class SkillManifest:
    """Schema model for manifest.json of a custom skill."""

    name: str
    version: str = "1.0.0"
    description: str = ""
    parameters: dict[str, Any] = field(
        default_factory=lambda: {"type": "object", "properties": {}, "required": []}
    )
    permissions: SkillPermissions = field(default_factory=SkillPermissions)
    timeout_sec: int = 10
    created_by: str = "agent"  # "agent" or "user"
    status: str = SkillStatus.DRAFT.value
    created_at: str = field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )
    updated_at: str = field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )

    def validate(self) -> list[str]:
        """Validate manifest attributes, returning a list of validation errors."""
        errors: list[str] = []

        # Name validation
        if not self.name or not NAME_REGEX.match(self.name):
            errors.append(
                f"Nama skill '{self.name}' tidak valid. Harus 3-40 karakter huruf kecil, "
                f"diawali huruf, dan hanya boleh mengandung huruf, angka, dan underscore."
            )

        # Version validation
        if not self.version or not SEMVER_REGEX.match(self.version):
            errors.append(f"Versi '{self.version}' tidak valid. Harus format semver (mis. '1.0.0').")

        # Description validation
        if not self.description or len(self.description.strip()) < 5:
            errors.append("Deskripsi skill wajib diisi minimal 5 karakter.")

        # Parameters JSON Schema validation
        if not isinstance(self.parameters, dict):
            errors.append("Parameters wajib berupa JSON Schema dictionary.")
        elif self.parameters.get("type") != "object":
            errors.append("Parameters schema wajib memiliki root type 'object'.")

        # Status validation
        valid_statuses = {s.value for s in SkillStatus}
        if self.status not in valid_statuses:
            errors.append(f"Status '{self.status}' tidak valid. Pilihan: {sorted(valid_statuses)}")

        # Timeout validation
        if not (1 <= self.timeout_sec <= 60):
            errors.append(f"timeout_sec ({self.timeout_sec}) di luar batas wajar (1-60 detik).")

        # Created by validation
        if self.created_by not in ("agent", "user"):
            errors.append(f"created_by '{self.created_by}' tidak valid. Harus 'agent' atau 'user'.")

        return errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "parameters": self.parameters,
            "permissions": self.permissions.to_dict(),
            "timeout_sec": self.timeout_sec,
            "created_by": self.created_by,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SkillManifest:
        if not isinstance(data, dict):
            raise SkillValidationError("Manifest data must be a dictionary.")

        name = str(data.get("name", "")).strip()
        version = str(data.get("version", "1.0.0")).strip()
        description = str(data.get("description", "")).strip()
        parameters = data.get("parameters") or {"type": "object", "properties": {}, "required": []}
        permissions = SkillPermissions.from_dict(data.get("permissions"))
        timeout_sec = int(data.get("timeout_sec", 10))
        created_by = str(data.get("created_by", "agent")).strip()
        status = str(data.get("status", SkillStatus.DRAFT.value)).strip().lower()
        created_at = str(data.get("created_at", ""))
        updated_at = str(data.get("updated_at", ""))

        manifest = cls(
            name=name,
            version=version,
            description=description,
            parameters=parameters,
            permissions=permissions,
            timeout_sec=timeout_sec,
            created_by=created_by,
            status=status,
            created_at=created_at or datetime.datetime.now(datetime.timezone.utc).isoformat(),
            updated_at=updated_at or datetime.datetime.now(datetime.timezone.utc).isoformat(),
        )

        errors = manifest.validate()
        if errors:
            raise SkillValidationError("; ".join(errors))

        return manifest

    def to_openai_tool(self) -> dict[str, Any]:
        """Convert manifest to OpenAI function calling tool schema."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": f"[Custom Skill] {self.description}",
                "parameters": self.parameters,
            },
        }
