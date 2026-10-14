from __future__ import annotations

"""Shared path validation helpers for tool implementations (skills, cron, credential files)."""

import logging
import os
import pathlib
import re
from typing import Any

from src.config import get_settings

logger = logging.getLogger("faf_agent.tools.path_security")

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class PathSecurityError(ValueError):
    """Base exception for all path security validation violations."""


class PathTraversalError(PathSecurityError):
    """Raised when a path attempts directory traversal outside the allowed base sandbox."""


class CredentialAccessError(PathSecurityError):
    """Raised when a path attempts to access sensitive credentials or secret files."""


class SystemProtectedPathError(PathSecurityError):
    """Raised when a path targets critical system partitions or protected Android paths."""


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_PROTECTED_SYSTEM_PATHS: set[str] = {
    "/",
    "/root",
    "/system",
    "/vendor",
    "/data",
    "/data/data",
    "/sdcard",
    "/storage",
    "/storage/emulated",
    "/storage/emulated/0",
    "/proc",
    "/sys",
    "/dev",
    "/data/data/com.termux/files",
    "/data/data/com.termux/files/usr",
}

DEFAULT_CREDENTIAL_PATTERNS: tuple[str, ...] = (
    r"\.env(\.|$)",
    r"id_rsa(\.|$)",
    r"id_ecdsa(\.|$)",
    r"id_ed25519(\.|$)",
    r"id_dsa(\.|$)",
    r"\.ssh($|/)",
    r"\.gnupg($|/)",
    r"authorized_keys\b",
    r"known_hosts\b",
    r"keystore(\.|$)",
    r"\.jks\b",
    r"telegram_bot_token",
    r"openai_api_key",
    r"credentials\.json\b",
    r"client_secret.*\.json\b",
    r"oauth.*\.json\b",
    r"/etc/shadow\b",
    r"/etc/gshadow\b",
    r"/etc/sudoers\b",
)


# ---------------------------------------------------------------------------
# Core Helpers
# ---------------------------------------------------------------------------


def normalize_path(path: str | pathlib.Path | os.PathLike) -> pathlib.Path:
    """Normalize and resolve a filesystem path safely.

    Expands '~' user directories, strips quotes/whitespace, detects null
    bytes, and resolves relative '.' and '..' components into an absolute Path.
    """
    raw = str(path).strip()
    # Strip enclosing quotes if present
    if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
        raw = raw[1:-1].strip()

    if "\x00" in raw:
        raise PathSecurityError(f"Null byte detected in path: {raw!r}")

    expanded = os.path.expanduser(raw)
    p = pathlib.Path(expanded)
    try:
        return p.resolve()
    except Exception as e:
        logger.debug(f"Path resolve error for {raw}: {e}")
        return pathlib.Path(os.path.abspath(expanded))


def is_safe_subpath(
    target_path: str | pathlib.Path | os.PathLike,
    base_dir: str | pathlib.Path | os.PathLike,
) -> bool:
    """Check if target_path is strictly contained within base_dir.

    Resolves all symlinks and '..' traversal attempts before comparison.
    """
    try:
        target = normalize_path(target_path)
        base = normalize_path(base_dir)
        target.relative_to(base)
        return True
    except (ValueError, PathSecurityError):
        return False


def ensure_safe_subpath(
    target_path: str | pathlib.Path | os.PathLike,
    base_dir: str | pathlib.Path | os.PathLike,
    error_msg: str | None = None,
) -> pathlib.Path:
    """Verify target_path is inside base_dir and return resolved Path.

    Raises PathTraversalError if the path attempts to escape base_dir.
    """
    target = normalize_path(target_path)
    base = normalize_path(base_dir)

    if not is_safe_subpath(target, base):
        msg = error_msg or f"Path '{target}' berada di luar direktori aman yang diizinkan '{base}' (Path Traversal terdeteksi)."
        raise PathTraversalError(msg)

    return target


def is_credential_path(
    path: str | pathlib.Path | os.PathLike,
    extra_patterns: list[str] | tuple[str, ...] | None = None,
) -> bool:
    """Check whether the given path targets sensitive credentials, tokens, or private keys."""
    raw = str(path).replace("\\", "/")
    basename = os.path.basename(raw.rstrip("/"))

    # Check exact basename matches (.env, id_rsa, etc.)
    if basename == ".env" or basename.startswith(".env."):
        return True

    patterns = list(DEFAULT_CREDENTIAL_PATTERNS)
    if extra_patterns:
        patterns.extend(extra_patterns)

    for pat in patterns:
        if re.search(pat, raw, re.IGNORECASE):
            return True
        if re.search(pat, basename, re.IGNORECASE):
            return True

    return False


def is_protected_system_path(path: str | pathlib.Path | os.PathLike) -> bool:
    """Check if the given path is a protected Android/Linux root mount point or system partition.

    Prevents operations targeting root partitions (e.g. '/', '/system',
    '/data', '/sdcard').
    """
    try:
        norm = str(normalize_path(path)).rstrip("/")
        if not norm:
            norm = "/"
    except Exception:
        norm = str(path).rstrip("/")

    # Check exact match against protected system roots
    for prot in DEFAULT_PROTECTED_SYSTEM_PATHS:
        p_clean = prot.rstrip("/") or "/"
        if norm == p_clean:
            return True

    return False


