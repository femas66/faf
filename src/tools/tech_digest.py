"""Tech Digest Harian: ringkasan berita keamanan siber & teknologi dari Hacker News, GitHub Trending, dan RSS."""
from __future__ import annotations

import asyncio
import contextlib
import datetime
import hashlib
import json
import logging
import os
import re
import sqlite3
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Any, Callable

import httpx

from src.config import get_settings
from src.tools.base import BaseTool, ToolContext, ToolResult
from src.tools.cronjob_mgr import (
    CronJobItem,
    CronJobStore,
    _format_readable_dt,
    _default_cron_store,
    parse_schedule_string,
)
from src.tools.path_security import get_default_state_path
from src.tools.safe_http import UnsafeURLError, parse_xml_safely, safe_get
from src.tools.web_search import _check_url_safety

logger = logging.getLogger("faf_agent.tools.tech_digest")

HN_API = "https://hn.algolia.com/api/v1/search"
GITHUB_TRENDING = "https://github.com/trending?since=daily"
GITHUB_SEARCH_API = "https://api.github.com/search/repositories"
FEED_MAX_BYTES = 2 * 1024 * 1024
PAGE_MAX_BYTES = 3 * 1024 * 1024
FETCH_TIMEOUT = 15.0
RSS_MAX_AGE_HOURS = 72

CYBER_WEIGHT = 1.0
TECH_WEIGHT = 0.8

SECTION_LIMITS = {"cyber": 5, "tech": 4, "github": 3}
SECTION_TITLES = {"cyber": "Keamanan Siber", "tech": "Teknologi Terbaru", "github": "GitHub Trending"}

# (nama, url, kategori)
DEFAULT_SOURCES: list[tuple[str, str, str]] = [
    ("The Hacker News", "https://feeds.feedburner.com/TheHackersNews", "cyber"),
    ("BleepingComputer", "https://www.bleepingcomputer.com/feed/", "cyber"),
    ("Krebs on Security", "https://krebsonsecurity.com/feed/", "cyber"),
    ("Schneier on Security", "https://www.schneier.com/feed/atom/", "cyber"),
    ("Google Project Zero", "https://googleprojectzero.blogspot.com/feeds/posts/default", "cyber"),
    ("CISA Advisories", "https://www.cisa.gov/cybersecurity-advisories/all.xml", "cyber"),
    ("arXiv cs.CR", "https://rss.arxiv.org/rss/cs.CR", "cyber"),
    ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index", "tech"),
    ("Simon Willison", "https://simonwillison.net/atom/everything/", "tech"),
    ("Hugging Face Blog", "https://huggingface.co/blog/feed.xml", "tech"),
    ("Lobsters", "https://lobste.rs/rss", "tech"),
]

DEFAULT_TOPICS: dict[str, Any] = {
    "cyber": [
        "security", "cyber", "vulnerability", "cve", "exploit", "zero-day", "malware", "ransomware",
        "breach", "phishing", "pentest", "ctf", "owasp", "apt", "backdoor", "supply chain",
    ],
    "tech": [
        "release", "launch", "ai", "llm", "open source", "linux", "rust", "python", "cloud",
        "kernel", "chip", "quantum",
    ],
}

