from __future__ import annotations

import importlib.util
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Callable, Any

logger = logging.getLogger("faf_agent.diagnostics")


@dataclass
class ToolDependency:
    """Definisi dependensi sistem atau pustaka untuk faf-agent."""

    id: str
    name: str
    tool_affected: str
    category: str
    check_fn: Callable[[], tuple[bool, str]]
    install_command: str
    is_critical: bool = False
    description: str = ""


@dataclass
class DependencyResult:
    """Hasil pemeriksaan status dependensi."""

    id: str
    name: str
    tool_affected: str
    category: str
    installed: bool
    detail: str
    install_command: str
    is_critical: bool
    description: str


def _check_binary(bin_names: list[str], version_cmd: str | None = None) -> tuple[bool, str]:
    """Cek keberadaan binary di PATH atau direktori standar Termux."""
    termux_prefix = os.environ.get("PREFIX", "/data/data/com.termux/files/usr")
    termux_bin_dir = f"{termux_prefix}/bin"

    found_path: str | None = None
    for name in bin_names:
        p = shutil.which(name)
        if p:
            found_path = p
            break
        custom_p = os.path.join(termux_bin_dir, name)
        if os.path.exists(custom_p) and os.access(custom_p, os.X_OK):
            found_path = custom_p
            break

    if not found_path:
        return False, "Binary tidak ditemukan di PATH sistem"

    if version_cmd:
        try:
            res = subprocess.run(
                version_cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=2,
            )
            out = (res.stdout or res.stderr or "").strip().splitlines()
            ver_text = out[0] if out else "Terpasang"
            return True, f"{ver_text} ({found_path})"
        except Exception:
            pass

    return True, f"Terpasang ({found_path})"


def _check_python_pkg(package_name: str, import_name: str) -> tuple[bool, str]:
    """Cek keberadaan pustaka Python."""
    try:
        spec = importlib.util.find_spec(import_name)
        if spec is not None:
            try:
                mod = importlib.import_module(import_name)
                ver = getattr(mod, "__version__", "Terpasang")
                return True, f"v{ver}"
            except Exception:
                return True, "Terpasang"
    except Exception:
        pass
    return False, f"Modul Python '{import_name}' belum terpasang"


def _check_file_exists(file_paths: list[str]) -> tuple[bool, str]:
    """Cek keberadaan berkas tertentu pada sistem."""
    for p in file_paths:
        expanded = os.path.expanduser(os.path.expandvars(p))
        if os.path.exists(expanded):
            size_kb = os.path.getsize(expanded) / 1024
            return True, f"Ditemukan ({expanded}, {size_kb:.1f} KB)"
    return False, "Berkas tidak ditemukan"


def _check_su_root() -> tuple[bool, str]:
    """Cek ketersediaan hak akses Root / Superuser."""
    su_paths = [
        "/system/bin/su",
        "/system/xbin/su",
        "/sbin/su",
        "/su/bin/su",
        "/data/local/xbin/su",
        "/data/local/bin/su",
    ]
    termux_prefix = os.environ.get("PREFIX", "/data/data/com.termux/files/usr")
    tsu_path = f"{termux_prefix}/bin/tsu"

    if shutil.which("tsu") or (os.path.exists(tsu_path) and os.access(tsu_path, os.X_OK)):
        return True, "tsu (Termux su) terpasang"

    if shutil.which("su"):
        return True, "su binary ditemukan di PATH"

    for p in su_paths:
        if os.path.exists(p):
            return True, f"su binary ditemukan di {p}"

    return False, "Perangkat belum di-root atau binary su/tsu tidak terpasang"


