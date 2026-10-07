from __future__ import annotations

import asyncio
import html
from html.parser import HTMLParser
import logging
import os
import random
import re
import time
import urllib.parse
from typing import Any

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
DDG_HTML_URL = "https://html.duckduckgo.com/html/"
DDG_LITE_URL = "https://lite.duckduckgo.com/lite/"


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
    if "uddg=" in raw_url:
        parsed = urllib.parse.urlparse(raw_url)
        qs = urllib.parse.parse_qs(parsed.query)
        if "uddg" in qs:
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


def _strip_html_tags(text: str) -> str:
    """Hapus tag HTML dan unescape entities."""
    if not text:
        return ""
    clean = re.sub(r"<[^>]+>", "", text)
    return html.unescape(clean).strip()


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
    """Tool pencarian dan penelusuran web otonom komprehensif mirip manusia (Human-grade Web Search & Deep Research)."""

    name = "web_search"
    description = (
        "Tool penelusuran web otonom tingkat tinggi layaknya pengguna manusia sungguhan. "
        "Mendukung 4 aksi: "
        "1. 'search': cari web dengan mesin DuckDuckGo, mengembalikan daftar sumber berperingkat (judul, URL, snippet). "
        "2. 'visit': mengunjungi dan membaca isi lengkap suatu halaman web (ekstrak artikel bersih tanpa iklan/script). "
        "3. 'deep_research': alur riset lengkap manusia (cari query -> telusuri top 3 sumber kredibel -> kompilasi data komprehensif). "
        "4. 'extract_links': melihat tautan-tautan yang ada di dalam suatu halaman web. "
        "Gunakan saat pengguna meminta mencari informasi internet, membaca berita/artikel web, riset kode/solusi, atau verifikasi fakta."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["search", "visit", "deep_research", "extract_links"],
                "description": (
                    "Aksi: 'search' (cari web), 'visit' (buka & baca halaman web), "
                    "'deep_research' (riset multi-sumber otomatis), 'extract_links' (ambil link di halaman)."
                ),
                "default": "search",
            },
            "query": {
                "type": "string",
                "description": "Kata kunci pencarian web (wajib untuk action 'search' dan 'deep_research').",
            },
            "url": {
                "type": "string",
                "description": "Alamat URL halaman web (wajib untuk action 'visit' dan 'extract_links').",
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
        else:
            return ToolResult(
                success=False,
                output="",
                error=f"Aksi '{action}' tidak dikenal. Pilihan: search, visit, deep_research, extract_links.",
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

        if not re.match(r"^https?://", raw_url, re.IGNORECASE):
            raw_url = "https://" + raw_url

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
            f"Kunjungan Web Berhasil",
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

        # Filter sumber teratas yang valid dan unik secara domain
        selected_sources: list[dict[str, str]] = []
        seen_domains: set[str] = set()

        for item in search_results:
            domain = urllib.parse.urlparse(item["url"]).netloc.lower()
            if domain and domain not in seen_domains:
                seen_domains.add(domain)
                selected_sources.append(item)
            if len(selected_sources) >= max_sources:
                break

        if not selected_sources:
            selected_sources = search_results[:max_sources]

        # Kunjungi masing-masing sumber layaknya manusia membaca
        compiled_findings: list[str] = []
        full_report_parts: list[str] = [
            f"# Laporan Riset Mandiri: {query}\nTanggal: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        ]

        for idx, src in enumerate(selected_sources, 1):
            if context.cancel_event.is_set():
                return ToolResult(success=False, output="", error="Riset dibatalkan oleh pengguna.")

            target_url = src["url"]
            if context.on_status_update:
                await context.on_status_update(
                    f"● [Riset Otonom] Tahap 2: Membaca sumber ({idx}/{len(selected_sources)}): {urllib.parse.urlparse(target_url).netloc}..."
                )

            # Jeda waktu manusiawi kecil (100-250 ms)
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
            # Potong ke inti terpenting (sekitar 1.500 karakter per sumber)
            sample_body = body[:1500].strip()

            compiled_findings.append(
                f"{idx}. {title}\n"
                f"   URL: {target_url}\n"
                f"   Inti Pembahasan:\n   {sample_body[:800]}..."
            )

            full_report_parts.append(
                f"## Sumber {idx}: {title}\nURL: {target_url}\n\n{body}\n\n---\n"
            )

        # Simpan laporan lengkap jika ada berkas
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

        if not re.match(r"^https?://", raw_url, re.IGNORECASE):
            raw_url = "https://" + raw_url

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

            base_parsed = urllib.parse.urlparse(raw_url)
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
    # Core Engine: Fetch Search Results
    # ------------------------------------------------------------------
    async def _fetch_search_results(
        self, query: str, max_results: int, region: str, time_filter: str
    ) -> tuple[list[dict[str, str]], str | None]:
        """Eksekusi pencarian dengan DuckDuckGo HTML dengan fallback otomatis."""
        headers = _random_headers(referer="https://duckduckgo.com/")

        post_data: dict[str, str] = {"q": query}
        if region and region != "wt-wt":
            post_data["kl"] = region
        if time_filter in ("d", "w", "m", "y"):
            post_data["df"] = time_filter

        try:
            async with httpx.AsyncClient(headers=headers, timeout=20.0, follow_redirects=True) as client:
                res = await client.post(DDG_HTML_URL, data=post_data)

            if res.status_code != 200:
                # Coba fallback via DuckDuckGo GET
                async with httpx.AsyncClient(headers=headers, timeout=20.0, follow_redirects=True) as client:
                    res = await client.get(f"{DDG_HTML_URL}?q={urllib.parse.quote(query)}")

            if res.status_code != 200:
                return [], f"Mesin pencari mengembalikan status HTTP {res.status_code}"

            html_content = res.text
            results: list[dict[str, str]] = []

            # Ekstrak blok-blok hasil pencarian DuckDuckGo HTML
            blocks = re.findall(
                r'<div class="[^"]*result results_links[^"]*">.*?</div>\s*</div>',
                html_content,
                re.DOTALL,
            )
            if not blocks:
                blocks = re.findall(r'<div class="result__body">.*?</div>', html_content, re.DOTALL)

            for b in blocks:
                # Judul & URL
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

                # Snippet
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
            logger.exception("Error executing search: %s", e)
            return [], f"Kesalahan saat mencari di web: {e}"

    # ------------------------------------------------------------------
    # Core Engine: Fetch & Parse Web Page
    # ------------------------------------------------------------------
    async def _fetch_page_content(self, url: str) -> tuple[dict[str, str], str | None]:
        """Unduh dan bersihkan isi dokumen web menjadi teks siap baca."""
        headers = _random_headers(referer="https://html.duckduckgo.com/")

        try:
            async with httpx.AsyncClient(headers=headers, timeout=25.0, follow_redirects=True) as client:
                res = await client.get(url)

            if res.status_code == 403:
                return {}, "Akses diblokir oleh situs (403 Forbidden - proteksi Cloudflare/WAF)."
            elif res.status_code == 404:
                return {}, "Halaman tidak ditemukan (404 Not Found)."
            elif res.status_code != 200:
                return {}, f"Gagal mengunduh halaman (HTTP {res.status_code})."

            ctype = res.headers.get("content-type", "").lower()
            if ctype and not any(t in ctype for t in ("text/html", "application/xhtml", "text/plain")):
                return {}, f"Format konten tidak didukung ({ctype}). Hanya berkas web HTML yang dapat dibaca."

            extractor = SmartWebExtractor()
            extractor.feed(res.text)
            title, desc, body = extractor.get_clean_text()

            return {
                "title": title,
                "description": desc,
                "body": body,
            }, None
        except httpx.TimeoutException:
            return {}, "Waktu tunggu habis saat membuka halaman (timeout)."
        except Exception as e:
            return {}, f"Kesalahan saat membuka halaman: {e}"
