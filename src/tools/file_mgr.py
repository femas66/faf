from __future__ import annotations

import asyncio
import datetime
import hashlib
import logging
import os
import pathlib
import re
import shutil
import stat
import tarfile
import zipfile
from typing import Any

from src.core.permissions import permission_manager
from src.tools.base import BaseTool, ToolContext, ToolResult

logger = logging.getLogger("faf_agent.tools.file_mgr")

# Protected system paths that can never be deleted or wiped
PROTECTED_PATHS = {
    "/",
    "/root",
    "/system",
    "/vendor",
    "/data",
    "/data/data",
    "/sdcard",
    "/storage",
    "/storage/emulated",
    "/storage/emulated/0",
    "/data/data/com.termux/files",
    "/data/data/com.termux/files/usr",
}


def _format_size(size_bytes: int) -> str:
    """Format bytes into readable human-friendly size."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.2f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.2f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def _format_timestamp(ts: float) -> str:
    """Format epoch timestamp to readable date string."""
    dt = datetime.datetime.fromtimestamp(ts)
    return dt.strftime("%d-%m-%Y %H:%M:%S")


def _is_binary(file_path: str, block_size: int = 1024) -> bool:
    """Check if a file appears to be binary by inspecting initial bytes for null characters."""
    try:
        with open(file_path, "rb") as f:
            chunk = f.read(block_size)
            if b"\x00" in chunk:
                return True
            # Check for non-text characters ratio
            text_chars = bytearray({7, 8, 9, 10, 12, 13, 27} | set(range(0x20, 0x100)) - {0x7F})
            non_text = chunk.translate(None, text_chars)
            return len(non_text) / len(chunk) > 0.30 if chunk else False
    except Exception:
        return False


def _resolve_safe_path(target_path: str) -> str:
    """Expand user tilde and convert to absolute normalized path."""
    expanded = os.path.expanduser(target_path.strip())
    # Expand Termux environment variables if present
    expanded = os.path.expandvars(expanded)
    return os.path.abspath(expanded)


class FileManagerTool(BaseTool):
    """Dedicated all-in-one comprehensive tool for reading, writing, editing line-by-line,

    searching, inspecting, and managing files and directories on Android / Termux.
    """

    name = "file_manager"
    description = (
        "Tool komprehensif dan lengkap untuk mengelola file dan direktori di Android / Termux: "
        "membaca seluruh file atau rentang baris tertentu (start_line sampai end_line), menulis file baru, "
        "mengedit baris per baris, menyisipkan baris, mencari & mengganti teks, mencari file/grep, "
        "melihat informasi berkas (ukuran, izin, hash), membuat folder, menyalin, memindahkan, "
        "dan menghapus file dengan pengamanan ketat. AI WAJIB menggunakan tool ini daripada shell."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "read",
                    "write",
                    "append",
                    "edit_lines",
                    "insert_lines",
                    "find_replace",
                    "delete",
                    "file_info",
                    "list_dir",
                    "search_text",
                    "copy",
                    "move",
                    "make_dir",
                    "checksum",
                    "tree",
                    "extract_archive",
                    "send_file",
                ],
                "description": (
                    "Aksi operasi berkas yang diinginkan: "
                    "'read' (baca seluruh file atau rentang baris start_line s/d end_line), "
                    "'write' (tulis file baru atau timpa isi file), "
                    "'append' (tambahkan teks ke akhir file), "
                    "'edit_lines' (ganti rentang baris tertentu dengan konten baru), "
                    "'insert_lines' (sisipkan teks di nomor baris tertentu), "
                    "'find_replace' (cari kata/teks dan ganti dalam file), "
                    "'delete' (hapus file atau direktori dengan penjaga konfirmasi), "
                    "'file_info' (informasi detail ukuran, izin, mtime, hash file), "
                    "'list_dir' (lihat daftar berkas dan folder dalam suatu direktori), "
                    "'search_text' (cari teks/grep di dalam file atau seluruh direktori), "
                    "'copy' (salin file atau folder), "
                    "'move' (pindahkan atau ganti nama file/folder), "
                    "'make_dir' (buat folder baru beserta induknya jika belum ada), "
                    "'checksum' (hitung hash MD5, SHA1, SHA256 file), "
                    "'tree' (tampilkan struktur pohon direktori hierarkis), "
                    "'extract_archive' (ekstrak file arsip .zip / .tar.xz / .tar.gz ke destination_path), "
                    "'send_file' (mengirimkan berkas apapun dari penyimpanan HP langsung ke chat Telegram sebagai dokumen atau foto)."
                ),
            },
            "path": {
                "type": "string",
                "description": (
                    "Path berkas atau direktori target (contoh: '/sdcard/Notes/todo.txt' atau 'src/core/agent.py'). "
                    "WAJIB menyertakan lokasi folder/direktori. JANGAN menebak path jika lokasi folder belum ditentukan "
                    "oleh pengguna, melainkan tanyakan klarifikasi terlebih dahulu."
                ),
            },
            "source_path": {
                "type": "string",
                "description": "Path asal untuk operasi 'copy' atau 'move'.",
            },
            "destination_path": {
                "type": "string",
                "description": "Path tujuan untuk operasi 'copy' atau 'move'.",
            },
            "content": {
                "type": "string",
                "description": "Isi teks yang akan ditulis, ditambahkan, atau disisipkan ke dalam berkas.",
            },
            "start_line": {
                "type": "integer",
                "description": "Nomor baris awal (1-indexed) untuk aksi 'read' atau 'edit_lines'.",
            },
            "end_line": {
                "type": "integer",
                "description": "Nomor baris akhir (1-indexed) untuk aksi 'read' atau 'edit_lines'.",
            },
            "line_number": {
                "type": "integer",
                "description": "Nomor baris target untuk aksi 'insert_lines'.",
            },
            "position": {
                "type": "string",
                "enum": ["before", "after"],
                "description": "Posisi penyisipan untuk 'insert_lines' ('before' = sebelum baris, 'after' = setelah baris). Default: 'after'.",
                "default": "after",
            },
            "find_text": {
                "type": "string",
                "description": "Teks atau pola yang dicari untuk aksi 'find_replace'.",
            },
            "replace_text": {
                "type": "string",
                "description": "Teks pengganti untuk aksi 'find_replace'.",
            },
            "replace_all": {
                "type": "boolean",
                "description": "Setel True untuk mengganti semua kecocokan pada 'find_replace', False untuk hanya kecocokan pertama.",
                "default": True,
            },
            "pattern": {
                "type": "string",
                "description": "Pola teks atau regex yang dicari untuk aksi 'search_text'.",
            },
            "is_regex": {
                "type": "boolean",
                "description": "Setel True jika find_text atau pattern adalah Regular Expression (Regex).",
                "default": False,
            },
            "ignore_case": {
                "type": "boolean",
                "description": "Setel True untuk pencarian tanpa membedakan huruf besar/kecil (case-insensitive).",
                "default": True,
            },
            "recursive": {
                "type": "boolean",
                "description": "Setel True untuk pencarian rekursif subfolder atau penghapusan direktori rekursif.",
                "default": False,
            },
            "file_extension": {
                "type": "string",
                "description": "Filter ekstensi file untuk aksi 'search_text' (contoh: '.py', '.txt', '.json').",
            },
            "overwrite": {
                "type": "boolean",
                "description": "Setel True untuk menimpa file yang sudah ada pada 'write', 'copy', atau 'move'.",
                "default": True,
            },
            "create_dirs": {
                "type": "boolean",
                "description": "Setel True untuk otomatis membuat direktori induk jika belum ada saat 'write' atau 'append'.",
                "default": True,
            },
            "show_hidden": {
                "type": "boolean",
                "description": "Setel True untuk menampilkan file/folder tersembunyi (diawali titik '.') pada 'list_dir' atau 'tree'.",
                "default": False,
            },
            "sort_by": {
                "type": "string",
                "enum": ["name", "size", "mtime", "type"],
                "description": "Kriteria pengurutan daftar berkas pada 'list_dir'. Default: 'name'.",
                "default": "name",
            },
            "max_items": {
                "type": "integer",
                "description": "Batas maksimal jumlah baris / item yang ditampilkan pada 'list_dir' atau 'search_text'. Default: 100.",
                "default": 100,
            },
            "max_depth": {
                "type": "integer",
                "description": "Kedalaman hierarki maksimal untuk aksi 'tree'. Default: 3.",
                "default": 3,
            },
            "with_line_numbers": {
                "type": "boolean",
                "description": "Setel True untuk menyertakan penomoran baris pada hasil aksi 'read'. Default: True.",
                "default": True,
            },
        },
        "required": ["action"],
    }

    async def execute(self, context: ToolContext, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action", "").lower().strip()
        path_arg = kwargs.get("path", "")
        source_path_arg = kwargs.get("source_path", "")
        dest_path_arg = kwargs.get("destination_path", "")

        target_path = _resolve_safe_path(path_arg) if path_arg else ""
        source_path = _resolve_safe_path(source_path_arg) if source_path_arg else ""
        dest_path = _resolve_safe_path(dest_path_arg) if dest_path_arg else ""

        if context.on_status_update:
            display_name = os.path.basename(target_path or source_path or "")
            await context.on_status_update(f"● file_manager · {action} {display_name}")

        # -------------------------------------------------------------------
        # 1. Action: READ (View entire file or specific line range)
        # -------------------------------------------------------------------
        if action == "read":
            if not target_path:
                return ToolResult(success=False, output="", error="Parameter 'path' wajib diisi untuk aksi read.")

            # Security check: credential exfiltration guard
            is_exfil, exfil_reason = permission_manager.check_credential_exfiltration(target_path)
            if is_exfil:
                return ToolResult(success=False, output="", error=exfil_reason)

            if not os.path.exists(target_path):
                return ToolResult(success=False, output="", error=f"Berkas tidak ditemukan: {target_path}")

            if os.path.isdir(target_path):
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Path tersebut adalah direktori, bukan file. Gunakan action 'list_dir': {target_path}",
                )

            if _is_binary(target_path):
                size_str = _format_size(os.path.getsize(target_path))
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Berkas adalah file biner (binary file, {size_str}). Tidak dapat dibaca sebagai teks biasa.",
                )

            try:
                with open(target_path, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
            except Exception as e:
                return ToolResult(success=False, output="", error=f"Gagal membaca file: {str(e)}")

            total_lines = len(lines)
            start_line = kwargs.get("start_line")
            end_line = kwargs.get("end_line")
            with_num = kwargs.get("with_line_numbers", True)

            # Determine slice range (1-indexed)
            if start_line is not None and start_line > 0:
                s_idx = start_line - 1
            else:
                s_idx = 0

            if end_line is not None and end_line > 0:
                e_idx = min(end_line, total_lines)
            else:
                e_idx = total_lines

            if s_idx >= total_lines:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"start_line ({start_line}) melebihi total baris file ({total_lines} baris).",
                )

            if s_idx >= e_idx:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"start_line ({start_line}) harus lebih kecil atau sama dengan end_line ({end_line}).",
                )

            selected_lines = lines[s_idx:e_idx]
            file_name = os.path.basename(target_path)

            output_lines = [
                f"Isi Berkas: {file_name} ({target_path})",
                f"• Rentang Baris: {s_idx + 1} sampai {e_idx} (dari total {total_lines} baris)",
                "",
            ]

            max_line_len = len(str(e_idx))
            for i, line_content in enumerate(selected_lines, start=s_idx + 1):
                clean_content = line_content.rstrip("\r\n")
                if with_num:
                    num_str = str(i).rjust(max_line_len)
                    output_lines.append(f"{num_str} | {clean_content}")
                else:
                    output_lines.append(clean_content)

            return ToolResult(success=True, output="\n".join(output_lines))

        # -------------------------------------------------------------------
        # 2. Action: WRITE (Create new file or overwrite)
        # -------------------------------------------------------------------
        elif action == "write":
            if not target_path:
                return ToolResult(success=False, output="", error="Parameter 'path' wajib diisi untuk aksi write.")

            # Ambiguity guard: check for bare filename without directory
            if not any(sep in path_arg for sep in ("/", "\\", "~")):
                return ToolResult(
                    success=False,
                    output="",
                    error=(
                        f"Lokasi folder target untuk '{path_arg}' belum ditentukan (ambigu). "
                        "Tanyakan klarifikasi kepada pengguna di direktori mana berkas ingin disimpan "
                        "(misalnya di direktori home Termux ~/ atau penyimpanan internal /sdcard)."
                    ),
                )

            # Security check
            is_exfil, exfil_reason = permission_manager.check_credential_exfiltration(target_path)
            if is_exfil:
                return ToolResult(success=False, output="", error=exfil_reason)

            content = kwargs.get("content", "")
            overwrite = kwargs.get("overwrite", True)
            create_dirs = kwargs.get("create_dirs", True)

            if os.path.exists(target_path) and not overwrite:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Berkas sudah ada dan 'overwrite' bernilai False: {target_path}",
                )

            try:
                parent_dir = os.path.dirname(target_path)
                if create_dirs and parent_dir and not os.path.exists(parent_dir):
                    os.makedirs(parent_dir, exist_ok=True)

                with open(target_path, "w", encoding="utf-8") as f:
                    f.write(content)

                file_size = os.path.getsize(target_path)
                line_count = len(content.splitlines())

                res_text = (
                    f"Berhasil menulis ke berkas: {target_path}\n"
                    f"• Ukuran Berkas: {_format_size(file_size)}\n"
                    f"• Jumlah Baris: {line_count} baris\n"
                    f"• Status: Berkas tersimpan dengan aman"
                )
                return ToolResult(success=True, output=res_text)
            except Exception as e:
                return ToolResult(success=False, output="", error=f"Gagal menulis file: {str(e)}")

        # -------------------------------------------------------------------
        # 3. Action: APPEND (Add content to end of file)
        # -------------------------------------------------------------------
        elif action == "append":
            if not target_path:
                return ToolResult(success=False, output="", error="Parameter 'path' wajib diisi untuk aksi append.")

            # Ambiguity guard: check for bare filename without directory
            if not any(sep in path_arg for sep in ("/", "\\", "~")):
                return ToolResult(
                    success=False,
                    output="",
                    error=(
                        f"Lokasi folder target untuk '{path_arg}' belum ditentukan (ambigu). "
                        "Tanyakan klarifikasi kepada pengguna di direktori mana berkas ingin ditambahkan teks "
                        "(misalnya di direktori home Termux ~/ atau penyimpanan internal /sdcard)."
                    ),
                )

            # Security check
            is_exfil, exfil_reason = permission_manager.check_credential_exfiltration(target_path)
            if is_exfil:
                return ToolResult(success=False, output="", error=exfil_reason)

            content = kwargs.get("content", "")
            create_dirs = kwargs.get("create_dirs", True)

            try:
                parent_dir = os.path.dirname(target_path)
                if create_dirs and parent_dir and not os.path.exists(parent_dir):
                    os.makedirs(parent_dir, exist_ok=True)

                # Append newline if existing file doesn't end with one and has content
                needs_newline = False
                if os.path.exists(target_path) and os.path.getsize(target_path) > 0:
                    with open(target_path, "rb") as f:
                        f.seek(-1, os.SEEK_END)
                        last_byte = f.read(1)
                        if last_byte != b"\n":
                            needs_newline = True

                with open(target_path, "a", encoding="utf-8") as f:
                    if needs_newline:
                        f.write("\n")
                    f.write(content)

                file_size = os.path.getsize(target_path)
                res_text = (
                    f"Berhasil menambahkan teks ke berkas: {target_path}\n"
                    f"• Ukuran Sekarang: {_format_size(file_size)}\n"
                    f"• Teks Ditambahkan: {len(content.splitlines())} baris ({len(content)} karakter)"
                )
                return ToolResult(success=True, output=res_text)
            except Exception as e:
                return ToolResult(success=False, output="", error=f"Gagal menambahkan teks ke file: {str(e)}")

        # -------------------------------------------------------------------
        # 4. Action: EDIT_LINES (Replace line range start_line to end_line)
        # -------------------------------------------------------------------
        elif action == "edit_lines":
            if not target_path:
                return ToolResult(success=False, output="", error="Parameter 'path' wajib diisi untuk edit_lines.")

            is_exfil, exfil_reason = permission_manager.check_credential_exfiltration(target_path)
            if is_exfil:
                return ToolResult(success=False, output="", error=exfil_reason)

            if not os.path.exists(target_path):
                return ToolResult(success=False, output="", error=f"Berkas tidak ditemukan: {target_path}")

            start_line = kwargs.get("start_line")
            end_line = kwargs.get("end_line")
            new_content = kwargs.get("content", "")

            if start_line is None or end_line is None:
                return ToolResult(
                    success=False,
                    output="",
                    error="Parameter 'start_line' dan 'end_line' (1-indexed) wajib diisi untuk edit_lines.",
                )

            try:
                with open(target_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
            except Exception as e:
                return ToolResult(success=False, output="", error=f"Gagal membaca file untuk diedit: {str(e)}")

            total_lines = len(lines)
            if start_line < 1 or start_line > total_lines:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"start_line ({start_line}) tidak valid (file memiliki {total_lines} baris).",
                )

            if end_line < start_line or end_line > total_lines:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"end_line ({end_line}) harus >= start_line ({start_line}) dan <= total baris ({total_lines}).",
                )

            # Prepare replacement lines
            new_lines = [l + "\n" for l in new_content.splitlines()]
            if not new_lines and new_content == "":
                new_lines = []

            # Splice lines
            s_idx = start_line - 1
            e_idx = end_line
            lines[s_idx:e_idx] = new_lines

            try:
                with open(target_path, "w", encoding="utf-8") as f:
                    f.writelines(lines)

                new_total = len(lines)
                res_text = (
                    f"Berhasil mengedit baris di berkas: {target_path}\n"
                    f"• Baris Lama Diganti: Baris {start_line} sampai {end_line} ({end_line - start_line + 1} baris)\n"
                    f"• Baris Baru Ditulis: {len(new_lines)} baris\n"
                    f"• Total Baris Sekarang: {new_total} baris\n"
                    f"• Ukuran Berkas: {_format_size(os.path.getsize(target_path))}"
                )
                return ToolResult(success=True, output=res_text)
            except Exception as e:
                return ToolResult(success=False, output="", error=f"Gagal menyimpan perubahan edit_lines: {str(e)}")

        # -------------------------------------------------------------------
        # 5. Action: INSERT_LINES (Insert content at specific line number)
        # -------------------------------------------------------------------
        elif action == "insert_lines":
            if not target_path:
                return ToolResult(success=False, output="", error="Parameter 'path' wajib diisi untuk insert_lines.")

            is_exfil, exfil_reason = permission_manager.check_credential_exfiltration(target_path)
            if is_exfil:
                return ToolResult(success=False, output="", error=exfil_reason)

            if not os.path.exists(target_path):
                return ToolResult(success=False, output="", error=f"Berkas tidak ditemukan: {target_path}")

            line_number = kwargs.get("line_number")
            insert_content = kwargs.get("content", "")
            position = kwargs.get("position", "after").lower()

            if line_number is None or line_number < 1:
                return ToolResult(
                    success=False,
                    output="",
                    error="Parameter 'line_number' wajib berupa angka positif (1-indexed).",
                )

            try:
                with open(target_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
            except Exception as e:
                return ToolResult(success=False, output="", error=f"Gagal membaca file: {str(e)}")

            total_lines = len(lines)
            insert_idx = (line_number - 1) if position == "before" else line_number
            insert_idx = max(0, min(insert_idx, total_lines))

            new_lines = [l + "\n" for l in insert_content.splitlines()]
            lines[insert_idx:insert_idx] = new_lines

            try:
                with open(target_path, "w", encoding="utf-8") as f:
                    f.writelines(lines)

                res_text = (
                    f"Berhasil menyisipkan baris di berkas: {target_path}\n"
                    f"• Posisi Sisip: {position.upper()} baris {line_number}\n"
                    f"• Jumlah Baris Disisipkan: {len(new_lines)} baris\n"
                    f"• Total Baris Sekarang: {len(lines)} baris"
                )
                return ToolResult(success=True, output=res_text)
            except Exception as e:
                return ToolResult(success=False, output="", error=f"Gagal menyimpan file: {str(e)}")

        # -------------------------------------------------------------------
        # 6. Action: FIND_REPLACE (Search string/regex and replace)
        # -------------------------------------------------------------------
        elif action == "find_replace":
            if not target_path:
                return ToolResult(success=False, output="", error="Parameter 'path' wajib diisi untuk find_replace.")

            is_exfil, exfil_reason = permission_manager.check_credential_exfiltration(target_path)
            if is_exfil:
                return ToolResult(success=False, output="", error=exfil_reason)

            if not os.path.exists(target_path):
                return ToolResult(success=False, output="", error=f"Berkas tidak ditemukan: {target_path}")

            find_text = kwargs.get("find_text", "")
            replace_text = kwargs.get("replace_text", "")
            replace_all = kwargs.get("replace_all", True)
            is_regex = kwargs.get("is_regex", False)

            if not find_text:
                return ToolResult(success=False, output="", error="Parameter 'find_text' tidak boleh kosong.")

            try:
                with open(target_path, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception as e:
                return ToolResult(success=False, output="", error=f"Gagal membaca file: {str(e)}")

            match_count = 0
            if is_regex:
                try:
                    pattern = re.compile(find_text)
                    matches = pattern.findall(content)
                    match_count = len(matches)
                    if match_count == 0:
                        return ToolResult(
                            success=True,
                            output=f"Pola regex '{find_text}' tidak ditemukan di berkas {target_path}. Tidak ada perubahan.",
                        )
                    count_limit = 0 if replace_all else 1
                    new_content = pattern.sub(replace_text, content, count=count_limit)
                except re.error as re_err:
                    return ToolResult(success=False, output="", error=f"Sintaks regex tidak valid: {str(re_err)}")
            else:
                match_count = content.count(find_text)
                if match_count == 0:
                    return ToolResult(
                        success=True,
                        output=f"Teks '{find_text}' tidak ditemukan di berkas {target_path}. Tidak ada perubahan.",
                    )
                if replace_all:
                    new_content = content.replace(find_text, replace_text)
                else:
                    new_content = content.replace(find_text, replace_text, 1)

            try:
                with open(target_path, "w", encoding="utf-8") as f:
                    f.write(new_content)

                repl_count_str = str(match_count) if replace_all else f"1 dari {match_count}"
                res_text = (
                    f"Berhasil mengganti teks di berkas: {target_path}\n"
                    f"• Teks Dicari: '{find_text}'\n"
                    f"• Jumlah Kecocokan Diganti: {repl_count_str} tempat\n"
                    f"• Ukuran Berkas Baru: {_format_size(os.path.getsize(target_path))}"
                )
                return ToolResult(success=True, output=res_text)
            except Exception as e:
                return ToolResult(success=False, output="", error=f"Gagal menyimpan penggantian teks: {str(e)}")

        # -------------------------------------------------------------------
        # 7. Action: DELETE (Delete file or directory with security confirmation)
        # -------------------------------------------------------------------
        elif action == "delete":
            if not target_path:
                return ToolResult(success=False, output="", error="Parameter 'path' wajib diisi untuk aksi delete.")

            # Safety check: protected paths
            for prot in PROTECTED_PATHS:
                if target_path == prot or target_path == prot.rstrip("/"):
                    return ToolResult(
                        success=False,
                        output="",
                        error=f"SECURITY VIOLATION: Dilarang keras menghapus direktori sistem terproteksi: {target_path}",
                    )

            if not os.path.exists(target_path):
                return ToolResult(success=False, output="", error=f"Target penghapusan tidak ditemukan: {target_path}")

            is_dir = os.path.isdir(target_path)
            recursive = kwargs.get("recursive", False)

            # Trigger inline button confirmation for destructive operations
            target_type_label = "Direktori (Folder)" if is_dir else "Berkas (File)"
            if context.on_request_confirmation:
                title = f"⚠️ Konfirmasi Penghapusan {target_type_label}"
                details = (
                    f"Apakah Anda yakin ingin menghapus {target_type_label.lower()} berikut?\n"
                    f"• Lokasi: {target_path}\n"
                    f"• Rekursif: {'Ya' if recursive else 'Tidak'}\n"
                    f"• Tindakan: Penghapusan permanen dari sistem Android"
                )
                approved = await context.on_request_confirmation(title, details)
                if not approved:
                    return ToolResult(
                        success=False,
                        output="",
                        error="Operasi penghapusan dibatalkan: Konfirmasi ditolak oleh pengguna atau batas waktu (timeout) habis.",
                    )
            else:
                # If no confirmation callback available, block directory deletion for safety
                if is_dir and recursive:
                    return ToolResult(
                        success=False,
                        output="",
                        error=f"Operasi ditolak: Penghapusan direktori rekursif ({target_path}) memerlukan persetujuan manual pengguna.",
                    )

            try:
                if is_dir:
                    if recursive:
                        shutil.rmtree(target_path)
                    else:
                        os.rmdir(target_path)
                else:
                    os.remove(target_path)

                res_text = (
                    f"Penghapusan Berhasil Diselesaikan\n"
                    f"• Tipe: {target_type_label}\n"
                    f"• Lokasi: {target_path}\n"
                    f"• Status: Berhasil dihapus permanen dari perangkat"
                )
                return ToolResult(success=True, output=res_text)
            except Exception as e:
                return ToolResult(success=False, output="", error=f"Gagal menghapus {target_type_label.lower()}: {str(e)}")

        # -------------------------------------------------------------------
        # 8. Action: FILE_INFO (Stat & detail analysis)
        # -------------------------------------------------------------------
        elif action in ("file_info", "stat", "info"):
            if not target_path:
                return ToolResult(success=False, output="", error="Parameter 'path' wajib diisi untuk file_info.")

            is_exfil, exfil_reason = permission_manager.check_credential_exfiltration(target_path)
            if is_exfil:
                return ToolResult(success=False, output="", error=exfil_reason)

            if not os.path.exists(target_path):
                return ToolResult(success=False, output="", error=f"Berkas atau direktori tidak ditemukan: {target_path}")

            try:
                st = os.stat(target_path)
                mode = st.st_mode
                is_dir = stat.S_ISDIR(mode)
                is_link = os.path.islink(target_path)

                file_type = "Direktori (Folder)" if is_dir else "Berkas Reguler"
                if is_link:
                    file_type += " (Symlink)"

                perm_octal = oct(stat.S_IMODE(mode))
                perm_str = stat.filemode(mode)
                size_str = _format_size(st.st_size)

                mtime_str = _format_timestamp(st.st_mtime)
                ctime_str = _format_timestamp(st.st_ctime)
                atime_str = _format_timestamp(st.st_atime)

                out_lines = [
                    f"Informasi Berkas: {os.path.basename(target_path)}",
                    f"• Path Lengkap: {target_path}",
                    f"• Tipe: {file_type}",
                    f"• Ukuran: {size_str} ({st.st_size:,} bytes)",
                    f"• Izin Akses: {perm_octal} ({perm_str})",
                    f"• Pemilik (UID/GID): {st.st_uid} / {st.st_gid}",
                    f"• Terakhir Dimodifikasi: {mtime_str}",
                    f"• Waktu Dibuat / Status: {ctime_str}",
                    f"• Terakhir Diakses: {atime_str}",
                ]

                if not is_dir:
                    # Check text or binary
                    is_bin = _is_binary(target_path)
                    out_lines.append(f"• Format Konten: {'Biner (Binary Data)' if is_bin else 'Teks (Text File)'}")

                    if not is_bin:
                        try:
                            with open(target_path, "r", encoding="utf-8", errors="replace") as f:
                                l_count = sum(1 for _ in f)
                            out_lines.append(f"• Total Baris Teks: {l_count} baris")
                        except Exception:
                            pass

                    # Calculate checksum for files < 50MB
                    if st.st_size < 50 * 1024 * 1024:
                        h_sha256 = hashlib.sha256()
                        h_md5 = hashlib.md5()
                        with open(target_path, "rb") as f:
                            while chunk := f.read(65536):
                                h_sha256.update(chunk)
                                h_md5.update(chunk)
                        out_lines.append(f"• Hash SHA256: {h_sha256.hexdigest()}")
                        out_lines.append(f"• Hash MD5: {h_md5.hexdigest()}")
                else:
                    # Directory item counts
                    try:
                        entries = os.listdir(target_path)
                        total_entries = len(entries)
                        dirs_count = sum(1 for e in entries if os.path.isdir(os.path.join(target_path, e)))
                        files_count = total_entries - dirs_count
                        out_lines.append(f"• Isi Direktori: {files_count} berkas, {dirs_count} subfolder ({total_entries} total item)")
                    except Exception:
                        pass

                return ToolResult(success=True, output="\n".join(out_lines))
            except Exception as e:
                return ToolResult(success=False, output="", error=f"Gagal mengambil informasi berkas: {str(e)}")

        # -------------------------------------------------------------------
        # 9. Action: LIST_DIR (List directory contents)
        # -------------------------------------------------------------------
        elif action in ("list_dir", "ls", "dir"):
            target_dir = target_path or os.getcwd()
            if not os.path.exists(target_dir):
                return ToolResult(success=False, output="", error=f"Direktori tidak ditemukan: {target_dir}")

            if not os.path.isdir(target_dir):
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Path tersebut adalah file, bukan direktori. Gunakan action 'file_info': {target_dir}",
                )

            show_hidden = kwargs.get("show_hidden", False)
            sort_by = kwargs.get("sort_by", "name").lower()
            max_items = kwargs.get("max_items", 100)

            try:
                raw_entries = os.listdir(target_dir)
            except Exception as e:
                return ToolResult(success=False, output="", error=f"Gagal membaca direktori: {str(e)}")

            items = []
            for name in raw_entries:
                if not show_hidden and name.startswith("."):
                    continue
                full_p = os.path.join(target_dir, name)
                try:
                    st = os.stat(full_p)
                    is_d = stat.S_ISDIR(st.st_mode)
                    items.append({
                        "name": name,
                        "path": full_p,
                        "is_dir": is_d,
                        "size": st.st_size,
                        "mtime": st.st_mtime,
                        "mode": stat.filemode(st.st_mode),
                    })
                except Exception:
                    items.append({
                        "name": name,
                        "path": full_p,
                        "is_dir": False,
                        "size": 0,
                        "mtime": 0,
                        "mode": "???",
                    })

            # Sorting
            if sort_by == "size":
                items.sort(key=lambda x: (not x["is_dir"], x["size"]), reverse=True)
            elif sort_by == "mtime":
                items.sort(key=lambda x: x["mtime"], reverse=True)
            elif sort_by == "type":
                items.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
            else:  # name
                items.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))

            total_items = len(items)
            display_items = items[:max_items]

            out_lines = [
                f"Daftar Direktori: {target_dir}",
                f"• Total Ditemukan: {total_items} item" + (f" (menampilkan {max_items} item teratas)" if total_items > max_items else ""),
                "",
            ]

            dir_count = 0
            file_count = 0
            for item in display_items:
                if item["is_dir"]:
                    dir_count += 1
                    out_lines.append(f"[DIR]  {item['name']}  ({_format_timestamp(item['mtime'])})")
                else:
                    file_count += 1
                    sz = _format_size(item["size"])
                    out_lines.append(f"[FILE] {item['name']}  ({sz} | {_format_timestamp(item['mtime'])})")

            out_lines.append("")
            out_lines.append(f"Ringkasan: {file_count} berkas, {dir_count} direktori ditampilkan.")
            return ToolResult(success=True, output="\n".join(out_lines))

        # -------------------------------------------------------------------
        # 10. Action: SEARCH_TEXT (Grep across file or directory)
        # -------------------------------------------------------------------
        elif action in ("search_text", "grep", "search"):
            pattern_str = kwargs.get("pattern", "")
            if not pattern_str:
                return ToolResult(success=False, output="", error="Parameter 'pattern' wajib diisi untuk search_text.")

            target_loc = target_path or os.getcwd()
            if not os.path.exists(target_loc):
                return ToolResult(success=False, output="", error=f"Lokasi pencarian tidak ditemukan: {target_loc}")

            is_regex = kwargs.get("is_regex", False)
            ignore_case = kwargs.get("ignore_case", True)
            recursive = kwargs.get("recursive", False)
            file_ext = kwargs.get("file_extension", "").lower().strip()
            max_results = kwargs.get("max_items", 50)

            # Compile regex or search pattern
            flags = re.IGNORECASE if ignore_case else 0
            if is_regex:
                try:
                    compiled_re = re.compile(pattern_str, flags)
                except re.error as e:
                    return ToolResult(success=False, output="", error=f"Regex tidak valid: {str(e)}")
            else:
                compiled_re = re.compile(re.escape(pattern_str), flags)

            files_to_check: list[str] = []
            if os.path.isfile(target_loc):
                files_to_check.append(target_loc)
            elif recursive:
                for root, _, files in os.walk(target_loc):
                    # Skip hidden directory paths
                    if any(part.startswith(".") and part != "." for part in root.split(os.sep)):
                        continue
                    for f in files:
                        if f.startswith("."):
                            continue
                        if file_ext and not f.lower().endswith(file_ext):
                            continue
                        files_to_check.append(os.path.join(root, f))
            else:
                for entry in os.listdir(target_loc):
                    full_p = os.path.join(target_loc, entry)
                    if os.path.isfile(full_p) and not entry.startswith("."):
                        if file_ext and not entry.lower().endswith(file_ext):
                            continue
                        files_to_check.append(full_p)

            results: list[str] = []
            matches_count = 0

            for fp in files_to_check:
                # Security check
                is_exfil, _ = permission_manager.check_credential_exfiltration(fp)
                if is_exfil or _is_binary(fp):
                    continue

                try:
                    with open(fp, "r", encoding="utf-8", errors="replace") as f:
                        for line_no, line in enumerate(f, start=1):
                            if compiled_re.search(line):
                                matches_count += 1
                                rel_path = os.path.relpath(fp, target_loc) if os.path.isdir(target_loc) else os.path.basename(fp)
                                results.append(f"{rel_path}:{line_no} | {line.strip()}")
                                if matches_count >= max_results:
                                    break
                except Exception:
                    continue
                if matches_count >= max_results:
                    break

            out_lines = [
                f"Hasil Pencarian Teks: '{pattern_str}'",
                f"• Lokasi: {target_loc}",
                f"• Total Kecocokan: {matches_count}" + (f" (dibatasi {max_results} baris teratas)" if matches_count >= max_results else ""),
                "",
            ]
            if results:
                out_lines.extend(results)
            else:
                out_lines.append("Tidak ditemukan teks atau baris yang cocok.")

            return ToolResult(success=True, output="\n".join(out_lines))

        # -------------------------------------------------------------------
        # 11. Action: COPY (Copy file or directory)
        # -------------------------------------------------------------------
        elif action in ("copy", "cp"):
            if not source_path or not dest_path:
                return ToolResult(
                    success=False,
                    output="",
                    error="Parameter 'source_path' dan 'destination_path' wajib diisi untuk aksi copy.",
                )

            # Security check
            is_exfil, exfil_reason = permission_manager.check_credential_exfiltration(source_path)
            if is_exfil:
                return ToolResult(success=False, output="", error=exfil_reason)

            if not os.path.exists(source_path):
                return ToolResult(success=False, output="", error=f"Berkas sumber tidak ditemukan: {source_path}")

            overwrite = kwargs.get("overwrite", True)
            if os.path.exists(dest_path) and not overwrite:
                return ToolResult(success=False, output="", error=f"Tujuan sudah ada dan overwrite=False: {dest_path}")

            try:
                dest_parent = os.path.dirname(dest_path)
                if dest_parent and not os.path.exists(dest_parent):
                    os.makedirs(dest_parent, exist_ok=True)

                if os.path.isdir(source_path):
                    if os.path.exists(dest_path):
                        shutil.rmtree(dest_path)
                    shutil.copytree(source_path, dest_path)
                else:
                    shutil.copy2(source_path, dest_path)

                res_text = (
                    f"Berhasil Menyalin Data\n"
                    f"• Dari (Sumber): {source_path}\n"
                    f"• Ke (Tujuan): {dest_path}\n"
                    f"• Tipe: {'Direktori' if os.path.isdir(dest_path) else 'Berkas'}"
                )
                return ToolResult(success=True, output=res_text)
            except Exception as e:
                return ToolResult(success=False, output="", error=f"Gagal menyalin: {str(e)}")

        # -------------------------------------------------------------------
        # 12. Action: MOVE (Move or rename file or directory)
        # -------------------------------------------------------------------
        elif action in ("move", "mv", "rename"):
            if not source_path or not dest_path:
                return ToolResult(
                    success=False,
                    output="",
                    error="Parameter 'source_path' dan 'destination_path' wajib diisi untuk aksi move/rename.",
                )

            is_exfil, exfil_reason = permission_manager.check_credential_exfiltration(source_path)
            if is_exfil:
                return ToolResult(success=False, output="", error=exfil_reason)

            if not os.path.exists(source_path):
                return ToolResult(success=False, output="", error=f"Berkas sumber tidak ditemukan: {source_path}")

            overwrite = kwargs.get("overwrite", True)
            if os.path.exists(dest_path) and not overwrite:
                return ToolResult(success=False, output="", error=f"Tujuan sudah ada dan overwrite=False: {dest_path}")

            try:
                dest_parent = os.path.dirname(dest_path)
                if dest_parent and not os.path.exists(dest_parent):
                    os.makedirs(dest_parent, exist_ok=True)

                if os.path.exists(dest_path) and overwrite:
                    if os.path.isdir(dest_path):
                        shutil.rmtree(dest_path)
                    else:
                        os.remove(dest_path)

                shutil.move(source_path, dest_path)

                res_text = (
                    f"Berhasil Memindahkan / Mengganti Nama\n"
                    f"• Dari: {source_path}\n"
                    f"• Ke: {dest_path}"
                )
                return ToolResult(success=True, output=res_text)
            except Exception as e:
                return ToolResult(success=False, output="", error=f"Gagal memindahkan berkas: {str(e)}")

        # -------------------------------------------------------------------
        # 13. Action: MAKE_DIR (Create directory and parents)
        # -------------------------------------------------------------------
        elif action in ("make_dir", "mkdir"):
            if not target_path:
                return ToolResult(success=False, output="", error="Parameter 'path' wajib diisi untuk make_dir.")

            if os.path.exists(target_path):
                return ToolResult(success=True, output=f"Direktori sudah ada sebelumnya: {target_path}")

            try:
                os.makedirs(target_path, exist_ok=True)
                return ToolResult(success=True, output=f"Berhasil membuat direktori baru: {target_path}")
            except Exception as e:
                return ToolResult(success=False, output="", error=f"Gagal membuat direktori: {str(e)}")

        # -------------------------------------------------------------------
        # 14. Action: CHECKSUM (Calculate MD5, SHA1, SHA256 hashes)
        # -------------------------------------------------------------------
        elif action in ("checksum", "hash"):
            if not target_path:
                return ToolResult(success=False, output="", error="Parameter 'path' wajib diisi untuk checksum.")

            is_exfil, exfil_reason = permission_manager.check_credential_exfiltration(target_path)
            if is_exfil:
                return ToolResult(success=False, output="", error=exfil_reason)

            if not os.path.isfile(target_path):
                return ToolResult(success=False, output="", error=f"Target harus berupa file reguler: {target_path}")

            try:
                h_md5 = hashlib.md5()
                h_sha1 = hashlib.sha1()
                h_sha256 = hashlib.sha256()

                with open(target_path, "rb") as f:
                    while chunk := f.read(65536):
                        h_md5.update(chunk)
                        h_sha1.update(chunk)
                        h_sha256.update(chunk)

                res_text = (
                    f"Nilai Hash Verifikasi Integritas: {os.path.basename(target_path)}\n"
                    f"• Path: {target_path}\n"
                    f"• Ukuran: {_format_size(os.path.getsize(target_path))}\n"
                    f"• MD5: {h_md5.hexdigest()}\n"
                    f"• SHA-1: {h_sha1.hexdigest()}\n"
                    f"• SHA-256: {h_sha256.hexdigest()}"
                )
                return ToolResult(success=True, output=res_text)
            except Exception as e:
                return ToolResult(success=False, output="", error=f"Gagal menghitung hash berkas: {str(e)}")

        # -------------------------------------------------------------------
        # 15. Action: TREE (Hierarchical directory tree structure)
        # -------------------------------------------------------------------
        elif action == "tree":
            target_dir = target_path or os.getcwd()
            if not os.path.exists(target_dir):
                return ToolResult(success=False, output="", error=f"Direktori tidak ditemukan: {target_dir}")

            if not os.path.isdir(target_dir):
                return ToolResult(success=False, output="", error=f"Target tree harus berupa direktori: {target_dir}")

            max_depth = kwargs.get("max_depth", 3)
            show_hidden = kwargs.get("show_hidden", False)

            lines_out = [f"Struktur Direktori: {target_dir}", ""]
            dir_count = 0
            file_count = 0

            def _build_tree(curr_path: str, prefix: str = "", depth: int = 0) -> None:
                nonlocal dir_count, file_count
                if depth >= max_depth:
                    return

                try:
                    entries = sorted(os.listdir(curr_path))
                except Exception:
                    return

                filtered = [e for e in entries if show_hidden or not e.startswith(".")]
                total = len(filtered)

                for idx, entry in enumerate(filtered):
                    is_last = (idx == total - 1)
                    connector = "└── " if is_last else "├── "
                    child_path = os.path.join(curr_path, entry)
                    is_child_dir = os.path.isdir(child_path)

                    if is_child_dir:
                        dir_count += 1
                        lines_out.append(f"{prefix}{connector}{entry}/")
                        new_prefix = prefix + ("    " if is_last else "│   ")
                        _build_tree(child_path, new_prefix, depth + 1)
                    else:
                        file_count += 1
                        lines_out.append(f"{prefix}{connector}{entry}")

            _build_tree(target_dir, "", 0)
            lines_out.append("")
            lines_out.append(f"Total: {dir_count} direktori, {file_count} berkas terdaftar.")
            return ToolResult(success=True, output="\n".join(lines_out))

        # -------------------------------------------------------------------
        # 16. Action: EXTRACT_ARCHIVE (Safely extract zip/tar archives)
        # -------------------------------------------------------------------
        elif action == "extract_archive":
            archive_path = target_path or source_path
            if not archive_path:
                return ToolResult(success=False, output="", error="Parameter 'path' wajib diisi untuk aksi extract_archive.")

            if not os.path.exists(archive_path):
                return ToolResult(success=False, output="", error=f"Berkas arsip tidak ditemukan: {archive_path}")

            out_dir = dest_path or kwargs.get("output_dir") or os.getcwd()
            out_dir = os.path.abspath(os.path.expanduser(out_dir))
            os.makedirs(out_dir, exist_ok=True)

            try:
                extracted = []
                ext_l = archive_path.lower()
                if ext_l.endswith(".zip"):
                    with zipfile.ZipFile(archive_path, "r") as z:
                        for m in z.infolist():
                            if m.is_dir():
                                continue
                            clean_rel = os.path.normpath(m.filename).lstrip("/\\")
                            if ".." in clean_rel.split(os.sep):
                                continue
                            dest = os.path.abspath(os.path.join(out_dir, clean_rel))
                            if not dest.startswith(out_dir):
                                continue
                            os.makedirs(os.path.dirname(dest), exist_ok=True)
                            with z.open(m) as src, open(dest, "wb") as dst:
                                shutil.copyfileobj(src, dst)
                            extracted.append(dest)
                elif ext_l.endswith((".tar.xz", ".tar.gz", ".tar.bz2", ".tar", ".tgz")):
                    with tarfile.open(archive_path, "r:*") as t:
                        for m in t.getmembers():
                            if not m.isfile():
                                continue
                            clean_rel = os.path.normpath(m.name).lstrip("/\\")
                            if ".." in clean_rel.split(os.sep):
                                continue
                            dest = os.path.abspath(os.path.join(out_dir, clean_rel))
                            if not dest.startswith(out_dir):
                                continue
                            os.makedirs(os.path.dirname(dest), exist_ok=True)
                            fobj = t.extractfile(m)
                            if fobj:
                                with open(dest, "wb") as dst:
                                    shutil.copyfileobj(fobj, dst)
                                extracted.append(dest)
                else:
                    return ToolResult(
                        success=False,
                        output="",
                        error=f"Format arsip '{archive_path}' tidak didukung. Didukung: .zip, .tar.xz, .tar.gz, .tar.bz2, .tar",
                    )

                rel_target = os.path.relpath(out_dir, os.getcwd()) if out_dir.startswith(os.getcwd()) else out_dir
                return ToolResult(
                    success=True,
                    output=(
                        f"Ekstraksi Arsip Selesai: {os.path.basename(archive_path)}\n\n"
                        f"• Direktori Tujuan: {rel_target}\n"
                        f"• Total Berkas Diekstrak: {len(extracted)} berkas\n"
                        f"• Status: Berhasil diekstrak."
                    ),
                )
            except Exception as e:
                return ToolResult(success=False, output="", error=f"Gagal mengekstrak arsip: {e}")

        # -------------------------------------------------------------------
        # 17. Action: SEND_FILE (Send file to Telegram chat)
        # -------------------------------------------------------------------
        elif action in ("send_file", "send_document"):
            raw_path = kwargs.get("path")
            if not raw_path:
                return ToolResult(
                    success=False,
                    output="",
                    error="Parameter 'path' wajib diisi untuk action 'send_file'.",
                )

            target = _resolve_safe_path(str(raw_path))
            from src.tools.path_security import validate_path
            ok, msg, validated_p = validate_path(
                target,
                check_credentials=True,
                check_protected=True,
            )
            if not ok or not validated_p:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Akses berkas ditolak: {msg}",
                )

            if not validated_p.exists():
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Berkas '{raw_path}' tidak ditemukan di lokasi: {validated_p}",
                )

            if validated_p.is_dir():
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Path '{raw_path}' adalah direktori. Hanya berkas yang dapat dikirimkan ke Telegram.",
                )

            file_size = validated_p.stat().st_size
            if file_size > 50 * 1024 * 1024:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Ukuran berkas ({_format_size(file_size)}) melebihi batas maksimal pengiriman dokumen Telegram Bot (50 MB).",
                )

            ext = validated_p.suffix.lower()
            media_type = "photo" if ext in (".jpg", ".jpeg", ".png", ".webp") else "document"

            return ToolResult(
                success=True,
                output=f"Berkas '{validated_p.name}' ({_format_size(file_size)}) berhasil disiapkan dan dikirimkan ke chat Telegram.",
                media_path=str(validated_p.resolve()),
                media_type=media_type,
            )

        else:
            return ToolResult(
                success=False,
                output="",
                error=(
                    f"Aksi '{action}' tidak dikenal. Aksi yang didukung: read, write, append, "
                    f"edit_lines, insert_lines, find_replace, delete, file_info, list_dir, "
                    f"search_text, copy, move, make_dir, checksum, tree, extract_archive, send_file."
                ),
            )
