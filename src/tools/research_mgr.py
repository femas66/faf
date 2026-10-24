"""Paper Research Assistant: cari, ringkas, sitasi, dan simpan paper ilmiah (arXiv + Semantic Scholar)."""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import pathlib
import re
import sqlite3
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

import httpx

from src.config import get_settings
from src.tools.base import BaseTool, ToolContext, ToolResult
from src.tools.path_security import get_default_state_path, validate_document_path
from src.tools.safe_http import (
    ResponseTooLargeError,
    UnsafeURLError,
    parse_xml_safely,
    safe_get,
)

try:
    import pypdf
except ImportError:  # pragma: no cover
    pypdf = None  # type: ignore

logger = logging.getLogger("faf_agent.tools.research_mgr")

ARXIV_API = "https://export.arxiv.org/api/query"
S2_API = "https://api.semanticscholar.org/graph/v1"
S2_FIELDS = "title,authors,year,abstract,externalIds,citationCount,venue,openAccessPdf"
PRIORITY_CATEGORIES = {"cs.CR", "cs.AI", "cs.LG", "cs.CL", "cs.NI", "cs.SE"}

ARXIV_MIN_INTERVAL = 3.0  # detik antar request ke arXiv
S2_BACKOFF = (1.0, 2.0)  # jeda retry saat 429 (maks 2 retry)
API_MAX_BYTES = 5 * 1024 * 1024
MAX_PDF_PAGES = 60

_ATOM_NS = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
_DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")
_ARXIV_RE = re.compile(
    r"^(?:arxiv:)?(\d{4}\.\d{4,5}|[a-z\-]+(?:\.[A-Za-z]{2})?/\d{7})(?:v\d+)?$", re.IGNORECASE
)

_arxiv_lock = asyncio.Lock()
_arxiv_last = 0.0


async def _arxiv_throttle() -> None:
    global _arxiv_last
    async with _arxiv_lock:
        wait = ARXIV_MIN_INTERVAL - (time.monotonic() - _arxiv_last)
        if wait > 0:
            await asyncio.sleep(wait)
        _arxiv_last = time.monotonic()


# ---------------------------------------------------------------------------
# Model data
# ---------------------------------------------------------------------------
@dataclass
class PaperItem:
    title: str
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    abstract: str = ""
    doi: str | None = None
    arxiv_id: str | None = None
    s2_id: str | None = None
    citation_count: int | None = None
    venue: str | None = None
    pdf_url: str | None = None
    source: str = ""
    categories: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    rank: int = 999

    @property
    def paper_key(self) -> str:
        if self.doi:
            return self.doi.lower()
        if self.arxiv_id:
            return f"arxiv:{self.arxiv_id.lower()}"
        if self.s2_id:
            return f"s2:{self.s2_id}"
        return "title:" + hashlib.sha1(_norm_title(self.title).encode()).hexdigest()[:12]


def _norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()


def _clean_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


# ---------------------------------------------------------------------------
# Parsers & merging
# ---------------------------------------------------------------------------
def parse_arxiv_feed(xml_bytes: bytes) -> list[PaperItem]:
    root = parse_xml_safely(xml_bytes)
    papers: list[PaperItem] = []
    for idx, entry in enumerate(root.findall("a:entry", _ATOM_NS)):
        id_text = (entry.findtext("a:id", default="", namespaces=_ATOM_NS) or "").strip()
        m = re.search(r"abs/(.+?)(?:v\d+)?$", id_text)
        if not m:
            continue
        arxiv_id = m.group(1)
        title = _clean_ws(entry.findtext("a:title", default="", namespaces=_ATOM_NS))
        if not title:
            continue
        published = entry.findtext("a:published", default="", namespaces=_ATOM_NS) or ""
        year = int(published[:4]) if published[:4].isdigit() else None
        authors = [
            _clean_ws(a.findtext("a:name", default="", namespaces=_ATOM_NS))
            for a in entry.findall("a:author", _ATOM_NS)
        ]
        doi = (entry.findtext("arxiv:doi", default="", namespaces=_ATOM_NS) or "").strip() or None
        categories = [c.get("term", "") for c in entry.findall("a:category", _ATOM_NS) if c.get("term")]
        papers.append(
            PaperItem(
                title=title,
                authors=[a for a in authors if a],
                year=year,
                abstract=_clean_ws(entry.findtext("a:summary", default="", namespaces=_ATOM_NS)),
                doi=doi,
                arxiv_id=arxiv_id,
                pdf_url=f"https://arxiv.org/pdf/{arxiv_id}",
                venue="arXiv",
                source="arxiv",
                categories=categories,
                rank=idx,
            )
        )
    return papers


