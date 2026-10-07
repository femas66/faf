from __future__ import annotations

import logging
import re
import shlex
from typing import Any

from src.core.android_bridge import bridge
from src.core.permissions import permission_manager
from src.tools.base import BaseTool, ToolContext, ToolResult

logger = logging.getLogger("faf_agent.tools.package_mgr")

# Common aliases for quick app launch by casual name
APP_ALIASES: dict[str, str] = {
    "whatsapp": "com.whatsapp",
    "wa": "com.whatsapp",
    "telegram": "org.telegram.messenger",
    "tg": "org.telegram.messenger",
    "youtube": "com.google.android.youtube",
    "yt": "com.google.android.youtube",
    "chrome": "com.android.chrome",
    "browser": "com.android.chrome",
    "spotify": "com.spotify.music",
    "tiktok": "com.zhiliaoapp.musically",
    "instagram": "com.instagram.android",
    "ig": "com.instagram.android",
    "camera": "com.android.camera",
    "settings": "com.android.settings",
    "pengaturan": "com.android.settings",
    "calculator": "com.google.android.calculator",
    "kalkulator": "com.google.android.calculator",
    "clock": "com.google.android.deskclock",
    "jam": "com.google.android.deskclock",
    "gallery": "com.google.android.apps.photos",
    "galeri": "com.google.android.apps.photos",
    "maps": "com.google.android.apps.maps",
    "gmail": "com.google.android.gm",
    "termux": "com.termux",
}


