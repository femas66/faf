from __future__ import annotations

import asyncio
import json
import logging
import os
import pathlib
import sys
import time
from dataclasses import dataclass, field
from typing import Any

from src.config import get_settings
from src.custom_skills.ast_validator import ASTValidator
from src.custom_skills.audit import skill_audit_logger
from src.custom_skills.manifest import SkillManifest

logger = logging.getLogger("faf_agent.custom_skills.runner")

MAX_INPUT_BYTES = 32 * 1024   # 32 KB
MAX_OUTPUT_BYTES = 64 * 1024  # 64 KB
MAX_MEMORY_BYTES = 256 * 1024 * 1024  # 256 MB


@dataclass
class ExecutionResult:
    success: bool
    output: str = ""
    data: dict[str, Any] | None = None
    error: str | None = None
    duration_ms: float = 0.0
    violation_type: str | None = None


def _create_sandbox_preexec(timeout_sec: int):
    """Factory creating preexec_fn for child process with resource limits."""
    def preexec() -> None:
        try:
            import resource
            # CPU time limit (soft = timeout+2, hard = timeout+4)
            resource.setrlimit(resource.RLIMIT_CPU, (timeout_sec + 2, timeout_sec + 4))
        except Exception:
            pass

        try:
            import resource
            # Max open file descriptors
            resource.setrlimit(resource.RLIMIT_NOFILE, (32, 64))
        except Exception:
            pass

        try:
            import resource
            # Address space / virtual memory (256 MB on Linux/Termux)
            resource.setrlimit(resource.RLIMIT_AS, (MAX_MEMORY_BYTES, MAX_MEMORY_BYTES))
        except Exception:
            pass

    return preexec


