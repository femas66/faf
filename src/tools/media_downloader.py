from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import shlex
import shutil
import tempfile
import time
import urllib.parse
import urllib.request
from typing import Any

from src.config import get_settings
from src.core.android_bridge import bridge
from src.tools.base import BaseTool, ToolContext, ToolResult

logger = logging.getLogger("faf_agent.tools.media_downloader")

# Telegram Bot API upload limit is 50 MB
TELEGRAM_MAX_UPLOAD_BYTES = 50 * 1024 * 1024

# Social media and stream video/audio domains suitable for yt-dlp
STREAM_DOMAINS = [
    "youtube.com",
    "youtu.be",
    "tiktok.com",
    "instagram.com",
    "twitter.com",
    "x.com",
    "facebook.com",
    "fb.watch",
    "soundcloud.com",
    "reddit.com",
    "vimeo.com",
    "twitch.tv",
    "dailymotion.com",
    "pinterest.com",
]


def _format_size(size_bytes: int) -> str:
    """Format bytes into human-readable size."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.2f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.2f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def _format_duration(seconds: float | int | None) -> str:
    """Format seconds into HH:MM:SS or MM:SS."""
    if not seconds or seconds < 0:
        return "Tidak diketahui"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _compute_sha256(filepath: str) -> str:
    """Compute SHA-256 checksum of a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def _get_installed_engines() -> dict[str, str | None]:
    """Detect available CLI download and media tools."""
    engines = ["yt-dlp", "aria2c", "ffmpeg", "curl", "wget"]
    res: dict[str, str | None] = {}
    for eng in engines:
        p = shutil.which(eng)
        if not p:
            termux_p = f"/data/data/com.termux/files/usr/bin/{eng}"
            if os.path.exists(termux_p) and os.access(termux_p, os.X_OK):
                p = termux_p
        res[eng] = p
    return res


def _resolve_download_dir(custom_dir: str | None = None) -> str:
    """Resolve a writable download directory on Android / Termux / Linux."""
    candidates: list[str] = []
    if custom_dir:
        candidates.append(os.path.abspath(custom_dir))

    candidates.extend([
        "/sdcard/Download",
        "/storage/emulated/0/Download",
        "/sdcard",
        os.path.expanduser("~/downloads"),
        os.path.join(tempfile.gettempdir(), "faf_downloads"),
    ])

    for c in candidates:
        try:
            os.makedirs(c, exist_ok=True)
            test_f = os.path.join(c, f".write_test_{int(time.time())}")
            with open(test_f, "w") as f:
                f.write("ok")
            os.remove(test_f)
            return c
        except Exception:
            continue

    fallback = os.path.join(tempfile.gettempdir(), "faf_downloads")
    os.makedirs(fallback, exist_ok=True)
    return fallback


def _is_stream_url(url: str) -> bool:
    """Check if URL points to a stream / social media site handled by yt-dlp."""
    u_lower = url.lower()
    return any(d in u_lower for d in STREAM_DOMAINS)


def _sanitize_filename(name: str) -> str:
    """Sanitize filename removing problematic characters."""
    clean = re.sub(r'[\\/*?:"<>|]', "_", name)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean or f"download_{int(time.time())}"


