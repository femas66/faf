from __future__ import annotations

"""Shared path validation helpers re-exported from src.tools.path_security."""

from src.tools.path_security import (
    PathSecurityError,
    PathTraversalError,
    CredentialAccessError,
    SystemProtectedPathError,
    DEFAULT_PROTECTED_SYSTEM_PATHS,
    DEFAULT_CREDENTIAL_PATTERNS,
    normalize_path,
    is_safe_subpath,
    ensure_safe_subpath,
    is_credential_path,
    is_protected_system_path,
    validate_path,
    validate_skill_path,
    validate_cron_state_path,
    validate_credential_access,
    DEFAULT_DATA_DIR,
    get_default_data_dir,
    get_default_state_path,
)

__all__ = [
    "PathSecurityError",
    "PathTraversalError",
    "CredentialAccessError",
    "SystemProtectedPathError",
    "DEFAULT_PROTECTED_SYSTEM_PATHS",
    "DEFAULT_CREDENTIAL_PATTERNS",
    "normalize_path",
    "is_safe_subpath",
    "ensure_safe_subpath",
    "is_credential_path",
    "is_protected_system_path",
    "validate_path",
    "validate_skill_path",
    "validate_cron_state_path",
    "validate_credential_access",
    "DEFAULT_DATA_DIR",
    "get_default_data_dir",
    "get_default_state_path",
]
