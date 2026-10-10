from __future__ import annotations

import asyncio
import base64
import html
from html.parser import HTMLParser
import ipaddress
import logging
import os
import random
import re
import socket
import time
import urllib.parse
from typing import Any
import xml.etree.ElementTree as ET

import httpx

from src.config import get_settings
from src.tools.base import BaseTool, ToolContext, ToolResult

logger = logging.getLogger("faf_agent.tools.web_search")

# Pool user agent realistis manusia (Desktop & Mobile)
USER_AGENTS = [
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36"
    ),
    (
        "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0"
    ),
]

MAX_INLINE_CHARS = 4500

# Pattern pendeteksi bot / WAF / Cloudflare captcha
_BOT_DETECTION_TITLE_PATTERNS = (
    "access denied", "access to this page has been denied", "blocked", "bot detected", "verification required",
    "please verify", "are you a robot", "captcha", "cloudflare", "ddos protection", "checking your browser",
    "just a moment", "attention required",
)

# Port berbahaya / non-web yang dilarang untuk mencegah port scanning & SSRF
_DANGEROUS_PORTS = {
    20, 21, 22, 23, 25, 53, 69, 110, 119, 123, 135, 137, 138, 139, 143,
    161, 389, 445, 514, 873, 1080, 1433, 1521, 2049, 3306, 3389, 5432,
    5900, 6379, 9200, 11211, 27017,
}

# Ekstensi berbahaya yang tidak boleh dibuka sebagai dokumen web
_DANGEROUS_EXTENSIONS = (
    ".exe", ".bat", ".cmd", ".sh", ".bash", ".apk", ".msi", ".vbs",
    ".ps1", ".scr", ".bin", ".jar", ".dll", ".so", ".dylib",
)

BING_SEARCH_URL = "https://www.bing.com/search"
GOOGLE_NEWS_RSS_URL = "https://news.google.com/rss/search"
WIKIPEDIA_API_URL = "https://id.wikipedia.org/w/api.php"


def _random_headers(referer: str | None = None) -> dict[str, str]:
    """Buat HTTP headers menyerupai browser pengguna manusia sungguhan."""
    ua = random.choice(USER_AGENTS)
    headers = {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin" if referer else "none",
        "Sec-Fetch-User": "?1",
    }
    if referer:
        headers["Referer"] = referer
    return headers


def _clean_url(raw_url: str) -> str:
    """Bersihkan redirect DuckDuckGo (uddg) dan parameter tracking."""
    if not raw_url:
        return ""
    if "uddg=" in raw_url:
        parsed = urllib.parse.urlparse(raw_url)
        qs = urllib.parse.parse_qs(parsed.query)
        if "uddg" in qs and qs["uddg"]:
            raw_url = qs["uddg"][0]

    # Bersihkan parameter pelacak umum (utm_*, fbclid, gclid, ref)
    try:
        p = urllib.parse.urlparse(raw_url)
        if p.query:
            filtered_q = [
                (k, v)
                for k, v in urllib.parse.parse_qsl(p.query)
                if not re.match(r"^(utm_|fbclid|gclid|ref|ref_src)", k, re.IGNORECASE)
            ]
            new_query = urllib.parse.urlencode(filtered_q)
            p = p._replace(query=new_query)
            return urllib.parse.urlunparse(p)
    except Exception:
        pass
    return raw_url


def _unwrap_bing_url(raw_url: str) -> str:
    """
    Ekstrak URL target asli dari redirect Bing (/ck/a?!...&u=a1<base64>).
    Menghilangkan roundtrip HTTP redirect dan tracking parameter.
    """
    if not raw_url:
        return ""
    clean = raw_url.replace("&amp;", "&")
    try:
        parsed = urllib.parse.urlparse(clean)
        qs = urllib.parse.parse_qs(parsed.query)
        if "u" in qs and qs["u"]:
            u_val = qs["u"][0]
            if u_val.startswith("a1"):
                b64 = u_val[2:]
                b64 += "=" * ((4 - len(b64) % 4) % 4)
                decoded = base64.urlsafe_b64decode(b64).decode("utf-8", errors="ignore")
                if decoded.startswith(("http://", "https://")):
                    return _clean_url(decoded)
    except Exception:
        pass
    return _clean_url(clean)


def _strip_html_tags(text: str) -> str:
    """Hapus tag HTML dan unescape entities."""
    if not text:
        return ""
    clean = re.sub(r"<[^>]+>", "", text)
    return html.unescape(clean).strip()


def _normalize_search_query(q: str) -> str:
    """
    Normalisasi pertanyaan percakapan manusia menjadi kata kunci pencarian terarah.
    Contoh: 'siapa pemenang indonesia vs thailand kemarin?' -> 'pemenang indonesia vs thailand kemarin'
    """
    if not q:
        return ""
    cleaned = re.sub(r"[?!.,;:\"'()[\]{}|\\]+", " ", q)
    stop_words = {
        "siapa", "apakah", "apa", "adakah", "dimana", "kemana", "bagaimana", "bagaimanakah",
        "kenapa", "mengapa", "kapan", "bisakah", "bolehkah", "tolong", "carikan", "cari",
        "infokan", "informasi", "tentang", "mengenai", "who", "what", "where", "when", "how", "why",
    }
    words = cleaned.split()
    filtered = [w for w in words if w.lower() not in stop_words]
    return " ".join(filtered) if filtered else cleaned.strip()