def parse_s2_item(data: dict[str, Any], rank: int = 999) -> PaperItem | None:
    title = _clean_ws(data.get("title") or "")
    if not title:
        return None
    ext = data.get("externalIds") or {}
    oa = data.get("openAccessPdf") or {}
    return PaperItem(
        title=title,
        authors=[a.get("name", "") for a in (data.get("authors") or []) if a.get("name")],
        year=data.get("year"),
        abstract=_clean_ws(data.get("abstract") or ""),
        doi=(ext.get("DOI") or None),
        arxiv_id=(ext.get("ArXiv") or None),
        s2_id=data.get("paperId"),
        citation_count=data.get("citationCount"),
        venue=(data.get("venue") or None),
        pdf_url=(oa.get("url") or None),
        source="semantic_scholar",
        rank=rank,
    )


def _merge_into(base: PaperItem, other: PaperItem) -> None:
    for attr in ("doi", "arxiv_id", "s2_id", "venue", "pdf_url", "year"):
        if not getattr(base, attr) and getattr(other, attr):
            setattr(base, attr, getattr(other, attr))
    if len(other.abstract) > len(base.abstract):
        base.abstract = other.abstract
    if not base.authors and other.authors:
        base.authors = other.authors
    if other.citation_count is not None:
        base.citation_count = max(base.citation_count or 0, other.citation_count)
    for c in other.categories:
        if c not in base.categories:
            base.categories.append(c)
    base.rank = min(base.rank, other.rank)
    if other.source and other.source not in base.source:
        base.source = f"{base.source}+{other.source}".strip("+")


def merge_papers(*groups: list[PaperItem]) -> list[PaperItem]:
    """Gabung hasil beberapa sumber dan buang duplikat (DOI, arXiv ID, atau judul)."""
    merged: list[PaperItem] = []
    by_doi: dict[str, PaperItem] = {}
    by_arxiv: dict[str, PaperItem] = {}
    by_title: dict[str, PaperItem] = {}
    for group in groups:
        for p in group:
            existing = (
                (p.doi and by_doi.get(p.doi.lower()))
                or (p.arxiv_id and by_arxiv.get(p.arxiv_id.lower()))
                or by_title.get(_norm_title(p.title))
            )
            if existing:
                _merge_into(existing, p)
                target = existing
            else:
                merged.append(p)
                target = p
            if target.doi:
                by_doi[target.doi.lower()] = target
            if target.arxiv_id:
                by_arxiv[target.arxiv_id.lower()] = target
            by_title[_norm_title(target.title)] = target
    return merged


def rank_papers(papers: list[PaperItem]) -> list[PaperItem]:
    def score(p: PaperItem) -> float:
        s = 1.0 / (1 + p.rank)
        if "+" in p.source:
            s += 1.0
        if set(p.categories) & PRIORITY_CATEGORIES:
            s += 0.5
        s += min(p.citation_count or 0, 1000) / 1000
        return s

    return sorted(papers, key=score, reverse=True)


# ---------------------------------------------------------------------------
# Sitasi
# ---------------------------------------------------------------------------
def _split_name(name: str) -> tuple[str, str]:
    """Mengembalikan (nama_belakang, inisial) dari 'Given Family'."""
    parts = name.replace(",", " ").split()
    if not parts:
        return "", ""
    if "," in name:
        last, given = name.split(",", 1)
        parts = given.split()
        initials = " ".join(f"{p[0]}." for p in parts if p)
        return last.strip(), initials
    last = parts[-1]
    initials = " ".join(f"{p[0]}." for p in parts[:-1] if p)
    return last, initials


def _bibtex_key(paper: PaperItem) -> str:
    last = _split_name(paper.authors[0])[0] if paper.authors else "anon"
    first_word = re.sub(r"[^a-z0-9]", "", (paper.title.split() or ["paper"])[0].lower())
    return re.sub(r"[^a-z0-9]", "", last.lower()) + str(paper.year or "nd") + first_word


