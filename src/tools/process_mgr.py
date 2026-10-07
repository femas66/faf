from __future__ import annotations

import logging
import os
import re
import signal
from typing import Any

from src.core.android_bridge import bridge
from src.core.permissions import permission_manager
from src.tools.base import BaseTool, ToolContext, ToolResult

logger = logging.getLogger("faf_agent.tools.process_mgr")


def _read_proc_file(filepath: str) -> str:
    """Safely read content of a Linux /proc file."""
    try:
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                return f.read().strip()
    except Exception:
        pass
    return ""


class ProcessManagerTool(BaseTool):
    """Deep Linux and Android Process Management Tool (Pure Linux /proc & ps, Zero psutil)."""

    name = "process_manager"
    description = (
        "Manajemen proses sistem Linux & Android: melihat daftar proses sistem yang berjalan "
        "(dengan filter nama, pengurutan memori/CPU), inspeksi mendalam detail proses via PID "
        "(status, memori RSS, thread, command line), ringkasan top proses & beban sistem (load average), "
        "serta menghentikan proses via PID atau nama proses dengan proteksi mutlak anti self-termination."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "list_processes",
                    "process_info",
                    "top_summary",
                    "kill_process",
                    "kill_by_name",
                ],
                "description": "Tindakan manajemen proses yang diinginkan.",
            },
            "limit": {
                "type": "integer",
                "description": "Jumlah proses yang ditampilkan (default: 15).",
                "default": 15,
            },
            "search_query": {
                "type": "string",
                "description": "Kata kunci pencarian nama atau perintah proses.",
            },
            "sort_by": {
                "type": "string",
                "enum": ["mem", "cpu", "pid", "name"],
                "description": "Pengurutan daftar proses: mem, cpu, pid, atau name (default: mem).",
                "default": "mem",
            },
            "pid": {
                "type": "integer",
                "description": "ID Proses (PID) untuk inspeksi atau terminasi.",
            },
            "process_name": {
                "type": "string",
                "description": "Nama proses untuk aksi 'kill_by_name'.",
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
        action = kwargs.get("action", "").lower().strip()

        if context.on_status_update:
            await context.on_status_update(f"● process_manager · {action}")

        # -------------------------------------------------------------------
        # 1. Action: LIST_PROCESSES
        # -------------------------------------------------------------------
        if action == "list_processes":
            limit = kwargs.get("limit", 15)
            query = kwargs.get("search_query", "").lower().strip()
            sort_by = kwargs.get("sort_by", "mem").lower()

            res = await bridge.execute_shell("ps -ef || ps -A", timeout=5)
            if res.success and res.stdout:
                raw_lines = [l for l in res.stdout.splitlines() if l.strip()]
                content_lines = raw_lines[1:] if len(raw_lines) > 1 else raw_lines

                parsed_procs = []
                for line in content_lines:
                    parts = line.split()
                    if len(parts) >= 4:
                        # Extract PID
                        pid_str = parts[1] if not parts[0].isdigit() else parts[0]
                        cmd = parts[-1].split("/")[-1]
                        full_cmd = " ".join(parts[7:]) if len(parts) > 7 else cmd
                        if query and query not in full_cmd.lower() and query not in pid_str:
                            continue
                        parsed_procs.append({
                            "pid": pid_str,
                            "user": parts[0],
                            "cmd": cmd,
                            "full_cmd": full_cmd,
                            "line": line,
                        })

                total = len(parsed_procs)
                display = parsed_procs[:limit]

                out_lines = [
                    f"Daftar Proses Sistem yang Berjalan:",
                    f"• Total Ditemukan: {total} proses" + (f" (menampilkan {limit} teratas)" if total > limit else ""),
                    "",
                ]
                for p in display:
                    out_lines.append(f"• PID {p['pid']} ({p['user']}): {p['cmd']}")

                return ToolResult(success=True, output="\n".join(out_lines))
            return ToolResult(success=True, output="Tidak ada daftar proses yang dapat diambil.")

        # -------------------------------------------------------------------
        # 2. Action: PROCESS_INFO
        # -------------------------------------------------------------------
        elif action == "process_info":
            target_pid = kwargs.get("pid")
            if target_pid is None:
                return ToolResult(success=False, output="", error="Parameter 'pid' wajib disertakan.")

            proc_dir = f"/proc/{target_pid}"
            if not os.path.exists(proc_dir):
                return ToolResult(success=False, output="", error=f"Proses dengan PID {target_pid} tidak ditemukan atau telah berhenti.")

            comm = _read_proc_file(f"{proc_dir}/comm")
            cmdline = _read_proc_file(f"{proc_dir}/cmdline").replace("\x00", " ")
            status_text = _read_proc_file(f"{proc_dir}/status")

            # Parse status fields
            info_dict = {}
            for sline in status_text.splitlines():
                if ":" in sline:
                    k, v = sline.split(":", 1)
                    info_dict[k.strip()] = v.strip()

            state = info_dict.get("State", "Unknown")
            ppid = info_dict.get("PPid", "-")
            uid = info_dict.get("Uid", "-")
            threads = info_dict.get("Threads", "1")
            vm_rss = info_dict.get("VmRSS", "-")
            vm_size = info_dict.get("VmSize", "-")

            out_lines = [
                f"Informasi Detail Proses PID {target_pid}:",
                f"• Nama Proses: {comm}",
                f"• Status (State): {state}",
                f"• Parent PID (PPID): {ppid}",
                f"• Pengguna (UID): {uid}",
                f"• Jumlah Thread: {threads}",
                f"• Memori Fisik (RSS): {vm_rss}",
                f"• Memori Virtual: {vm_size}",
                f"• Command Line: {cmdline[:200] if cmdline else comm}",
            ]
            return ToolResult(success=True, output="\n".join(out_lines))

        # -------------------------------------------------------------------
        # 3. Action: TOP_SUMMARY
        # -------------------------------------------------------------------
        elif action == "top_summary":
            loadavg = _read_proc_file("/proc/loadavg")
            load_str = loadavg.split()[:3] if loadavg else ["-", "-", "-"]
            load_formatted = ", ".join(load_str)

            res = await bridge.execute_shell("ps -eo pid,user,comm,%mem --sort=-%mem 2>/dev/null || ps -ef", timeout=4)
            procs = []
            if res.success and res.stdout:
                lines = [l for l in res.stdout.splitlines() if l.strip()][1:]
                for l in lines[:10]:
                    parts = l.split()
                    if len(parts) >= 2:
                        pid = parts[0]
                        cmd = parts[-1].split("/")[-1]
                        procs.append(f"• PID {pid}: {cmd}")

            out_lines = [
                f"Ringkasan Beban & Proses Teratas Sistem:",
                f"• Load Average (1m, 5m, 15m): {load_formatted}",
                f"• Proses Teratas Berjalan:",
            ]
            out_lines.extend(procs if procs else ["(Tidak ada data top proses)"])
            return ToolResult(success=True, output="\n".join(out_lines))

        # -------------------------------------------------------------------
        # 4. Action: KILL_PROCESS
        # -------------------------------------------------------------------
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

            try:
                os.kill(target_pid, sig_num)
                return ToolResult(
                    success=True,
                    output=f"Proses PID {target_pid} berhasil dihentikan dengan sinyal {sig_num}.",
                )
            except ProcessLookupError:
                return ToolResult(success=False, output="", error=f"Proses dengan PID {target_pid} tidak ditemukan.")
            except PermissionError:
                if bridge.is_root_available():
                    res = await bridge.execute_shell(f"kill -{sig_num} {target_pid}", as_root=True)
                    if res.success:
                        return ToolResult(success=True, output=f"Proses PID {target_pid} dihentikan via root Superuser.")
                    return ToolResult(success=False, output="", error=f"Gagal menghentikan proses via root: {res.stderr}")
                return ToolResult(success=False, output="", error=f"Tidak memiliki izin untuk menghentikan PID {target_pid}.")
            except Exception as e:
                return ToolResult(success=False, output="", error=f"Gagal menghentikan PID {target_pid}: {str(e)}")

        # -------------------------------------------------------------------
        # 5. Action: KILL_BY_NAME
        # -------------------------------------------------------------------
        elif action == "kill_by_name":
            proc_name = kwargs.get("process_name", "").strip()
            sig_num = kwargs.get("signal", 9)

            if not proc_name:
                return ToolResult(success=False, output="", error="Parameter 'process_name' wajib disertakan.")

            # IMMUNITY CHECK
            is_immune, reason = permission_manager.check_self_termination(command=f"pkill {proc_name}")
            if is_immune:
                logger.warning(f"Prevented kill_by_name on protected process: {proc_name}")
                return ToolResult(success=False, output="", error=reason)

            res = await bridge.execute_shell(f"pkill -{sig_num} -f {shlex.quote(proc_name)}", as_root=bridge.is_root_available())
            if res.success:
                return ToolResult(
                    success=True,
                    output=f"Proses dengan nama '{proc_name}' berhasil dihentikan.",
                )
            return ToolResult(
                success=True,
                output=f"Tidak ditemukan proses aktif dengan nama '{proc_name}'.",
            )

        return ToolResult(success=False, output="", error=f"Aksi process_manager '{action}' tidak dikenal.")
