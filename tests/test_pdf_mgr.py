from __future__ import annotations

import asyncio
import io
import os
import pathlib
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from src.config import Settings, set_settings
from src.tools.base import ToolContext
from src.tools.pdf_mgr import (
    PDFManagerTool,
    _format_size,
    _parse_page_range,
    _extract_snippets,
    _resolve_pdf_path,
)
from src.tools.path_security import (
    DEFAULT_DOCUMENTS_DIR,
    get_default_documents_dir,
    validate_document_path,
)
from src.tools import default_registry


def create_sample_pdf(filepath: str, pages_text: list[str], title: str = "Test Doc", author: str = "Test Author") -> None:
    """Helper to generate a valid test PDF file with text content, metadata, and outline."""
    writer = PdfWriter()
    for i, text in enumerate(pages_text):
        page = writer.add_blank_page(width=612, height=792)
        stream_obj = DecodedStreamObject()
        # Clean text for PDF literal string
        safe_text = text.replace("(", r"\(").replace(")", r"\)")
        stream_obj.set_data(f"BT /F1 12 Tf 50 700 Td ({safe_text}) Tj ET".encode("latin1"))
        page[NameObject("/Contents")] = stream_obj
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({
                NameObject("/F1"): DictionaryObject({
                    NameObject("/Type"): NameObject("/Font"),
                    NameObject("/Subtype"): NameObject("/Type1"),
                    NameObject("/BaseFont"): NameObject("/Helvetica"),
                })
            })
        })
        writer.add_outline_item(f"Bab {i + 1}", i)

    writer.add_metadata({
        "/Title": title,
        "/Author": author,
    })

    with open(filepath, "wb") as f:
        writer.write(f)


@pytest.fixture(autouse=True)
def setup_test_settings():
    test_settings = Settings(
        TELEGRAM_BOT_TOKEN="test_token_12345",
        ALLOWED_TELEGRAM_USER_IDS="111,222,333",
        OPENAI_API_KEY="test_openai_key",
    )
    set_settings(test_settings)
    return test_settings


@pytest.fixture
def mock_context():
    return ToolContext(
        chat_id=12345,
        user_id=111,
        message_id=99,
        on_status_update=AsyncMock(),
    )


@pytest.fixture
def temp_docs_dir(tmp_path, monkeypatch):
    docs_dir = tmp_path / "documents"
    docs_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("src.tools.path_security.DEFAULT_DOCUMENTS_DIR", str(docs_dir))
    monkeypatch.setattr("src.tools.pdf_mgr.DEFAULT_DOCUMENTS_DIR", str(docs_dir))
    monkeypatch.setattr("src.bot.handlers.chat.get_default_documents_dir", lambda: docs_dir)
    return docs_dir


def test_tool_registered_in_default_registry():
    tool = default_registry.get("pdf_manager")
    assert tool is not None
    assert isinstance(tool, PDFManagerTool)
    assert tool.name == "pdf_manager"


def test_format_size():
    assert _format_size(500) == "500 B"
    assert _format_size(2048) == "2.00 KB"
    assert _format_size(1024 * 1024 * 5) == "5.00 MB"


def test_parse_page_range():
    assert _parse_page_range(None, 10) == [0, 1, 2, 3, 4]
    assert _parse_page_range("1-3", 10) == [0, 1, 2]
    assert _parse_page_range("2", 10) == [1]
    assert _parse_page_range("1,3,5", 10) == [0, 2, 4]
    assert _parse_page_range("invalid", 10) == [0, 1, 2, 3, 4]


def test_extract_snippets():
    text = "Bab 1 Metodologi. Dalam menyusun skripsi, penting memahami Research Objective secara spesifik. Bab 2 Penutup."
    snippets = _extract_snippets(text, "Research Objective", context_chars=20)
    assert len(snippets) == 1
    assert "Research Objective" in snippets[0]


