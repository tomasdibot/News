"""News about the artists you like (typed in the app or read from your Spotify).

For each artist, Google News is searched (Spanish and English); every result keeps the name of
the outlet that published it, so a release or tour covered by several outlets becomes one story
with several sources, like any other story. These stories then go through the normal ranking
and the AI theme filter (a "Música" theme gets them).
"""

from __future__ import annotations

import concurrent.futures as cf
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import feedparser

from .config import ROOT, Source
from .fetch import SAFE_LINK, Article, _get, _published
from .music import MAX_ARTISTS
from .text import clean_html, normalize

log = logging.getLogger(__name__)

CACHE_PATH = ROOT / "build" / "gnews-cache.json"   # last good search results (kept by the workflow)
EDITIONS = [("es", "hl=es-419&gl=AR&ceid=AR:es-419"), ("en", "hl=en-US&gl=US&ceid=US:en")]
PER_FEED = 8
SHOW_EDITION = EDITIONS[0][1]
SHOW_QUERIES = ["gira Argentina", "show en Buenos Aires", "recital Argentina", "concierto Buenos Aires",
                "festival música Argentina", "entradas a la venta show", "gira 2026 Argentina",
                "show en Córdoba", "show en Rosario"]
SHOW_DAYS = 14   # shows are announced weeks ahead; artist searches stay at 7 days
MUSIC_WORDS = ["shows", "tour", "tours", "recital", "recitales", "concierto", "conciertos", "festival",
               "cantante", "musico", "musica", "album", "disco", "single", "rock", "pop",
               "trap", "cumbia"]


def search_url(artist: str, edition: str) -> str:
    return f"https://news.google.com/rss/search?q={quote(chr(34) + artist + chr(34))}+when:7d&{edition}"


def show_search_url(query: str) -> str:
    return f"https://news.google.com/rss/search?q={quote(query)}+when:{SHOW_DAYS}d&{SHOW_EDITION}"


def parse_search(content: bytes, artist: str, lang: str, now: datetime) -> list[Article]:
    want = normalize(artist)
    return _parse(content, lang, now, lambda title: want in normalize(title), query=normalize(artist))   # the artist must be in the headline


def parse_shows(content: bytes, now: datetime) -> list[Article]:
    """Results of a shows query: only headlines with a music or show word (a "gira" can be political)."""
    def music(title: str) -> bool:
        words = set(re.split(r"[^a-z0-9]+", normalize(title)))
        return bool(words & set(MUSIC_WORDS))
    return _parse(content, "es", now, music, SHOW_DAYS)


def _parse(content: bytes, lang: str, now: datetime, keep, days: int = 7, query: str = "") -> list[Article]:
    out = []
    for e in feedparser.parse(content).entries[:PER_FEED]:
        outlet = clean_html((e.get("source") or {}).get("title", "")) or "Google News"
        title = clean_html(e.get("title", ""))
        title = re.sub(r"\s+-\s+" + re.escape(outlet) + r"\s*$", "", title)   # "Headline - Outlet"
        link = e.get("link", "")
        if not title or not SAFE_LINK.match(link) or not keep(title):
            continue
        published = _published(e) or now
        if now - published > timedelta(days=days):
            continue
        src = Source(id="gn-" + re.sub(r"[^a-z0-9]+", "-", normalize(outlet)), outlet=outlet, url="",
                     lang=lang, region="global", tier="commercial", topics=["culture"],
                     max_age_hours=days * 24)
        out.append(Article(source=src, title=title, link=link, summary="", published=min(published, now), query=query))
    return out


def fetch_show_news(now: datetime | None = None) -> list[Article]:
    """Shows in Argentina and big tours, from fixed Google News searches (check-feeds shows their status)."""
    now = now or datetime.now(timezone.utc)

    def one(q):
        try:
            return parse_shows(_get(show_search_url(q)).content, now)
        except Exception as exc:   # one failed search must never break the edition
            log.warning("show news for %r failed: %s", q, exc)
            return []

    with cf.ThreadPoolExecutor(5) as pool:
        found = [a for batch in pool.map(one, SHOW_QUERIES) for a in batch]
    seen, out = set(), []
    for a in found:
        if a.link not in seen:
            seen.add(a.link)
            out.append(a)
    log.info("show news: %d articles from %d queries", len(out), len(SHOW_QUERIES))
    return out


