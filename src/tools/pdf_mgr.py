from __future__ import annotations

import csv
import datetime
import io
import json
import logging
import os
import pathlib
import re
from typing import Any

from src.tools.base import BaseTool, ToolContext, ToolResult
from src.tools.path_security import (
    DEFAULT_DOCUMENTS_DIR,
    get_default_documents_dir,
    validate_document_path,
)

logger = logging.getLogger("faf_agent.tools.pdf_mgr")

try:
    import pypdf
except ImportError:
    pypdf = None  # type: ignore


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


def _parse_page_range(pages_str: str | None, max_pages: int) -> list[int]:
    """Parse 1-based page range string (e.g. '1-3,5', '10') to 0-based index list."""
    if not pages_str or not str(pages_str).strip():
        # Default first 5 pages if large document, or all pages if <= 5
        return list(range(min(5, max_pages)))

    result: set[int] = set()
    cleaned = str(pages_str).strip()
    for part in cleaned.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            chunks = part.split("-", 1)
            start_s, end_s = chunks[0].strip(), chunks[1].strip()
            start = int(start_s) if start_s.isdigit() else 1
            end = int(end_s) if end_s.isdigit() else max_pages
            for p in range(max(1, start), min(max_pages, end) + 1):
                result.add(p - 1)
        elif part.isdigit():
            p = int(part)
            if 1 <= p <= max_pages:
                result.add(p - 1)

    sorted_indices = sorted(list(result))
    return sorted_indices if sorted_indices else list(range(min(5, max_pages)))


def _extract_snippets(text: str, query: str, context_chars: int = 150, max_snippets: int = 3) -> list[str]:
    """Find query in text and extract contextual text snippets around matches."""
    if not text or not query:
        return []

    snippets: list[str] = []
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    matches = list(pattern.finditer(text))

    for m in matches[:max_snippets]:
        start = max(0, m.start() - context_chars)
        end = min(len(text), m.end() + context_chars)
        snippet = text[start:end].replace("\n", " ").strip()
        prefix = "..." if start > 0 else ""
        suffix = "..." if end < len(text) else ""
        snippets.append(f"{prefix}{snippet}{suffix}")

    return snippets


def _resolve_pdf_path(path_arg: str | None) -> tuple[bool, str, str]:
    """Resolve file path to an absolute existing PDF path in documents directory or filesystem.

    Returns:
        (is_valid: bool, resolved_path: str, error_message: str)
    """
    docs_dir = get_default_documents_dir()

    if not path_arg or not str(path_arg).strip():
        return False, "", "Parameter 'path' tidak boleh kosong."

    raw = str(path_arg).strip()

    # Case 1: Simple filename (e.g. 'skripsi.pdf') -> look in DEFAULT_DOCUMENTS_DIR
    if "/" not in raw and "\\" not in raw:
        candidate = docs_dir / raw
        if not candidate.exists() and not raw.lower().endswith(".pdf"):
            candidate_pdf = docs_dir / f"{raw}.pdf"
            if candidate_pdf.exists():
                candidate = candidate_pdf
        target_path = candidate
    else:
        # Case 2: Full or relative path
        expanded = os.path.expanduser(raw)
        target_path = pathlib.Path(expanded)
        if not target_path.exists() and not raw.lower().endswith(".pdf"):
            candidate_pdf = pathlib.Path(f"{expanded}.pdf")
            if candidate_pdf.exists():
                target_path = candidate_pdf

    ok, msg, validated = validate_document_path(target_path)
    if not ok:
        return False, "", f"Keamanan berkas: {msg}"

    resolved_str = str(validated)
    if not os.path.exists(resolved_str):
        return False, "", f"Berkas PDF tidak ditemukan: {resolved_str}"

    if os.path.isdir(resolved_str):
        return False, "", f"Path '{resolved_str}' adalah direktori, bukan berkas PDF."

    return True, resolved_str, ""


