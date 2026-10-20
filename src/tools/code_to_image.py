from __future__ import annotations

import logging
import os
import tempfile
import time
from typing import Any

from code_to_image import render_code_to_image
from src.config import get_settings
from src.tools.base import BaseTool, ToolContext, ToolResult
from src.tools.path_security import is_credential_path, validate_path

logger = logging.getLogger("faf_agent.tools.code_to_image")


def _format_size(size_bytes: int) -> str:
    """Format bytes into readable size."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.2f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.2f} MB"


class CodeToImageTool(BaseTool):
    """Tool to generate realistic VS Code Dark+ screenshot images from code text or files."""

    name = "code_to_image"
    description = (
        "Ubah teks atau berkas kode pemrograman menjadi gambar PNG berkualitas tinggi bergaya "
        "tangkapan layar VS Code (tema Dark+). Mendukung berbagai bahasa (Python, Go, PHP, "
        "JavaScript, TypeScript, HTML, CSS, Bash, Rust, C++, JSON, Markdown, IPYNB/Jupyter, dll.), "
        "nomor baris kustom (mulai baris N), sorot baris (--highlight), kursor aktif (--cursor), "
        "gaya frame (tab default tanpa status bar, full dengan title bar & status bar, atau none), "
        "gaya OS Windows/Mac, serta soft wrap. Gambar yang dihasilkan otomatis dikirimkan ke chat pengguna."
    )
    parameters = {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "Teks kode pemrograman yang akan diubah menjadi gambar screenshot VS Code.",
            },
            "file_path": {
                "type": "string",
                "description": "Path berkas kode yang ingin dibaca dan diubah jadi gambar (opsional, jika tidak memakai parameter 'text').",
            },
            "lang": {
                "type": "string",
                "description": "Bahasa pemrograman (python, js, ts, go, php, html, css, json, bash, ipynb, dll.). Jika dikosongkan, akan ditebak otomatis.",
            },
            "name": {
                "type": "string",
                "description": "Nama file yang tampil pada tab VS Code (contoh: 'main.py', 'server.go', 'App.tsx').",
            },
            "path": {
                "type": "string",
                "description": "Path breadcrumb di atas editor (contoh: 'src/controllers/user.py').",
            },
            "frame": {
                "type": "string",
                "enum": ["tab", "full", "none"],
                "description": "Gaya frame: 'tab' (default, tab + breadcrumb + kode, tanpa status bar), 'full' (+ title bar & status bar), 'none' (hanya kode saja).",
            },
            "os_style": {
                "type": "string",
                "enum": ["mac", "win"],
                "description": "Gaya tombol title bar untuk frame 'full' ('mac' atau 'win'). Default 'mac'.",
            },
            "project": {
                "type": "string",
                "description": "Nama folder proyek pada title bar (contoh: 'my-project').",
            },
            "branch": {
                "type": "string",
                "description": "Nama branch Git pada status bar (contoh: 'main', 'feature/auth').",
            },
            "highlight": {
                "type": "string",
                "description": "Daftar baris atau rentang baris yang disorot (contoh: '3,5-7', '42,45-48').",
            },
            "cursor": {
                "type": "string",
                "description": "Posisi kursor dan highlight baris aktif dengan format 'baris:kolom' (contoh: '12:5').",
            },
            "wrap": {
                "type": "integer",
                "description": "Batas kolom soft wrap (contoh: 80). Jika kosong, tidak di-wrap.",
            },
            "start_line": {
                "type": "integer",
                "description": "Nomor baris awal pada editor (contoh: 40 untuk mulai dari baris 40). Default: 1.",
            },
            "scale": {
                "type": "number",
                "description": "Skala resolusi gambar (2 = tajam Retina/HiDPI, default: 2).",
            },
            "no_status_bar": {
                "type": "boolean",
                "description": "Set true untuk menyembunyikan status bar meskipun menggunakan frame 'full'.",
            },
        },
    }

    async def execute(self, context: ToolContext, **kwargs: Any) -> ToolResult:
        settings = get_settings()

        text_input = kwargs.get("text")
        file_path = kwargs.get("file_path")

        if not text_input and not file_path:
            return ToolResult(
                success=False,
                output="",
                error="Harap sertakan kode melalui parameter 'text' atau path berkas melalui 'file_path'.",
            )

        code_content = ""
        filename = kwargs.get("name")
        breadcrumb_path = kwargs.get("path")

        if file_path:
            # Security validation
            if is_credential_path(file_path):
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Akses ke berkas sensitif/kredensial ditolak: {file_path}",
                )

            is_valid, err_msg, validated_path = validate_path(file_path, check_credentials=True)
            if not is_valid or not validated_path:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Path berkas tidak valid atau tidak aman: {err_msg}",
                )

            if not os.path.isfile(validated_path):
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Berkas tidak ditemukan: {file_path}",
                )

            try:
                with open(validated_path, "r", encoding="utf-8", errors="replace") as f:
                    code_content = f.read()
            except Exception as e:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Gagal membaca berkas {file_path}: {str(e)}",
                )

            if not filename:
                filename = os.path.basename(validated_path)
            if not breadcrumb_path:
                breadcrumb_path = str(file_path)
        else:
            code_content = str(text_input)

        lang = kwargs.get("lang")
        if not filename:
            from code_to_image import DEFAULT_FILENAMES_PER_LANG
            if lang and lang.lower().strip() in DEFAULT_FILENAMES_PER_LANG:
                filename = DEFAULT_FILENAMES_PER_LANG[lang.lower().strip()]
            else:
                filename = "main.py"
        if not breadcrumb_path:
            breadcrumb_path = filename

        # Prepare destination directory
        media_dir = getattr(settings, "temp_media_dir", None)
        if not media_dir:
            media_dir = os.path.join(tempfile.gettempdir(), "faf_media")
        try:
            os.makedirs(media_dir, exist_ok=True)
        except OSError:
            media_dir = tempfile.gettempdir()

        clean_base = os.path.splitext(os.path.basename(filename))[0] or "code"
        timestamp = int(time.time())
        output_filename = f"code_{clean_base}_{timestamp}.png"
        output_filepath = os.path.join(media_dir, output_filename)

        if context.on_status_update:
            await context.on_status_update(f"● code_to_image · merender {filename} (VS Code Dark+)...")

        # Extract arguments
        lang = kwargs.get("lang")
        frame = kwargs.get("frame", "tab")
        os_style = kwargs.get("os_style", "mac")
        project = kwargs.get("project", "faf-agent")
        branch = kwargs.get("branch", "main")
        highlight = kwargs.get("highlight")
        cursor = kwargs.get("cursor")
        wrap = kwargs.get("wrap")
        scale = kwargs.get("scale", 2.0)
        start_line = kwargs.get("start_line", 1)
        no_status_bar = kwargs.get("no_status_bar", False)

        try:
            saved_path = render_code_to_image(
                code=code_content,
                output_path=output_filepath,
                lang=lang,
                name=filename,
                path=breadcrumb_path,
                frame=frame,
                os_style=os_style,
                project=project,
                branch=branch,
                highlight=highlight,
                cursor=cursor,
                wrap=wrap,
                scale=scale,
                start_line=start_line,
                no_status_bar=no_status_bar,
            )
        except Exception as e:
            logger.exception("Failed to render code to image: %s", e)
            return ToolResult(
                success=False,
                output="",
                error=f"Terjadi kesalahan saat merender gambar kode: {str(e)}",
            )

        if os.path.exists(saved_path) and os.path.getsize(saved_path) > 0:
            file_size_str = _format_size(os.path.getsize(saved_path))
            out_msg = (
                f"Gambar Screenshot Kode Berhasil Dibuat (Gaya VS Code Dark+)\n\n"
                f"• Berkas: {filename}\n"
                f"• Bahasa: {lang or 'Otomatis'}\n"
                f"• Frame: {frame}\n"
                f"• Nomor Baris Awal: {start_line}\n"
                f"• Ukuran Berkas: {file_size_str}\n"
                f"• Gambar telah dikirimkan langsung ke obrolan Telegram ini."
            )
            return ToolResult(
                success=True,
                output=out_msg,
                media_path=saved_path,
                media_type="photo",
            )
        else:
            return ToolResult(
                success=False,
                output="",
                error="Gagal menyimpan gambar hasil render kode.",
            )
