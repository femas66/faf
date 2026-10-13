from __future__ import annotations

import os
import pathlib
import pytest

from src.tools.path_security import (
    PathSecurityError,
    PathTraversalError,
    CredentialAccessError,
    SystemProtectedPathError,
    normalize_path,
    is_safe_subpath,
    ensure_safe_subpath,
    is_credential_path,
    is_protected_system_path,
    validate_path,
    validate_skill_path,
    validate_cron_state_path,
    validate_credential_access,
)


def test_normalize_path_basic(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    target = sub / "file.txt"
    target.write_text("hello")

    norm = normalize_path(str(target))
    assert isinstance(norm, pathlib.Path)
    assert norm == target.resolve()


def test_normalize_path_null_byte_rejection():
    with pytest.raises(PathSecurityError, match="Null byte"):
        normalize_path("/tmp/test\x00.txt")


def test_is_safe_subpath(tmp_path):
    base = tmp_path / "sandbox"
    base.mkdir()
    safe_file = base / "data" / "file.txt"
    safe_file.parent.mkdir()
    safe_file.write_text("ok")

    assert is_safe_subpath(safe_file, base) is True

    # Traversal attempt
    escape_file = base / ".." / "outside.txt"
    assert is_safe_subpath(escape_file, base) is False


def test_ensure_safe_subpath_success_and_failure(tmp_path):
    base = tmp_path / "sandbox"
    base.mkdir()
    child = base / "allowed.txt"

    res = ensure_safe_subpath(child, base)
    assert res == child.resolve()

    # Traversal raises PathTraversalError
    with pytest.raises(PathTraversalError):
        ensure_safe_subpath(base / "../../etc/passwd", base)


def test_is_credential_path():
    sensitive_paths = [
        ".env",
        "/data/data/com.termux/files/home/.env",
        "/home/user/.env.production",
        "/home/user/.ssh/id_rsa",
        "~/.ssh/id_ed25519",
        "~/.ssh/id_ecdsa",
        "~/.ssh/authorized_keys",
        "/etc/shadow",
        "keystore.jks",
        "app_keystore",
        "google_credentials.json",
        "/tmp/telegram_bot_token.txt",
        "/tmp/openai_api_key.key",
    ]

    for p in sensitive_paths:
        assert is_credential_path(p) is True, f"Failed for {p}"

    safe_paths = [
        "app.py",
        "/sdcard/Notes/catatan.txt",
        "/data/data/com.termux/files/home/script.sh",
        "README.md",
        "env_info.txt",
    ]

    for p in safe_paths:
        assert is_credential_path(p) is False, f"False positive for {p}"


def test_is_protected_system_path():
    protected = [
        "/",
        "/root",
        "/system",
        "/vendor",
        "/data",
        "/data/data",
        "/sdcard",
        "/storage",
        "/storage/emulated/0",
        "/proc",
        "/sys",
        "/dev",
    ]

    for p in protected:
        assert is_protected_system_path(p) is True, f"Failed for {p}"

    unprotected = [
        "/sdcard/Download/lagu.mp3",
        "/sdcard/Notes/todo.txt",
        "/data/data/com.termux/files/home/workspace",
    ]

    for p in unprotected:
        assert is_protected_system_path(p) is False, f"False positive for {p}"


def test_validate_path_all_in_one(tmp_path):
    base = tmp_path / "workspace"
    base.mkdir()
    safe_target = base / "doc.txt"
    safe_target.write_text("content")

    # Safe path
    ok, msg, p = validate_path(safe_target, base_dir=base)
    assert ok is True
    assert p == safe_target.resolve()

    # Credential path rejection
    cred_target = base / ".env"
    ok, msg, p = validate_path(cred_target, base_dir=base, check_credentials=True)
    assert ok is False
    assert "kredensial" in msg.lower()

    # Traversal path rejection
    traversal_target = base / ".." / "outside.txt"
    ok, msg, p = validate_path(traversal_target, base_dir=base)
    assert ok is False
    assert "traversal" in msg.lower() or "berada di luar" in msg.lower()


def test_validate_skill_path(tmp_path):
    skills_root = tmp_path / "skills"
    skills_root.mkdir()
    skill_dir = skills_root / "pdf_editor"
    skill_dir.mkdir()
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text("# PDF Editor")

    # Valid skill
    ok, msg, p = validate_skill_path(skill_md, skills_root=skills_root)
    assert ok is True
    assert p == skill_md.resolve()

    # Traversal skill
    bad_skill = skills_root / ".." / "etc" / "script.sh"
    ok, msg, p = validate_skill_path(bad_skill, skills_root=skills_root)
    assert ok is False
    assert "skill" in msg.lower() or "traversal" in msg.lower()


def test_validate_cron_state_path(tmp_path):
    cron_root = tmp_path / "cron_states"
    cron_root.mkdir()

    # Valid cron state path
    state_file = cron_root / "wifi_watchdog.state"
    ok, msg, p = validate_cron_state_path(state_file, default_storage_dir=cron_root)
    assert ok is True
    assert p == state_file.resolve()

    # Cron state targeting credentials
    bad_state = cron_root / ".env"
    ok, msg, p = validate_cron_state_path(bad_state, default_storage_dir=cron_root)
    assert ok is False
    assert "kredensial" in msg.lower()


def test_validate_credential_access():
    ok, msg = validate_credential_access("/sdcard/.env")
    assert ok is False
    assert "dilarang" in msg.lower() or "kredensial" in msg.lower()

    ok_safe, msg_safe = validate_credential_access("/sdcard/Notes/belanja.txt")
    assert ok_safe is True


def test_standardized_state_paths_and_store_validation(tmp_path):
    from src.tools.path_security import (
        DEFAULT_DATA_DIR,
        get_default_data_dir,
        get_default_state_path,
        validate_cron_state_path,
    )
    from src.tools.reminder_mgr import ReminderStore, DEFAULT_REMINDERS_PATH
    from src.tools.cronjob_mgr import CronJobStore, DEFAULT_CRONJOBS_PATH

    # 1. Standardized paths are absolute and point to ~/.faf_agent/data
    data_dir = get_default_data_dir()
    assert os.path.isabs(str(data_dir))
    assert str(data_dir) == os.path.expanduser(DEFAULT_DATA_DIR)
    assert os.path.exists(str(data_dir))

    rem_path = get_default_state_path("reminders.json")
    assert rem_path == DEFAULT_REMINDERS_PATH
    assert os.path.isabs(rem_path)
    assert rem_path.endswith(os.path.join(".faf_agent", "data", "reminders.json"))

    cron_path = get_default_state_path("cronjobs.json")
    assert cron_path == DEFAULT_CRONJOBS_PATH
    assert os.path.isabs(cron_path)
    assert cron_path.endswith(os.path.join(".faf_agent", "data", "cronjobs.json"))

    # 2. validate_cron_state_path accepts default paths
    ok, _, p = validate_cron_state_path(DEFAULT_REMINDERS_PATH)
    assert ok is True
    assert p == pathlib.Path(DEFAULT_REMINDERS_PATH).resolve()

    ok, _, p = validate_cron_state_path(DEFAULT_CRONJOBS_PATH)
    assert ok is True
    assert p == pathlib.Path(DEFAULT_CRONJOBS_PATH).resolve()

    # 3. ReminderStore defaults to DEFAULT_REMINDERS_PATH
    r_store = ReminderStore()
    assert r_store.file_path == str(pathlib.Path(DEFAULT_REMINDERS_PATH).resolve())

    # 4. CronJobStore defaults to DEFAULT_CRONJOBS_PATH
    c_store = CronJobStore()
    assert c_store.file_path == str(pathlib.Path(DEFAULT_CRONJOBS_PATH).resolve())

    # 5. Security violation: stores reject sensitive credentials and protected paths
    with pytest.raises(ValueError, match="kredensial|Invalid reminder store path"):
        ReminderStore(file_path="/sdcard/.env")

    with pytest.raises(ValueError, match="kredensial|Invalid cronjob store path"):
        CronJobStore(file_path="/sdcard/.env")

    with pytest.raises(ValueError, match="dilindungi|Invalid reminder store path"):
        ReminderStore(file_path="/system")

    with pytest.raises(ValueError, match="dilindungi|Invalid cronjob store path"):
        CronJobStore(file_path="/system")