@pytest.mark.asyncio
async def test_pdf_mgr_list_documents(temp_docs_dir, mock_context):
    tool = PDFManagerTool()

    # Empty dir
    res = await tool.execute(mock_context, action="list_documents")
    assert res.success is True
    assert "Belum ada berkas PDF" in res.output

    # Add sample PDF
    pdf_path = temp_docs_dir / "research_guide.pdf"
    create_sample_pdf(str(pdf_path), ["Konten Panduan"], title="Buku Panduan Riset")

    res = await tool.execute(mock_context, action="list_documents")
    assert res.success is True
    assert "research_guide.pdf" in res.output
    assert "Buku Panduan Riset" in res.output
    assert "1 halaman" in res.output


@pytest.mark.asyncio
async def test_pdf_mgr_get_info(temp_docs_dir, mock_context):
    tool = PDFManagerTool()
    pdf_path = temp_docs_dir / "thesis_guide.pdf"
    create_sample_pdf(
        str(pdf_path),
        ["Bab 1 Latar Belakang", "Bab 2 Tinjauan Pustaka"],
        title="Panduan Skripsi 2026",
        author="Dr. Akademisi",
    )

    # Info by filename in default dir
    res = await tool.execute(mock_context, action="get_info", path="thesis_guide.pdf")
    assert res.success is True
    assert "thesis_guide.pdf" in res.output
    assert "Panduan Skripsi 2026" in res.output
    assert "Dr. Akademisi" in res.output
    assert "Total Halaman: 2" in res.output

    # Info for nonexistent file
    res_err = await tool.execute(mock_context, action="get_info", path="non_existent.pdf")
    assert res_err.success is False
    assert "tidak ditemukan" in res_err.error


@pytest.mark.asyncio
async def test_pdf_mgr_search_text(temp_docs_dir, mock_context):
    tool = PDFManagerTool()
    pdf_path = temp_docs_dir / "methodology.pdf"
    create_sample_pdf(
        str(pdf_path),
        [
            "Pendahuluan tentang penelitian akademik",
            "Cara merumuskan Research Objective yang baik dan terukur",
            "Daftar pustaka",
        ],
        title="Metodologi Penelitian",
    )

    # Empty query error
    res_no_q = await tool.execute(mock_context, action="search_text", query="")
    assert res_no_q.success is False
    assert "query" in res_no_q.error

    # Search specific file
    res = await tool.execute(mock_context, action="search_text", path="methodology.pdf", query="Research Objective")
    assert res.success is True
    assert "methodology.pdf" in res.output
    assert "Halaman 2" in res.output
    assert "Research Objective" in res.output

    # Search all files without path
    res_all = await tool.execute(mock_context, action="search_text", query="Research Objective")
    assert res_all.success is True
    assert "methodology.pdf" in res_all.output
    assert "Halaman 2" in res_all.output

    # Query not found
    res_not_found = await tool.execute(mock_context, action="search_text", path="methodology.pdf", query="Quantum Physics")
    assert res_not_found.success is True
    assert "tidak ditemukan" in res_not_found.output


@pytest.mark.asyncio
async def test_pdf_mgr_read_pages(temp_docs_dir, mock_context):
    tool = PDFManagerTool()
    pdf_path = temp_docs_dir / "paper.pdf"
    create_sample_pdf(
        str(pdf_path),
        [
            "Halaman pertama pendahuluan",
            "Halaman kedua pembahasan Research Objective dengan penjelasan yang sangat panjang dan rinci untuk menguji pemotongan batas karakter konteks LLM.",
            "Halaman ketiga kesimpulan",
        ],
    )

    # Read specific page 2
    res = await tool.execute(mock_context, action="read_pages", path="paper.pdf", pages="2")
    assert res.success is True
    assert "Halaman 2" in res.output
    assert "Research Objective" in res.output
    assert "Halaman 1" not in res.output

    # Read range 1-2
    res_range = await tool.execute(mock_context, action="read_pages", path="paper.pdf", pages="1-2")
    assert res_range.success is True
    assert "Halaman 1" in res_range.output
    assert "Halaman 2" in res_range.output
    assert "Halaman 3" not in res_range.output

    # Truncation check
    res_trunc = await tool.execute(mock_context, action="read_pages", path="paper.pdf", pages="2", char_limit=50)
    assert res_trunc.success is True
    assert "dipotong" in res_trunc.output


