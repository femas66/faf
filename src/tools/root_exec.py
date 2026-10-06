from __future__ import annotations

import logging
from typing import Any

from src.core.android_bridge import bridge
from src.core.permissions import permission_manager
from src.tools.base import BaseTool, ToolContext, ToolResult

logger = logging.getLogger("faf_agent.tools.root_exec")


class RootShellExecTool(BaseTool):
    name = "root_shell_exec"
    description = (
        "Menjalankan shell command di Android Termux (standar Termux atau Superuser via su -c). "
        "Gunakan untuk perintah sistem tingkat lanjut, diagnosa, manipulasi file, atau perintah root."
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Perintah shell Linux / Android yang akan dieksekusi.",
            },
            "as_root": {
                "type": "boolean",
                "description": "Setel True untuk mengeksekusi dengan hak akses Superuser (su -c).",
                "default": False,
            },
            "purpose": {
                "type": "string",
                "description": "Tujuan singkat eksekusi perintah (untuk audit & transparansi).",
                "default": "",
            },
        },
        "required": ["command"],
    }

    async def execute(self, context: ToolContext, **kwargs: Any) -> ToolResult:
        command: str = kwargs.get("command", "").strip()
        as_root: bool = kwargs.get("as_root", False)
        purpose: str = kwargs.get("purpose", "")

        if not command:
            return ToolResult(success=False, output="", error="Perintah shell tidak boleh kosong.")

        # 1. Check credential exfiltration
        is_exfil, exfil_reason = permission_manager.check_credential_exfiltration(command)
        if is_exfil:
            logger.warning(f"Blocked credential exfiltration attempt: {command}")
            return ToolResult(success=False, output="", error=exfil_reason)

        # 2. Check process immunity (anti self-termination)
        is_self_term, term_reason = permission_manager.check_self_termination(command)
        if is_self_term:
            logger.warning(f"Blocked self-termination attempt: {command}")
            return ToolResult(success=False, output="", error=term_reason)

        # 3. Check destructive command guard
        is_destr, destr_reason = permission_manager.check_destructive(command)
        if is_destr:
            logger.warning(f"Destructive operation intercepted: {command}")
            if context.on_request_confirmation:
                title = "⚠️ Konfirmasi Tindakan Berisiko Tinggi"
                details = (
                    f"**Alasan:** {destr_reason}\n"
                    f"**Perintah:** `{command}`\n"
                    f"**Mode Root:** `{'Ya' if as_root else 'Tidak'}`\n"
                    f"**Tujuan:** {purpose or '-'}"
                )
                approved = await context.on_request_confirmation(title, details)
                if not approved:
                    return ToolResult(
                        success=False,
                        output="",
                        error="Operasi dibatalkan: Konfirmasi ditolak oleh pengguna atau batas waktu (timeout) terlampaui.",
                    )
            else:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Operasi ditolak: {destr_reason} memerlukan persetujuan manual pengguna.",
                )

        # 4. Status indicator update
        if context.on_status_update:
            prefix = "[ROOT] " if as_root else ""
            summary = command if len(command) <= 45 else f"{command[:42]}..."
            await context.on_status_update(f"● root_shell_exec · {prefix}`{summary}`")

        # 5. Execute command via bridge
        result = await bridge.execute_shell(command, as_root=as_root)

        if result.success:
            output = result.stdout or "(Command finished with empty output)"
            return ToolResult(success=True, output=output)
        else:
            err_msg = result.stderr or f"Exit code {result.returncode}"
            return ToolResult(
                success=False,
                output=result.stdout,
                error=f"Command failed (code {result.returncode}): {err_msg}",
            )
