from __future__ import annotations

import asyncio
import json
import logging
import pathlib
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from typing import Any

from src.config import get_settings
from src.core.ai_client import AIClient
from src.custom_skills.ast_validator import ASTValidator
from src.custom_skills.audit import skill_audit_logger
from src.custom_skills.git_store import skill_git_store
from src.custom_skills.manifest import SkillManifest, SkillPermissions, SkillStatus
from src.custom_skills.registry import custom_skill_registry
from src.custom_skills.runner import ExecutionResult, SkillRunner

logger = logging.getLogger("faf_agent.custom_skills.pipeline")

SYSTEM_GENERATOR_PROMPT = """Anda adalah insinyur pembuat modul skill Python terisolasi untuk faf-agent di lingkungan Android Termux.
Tugas Anda adalah menghasilkan ekstensi skill baru yang aman, stabil, dan minimal dalam format JSON murni.

ATURAN KEAMANAN & RUNNER:
1. Kode Python hanya boleh memiliki SATU fungsi entry point: `def run(params: dict) -> dict:`
2. Kode WAJIB memiliki blok `if __name__ == '__main__':` yang membaca JSON dari sys.stdin dan menulis JSON ke sys.stdout.
3. DILARANG menggunakan `eval`, `exec`, `compile`, `__import__`, `globals`, `locals`, `getattr`, `setattr`, `ctypes`, `subprocess` bebas, atau modul di luar allowlist.
4. Modul yang diizinkan: `json`, `math`, `re`, `datetime`, `time`, `urllib.parse`, `dataclasses`, `typing`, `sys`, `collections`.
5. Jika membutuhkan Termux:API, hanya boleh memanggil binary resmi yang dideklarasikan di izin `termux_api` (mis. `termux-battery-status`) via `shutil.which` dan `subprocess.run([cmd], ...)`.
6. Parameter schema WAJIB berformat JSON Schema dengan root type 'object'.
7. Sediakan minimal 3 kasus uji di `tests` (2 skenario normal dan 1 skenario edge-case/gagal).

FORMAT OUTPUT WAJIB JSON VALID TUNGGAL (tanpa markdown pembuka/penutup):
{
  "manifest": {
    "name": "<nama_skill_snake_case>",
    "version": "1.0.0",
    "description": "<deskripsi singkat jelas>",
    "parameters": {
      "type": "object",
      "properties": {},
      "required": []
    },
    "permissions": {
      "termux_api": [],
      "network": [],
      "fs_read": [],
      "fs_write": [],
      "shell": false
    },
    "timeout_sec": 10
  },
  "code": "<kode python lengkap>",
  "tests": [
    {
      "name": "<nama_test_1>",
      "input": {},
      "expected_keys": ["success", "output"]
    }
  ],
  "changelog": "# Changelog <nama_skill>\\n\\n## [1.0.0] - Inisialisasi skill baru"
}
"""


@dataclass
class PendingProposal:
    skill_name: str
    manifest: SkillManifest
    code: str
    tests: list[dict[str, Any]]
    changelog: str
    test_results: list[dict[str, Any]]
    chat_id: int
    user_id: int
    created_at: float = field(default_factory=time.monotonic)
    ttl_seconds: int = 300  # 5 minutes expiration window

    def is_expired(self) -> bool:
        return (time.monotonic() - self.created_at) > self.ttl_seconds

    def format_proposal_summary(self) -> str:
        """Format a clean, mobile-screen friendly proposal summary without broken tables."""
        perms = self.manifest.permissions
        req_perms: list[str] = []
        if perms.termux_api:
            req_perms.append(f"Termux API: {', '.join(perms.termux_api)}")
        if perms.network:
            req_perms.append(f"Network: {', '.join(perms.network)}")
        if perms.fs_read:
            req_perms.append(f"Baca File: {', '.join(perms.fs_read)}")
        if perms.fs_write:
            req_perms.append(f"Tulis File: {', '.join(perms.fs_write)}")
        if perms.shell:
            req_perms.append("Akses Shell (Sensitif)")
        perm_text = " • " + "\n • ".join(req_perms) if req_perms else " • Tidak membutuhkan izin khusus (Aman)"

        passed_tests = sum(1 for t in self.test_results if t.get("passed"))
        total_tests = len(self.test_results)

        return (
            f"Proposal Skill Baru Siap Diaktifkan:\n\n"
            f"• Nama: {self.skill_name} (v{self.manifest.version})\n"
            f"• Deskripsi: {self.manifest.description}\n"
            f"• Batas Waktu: {self.manifest.timeout_sec} detik\n\n"
            f"Izin yang Diminta:\n{perm_text}\n\n"
            f"Hasil Uji Validasi:\n"
            f"• {passed_tests}/{total_tests} pengujian otomatis berhasil lolos di lingkungan terisolasi.\n\n"
            f"Ketik 'Ya' untuk menyetujui dan mengaktifkan skill ini (berlaku 5 menit).\n"
            f"Ketik 'Tidak' untuk membatalkan."
        )


