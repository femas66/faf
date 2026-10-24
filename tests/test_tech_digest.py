from __future__ import annotations

import time

import httpx
import pytest

from src.config import Settings, set_settings
from src.tools import default_registry
from src.tools.base import ToolContext
from src.tools.cronjob_mgr import CronJobStore
from src.tools.tech_digest import (
    DEFAULT_TOPICS,
    DigestItem,
    DigestStore,
    TechDigestTool,
    format_digest,
    normalize_url,
    parse_feed,
    parse_github_search,
    parse_github_trending,
    parse_hn,
    score_and_filter,
    select_top,
)

RSS = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>Feed</title>
  <item><title>Critical zero-day in VPN actively exploited</title>
    <link>https://news.example/a?utm_source=x#frag</link>
    <description>&lt;p&gt;Patch now.&lt;/p&gt;</description>
    <pubDate>{now}</pubDate></item>
  <item><title>Old ransomware report</title>
    <link>https://news.example/old</link><pubDate>Mon, 01 Jan 2024 10:00:00 GMT</pubDate></item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>A</title>
  <entry><title>Atom post about Rust</title>
    <link rel="alternate" href="https://blog.example/rust"/>
    <updated>2099-01-01T00:00:00Z</updated><summary>Rust release notes</summary></entry>
</feed>"""

HN_JSON = {
    "hits": [
        {"objectID": "1", "title": "Big Linux kernel release", "url": "https://kernel.org/x",
         "points": 400, "num_comments": 120, "created_at_i": int(time.time()) - 3600},
        {"objectID": "2", "title": "Ask HN: small thing", "url": None, "points": 5, "num_comments": 2,
         "created_at_i": int(time.time())},
    ]
}

TRENDING_HTML = """
<html><body>
<article class="Box-row">
  <h2 class="h3 lh-condensed"><a href="/owner/scanner"> owner / scanner </a></h2>
  <p class="col-9 color-fg-muted my-1 pr-4">Fast container vulnerability scanner</p>
  <span itemprop="programmingLanguage">Go</span>
  <span class="d-inline-block float-sm-right">1,234 stars today</span>
</article>
<article class="Box-row">
  <h2><a href="/x/small">x / small</a></h2><p>tiny</p><span>12 stars today</span>
