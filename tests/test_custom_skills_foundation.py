from __future__ import annotations

import asyncio
import json
import pathlib
import pytest

from src.custom_skills.manifest import (
    SkillManifest,
    SkillPermissions,
    SkillStatus,
    SkillValidationError,
)
from src.custom_skills.permissions import SkillPermissionValidator
from src.custom_skills.registry import CustomSkillRegistry
from src.tools.base import ToolContext, ToolRegistry
from src.tools.custom_skill_adapter import CustomSkillToolAdapter
from src.core.tool_router import ToolRouter


def test_manifest_validation_valid():
    manifest = SkillManifest(
        name="cek_suhu",
        version="1.0.0",
        description="Membaca suhu CPU dan thermal perangkat",
        parameters={"type": "object", "properties": {}, "required": []},
        permissions=SkillPermissions(termux_api=["termux-battery-status"]),
        timeout_sec=10,
        created_by="user",
        status=SkillStatus.ACTIVE.value,
    )
    errors = manifest.validate()
    assert errors == []
    openai_tool = manifest.to_openai_tool()
    assert openai_tool["type"] == "function"
    assert openai_tool["function"]["name"] == "cek_suhu"


def test_manifest_validation_invalid_fields():
    # Invalid name (starts with digit or uppercase)
    m1 = SkillManifest(name="123_invalid", description="test", status="active")
    assert any("Nama skill" in err for err in m1.validate())

    m2 = SkillManifest(name="Invalid_Name", description="test", status="active")
    assert any("Nama skill" in err for err in m2.validate())

    # Invalid semver
    m3 = SkillManifest(name="valid_name", version="v1.0", description="test", status="active")
    assert any("Versi" in err for err in m3.validate())

    # Missing description
    m4 = SkillManifest(name="valid_name", description="   ", status="active")
    assert any("Deskripsi" in err for err in m4.validate())

    # Invalid status
    m5 = SkillManifest(name="valid_name", description="Valid description", status="unknown_status")
    assert any("Status" in err for err in m5.validate())


def test_permission_validator_rejection():
    # 1. Reject dangerous reboot / shutdown commands
    p_reboot = SkillPermissions(termux_api=["termux-battery-status", "reboot"])
    v = SkillPermissionValidator.validate(p_reboot)
    assert any("keamanan perangkat" in err for err in v)

    # 2. Reject non termux- commands in termux_api
    p_non_termux = SkillPermissions(termux_api=["ls", "cat /etc/passwd"])
    v = SkillPermissionValidator.validate(p_non_termux)
    assert any("Hanya binary 'termux-*'" in err for err in v)

    # 3. Reject credential files access in fs_read
    p_secret = SkillPermissions(fs_read=[".env", "/data/data/com.termux/files/home/.env"])
    v = SkillPermissionValidator.validate(p_secret)
    assert any("file kredensial/rahasia" in err for err in v)

    # 4. Reject core agent directory in fs_write
    p_core = SkillPermissions(fs_write=["src/core/agent.py"])
    v = SkillPermissionValidator.validate(p_core)
    assert any("file/direktori inti agent" in err for err in v)

    # 5. Reject SSRF / private IP / localhost in network
    p_ssrf1 = SkillPermissions(network=["127.0.0.1", "localhost"])
    v = SkillPermissionValidator.validate(p_ssrf1)
    assert any("SSRF" in err or "loopback" in err for err in v)

    p_ssrf2 = SkillPermissions(network=["192.168.1.1", "10.0.0.5", "169.254.169.254"])
    v = SkillPermissionValidator.validate(p_ssrf2)
    assert any("SSRF" in err for err in v)

    # 6. Reject shell: true for agent
    p_shell = SkillPermissions(shell=True)
    v = SkillPermissionValidator.validate(p_shell, created_by="agent")
    assert any("dilarang keras meminta izin shell" in err for err in v)


def test_permission_validator_accepts_safe():
    p_safe = SkillPermissions(
        termux_api=["termux-battery-status", "termux-torch"],
        network=["api.github.com"],
        fs_read=["/sdcard/Download"],
        fs_write=["./.sandbox"],
        shell=False,
    )
    v = SkillPermissionValidator.validate(p_safe, created_by="agent")
    assert v == []


