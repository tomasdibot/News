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
ARTIST_DAYS = 7


def search_url(artist: str, edition: str, days: int = ARTIST_DAYS) -> str:
    return f"https://news.google.com/rss/search?q={quote(chr(34) + artist + chr(34))}+when:{days}d&{edition}"


def parse_search(content: bytes, artist: str, lang: str, now: datetime) -> list[Article]:
    want = normalize(artist)
    return _parse(content, lang, now, lambda title: want in normalize(title), query=normalize(artist))   # the artist must be in the headline


def _parse(content: bytes, lang: str, now: datetime, keep, days: int = ARTIST_DAYS, query: str = "") -> list[Article]:
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


def _source(outlet: str, lang: str, days: int = ARTIST_DAYS) -> Source:
    return Source(id="gn-" + re.sub(r"[^a-z0-9]+", "-", normalize(outlet)), outlet=outlet, url="",
                  lang=lang, region="global", tier="commercial", topics=["culture"], max_age_hours=days * 24)


def _pack(a: Article) -> dict:
    return {"title": a.title, "link": a.link, "outlet": a.outlet, "lang": a.source.lang,
            "published": a.published.isoformat(), "query": a.query}


def _unpack(d: dict, days: int = ARTIST_DAYS) -> Article:
    return Article(source=_source(d["outlet"], d["lang"], days), title=d["title"], link=d["link"], summary="",
                   published=datetime.fromisoformat(d["published"]), query=d.get("query", ""))


def fetch_google_news(artists: list[str], now: datetime | None = None, cache_path=CACHE_PATH) -> list[Article]:
    """Artist news. A list that comes back empty (outage) is replaced by the last good one
    (artists still in your list, articles still within their age limit)."""
    now = now or datetime.now(timezone.utc)
    found = fetch_artist_news(artists, now) if artists else []
    try:
        saved = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}
    entry = saved.get("artist") if isinstance(saved, dict) else None
    if not found and isinstance(entry, dict):
        wanted = {normalize(a) for a in artists[:MAX_ARTISTS]}
        try:
            old = [_unpack(d) for d in entry["items"]]
        except (KeyError, ValueError, TypeError):
            old = []
        found = [a for a in old if now - a.published <= timedelta(days=ARTIST_DAYS) and a.query in wanted]
        if found:
            log.warning("gnews fallback: %d artist articles from %s", len(found), entry.get("saved", "?"))
    elif found:
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps({"artist": {"saved": now.isoformat(), "items": [_pack(a) for a in found]}}),
                                  encoding="utf-8")
        except OSError as exc:
            log.warning("gnews cache not saved: %s", exc)
    return found
