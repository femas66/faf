from __future__ import annotations

import logging
import shlex
from typing import Any

from src.core.android_bridge import bridge
from src.tools.base import BaseTool, ToolContext, ToolResult

logger = logging.getLogger("faf_agent.tools.package_mgr")


class PackageManagerTool(BaseTool):
    name = "package_manager"
    description = (
        "Manajemen aplikasi Android: melihat daftar aplikasi yang terpasang (3rd-party atau sistem), "
        "membuka aplikasi secara langsung via package name, dan mengecek informasi/versi aplikasi."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list_apps", "open_app", "app_info"],
                "description": "Tindakan package manager yang diinginkan.",
            },
            "filter_type": {
                "type": "string",
                "enum": ["3rd_party", "system", "all"],
                "description": "Filter daftar aplikasi: 3rd_party (aplikasi pengguna), system (aplikasi bawaan), atau all.",
                "default": "3rd_party",
            },
            "package_name": {
                "type": "string",
                "description": "Nama paket Android (contoh: com.whatsapp, com.spotify.music).",
            },
        },
        "required": ["action"],
    }

    async def execute(self, context: ToolContext, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action", "")

        if context.on_status_update:
            await context.on_status_update(f"● package_manager · {action}")

        # 1. List Applications
        if action == "list_apps":
            ftype = kwargs.get("filter_type", "3rd_party")
            flag = "-3" if ftype == "3rd_party" else ("-s" if ftype == "system" else "")
            res = await bridge.execute_shell(f"pm list packages {flag}".strip())

            if res.success and res.stdout:
                packages = [
                    line.replace("package:", "").strip()
                    for line in res.stdout.splitlines()
                    if line.strip()
                ]
                total = len(packages)
                preview = "\n".join(packages[:30])
                suffix = f"\n... dan {total - 30} aplikasi lainnya." if total > 30 else ""
                return ToolResult(
                    success=True,
                    output=f"Ditemukan {total} aplikasi ({ftype}):\n{preview}{suffix}",
                )
            return ToolResult(
                success=True,
                output="Tidak ada aplikasi ditemukan atau perintah pm tidak mengembalikan hasil.",
            )

        # 2. Open Application
        elif action == "open_app":
            pkg = kwargs.get("package_name", "").strip()
            if not pkg:
                return ToolResult(success=False, output="", error="Parameter 'package_name' wajib diisi.")

            # Launch via monkey
            cmd = f"monkey -p {shlex.quote(pkg)} -c android.intent.category.LAUNCHER 1"
            res = await bridge.execute_shell(cmd)
            if "No activities found to run" in res.stdout or not res.success:
                return ToolResult(
                    success=False,
                    output=res.stdout,
                    error=f"Aplikasi '{pkg}' tidak ditemukan atau tidak memiliki launcher activity.",
                )
            return ToolResult(
                success=True,
                output=f"Aplikasi '{pkg}' berhasil diluncurkan ke layar.",
            )

        # 3. Application Info
        elif action == "app_info":
            pkg = kwargs.get("package_name", "").strip()
            if not pkg:
                return ToolResult(success=False, output="", error="Parameter 'package_name' wajib diisi.")

            res_path = await bridge.execute_shell(f"pm path {shlex.quote(pkg)}")
            res_dump = await bridge.execute_shell(
                f"dumpsys package {shlex.quote(pkg)} | grep -E 'versionName|versionCode|firstInstallTime|lastUpdateTime'"
            )

            if not res_path.stdout and not res_dump.stdout:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Detail paket '{pkg}' tidak ditemukan di sistem.",
                )

            info = f"Informasi Paket: {pkg}\n"
            if res_path.stdout:
                info += f"{res_path.stdout}\n"
            if res_dump.stdout:
                info += f"{res_dump.stdout}\n"

            return ToolResult(success=True, output=info.strip())

        return ToolResult(success=False, output="", error=f"Aksi '{action}' tidak dikenal.")