# ---------------------------------------------------------------------------
# High-Level Validators
# ---------------------------------------------------------------------------


def validate_path(
    path: str | pathlib.Path | os.PathLike,
    base_dir: str | pathlib.Path | os.PathLike | None = None,
    allow_create: bool = False,
    check_credentials: bool = True,
    check_protected: bool = False,
) -> tuple[bool, str, pathlib.Path | None]:
    """Universal path validator for tool implementations.

    Returns:
        (is_valid: bool, status_message: str, resolved_path: Path | None)
    """
    if not path or not str(path).strip():
        return False, "Path tidak boleh kosong.", None

    try:
        resolved = normalize_path(path)
    except PathSecurityError as e:
        return False, f"Path tidak aman: {str(e)}", None
    except Exception as e:
        return False, f"Gagal memproses path: {str(e)}", None

    # 1. Base directory confinement (sandbox) check
    if base_dir:
        try:
            base_resolved = normalize_path(base_dir)
            if not is_safe_subpath(resolved, base_resolved):
                return (
                    False,
                    f"Akses ditolak: Path '{resolved}' berada di luar batas direktori yang diizinkan '{base_resolved}' (Path Traversal).",
                    None,
                )
        except Exception as e:
            return False, f"Validasi batas direktori gagal: {str(e)}", None

    # 2. Credential access check
    if check_credentials and is_credential_path(resolved):
        return (
            False,
            f"Akses ditolak: Berkas '{resolved.name}' tergolong kredensial rahasia (kunci privat / token).",
            None,
        )

    # 3. System protected partition check
    if check_protected and is_protected_system_path(resolved):
        return (
            False,
            f"Akses ditolak: Path '{resolved}' adalah partisi sistem kritis yang dilindungi.",
            None,
        )

    return True, "Path valid dan aman.", resolved


def validate_skill_path(
    skill_path: str | pathlib.Path | os.PathLike,
    skills_root: str | pathlib.Path | os.PathLike | None = None,
) -> tuple[bool, str, pathlib.Path | None]:
    """Validate skill file paths (scripts, SKILL.md, templates).

    Ensures skill resources remain strictly within the skills root and
    do not access credential files.
    """
    if skills_root is None:
        # Default project skills directory
        skills_root = pathlib.Path(__file__).parent.parent.parent / "skills"

    ok, msg, resolved = validate_path(
        path=skill_path,
        base_dir=skills_root,
        check_credentials=True,
        check_protected=True,
    )
    if not ok:
        return False, f"Skill Path Invalid: {msg}", None

    return True, "Skill path aman.", resolved


DEFAULT_DATA_DIR: str = os.path.expanduser("~/.faf_agent/data")
DEFAULT_DOCUMENTS_DIR: str = os.path.expanduser("~/.faf_agent/documents")


def get_default_data_dir() -> pathlib.Path:
    """Return absolute path for persistent state storage (~/.faf_agent/data)."""
    data_dir = pathlib.Path(DEFAULT_DATA_DIR)
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_default_documents_dir() -> pathlib.Path:
    """Return absolute path for persistent user documents (~/.faf_agent/documents)."""
    docs_dir = pathlib.Path(DEFAULT_DOCUMENTS_DIR)
    docs_dir.mkdir(parents=True, exist_ok=True)
    return docs_dir


def get_default_state_path(filename: str) -> str:
    """Return absolute path for a persistent state file in DEFAULT_DATA_DIR."""
    return str(get_default_data_dir() / filename)


def validate_document_path(
    doc_path: str | pathlib.Path | os.PathLike,
    default_storage_dir: str | pathlib.Path | os.PathLike | None = None,
) -> tuple[bool, str, pathlib.Path | None]:
    """Validate document file paths (PDF, docs).

    Ensures document paths do not access system files or sensitive credentials.
    If default_storage_dir is provided, confines doc_path within that directory.
    """
    ok, msg, resolved = validate_path(
        path=doc_path,
        base_dir=default_storage_dir,
        check_credentials=True,
        check_protected=True,
    )
    if not ok:
        return False, f"Document Path Invalid: {msg}", None

    return True, "Document path aman.", resolved


def validate_cron_state_path(
    state_path: str | pathlib.Path | os.PathLike,
    default_storage_dir: str | pathlib.Path | os.PathLike | None = None,
) -> tuple[bool, str, pathlib.Path | None]:
    """Validate cron and reminder state persistence file paths.

    Ensures state paths do not overwrite system files, credentials,
    or escape intended storage locations. If default_storage_dir is provided,
    strictly confines state_path within that directory.
    """
    ok, msg, resolved = validate_path(
        path=state_path,
        base_dir=default_storage_dir,
        check_credentials=True,
        check_protected=True,
    )
    if not ok:
        return False, f"Cron State Path Invalid: {msg}", None

    return True, "Cron state path aman.", resolved


def validate_credential_access(
    path: str | pathlib.Path | os.PathLike,
) -> tuple[bool, str]:
    """Check if direct access to a file is prohibited due to credential protection."""
    if is_credential_path(path):
        return (
            False,
            "Akses ditolak: Operasi dilarang membaca atau memanipulasi berkas kredensial sensitif.",
        )
    return True, "Berkas aman untuk diakses."