def _check_url_safety(url: str) -> tuple[bool, str, dict[str, Any]]:
    """
    Validasi keamanan URL tingkat tinggi (mencegah SSRF, private network bypass, port scanning,
    skema berbahaya, dan ekstensi file malware).
    Mengembalikan: (is_safe: bool, status_message: str, details: dict).
    PENTING: Jika tidak aman, pesan status WAJIB memuat frasa 'tidak aman'.
    """
    raw = (url or "").strip()
    if not raw:
        return False, "URL kosong (tidak aman).", {"url": raw}

    try:
        parsed = urllib.parse.urlsplit(raw)
    except Exception as e:
        return False, f"URL tidak dapat diparsing (tidak aman): {e}", {"url": raw}

    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        return False, f"Skema URL '{scheme}' tidak aman. Hanya http dan https yang diizinkan.", {
            "url": raw, "scheme": scheme,
        }

    if parsed.username or parsed.password:
        return False, "URL memuat kredensial akun/otentikasi (tidak aman).", {
            "url": raw, "has_credentials": True,
        }

    port = parsed.port
    if port and port in _DANGEROUS_PORTS:
        return False, f"Port {port} tergolong berbahaya/layanan internal (tidak aman).", {
            "url": raw, "port": port,
        }

    hostname = (parsed.hostname or "").strip().lower()
    if not hostname:
        return False, "URL tidak memiliki hostname/domain yang valid (tidak aman).", {
            "url": raw, "hostname": hostname,
        }

    blocked_local = {"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"}
    if hostname in blocked_local or hostname.endswith(".localhost"):
        return False, f"Hostname '{hostname}' merujuk ke mesin lokal (tidak aman / ancaman SSRF).", {
            "url": raw, "hostname": hostname,
        }

    # Cek apakah hostname adalah representasi IP langsung
    clean_host = hostname.strip("[]")
    try:
        ip = ipaddress.ip_address(clean_host)
        if ip.is_loopback:
            return False, f"Alamat IP {hostname} adalah loopback (tidak aman / ancaman SSRF).", {
                "url": raw, "ip": str(ip), "type": "loopback",
            }
        if ip.is_private:
            return False, f"Alamat IP {hostname} adalah jaringan privat (tidak aman / ancaman SSRF).", {
                "url": raw, "ip": str(ip), "type": "private",
            }
        if ip.is_link_local:
            return False, f"Alamat IP {hostname} adalah link-local (tidak aman / ancaman SSRF / metadata cloud).", {
                "url": raw, "ip": str(ip), "type": "link_local",
            }
        if ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            return False, f"Alamat IP {hostname} tidak aman.", {
                "url": raw, "ip": str(ip), "type": "reserved_or_unspecified",
            }
    except ValueError:
        # Hostname adalah nama domain, bukan IP langsung.
        # Resolusi DNS untuk proteksi SSRF terhadap domain yang mengarah ke internal/localhost
        try:
            resolved_ip_str = socket.gethostbyname(hostname)
            resolved_ip = ipaddress.ip_address(resolved_ip_str)
            if resolved_ip.is_loopback or resolved_ip.is_private or resolved_ip.is_link_local:
                return False, f"Domain '{hostname}' mengarah ke IP privat {resolved_ip_str} (tidak aman / ancaman SSRF).", {
                    "url": raw, "hostname": hostname, "resolved_ip": resolved_ip_str,
                }
        except (socket.gaierror, socket.herror, OSError, TimeoutError):
            pass

    # Cek ekstensi file berbahaya
    path_lower = parsed.path.lower()
    for ext in _DANGEROUS_EXTENSIONS:
        if path_lower.endswith(ext):
            return False, f"URL mengarah ke file eksekusi berbahaya '{ext}' (tidak aman).", {
                "url": raw, "extension": ext,
            }

    return True, "URL aman untuk diakses.", {
        "url": raw,
        "scheme": scheme,
        "hostname": hostname,
        "port": port or (443 if scheme == "https" else 80),
    }