def test_pdf_security_validation(temp_docs_dir):
    # Path traversal attempt outside base directory
    traversal_path = temp_docs_dir / ".." / "outside.pdf"
    ok, msg, _ = validate_document_path(traversal_path, default_storage_dir=temp_docs_dir)
    assert ok is False
    assert "Path Traversal" in msg or "luar batas" in msg

    # Path to sensitive files
    env_path = temp_docs_dir / ".env"
    ok_env, msg_env, _ = validate_document_path(env_path)
    assert ok_env is False
    assert "kredensial rahasia" in msg_env or "Akses ditolak" in msg_env


@pytest.mark.asyncio
async def test_telegram_document_upload_handling(temp_docs_dir, monkeypatch):
    """Test Telegram chat handler receiving document with/without caption."""
    from src.bot.handlers.chat import handle_chat_message
    from telegram import Update, Message, Document, Chat, User

    # Mock update and message
    mock_chat = Chat(id=111, type="private")
    mock_user = User(id=111, is_bot=False, first_name="User")

    sample_pdf_bytes = io.BytesIO()
    writer = PdfWriter()
    p = writer.add_blank_page(width=612, height=792)
    stream_obj = DecodedStreamObject()
    stream_obj.set_data(b"BT /F1 12 Tf 50 700 Td (Research Objective Sample) Tj ET")
    p[NameObject("/Contents")] = stream_obj
    writer.write(sample_pdf_bytes)
    sample_pdf_data = sample_pdf_bytes.getvalue()

    async def fake_download(custom_path: str):
        with open(custom_path, "wb") as f:
            f.write(sample_pdf_data)

    mock_tg_file = AsyncMock()
    mock_tg_file.download_to_drive = AsyncMock(side_effect=fake_download)

    mock_doc = MagicMock(spec=Document)
    mock_doc.file_name = "test_research.pdf"
    mock_doc.mime_type = "application/pdf"
    mock_doc.get_file = AsyncMock(return_value=mock_tg_file)

    mock_message = MagicMock(spec=Message)
    mock_message.message_id = 100
    mock_message.document = mock_doc
    mock_message.text = None
    mock_message.caption = "Bagaimana cara membuat Research Objective?"
    mock_message.reply_text = AsyncMock()

    mock_update = MagicMock(spec=Update)
    mock_update.effective_message = mock_message
    mock_update.effective_chat = mock_chat
    mock_update.effective_user = mock_user

    mock_context = MagicMock()

    # Mock agent.run
    with patch("src.bot.handlers.chat.agent.run", new_callable=AsyncMock) as mock_agent_run:
        from src.core.agent import AgentResponse
        mock_agent_run.return_value = AgentResponse(
            text="Berikut langkah membuat Research Objective berdasarkan dokumen yang diunggah.",
        )

        await handle_chat_message(mock_update, mock_context)

        # Verify download was called
        mock_doc.get_file.assert_awaited_once()
        mock_tg_file.download_to_drive.assert_awaited_once()

        # Verify agent.run received the injected document info and caption
        mock_agent_run.assert_awaited_once()
        call_kwargs = mock_agent_run.call_args[1]
        assert "test_research.pdf" in call_kwargs["user_message"]
        assert "Research Objective" in call_kwargs["user_message"]

    # Test upload WITHOUT caption -> quick confirmation reply without calling agent.run
    mock_message_nocap = MagicMock(spec=Message)
    mock_message_nocap.message_id = 101
    mock_message_nocap.document = mock_doc
    mock_message_nocap.text = None
    mock_message_nocap.caption = None
    mock_message_nocap.reply_text = AsyncMock()

    mock_update_nocap = MagicMock(spec=Update)
    mock_update_nocap.effective_message = mock_message_nocap
    mock_update_nocap.effective_chat = mock_chat
    mock_update_nocap.effective_user = mock_user

    with patch("src.bot.handlers.chat.agent.run", new_callable=AsyncMock) as mock_agent_run:
        await handle_chat_message(mock_update_nocap, mock_context)
        mock_agent_run.assert_not_awaited()
        mock_message_nocap.reply_text.assert_awaited_once()
        reply_call_text = mock_message_nocap.reply_text.call_args[0][0]
        assert "test_research.pdf" in reply_call_text
        assert "perpustakaan dokumen" in reply_call_text