</article>
</body></html>"""


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    set_settings(Settings())
    monkeypatch.setattr("src.tools.safe_http._check_url_safety", lambda url, check_dangerous_extensions=True: (True, "ok", {}))
    monkeypatch.setattr("src.tools.tech_digest._check_url_safety", _fake_safety)
    yield
    set_settings(Settings())


def _fake_safety(url, check_dangerous_extensions=True):
    from src.tools.web_search import _check_url_safety

    if any(h in url for h in ("127.0.0.1", "localhost", "192.168.", "169.254.")):
        return _check_url_safety(url)
    return True, "ok", {}


def rss_bytes() -> bytes:
    from email.utils import formatdate

    return RSS.replace(b"{now}", formatdate(time.time()).encode())


def ctx(chat_id: int = 1) -> ToolContext:
    return ToolContext(chat_id=chat_id, user_id=chat_id)


def handler(request: httpx.Request) -> httpx.Response:
    host = request.url.host
    if host == "hn.algolia.com":
        return httpx.Response(200, json=HN_JSON)
    if host == "github.com":
        return httpx.Response(200, text=TRENDING_HTML)
    if host == "api.github.com":
        return httpx.Response(200, json={"items": []})
    if host == "atom.example":
        return httpx.Response(200, content=ATOM)
    if host in ("feeds.feedburner.com",):
        return httpx.Response(200, content=rss_bytes())
    return httpx.Response(404)


def make_tool(tmp_path, h=handler) -> TechDigestTool:
    return TechDigestTool(
        store=DigestStore(str(tmp_path / "digest.db")),
        cron_store=CronJobStore(str(tmp_path / "cron.json")),
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(h)),
    )


# --------------------------- parsers ---------------------------------------
def test_registered_in_registry():
    assert default_registry.get("tech_digest") is not None


def test_parse_rss_and_atom():
    items = parse_feed(rss_bytes(), "Feed", "cyber")
    assert len(items) == 2 and items[0].description == "Patch now."
    assert items[0].published_at is not None and items[0].category == "cyber"
    atom = parse_feed(ATOM, "A", "tech")
    assert atom[0].url == "https://blog.example/rust" and atom[0].published_at

def test_broken_feed_raises():
    with pytest.raises(Exception):
        parse_feed(b"<rss><item></rss>", "x", "tech")


def test_parse_hn():
    items = parse_hn(HN_JSON)
    assert items[0].score == 400 and items[1].url.startswith("https://news.ycombinator.com/item?id=2")


def test_parse_github_trending_and_fallback_parser():
    items = parse_github_trending(TRENDING_HTML)
    assert [i.title for i in items] == ["owner/scanner", "x/small"]
    assert items[0].score == 1234 and items[0].extra == "Go"
    assert parse_github_trending("<html>layout berubah</html>") == []
    s = parse_github_search({"items": [{"full_name": "a/b", "html_url": "https://github.com/a/b",
                                        "stargazers_count": 900, "language": "Rust", "description": "d"}]})
    assert s[0].title == "a/b" and s[0].score == 900


def test_normalize_url():
    assert normalize_url("HTTPS://News.Example/a/?utm_source=x&id=3#frag") == "https://news.example/a?id=3"


# --------------------------- scoring ---------------------------------------
def _topics():
    t = dict(DEFAULT_TOPICS)
    t["quality"] = {"hn_min_points": 100, "hn_min_comments": 50, "github_min_stars_today": 200}
    return t


def test_quality_filter_and_critical_bypass():
    now = time.time()
    items = [
        DigestItem(source="hn", title="Low quality Linux post", url="u1", score=5, comments=1, published_at=now),
        DigestItem(source="hn", title="Popular Linux kernel", url="u2", score=300, comments=10, published_at=now),
        DigestItem(source="hn", title="Zero-day exploit in router", url="u3", score=3, comments=0, published_at=now),
        DigestItem(source="github", title="a/b", url="u4", score=50),
        DigestItem(source="github", title="c/d", url="u5", score=500),
        DigestItem(source="rss", title="Old news", url="u6", published_at=now - 10 * 86400, category="tech"),
    ]
    out = score_and_filter(items, _topics(), now=now)
    urls = [i.url for i in out]
    assert "u1" not in urls and "u4" not in urls and "u6" not in urls
    assert {"u2", "u3", "u5"} <= set(urls)
    assert out[0].url == "u3" and out[0].critical  # kritis menempati urutan teratas
    assert next(i for i in out if i.url == "u3").section == "cyber"
    assert next(i for i in out if i.url == "u5").section == "github"


def test_cyber_section_by_keyword_and_topic_filter():
    now = time.time()
    items = [
        DigestItem(source="rss", title="New ransomware gang", url="a", published_at=now, category="tech"),
        DigestItem(source="rss", title="Rust 2.0 launch", url="b", published_at=now, category="tech"),
    ]
    out = score_and_filter(items, _topics(), now=now)
    assert next(i for i in out if i.url == "a").section == "cyber"
    assert next(i for i in out if i.url == "b").section == "tech"
    only = score_and_filter(items, _topics(), now=now, topic_filter="rust")
    assert [i.url for i in only] == ["b"]


def test_select_top_limits_and_message_length():
    now = time.time()
    items = [DigestItem(source="rss", title=f"ransomware {i}", url=f"c{i}", published_at=now, category="cyber") for i in range(9)]
    items += [DigestItem(source="rss", title=f"Rust launch {i}", url=f"t{i}", published_at=now, category="tech") for i in range(9)]
    items += [DigestItem(source="github", title=f"o/r{i}", url=f"g{i}", score=999) for i in range(9)]
    picked = select_top(score_and_filter(items, _topics(), now=now), 12)
    secs = [i.section for i in picked]
    assert secs.count("cyber") == 5 and secs.count("tech") == 4 and secs.count("github") == 3
    assert len(picked) == 12
    text = format_digest(picked, [])
    assert len(text) < 4096 and "**" not in text and "|" not in text
    assert text.index("Keamanan Siber") < text.index("Teknologi Terbaru") < text.index("GitHub Trending")


# --------------------------- store -----------------------------------------
def test_store_seen_and_purge(tmp_path):
    st = DigestStore(str(tmp_path / "d.db"))
    items = [DigestItem(source="rss", title="a", url="https://x.com/a?utm_source=1"),
             DigestItem(source="rss", title="a dup", url="https://x.com/a")]
    assert len(st.filter_unseen(1, items)) == 1  # duplikat dalam batch
    st.mark_seen(1, items[:1])
    assert st.filter_unseen(1, items) == []
    assert len(st.filter_unseen(2, items)) == 1  # per chat
    assert st.purge_old(0) == 1
    assert len(st.filter_unseen(1, items)) == 1


def test_store_sources_topics(tmp_path):
    st = DigestStore(str(tmp_path / "d.db"))
    st.ensure_chat(1, {"hn_min_points": 100})
    assert len(st.list_sources(1)) >= 10
    assert st.add_source(1, "https://a.example/rss", "A", "tech") is True
    assert st.add_source(1, "https://a.example/rss", "A", "tech") is False
    assert st.remove_source(1, "a") == 1
    assert "security" in st.get_topics(1)["cyber"]


# --------------------------- tool ------------------------------------------
async def test_run_end_to_end_and_dedup(tmp_path):
    tool = make_tool(tmp_path)
    res = await tool.execute(ctx(), action="run")
    assert res.success, res.error
    out = res.output
    assert "[PENTING]" in out and "zero-day" in out.lower()
    assert "Big Linux kernel release" in out  # HN lolos
    assert "Ask HN: small thing" not in out  # HN tidak lolos
    assert "owner/scanner" in out and "x/small" not in out
    assert "tidak bisa diakses" in out  # sebagian sumber default 404 -> dicatat
    # dijalankan lagi: item sudah dikirim tidak muncul lagi
    again = await tool.execute(ctx(), action="run")
    assert "Big Linux kernel release" not in again.output


async def test_run_preview_does_not_mark_seen(tmp_path):
    tool = make_tool(tmp_path)
    await tool.execute(ctx(), action="run", preview=True)
    second = await tool.execute(ctx(), action="run", preview=True)
    assert "Big Linux kernel release" in second.output


async def test_run_all_sources_down(tmp_path):
    tool = make_tool(tmp_path, lambda r: httpx.Response(500))
    res = await tool.execute(ctx(), action="run")
    assert not res.success and "tidak bisa diakses" in res.error


async def test_github_falls_back_to_search_api(tmp_path):
    def h(request: httpx.Request) -> httpx.Response:
        if request.url.host == "github.com":
            return httpx.Response(200, text="<html>kosong</html>")
        if request.url.host == "api.github.com":
            return httpx.Response(200, json={"items": [{"full_name": "z/fallback", "html_url": "https://github.com/z/fallback",
                                                        "stargazers_count": 900, "language": "Python"}]})
        return handler(request)

    tool = make_tool(tmp_path, h)
    res = await tool.execute(ctx(), action="run")
    assert "z/fallback" in res.output


async def test_schedule_creates_cron_job(tmp_path):
    tool = make_tool(tmp_path)
    res = await tool.execute(ctx(7), action="schedule", time="7:05")
    assert res.success and "07:05" in res.output
    job = await tool.cron_store.get("digest_7")
    assert job and job.schedule == "daily at 07:05" and job.timezone == "Asia/Jakarta"
    assert job.execution_type == "agent_prompt" and "tech_digest" in job.prompt
    bad = await tool.execute(ctx(7), action="schedule", time="25:99")
    assert not bad.success
    off = await tool.execute(ctx(7), action="unschedule")
    assert "dimatikan" in off.output and await tool.cron_store.get("digest_7") is None


async def test_add_source_validation(tmp_path):
    tool = make_tool(tmp_path)
    ssrf = await tool.execute(ctx(), action="add_source", source_url="http://192.168.1.5/feed")
    assert not ssrf.success and "ditolak" in ssrf.error.lower()
    notfeed = await tool.execute(ctx(), action="add_source", source_url="https://nothing.example/x")
    assert not notfeed.success
    ok = await tool.execute(ctx(), action="add_source", source_url="https://atom.example/feed", source_name="Atom", source_category="tech")
    assert ok.success and "ditambahkan" in ok.output
    listing = await tool.execute(ctx(), action="list_sources")
    assert "Atom" in listing.output
    removed = await tool.execute(ctx(), action="remove_source", source_name="atom")
    assert "dihapus" in removed.output


async def test_set_and_show_topics(tmp_path):
    tool = make_tool(tmp_path)
    res = await tool.execute(ctx(), action="set_topics", topics=["Blockchain", "web3"], group="tech")
    assert res.success and "blockchain" in res.output
    shown = await tool.execute(ctx(), action="show_topics")
    assert "blockchain" in shown.output and "zero-day" in shown.output
    replaced = await tool.execute(ctx(), action="set_topics", topics=["onlyone"], group="cyber", replace=True)
    assert "onlyone" in replaced.output and "malware" not in replaced.output
    assert not (await tool.execute(ctx(), action="set_topics")).success