class MediaDownloaderTool(BaseTool):
    """Complex multi-engine media and file downloader for Android Termux.

    Supports direct downloads, social media/video extraction (yt-dlp),
    multi-connection acceleration (aria2c), audio extraction, metadata inspection,
    torrent/magnet, and automatic Telegram dispatch.
    """

    name = "media_downloader"
    description = (
        "Tool pengunduh media dan berkas serbaguna tingkat lanjut (multi-engine downloader). "
        "Mendukung pengunduhan berkas langsung (HTTP/HTTPS via aria2c/curl/wget/Python native dengan akselerasi multi-thread), "
        "ekstraksi video dan audio media sosial (YouTube, TikTok, Instagram, Twitter/X, SoundCloud, dll. via yt-dlp), "
        "konversi/ekstraksi MP3 audio, inspeksi metadata URL sebelum mengunduh (info judul, durasi, ukuran), "
        "unduhan batch banyak tautan sekaligus, unduhan torrent/magnet, serta riwayat berkas unduhan di Android (/sdcard/Download). "
        "Berkas berukuran <= 50MB otomatis dikirimkan langsung ke Telegram pengguna."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "download",
                    "extract_audio",
                    "info",
                    "batch_download",
                    "torrent_magnet",
                    "list_downloads",
                    "check_environment",
                ],
                "description": (
                    "Aksi yang diinginkan: 'download' (unduh berkas langsung atau video media sosial), "
                    "'extract_audio' (unduh dan ekstrak audio sebagai MP3/M4A), "
                    "'info' (inspeksi metadata URL tanpa mengunduh), "
                    "'batch_download' (unduh banyak tautan sekaligus), "
                    "'torrent_magnet' (unduh tautan magnet atau file torrent via aria2c), "
                    "'list_downloads' (lihat berkas yang baru diunduh di perangkat), "
                    "'check_environment' (cek kesiapan engine yt-dlp, aria2c, ffmpeg, curl di Termux)."
                ),
                "default": "download",
            },
            "url": {
                "type": "string",
                "description": "Tautan URL web, video, audio, berkas langsung, atau Magnet URI yang ingin diunduh/diinspeksi.",
            },
            "urls": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Daftar beberapa URL sekaligus untuk aksi 'batch_download'.",
            },
            "format": {
                "type": "string",
                "enum": ["best", "1080p", "720p", "480p", "360p", "mp3", "m4a", "opus"],
                "description": "Format atau kualitas yang diinginkan (default: 'best'). Gunakan 'mp3' untuk musik.",
                "default": "best",
            },
            "output_dir": {
                "type": "string",
                "description": "Direktori penyimpanan di perangkat (default: '/sdcard/Download').",
            },
            "filename": {
                "type": "string",
                "description": "Nama kustom untuk berkas unduhan (opsional, jika kosong otomatis ditentukan dari URL).",
            },
            "send_to_telegram": {
                "type": "boolean",
                "description": "Kirimkan berkas ke obrolan Telegram jika ukurannya <= 50MB (default: True).",
                "default": True,
            },
            "accelerated": {
                "type": "boolean",
                "description": "Gunakan akselerasi multi-connection via aria2c jika tersedia (default: True).",
                "default": True,
            },
            "max_connections": {
                "type": "integer",
                "description": "Jumlah koneksi split simultan untuk aria2c (1-16, default: 8).",
                "default": 8,
            },
            "timeout_seconds": {
                "type": "integer",
                "description": "Batas waktu pengunduhan dalam detik (default: 180 detik).",
                "default": 180,
            },
        },
        "required": [],
    }

    async def execute(self, context: ToolContext, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action", "download").lower().strip()

        # -------------------------------------------------------------------
        # 1. Action: CHECK_ENVIRONMENT
        # -------------------------------------------------------------------
        if action == "check_environment":
            return await self._action_check_environment()

        # -------------------------------------------------------------------
        # 2. Action: LIST_DOWNLOADS
        # -------------------------------------------------------------------
        if action == "list_downloads":
            target_dir = _resolve_download_dir(kwargs.get("output_dir"))
            return await self._action_list_downloads(target_dir)

        # -------------------------------------------------------------------
        # 3. Action: INFO (Inspect URL without downloading)
        # -------------------------------------------------------------------
        if action == "info":
            url = kwargs.get("url", "").strip()
            if not url:
                return ToolResult(success=False, output="", error="Parameter 'url' wajib disertakan untuk aksi 'info'.")
            return await self._action_info(url, context)

        # -------------------------------------------------------------------
        # 4. Action: TORRENT_MAGNET
        # -------------------------------------------------------------------
        if action == "torrent_magnet":
            url = kwargs.get("url", "").strip()
            if not url:
                return ToolResult(success=False, output="", error="Parameter 'url' (Magnet URI atau file .torrent) wajib disertakan.")
            return await self._action_torrent(url, context, kwargs)

        # -------------------------------------------------------------------
        # 5. Action: BATCH_DOWNLOAD
        # -------------------------------------------------------------------
        if action == "batch_download":
            urls = kwargs.get("urls") or []
            if not urls and kwargs.get("url"):
                urls = [kwargs.get("url")]
            if not urls:
                return ToolResult(success=False, output="", error="Daftar parameter 'urls' wajib disertakan untuk batch download.")
            return await self._action_batch_download(urls, context, kwargs)

        # -------------------------------------------------------------------
        # 6. Action: EXTRACT_AUDIO
        # -------------------------------------------------------------------
        if action == "extract_audio":
            kwargs["format"] = kwargs.get("format") or "mp3"
            return await self._action_download(context, kwargs, is_audio_only=True)

        # -------------------------------------------------------------------
        # 7. Action: DOWNLOAD (Default)
        # -------------------------------------------------------------------
        return await self._action_download(context, kwargs, is_audio_only=False)

    # =======================================================================
    # Internal Action Handlers
    # =======================================================================

    async def _action_check_environment(self) -> ToolResult:
        """Diagnose installed download tools on Termux/system."""
        engines = _get_installed_engines()
        status_lines: list[str] = ["Status Mesin Unduh & Ekstraksi Media:\n"]

        all_ready = True
        for eng, path in engines.items():
            if path:
                # Get version if possible
                ver_res = await bridge.execute_shell(f"{shlex.quote(path)} --version", timeout=4)
                first_line = ver_res.stdout.splitlines()[0] if ver_res.stdout else "Terpasang"
                status_lines.append(f"• {eng}: {path} ({first_line[:40]})")
            else:
                status_lines.append(f"• {eng}: Belum terpasang")
                if eng in ("yt-dlp", "aria2c", "ffmpeg"):
                    all_ready = False

        if not all_ready:
            status_lines.append("\nRekomendasi Perintah Instalasi di Termux:")
            status_lines.append("pkg update && pkg install aria2 ffmpeg curl wget")
            status_lines.append("pkg install python-pip && pip install -U yt-dlp")
        else:
            status_lines.append("\nSemua komponen utama pengunduhan telah lengkap dan siap digunakan.")

        return ToolResult(success=True, output="\n".join(status_lines))

    async def _action_list_downloads(self, target_dir: str) -> ToolResult:
        """List recently downloaded files in the target directory."""
        if not os.path.exists(target_dir):
            return ToolResult(success=False, output="", error=f"Direktori '{target_dir}' tidak ditemukan.")

        try:
            entries = []
            for fname in os.listdir(target_dir):
                if fname.startswith("."):
                    continue
                fpath = os.path.join(target_dir, fname)
                if os.path.isfile(fpath):
                    st = os.stat(fpath)
                    entries.append((st.st_mtime, fpath, fname, st.st_size))

            entries.sort(key=lambda x: x[0], reverse=True)
            top_entries = entries[:15]

            if not top_entries:
                return ToolResult(
                    success=True,
                    output=f"Daftar Unduhan di {target_dir}:\n(Belum ada berkas unduhan di folder ini.)",
                )

            lines = [f"Daftar Berkas Unduhan Terbaru ({target_dir}):\n"]
            for mtime, fpath, fname, size in top_entries:
                time_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime))
                lines.append(f"• {fname}\n  Ukuran: {_format_size(size)} | Tanggal: {time_str}")

            return ToolResult(success=True, output="\n".join(lines))
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Gagal membaca direktori unduhan: {e}")

    async def _action_info(self, url: str, context: ToolContext) -> ToolResult:
        """Inspect media or direct file metadata without downloading."""
        if context.on_status_update:
            await context.on_status_update(f"● media_downloader · memeriksa info {url[:40]}...")

        engines = _get_installed_engines()

        # If it's a stream URL and yt-dlp is installed, inspect with yt-dlp
        if _is_stream_url(url) and engines.get("yt-dlp"):
            yt_path = engines["yt-dlp"]
            cmd = f"{shlex.quote(yt_path)} --dump-single-json --no-playlist {shlex.quote(url)}"
            res = await bridge.execute_shell(cmd, timeout=30)
            if res.success and res.stdout.strip():
                try:
                    data = json.loads(res.stdout)
                    title = data.get("title", "Tidak ada judul")
                    duration = _format_duration(data.get("duration"))
                    uploader = data.get("uploader") or data.get("channel") or "Tidak diketahui"
                    views = data.get("view_count", "N/A")
                    formats = data.get("formats", [])
                    max_height = max([f.get("height") or 0 for f in formats], default=0)

                    out = (
                        f"Informasi Media Stream (yt-dlp):\n\n"
                        f"• Judul: {title}\n"
                        f"• Saluran / Uploader: {uploader}\n"
                        f"• Durasi: {duration}\n"
                        f"• Resolusi Maksimal: {max_height}p\n"
                        f"• Jumlah Tayangan: {views:,}" if isinstance(views, int) else f"• Jumlah Tayangan: {views}\n"
                        f"• Sumber URL: {url}"
                    )
                    return ToolResult(success=True, output=out)
                except Exception:
                    pass

        # Direct HTTP/HTTPS HEAD Inspection
        try:
            req = urllib.request.Request(url, method="HEAD")
            req.add_header("User-Agent", "Mozilla/5.0 (Android; Mobile; rv:124.0) Gecko/124.0 Firefox/124.0")
            loop = asyncio.get_running_loop()

            def _do_head() -> dict[str, Any]:
                try:
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        headers = dict(resp.headers)
                        return {
                            "status": resp.status,
                            "content_type": headers.get("Content-Type", "Tidak diketahui"),
                            "content_length": int(headers.get("Content-Length", -1)),
                            "accept_ranges": headers.get("Accept-Ranges", "none"),
                            "content_disposition": headers.get("Content-Disposition", ""),
                        }
                except Exception as ex:
                    return {"error": str(ex)}

            head_info = await loop.run_in_executor(None, _do_head)
            if "error" in head_info:
                return ToolResult(success=False, output="", error=f"Gagal memeriksa URL {url}: {head_info['error']}")

            clen = head_info["content_length"]
            size_str = _format_size(clen) if clen > 0 else "Tidak diketahui (chunked/stream)"
            resumable = "Mendukung Resume (Range)" if head_info["accept_ranges"] == "bytes" else "Tidak mendukung resume"

            out = (
                f"Informasi Berkas Langsung (HTTP HEAD):\n\n"
                f"• URL: {url}\n"
                f"• Tipe Konten (MIME): {head_info['content_type']}\n"
                f"• Perkiraan Ukuran: {size_str}\n"
                f"• Fitur Unduh: {resumable}\n"
                f"• Status Server: {head_info['status']} OK"
            )
            return ToolResult(success=True, output=out)
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Gagal memeriksa URL: {e}")

    async def _action_torrent(self, magnet_url: str, context: ToolContext, kwargs: dict[str, Any]) -> ToolResult:
        """Download torrent or magnet link via aria2c."""
        engines = _get_installed_engines()
        aria_path = engines.get("aria2c")
        if not aria_path:
            return ToolResult(
                success=False,
                output="",
                error=(
                    "Engine aria2c belum terpasang di Termux.\n"
                    "Pasang aria2c untuk mendukung unduhan torrent/magnet:\n"
                    "pkg install aria2"
                ),
            )

        output_dir = _resolve_download_dir(kwargs.get("output_dir"))
        timeout = min(600, max(30, kwargs.get("timeout_seconds", 300)))

        if context.on_status_update:
            await context.on_status_update(f"● media_downloader · memulai unduhan torrent/magnet...")

        cmd = (
            f"{shlex.quote(aria_path)} --dir={shlex.quote(output_dir)} "
            f"--seed-time=0 --max-connection-per-server=8 "
            f"--bt-max-peers=50 --follow-torrent=mem {shlex.quote(magnet_url)}"
        )
        res = await bridge.execute_shell(cmd, timeout=timeout)
        if not res.success:
            return ToolResult(
                success=False,
                output="",
                error=f"Gagal mengunduh torrent/magnet: {res.stderr or res.stdout or 'Timeout/Error'}",
            )

        return ToolResult(
            success=True,
            output=(
                f"Unduhan Torrent / Magnet Selesai\n\n"
                f"• Target Direktori: {output_dir}\n"
                f"• Status: Berhasil diunduh ke penyimpanan perangkat."
            ),
        )

    async def _action_batch_download(
        self, urls: list[str], context: ToolContext, kwargs: dict[str, Any]
    ) -> ToolResult:
        """Download multiple URLs sequentially with progress tracking."""
        total = len(urls)
        success_list: list[str] = []
        fail_list: list[str] = []

        for idx, u in enumerate(urls, start=1):
            if context.cancel_event.is_set():
                break
            if context.on_status_update:
                await context.on_status_update(f"● media_downloader · mengunduh {idx}/{total}: {u[:35]}...")

            item_kwargs = dict(kwargs)
            item_kwargs["url"] = u
            item_kwargs["send_to_telegram"] = False  # Keep local during batch

            res = await self._action_download(context, item_kwargs, is_audio_only=False)
            if res.success:
                success_list.append(u)
            else:
                fail_list.append(f"{u} (Gagal: {res.error or 'error'})")

        out_lines = [
            f"Ringkasan Pengunduhan Batch ({len(success_list)}/{total} Berhasil):\n"
        ]
        if success_list:
            out_lines.append("• Berhasil Diunduh:")
            for s in success_list:
                out_lines.append(f"  - {s}")
        if fail_list:
            out_lines.append("\n• Gagal:")
            for f in fail_list:
                out_lines.append(f"  - {f}")

        return ToolResult(
            success=len(success_list) > 0,
            output="\n".join(out_lines),
            error=None if success_list else "Semua unduhan dalam batch gagal.",
        )

    async def _action_download(
        self, context: ToolContext, kwargs: dict[str, Any], is_audio_only: bool = False
    ) -> ToolResult:
        """Main download dispatcher handling media extraction or direct downloading."""
        raw_url = kwargs.get("url", "").strip()
        if not raw_url:
            return ToolResult(success=False, output="", error="Parameter 'url' wajib disertakan.")

        output_dir = _resolve_download_dir(kwargs.get("output_dir"))
        timeout = min(600, max(15, kwargs.get("timeout_seconds", 180)))
        send_telegram = kwargs.get("send_to_telegram", True)
        format_choice = kwargs.get("format", "best" if not is_audio_only else "mp3").lower().strip()

        engines = _get_installed_engines()

        # Route A: Stream / Social Media Extractor (yt-dlp)
        if _is_stream_url(raw_url) or is_audio_only or format_choice in ("mp3", "m4a", "opus"):
            if engines.get("yt-dlp"):
                return await self._download_via_ytdlp(
                    raw_url, output_dir, format_choice, is_audio_only, timeout, send_telegram, context, kwargs
                )

        # Route B: Direct Download (Aria2c / Curl / Native)
        return await self._download_direct(
            raw_url, output_dir, timeout, send_telegram, context, kwargs
        )

    async def _download_via_ytdlp(
        self,
        url: str,
        output_dir: str,
        format_choice: str,
        is_audio_only: bool,
        timeout: int,
        send_telegram: bool,
        context: ToolContext,
        kwargs: dict[str, Any],
    ) -> ToolResult:
        """Download and extract video or audio using yt-dlp."""
        engines = _get_installed_engines()
        yt_bin = engines["yt-dlp"]
        if not yt_bin:
            return ToolResult(
                success=False,
                output="",
                error=(
                    "Engine yt-dlp belum terpasang di Termux.\n"
                    "Pasang yt-dlp untuk mengunduh video dan audio dari tautan media sosial:\n"
                    "pkg install python-pip && pip install -U yt-dlp"
                ),
            )

        if context.on_status_update:
            mode_lbl = "audio " + format_choice if is_audio_only else "video " + format_choice
            await context.on_status_update(f"● media_downloader · mengekstrak {mode_lbl} dari {url[:35]}...")

        custom_name = kwargs.get("filename")
        if custom_name:
            out_template = os.path.join(output_dir, _sanitize_filename(custom_name))
            if not os.path.splitext(out_template)[1]:
                out_template += ".%(ext)s"
        else:
            out_template = os.path.join(output_dir, "%(title).80s-%(id)s.%(ext)s")

        cmd_args = [
            shlex.quote(yt_bin),
            "--no-playlist",
            "--no-check-certificates",
            "-o",
            shlex.quote(out_template),
        ]

        # Audio vs Video formatting
        if is_audio_only or format_choice in ("mp3", "m4a", "opus"):
            cmd_args.extend(["-x", "--audio-format", format_choice if format_choice != "best" else "mp3"])
            cmd_args.extend(["--audio-quality", "0"])
        else:
            if format_choice == "1080p":
                cmd_args.extend(["-f", "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best"])
            elif format_choice == "720p":
                cmd_args.extend(["-f", "bestvideo[height<=720]+bestaudio/best[height<=720]/best"])
            elif format_choice in ("480p", "360p"):
                h = 480 if format_choice == "480p" else 360
                cmd_args.extend(["-f", f"bestvideo[height<={h}]+bestaudio/best[height<={h}]/best"])
            else:
                cmd_args.extend(["-f", "bestvideo+bestaudio/best"])

        cmd_args.append(shlex.quote(url))
        cmd = " ".join(cmd_args)

        # Record directory snapshot before execution
        before_files = set(os.listdir(output_dir))
        res = await bridge.execute_shell(cmd, timeout=timeout)
        after_files = set(os.listdir(output_dir))
        new_files = list(after_files - before_files)

        if not res.success and not new_files:
            return ToolResult(
                success=False,
                output="",
                error=f"Gagal mengunduh media dari {url}: {res.stderr or res.stdout or 'Error/Timeout'}",
            )

        # Find the generated file
        downloaded_file: str | None = None
        if new_files:
            downloaded_file = os.path.join(output_dir, new_files[0])
        else:
            # Fallback inspect output for filename
            m = re.search(r'Destination:\s*([^\n\r]+)', res.stdout)
            if m:
                p = m.group(1).strip()
                if os.path.exists(p):
                    downloaded_file = p

        if not downloaded_file or not os.path.exists(downloaded_file):
            return ToolResult(
                success=False,
                output="",
                error=f"Proses selesai namun berkas hasil unduhan tidak ditemukan di {output_dir}.",
            )

        file_size = os.path.getsize(downloaded_file)
        fname = os.path.basename(downloaded_file)
        ext = os.path.splitext(fname)[1].lower()

        media_type = "photo" if ext in (".jpg", ".jpeg", ".png", ".webp") else "document"
        can_send_telegram = send_telegram and (file_size <= TELEGRAM_MAX_UPLOAD_BYTES)

        out_lines = [
            "Pengunduhan & Ekstraksi Media Berhasil\n",
            f"• Judul / Nama Berkas: {fname}",
            f"• Format: {ext[1:].upper() if ext else 'Media'}",
            f"• Ukuran: {_format_size(file_size)}",
            f"• Lokasi Penyimpanan: {downloaded_file}",
        ]

        if can_send_telegram:
            out_lines.append("• Pengiriman: Berkas otomatis dikirimkan ke chat Telegram ini.")
            return ToolResult(
                success=True,
                output="\n".join(out_lines),
                media_path=downloaded_file,
                media_type=media_type,
            )
        else:
            if file_size > TELEGRAM_MAX_UPLOAD_BYTES:
                out_lines.append(
                    f"• Catatan Telegram: Ukuran berkas ({_format_size(file_size)}) melebihi batas "
                    f"maksimal bot Telegram (50 MB). Berkas tetap tersimpan aman di HP Anda."
                )
            return ToolResult(success=True, output="\n".join(out_lines))

    async def _download_direct(
        self,
        url: str,
        output_dir: str,
        timeout: int,
        send_telegram: bool,
        context: ToolContext,
        kwargs: dict[str, Any],
    ) -> ToolResult:
        """Download file directly using aria2c, curl, wget, or native Python fallback."""
        engines = _get_installed_engines()
        accelerated = kwargs.get("accelerated", True)
        max_conn = max(1, min(16, kwargs.get("max_connections", 8)))

        # Determine target filename
        custom_name = kwargs.get("filename")
        if custom_name:
            final_filename = _sanitize_filename(custom_name)
        else:
            parsed = urllib.parse.urlparse(url)
            base = os.path.basename(parsed.path)
            final_filename = _sanitize_filename(base) if base else f"download_{int(time.time())}.bin"

        dest_path = os.path.join(output_dir, final_filename)

        if context.on_status_update:
            await context.on_status_update(f"● media_downloader · mengunduh {final_filename}...")

        # 1. Engine: aria2c (Accelerated multi-connection)
        if accelerated and engines.get("aria2c"):
            aria_bin = engines["aria2c"]
            cmd = (
                f"{shlex.quote(aria_bin)} -c -s {max_conn} -x {max_conn} "
                f"--dir={shlex.quote(output_dir)} -o {shlex.quote(final_filename)} "
                f"--check-certificate=false {shlex.quote(url)}"
            )
            res = await bridge.execute_shell(cmd, timeout=timeout)
            if res.success and os.path.exists(dest_path) and os.path.getsize(dest_path) > 0:
                return self._build_direct_success(dest_path, "aria2c (multi-thread)", send_telegram)

        # 2. Engine: curl
        if engines.get("curl"):
            curl_bin = engines["curl"]
            cmd = (
                f"{shlex.quote(curl_bin)} -k -L -C - -o {shlex.quote(dest_path)} "
                f"--connect-timeout 15 -m {timeout} {shlex.quote(url)}"
            )
            res = await bridge.execute_shell(cmd, timeout=timeout)
            if res.success and os.path.exists(dest_path) and os.path.getsize(dest_path) > 0:
                return self._build_direct_success(dest_path, "curl", send_telegram)

        # 3. Engine: wget
        if engines.get("wget"):
            wget_bin = engines["wget"]
            cmd = (
                f"{shlex.quote(wget_bin)} --no-check-certificate -c -O {shlex.quote(dest_path)} "
                f"--timeout=15 {shlex.quote(url)}"
            )
            res = await bridge.execute_shell(cmd, timeout=timeout)
            if res.success and os.path.exists(dest_path) and os.path.getsize(dest_path) > 0:
                return self._build_direct_success(dest_path, "wget", send_telegram)

        # 4. Engine: Native Python Async Chunk Downloader
        try:
            loop = asyncio.get_running_loop()

            def _native_download() -> str | None:
                req = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Android; Mobile; rv:124.0) Gecko/124.0 Firefox/124.0"
                    },
                )
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    with open(dest_path, "wb") as out_f:
                        while True:
                            chunk = resp.read(65536)
                            if not chunk:
                                break
                            out_f.write(chunk)
                return dest_path

            await loop.run_in_executor(None, _native_download)
            if os.path.exists(dest_path) and os.path.getsize(dest_path) > 0:
                return self._build_direct_success(dest_path, "Python Native Stream", send_telegram)
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Gagal mengunduh berkas dari {url}: {e}",
            )

        return ToolResult(
            success=False,
            output="",
            error=f"Gagal mengunduh berkas dari {url}: Tidak ada mesin unduh yang berhasil.",
        )

    def _build_direct_success(self, dest_path: str, engine_used: str, send_telegram: bool) -> ToolResult:
        """Construct success ToolResult for direct download."""
        file_size = os.path.getsize(dest_path)
        fname = os.path.basename(dest_path)
        ext = os.path.splitext(fname)[1].lower()

        media_type = "photo" if ext in (".jpg", ".jpeg", ".png", ".webp") else "document"
        can_send_telegram = send_telegram and (file_size <= TELEGRAM_MAX_UPLOAD_BYTES)

        sha256 = _compute_sha256(dest_path)

        out_lines = [
            "Pengunduhan Berkas Selesai\n",
            f"• Nama Berkas: {fname}",
            f"• Ukuran: {_format_size(file_size)}",
            f"• Mesin Unduh: {engine_used}",
            f"• SHA-256: {sha256[:16]}...{sha256[-8:]}",
            f"• Lokasi Penyimpanan: {dest_path}",
        ]

        if can_send_telegram:
            out_lines.append("• Pengiriman: Berkas otomatis dikirimkan ke chat Telegram ini.")
            return ToolResult(
                success=True,
                output="\n".join(out_lines),
                media_path=dest_path,
                media_type=media_type,
            )
        else:
            if file_size > TELEGRAM_MAX_UPLOAD_BYTES:
                out_lines.append(
                    f"• Catatan Telegram: Ukuran berkas ({_format_size(file_size)}) melebihi batas "
                    f"maksimal bot Telegram (50 MB). Berkas tetap tersimpan aman di HP Anda."
                )
            return ToolResult(success=True, output="\n".join(out_lines))