def format_bibtex(paper: PaperItem) -> str:
    def esc(v: str) -> str:
        return v.replace("{", "\\{").replace("}", "\\}")

    fields = [
        f"  title = {{{esc(paper.title)}}}",
        f"  author = {{{' and '.join(esc(a) for a in paper.authors)}}}",
    ]
    if paper.year:
        fields.append(f"  year = {{{paper.year}}}")
    if paper.venue:
        fields.append(f"  journal = {{{esc(paper.venue)}}}")
    if paper.doi:
        fields.append(f"  doi = {{{paper.doi}}}")
    if paper.arxiv_id:
        fields.append(f"  eprint = {{{paper.arxiv_id}}}")
        fields.append("  archivePrefix = {arXiv}")
    return "@article{" + _bibtex_key(paper) + ",\n" + ",\n".join(fields) + "\n}"


def format_apa(paper: PaperItem) -> str:
    names = []
    for a in paper.authors:
        last, initials = _split_name(a)
        names.append(f"{last}, {initials}".strip(", "))
    if len(names) > 1:
        authors = ", ".join(names[:-1]) + ", & " + names[-1]
    else:
        authors = names[0] if names else "Anonim"
    out = f"{authors} ({paper.year or 'n.d.'}). {paper.title.rstrip('.')}."
    if paper.venue:
        out += f" {paper.venue}."
    if paper.doi:
        out += f" https://doi.org/{paper.doi}"
    elif paper.arxiv_id:
        out += f" https://arxiv.org/abs/{paper.arxiv_id}"
    return out


def format_ieee(paper: PaperItem) -> str:
    names = []
    for a in paper.authors:
        last, initials = _split_name(a)
        names.append(f"{initials} {last}".strip())
    if len(names) > 2:
        authors = ", ".join(names[:-1]) + ", and " + names[-1]
    else:
        authors = " and ".join(names) if names else "Anonim"
    out = f'{authors}, "{paper.title.rstrip(".")},"'
    if paper.venue:
        out += f" {paper.venue},"
    out += f" {paper.year or 'n.d.'}"
    if paper.doi:
        out += f", doi: {paper.doi}"
    elif paper.arxiv_id:
        out += f", arXiv:{paper.arxiv_id}"
    return out + "."


# ---------------------------------------------------------------------------
# PDF text extraction
# ---------------------------------------------------------------------------
def extract_pdf_text(path: str, max_pages: int = MAX_PDF_PAGES) -> str:
    if pypdf is None:
        raise RuntimeError("Library pypdf belum terpasang (pip install pypdf).")
    reader = pypdf.PdfReader(path)
    chunks: list[str] = []
    for page in reader.pages[:max_pages]:
        try:
            chunks.append(page.extract_text() or "")
        except Exception:  # halaman rusak jangan menggagalkan semuanya
            continue
    return "\n".join(chunks)


def select_key_sections(text: str, max_chars: int) -> str:
    """Prioritaskan awal dokumen (abstract/intro) dan bagian conclusion, buang referensi."""
    text = re.sub(r"[ \t]+", " ", text or "").strip()
    if len(text) <= max_chars:
        return text

    ref_match = None
    for ref_match in re.finditer(r"\n\s*(references|bibliography)\s*\n", text, re.IGNORECASE):
        pass
    body = text[: ref_match.start()] if ref_match else text
    if len(body) <= max_chars:
        return body

    head_budget = int(max_chars * 0.55)
    tail_budget = max_chars - head_budget
    concl = None
    for concl in re.finditer(r"\n\s*(?:\d+\.?\s*)?(conclusions?|discussion|kesimpulan)\b", body, re.IGNORECASE):
        pass
    tail_start = concl.start() if concl and concl.start() > head_budget else max(head_budget, len(body) - tail_budget)
    return body[:head_budget] + "\n[... bagian tengah dilewati ...]\n" + body[tail_start : tail_start + tail_budget]