_CRITICAL_RE = re.compile(
    r"zero[- ]?day|0[- ]day|actively exploited|known exploited|exploited in the wild|critical (?:cve|vulnerabilit)",
    re.IGNORECASE,
)
_UTM_RE = re.compile(r"^(utm_|fbclid|gclid|ref$|ref_src$)", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Model & helper
# ---------------------------------------------------------------------------
@dataclass
class DigestItem:
    source: str  # "hn" | "github" | "rss"
    title: str
    url: str
    description: str = ""
    score: int = 0  # poin HN / bintang hari ini
    comments: int = 0
    published_at: float | None = None
    extra: str = ""  # bahasa repo, nama blog, dll.
    category: str = "tech"  # kategori sumber RSS: "cyber" | "tech"
    section: str = ""
    critical: bool = False
    rank_score: float = 0.0


def normalize_url(url: str) -> str:
    """Normalisasi URL untuk deduplikasi: huruf kecil host, tanpa fragment dan parameter pelacak."""
    try:
        p = urllib.parse.urlsplit((url or "").strip())
    except ValueError:
        return (url or "").strip().lower()
    query = [(k, v) for k, v in urllib.parse.parse_qsl(p.query) if not _UTM_RE.match(k)]
    path = p.path.rstrip("/") or ""
    return urllib.parse.urlunsplit(
        (p.scheme.lower(), p.netloc.lower(), path, urllib.parse.urlencode(query), "")
    )


def url_hash(url: str) -> str:
    return hashlib.sha1(normalize_url(url).lower().encode()).hexdigest()


def _strip_tags(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()


def _parse_date(value: str | None) -> float | None:
    if not value:
        return None
    value = value.strip()
    try:
        return parsedate_to_datetime(value).timestamp()
    except (TypeError, ValueError):
        pass
    try:
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Parser sumber
# ---------------------------------------------------------------------------
def parse_feed(data: bytes, source_name: str, category: str) -> list[DigestItem]:
    """Parse RSS 2.0 dan Atom 1.0."""
    root = parse_xml_safely(data)
    items: list[DigestItem] = []

    def local(tag: str) -> str:
        return tag.rsplit("}", 1)[-1]

    def child_text(el: Any, name: str) -> str:
        for c in el:
            if local(c.tag) == name:
                return (c.text or "").strip()
        return ""

    for el in root.iter():
        kind = local(el.tag)
        if kind == "item":  # RSS
            link = child_text(el, "link")
            date = child_text(el, "pubDate") or child_text(el, "date")
            desc = child_text(el, "description")
        elif kind == "entry":  # Atom
            link = ""
            for c in el:
                if local(c.tag) == "link":
                    rel = c.get("rel", "alternate")
                    if rel == "alternate" and c.get("href"):
                        link = c.get("href", "")
                        break
                    link = link or c.get("href", "")
            date = child_text(el, "published") or child_text(el, "updated")
            desc = child_text(el, "summary") or child_text(el, "content")
        else:
            continue
        title = _strip_tags(child_text(el, "title"))
        if not title or not link:
            continue
        items.append(
            DigestItem(
                source="rss",
                title=title,
                url=link,
                description=_strip_tags(desc)[:300],
                published_at=_parse_date(date),
                extra=source_name,
                category=category,
            )
        )
    return items


def parse_hn(data: dict[str, Any]) -> list[DigestItem]:
    items: list[DigestItem] = []
    for hit in data.get("hits") or []:
        title = (hit.get("title") or "").strip()
        if not title:
            continue
        object_id = hit.get("objectID")
        url = hit.get("url") or f"https://news.ycombinator.com/item?id={object_id}"
        items.append(
            DigestItem(
                source="hn",
                title=title,
                url=url,
                score=int(hit.get("points") or 0),
                comments=int(hit.get("num_comments") or 0),
                published_at=float(hit["created_at_i"]) if hit.get("created_at_i") else None,
                extra=f"https://news.ycombinator.com/item?id={object_id}",
            )
        )
    return items


class _TrendingParser(HTMLParser):
    """Parser defensif untuk halaman github.com/trending."""

    def __init__(self) -> None:
        super().__init__()
        self.repos: list[dict[str, Any]] = []
        self._cur: dict[str, Any] | None = None
        self._in_h2 = False
        self._in_desc = False
        self._in_lang = False
        self._buf = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        cls = a.get("class") or ""
        if tag == "article" and "Box-row" in cls:
            self._cur = {"path": "", "desc": "", "lang": "", "stars_today": 0}
            self.repos.append(self._cur)
        elif self._cur is not None:
            if tag == "h2":
                self._in_h2 = True
            elif tag == "a" and self._in_h2 and not self._cur["path"]:
                href = a.get("href") or ""
                if href.startswith("/") and href.count("/") == 2:
                    self._cur["path"] = href
            elif tag == "p" and not self._cur["desc"]:
                self._in_desc = True
                self._buf = ""
            elif tag == "span" and a.get("itemprop") == "programmingLanguage":
                self._in_lang = True
                self._buf = ""

    def handle_endtag(self, tag: str) -> None:
        if self._cur is None:
            return
        if tag == "h2":
            self._in_h2 = False
        elif tag == "p" and self._in_desc:
            self._cur["desc"] = re.sub(r"\s+", " ", self._buf).strip()
            self._in_desc = False
        elif tag == "span" and self._in_lang:
            self._cur["lang"] = self._buf.strip()
            self._in_lang = False

    def handle_data(self, data: str) -> None:
        if self._cur is None:
            return
        if self._in_desc or self._in_lang:
            self._buf += data
        m = re.search(r"([\d,]+)\s+stars?\s+today", data)
        if m:
            self._cur["stars_today"] = int(m.group(1).replace(",", ""))


def parse_github_trending(html_text: str) -> list[DigestItem]:
    parser = _TrendingParser()
    parser.feed(html_text)
    items = []
    for r in parser.repos:
        if not r["path"]:
            continue
        name = r["path"].strip("/")
        items.append(
            DigestItem(
                source="github",
                title=name,
                url=f"https://github.com/{name}",
                description=r["desc"][:200],
                score=r["stars_today"],
                extra=r["lang"],
            )
        )
    return items


def parse_github_search(data: dict[str, Any]) -> list[DigestItem]:
    items = []
    for repo in data.get("items") or []:
        name = repo.get("full_name")
        if not name:
            continue
        items.append(
            DigestItem(
                source="github",
                title=name,
                url=repo.get("html_url") or f"https://github.com/{name}",
                description=(repo.get("description") or "")[:200],
                score=int(repo.get("stargazers_count") or 0),  # fallback: total bintang repo baru
                extra=repo.get("language") or "",
            )
        )
    return items


# ---------------------------------------------------------------------------
# Penilaian & penyaringan
# ---------------------------------------------------------------------------
def _hits(text: str, keywords: list[str]) -> int:
    count = 0
    for kw in keywords:
        kw = kw.strip().lower()
        if kw and re.search(r"(?<![a-z0-9])" + re.escape(kw) + r"(?![a-z0-9])", text):
            count += 1
    return count


def score_and_filter(
    items: list[DigestItem],
    topics: dict[str, Any],
    *,
    now: float | None = None,
    hn_min_points: int = 100,
    hn_min_comments: int = 50,
    github_min_stars: int = 200,
    topic_filter: str | None = None,
) -> list[DigestItem]:
    """Terapkan filter kualitas, hitung skor, dan tentukan section tiap item."""
    now = now or time.time()
    cyber_kw = list(topics.get("cyber") or [])
    tech_kw = list(topics.get("tech") or [])
    quality = topics.get("quality") or {}
    hn_min_points = int(quality.get("hn_min_points", hn_min_points))
    hn_min_comments = int(quality.get("hn_min_comments", hn_min_comments))
    github_min_stars = int(quality.get("github_min_stars_today", github_min_stars))
    tf = (topic_filter or "").strip().lower()

    kept: list[DigestItem] = []
    for it in items:
        text = f"{it.title} {it.description}".lower()
        if tf and tf not in text:
            continue
        it.critical = bool(_CRITICAL_RE.search(text))
        cyber_hits = _hits(text, cyber_kw)
        tech_hits = _hits(text, tech_kw)

        # Filter kualitas (item kritis selalu lolos)
        if not it.critical:
            if it.source == "hn" and not (it.score >= hn_min_points or it.comments >= hn_min_comments):
                continue
            if it.source == "github" and it.score < github_min_stars:
                continue
            if it.source == "rss" and it.published_at and (now - it.published_at) > RSS_MAX_AGE_HOURS * 3600:
                continue

        if it.source == "github":
            it.section = "github"
        elif it.category == "cyber" or cyber_hits > 0:
            it.section = "cyber"
        else:
            it.section = "tech"

        interest = 0.0
        if cyber_hits:
            interest = max(interest, CYBER_WEIGHT * min(1.0, 0.6 + 0.2 * cyber_hits))
        if tech_hits:
            interest = max(interest, TECH_WEIGHT * min(1.0, 0.6 + 0.2 * tech_hits))
        if it.category == "cyber" and not cyber_hits:
            interest = max(interest, 0.5)

        if it.source == "hn":
            pop = min(1.0, it.score / 500)
        elif it.source == "github":
            pop = min(1.0, it.score / 1000)
        else:
            pop = 0.4
        if it.published_at:
            age_h = max(0.0, (now - it.published_at) / 3600)
            recency = max(0.0, 1.0 - age_h / 48)
        else:
            recency = 0.5

        it.rank_score = 0.5 * interest + 0.3 * pop + 0.2 * recency + (1.0 if it.critical else 0.0)
        kept.append(it)
    return sorted(kept, key=lambda i: i.rank_score, reverse=True)


def select_top(items: list[DigestItem], max_items: int) -> list[DigestItem]:
    """Ambil top per section dengan urutan Cyber, Tech, GitHub dan batas total."""
    result: list[DigestItem] = []
    for section in ("cyber", "tech", "github"):
        picked = [i for i in items if i.section == section][: SECTION_LIMITS[section]]
        result.extend(picked)
    if len(result) > max_items:
        # buang dari belakang section yang paling akhir, tapi pertahankan item kritis
        trimmed: list[DigestItem] = []
        budget = max_items
        for it in sorted(result, key=lambda i: (not i.critical, 0)):
            if budget <= 0:
                break
            trimmed.append(it)
            budget -= 1
        order = {"cyber": 0, "tech": 1, "github": 2}
        result = sorted(trimmed, key=lambda i: (order[i.section], -i.rank_score))
    return result


def format_digest(items: list[DigestItem], notes: list[str], now: datetime.datetime | None = None) -> str:
    now = now or datetime.datetime.now()
    lines = [f"Tech Digest, {now.strftime('%d %b %Y')}", ""]
    for section in ("cyber", "tech", "github"):
        sec_items = [i for i in items if i.section == section]
        if not sec_items:
            continue
        lines.append(SECTION_TITLES[section])
        for idx, it in enumerate(sec_items, 1):
            prefix = "[PENTING] " if it.critical else ""
            meta = ""
            if it.source == "hn":
                meta = f" ({it.score} poin, {it.comments} komentar)"
            elif it.source == "github":
                meta = f" ({it.extra or 'repo'}, +{it.score} bintang)"
            elif it.extra:
                meta = f" ({it.extra})"
            lines.append(f"{idx}. {prefix}{it.title}{meta}")
            if it.description:
                lines.append(f"   {it.description[:160]}")
            lines.append(f"   {it.url}")
        lines.append("")
    for n in notes:
        lines.append(f"({n})")
    return "\n".join(lines).strip()


# ---------------------------------------------------------------------------
# Penyimpanan SQLite
# ---------------------------------------------------------------------------
class DigestStore:
    """SQLite: sumber RSS, profil topik, dan item yang sudah dikirim. Dilindungi RLock."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._lock = threading.RLock()
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._run(self._init_schema)

    @staticmethod
    def _init_schema(conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS digest_sources (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id  INTEGER NOT NULL,
                name     TEXT NOT NULL,
                url      TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'tech',
                enabled  INTEGER NOT NULL DEFAULT 1,
                UNIQUE(chat_id, url)
            );
            CREATE TABLE IF NOT EXISTS digest_topics (
                chat_id INTEGER PRIMARY KEY,
                topics  TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS digest_seen (
                chat_id  INTEGER NOT NULL,
                url_hash TEXT NOT NULL,
                sent_at  REAL NOT NULL,
                PRIMARY KEY (chat_id, url_hash)
            );
            """
        )

    def _run(self, fn: Callable[[sqlite3.Connection], Any]) -> Any:
        with self._lock:
            with contextlib.closing(sqlite3.connect(self.db_path, timeout=10)) as conn:
                result = fn(conn)
                conn.commit()
                return result

    def ensure_chat(self, chat_id: int, default_quality: dict[str, int]) -> None:
        """Seed sumber dan topik default saat chat pertama kali memakai digest."""

        def op(conn: sqlite3.Connection) -> None:
            if conn.execute("SELECT 1 FROM digest_topics WHERE chat_id=?", (chat_id,)).fetchone():
                return
            topics = dict(DEFAULT_TOPICS)
            topics["quality"] = default_quality
            conn.execute("INSERT INTO digest_topics (chat_id, topics) VALUES (?,?)", (chat_id, json.dumps(topics)))
            conn.executemany(
                "INSERT OR IGNORE INTO digest_sources (chat_id, name, url, category) VALUES (?,?,?,?)",
                [(chat_id, n, u, c) for n, u, c in DEFAULT_SOURCES],
            )

        self._run(op)

    def get_topics(self, chat_id: int) -> dict[str, Any]:
        row = self._run(lambda c: c.execute("SELECT topics FROM digest_topics WHERE chat_id=?", (chat_id,)).fetchone())
        return json.loads(row[0]) if row else dict(DEFAULT_TOPICS)

    def set_topics(self, chat_id: int, topics: dict[str, Any]) -> None:
        self._run(
            lambda c: c.execute(
                "INSERT INTO digest_topics (chat_id, topics) VALUES (?,?) "
                "ON CONFLICT(chat_id) DO UPDATE SET topics=excluded.topics",
                (chat_id, json.dumps(topics)),
            )
        )

    def list_sources(self, chat_id: int) -> list[tuple[str, str, str]]:
        rows = self._run(
            lambda c: c.execute(
                "SELECT name, url, category FROM digest_sources WHERE chat_id=? AND enabled=1 ORDER BY id",
                (chat_id,),
            ).fetchall()
        )
        return [(r[0], r[1], r[2]) for r in rows]

    def add_source(self, chat_id: int, url: str, name: str, category: str) -> bool:
        def op(conn: sqlite3.Connection) -> bool:
            cur = conn.execute(
                "INSERT OR IGNORE INTO digest_sources (chat_id, name, url, category) VALUES (?,?,?,?)",
                (chat_id, name, url, category),
            )
            return cur.rowcount > 0

        return bool(self._run(op))

    def remove_source(self, chat_id: int, ident: str) -> int:
        """Hapus berdasarkan URL atau nama (tidak peka huruf besar/kecil)."""
        return int(
            self._run(
                lambda c: c.execute(
                    "DELETE FROM digest_sources WHERE chat_id=? AND (url=? OR lower(name)=lower(?))",
                    (chat_id, ident, ident),
                ).rowcount
            )
        )

    def filter_unseen(self, chat_id: int, items: list[DigestItem]) -> list[DigestItem]:
        def op(conn: sqlite3.Connection) -> set[str]:
            rows = conn.execute("SELECT url_hash FROM digest_seen WHERE chat_id=?", (chat_id,)).fetchall()
            return {r[0] for r in rows}

        seen = self._run(op)
        out, batch = [], set()
        for it in items:
            h = url_hash(it.url)
            if h in seen or h in batch:
                continue
            batch.add(h)
            out.append(it)
        return out

    def mark_seen(self, chat_id: int, items: list[DigestItem]) -> None:
        now = time.time()
        self._run(
            lambda c: c.executemany(
                "INSERT OR REPLACE INTO digest_seen (chat_id, url_hash, sent_at) VALUES (?,?,?)",
                [(chat_id, url_hash(i.url), now) for i in items],
            )
        )

    def purge_old(self, retention_days: int) -> int:
        cutoff = time.time() - retention_days * 86400
        return int(self._run(lambda c: c.execute("DELETE FROM digest_seen WHERE sent_at < ?", (cutoff,)).rowcount))


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------
_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
DIGEST_PROMPT = (
    "Jalankan tool tech_digest dengan action=run, lalu kirim hasilnya sebagai satu pesan plain text "
    "(tanpa markdown dan tanpa tabel). Tulis satu kalimat ringkas bahasa Indonesia untuk tiap item."
)


class TechDigestTool(BaseTool):
    name = "tech_digest"
    description = (
        "Ringkasan berita teknologi dan keamanan siber dari Hacker News, GitHub Trending, dan RSS pilihan. "
        "action='run' mengambil data terbaru dan mengembalikan daftar item (tugas Anda: tulis satu kalimat "
        "ringkas bahasa Indonesia per item, plain text, di bawah 4000 karakter, urutan bagian dipertahankan). "
        "Juga mengatur jadwal digest harian (schedule/unschedule), sumber RSS (add_source/remove_source/"
        "list_sources), dan profil topik minat (set_topics/show_topics)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "run", "schedule", "unschedule", "add_source", "remove_source",
                    "list_sources", "set_topics", "show_topics",
                ],
            },
            "topic_filter": {"type": "string", "description": "Fokus sementara untuk run, mis. 'AI'."},
            "preview": {"type": "boolean", "description": "Jika true, run tidak menandai item sebagai terkirim."},
            "time": {"type": "string", "description": "Jam kirim format HH:MM 24 jam (untuk schedule)."},
            "source_url": {"type": "string"},
            "source_name": {"type": "string"},
            "source_category": {"type": "string", "enum": ["cyber", "tech"]},
            "topics": {"type": "array", "items": {"type": "string"}, "description": "Kata kunci topik."},
            "group": {"type": "string", "enum": ["cyber", "tech"], "description": "Kelompok topik (default tech)."},
            "replace": {"type": "boolean", "description": "Ganti seluruh kata kunci kelompok, bukan menambah."},
        },
        "required": ["action"],
    }

    def __init__(
        self,
        store: DigestStore | None = None,
        cron_store: CronJobStore | None = None,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        self._store = store
        self._cron_store = cron_store
        self._client_factory = client_factory or (lambda: httpx.AsyncClient(timeout=FETCH_TIMEOUT))

    @property
    def store(self) -> DigestStore:
        if self._store is None:
            self._store = DigestStore(get_default_state_path("tech_digest.db"))
        return self._store

    @property
    def cron_store(self) -> CronJobStore:
        return self._cron_store or _default_cron_store

    @staticmethod
    def _ok(msg: str) -> ToolResult:
        return ToolResult(success=True, output=msg)

    @staticmethod
    def _fail(msg: str) -> ToolResult:
        return ToolResult(success=False, output="", error=msg)

    def _quality_defaults(self) -> dict[str, int]:
        s = get_settings()
        return {
            "hn_min_points": s.digest_hn_min_points,
            "hn_min_comments": 50,
            "github_min_stars_today": s.digest_github_min_stars_today,
        }

    # -- fetchers -----------------------------------------------------------
    async def _fetch_hn(self, client: httpx.AsyncClient) -> list[DigestItem]:
        body, _, _ = await asyncio.wait_for(
            safe_get(client, HN_API, params={"tags": "front_page", "hitsPerPage": 40}, max_bytes=FEED_MAX_BYTES),
            FETCH_TIMEOUT,
        )
        return parse_hn(json.loads(body.decode("utf-8", errors="replace")))

    async def _fetch_github(self, client: httpx.AsyncClient) -> list[DigestItem]:
        items: list[DigestItem] = []
        try:
            body, _, _ = await asyncio.wait_for(
                safe_get(client, GITHUB_TRENDING, max_bytes=PAGE_MAX_BYTES), FETCH_TIMEOUT
            )
            items = parse_github_trending(body.decode("utf-8", errors="replace"))
        except Exception as e:
            logger.info(f"Scraping GitHub Trending gagal: {e}")
        if items:
            return items
        # Fallback: Search API (repo baru dengan bintang terbanyak 7 hari terakhir)
        since = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
        headers = {"Accept": "application/vnd.github+json"}
        token = get_settings().github_token
        if token:
            headers["Authorization"] = f"Bearer {token}"
        body, _, _ = await asyncio.wait_for(
            safe_get(
                client,
                GITHUB_SEARCH_API,
                params={"q": f"created:>{since}", "sort": "stars", "order": "desc", "per_page": 15},
                headers=headers,
                max_bytes=FEED_MAX_BYTES,
            ),
            FETCH_TIMEOUT,
        )
        return parse_github_search(json.loads(body.decode("utf-8", errors="replace")))

    async def _fetch_feed(
        self, client: httpx.AsyncClient, name: str, url: str, category: str
    ) -> list[DigestItem]:
        body, _, _ = await asyncio.wait_for(safe_get(client, url, max_bytes=FEED_MAX_BYTES), FETCH_TIMEOUT)
        return parse_feed(body, name, category)

    # -- eksekusi -----------------------------------------------------------
    async def execute(self, context: ToolContext, **kwargs: Any) -> ToolResult:
        action = (kwargs.get("action") or "").lower().strip()
        try:
            self.store.ensure_chat(context.chat_id, self._quality_defaults())
            if action == "run":
                return await self._run(context, kwargs)
            if action == "schedule":
                return await self._schedule(context, kwargs)
            if action == "unschedule":
                removed = await self.cron_store.remove(f"digest_{context.chat_id}")
                return self._ok("Jadwal digest harian dimatikan." if removed else "Tidak ada jadwal digest yang aktif.")
            if action == "add_source":
                return await self._add_source(context, kwargs)
            if action == "remove_source":
                ident = str(kwargs.get("source_url") or kwargs.get("source_name") or "").strip()
                if not ident:
                    return self._fail("source_url atau source_name wajib diisi.")
                n = self.store.remove_source(context.chat_id, ident)
                return self._ok(f"{n} sumber dihapus." if n else "Sumber itu tidak ditemukan.")
            if action == "list_sources":
                srcs = self.store.list_sources(context.chat_id)
                lines = [f"Sumber RSS aktif ({len(srcs)}):"]
                lines += [f"{i}. {n} [{c}] {u}" for i, (n, u, c) in enumerate(srcs, 1)]
                return self._ok("\n".join(lines))
            if action == "set_topics":
                return self._set_topics(context, kwargs)
            if action == "show_topics":
                t = self.store.get_topics(context.chat_id)
                q = t.get("quality") or {}
                return self._ok(
                    f"Topik keamanan siber: {', '.join(t.get('cyber', []))}\n"
                    f"Topik teknologi: {', '.join(t.get('tech', []))}\n"
                    f"Filter kualitas: HN min {q.get('hn_min_points')} poin atau {q.get('hn_min_comments')} komentar, "
                    f"GitHub min {q.get('github_min_stars_today')} bintang hari ini."
                )
            return self._fail(f"Action '{action}' tidak dikenal.")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception("tech_digest error")
            return self._fail(f"Terjadi kendala saat memproses digest: {e}")

    async def _run(self, context: ToolContext, kw: dict[str, Any]) -> ToolResult:
        settings = get_settings()
        chat_id = context.chat_id
        topics = self.store.get_topics(chat_id)
        sources = self.store.list_sources(chat_id)

        async with self._client_factory() as client:
            tasks: list[tuple[str, Any]] = [("Hacker News", self._fetch_hn(client)), ("GitHub Trending", self._fetch_github(client))]
            tasks += [(n, self._fetch_feed(client, n, u, c)) for n, u, c in sources]
            results = await asyncio.gather(*(t for _, t in tasks), return_exceptions=True)

        if context.cancel_event.is_set():
            return self._fail("Dibatalkan.")

        all_items: list[DigestItem] = []
        failed: list[str] = []
        for (label, _), res in zip(tasks, results):
            if isinstance(res, asyncio.CancelledError):
                raise res
            if isinstance(res, Exception):
                logger.warning(f"Sumber digest '{label}' gagal: {res}")
                failed.append(label)
            else:
                all_items.extend(res)

        if not all_items:
            return self._fail("Semua sumber digest sedang tidak bisa diakses. Coba lagi nanti.")

        self.store.purge_old(settings.digest_seen_retention_days)
        unseen = self.store.filter_unseen(chat_id, all_items)
        scored = score_and_filter(
            unseen,
            topics,
            hn_min_points=settings.digest_hn_min_points,
            github_min_stars=settings.digest_github_min_stars_today,
            topic_filter=kw.get("topic_filter"),
        )
        picked = select_top(scored, settings.digest_max_items)

        notes = []
        if failed:
            shown = ", ".join(failed[:3]) + (f" dan {len(failed) - 3} lainnya" if len(failed) > 3 else "")
            notes.append(f"Sumber yang sedang tidak bisa diakses: {shown}")
        if not picked:
            return self._ok("Belum ada berita baru yang lolos filter hari ini." + (f" {notes[0]}." if notes else ""))

        if not kw.get("preview"):
            self.store.mark_seen(chat_id, picked)

        digest = format_digest(picked, notes)
        return self._ok(
            "Data digest (tulis ulang sebagai satu pesan plain text; satu kalimat ringkas Indonesia per item; "
            "pertahankan judul bagian, penanda [PENTING], dan URL):\n\n" + digest
        )

    async def _schedule(self, context: ToolContext, kw: dict[str, Any]) -> ToolResult:
        time_str = str(kw.get("time") or get_settings().digest_default_time).strip()
        m = _TIME_RE.match(time_str)
        if not m:
            return self._fail("Format jam harus HH:MM (24 jam), contoh 07:00.")
        hhmm = f"{int(m.group(1)):02d}:{m.group(2)}"
        schedule = f"daily at {hhmm}"
        now_dt = datetime.datetime.now().astimezone()
        next_ts = parse_schedule_string(schedule, now_dt)
        if not next_ts:
            return self._fail(f"Jadwal '{schedule}' tidak valid.")
        item = CronJobItem(
            id=f"digest_{context.chat_id}",
            chat_id=context.chat_id,
            title="Tech Digest Harian",
            schedule=schedule,
            timezone="Asia/Jakarta",
            execution_type="agent_prompt",
            prompt=DIGEST_PROMPT,
            deliver={"channel": "telegram", "target_id": str(context.chat_id)},
            created_at=_format_readable_dt(now_dt),
            next_run_timestamp=next_ts,
            next_run_readable=_format_readable_dt(datetime.datetime.fromtimestamp(next_ts).astimezone()),
            is_active=True,
        )
        await self.cron_store.add(item)
        return self._ok(f"Digest harian dijadwalkan setiap hari jam {hhmm}. Pengiriman berikutnya: {item.next_run_readable}.")

    async def _add_source(self, context: ToolContext, kw: dict[str, Any]) -> ToolResult:
        url = str(kw.get("source_url") or "").strip()
        if not url:
            return self._fail("source_url wajib diisi.")
        ok, msg, _ = _check_url_safety(url)
        if not ok:
            return self._fail(f"URL ditolak: {msg}")
        category = kw.get("source_category") or "tech"
        if category not in ("cyber", "tech"):
            return self._fail("source_category harus 'cyber' atau 'tech'.")
        name = str(kw.get("source_name") or urllib.parse.urlsplit(url).netloc).strip()
        try:
            async with self._client_factory() as client:
                body, _, _ = await asyncio.wait_for(safe_get(client, url, max_bytes=FEED_MAX_BYTES), FETCH_TIMEOUT)
            parsed = parse_feed(body, name, category)
        except UnsafeURLError as e:
            return self._fail(f"URL ditolak: {e}")
        except Exception as e:
            return self._fail(f"Feed tidak bisa dibaca ({e}). Pastikan itu URL RSS/Atom yang benar.")
        if not parsed:
            return self._fail("URL itu terbaca, tapi tidak berisi item RSS/Atom yang valid.")
        added = self.store.add_source(context.chat_id, url, name, category)
        return self._ok(f"Sumber '{name}' ditambahkan ({len(parsed)} item terbaca)." if added else "Sumber itu sudah ada.")

    def _set_topics(self, context: ToolContext, kw: dict[str, Any]) -> ToolResult:
        new = [str(t).strip().lower() for t in (kw.get("topics") or []) if str(t).strip()]
        if not new:
            return self._fail("topics wajib diisi (daftar kata kunci).")
        group = kw.get("group") or "tech"
        if group not in ("cyber", "tech"):
            return self._fail("group harus 'cyber' atau 'tech'.")
        topics = self.store.get_topics(context.chat_id)
        current = [] if kw.get("replace") else list(topics.get(group) or [])
        topics[group] = list(dict.fromkeys(current + new))
        self.store.set_topics(context.chat_id, topics)
        return self._ok(f"Topik {group} sekarang: {', '.join(topics[group])}.")