class SkillTester:
    """Executes test cases against a skill candidate inside SkillRunner."""

    @classmethod
    async def run_tests(
        cls, manifest: SkillManifest, skill_dir: pathlib.Path, tests: list[dict[str, Any]]
    ) -> tuple[bool, list[dict[str, Any]]]:
        runner = SkillRunner(manifest=manifest, skill_dir=skill_dir)
        results: list[dict[str, Any]] = []
        all_passed = True

        for idx, t in enumerate(tests):
            test_name = t.get("name", f"test_{idx+1}")
            test_input = t.get("input", {})
            expected_keys = t.get("expected_keys") or t.get("expected_output_keys", [])
            expect_failure = t.get("expect_failure", False)

            exec_res: ExecutionResult = await runner.execute(arguments=test_input)

            passed = False
            detail = ""

            if expect_failure:
                if not exec_res.success:
                    passed = True
                    detail = "Berhasil memicu kegagalan yang diharapkan."
                else:
                    passed = False
                    detail = "Uji gagal: Seharusnya gagal tapi mengembalikan sukses."
            else:
                if exec_res.success:
                    if expected_keys and exec_res.data:
                        missing = [k for k in expected_keys if k not in exec_res.data]
                        if missing:
                            passed = False
                            detail = f"Output tidak memuat kunci yang diharapkan: {missing}"
                        else:
                            passed = True
                            detail = "Lolos pengujian."
                    else:
                        passed = True
                        detail = "Lolos pengujian."
                else:
                    passed = False
                    detail = f"Eksekusi gagal: {exec_res.error}"

            if not passed:
                all_passed = False

            results.append({
                "test_name": test_name,
                "passed": passed,
                "detail": detail,
                "output": exec_res.output,
                "error": exec_res.error,
                "duration_ms": exec_res.duration_ms,
            })

        return all_passed, results


