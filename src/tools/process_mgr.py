from __future__ import annotations

import logging
import os
import signal
from typing import Any

from src.core.android_bridge import bridge
from src.core.permissions import permission_manager
from src.tools.base import BaseTool, ToolContext, ToolResult

logger = logging.getLogger("faf_agent.tools.process_mgr")


class ProcessManagerTool(BaseTool):
    name = "process_manager"
    description = (
        "Manajemen proses sistem: melihat daftar proses sistem yang berjalan "
        "dan menghentikan proses tertentu via PID (dilengkapi proteksi anti self-termination)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list_processes", "kill_process"],
                "description": "Tindakan manajemen proses.",
            },
            "limit": {
                "type": "integer",
                "description": "Jumlah proses teratas yang ditampilkan (default: 10).",
                "default": 10,
            },
            "pid": {
                "type": "integer",
                "description": "ID Proses (PID) yang akan dihentikan.",
            },
            "signal": {
                "type": "integer",
                "description": "Nomor sinyal terminasi (default: 9 untuk SIGKILL, 15 untuk SIGTERM).",
                "default": 9,
            },
        },
        "required": ["action"],
    }

    async def execute(self, context: ToolContext, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action", "")

        if context.on_status_update:
            await context.on_status_update(f"● process_manager · {action}")

        # 1. List Processes (Format list ramah layar HP, tanpa tabel)
        if action == "list_processes":
            limit = kwargs.get("limit", 10)
            res = await bridge.execute_shell("ps -ef || ps -A", timeout=5)
            if res.success and res.stdout:
                raw_lines = [l for l in res.stdout.splitlines() if l.strip()]
                # Skip header
                content_lines = raw_lines[1:] if len(raw_lines) > 1 else raw_lines
                formatted_items = []
                for line in content_lines[:limit]:
                    parts = line.split()
                    if len(parts) >= 2:
                        pid = parts[1] if not parts[0].isdigit() else parts[0]
                        cmd = parts[-1].split("/")[-1]
                        formatted_items.append(f"• PID {pid}: {cmd}")
                    else:
                        formatted_items.append(f"• {line}")

                output = "Daftar proses sistem:\n" + "\n".join(formatted_items)
                return ToolResult(
                    success=True,
                    output=output,
                )
            return ToolResult(
                success=True,
                output="Tidak ada daftar proses yang dapat diambil saat ini.",
            )

        # 2. Kill Process with Immunity Verification
        elif action == "kill_process":
            target_pid = kwargs.get("pid")
            sig_num = kwargs.get("signal", 9)

            if target_pid is None:
                return ToolResult(success=False, output="", error="Parameter 'pid' wajib disertakan.")

            # IMMUNITY CHECK
            is_immune, reason = permission_manager.check_self_termination(
                command=f"kill {target_pid}", target_pid=target_pid
            )
            if is_immune:
                logger.warning(f"Prevented kill attempt on protected process: PID {target_pid}")
                return ToolResult(success=False, output="", error=reason)

            # Native os.kill (standard library)
            try:
                os.kill(target_pid, sig_num)
                return ToolResult(
                    success=True,
                    output=f"Proses PID {target_pid} berhasil dikirim sinyal {sig_num}.",
                )
            except ProcessLookupError:
                return ToolResult(
                    success=False, output="", error=f"Proses dengan PID {target_pid} tidak ditemukan."
                )
            except PermissionError:
                if bridge.is_root_available():
                    res = await bridge.execute_shell(f"kill -{sig_num} {target_pid}", as_root=True)
                    if res.success:
                        return ToolResult(
                            success=True,
                            output=f"Proses PID {target_pid} berhasil dihentikan menggunakan hak Superuser (root).",
                        )
                    return ToolResult(
                        success=False,
                        output="",
                        error=f"Gagal menghentikan proses via root: {res.stderr}",
                    )
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Akses ditolak untuk menghentikan PID {target_pid}. Diperlukan hak akses root.",
                )
            except Exception as e:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Gagal mengirim sinyal ke PID {target_pid}: {str(e)}",
                )

        return ToolResult(success=False, output="", error=f"Aksi '{action}' tidak dikenal.")