# ---------------------------------------------------------------------------
# Perpustakaan SQLite
# ---------------------------------------------------------------------------
class PaperLibrary:
    """Perpustakaan paper pribadi. Akses dilindungi RLock, koneksi selalu ditutup."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._lock = threading.RLock()
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._run(self._init_schema)

    @staticmethod
    def _init_schema(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS papers (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id         INTEGER NOT NULL,
                paper_key       TEXT NOT NULL,
                title           TEXT NOT NULL,
                authors_json    TEXT NOT NULL,
                year            INTEGER,
                venue           TEXT,
                doi             TEXT,
                arxiv_id        TEXT,
                pdf_url         TEXT,
                local_pdf_path  TEXT,
                abstract        TEXT,
                summary         TEXT,
                citation_count  INTEGER,
                tags            TEXT,
                note            TEXT,
                created_at      TEXT NOT NULL,
                UNIQUE(chat_id, paper_key)
            )
            """
        )

    def _run(self, fn: Callable[[sqlite3.Connection], Any]) -> Any:
        with self._lock:
            with contextlib.closing(sqlite3.connect(self.db_path, timeout=10)) as conn:
                conn.row_factory = sqlite3.Row
                result = fn(conn)
                conn.commit()
                return result

    @staticmethod
    def _row_to_paper(row: sqlite3.Row) -> PaperItem:
        return PaperItem(
            title=row["title"],
            authors=json.loads(row["authors_json"] or "[]"),
            year=row["year"],
            abstract=row["abstract"] or "",
            doi=row["doi"],
            arxiv_id=row["arxiv_id"],
            citation_count=row["citation_count"],
            venue=row["venue"],
            pdf_url=row["pdf_url"],
            tags=[t for t in (row["tags"] or "").split(",") if t],
            source="library",
        )

    def save(
        self,
        chat_id: int,
        paper: PaperItem,
        note: str = "",
        tags: list[str] | None = None,
        summary: str = "",
        local_pdf_path: str | None = None,
    ) -> bool:
        """Simpan paper. Mengembalikan True jika baru, False jika memperbarui yang lama."""

        def op(conn: sqlite3.Connection) -> bool:
            existing = conn.execute(
                "SELECT tags, note, summary, local_pdf_path FROM papers WHERE chat_id=? AND paper_key=?",
                (chat_id, paper.paper_key),
            ).fetchone()
            merged_tags = list(dict.fromkeys((paper.tags or []) + (tags or [])))
            if existing:
                merged_tags = list(
                    dict.fromkeys([t for t in (existing["tags"] or "").split(",") if t] + merged_tags)
                )
                conn.execute(
                    "UPDATE papers SET tags=?, note=?, summary=?, local_pdf_path=? WHERE chat_id=? AND paper_key=?",
                    (
                        ",".join(merged_tags),
                        note or existing["note"],
                        summary or existing["summary"],
                        local_pdf_path or existing["local_pdf_path"],
                        chat_id,
                        paper.paper_key,
                    ),
                )
                return False
            conn.execute(
                """
                INSERT INTO papers (chat_id, paper_key, title, authors_json, year, venue, doi, arxiv_id,
                    pdf_url, local_pdf_path, abstract, summary, citation_count, tags, note, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    chat_id,
                    paper.paper_key,
                    paper.title,
                    json.dumps(paper.authors),
                    paper.year,
                    paper.venue,
                    paper.doi,
                    paper.arxiv_id,
                    paper.pdf_url,
                    local_pdf_path,
                    paper.abstract,
                    summary,
                    paper.citation_count,
                    ",".join(merged_tags),
                    note,
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
            return True

        return bool(self._run(op))

    def list(self, chat_id: int, tag: str | None = None) -> list[PaperItem]:
        def op(conn: sqlite3.Connection) -> list[PaperItem]:
            rows = conn.execute(
                "SELECT * FROM papers WHERE chat_id=? ORDER BY id DESC", (chat_id,)
            ).fetchall()
            papers = [self._row_to_paper(r) for r in rows]
            if tag:
                papers = [p for p in papers if tag.lower() in [t.lower() for t in p.tags]]
            return papers

        return self._run(op)

    def find(self, chat_id: int, ref: str) -> PaperItem | None:
        ref_l = ref.lower().strip()

        def op(conn: sqlite3.Connection) -> PaperItem | None:
            keys = {ref_l, f"arxiv:{ref_l}"}
            for k in keys:
                row = conn.execute(
                    "SELECT * FROM papers WHERE chat_id=? AND paper_key=?", (chat_id, k)
                ).fetchone()
                if row:
                    return self._row_to_paper(row)
            row = conn.execute(
                "SELECT * FROM papers WHERE chat_id=? AND lower(title) LIKE ? LIMIT 1",
                (chat_id, f"%{ref_l}%"),
            ).fetchone()
            return self._row_to_paper(row) if row else None

        return self._run(op)

    def export_bib(self, chat_id: int) -> str:
        return "\n\n".join(format_bibtex(p) for p in reversed(self.list(chat_id)))


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------
def _short_authors(authors: list[str], limit: int = 3) -> str:
    if not authors:
        return "penulis tidak diketahui"
    if len(authors) <= limit:
        return ", ".join(authors)
    return ", ".join(authors[:limit]) + " dkk."


def _paper_line(idx: int, p: PaperItem) -> str:
    meta = [str(p.year)] if p.year else []
    if p.citation_count is not None:
        meta.append(f"{p.citation_count} sitasi")
    if p.venue:
        meta.append(p.venue)
    cats = [c for c in p.categories if c in PRIORITY_CATEGORIES][:2]
    if cats:
        meta.append(", ".join(cats))
    ident = p.doi or (f"arXiv:{p.arxiv_id}" if p.arxiv_id else "")
    line = f"{idx}. {p.title}\n   {_short_authors(p.authors)} | {' | '.join(meta)}"
    if ident:
        line += f"\n   id: {ident}"
    return line


class ResearchPaperTool(BaseTool):
    name = "research_paper"
    description = (
        "Asisten riset paper ilmiah. Cari paper (arXiv + Semantic Scholar), lihat detail, ambil teks PDF untuk "
        "diringkas, buat sitasi (bibtex/apa/ieee), simpan ke perpustakaan pribadi, dan ekspor ke file .bib. "
        "Gunakan untuk permintaan riset akademik atau literatur. Setelah action 'search', pengguna bisa merujuk "
        "hasil dengan nomor (paper_ref='2'), DOI, atau arXiv ID. Action 'summarize' mengembalikan teks paper; "
        "tugas Anda menyusun ringkasan: masalah, metode, hasil, dan keterbatasan."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["search", "detail", "summarize", "cite", "save", "library", "export"],
            },
            "query": {"type": "string", "description": "Kata kunci pencarian (untuk action search)."},
            "paper_ref": {
                "type": "string",
                "description": "Nomor hasil pencarian terakhir (mis. '2'), DOI, arXiv ID, atau judul di perpustakaan.",
            },
            "year_from": {"type": "integer", "description": "Hanya paper dari tahun ini ke atas."},
            "limit": {"type": "integer", "description": "Jumlah hasil pencarian (1-10, default 5)."},
            "category": {"type": "string", "description": "Opsional: batasi arXiv ke kategori, mis. cs.CR."},
            "style": {"type": "string", "enum": ["bibtex", "apa", "ieee"], "description": "Format sitasi."},
            "tag": {"type": "string", "description": "Tag untuk save atau filter library."},
            "note": {"type": "string", "description": "Catatan pribadi saat menyimpan paper."},
            "summary": {"type": "string", "description": "Ringkasan yang ingin disimpan bersama paper."},
        },
        "required": ["action"],
    }

    def __init__(
        self,
        library: PaperLibrary | None = None,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        self._library = library
        self._client_factory = client_factory or (lambda: httpx.AsyncClient(timeout=30.0))
        self._last_results: dict[int, list[PaperItem]] = {}

    @property
    def library(self) -> PaperLibrary:
        if self._library is None:
            self._library = PaperLibrary(get_default_state_path("research.db"))
        return self._library

    # -- util ---------------------------------------------------------------
    @staticmethod
    def _papers_dir() -> pathlib.Path:
        d = pathlib.Path(os.path.expanduser(get_settings().papers_dir))
        d.mkdir(parents=True, exist_ok=True)
        return d

    @staticmethod
    def _ok(msg: str, **kw: Any) -> ToolResult:
        return ToolResult(success=True, output=msg, **kw)

    @staticmethod
    def _fail(msg: str) -> ToolResult:
        return ToolResult(success=False, output="", error=msg)

    # -- sumber data --------------------------------------------------------
    async def _search_arxiv(
        self, client: httpx.AsyncClient, query: str, limit: int, category: str | None
    ) -> list[PaperItem]:
        words = [w for w in re.split(r"\s+", query.strip()) if w]
        q = " AND ".join(f"all:{w}" for w in words) or "all:*"
        if category:
            q = f"({q}) AND cat:{category}"
        await _arxiv_throttle()
        body, _, _ = await safe_get(
            client,
            ARXIV_API,
            params={"search_query": q, "start": 0, "max_results": limit, "sortBy": "relevance"},
            max_bytes=API_MAX_BYTES,
        )
        return parse_arxiv_feed(body)

    def _s2_headers(self) -> dict[str, str]:
        key = get_settings().semantic_scholar_api_key
        return {"x-api-key": key} if key else {}

    async def _s2_get(self, client: httpx.AsyncClient, path: str, params: dict[str, Any]) -> dict[str, Any]:
        last_exc: Exception | None = None
        for attempt in range(len(S2_BACKOFF) + 1):
            try:
                body, _, _ = await safe_get(
                    client,
                    f"{S2_API}{path}",
                    params=params,
                    headers=self._s2_headers(),
                    max_bytes=API_MAX_BYTES,
                )
                return json.loads(body.decode("utf-8", errors="replace"))
            except httpx.HTTPStatusError as e:
                last_exc = e
                if e.response.status_code == 429 and attempt < len(S2_BACKOFF):
                    await asyncio.sleep(S2_BACKOFF[attempt])
                    continue
                raise
        raise last_exc or RuntimeError("Semantic Scholar gagal.")

    async def _search_s2(self, client: httpx.AsyncClient, query: str, limit: int) -> list[PaperItem]:
        data = await self._s2_get(
            client, "/paper/search", {"query": query, "limit": limit, "fields": S2_FIELDS}
        )
        items = [parse_s2_item(d, rank=i) for i, d in enumerate(data.get("data") or [])]
        return [p for p in items if p]

    async def _fetch_by_ref(self, client: httpx.AsyncClient, ref: str) -> PaperItem | None:
        ref = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:)", "", ref.strip(), flags=re.IGNORECASE)
        if _DOI_RE.match(ref):
            s2_id = f"DOI:{ref}"
        else:
            m = _ARXIV_RE.match(ref)
            if not m:
                return None
            s2_id = f"ARXIV:{m.group(1)}"
        try:
            data = await self._s2_get(client, f"/paper/{urllib.parse.quote(s2_id, safe=':/')}", {"fields": S2_FIELDS})
            paper = parse_s2_item(data)
            if paper:
                return paper
        except Exception as e:
            logger.info(f"S2 lookup gagal untuk {s2_id}: {e}")
        if s2_id.startswith("ARXIV:"):
            try:
                await _arxiv_throttle()
                body, _, _ = await safe_get(
                    client, ARXIV_API, params={"id_list": s2_id[6:]}, max_bytes=API_MAX_BYTES
                )
                found = parse_arxiv_feed(body)
                return found[0] if found else None
            except Exception as e:
                logger.info(f"arXiv lookup gagal untuk {s2_id}: {e}")
        return None

    async def _resolve(self, client: httpx.AsyncClient, chat_id: int, ref: str) -> PaperItem | None:
        ref = (ref or "").strip()
        if not ref:
            return None
        if ref.isdigit():
            results = self._last_results.get(chat_id) or []
            idx = int(ref)
            return results[idx - 1] if 1 <= idx <= len(results) else None
        stripped = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:)", "", ref, flags=re.IGNORECASE)
        library_hit = self.library.find(chat_id, stripped) or self.library.find(chat_id, ref)
        if library_hit:
            return library_hit
        return await self._fetch_by_ref(client, ref)

    async def _doi_cite(self, client: httpx.AsyncClient, doi: str, accept: str) -> str | None:
        try:
            body, _, _ = await safe_get(
                client, f"https://doi.org/{doi}", headers={"Accept": accept}, max_bytes=200_000
            )
            text = body.decode("utf-8", errors="replace").strip()
            return text or None
        except Exception as e:
            logger.info(f"Negosiasi konten DOI gagal ({doi}): {e}")
            return None

    # -- eksekusi -----------------------------------------------------------
    async def execute(self, context: ToolContext, **kwargs: Any) -> ToolResult:
        action = (kwargs.get("action") or "").lower().strip()
        handlers = {
            "search": self._do_search,
            "detail": self._do_detail,
            "summarize": self._do_summarize,
            "cite": self._do_cite,
            "save": self._do_save,
            "library": self._do_library,
            "export": self._do_export,
        }
        handler = handlers.get(action)
        if not handler:
            return self._fail(f"Action '{action}' tidak dikenal. Pilihan: {', '.join(handlers)}.")
        try:
            async with self._client_factory() as client:
                return await handler(context, client, kwargs)
        except UnsafeURLError as e:
            return self._fail(f"URL ditolak demi keamanan: {e}")
        except ResponseTooLargeError as e:
            return self._fail(f"Berkas terlalu besar: {e}")
        except httpx.TimeoutException:
            return self._fail("Koneksi ke server paper kehabisan waktu. Coba lagi sebentar lagi.")
        except httpx.HTTPError as e:
            return self._fail(f"Gagal menghubungi sumber paper: {e}")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception("research_paper error")
            return self._fail(f"Terjadi kendala saat memproses paper: {e}")

    async def _need_paper(
        self, client: httpx.AsyncClient, context: ToolContext, kwargs: dict[str, Any]
    ) -> tuple[PaperItem | None, ToolResult | None]:
        ref = str(kwargs.get("paper_ref") or "").strip()
        if not ref:
            return None, self._fail("paper_ref wajib diisi (nomor hasil, DOI, atau arXiv ID).")
        if ref.isdigit() and not self._last_results.get(context.chat_id):
            return None, self._fail("Belum ada hasil pencarian. Lakukan pencarian dulu atau berikan DOI/arXiv ID.")
        paper = await self._resolve(client, context.chat_id, ref)
        if not paper:
            return None, self._fail(f"Paper '{ref}' tidak ditemukan.")
        return paper, None

    async def _do_search(self, context: ToolContext, client: httpx.AsyncClient, kw: dict[str, Any]) -> ToolResult:
        query = str(kw.get("query") or "").strip()
        if not query:
            return self._fail("query wajib diisi untuk pencarian.")
        limit = max(1, min(int(kw.get("limit") or 5), 10))
        year_from = kw.get("year_from")
        category = (kw.get("category") or "").strip() or None

        arxiv_res, s2_res = await asyncio.gather(
            self._search_arxiv(client, query, limit, category),
            self._search_s2(client, query, limit),
            return_exceptions=True,
        )
        notes: list[str] = []
        groups: list[list[PaperItem]] = []
        for name, res in (("arXiv", arxiv_res), ("Semantic Scholar", s2_res)):
            if isinstance(res, asyncio.CancelledError):
                raise res
            if isinstance(res, Exception):
                logger.warning(f"Pencarian {name} gagal: {res}")
                notes.append(f"{name} sedang tidak bisa diakses, hasil dari sumber lain saja.")
            else:
                groups.append(res)
        if not groups:
            return self._fail("Kedua sumber (arXiv dan Semantic Scholar) sedang tidak bisa diakses. Coba lagi nanti.")

        papers = rank_papers(merge_papers(*groups))
        if year_from:
            papers = [p for p in papers if p.year is None or p.year >= int(year_from)]
        papers = papers[:limit]
        self._last_results[context.chat_id] = papers
        if not papers:
            return self._ok("Tidak ada paper yang cocok dengan pencarian itu." + (" " + " ".join(notes) if notes else ""))

        lines = [f"Nemu {len(papers)} paper untuk '{query}':", ""]
        lines += [_paper_line(i, p) for i, p in enumerate(papers, 1)]
        lines += ["", "Sebutkan nomornya kalau mau diringkas, disitasi, atau disimpan."]
        if notes:
            lines += ["", "Catatan: " + " ".join(notes)]
        return self._ok("\n".join(lines))

    async def _do_detail(self, context: ToolContext, client: httpx.AsyncClient, kw: dict[str, Any]) -> ToolResult:
        paper, err = await self._need_paper(client, context, kw)
        if err:
            return err
        assert paper is not None
        abstract = paper.abstract or "(abstrak tidak tersedia)"
        if len(abstract) > 1500:
            abstract = abstract[:1500] + "..."
        lines = [
            f"Judul: {paper.title}",
            f"Penulis: {', '.join(paper.authors) or '-'}",
            f"Tahun: {paper.year or '-'}",
            f"Venue: {paper.venue or '-'}",
            f"Sitasi: {paper.citation_count if paper.citation_count is not None else '-'}",
            f"DOI: {paper.doi or '-'}",
            f"arXiv: {paper.arxiv_id or '-'}",
            f"PDF: {paper.pdf_url or '-'}",
            "",
            f"Abstrak: {abstract}",
        ]
        return self._ok("\n".join(lines))

    async def _do_summarize(self, context: ToolContext, client: httpx.AsyncClient, kw: dict[str, Any]) -> ToolResult:
        paper, err = await self._need_paper(client, context, kw)
        if err:
            return err
        assert paper is not None
        settings = get_settings()
        max_chars = settings.research_summary_max_chars
        header = (
            f"Judul: {paper.title}\nPenulis: {_short_authors(paper.authors, 5)}\nTahun: {paper.year or '-'}\n"
        )
        instruction = (
            "\n\nTUGAS: susun ringkasan plain text (tanpa markdown) dengan urutan: masalah, metode, hasil, "
            "keterbatasan. Gunakan hanya isi teks di atas."
        )

        pdf_url = paper.pdf_url or (f"https://arxiv.org/pdf/{paper.arxiv_id}" if paper.arxiv_id else None)
        abstract_only = (
            f"{header}\n[PDF tidak tersedia, ringkasan hanya dari abstrak. Beri tahu pengguna.]\n\n"
            f"Abstrak: {paper.abstract or '(kosong)'}{instruction}"
        )
        if not pdf_url:
            return self._ok(abstract_only)

        papers_dir = self._papers_dir()
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", paper.paper_key)[:80] + ".pdf"
        ok, msg, pdf_path = validate_document_path(papers_dir / safe_name, papers_dir)
        if not ok or pdf_path is None:
            return self._fail(msg)

        if not pdf_path.exists():
            if context.on_status_update:
                await context.on_status_update("📥 Mengunduh PDF paper...")
            try:
                data, _, _ = await safe_get(
                    client,
                    pdf_url,
                    max_bytes=settings.research_max_pdf_mb * 1024 * 1024,
                    cancel_event=context.cancel_event,
                )
            except (httpx.HTTPError, ResponseTooLargeError) as e:
                logger.info(f"Unduh PDF gagal: {e}")
                return self._ok(abstract_only)
            if not data.lstrip().startswith(b"%PDF"):
                return self._ok(abstract_only)
            pdf_path.write_bytes(data)

        if context.cancel_event.is_set():
            return self._fail("Dibatalkan.")
        if context.on_status_update:
            await context.on_status_update("⏳ Membaca isi paper...")
        try:
            text = await asyncio.to_thread(extract_pdf_text, str(pdf_path))
        except Exception as e:
            logger.info(f"Ekstraksi PDF gagal: {e}")
            return self._ok(abstract_only)
        if len(text.strip()) < 200:
            return self._ok(abstract_only)

        selected = select_key_sections(text, max_chars)
        return self._ok(f"{header}File: {pdf_path}\n\nIsi paper:\n{selected}{instruction}")

    async def _do_cite(self, context: ToolContext, client: httpx.AsyncClient, kw: dict[str, Any]) -> ToolResult:
        paper, err = await self._need_paper(client, context, kw)
        if err:
            return err
        assert paper is not None
        style = (kw.get("style") or "bibtex").lower()
        if style not in ("bibtex", "apa", "ieee"):
            return self._fail("style harus bibtex, apa, atau ieee.")
        text: str | None = None
        if paper.doi and style == "bibtex":
            text = await self._doi_cite(client, paper.doi, "application/x-bibtex")
        elif paper.doi and style == "apa":
            text = await self._doi_cite(client, paper.doi, "text/x-bibliography; style=apa")
        if not text:
            text = {"bibtex": format_bibtex, "apa": format_apa, "ieee": format_ieee}[style](paper)
        return self._ok(text)

    async def _do_save(self, context: ToolContext, client: httpx.AsyncClient, kw: dict[str, Any]) -> ToolResult:
        paper, err = await self._need_paper(client, context, kw)
        if err:
            return err
        assert paper is not None
        tag = (kw.get("tag") or "").strip()
        is_new = self.library.save(
            context.chat_id,
            paper,
            note=str(kw.get("note") or ""),
            tags=[tag] if tag else None,
            summary=str(kw.get("summary") or ""),
        )
        verb = "disimpan ke" if is_new else "diperbarui di"
        return self._ok(f"Paper '{paper.title}' {verb} perpustakaan.")

    async def _do_library(self, context: ToolContext, client: httpx.AsyncClient, kw: dict[str, Any]) -> ToolResult:
        tag = (kw.get("tag") or "").strip() or None
        papers = self.library.list(context.chat_id, tag=tag)
        if not papers:
            return self._ok("Perpustakaan masih kosong." if not tag else f"Tidak ada paper dengan tag '{tag}'.")
        self._last_results[context.chat_id] = papers
        lines = [f"Perpustakaan paper ({len(papers)}):", ""]
        lines += [_paper_line(i, p) for i, p in enumerate(papers, 1)]
        return self._ok("\n".join(lines))

    async def _do_export(self, context: ToolContext, client: httpx.AsyncClient, kw: dict[str, Any]) -> ToolResult:
        bib = self.library.export_bib(context.chat_id)
        if not bib:
            return self._fail("Perpustakaan masih kosong, tidak ada yang bisa diekspor.")
        papers_dir = self._papers_dir()
        ok, msg, out_path = validate_document_path(papers_dir / "library.bib", papers_dir)
        if not ok or out_path is None:
            return self._fail(msg)
        out_path.write_text(bib + "\n", encoding="utf-8")
        return self._ok("Perpustakaan diekspor ke library.bib.", media_path=str(out_path), media_type="document")