def check_shows() -> list[tuple[str, str, bool, str]]:
    """For `check-feeds`: (query, url, ok, text) per show query."""
    now = datetime.now(timezone.utc)
    out = []
    for q in SHOW_QUERIES:
        url = show_search_url(q)
        try:
            n = len(parse_shows(_get(url).content, now))
            out.append((q, url, n > 0, f"{n} items"))
        except Exception as exc:
            out.append((q, url, False, str(exc)[:40]))
    return out


def fetch_artist_news(artists: list[str], now: datetime | None = None) -> list[Article]:
    now = now or datetime.now(timezone.utc)
    jobs = [(a, lang, ed) for a in artists[:MAX_ARTISTS] for lang, ed in EDITIONS]

    def one(job):
        artist, lang, ed = job
        try:
            return parse_search(_get(search_url(artist, ed)).content, artist, lang, now)
        except Exception as exc:   # one failed search must never break the edition
            log.warning("artist news for %s failed: %s", artist, exc)
            return []

    with cf.ThreadPoolExecutor(8) as pool:
        found = [a for batch in pool.map(one, jobs) for a in batch]
    seen, out = set(), []
    for a in found:   # the same article can come from both editions
        if a.link not in seen:
            seen.add(a.link)
            out.append(a)
    log.info("artist news: %d articles for %d artists", len(out), min(len(artists), MAX_ARTISTS))
    return out


def _source(outlet: str, lang: str, days: int) -> Source:
    return Source(id="gn-" + re.sub(r"[^a-z0-9]+", "-", normalize(outlet)), outlet=outlet, url="",
                  lang=lang, region="global", tier="commercial", topics=["culture"], max_age_hours=days * 24)


def _pack(a: Article) -> dict:
    return {"title": a.title, "link": a.link, "outlet": a.outlet, "lang": a.source.lang,
            "published": a.published.isoformat(), "query": a.query}


def _unpack(d: dict, days: int) -> Article:
    return Article(source=_source(d["outlet"], d["lang"], days), title=d["title"], link=d["link"], summary="",
                   published=datetime.fromisoformat(d["published"]), query=d.get("query", ""))


def fetch_google_news(artists: list[str], now: datetime | None = None, cache_path=CACHE_PATH) -> list[Article]:
    """Artist and show news. A list that comes back empty (outage) is replaced by the last good one
    (artists still in your list, articles still within their age limits)."""
    now = now or datetime.now(timezone.utc)
    live = {"artist": fetch_artist_news(artists, now) if artists else [], "show": fetch_show_news(now)}
    try:
        saved = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}
    if not isinstance(saved, dict):
        saved = {}
    days = {"artist": 7, "show": SHOW_DAYS}
    wanted = {normalize(a) for a in artists[:MAX_ARTISTS]}
    out, reused, stamps = {}, {}, []
    for kind, found in live.items():
        entry = saved.get(kind)
        if found or not isinstance(entry, dict):
            out[kind] = found
            continue
        try:
            old = [_unpack(d, days[kind]) for d in entry["items"]]
        except (KeyError, ValueError, TypeError):
            out[kind] = found
            continue
        out[kind] = [a for a in old if now - a.published <= timedelta(days=days[kind])
                     and (kind == "show" or a.query in wanted)]
        if out[kind]:
            reused[kind] = len(out[kind])
            stamps.append(entry.get("saved", "?"))
    if reused:
        log.warning("gnews fallback: %d artist + %d show articles from %s",
                    reused.get("artist", 0), reused.get("show", 0), min(stamps))
    if any(live.values()):
        fresh = {k: ({"saved": now.isoformat(), "items": [_pack(a) for a in v]} if v else saved.get(k))
                 for k, v in live.items()}
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps({k: v for k, v in fresh.items() if v}), encoding="utf-8")
        except OSError as exc:
            log.warning("gnews cache not saved: %s", exc)
    return out["artist"] + out["show"]