class SkillRunner:
    """Isolated subprocess execution runner enforcing AST security, timeouts, and resource limits."""

    def __init__(self, manifest: SkillManifest, skill_dir: str | pathlib.Path) -> None:
        self.manifest = manifest
        self.skill_dir = pathlib.Path(skill_dir).resolve()
        self.settings = get_settings()

    async def execute(
        self,
        arguments: dict[str, Any] | None = None,
        user_id: int | None = None,
        timeout_override: int | None = None,
    ) -> ExecutionResult:
        """Run skill in isolated subprocess with strict security & resource controls."""
        start_time = time.monotonic()
        args = arguments or {}
        main_script = self.skill_dir / "main.py"
        timeout_sec = timeout_override or self.manifest.timeout_sec or self.settings.custom_skills_runner_timeout

        if not main_script.exists():
            err_msg = f"File main.py tidak ditemukan di direktori skill '{self.manifest.name}'."
            skill_audit_logger.log_event(
                action="execute",
                skill_name=self.manifest.name,
                version=self.manifest.version,
                user_id=user_id,
                status="failed",
                error=err_msg,
            )
            return ExecutionResult(success=False, error=err_msg)

        # 1. Static AST Analysis Gate
        try:
            with open(main_script, "r", encoding="utf-8") as f:
                code_content = f.read()
        except Exception as e:
            return ExecutionResult(success=False, error=f"Gagal membaca kode skill: {e}")

        ast_violations = ASTValidator.validate_code(code_content, permissions=self.manifest.permissions)
        if ast_violations:
            err_msg = f"Penolakan Analisis Statis AST: {'; '.join(ast_violations)}"
            duration_ms = (time.monotonic() - start_time) * 1000
            skill_audit_logger.log_event(
                action="security_blocked",
                skill_name=self.manifest.name,
                version=self.manifest.version,
                user_id=user_id,
                status="failed",
                duration_ms=duration_ms,
                error=err_msg,
                details={"violations": ast_violations},
            )
            return ExecutionResult(
                success=False,
                error=err_msg,
                duration_ms=duration_ms,
                violation_type="AST_SECURITY_VIOLATION",
            )

        # 2. Input JSON validation & size limit
        try:
            input_bytes = json.dumps(args, ensure_ascii=False).encode("utf-8")
            if len(input_bytes) > MAX_INPUT_BYTES:
                return ExecutionResult(
                    success=False,
                    error=f"Ukuran input parameter ({len(input_bytes)} bytes) melebihi batas 32KB.",
                    violation_type="INPUT_SIZE_EXCEEDED",
                )
        except Exception as e:
            return ExecutionResult(success=False, error=f"Serialisasi input JSON gagal: {e}")

        # 3. Environment sanitization (Default deny, strip all secrets)
        safe_env = {
            "PATH": os.environ.get(
                "PATH",
                "/data/data/com.termux/files/usr/bin:/system/bin:/bin:/usr/bin",
            ),
            "LANG": "C.UTF-8",
            "PYTHONUNBUFFERED": "1",
        }

        # 4. Isolated Working Directory
        sandbox_dir = self.skill_dir / ".sandbox"
        sandbox_dir.mkdir(parents=True, exist_ok=True)

        preexec = _create_sandbox_preexec(timeout_sec)

        # 5. Process execution via python -I (Isolated mode)
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                "-I",
                str(main_script),
                cwd=str(self.skill_dir),
                env=safe_env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                preexec_fn=preexec,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(input=input_bytes),
                    timeout=timeout_sec,
                )
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                    await proc.wait()
                except Exception:
                    pass
                duration_ms = (time.monotonic() - start_time) * 1000
                err_msg = f"Skill '{self.manifest.name}' melebihi batas waktu eksekusi ({timeout_sec} detik)."
                skill_audit_logger.log_event(
                    action="execute",
                    skill_name=self.manifest.name,
                    version=self.manifest.version,
                    user_id=user_id,
                    status="failed",
                    duration_ms=duration_ms,
                    error=err_msg,
                )
                return ExecutionResult(
                    success=False,
                    error=err_msg,
                    duration_ms=duration_ms,
                    violation_type="TIMEOUT",
                )

            duration_ms = (time.monotonic() - start_time) * 1000

            # 6. Check output size limit
            if len(stdout_bytes) > MAX_OUTPUT_BYTES:
                err_msg = f"Output skill melebihi batas maksimum 64KB ({len(stdout_bytes)} bytes)."
                skill_audit_logger.log_event(
                    action="security_blocked",
                    skill_name=self.manifest.name,
                    version=self.manifest.version,
                    user_id=user_id,
                    status="failed",
                    duration_ms=duration_ms,
                    error=err_msg,
                )
                return ExecutionResult(
                    success=False,
                    error=err_msg,
                    duration_ms=duration_ms,
                    violation_type="OUTPUT_SIZE_EXCEEDED",
                )

            stdout_str = stdout_bytes.decode("utf-8", errors="replace").strip()
            stderr_str = stderr_bytes.decode("utf-8", errors="replace").strip()

            if proc.returncode != 0:
                err_msg = f"Skill gagal (exit code {proc.returncode}): {stderr_str or stdout_str}"
                skill_audit_logger.log_event(
                    action="execute",
                    skill_name=self.manifest.name,
                    version=self.manifest.version,
                    user_id=user_id,
                    status="failed",
                    duration_ms=duration_ms,
                    error=err_msg,
                )
                return ExecutionResult(
                    success=False,
                    output=stdout_str,
                    error=err_msg,
                    duration_ms=duration_ms,
                )

            # 7. Parse JSON output
            try:
                res_data = json.loads(stdout_str)
                if isinstance(res_data, dict):
                    is_success = bool(res_data.get("success", True))
                    error_val = res_data.get("error")
                    output_text = str(res_data.get("output", stdout_str))
                    result = ExecutionResult(
                        success=is_success,
                        output=output_text,
                        data=res_data,
                        error=error_val,
                        duration_ms=duration_ms,
                    )
                else:
                    result = ExecutionResult(
                        success=True,
                        output=json.dumps(res_data, ensure_ascii=False),
                        duration_ms=duration_ms,
                    )
            except json.JSONDecodeError:
                result = ExecutionResult(
                    success=True,
                    output=stdout_str if stdout_str else "Skill selesai tanpa output teks.",
                    duration_ms=duration_ms,
                )

            skill_audit_logger.log_event(
                action="execute",
                skill_name=self.manifest.name,
                version=self.manifest.version,
                user_id=user_id,
                status="success" if result.success else "failed",
                duration_ms=duration_ms,
                error=result.error,
            )
            return result

        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            err_msg = f"Kesalahan eksekusi runner skill: {e}"
            skill_audit_logger.log_event(
                action="execute",
                skill_name=self.manifest.name,
                version=self.manifest.version,
                user_id=user_id,
                status="failed",
                duration_ms=duration_ms,
                error=err_msg,
            )
            return ExecutionResult(
                success=False,
                error=err_msg,
                duration_ms=duration_ms,
            )