class PDFManagerTool(BaseTool):
    """Pengelola dan pembaca dokumen PDF cerdas berbasis pure-Python (pypdf)."""

    name = "pdf_manager"
    description = (
        "Pengelola dan pembaca dokumen PDF cerdas. Gunakan tool ini untuk melihat daftar dokumen PDF "
        "yang tersimpan di perpustakaan ('list_documents'), mencari topik/kata kunci di seluruh atau dokumen "
        "tertentu ('search_text'), membaca teks dari halaman tertentu ('read_pages'), memeriksa informasi/struktur "
        "dokumen ('get_info'), dan mengirimkan berkas PDF dari HP ke chat Telegram ('send_document')."
    )

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list_documents", "get_info", "search_text", "read_pages", "extract_tables", "send_document"],
                "description": (
                    "Aksi yang akan dilakukan: "
                    "'list_documents' (melihat berkas PDF yang ada), "
                    "'search_text' (mencari kata kunci/topik dalam dokumen), "
                    "'read_pages' (membaca teks halaman tertentu), "
                    "'get_info' (informasi metadata dan jumlah halaman), "
                    "'extract_tables' (ekstraksi tabel), "
                    "'send_document' (mengirimkan berkas PDF dari penyimpanan HP langsung ke chat Telegram sebagai dokumen)."
                ),
            },
            "path": {
                "type": "string",
                "description": (
                    "Nama file atau path lengkap dokumen PDF. Jika hanya nama file (misal 'skripsi.pdf'), "
                    "otomatis dicari di direktori dokumen (~/.faf_agent/documents). Opsional untuk 'search_text' "
                    "(jika kosong, mencari di SEMUA dokumen)."
                ),
            },
            "query": {
                "type": "string",
                "description": "Kata kunci atau topik yang ingin dicari (wajib untuk action 'search_text', misal 'Research Objective').",
            },
            "pages": {
                "type": "string",
                "description": "Rentang halaman yang ingin dibaca untuk 'read_pages' (misal: '1-3', '5', atau '10-15'). Default 1-5.",
            },
            "char_limit": {
                "type": "integer",
                "description": "Batas karakter maksimal teks yang diekstrak per halaman (default: 3000).",
            },
            "max_results": {
                "type": "integer",
                "description": "Jumlah maksimal halaman cocok yang dikembalikan per dokumen pada 'search_text' (default: 5).",
            },
        },
        "required": ["action"],
    }

    async def execute(self, context: ToolContext, **kwargs: Any) -> ToolResult:
        if pypdf is None:
            return ToolResult(
                success=False,
                output="",
                error="Library 'pypdf' belum terpasang. Pasang dengan: pip install pypdf",
            )

        action = kwargs.get("action", "").strip()

        if context.on_status_update:
            await context.on_status_update(f"● pdf_manager · {action}")

        # -------------------------------------------------------------------
        # 1. Action: LIST_DOCUMENTS
        # -------------------------------------------------------------------
        if action == "list_documents":
            docs_dir = get_default_documents_dir()
            pdf_files: list[pathlib.Path] = []

            # Check DEFAULT_DOCUMENTS_DIR
            if docs_dir.exists():
                pdf_files.extend(list(docs_dir.glob("*.pdf")))

            # Check optional custom path if provided
            custom_path = kwargs.get("path")
            if custom_path and os.path.isdir(os.path.expanduser(custom_path)):
                custom_dir = pathlib.Path(os.path.expanduser(custom_path))
                pdf_files.extend([p for p in custom_dir.glob("*.pdf") if p not in pdf_files])

            if not pdf_files:
                return ToolResult(
                    success=True,
                    output=(
                        f"Perpustakaan Dokumen PDF kosong ({docs_dir}).\n"
                        "Belum ada berkas PDF yang tersimpan. Pengguna dapat mengunggah dokumen PDF melalui chat Telegram."
                    ),
                )

            lines = [f"Daftar Dokumen PDF Tersimpan ({len(pdf_files)} berkas di {docs_dir}):\n"]
            for idx, p in enumerate(sorted(pdf_files, key=lambda x: x.name.lower()), 1):
                size_str = _format_size(p.stat().st_size)
                page_count_str = "Halaman tidak diketahui"
                title_str = ""
                try:
                    reader = pypdf.PdfReader(str(p))
                    page_count_str = f"{len(reader.pages)} halaman"
                    if reader.metadata and reader.metadata.title:
                        title_str = f" - Judul: '{reader.metadata.title}'"
                except Exception:
                    pass

                lines.append(f"{idx}. {p.name} ({size_str}, {page_count_str}){title_str}")

            return ToolResult(success=True, output="\n".join(lines))

        # -------------------------------------------------------------------
        # 2. Action: GET_INFO
        # -------------------------------------------------------------------
        elif action == "get_info":
            path_arg = kwargs.get("path")
            valid, pdf_path, err = _resolve_pdf_path(path_arg)
            if not valid:
                return ToolResult(success=False, output="", error=err)

            try:
                reader = pypdf.PdfReader(pdf_path)
                meta = reader.metadata or {}
                total_pages = len(reader.pages)
                file_size = _format_size(os.path.getsize(pdf_path))
                filename = os.path.basename(pdf_path)

                info_lines = [
                    f"Informasi Dokumen PDF: {filename}",
                    f"• Lokasi Berkas: {pdf_path}",
                    f"• Ukuran Berkas: {file_size}",
                    f"• Total Halaman: {total_pages}",
                    f"• Terenkripsi: {'Ya (Perlu Password)' if reader.is_encrypted else 'Tidak'}",
                ]

                if meta.title:
                    info_lines.append(f"• Judul Dokumen: {meta.title}")
                if meta.author:
                    info_lines.append(f"• Penulis: {meta.author}")
                if meta.subject:
                    info_lines.append(f"• Subjek: {meta.subject}")
                if meta.creator:
                    info_lines.append(f"• Program Pembuat: {meta.creator}")

                # Check outline / Table of contents if present
                try:
                    outline = reader.outline
                    if outline and isinstance(outline, list):
                        info_lines.append("\nStruktur Daftar Isi / Bab:")
                        for item in outline[:10]:
                            if hasattr(item, "title"):
                                info_lines.append(f"  - {item.title}")
                            elif isinstance(item, dict) and "title" in item:
                                info_lines.append(f"  - {item['title']}")
                except Exception:
                    pass

                return ToolResult(success=True, output="\n".join(info_lines))

            except Exception as e:
                logger.exception(f"Error reading PDF info: {e}")
                return ToolResult(success=False, output="", error=f"Gagal membaca informasi PDF: {str(e)}")

        # -------------------------------------------------------------------
        # 3. Action: SEARCH_TEXT
        # -------------------------------------------------------------------
        elif action == "search_text":
            query = kwargs.get("query", "").strip()
            if not query:
                return ToolResult(success=False, output="", error="Parameter 'query' wajib diisi untuk search_text.")

            path_arg = kwargs.get("path")
            max_results = max(1, min(20, int(kwargs.get("max_results", 5))))

            target_pdfs: list[str] = []
            if path_arg and str(path_arg).strip().lower() not in ("all", "*"):
                valid, pdf_path, err = _resolve_pdf_path(path_arg)
                if not valid:
                    return ToolResult(success=False, output="", error=err)
                target_pdfs.append(pdf_path)
            else:
                docs_dir = get_default_documents_dir()
                if docs_dir.exists():
                    target_pdfs = [str(p) for p in sorted(docs_dir.glob("*.pdf"))]

            if not target_pdfs:
                return ToolResult(
                    success=False,
                    output="",
                    error="Tidak ada berkas PDF untuk dicari. Silakan unggah dokumen PDF terlebih dahulu.",
                )

            search_results = []
            total_matches_count = 0

            for pdf_path in target_pdfs:
                filename = os.path.basename(pdf_path)
                try:
                    reader = pypdf.PdfReader(pdf_path)
                    doc_matches = []

                    for page_idx, page in enumerate(reader.pages):
                        page_text = page.extract_text() or ""
                        if query.lower() in page_text.lower():
                            snippets = _extract_snippets(page_text, query, context_chars=140, max_snippets=2)
                            doc_matches.append({
                                "page": page_idx + 1,
                                "snippets": snippets,
                            })
                            if len(doc_matches) >= max_results:
                                break

                    if doc_matches:
                        total_matches_count += len(doc_matches)
                        search_results.append({
                            "file": filename,
                            "path": pdf_path,
                            "matches": doc_matches,
                        })

                except Exception as e:
                    logger.warning(f"Failed to search in PDF {filename}: {e}")

            if not search_results:
                return ToolResult(
                    success=True,
                    output=f"Kata kunci '{query}' tidak ditemukan dalam {len(target_pdfs)} dokumen PDF yang diperiksa.",
                )

            out_lines = [
                f"Hasil Pencarian untuk '{query}' (Ditemukan di {len(search_results)} dokumen, {total_matches_count} halaman):\n"
            ]

            for doc in search_results:
                out_lines.append(f"Dokumen: {doc['file']} ({doc['path']})")
                for m in doc["matches"]:
                    page_num = m["page"]
                    out_lines.append(f"  • Halaman {page_num}:")
                    for snip in m["snippets"]:
                        out_lines.append(f'    "{snip}"')
                out_lines.append("")

            out_lines.append("Tip: Gunakan action 'read_pages' dengan nomor halaman di atas untuk membaca konteks lengkap.")
            return ToolResult(success=True, output="\n".join(out_lines))

        # -------------------------------------------------------------------
        # 4. Action: READ_PAGES
        # -------------------------------------------------------------------
        elif action == "read_pages":
            path_arg = kwargs.get("path")
            valid, pdf_path, err = _resolve_pdf_path(path_arg)
            if not valid:
                return ToolResult(success=False, output="", error=err)

            pages_arg = kwargs.get("pages")
            char_limit = max(50, min(10000, int(kwargs.get("char_limit", 3000))))

            try:
                reader = pypdf.PdfReader(pdf_path)
                total_pages = len(reader.pages)
                page_indices = _parse_page_range(pages_arg, total_pages)
                filename = os.path.basename(pdf_path)

                if not page_indices:
                    return ToolResult(
                        success=False,
                        output="",
                        error=f"Rentang halaman '{pages_arg}' tidak valid. Dokumen memiliki {total_pages} halaman.",
                    )

                out_lines = [
                    f"Isi Teks Dokumen: {filename} (Halaman {', '.join(str(p + 1) for p in page_indices)} dari total {total_pages})\n"
                ]

                total_extracted_chars = 0
                for idx in page_indices:
                    page = reader.pages[idx]
                    page_text = page.extract_text() or ""
                    clean_page_text = page_text.strip()

                    if len(clean_page_text) > char_limit:
                        clean_page_text = clean_page_text[:char_limit] + "\n... [Teks dipotong untuk efisiensi konteks]"

                    total_extracted_chars += len(clean_page_text)
                    out_lines.append(f"--- Halaman {idx + 1} ---")
                    if clean_page_text:
                        out_lines.append(clean_page_text)
                    else:
                        out_lines.append("[Halaman tidak memuat teks atau berupa gambar hasil scan]")
                    out_lines.append("")

                if total_extracted_chars == 0:
                    out_lines.append(
                        "Catatan: Dokumen ini tampaknya berupa PDF hasil pemindaian (scanned PDF) tanpa layer teks digital. "
                        "Gunakan tool 'ocr' untuk mengekstrak teks dari gambar halaman tersebut."
                    )

                return ToolResult(success=True, output="\n".join(out_lines))

            except Exception as e:
                logger.exception(f"Error reading pages from PDF: {e}")
                return ToolResult(success=False, output="", error=f"Gagal membaca halaman PDF: {str(e)}")

        # -------------------------------------------------------------------
        # 5. Action: EXTRACT_TABLES
        # -------------------------------------------------------------------
        elif action == "extract_tables":
            path_arg = kwargs.get("path")
            valid, pdf_path, err = _resolve_pdf_path(path_arg)
            if not valid:
                return ToolResult(success=False, output="", error=err)

            try:
                import pdfplumber
            except ImportError:
                return ToolResult(
                    success=False,
                    output="",
                    error=(
                        "Library 'pdfplumber' diperlukan untuk ekstraksi tabel terstruktur. "
                        "Pasang dengan: pip install pdfplumber. Sebagai alternatif, gunakan 'read_pages' untuk membaca teks biasa."
                    ),
                )

            pages_arg = kwargs.get("pages")
            filename = os.path.basename(pdf_path)

            try:
                with pdfplumber.open(pdf_path) as pdf:
                    total_pages = len(pdf.pages)
                    page_indices = _parse_page_range(pages_arg, total_pages)
                    extracted_tables = []

                    for idx in page_indices:
                        page = pdf.pages[idx]
                        tables = page.extract_tables()
                        for t_idx, table in enumerate(tables):
                            cleaned_rows = [
                                [str(cell).strip() if cell is not None else "" for cell in row]
                                for row in table
                            ]
                            extracted_tables.append((idx + 1, t_idx + 1, cleaned_rows))

                    if not extracted_tables:
                        return ToolResult(
                            success=True,
                            output=f"Tidak ditemukan tabel terstruktur pada halaman yang diperiksa di '{filename}'.",
                        )

                    out_lines = [f"Tabel Terdeteksi pada '{filename}':\n"]
                    for page_num, t_num, rows in extracted_tables:
                        out_lines.append(f"Tabel {t_num} (Halaman {page_num}, {len(rows)} baris):")
                        for r in rows[:15]:
                            out_lines.append(" | ".join(r))
                        if len(rows) > 15:
                            out_lines.append(f"... ({len(rows) - 15} baris lainnya dipotong)")
                        out_lines.append("")

                    return ToolResult(success=True, output="\n".join(out_lines))

            except Exception as e:
                logger.exception(f"Error extracting tables: {e}")
                return ToolResult(success=False, output="", error=f"Gagal mengekstrak tabel: {str(e)}")

        # -------------------------------------------------------------------
        # 6. Action: SEND_DOCUMENT (Send PDF to Telegram)
        # -------------------------------------------------------------------
        elif action in ("send_document", "send_pdf"):
            path_arg = kwargs.get("path")
            if not path_arg:
                return ToolResult(
                    success=False,
                    output="",
                    error="Parameter 'path' (nama berkas atau path lengkap PDF) wajib diisi untuk action 'send_document'.",
                )

            is_valid, resolved_path, err_msg = _resolve_pdf_path(str(path_arg))
            if not is_valid:
                return ToolResult(
                    success=False,
                    output="",
                    error=err_msg,
                )

            pdf_file = pathlib.Path(resolved_path)
            file_size_bytes = pdf_file.stat().st_size
            if file_size_bytes > 50 * 1024 * 1024:
                return ToolResult(
                    success=False,
                    output="",
                    error=(
                        f"Ukuran berkas PDF ({_format_size(file_size_bytes)}) melebihi batas "
                        "maksimal pengiriman dokumen Telegram Bot (50 MB)."
                    ),
                )

            size_str = _format_size(file_size_bytes)
            return ToolResult(
                success=True,
                output=f"Berkas PDF '{pdf_file.name}' ({size_str}) berhasil disiapkan dan dikirimkan ke chat Telegram.",
                media_path=str(pdf_file.resolve()),
                media_type="document",
            )

        return ToolResult(
            success=False,
            output="",
            error=f"Aksi '{action}' tidak dikenali. Pilih: 'list_documents', 'get_info', 'search_text', 'read_pages', 'extract_tables', 'send_document'.",
        )
