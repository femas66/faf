from __future__ import annotations

import ipaddress
import logging
import os
import pathlib
import re
from typing import Any

from src.custom_skills.manifest import SkillPermissions

logger = logging.getLogger("faf_agent.custom_skills.permissions")

# Power & Process safety guardrails (Hard invariants)
FORBIDDEN_COMMANDS = {
    "reboot",
    "shutdown",
    "poweroff",
    "halt",
    "init",
    "sysrq-trigger",
    "svc power shutdown",
    "svc power reboot",
    "battery set level 0",
    "su",
    "tsu",
    "sudo",
}

BLOCKED_CORE_PATHS = {
    "src",
    "tests",
    "skills",
    ".git",
    "main.py",
    "pyproject.toml",
    "requirements.txt",
    "faf_memory.db",
    "faf_agent.lock",
}

PRIVATE_IP_RANGES = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


class SkillPermissionValidator:
    """Validates requested skill permissions against safety rules & physical invariants."""

    @classmethod
    def validate(cls, permissions: SkillPermissions, created_by: str = "agent") -> list[str]:
        """Validate permissions and return list of security violations (empty if valid)."""
        violations: list[str] = []

        # 1. Shell validation
        if permissions.shell and created_by == "agent":
            violations.append(
                "Skill buatan agen dilarang keras meminta izin shell umum (shell=true). "
                "Gunakan array termux_api untuk kontrol perangkat spesifik."
            )

        # 2. Termux:API validation
        for cmd in permissions.termux_api:
            cmd_clean = cmd.strip()
            if not cmd_clean.startswith("termux-"):
                violations.append(
                    f"Perintah termux_api '{cmd}' tidak valid. Hanya binary 'termux-*' yang diizinkan."
                )
            for forbidden in FORBIDDEN_COMMANDS:
                if forbidden in cmd_clean.lower():
                    violations.append(
                        f"Perintah termux_api '{cmd}' melanggar aturan keamanan perangkat ({forbidden})."
                    )

        # 3. File System Read/Write validation
        for p in permissions.fs_read:
            cls._check_fs_path(p, violations, access_type="read")

        for p in permissions.fs_write:
            cls._check_fs_path(p, violations, access_type="write")

        # 4. Network domain validation
        for domain in permissions.network:
            cls._check_network_domain(domain, violations)

        return violations

    @classmethod
    def _check_fs_path(cls, path_str: str, violations: list[str], access_type: str) -> None:
        from src.tools.path_security import is_credential_path, normalize_path

        raw = str(path_str).strip()
        if not raw:
            violations.append(f"Path fs_{access_type} tidak boleh kosong.")
            return

        # Check credentials pattern
        if is_credential_path(raw):
            violations.append(
                f"Path fs_{access_type} '{raw}' dilarang karena merujuk pada file kredensial/rahasia."
            )
            return

        # Check core agent files/folders
        try:
            norm = normalize_path(raw)
            norm_str = str(norm)
            parts = norm.parts
            for blocked in BLOCKED_CORE_PATHS:
                if blocked in parts or norm.name == blocked:
                    violations.append(
                        f"Path fs_{access_type} '{raw}' dilarang karena menargetkan file/direktori inti agent ({blocked})."
                    )
                    return
        except Exception as e:
            violations.append(f"Format path fs_{access_type} '{raw}' tidak valid: {e}")

    @classmethod
    def _check_network_domain(cls, domain_str: str, violations: list[str]) -> None:
        domain = domain_str.strip().lower()
        if not domain:
            violations.append("Nama domain network tidak boleh kosong.")
            return

        # Check IP address attempts
        try:
            ip = ipaddress.ip_address(domain)
            for priv in PRIVATE_IP_RANGES:
                if ip in priv:
                    violations.append(
                        f"Domain network '{domain}' adalah alamat IP privat/loopback/metadata (SSRF terlarang)."
                    )
                    return
        except ValueError:
            pass

        # Check wildcard and protocols
        if domain.startswith("http://") or domain.startswith("https://"):
            violations.append(f"Domain network '{domain}' harus berupa nama domain murni tanpa protokol http/https.")
            return

        if "*" in domain:
            violations.append(f"Domain network '{domain}' tidak boleh menggunakan wildcard (*).")
            return

        if domain in ("localhost", "127.0.0.1", "0.0.0.0"):
            violations.append(f"Domain network '{domain}' dilarang (loopback lokal).")
            return

        # Simple domain name regex
        if not re.match(r"^[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", domain):
            violations.append(f"Domain network '{domain}' formatnya tidak valid.")