class SmartWebExtractor(HTMLParser):
    """Parser HTML murni yang mengekstrak konten artikel utama dan mengabaikan script, iklan, serta navigasi."""

    def __init__(self) -> None:
        super().__init__()
        self.text_parts: list[str] = []
        self.title: str = ""
        self.meta_desc: str = ""
        self.in_title = False
        self.ignored_tags = {
            "script",
            "style",
            "nav",
            "header",
            "footer",
            "aside",
            "noscript",
            "svg",
            "form",
            "button",
            "canvas",
            "dialog",
        }
        self.ignore_depth = 0
        self.block_tags = {
            "p",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "li",
            "article",
            "section",
            "blockquote",
            "pre",
            "tr",
        }
        self.links: list[tuple[str, str]] = []  # (href, text)
        self.current_link_href: str | None = None
        self.current_link_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        attr_dict = {k.lower(): v for k, v in attrs if v is not None}

        if t in self.ignored_tags:
            self.ignore_depth += 1
            return

        if self.ignore_depth > 0:
            return

        if t == "title":
            self.in_title = True
        elif t == "meta":
            name = attr_dict.get("name", "").lower()
            prop = attr_dict.get("property", "").lower()
            if name in ("description", "og:description") or prop in ("description", "og:description"):
                if not self.meta_desc:
                    self.meta_desc = attr_dict.get("content", "").strip()
        elif t == "a":
            href = attr_dict.get("href", "")
            if href and not href.startswith(("#", "javascript:", "mailto:", "tel:")):
                self.current_link_href = href
                self.current_link_text = []
        elif t in self.block_tags:
            self.text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t in self.ignored_tags:
            if self.ignore_depth > 0:
                self.ignore_depth -= 1
            return

        if self.ignore_depth > 0:
            return

        if t == "title":
            self.in_title = False
        elif t == "a":
            if self.current_link_href:
                link_txt = "".join(self.current_link_text).strip()
                if link_txt:
                    self.links.append((self.current_link_href, link_txt))
            self.current_link_href = None
            self.current_link_text = []
        elif t in self.block_tags:
            self.text_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title += data
            return

        if self.ignore_depth == 0:
            clean = data.strip()
            if clean:
                self.text_parts.append(clean + " ")
            if self.current_link_href is not None:
                self.current_link_text.append(data)

    def get_clean_text(self) -> tuple[str, str, str]:
        """Kembalikan (title, meta_description, clean_body_text)."""
        raw = "".join(self.text_parts)
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        body = "\n\n".join(lines)
        return html.unescape(self.title.strip()), html.unescape(self.meta_desc.strip()), body