class SkillCreationPipeline:
    """Pipeline orchestrating LLM generation, AST validation, test execution, and approval lifecycle."""

    def __init__(self, ai_client: AIClient | None = None) -> None:
        self.ai_client = ai_client or AIClient()
        self.settings = get_settings()
        self._pending_proposals: dict[int, PendingProposal] = {}

    def get_pending_proposal(self, chat_id: int) -> PendingProposal | None:
        prop = self._pending_proposals.get(chat_id)
        if prop and prop.is_expired():
            self._pending_proposals.pop(chat_id, None)
            return None
        return prop

    async def create_skill(
        self,
        prompt_request: str,
        chat_id: int,
        user_id: int,
        max_iterations: int = 3,
    ) -> tuple[bool, str, PendingProposal | None]:
        """Run iterative generation and verification pipeline (max 3 self-correction iterations)."""
        logger.info(f"Starting skill creation pipeline for chat_id={chat_id}: '{prompt_request}'")

        messages = [
            {"role": "system", "content": SYSTEM_GENERATOR_PROMPT},
            {
                "role": "user",
                "content": f"Buatkan skill baru untuk kebutuhan berikut:\n\"{prompt_request}\"",
            },
        ]

        iteration = 0
        last_error = ""

        # Temporary staging folder for isolated test execution
        temp_dir = pathlib.Path(tempfile.mkdtemp(prefix="faf_skill_gen_"))

        try:
            while iteration < max_iterations:
                iteration += 1
                logger.info(f"Skill generation iteration {iteration}/{max_iterations}")

                # 1. Call LLM
                try:
                    response = await self.ai_client.get_chat_completion(
                        messages=messages,
                        temperature=0.1,
                    )
                    raw_content = response.choices[0].message.content or "{}"
                    # Strip any accidental markdown fences
                    clean_json = raw_content.strip()
                    if clean_json.startswith("```"):
                        lines = clean_json.splitlines()
                        if lines[0].startswith("```"):
                            lines = lines[1:]
                        if lines and lines[-1].startswith("```"):
                            lines = lines[:-1]
                        clean_json = "\n".join(lines).strip()

                    payload = json.loads(clean_json)
                except Exception as e:
                    last_error = f"Gagal mem-parsing keluaran JSON generator: {e}"
                    messages.append({
                        "role": "assistant",
                        "content": raw_content if 'raw_content' in locals() else "",
                    })
                    messages.append({
                        "role": "user",
                        "content": f"Format JSON tidak valid ({e}). Tolong kirimkan HANYA valid JSON tunggal.",
                    })
                    continue

                # 2. Parse Manifest
                try:
                    manifest_data = payload.get("manifest", {})
                    manifest = SkillManifest.from_dict(manifest_data)
                    manifest.status = SkillStatus.TESTED.value
                    code_content = str(payload.get("code", "")).strip()
                    tests_list = payload.get("tests", [])
                    changelog_text = str(payload.get("changelog", f"# Changelog {manifest.name}\n\n## [1.0.0]"))
                except Exception as e:
                    last_error = f"Manifest tidak valid: {e}"
                    messages.append({
                        "role": "user",
                        "content": f"Manifest tidak valid ({e}). Perbaiki skema manifest.",
                    })
                    continue

                # 3. Static AST Security Gate
                ast_violations = ASTValidator.validate_code(code_content, permissions=manifest.permissions)
                if ast_violations:
                    last_error = f"Pelanggaran AST: {'; '.join(ast_violations)}"
                    logger.warning(f"Iteration {iteration} AST rejected: {ast_violations}")
                    messages.append({
                        "role": "assistant",
                        "content": json.dumps(payload),
                    })
                    messages.append({
                        "role": "user",
                        "content": (
                            f"Kode ditolak oleh analisis statis AST:\n"
                            f"{'; '.join(ast_violations)}\n"
                            f"Perbaiki kode agar mematuhi aturan keamanan dan allowlist modul."
                        ),
                    })
                    continue

                # 4. Prepare Staging Directory & Run Tests
                stage_skill_dir = temp_dir / manifest.name
                if stage_skill_dir.exists():
                    shutil.rmtree(stage_skill_dir)
                stage_skill_dir.mkdir(parents=True, exist_ok=True)

                with open(stage_skill_dir / "main.py", "w", encoding="utf-8") as f:
                    f.write(code_content)
                with open(stage_skill_dir / "manifest.json", "w", encoding="utf-8") as f:
                    json.dump(manifest.to_dict(), f, indent=2)

                all_passed, test_results = await SkillTester.run_tests(
                    manifest=manifest, skill_dir=stage_skill_dir, tests=tests_list
                )

                if not all_passed:
                    failed_details = [
                        f"- {t['test_name']}: {t['detail']} (Error: {t.get('error')})"
                        for t in test_results
                        if not t["passed"]
                    ]
                    last_error = f"Uji runtime gagal: {'; '.join(failed_details)}"
                    logger.warning(f"Iteration {iteration} tests failed: {failed_details}")
                    messages.append({
                        "role": "assistant",
                        "content": json.dumps(payload),
                    })
                    messages.append({
                        "role": "user",
                        "content": (
                            f"Pengujian otomatis gagal pada kasus berikut:\n"
                            f"{chr(10).join(failed_details)}\n"
                            f"Perbaiki kode Python dan/atau kasus uji agar semua tes berhasil lolos."
                        ),
                    })
                    continue

                # If both AST and all tests pass: Success!
                manifest.status = SkillStatus.PENDING_APPROVAL.value
                proposal = PendingProposal(
                    skill_name=manifest.name,
                    manifest=manifest,
                    code=code_content,
                    tests=tests_list,
                    changelog=changelog_text,
                    test_results=test_results,
                    chat_id=chat_id,
                    user_id=user_id,
                )
                self._pending_proposals[chat_id] = proposal

                skill_audit_logger.log_event(
                    action="create",
                    skill_name=manifest.name,
                    version=manifest.version,
                    user_id=user_id,
                    status="success",
                    details={"iterations": iteration},
                )

                summary_text = proposal.format_proposal_summary()
                return True, summary_text, proposal

            # Max iterations reached without passing tests
            err_report = (
                f"Saya telah mencoba membuat dan memperbaiki skill ini sebanyak 3 iterasi, "
                f"namun pengujian otomatis tetap belum berhasil.\n\n"
                f"Kendala terakhir: {last_error}"
            )
            skill_audit_logger.log_event(
                action="create",
                skill_name="unknown",
                user_id=user_id,
                status="failed",
                error=err_report,
                details={"iterations": iteration},
            )
            return False, err_report, None

        finally:
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)

    async def approve_proposal(self, chat_id: int, user_id: int) -> tuple[bool, str]:
        """Approve pending proposal, save skill to disk, commit to git, and activate."""
        proposal = self.get_pending_proposal(chat_id)
        if not proposal:
            return False, "Tidak ada proposal skill yang sedang menunggu persetujuan (atau sudah kedaluwarsa)."

        # Save to custom_skills directory
        manifest = proposal.manifest
        manifest.status = SkillStatus.ACTIVE.value

        try:
            custom_skill_registry.save_skill(
                manifest=manifest,
                code=proposal.code,
                tests=proposal.tests,
                changelog=proposal.changelog,
            )

            # Git commit
            commit_hash = await skill_git_store.commit_skill(
                skill_name=proposal.skill_name,
                message=f"feat(skill): add {proposal.skill_name} v{manifest.version}",
            )

            # Sync to ToolRegistry
            custom_skill_registry.sync_to_tool_registry()

            # Remove pending
            self._pending_proposals.pop(chat_id, None)

            skill_audit_logger.log_event(
                action="approve",
                skill_name=proposal.skill_name,
                version=manifest.version,
                user_id=user_id,
                status="success",
                details={"commit_hash": commit_hash},
            )

            success_msg = (
                f"Skill '{proposal.skill_name}' (v{manifest.version}) berhasil disetujui dan telah aktif!\n"
                f"Anda sekarang dapat langsung meminta saya untuk menggunakannya."
            )
            return True, success_msg

        except Exception as e:
            logger.error(f"Failed to activate skill {proposal.skill_name}: {e}")
            return False, f"Gagal mengaktifkan skill: {e}"

    async def reject_proposal(self, chat_id: int, user_id: int, reason: str = "") -> tuple[bool, str]:
        """Reject and cancel pending skill proposal."""
        proposal = self.get_pending_proposal(chat_id)
        if not proposal:
            return False, "Tidak ada proposal skill yang aktif."

        skill_name = proposal.skill_name
        self._pending_proposals.pop(chat_id, None)

        skill_audit_logger.log_event(
            action="reject",
            skill_name=skill_name,
            version=proposal.manifest.version,
            user_id=user_id,
            status="success",
            details={"reason": reason or "Ditolak oleh pengguna."},
        )

        return True, f"Pembuatan skill '{skill_name}' telah dibatalkan."


# Singleton default pipeline
skill_pipeline = SkillCreationPipeline()