# Daftar dependensi lengkap yang dibutuhkan seluruh tools faf-agent
DEPENDENCY_REGISTRY: list[ToolDependency] = [
    # 1. Termux API (System, Media, Productivity)
    ToolDependency(
        id="termux_api",
        name="termux-api",
        tool_affected="system_settings, productivity_control, media_control",
        category="Termux API",
        check_fn=lambda: _check_binary(["termux-battery-status", "termux-torch", "termux-toast"]),
        install_command="pkg install termux-api -y",
        is_critical=True,
        description="Jembatan kontrol hardware Android (senter, baterai, kamera, sensor, clipboard, kontak, notifikasi)",
    ),
    # 2. Superuser & Root
    ToolDependency(
        id="tsu",
        name="tsu (Root Superuser)",
        tool_affected="root_shell_exec, system_settings (opsi root)",
        category="Superuser / Root",
        check_fn=_check_su_root,
        install_command="pkg install tsu -y",
        is_critical=False,
        description="Eksekusi perintah shell tingkat tinggi dengan wewenang Superuser (root)",
    ),
    # 3. Media Downloader: yt-dlp
    ToolDependency(
        id="yt_dlp",
        name="yt-dlp",
        tool_affected="media_downloader",
        category="Media & Unduhan",
        check_fn=lambda: _check_binary(["yt-dlp"], "yt-dlp --version"),
        install_command="pkg install yt-dlp -y (atau: pip install yt-dlp)",
        is_critical=False,
        description="Pengunduh dan pengekstraksi video/audio YouTube, TikTok, IG, FB, X, SoundCloud",
    ),
    # 4. Media Downloader: aria2c
    ToolDependency(
        id="aria2c",
        name="aria2c (aria2)",
        tool_affected="media_downloader",
        category="Media & Unduhan",
        check_fn=lambda: _check_binary(["aria2c"], "aria2c --version"),
        install_command="pkg install aria2 -y",
        is_critical=False,
        description="Mesin akselerasi multi-koneksi unduh berkas cepat dan torrent/magnet",
    ),
    # 5. Media Downloader & Media Control: ffmpeg
    ToolDependency(
        id="ffmpeg",
        name="ffmpeg",
        tool_affected="media_downloader, media_control",
        category="Media & Unduhan",
        check_fn=lambda: _check_binary(["ffmpeg"], "ffmpeg -version"),
        install_command="pkg install ffmpeg -y",
        is_critical=False,
        description="Pengekstrak audio MP3, pemotong media, dan konversi format video",
    ),
    # 6. cURL & Wget
    ToolDependency(
        id="curl",
        name="curl",
        tool_affected="media_downloader, system_settings",
        category="Media & Unduhan",
        check_fn=lambda: _check_binary(["curl"], "curl --version"),
        install_command="pkg install curl -y",
        is_critical=False,
        description="Pengunduh berkas HTTP/HTTPS langsung via shell",
    ),
    ToolDependency(
        id="wget",
        name="wget",
        tool_affected="media_downloader",
        category="Media & Unduhan",
        check_fn=lambda: _check_binary(["wget"], "wget --version"),
        install_command="pkg install wget -y",
        is_critical=False,
        description="Pengunduh berkas web alternatif",
    ),
    # 7. OCR: Tesseract
    ToolDependency(
        id="tesseract",
        name="tesseract (OCR Engine)",
        tool_affected="ocr_extract",
        category="Optical Character Recognition (OCR)",
        check_fn=lambda: _check_binary(["tesseract"], "tesseract --version"),
        install_command="pkg install tesseract -y",
        is_critical=False,
        description="Mesin ekstraksi teks dari gambar, tangkapan layar, dan dokumen secara offline",
    ),
    # 8. OCR: Indonesian Language Data
    ToolDependency(
        id="ind_traineddata",
        name="ind.traineddata (Bahasa Indonesia OCR)",
        tool_affected="ocr_extract",
        category="Optical Character Recognition (OCR)",
        check_fn=lambda: _check_file_exists([
            "$PREFIX/share/tessdata/ind.traineddata",
            "/data/data/com.termux/files/usr/share/tessdata/ind.traineddata",
            "/usr/share/tessdata/ind.traineddata",
            "/usr/local/share/tessdata/ind.traineddata",
            "/opt/homebrew/share/tessdata/ind.traineddata",
        ]),
        install_command=(
            "curl -L -o $PREFIX/share/tessdata/ind.traineddata "
            "https://github.com/tesseract-ocr/tessdata_fast/raw/main/ind.traineddata"
        ),
        is_critical=False,
        description="Dataset model bahasa Indonesia untuk akurasi pengenalan teks Tesseract",
    ),
    # 9. Web Screenshot & Browser Agent: Chromium
    ToolDependency(
        id="chromium",
        name="chromium (Headless Web Browser)",
        tool_affected="web_screenshot, browser_agent",
        category="Web & Browser",
        check_fn=lambda: _check_binary(["chromium", "chromium-browser", "chrome"], "chromium --version"),
        install_command="pkg install x11-repo -y && pkg install chromium -y",
        is_critical=False,
        description="Browser headless untuk web_screenshot & interaktif browser_agent (CDP, SPA, PDF)",
    ),
    # 10. Android Native CLI (pm, am, input, monkey)
    ToolDependency(
        id="android_native",
        name="Android Native Tools (pm, am, input)",
        tool_affected="package_manager, device_interaction, productivity_control",
        category="Android Framework",
        check_fn=lambda: _check_binary(["pm", "am", "input"]),
        install_command="Bawaan sistem Android (otomatis ada pada Android fisik)",
        is_critical=True,
        description="Manajemen paket aplikasi, peluncuran intent, dan otomasi input sentuh/tombol",
    ),
    # 11. Python Libraries
    ToolDependency(
        id="python_telegram_bot",
        name="python-telegram-bot",
        tool_affected="bot core",
        category="Pustaka Python",
        check_fn=lambda: _check_python_pkg("python-telegram-bot", "telegram"),
        install_command="pip install python-telegram-bot",
        is_critical=True,
        description="Framework bot Telegram asinkron",
    ),
    ToolDependency(
        id="httpx",
        name="httpx",
        tool_affected="ai_client, web_search, reminder_mgr",
        category="Pustaka Python",
        check_fn=lambda: _check_python_pkg("httpx", "httpx"),
        install_command="pip install httpx",
        is_critical=True,
        description="HTTP client asinkron untuk komunikasi LLM API dan web scraping",
    ),
    ToolDependency(
        id="python_dotenv",
        name="python-dotenv",
        tool_affected="config",
        category="Pustaka Python",
        check_fn=lambda: _check_python_pkg("python-dotenv", "dotenv"),
        install_command="pip install python-dotenv",
        is_critical=True,
        description="Pemuat variabel lingkungan dari berkas .env",
    ),
]