class WebSearchTool(BaseTool):
    """Tool browser dan penelusuran web komprehensif tingkat tinggi layaknya pengguna manusia sungguhan."""

    name = "web_search"
    description = (
        "Tool penelusuran dan interaksi web otonom komprehensif tingkat tinggi. "
        "Mendukung 6 aksi: "
        "1. 'search': cari web dengan mesin Bing & feed berita terkini (judul, URL, snippet). "
        "2. 'visit': mengunjungi dan membaca isi lengkap suatu halaman web dengan perlindungan anti-bot & keamanan URL. "
        "3. 'deep_research': alur riset multi-sumber otomatis (mencari -> membuka top sumber aman -> sintesis laporan). "
        "4. 'extract_links': mengambil daftar tautan keluar di halaman web. "
        "5. 'check_safety': audit keamanan URL mendalam (deteksi SSRF, IP privat, port berbahaya, ekstensi malware). "
        "6. 'inspect': inspeksi teknis halaman web (HTTP status, server headers, meta tags, security headers). "
        "Gunakan untuk mencari info internet, membaca berita/artikel, riset kode/solusi, verifikasi fakta, atau audit link."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["search", "visit", "deep_research", "extract_links", "check_safety", "inspect"],
                "description": (
                    "Aksi: 'search' (cari web), 'visit' (buka & baca halaman web), "
                    "'deep_research' (riset multi-sumber), 'extract_links' (ambil tautan), "
                    "'check_safety' (cek keamanan URL), 'inspect' (inspeksi header & meta)."
                ),
                "default": "search",
            },
            "query": {
                "type": "string",
                "description": "Kata kunci pencarian web (wajib untuk 'search' dan 'deep_research').",
            },
            "url": {
                "type": "string",
                "description": "Alamat URL halaman web (wajib untuk 'visit', 'extract_links', 'check_safety', 'inspect').",
            },
            "max_results": {
                "type": "integer",
                "description": "Batas jumlah hasil pencarian (default: 5, maksimal: 10).",
                "default": 5,
            },
            "region": {
                "type": "string",
                "description": "Region pencarian, contoh: 'id-id' (Indonesia, default) atau 'wt-wt' (global).",
                "default": "id-id",
            },
            "time_filter": {
                "type": "string",
                "enum": ["all", "d", "w", "m", "y"],
                "description": "Filter waktu pencarian: 'all' (semua), 'd' (hari ini), 'w' (minggu ini), 'm' (bulan ini), 'y' (tahun ini).",
                "default": "all",
            },
            "save_to": {
                "type": "string",
                "description": "Opsional: path file lokal untuk menyimpan hasil riset/teks artikel.",
            },
        },
        "required": [],
    }

    async def execute(self, context: ToolContext, **kwargs: Any) -> ToolResult:
        action = str(kwargs.get("action") or "search").lower().strip()
        settings = get_settings()

        if action == "search":
            return await self._action_search(context, kwargs)
        elif action == "visit":
            return await self._action_visit(context, kwargs, settings.temp_media_dir)
        elif action == "deep_research":
            return await self._action_deep_research(context, kwargs, settings.temp_media_dir)
        elif action == "extract_links":
            return await self._action_extract_links(context, kwargs)
        elif action == "check_safety":
            return await self._action_check_safety(context, kwargs)
        elif action == "inspect":
            return await self._action_inspect(context, kwargs)
        else:
            return ToolResult(
                success=False,
                output="",
                error=f"Aksi '{action}' tidak dikenal. Pilihan: search, visit, deep_research, extract_links, check_safety, inspect.",
            )

    # ------------------------------------------------------------------
    # Action 1: Search
    # ------------------------------------------------------------------
    async def _action_search(self, context: ToolContext, kwargs: dict[str, Any]) -> ToolResult:
        query = str(kwargs.get("query") or "").strip()
        if not query:
            return ToolResult(success=False, output="", error="Parameter 'query' wajib diisi untuk pencarian.")

        max_results = min(max(int(kwargs.get("max_results") or 5), 1), 10)
        region = str(kwargs.get("region") or "id-id").strip()
        time_filter = str(kwargs.get("time_filter") or "all").lower().strip()

        if context.on_status_update:
            await context.on_status_update(f"● Menelusuri web untuk: '{query}'...")

        results, err = await self._fetch_search_results(query, max_results, region, time_filter)
        if err:
            return ToolResult(success=False, output="", error=err)

        if not results:
            return ToolResult(
                success=True,
                output=f"Tidak ditemukan hasil pencarian untuk kata kunci: '{query}'. Coba gunakan kata kunci lain.",
            )

        lines = [
            f"Hasil Pencarian Web (Ditemukan {len(results)} sumber)",
            f"• Kata Kunci : '{query}'",
            f"• Region     : {region}",
            f"• Filter Waktu: {time_filter}",
            "",
        ]

        for i, item in enumerate(results, 1):
            domain = urllib.parse.urlparse(item["url"]).netloc
            lines.append(f"{i}. {item['title']}")
            lines.append(f"   Domain : {domain}")
            lines.append(f"   URL    : {item['url']}")
            if item.get("snippet"):
                lines.append(f"   Ringkasan: {item['snippet']}")
            lines.append("")

        return ToolResult(success=True, output="\n".join(lines).strip())

    # ------------------------------------------------------------------
    # Action 2: Visit Page
    # ------------------------------------------------------------------
    async def _action_visit(
        self, context: ToolContext, kwargs: dict[str, Any], temp_dir: str
    ) -> ToolResult:
        raw_url = str(kwargs.get("url") or "").strip()
        if not raw_url:
            return ToolResult(success=False, output="", error="Parameter 'url' wajib diisi untuk mengunjungi halaman.")

        if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", raw_url):
            raw_url = "https://" + raw_url

        # Validasi keamanan URL (SSRF, IP privat, skema, dll.)
        is_safe, safety_msg, _ = _check_url_safety(raw_url)
        if not is_safe:
            return ToolResult(
                success=False,
                output="",
                error=f"Akses ditolak karena URL tidak aman: {safety_msg}",
            )

        if context.on_status_update:
            await context.on_status_update(f"● Mengunjungi halaman: {raw_url}...")

        page_data, err = await self._fetch_page_content(raw_url)
        if err:
            return ToolResult(success=False, output="", error=err)

        title = page_data.get("title") or "Tanpa Judul"
        desc = page_data.get("description") or ""
        body = page_data.get("body") or ""

        if not body:
            return ToolResult(
                success=True,
                output=(
                    f"Halaman berhasil dibuka ({raw_url}), namun tidak ditemukan teks konten utama yang dapat dibaca. "
                    "Halaman mungkin menggunakan JavaScript rendering berat (SPA) atau memblokir scraping teks."
                ),
            )

        total_chars = len(body)
        save_to = str(kwargs.get("save_to") or "").strip()
        if not save_to and total_chars > MAX_INLINE_CHARS:
            try:
                os.makedirs(temp_dir, exist_ok=True)
                save_to = os.path.join(temp_dir, f"web_article_{int(time.time())}.txt")
            except OSError:
                save_to = ""

        saved_path: str | None = None
        if save_to:
            try:
                save_to = os.path.expanduser(save_to)
                os.makedirs(os.path.dirname(save_to) or ".", exist_ok=True)
                with open(save_to, "w", encoding="utf-8") as f:
                    f.write(f"URL: {raw_url}\nJudul: {title}\n\n{body}")
                saved_path = save_to
            except OSError as e:
                logger.warning("Failed to save article text: %s", e)

        shown_body = (
            body if total_chars <= MAX_INLINE_CHARS else body[:MAX_INLINE_CHARS] + "\n...(konten panjang, teks lengkap tersimpan di berkas)"
        )

        header_lines = [
            "Kunjungan Web Berhasil",
            f"• Judul       : {title}",
            f"• URL         : {raw_url}",
            f"• Panjang     : {total_chars} karakter",
        ]
        if desc:
            header_lines.append(f"• Deskripsi   : {desc}")
        if saved_path:
            header_lines.append(f"• Disimpan ke : {saved_path}")

        header_lines.append("\n--- ISI KONTEN ---")
        header_lines.append(shown_body)

        return ToolResult(
            success=True,
            output="\n".join(header_lines),
            media_path=saved_path,
            media_type="document" if saved_path else None,
        )

    # ------------------------------------------------------------------
    # Action 3: Deep Research (Multi-Source Human Synthesis)
    # ------------------------------------------------------------------
    async def _action_deep_research(
        self, context: ToolContext, kwargs: dict[str, Any], temp_dir: str
    ) -> ToolResult:
        query = str(kwargs.get("query") or "").strip()
        if not query:
            return ToolResult(success=False, output="", error="Parameter 'query' wajib diisi untuk deep_research.")

        max_sources = min(max(int(kwargs.get("max_results") or 3), 2), 5)
        region = str(kwargs.get("region") or "id-id").strip()
        time_filter = str(kwargs.get("time_filter") or "all").lower().strip()

        if context.on_status_update:
            await context.on_status_update(f"● [Riset Otonom] Tahap 1: Mencari sumber terpercaya untuk '{query}'...")

        search_results, err = await self._fetch_search_results(query, max_sources + 2, region, time_filter)
        if err or not search_results:
            return ToolResult(
                success=False,
                output="",
                error=f"Gagal menemukan sumber awal untuk riset: {err or 'Hasil kosong'}",
            )

        # Filter sumber teratas yang valid dan aman
        selected_sources: list[dict[str, str]] = []
        seen_domains: set[str] = set()

        for item in search_results:
            target_url = item["url"]
            safe, _, _ = _check_url_safety(target_url)
            if not safe:
                continue

            domain = urllib.parse.urlparse(target_url).netloc.lower()
            if domain and domain not in seen_domains:
                seen_domains.add(domain)
                selected_sources.append(item)
            if len(selected_sources) >= max_sources:
                break

        if not selected_sources:
            selected_sources = [s for s in search_results if _check_url_safety(s["url"])[0]][:max_sources]

        if not selected_sources:
            return ToolResult(
                success=False,
                output="",
                error="Semua sumber hasil pencarian tidak aman untuk dikunjungi.",
            )

        # Kunjungi masing-masing sumber layaknya manusia membaca
        compiled_findings: list[str] = []
        full_report_parts: list[str] = [
            f"# Laporan Riset Mandiri: {query}\nTanggal: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        ]

        for idx, src in enumerate(selected_sources, 1):
            if context.cancel_event.is_set():
                return ToolResult(success=False, output="", error="Riset dibatalkan oleh pengguna.")

            target_url = src["url"]
            domain_name = urllib.parse.urlparse(target_url).netloc
            if context.on_status_update:
                await context.on_status_update(
                    f"● [Riset Otonom] Tahap 2: Membaca sumber ({idx}/{len(selected_sources)}): {domain_name}..."
                )

            await asyncio.sleep(random.uniform(0.1, 0.25))

            page_data, page_err = await self._fetch_page_content(target_url)
            if page_err or not page_data.get("body"):
                compiled_findings.append(
                    f"{idx}. [{src['title']}]({target_url})\n"
                    f"   Catatan: Halaman tidak dapat diekstrak langsung ({page_err or 'konten kosong'}). "
                    f"Snippet pencarian: {src.get('snippet', '-')}"
                )
                continue

            title = page_data.get("title") or src["title"]
            body = page_data.get("body") or ""
            sample_body = body[:1500].strip()

            compiled_findings.append(
                f"{idx}. {title}\n"
                f"   URL: {target_url}\n"
                f"   Inti Pembahasan:\n   {sample_body[:800]}..."
            )

            full_report_parts.append(
                f"## Sumber {idx}: {title}\nURL: {target_url}\n\n{body}\n\n---\n"
            )

        saved_path: str | None = None
        try:
            os.makedirs(temp_dir, exist_ok=True)
            report_file = os.path.join(temp_dir, f"research_{int(time.time())}.txt")
            with open(report_file, "w", encoding="utf-8") as f:
                f.write("\n".join(full_report_parts))
            saved_path = report_file
        except OSError as e:
            logger.debug("Could not write research report file to %s: %s", temp_dir, e)

        output_text = (
            f"Riset Multi-Sumber Selesai ({len(selected_sources)} sumber diteliti)\n"
            f"• Topik: '{query}'\n\n"
            + "\n\n".join(compiled_findings)
        )

        return ToolResult(
            success=True,
            output=output_text,
            media_path=saved_path,
            media_type="document" if saved_path else None,
        )

    # ------------------------------------------------------------------
    # Action 4: Extract Links
    # ------------------------------------------------------------------
    async def _action_extract_links(self, context: ToolContext, kwargs: dict[str, Any]) -> ToolResult:
        raw_url = str(kwargs.get("url") or "").strip()
        if not raw_url:
            return ToolResult(success=False, output="", error="Parameter 'url' wajib diisi.")

        if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", raw_url):
            raw_url = "https://" + raw_url

        is_safe, safety_msg, _ = _check_url_safety(raw_url)
        if not is_safe:
            return ToolResult(
                success=False,
                output="",
                error=f"Akses ditolak karena URL tidak aman: {safety_msg}",
            )

        if context.on_status_update:
            await context.on_status_update(f"● Mengekstrak link dari: {raw_url}...")

        headers = _random_headers(referer=raw_url)
        try:
            async with httpx.AsyncClient(headers=headers, timeout=20.0, follow_redirects=True) as client:
                res = await client.get(raw_url)
            if res.status_code != 200:
                return ToolResult(success=False, output="", error=f"Gagal membuka URL (HTTP {res.status_code}).")

            extractor = SmartWebExtractor()
            extractor.feed(res.text)

            links = []
            seen = set()
            for href, txt in extractor.links:
                full_url = urllib.parse.urljoin(raw_url, href)
                if full_url not in seen and full_url.startswith(("http://", "https://")):
                    seen.add(full_url)
                    links.append((full_url, txt[:80]))
                if len(links) >= 20:
                    break

            if not links:
                return ToolResult(success=True, output=f"Tidak ditemukan tautan keluar yang relevan di {raw_url}.")

            out_lines = [f"Tautan Keluar di {raw_url} (Top {len(links)}):", ""]
            for i, (u, t) in enumerate(links, 1):
                out_lines.append(f"{i}. [{t or 'Tautan'}] -> {u}")

            return ToolResult(success=True, output="\n".join(out_lines))
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Gagal mengekstrak tautan: {e}")

    # ------------------------------------------------------------------
    # Action 5: Check URL Safety
    # ------------------------------------------------------------------
    async def _action_check_safety(self, context: ToolContext, kwargs: dict[str, Any]) -> ToolResult:
        raw_url = str(kwargs.get("url") or "").strip()
        if not raw_url:
            return ToolResult(success=False, output="", error="Parameter 'url' wajib diisi untuk memeriksa keamanan.")

        if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", raw_url):
            raw_url = "https://" + raw_url

        if context.on_status_update:
            await context.on_status_update(f"● Memeriksa keamanan URL: {raw_url}...")

        is_safe, msg, info = _check_url_safety(raw_url)
        verdict = "AMAN" if is_safe else "TIDAK AMAN"

        lines = [
            f"Laporan Audit Keamanan URL: [{verdict}]",
            f"• Status      : {verdict}",
            f"• Detail      : {msg}",
            f"• URL Target  : {raw_url}",
            f"• Skema       : {info.get('scheme', '-')}",
            f"• Host/Domain : {info.get('hostname', '-')}",
            f"• Port        : {info.get('port', '-')}",
        ]
        if info.get("resolved_ip"):
            lines.append(f"• Resolusi IP : {info['resolved_ip']}")
        if info.get("extension"):
            lines.append(f"• Ekstensi    : {info['extension']}")

        if not is_safe:
            return ToolResult(
                success=False,
                output="",
                error=f"URL tidak aman: {msg}\n" + "\n".join(lines),
            )

        return ToolResult(success=True, output="\n".join(lines))

    # ------------------------------------------------------------------
    # Action 6: Inspect Page Headers & Metadata
    # ------------------------------------------------------------------
    async def _action_inspect(self, context: ToolContext, kwargs: dict[str, Any]) -> ToolResult:
        raw_url = str(kwargs.get("url") or "").strip()
        if not raw_url:
            return ToolResult(success=False, output="", error="Parameter 'url' wajib diisi untuk inspeksi halaman.")

        if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", raw_url):
            raw_url = "https://" + raw_url

        is_safe, msg, _ = _check_url_safety(raw_url)
        if not is_safe:
            return ToolResult(success=False, output="", error=f"URL tidak aman: {msg}")

        if context.on_status_update:
            await context.on_status_update(f"● Menginspeksi halaman web: {raw_url}...")

        headers = _random_headers(referer="https://www.bing.com/")
        try:
            start_t = time.time()
            async with httpx.AsyncClient(headers=headers, timeout=20.0, follow_redirects=True) as client:
                res = await client.get(raw_url)
            elapsed_ms = int((time.time() - start_t) * 1000)

            extractor = SmartWebExtractor()
            extractor.feed(res.text)
            title, desc, _ = extractor.get_clean_text()

            # Analisis header keamanan
            sec_headers = {
                "HSTS": res.headers.get("strict-transport-security", "Tidak ada"),
                "X-Frame-Options": res.headers.get("x-frame-options", "Tidak ada"),
                "X-Content-Type-Options": res.headers.get("x-content-type-options", "Tidak ada"),
                "Content-Security-Policy": "Ada" if "content-security-policy" in res.headers else "Tidak ada",
            }

            content_size = len(res.content) if hasattr(res, "content") else len(res.text.encode("utf-8"))
            status_reason = getattr(res, "reason_phrase", "OK")

            lines = [
                f"Hasil Inspeksi Halaman Web: {raw_url}",
                f"• Status HTTP      : {res.status_code} ({status_reason})",
                f"• Waktu Respon     : {elapsed_ms} ms",
                f"• Server           : {res.headers.get('server', '-')}",
                f"• Content-Type     : {res.headers.get('content-type', '-')}",
                f"• Ukuran Konten    : {content_size} bytes",
                f"• Judul Halaman    : {title or '-'}",
                f"• Meta Deskripsi   : {desc or '-'}",
                "",
                "Keamanan Header:",
                f"• HSTS                     : {sec_headers['HSTS']}",
                f"• X-Frame-Options          : {sec_headers['X-Frame-Options']}",
                f"• X-Content-Type-Options   : {sec_headers['X-Content-Type-Options']}",
                f"• Content-Security-Policy  : {sec_headers['Content-Security-Policy']}",
            ]

            return ToolResult(success=True, output="\n".join(lines))
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Gagal menginspeksi halaman: {e}")

    # ------------------------------------------------------------------
    # Core Engine: Fetch Search Results
    # ------------------------------------------------------------------
    async def _fetch_search_results(
        self, query: str, max_results: int, region: str, time_filter: str
    ) -> tuple[list[dict[str, str]], str | None]:
        """
        Pencarian web tangguh dengan mesin Bing sebagai sumber utama,
        didukung query normalization dan Google News RSS untuk topik hangat.
        """
        headers = _random_headers(referer="https://www.bing.com/")
        normalized_q = _normalize_search_query(query)

        # 1. Coba pencarian Bing primer
        bing_results, bing_err = await self._fetch_bing_results(query, max_results, region, time_filter, headers)

        # Jika query percakapan ('siapa pemenang...'), dan hasil Bing kurang atau kosong,
        # coba cari dengan query ternormalisasi
        if not bing_err and not bing_results and normalized_q and normalized_q.lower() != query.lower():
            norm_results, norm_err = await self._fetch_bing_results(normalized_q, max_results, region, time_filter, headers)
            if norm_results:
                bing_results = norm_results
            elif norm_err:
                bing_err = norm_err

        # 2. Cek apakah kueri mengindikasikan berita / pertandingan / hasil terkini
        news_keywords = {"vs", "skor", "menang", "pemenang", "hasil", "kemarin", "hari ini", "juara", "final", "pertandingan", "terbaru"}
        query_words = set(re.findall(r"\w+", query.lower()))
        is_news_like = bool(query_words & news_keywords)

        if is_news_like:
            news_results = await self._fetch_news_results(normalized_q or query, max_results=3)
            if news_results:
                existing_urls = {item["url"] for item in bing_results}
                combined = [n for n in news_results if n["url"] not in existing_urls] + bing_results
                return combined[:max_results], None

        if bing_results:
            return bing_results[:max_results], None

        # Jika Bing berhasil merespon tanpa error tapi memang tidak ada hasil
        if bing_err is None and not bing_results:
            return [], None

        # 3. Fallback jika Bing mengalami kegagalan teknis (error/timeout)
        news_fallback = await self._fetch_news_results(normalized_q or query, max_results)
        if news_fallback:
            return news_fallback, None

        wiki_fallback = await self._fetch_wikipedia_results(normalized_q or query, max_results)
        if wiki_fallback:
            return wiki_fallback, None

        return [], bing_err or "Tidak ditemukan hasil yang cocok dari mesin pencari."

    async def _fetch_bing_results(
        self, query: str, max_results: int, region: str, time_filter: str, headers: dict[str, str]
    ) -> tuple[list[dict[str, str]], str | None]:
        """Eksekusi pencarian Bing dan parsing HTML secara aman."""
        post_data: dict[str, str] = {"q": query}
        params: dict[str, str] = {"q": query}

        if region.startswith("id"):
            post_data["setmkt"] = "id-ID"
            post_data["setlang"] = "id"
            params["setmkt"] = "id-ID"
            params["setlang"] = "id"
        else:
            post_data["setmkt"] = "en-US"
            post_data["setlang"] = "en"
            params["setmkt"] = "en-US"
            params["setlang"] = "en"

        if time_filter in ("d", "w", "m", "y"):
            filter_str = f" qft=+filterui:age-1{time_filter}"
            post_data["q"] += filter_str
            params["q"] += filter_str

        try:
            # Utamakan POST untuk kompatibilitas mock testing & proxy
            async with httpx.AsyncClient(headers=headers, timeout=20.0, follow_redirects=True) as client:
                res = await client.post(BING_SEARCH_URL, data=post_data)

            if res.status_code != 200:
                # Coba fallback via GET
                async with httpx.AsyncClient(headers=headers, timeout=20.0, follow_redirects=True) as client:
                    res = await client.get(BING_SEARCH_URL, params=params)

            if res.status_code != 200:
                return [], f"Mesin pencari mengembalikan status HTTP {res.status_code}"

            html_content = res.text
            results: list[dict[str, str]] = []

            # Format 1: Bing <li class="b_algo">
            blocks = re.findall(r'<li class="b_algo".*?</li>', html_content, re.DOTALL)
            for b in blocks:
                m_title = re.search(r'<h2><a[^>]*href="([^"]+)"[^>]*>(.*?)</a></h2>', b, re.DOTALL)
                if not m_title:
                    continue

                raw_url = m_title.group(1).strip()
                raw_title = _strip_html_tags(m_title.group(2))
                clean_target_url = _unwrap_bing_url(raw_url)

                m_snip = re.search(r'<div class="b_caption">.*?<p[^>]*>(.*?)</p>', b, re.DOTALL)
                if not m_snip:
                    m_snip = re.search(r'<p[^>]*>(.*?)</p>', b, re.DOTALL)
                raw_snippet = _strip_html_tags(m_snip.group(1)) if m_snip else ""

                if clean_target_url and clean_target_url.startswith("http"):
                    results.append(
                        {
                            "title": raw_title or "Tanpa Judul",
                            "url": clean_target_url,
                            "snippet": raw_snippet,
                        }
                    )
                if len(results) >= max_results:
                    break

            # Format 2 (kompatibilitas pengujian/fallback): DuckDuckGo HTML blok
            if not results:
                ddg_blocks = re.findall(
                    r'<div class="[^"]*result results_links[^"]*">.*?</div>\s*</div>',
                    html_content,
                    re.DOTALL,
                )
                if not ddg_blocks:
                    ddg_blocks = re.findall(r'<div class="result__body">.*?</div>', html_content, re.DOTALL)

                for b in ddg_blocks:
                    m_title = re.search(
                        r'<h2 class="result__title">\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
                        b,
                        re.DOTALL,
                    )
                    if not m_title:
                        continue
                    raw_url = m_title.group(1).strip()
                    raw_title = _strip_html_tags(m_title.group(2))
                    clean_target_url = _clean_url(raw_url)
                    m_snip = re.search(r'class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>', b, re.DOTALL)
                    if not m_snip:
                        m_snip = re.search(r'class="result__snippet"[^>]*>(.*?)<', b, re.DOTALL)
                    raw_snippet = _strip_html_tags(m_snip.group(1)) if m_snip else ""

                    if clean_target_url and clean_target_url.startswith("http"):
                        results.append(
                            {
                                "title": raw_title or "Tanpa Judul",
                                "url": clean_target_url,
                                "snippet": raw_snippet,
                            }
                        )
                    if len(results) >= max_results:
                        break

            return results, None
        except httpx.TimeoutException:
            return [], "Pencarian web melebihi batas waktu (timeout)."
        except Exception as e:
            logger.debug("Error executing Bing search: %s", e)
            return [], f"Kesalahan saat mencari di web: {e}"

    async def _fetch_news_results(self, query: str, max_results: int = 5) -> list[dict[str, str]]:
        """Ambil berita relevan terkini dari Google News RSS."""
        try:
            params = {
                "q": query,
                "hl": "id",
                "gl": "ID",
                "ceid": "ID:id",
            }
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                res = await client.get(GOOGLE_NEWS_RSS_URL, params=params)
            if res.status_code != 200:
                return []

            root = ET.fromstring(res.text)
            news_items: list[dict[str, str]] = []
            for it in root.findall(".//item"):
                title_elem = it.find("title")
                link_elem = it.find("link")
                desc_elem = it.find("description")
                if title_elem is None or not title_elem.text:
                    continue

                title = html.unescape(title_elem.text.strip())
                link = link_elem.text.strip() if link_elem is not None and link_elem.text else ""
                snippet = _strip_html_tags(desc_elem.text) if desc_elem is not None and desc_elem.text else ""

                news_items.append({
                    "title": title,
                    "url": link,
                    "snippet": snippet,
                })
                if len(news_items) >= max_results:
                    break
            return news_items
        except Exception as e:
            logger.debug("Google News RSS fetch error: %s", e)
            return []

    async def _fetch_wikipedia_results(self, query: str, max_results: int = 3) -> list[dict[str, str]]:
        """Ambil ringkasan ensiklopedia dari Wikipedia API bahasa Indonesia."""
        try:
            params = {
                "action": "query",
                "list": "search",
                "srsearch": query,
                "format": "json",
                "utf8": "1",
            }
            headers = {"User-Agent": "FAFAgent/1.0 (https://github.com/faf-agent; contact@fafagent.local)"}
            async with httpx.AsyncClient(headers=headers, timeout=10.0, follow_redirects=True) as client:
                res = await client.get(WIKIPEDIA_API_URL, params=params)
            if res.status_code != 200:
                return []

            data = res.json()
            search_entries = data.get("query", {}).get("search", [])
            wiki_items: list[dict[str, str]] = []
            for item in search_entries[:max_results]:
                title = item.get("title", "")
                snippet = _strip_html_tags(item.get("snippet", ""))
                article_url = f"https://id.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}"
                wiki_items.append({
                    "title": f"{title} - Wikipedia",
                    "url": article_url,
                    "snippet": snippet,
                })
            return wiki_items
        except Exception as e:
            logger.debug("Wikipedia fetch error: %s", e)
            return []

    # ------------------------------------------------------------------
    # Core Engine: Fetch & Parse Web Page
    # ------------------------------------------------------------------
    async def _fetch_page_content(self, url: str) -> tuple[dict[str, str], str | None]:
        """Unduh dan bersihkan isi dokumen web menjadi teks siap baca dengan deteksi bot komprehensif."""
        headers = _random_headers(referer="https://www.bing.com/")

        try:
            async with httpx.AsyncClient(headers=headers, timeout=25.0, follow_redirects=True) as client:
                res = await client.get(url)

            # Cek status kode
            if res.status_code == 404:
                return {}, "Halaman tidak ditemukan (404 Not Found)."
            elif res.status_code in (403, 429):
                text_lower = res.text[:2500].lower()
                for pat in _BOT_DETECTION_TITLE_PATTERNS:
                    if pat in text_lower:
                        return {}, f"Situs memblokir akses bot (HTTP {res.status_code} - terdeteksi '{pat}' / Cloudflare / WAF)."
                return {}, f"Akses diblokir oleh situs (HTTP {res.status_code} - proteksi Cloudflare/WAF)."
            elif res.status_code != 200:
                return {}, f"Gagal mengunduh halaman (HTTP {res.status_code})."

            ctype = res.headers.get("content-type", "").lower()
            if ctype and not any(t in ctype for t in ("text/html", "application/xhtml", "text/plain")):
                return {}, f"Format konten tidak didukung ({ctype}). Hanya berkas web HTML yang dapat dibaca."

            extractor = SmartWebExtractor()
            extractor.feed(res.text)
            title, desc, body = extractor.get_clean_text()

            # Pengecekan bot detection berdasarkan judul dan konten awal
            title_lower = title.lower()
            body_intro = body[:1000].lower()
            for pat in _BOT_DETECTION_TITLE_PATTERNS:
                if pat in title_lower or pat in body_intro:
                    return {}, f"Situs memblokir akses bot (terdeteksi tantangan bot: '{pat}' / proteksi Cloudflare / WAF)."

            return {
                "title": title,
                "description": desc,
                "body": body,
            }, None
        except httpx.TimeoutException:
            return {}, "Waktu tunggu habis saat membuka halaman (timeout)."
        except Exception as e:
            return {}, f"Kesalahan saat membuka halaman: {e}"
