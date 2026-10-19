from __future__ import annotations

import asyncio
import json
import os
import pathlib
import pytest

from src.custom_skills.ast_validator import ASTValidator
from src.custom_skills.audit import SkillAuditLogger
from src.custom_skills.manifest import SkillManifest, SkillPermissions
from src.custom_skills.runner import SkillRunner


@pytest.fixture
def temp_skill_dir(tmp_path: pathlib.Path) -> pathlib.Path:
    skill_dir = tmp_path / "rogue_skill"
    skill_dir.mkdir(parents=True, exist_ok=True)
    return skill_dir


def test_ast_rejects_eval_and_exec():
    code_eval = "def run(p):\n    return eval('2 + 2')"
    violations = ASTValidator.validate_code(code_eval)
    assert any("eval()" in v for v in violations)

    code_exec = "def run(p):\n    exec('import os')"
    violations_exec = ASTValidator.validate_code(code_exec)
    assert any("exec()" in v for v in violations_exec)

    code_compile = "def run(p):\n    return compile('1+1', '', 'eval')"
    violations_compile = ASTValidator.validate_code(code_compile)
    assert any("compile()" in v for v in violations_compile)


def test_ast_rejects_forbidden_modules_and_reflection():
    code_ctypes = "import ctypes\ndef run(p):\n    return {}"
    v = ASTValidator.validate_code(code_ctypes)
    assert any("ctypes" in x for x in v)

    code_reflection = "def run(p):\n    return ().__class__.__bases__[0].__subclasses__()"
    v_ref = ASTValidator.validate_code(code_reflection)
    assert any("__subclasses__" in x or "__bases__" in x for x in v_ref)


def test_ast_rejects_secret_file_access():
    code_secret = "def run(p):\n    path = '.env'\n    return {'path': path}"
    v = ASTValidator.validate_code(code_secret)
    assert any(".env" in x for x in v)

    code_secret2 = "def run(p):\n    f = 'faf_memory.db'\n    return {}"
    v2 = ASTValidator.validate_code(code_secret2)
    assert any("faf_memory.db" in x for x in v2)


def test_ast_rejects_network_without_permission():
    code_net = "import urllib.request\ndef run(p):\n    return urllib.request.urlopen('https://example.com').read()"
    # No network permissions declared
    perms = SkillPermissions(network=[])
    v = ASTValidator.validate_code(code_net, permissions=perms)
    assert any("jaringan" in x for x in v)

    code_socket = "import socket\ndef run(p):\n    s = socket.socket()\n    return {}"
    v_sock = ASTValidator.validate_code(code_socket, permissions=perms)
    assert any("socket" in x for x in v_sock)


def test_ast_rejects_unauthorized_termux_api():
    code_bad_cmd = """
import subprocess
def run(p):
    subprocess.run(["reboot"])
    return {}
"""
    perms = SkillPermissions(termux_api=["termux-battery-status"])
    v = ASTValidator.validate_code(code_bad_cmd, permissions=perms)
    assert any("reboot" in x for x in v)


@pytest.mark.asyncio
async def test_runner_blocks_ast_violation(temp_skill_dir: pathlib.Path):
    bad_code = "def run(p):\n    eval('1+1')\n"
    with open(temp_skill_dir / "main.py", "w") as f:
        f.write(bad_code)

    manifest = SkillManifest(name="bad_skill", description="Bad", status="active")
    runner = SkillRunner(manifest=manifest, skill_dir=temp_skill_dir)

    result = await runner.execute()
    assert result.success is False
    assert result.violation_type == "AST_SECURITY_VIOLATION"
    assert "eval()" in result.error


@pytest.mark.asyncio
async def test_runner_enforces_hard_timeout(temp_skill_dir: pathlib.Path):
    infinite_loop_code = """
import time
def run(p):
    while True:
        time.sleep(0.1)
    return {}

if __name__ == '__main__':
    run({})
"""
    with open(temp_skill_dir / "main.py", "w") as f:
        f.write(infinite_loop_code)

    manifest = SkillManifest(name="loop_skill", description="Loop", timeout_sec=2, status="active")
    runner = SkillRunner(manifest=manifest, skill_dir=temp_skill_dir)

    result = await runner.execute(timeout_override=2)
    assert result.success is False
    assert result.violation_type == "TIMEOUT"
    assert "batas waktu" in result.error


@pytest.mark.asyncio
async def test_runner_blocks_excessive_output_size(temp_skill_dir: pathlib.Path):
    bomb_code = """
import sys
def run(p):
    # Print 100KB of text
    sys.stdout.write("A" * (100 * 1024))
    sys.exit(0)

if __name__ == '__main__':
    run({})
"""
    with open(temp_skill_dir / "main.py", "w") as f:
        f.write(bomb_code)

    manifest = SkillManifest(name="bomb_skill", description="Bomb", status="active")
    runner = SkillRunner(manifest=manifest, skill_dir=temp_skill_dir)

    result = await runner.execute()
    assert result.success is False
    assert result.violation_type == "OUTPUT_SIZE_EXCEEDED"
    assert "64KB" in result.error


@pytest.mark.asyncio
async def test_runner_sanitized_environment(temp_skill_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret-key-12345")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:secret-bot-token")

    env_leak_test_code = """
import os, sys, json
def run(p):
    env_keys = list(os.environ.keys())
    has_openai = any("OPENAI" in k for k in env_keys)
    has_telegram = any("TELEGRAM" in k for k in env_keys)
    return {
        "success": True,
        "has_openai": has_openai,
        "has_telegram": has_telegram,
        "keys": env_keys
    }

if __name__ == '__main__':
    sys.stdout.write(json.dumps(run({})))
"""
    with open(temp_skill_dir / "main.py", "w") as f:
        f.write(env_leak_test_code)

    manifest = SkillManifest(
        name="env_leak_test",
        description="Env test",
        status="active",
        permissions=SkillPermissions(fs_read=["./.sandbox"])
    )
    runner = SkillRunner(manifest=manifest, skill_dir=temp_skill_dir)

    result = await runner.execute()
    assert result.success is True
    assert result.data is not None
    # Verify environment keys are completely absent from child process
    assert result.data.get("has_openai") is False
    assert result.data.get("has_telegram") is False
    assert "PATH" in result.data.get("keys", [])


def test_audit_logger_records_events(tmp_path: pathlib.Path):
    log_file = tmp_path / "test_audit.jsonl"
    audit = SkillAuditLogger(log_path=log_file)

    audit.log_event(
        action="security_blocked",
        skill_name="rogue_agent",
        version="1.0.0",
        user_id=999,
        status="failed",
        error="Blocked eval() call",
        details={"rule": "AST_RESTRICTION"}
    )

    assert log_file.exists()
    with open(log_file, "r", encoding="utf-8") as f:
        lines = f.readlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["action"] == "security_blocked"
    assert record["skill_name"] == "rogue_agent"
    assert record["error"] == "Blocked eval() call"