def check_all_dependencies() -> list[DependencyResult]:
    """Periksa status seluruh dependensi yang dibutuhkan oleh faf-agent."""
    results: list[DependencyResult] = []
    for dep in DEPENDENCY_REGISTRY:
        try:
            installed, detail = dep.check_fn()
        except Exception as e:
            installed = False
            detail = f"Pemeriksaan error: {str(e)}"

        results.append(
            DependencyResult(
                id=dep.id,
                name=dep.name,
                tool_affected=dep.tool_affected,
                category=dep.category,
                installed=installed,
                detail=detail,
                install_command=dep.install_command,
                is_critical=dep.is_critical,
                description=dep.description,
            )
        )
    return results


def check_single_dependency(dep_id: str) -> DependencyResult | None:
    """Periksa satu dependensi tertentu berdasarkan ID."""
    for dep in DEPENDENCY_REGISTRY:
        if dep.id == dep_id:
            installed, detail = dep.check_fn()
            return DependencyResult(
                id=dep.id,
                name=dep.name,
                tool_affected=dep.tool_affected,
                category=dep.category,
                installed=installed,
                detail=detail,
                install_command=dep.install_command,
                is_critical=dep.is_critical,
                description=dep.description,
            )
    return None


def get_missing_dependencies() -> list[DependencyResult]:
    """Ambil daftar dependensi yang belum terpasang."""
    all_res = check_all_dependencies()
    return [r for r in all_res if not r.installed]


def format_dependency_report(results: list[DependencyResult] | None = None) -> str:
    """Susun laporan status instalasi tools dalam format teks bersih dan nyaman dibaca.

    Secara eksplisit mencantumkan kalimat '[Nama] sudah di install' atau '[Nama] belum di install'.
    """
    if results is None:
        results = check_all_dependencies()

    installed_list = [r for r in results if r.installed]
    missing_list = [r for r in results if not r.installed]

    lines: list[str] = [
        "Status Pemeriksaan Instalasi Tools & Dependensi faf-agent:",
        f"• Total Diperiksa: {len(results)} komponen",
        f"• Sudah Terinstall: {len(installed_list)}",
        f"• Belum Diinstall: {len(missing_list)}",
        "",
    ]

    # 1. Tampilkan daftar yang BELUM diinstall terlebih dahulu (prioritas utama)
    if missing_list:
        lines.append("Komponen yang BELUM di-install:")
        for r in missing_list:
            crit_mark = " (Wajib/Kritis)" if r.is_critical else ""
            lines.append(f"• {r.name} belum di install{crit_mark}")
            lines.append(f"  Tool Terkait: {r.tool_affected}")
            lines.append(f"  Cara Install: {r.install_command}")
        lines.append("")
    else:
        lines.append("Semua komponen dan tools telah terinstall dengan lengkap!")
        lines.append("")

    # 2. Tampilkan daftar yang SUDAH diinstall
    if installed_list:
        lines.append("Komponen yang SUDAH di-install:")
        for r in installed_list:
            lines.append(f"• {r.name} sudah di install")
            lines.append(f"  Status: {r.detail}")
        lines.append("")

    # 3. Berikan perintah ringkas satu baris untuk instalasi sekaligus di Termux
    pkg_missing: list[str] = []
    pip_missing: list[str] = []
    special_missing: list[str] = []

    for r in missing_list:
        cmd = r.install_command
        if "pkg install" in cmd:
            # Ekstrak nama paket jika memungkinkan
            if r.id == "termux_api":
                pkg_missing.append("termux-api")
            elif r.id == "tsu":
                pkg_missing.append("tsu")
            elif r.id == "yt_dlp":
                pkg_missing.append("yt-dlp")
            elif r.id == "aria2c":
                pkg_missing.append("aria2")
            elif r.id == "ffmpeg":
                pkg_missing.append("ffmpeg")
            elif r.id == "curl":
                pkg_missing.append("curl")
            elif r.id == "wget":
                pkg_missing.append("wget")
            elif r.id == "tesseract":
                pkg_missing.append("tesseract")
            elif r.id == "chromium":
                special_missing.append("pkg install x11-repo -y && pkg install chromium -y")
        elif "pip install" in cmd:
            if r.id == "yt_dlp":
                pip_missing.append("yt-dlp")
            elif r.id in ("python_telegram_bot", "httpx", "python_dotenv"):
                pip_missing.append(cmd.replace("pip install ", "").strip())
        elif "curl" in cmd and r.id == "ind_traineddata":
            special_missing.append(cmd)

    if pkg_missing or pip_missing or special_missing:
        lines.append("Perintah cepat untuk menginstall di Termux:")
        if pkg_missing:
            lines.append(f"pkg update && pkg install {' '.join(pkg_missing)} -y")
        if pip_missing:
            lines.append(f"pip install {' '.join(pip_missing)}")
        for sc in special_missing:
            lines.append(sc)

    return "\n".join(lines).strip()