class PackageManagerTool(BaseTool):
    """Deep Android Application Management Tool: list, fuzzy open, detailed inspection,

    focus detection, force stop, enable/disable, clear data, and uninstall.
    """

    name = "package_manager"
    description = (
        "Manajemen aplikasi Android komprehensif: melihat daftar aplikasi (3rd-party, sistem, atau pencarian nama), "
        "membuka aplikasi secara langsung via package name atau nama umum (whatsapp, youtube, chrome, camera, dll), "
        "mengecek informasi detail aplikasi (versi, SDK, izin, UID, path APK), mendeteksi aplikasi yang sedang "
        "terbuka di layar (current_app), menghentikan paksa aplikasi (force_stop), menonaktifkan/mengaktifkan aplikasi, "
        "serta membersihkan data dan mencopot aplikasi dengan pengamanan konfirmasi."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "list_apps",
                    "open_app",
                    "app_info",
                    "current_app",
                    "force_stop",
                    "enable_app",
                    "disable_app",
                    "clear_data",
                    "uninstall",
                ],
                "description": "Tindakan package manager yang diinginkan.",
            },
            "filter_type": {
                "type": "string",
                "enum": ["3rd_party", "system", "all", "enabled", "disabled"],
                "description": "Filter daftar aplikasi (default: 3rd_party).",
                "default": "3rd_party",
            },
            "search_query": {
                "type": "string",
                "description": "Kata kunci filter nama atau paket untuk 'list_apps'.",
            },
            "package_name": {
                "type": "string",
                "description": "Nama paket Android (contoh: com.whatsapp) atau nama umum (whatsapp, youtube, camera).",
            },
            "limit": {
                "type": "integer",
                "description": "Batas maksimal jumlah aplikasi yang ditampilkan pada 'list_apps' (default: 30).",
                "default": 30,
            },
        },
        "required": ["action"],
    }

    async def execute(self, context: ToolContext, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action", "").lower().strip()

        if context.on_status_update:
            await context.on_status_update(f"● package_manager · {action}")

        # -------------------------------------------------------------------
        # 1. Action: LIST_APPS
        # -------------------------------------------------------------------
        if action == "list_apps":
            ftype = kwargs.get("filter_type", "3rd_party").lower()
            query = kwargs.get("search_query", "").lower().strip()
            limit = kwargs.get("limit", 30)

            flags = []
            if ftype == "3rd_party":
                flags.append("-3")
            elif ftype == "system":
                flags.append("-s")
            elif ftype == "enabled":
                flags.append("-e")
            elif ftype == "disabled":
                flags.append("-d")

            cmd = f"pm list packages {' '.join(flags)}".strip()
            res = await bridge.execute_shell(cmd)

            if res.success and res.stdout:
                raw_pkgs = [
                    line.replace("package:", "").strip()
                    for line in res.stdout.splitlines()
                    if line.strip()
                ]

                if query:
                    raw_pkgs = [p for p in raw_pkgs if query in p.lower()]

                total = len(raw_pkgs)
                display_pkgs = raw_pkgs[:limit]

                lines = [
                    f"Daftar Aplikasi Android ({ftype}):",
                    f"• Total Ditemukan: {total} aplikasi" + (f" (menampilkan {limit} teratas)" if total > limit else ""),
                    "",
                ]
                for p in display_pkgs:
                    lines.append(f"• {p}")

                return ToolResult(success=True, output="\n".join(lines))
            return ToolResult(success=True, output="Tidak ada aplikasi ditemukan dengan filter tersebut.")

        # -------------------------------------------------------------------
        # 2. Action: OPEN_APP
        # -------------------------------------------------------------------
        elif action == "open_app":
            target = kwargs.get("package_name", "").strip()
            if not target:
                return ToolResult(success=False, output="", error="Parameter 'package_name' wajib diisi.")

            # Map alias if available
            pkg = APP_ALIASES.get(target.lower(), target)

            # Try monkey launch
            cmd = f"monkey -p {shlex.quote(pkg)} -c android.intent.category.LAUNCHER 1"
            res = await bridge.execute_shell(cmd)

            if res.success and "No activities found to run" not in res.stdout:
                return ToolResult(
                    success=True,
                    output=f"Aplikasi '{pkg}' berhasil diluncurkan ke layar.",
                )

            # Fallback 1: am start
            res_am = await bridge.execute_shell(
                f"am start -n $(cmd package resolve-activity --brief {shlex.quote(pkg)} | tail -n 1) || am start -a android.intent.action.MAIN -c android.intent.category.LAUNCHER -p {shlex.quote(pkg)}"
            )
            if res_am.success and "Error" not in res_am.stdout:
                return ToolResult(
                    success=True,
                    output=f"Aplikasi '{pkg}' berhasil diluncurkan via Activity Manager.",
                )

            # Fallback 2: Search installed packages matching target name
            search_res = await bridge.execute_shell(f"pm list packages | grep -i {shlex.quote(target)} | head -n 1")
            if search_res.success and search_res.stdout.strip():
                resolved_pkg = search_res.stdout.strip().replace("package:", "")
                res_retry = await bridge.execute_shell(f"monkey -p {shlex.quote(resolved_pkg)} -c android.intent.category.LAUNCHER 1")
                if res_retry.success:
                    return ToolResult(
                        success=True,
                        output=f"Aplikasi '{target}' ditemukan sebagai '{resolved_pkg}' dan berhasil diluncurkan.",
                    )

            return ToolResult(
                success=False,
                output="",
                error=f"Aplikasi '{target}' tidak ditemukan atau tidak memiliki antarmuka peluncur (Launcher Activity).",
            )

        # -------------------------------------------------------------------
        # 3. Action: APP_INFO
        # -------------------------------------------------------------------
        elif action == "app_info":
            target = kwargs.get("package_name", "").strip()
            if not target:
                return ToolResult(success=False, output="", error="Parameter 'package_name' wajib diisi.")

            pkg = APP_ALIASES.get(target.lower(), target)

            res_path = await bridge.execute_shell(f"pm path {shlex.quote(pkg)}")
            if not res_path.success or not res_path.stdout.strip():
                return ToolResult(success=False, output="", error=f"Aplikasi '{pkg}' tidak terpasang di perangkat.")

            apk_path = res_path.stdout.strip().replace("package:", "")

            res_dump = await bridge.execute_shell(
                f"dumpsys package {shlex.quote(pkg)} | grep -E 'versionName|versionCode|targetSdk|firstInstallTime|lastUpdateTime|userId|dataDir'"
            )

            lines = [
                f"Informasi Detail Aplikasi: {pkg}",
                f"• Lokasi APK: {apk_path}",
            ]

            if res_dump.success and res_dump.stdout:
                for dline in res_dump.stdout.splitlines():
                    cleaned = dline.strip()
                    if cleaned:
                        lines.append(f"• {cleaned}")

            return ToolResult(success=True, output="\n".join(lines))

        # -------------------------------------------------------------------
        # 4. Action: CURRENT_APP (Focused Activity on Screen)
        # -------------------------------------------------------------------
        elif action == "current_app":
            res = await bridge.execute_shell(
                "dumpsys window | grep -E 'mCurrentFocus|mFocusedApp|mFocusedWindow' || dumpsys activity activities | grep -E 'mResumedActivity'",
                as_root=bridge.is_root_available(),
            )
            if res.success and res.stdout.strip():
                matches = re.findall(r"([a-zA-Z0-9_\.]+\/[a-zA-Z0-9_\.]+)", res.stdout)
                if matches:
                    comp = matches[0]
                    pkg, act = comp.split("/", 1)
                    return ToolResult(
                        success=True,
                        output=f"Aplikasi yang Sedang Aktif di Layar:\n• Paket: {pkg}\n• Activity: {act}",
                    )
                return ToolResult(success=True, output=f"Fokus Layar Saat Ini:\n{res.stdout.strip()}")
            return ToolResult(success=True, output="Tidak dapat mendeteksi fokus aplikasi layar.")

        # -------------------------------------------------------------------
        # 5. Action: FORCE_STOP
        # -------------------------------------------------------------------
        elif action == "force_stop":
            target = kwargs.get("package_name", "").strip()
            if not target:
                return ToolResult(success=False, output="", error="Parameter 'package_name' wajib diisi.")

            pkg = APP_ALIASES.get(target.lower(), target)
            res = await bridge.execute_shell(f"am force-stop {shlex.quote(pkg)}", as_root=bridge.is_root_available())
            return ToolResult(
                success=True,
                output=f"Aplikasi '{pkg}' berhasil dihentikan paksa (force stop).",
            )

        # -------------------------------------------------------------------
        # 6. Action: ENABLE_APP
        # -------------------------------------------------------------------
        elif action == "enable_app":
            target = kwargs.get("package_name", "").strip()
            if not target:
                return ToolResult(success=False, output="", error="Parameter 'package_name' wajib diisi.")

            pkg = APP_ALIASES.get(target.lower(), target)
            res = await bridge.execute_shell(f"pm enable {shlex.quote(pkg)}", as_root=True)
            if res.success:
                return ToolResult(success=True, output=f"Aplikasi '{pkg}' berhasil diaktifkan kembali.")
            return ToolResult(success=False, output="", error=f"Gagal mengaktifkan aplikasi: {res.stderr or 'Izin root diperlukan'}")

        # -------------------------------------------------------------------
        # 7. Action: DISABLE_APP
        # -------------------------------------------------------------------
        elif action == "disable_app":
            target = kwargs.get("package_name", "").strip()
            if not target:
                return ToolResult(success=False, output="", error="Parameter 'package_name' wajib diisi.")

            pkg = APP_ALIASES.get(target.lower(), target)
            res = await bridge.execute_shell(f"pm disable-user --user 0 {shlex.quote(pkg)}", as_root=True)
            if res.success:
                return ToolResult(success=True, output=f"Aplikasi '{pkg}' berhasil dinonaktifkan (freeze/disabled).")
            return ToolResult(success=False, output="", error=f"Gagal menonaktifkan aplikasi: {res.stderr or 'Izin root diperlukan'}")

        # -------------------------------------------------------------------
        # 8. Action: CLEAR_DATA (Destructive Guard Intercepted)
        # -------------------------------------------------------------------
        elif action == "clear_data":
            target = kwargs.get("package_name", "").strip()
            if not target:
                return ToolResult(success=False, output="", error="Parameter 'package_name' wajib diisi.")

            pkg = APP_ALIASES.get(target.lower(), target)

            # Destructive confirmation
            if context.on_request_confirmation:
                title = "⚠️ Konfirmasi Hapus Data Aplikasi (pm clear)"
                details = (
                    f"Apakah Anda yakin ingin menghapus seluruh data dan cache aplikasi berikut?\n"
                    f"• Paket: {pkg}\n"
                    f"• Tindakan: Seluruh sesi login, database, dan cache aplikasi akan terhapus permanen."
                )
                approved = await context.on_request_confirmation(title, details)
                if not approved:
                    return ToolResult(
                        success=False,
                        output="",
                        error=f"Pembersihan data aplikasi '{pkg}' dibatalkan oleh pengguna atau waktu habis.",
                    )
            else:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Operasi 'clear_data' pada '{pkg}' memerlukan konfirmasi manual pengguna.",
                )

            res = await bridge.execute_shell(f"pm clear {shlex.quote(pkg)}", as_root=bridge.is_root_available())
            if res.success:
                return ToolResult(success=True, output=f"Seluruh data dan cache aplikasi '{pkg}' berhasil dibersihkan.")
            return ToolResult(success=False, output="", error=f"Gagal membersihkan data aplikasi: {res.stderr}")

        # -------------------------------------------------------------------
        # 9. Action: UNINSTALL (Destructive Guard Intercepted)
        # -------------------------------------------------------------------
        elif action == "uninstall":
            target = kwargs.get("package_name", "").strip()
            if not target:
                return ToolResult(success=False, output="", error="Parameter 'package_name' wajib diisi.")

            pkg = APP_ALIASES.get(target.lower(), target)

            if context.on_request_confirmation:
                title = "⚠️ Konfirmasi Pencopotan Aplikasi (Uninstall)"
                details = (
                    f"Apakah Anda yakin ingin mencopot pemasangan aplikasi berikut dari HP?\n"
                    f"• Paket: {pkg}\n"
                    f"• Tindakan: Aplikasi akan dihapus dari sistem Android."
                )
                approved = await context.on_request_confirmation(title, details)
                if not approved:
                    return ToolResult(
                        success=False,
                        output="",
                        error=f"Pencopotan aplikasi '{pkg}' dibatalkan oleh pengguna atau waktu habis.",
                    )
            else:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Pencopotan aplikasi '{pkg}' memerlukan konfirmasi manual pengguna.",
                )

            res = await bridge.execute_shell(f"pm uninstall {shlex.quote(pkg)}", as_root=bridge.is_root_available())
            if res.success:
                return ToolResult(success=True, output=f"Aplikasi '{pkg}' berhasil dicopot pemasangannya dari sistem.")
            return ToolResult(success=False, output="", error=f"Gagal mencopot aplikasi: {res.stderr}")

        return ToolResult(success=False, output="", error=f"Aksi package_manager '{action}' tidak dikenal.")
