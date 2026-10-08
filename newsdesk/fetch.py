"""Download RSS/Atom feeds and turn entries into Article objects (with images)."""

from __future__ import annotations

import calendar
import concurrent.futures as cf
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser

import feedparser
import requests

from .config import Source
from .filters import exclusion_reason
from .lexicon import OPINION_TITLE_PREFIXES, OPINION_URL_PARTS
from .text import clean_html, normalize

log = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (compatible; Newsdesk/1.0; personal news reader)"
TIMEOUT = 20
IMG_SRC_RE = re.compile(r"<img[^>]+src=[\"']([^\"']+)[\"']", re.I)


@dataclass
class Article:
    source: Source
    title: str
    link: str
    summary: str
    published: datetime
    image: str | None = None
    tags: list[str] = field(default_factory=list)

    @property
    def outlet(self) -> str:
        return self.source.outlet


def _get(url: str) -> requests.Response:
    resp = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    return resp


def upgrade_image(url: str) -> str:
    # Some outlets serve tiny thumbnails in their feeds but larger sizes at a predictable URL.
    url = re.sub(r"(ichef\.bbci\.co\.uk/(?:news|ace/ws|ace/standard)/)(\d+)/", r"\g<1>800/", url)
    return url


def extract_image(entry) -> str | None:
    candidates: list[tuple[int, str]] = []
    for media in entry.get("media_content", []) or []:
        url = media.get("url")
        if url and (media.get("medium") in (None, "image") or "image" in media.get("type", "")):
            candidates.append((int(media.get("width") or 0) or 1, url))
    for thumb in entry.get("media_thumbnail", []) or []:
        if thumb.get("url"):
            candidates.append((int(thumb.get("width") or 0) or 0, thumb["url"]))
    for link in entry.get("links", []) or []:
        if link.get("type", "").startswith("image") and link.get("href"):
            candidates.append((1, link["href"]))
    for enc in entry.get("enclosures", []) or []:
        if enc.get("type", "").startswith("image") and enc.get("href"):
            candidates.append((1, enc["href"]))
    if not candidates:
        html_parts = [entry.get("summary", "")] + [c.get("value", "") for c in entry.get("content", []) or []]
        for part in html_parts:
            m = IMG_SRC_RE.search(part or "")
            if m:
                candidates.append((0, m.group(1)))
                break
    if not candidates:
        return None
    candidates.sort(key=lambda c: c[0], reverse=True)
    url = candidates[0][1].replace("&amp;", "&")
    if url.startswith("//"):
        url = "https:" + url
    return upgrade_image(url) if url.startswith("http") else None


def is_opinion(title: str, link: str) -> bool:
    t = normalize(title).strip()
    if any(t.startswith(p) for p in OPINION_TITLE_PREFIXES):
        return True
    low = link.lower()
    return any(part in low for part in OPINION_URL_PARTS)


def _published(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        value = entry.get(key)
        if value:
            return datetime.fromtimestamp(calendar.timegm(value), tz=timezone.utc)
    return None


def parse_feed(source: Source, content: bytes, now: datetime | None = None, country: str = "") -> list[Article]:
    now = now or datetime.now(timezone.utc)
    parsed = feedparser.parse(content)
    articles = []
    for entry in parsed.entries:
        title = clean_html(entry.get("title", ""))
        link = entry.get("link", "")
        tags = [t.get("term", "") for t in entry.get("tags", []) or [] if t.get("term")]
        if not title or not link or is_opinion(title, link):
            continue
        reason = exclusion_reason(title, link, tags, source.region, country)
        if reason:
            log.debug("skipped (%s): %s", reason, title)
            continue
        published = _published(entry) or now
        if published > now:  # some feeds publish future timestamps / wrong timezones
            published = now
        articles.append(Article(
            source=source,
            title=title,
            link=link,
            summary=clean_html(entry.get("summary", "")),
            published=published,
            image=extract_image(entry),
            tags=tags,
        ))
    return articles


def fetch_source(source: Source, country: str = "") -> list[Article]:
    try:
        return parse_feed(source, _get(source.url).content, country=country)
    except Exception as exc:  # one broken feed must never break the edition
        log.warning("feed %s failed: %s", source.id, exc)
        return []


def fetch_all(sources: list[Source], workers: int = 12, country: str = "") -> list[Article]:
    with cf.ThreadPoolExecutor(workers) as pool:
        results = pool.map(lambda s: fetch_source(s, country), sources)
    articles = [a for batch in results for a in batch]
    log.info("fetched %d articles from %d sources", len(articles), len(sources))
    return articles


class _OgImageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.image: str | None = None

    def handle_starttag(self, tag, attrs):
        if tag != "meta" or self.image:
            return
        a = dict(attrs)
        if (a.get("property") or a.get("name") or "").lower() in ("og:image", "twitter:image") and a.get("content"):
            self.image = a["content"]


def fetch_og_image(url: str) -> str | None:
    """Fallback: the article page's share image (og:image)."""
    try:
        resp = requests.get(url, timeout=8, headers={"User-Agent": USER_AGENT}, stream=True)
        head = resp.raw.read(300_000, decode_content=True).decode(resp.encoding or "utf-8", "ignore")
        resp.close()
        parser = _OgImageParser()
        parser.feed(head)
        if parser.image and parser.image.startswith("http"):
            return upgrade_image(parser.image)
    except Exception as exc:
        log.debug("og:image for %s failed: %s", url, exc)
    return None
