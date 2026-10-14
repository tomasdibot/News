"""News about the artists you like (typed in the app or read from your Spotify).

For each artist, Google News is searched (Spanish and English); every result keeps the name of
the outlet that published it, so a release or tour covered by several outlets becomes one story
with several sources, like any other story. These stories then go through the normal ranking
and the AI theme filter (a "Música" theme gets them).
"""

from __future__ import annotations

import concurrent.futures as cf
import logging
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import feedparser

from .config import Source
from .fetch import Article, _get, _published
from .text import clean_html, normalize

log = logging.getLogger(__name__)

EDITIONS = [("es", "hl=es-419&gl=AR&ceid=AR:es-419"), ("en", "hl=en-US&gl=US&ceid=US:en")]
MAX_ARTISTS = 20
PER_FEED = 8


def search_url(artist: str, edition: str) -> str:
    return f"https://news.google.com/rss/search?q={quote(chr(34) + artist + chr(34))}+when:7d&{edition}"


def parse_search(content: bytes, artist: str, lang: str, now: datetime) -> list[Article]:
    out = []
    want = normalize(artist)
    for e in feedparser.parse(content).entries[:PER_FEED]:
        outlet = clean_html((e.get("source") or {}).get("title", "")) or "Google News"
        title = clean_html(e.get("title", ""))
        title = re.sub(r"\s+-\s+" + re.escape(outlet) + r"\s*$", "", title)   # "Headline - Outlet"
        link = e.get("link", "")
        if not title or not link or want not in normalize(title):   # the artist must be in the headline
            continue
        published = _published(e) or now
        if now - published > timedelta(days=7):
            continue
        src = Source(id="gn-" + re.sub(r"[^a-z0-9]+", "-", normalize(outlet)), outlet=outlet, url="",
                     lang=lang, region="global", tier="commercial", topics=["culture"])
        out.append(Article(source=src, title=title, link=link, summary="", published=min(published, now)))
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
