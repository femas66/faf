from __future__ import annotations

import logging
import os
import signal
from typing import Any

import psutil

from src.core.android_bridge import bridge
from src.core.permissions import permission_manager
from src.tools.base import BaseTool, ToolContext, ToolResult

logger = logging.getLogger("faf_agent.tools.process_mgr")


class ProcessManagerTool(BaseTool):
    name = "process_manager"
    description = (
        "Manajemen proses sistem: melihat daftar proses dengan konsumsi CPU/RAM tertinggi "
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

        # 1. List Processes
        if action == "list_processes":
            limit = kwargs.get("limit", 10)
            procs = []
            for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent", "status"]):
                try:
                    p_info = p.info
                    procs.append(p_info)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            # Sort by memory percent or cpu
            procs.sort(key=lambda x: (x.get("memory_percent") or 0.0), reverse=True)
            top_procs = procs[:limit]

            lines = ["PID    | CPU % | MEM % | PROSES"]
            lines.append("-------|-------|-------|----------------------")
            for p in top_procs:
                pid = str(p.get("pid", 0)).ljust(6)
                cpu = f"{p.get('cpu_percent', 0.0):.1f}%".ljust(5)
                mem = f"{p.get('memory_percent', 0.0):.1f}%".ljust(5)
                name = str(p.get("name", "unknown"))[:22]
                lines.append(f"{pid} | {cpu} | {mem} | {name}")

            return ToolResult(
                success=True,
                output="\n".join(lines),
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

            # Attempt to kill via psutil or root shell
            try:
                proc = psutil.Process(target_pid)
                pname = proc.name()
                proc.send_signal(sig_num)
                return ToolResult(
                    success=True,
                    output=f"Proses '{pname}' (PID {target_pid}) berhasil dikirim sinyal {sig_num}.",
                )
            except psutil.NoSuchProcess:
                return ToolResult(success=False, output="", error=f"Proses dengan PID {target_pid} tidak ditemukan.")
            except psutil.AccessDenied:
                # Fallback to root kill if permitted
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

        return ToolResult(success=False, output="", error=f"Aksi '{action}' tidak dikenal.")