def test_registry_loading_and_fts():
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    skills_dir = repo_root / "custom_skills"

    registry = CustomSkillRegistry(skills_dir=skills_dir)
    loaded_count = registry.load_skills()
    assert loaded_count >= 2

    # Check both sample skills are loaded
    skill_battery = registry.get_skill("baca_baterai")
    assert skill_battery is not None
    assert skill_battery.status == SkillStatus.ACTIVE.value

    skill_discount = registry.get_skill("hitung_diskon")
    assert skill_discount is not None
    assert skill_discount.status == SkillStatus.ACTIVE.value

    # Top-K matching: Battery query
    matches_batt = registry.get_top_k("baterai ponsel apakah sedang dicas", k=2)
    assert len(matches_batt) > 0
    assert any(s.name == "baca_baterai" for s in matches_batt)

    # Top-K matching: Discount query
    matches_disc = registry.get_top_k("hitung diskon belanja", k=2)
    assert len(matches_disc) > 0
    assert any(s.name == "hitung_diskon" for s in matches_disc)

    # Irrelevant query
    matches_none = registry.get_top_k("pantun jenaka tentang laut", k=2)
    assert len(matches_none) == 0


@pytest.mark.asyncio
async def test_custom_skill_adapter_execution():
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    skills_dir = repo_root / "custom_skills"
    ctx = ToolContext(chat_id=123, user_id=456)

    # 1. Test hitung_diskon execution
    discount_manifest = SkillManifest.from_dict({
        "name": "hitung_diskon",
        "description": "Menghitung diskon",
        "parameters": {
            "type": "object",
            "properties": {"harga": {"type": "number"}, "diskon_persen": {"type": "number"}},
            "required": ["harga", "diskon_persen"]
        },
        "status": "active"
    })
    adapter_discount = CustomSkillToolAdapter(discount_manifest, skills_dir / "hitung_diskon")
    res = await adapter_discount.execute(ctx, harga=100000, diskon_persen=25)
    assert res.success is True
    assert "75,000" in res.output or "75000" in res.output

    # Test edge case: invalid discount > 100%
    res_err = await adapter_discount.execute(ctx, harga=50000, diskon_persen=150)
    assert res_err.success is False
    assert "maksimal 100%" in res_err.error or "maksimal 100%" in res_err.output

    # 2. Test baca_baterai execution
    battery_manifest = SkillManifest.from_dict({
        "name": "baca_baterai",
        "description": "Membaca baterai",
        "permissions": {"termux_api": ["termux-battery-status"]},
        "status": "active"
    })
    adapter_battery = CustomSkillToolAdapter(battery_manifest, skills_dir / "baca_baterai")
    res_batt = await adapter_battery.execute(ctx)
    assert res_batt.success is True
    assert "baterai" in res_batt.output.lower() or "dicas" in res_batt.output.lower()


@pytest.mark.asyncio
async def test_tool_registry_and_router_integration():
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    skills_dir = repo_root / "custom_skills"

    tool_reg = ToolRegistry()
    skill_reg = CustomSkillRegistry(skills_dir=skills_dir)
    skill_reg.load_skills()
    skill_reg.sync_to_tool_registry(tool_reg)

    # Ensure skill is in tool_reg and can be executed via tool_reg
    assert tool_reg.get("hitung_diskon") is not None
    ctx = ToolContext(chat_id=1, user_id=2)
    exec_res = await tool_reg.execute("hitung_diskon", ctx, {"harga": 200000, "diskon_persen": 10})
    assert exec_res.success is True
    assert "180,000" in exec_res.output or "180000" in exec_res.output

    # Test ToolRouter top-k inclusion
    router = ToolRouter(registry=tool_reg, custom_skill_registry=skill_reg)
    schemas = router.get_tools_for_message("tolong hitung diskon barang")
    assert schemas is not None
    schema_names = [s["function"]["name"] for s in schemas if "function" in s]
    assert "hitung_diskon" in schema_names
