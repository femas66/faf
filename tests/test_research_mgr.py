from __future__ import annotations

import json
import pathlib

import httpx
import pytest

from src.config import Settings, set_settings
from src.tools import default_registry
from src.tools import research_mgr
from src.tools.base import ToolContext
from src.tools.research_mgr import (
    PaperItem,
    PaperLibrary,
    ResearchPaperTool,
    format_apa,
    format_bibtex,
    format_ieee,
    merge_papers,
    parse_arxiv_feed,
    parse_s2_item,
    select_key_sections,
)
from src.tools.safe_http import UnsafeURLError, parse_xml_safely, safe_get

ATOM = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2401.01234v2</id>
    <published>2024-01-05T10:00:00Z</published>
    <title>MobileLLM:  Optimizing
      Small Models</title>
    <summary>  We study small models. </summary>
    <author><name>Alice Liu</name></author>
    <author><name>Bob Smith</name></author>
    <arxiv:doi>10.1000/mobilellm</arxiv:doi>
    <category term="cs.LG"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2402.00001v1</id>
    <published>2024-02-01T10:00:00Z</published>
    <title>Another Security Paper</title>
    <summary>About security.</summary>
    <author><name>Carol Jones</name></author>
    <category term="cs.CR"/>
  </entry>
</feed>"""

S2_JSON = {
    "data": [
        {
            "paperId": "abc123",
            "title": "MobileLLM: Optimizing Small Models",
            "year": 2024,
            "abstract": "We study small models on devices in depth.",
            "authors": [{"name": "Alice Liu"}, {"name": "Bob Smith"}],
            "externalIds": {"DOI": "10.1000/MobileLLM", "ArXiv": "2401.01234"},
            "citationCount": 120,
            "venue": "ICML",
            "openAccessPdf": {"url": "https://example.org/mobilellm.pdf"},
        }
    ]
}


@pytest.fixture(autouse=True)
def _setup(tmp_path, monkeypatch):
    set_settings(Settings(PAPERS_DIR=str(tmp_path / "papers"), RESEARCH_SUMMARY_MAX_CHARS=500))
    monkeypatch.setattr(research_mgr, "ARXIV_MIN_INTERVAL", 0.0)
    monkeypatch.setattr(research_mgr, "S2_BACKOFF", (0.0, 0.0))
    # hindari DNS nyata pada test
    monkeypatch.setattr("src.tools.safe_http._check_url_safety", _fake_safety)
    yield
    set_settings(Settings())


def _fake_safety(url: str, check_dangerous_extensions: bool = True):
    from src.tools.web_search import _check_url_safety

    if any(h in url for h in ("127.0.0.1", "169.254.", "localhost", "192.168.")):
        return _check_url_safety(url)
    return True, "ok", {}


def make_tool(tmp_path, handler) -> ResearchPaperTool:
    lib = PaperLibrary(str(tmp_path / "research.db"))
    return ResearchPaperTool(
        library=lib,
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


def ctx(chat_id: int = 1) -> ToolContext:
    return ToolContext(chat_id=chat_id, user_id=chat_id)


def default_handler(request: httpx.Request) -> httpx.Response:
    host = request.url.host
    if host == "export.arxiv.org":
        return httpx.Response(200, content=ATOM)
    if host == "api.semanticscholar.org":
        return httpx.Response(200, json=S2_JSON)
    if host == "doi.org":
        return httpx.Response(200, text="@article{fromdoi, title={X}}")
    return httpx.Response(404)


# ---------------------------------------------------------------------------
def test_registered_in_registry():
    assert default_registry.get("research_paper") is not None


def test_parse_arxiv_feed():
    papers = parse_arxiv_feed(ATOM)
    assert len(papers) == 2
    p = papers[0]
    assert p.arxiv_id == "2401.01234"
    assert p.title == "MobileLLM: Optimizing Small Models"
    assert p.year == 2024 and p.authors == ["Alice Liu", "Bob Smith"]
    assert p.doi == "10.1000/mobilellm"
    assert p.pdf_url == "https://arxiv.org/pdf/2401.01234"
    assert "cs.LG" in p.categories


def test_xml_entity_rejected():
    with pytest.raises(ValueError):
        parse_xml_safely(b'<?xml version="1.0"?><!DOCTYPE a [<!ENTITY x "y">]><a>&x;</a>')


def test_merge_dedup_by_doi_and_arxiv():
    arxiv = parse_arxiv_feed(ATOM)
    s2 = [parse_s2_item(S2_JSON["data"][0])]
    merged = merge_papers(arxiv, s2)
    assert len(merged) == 2  # paper pertama digabung
    first = merged[0]
    assert first.citation_count == 120
    assert first.s2_id == "abc123"
    assert "+" in first.source


def test_citation_formats():
    p = PaperItem(title="A Title", authors=["Alice Liu", "Bob Smith"], year=2024, doi="10.1/x", venue="ICML")
    bib = format_bibtex(p)
    assert bib.startswith("@article{liu2024a,")
    assert "doi = {10.1/x}" in bib
    assert "Liu, A., & Smith, B. (2024). A Title. ICML. https://doi.org/10.1/x" == format_apa(p)
    assert format_ieee(p).startswith('A. Liu and B. Smith, "A Title,"')


def test_select_key_sections_keeps_head_and_conclusion():
    text = "ABSTRACT start " + "x" * 3000 + "\n5. Conclusion\nFINAL WORDS " + "y" * 200 + "\nReferences\n[1] junk"
    out = select_key_sections(text, 600)
    assert out.startswith("ABSTRACT start")
    assert "FINAL WORDS" in out
    assert "junk" not in out
    assert len(out) < 800


def test_library_save_list_export(tmp_path):
    lib = PaperLibrary(str(tmp_path / "l.db"))
    p = PaperItem(title="Paper One", authors=["A B"], year=2023, doi="10.1/one")
    assert lib.save(1, p, tags=["ai"]) is True
    assert lib.save(1, p, tags=["sec"]) is False
    items = lib.list(1)
    assert len(items) == 1 and set(items[0].tags) == {"ai", "sec"}
    assert lib.list(2) == []
    assert lib.find(1, "10.1/one") is not None
    assert "@article" in lib.export_bib(1)


async def test_search_merges_and_caches(tmp_path):
    tool = make_tool(tmp_path, default_handler)
    res = await tool.execute(ctx(), action="search", query="small language model", limit=5)
    assert res.success
    assert "MobileLLM" in res.output and "120 sitasi" in res.output
    assert "Another Security Paper" in res.output
    # tidak ada markdown tebal
    assert "**" not in res.output
    assert len(tool._last_results[1]) == 2


async def test_search_year_filter(tmp_path):
    tool = make_tool(tmp_path, default_handler)
    res = await tool.execute(ctx(), action="search", query="x", year_from=2025)
    assert res.success and "Tidak ada paper" in res.output


async def test_search_falls_back_to_arxiv_on_s2_429(tmp_path):
    calls = {"s2": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.semanticscholar.org":
            calls["s2"] += 1
            return httpx.Response(429)
        return default_handler(request)

    tool = make_tool(tmp_path, handler)
    res = await tool.execute(ctx(), action="search", query="small models")
    assert res.success
    assert calls["s2"] == 3  # 1 + 2 retry
    assert "Semantic Scholar sedang tidak bisa diakses" in res.output
    assert "MobileLLM" in res.output


async def test_search_both_sources_down(tmp_path):
    tool = make_tool(tmp_path, lambda r: httpx.Response(500))
    res = await tool.execute(ctx(), action="search", query="x")
    assert not res.success and "tidak bisa diakses" in res.error


async def test_search_requires_query(tmp_path):
    tool = make_tool(tmp_path, default_handler)
    res = await tool.execute(ctx(), action="search")
    assert not res.success


async def test_cite_by_number_uses_doi_negotiation_then_fallback(tmp_path):
    tool = make_tool(tmp_path, default_handler)
    await tool.execute(ctx(), action="search", query="small")
    # nomor 1 punya DOI -> doi.org
    res = await tool.execute(ctx(), action="cite", paper_ref="1", style="bibtex")
    assert res.success and "fromdoi" in res.output

    tool2 = make_tool(tmp_path, lambda r: default_handler(r) if r.url.host != "doi.org" else httpx.Response(500))
    await tool2.execute(ctx(), action="search", query="small")
    res2 = await tool2.execute(ctx(), action="cite", paper_ref="1", style="apa")
    assert res2.success and "(2024)" in res2.output


async def test_cite_number_without_search(tmp_path):
    tool = make_tool(tmp_path, default_handler)
    res = await tool.execute(ctx(), action="cite", paper_ref="2")
    assert not res.success and "pencarian" in res.error


async def test_save_library_export(tmp_path):
    tool = make_tool(tmp_path, default_handler)
    await tool.execute(ctx(), action="search", query="small")
    saved = await tool.execute(ctx(), action="save", paper_ref="1", tag="llm", note="bagus")
    assert saved.success and "disimpan" in saved.output
    lib = await tool.execute(ctx(), action="library", tag="llm")
    assert "MobileLLM" in lib.output
    exp = await tool.execute(ctx(), action="export")
    assert exp.success and exp.media_type == "document"
    assert pathlib.Path(exp.media_path).read_text().count("@article") == 1


async def test_export_empty_library(tmp_path):
    tool = make_tool(tmp_path, default_handler)
    res = await tool.execute(ctx(), action="export")
    assert not res.success


async def test_resolve_by_arxiv_id(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.semanticscholar.org" and "/paper/ARXIV" in request.url.path:
            return httpx.Response(200, json=S2_JSON["data"][0])
        return default_handler(request)

    tool = make_tool(tmp_path, handler)
    res = await tool.execute(ctx(), action="detail", paper_ref="arXiv:2401.01234")
    assert res.success and "MobileLLM" in res.output and "ICML" in res.output


async def test_summarize_pdf_flow(tmp_path):
    # ekstraksi teks di-patch; yang diuji: unduh, validasi magic bytes, dan pemilihan bagian
    pdf_bytes = b"%PDF-1.4 fake"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host in ("example.org", "arxiv.org"):
            return httpx.Response(200, content=pdf_bytes, headers={"content-type": "application/pdf"})
        return default_handler(request)

    tool = make_tool(tmp_path, handler)
    await tool.execute(ctx(), action="search", query="small")
    import src.tools.research_mgr as rm

    orig = rm.extract_pdf_text
    rm.extract_pdf_text = lambda path, max_pages=60: "Abstract. " + "kata " * 400
    try:
        res = await tool.execute(ctx(), action="summarize", paper_ref="1")
    finally:
        rm.extract_pdf_text = orig
    assert res.success and "Isi paper:" in res.output and "TUGAS" in res.output


async def test_summarize_falls_back_to_abstract_when_pdf_fails(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host in ("example.org", "arxiv.org"):
            return httpx.Response(404)
        return default_handler(request)

    tool = make_tool(tmp_path, handler)
    await tool.execute(ctx(), action="search", query="small")
    res = await tool.execute(ctx(), action="summarize", paper_ref="1")
    assert res.success and "hanya dari abstrak" in res.output


async def test_summarize_rejects_non_pdf_content(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host in ("example.org", "arxiv.org"):
            return httpx.Response(200, content=b"<html>not pdf</html>")
        return default_handler(request)

    tool = make_tool(tmp_path, handler)
    await tool.execute(ctx(), action="search", query="small")
    res = await tool.execute(ctx(), action="summarize", paper_ref="1")
    assert "hanya dari abstrak" in res.output


# ---------------------------------------------------------------------------
# safe_http
# ---------------------------------------------------------------------------
async def test_safe_get_blocks_private_ip():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200))) as c:
        with pytest.raises(UnsafeURLError):
            await safe_get(c, "http://192.168.1.1/x.pdf", max_bytes=1000)
        with pytest.raises(UnsafeURLError):
            await safe_get(c, "http://127.0.0.1/", max_bytes=1000)


async def test_safe_get_blocks_redirect_to_private():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "good.example":
            return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data"})
        return httpx.Response(200, text="secret")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        with pytest.raises(UnsafeURLError):
            await safe_get(c, "https://good.example/file.pdf", max_bytes=1000)


async def test_safe_get_size_limit():
    big = httpx.Response(200, content=b"a" * 5000)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: big)) as c:
        with pytest.raises(Exception) as ei:
            await safe_get(c, "https://good.example/x", max_bytes=1000)
        assert "batas" in str(ei.value)
