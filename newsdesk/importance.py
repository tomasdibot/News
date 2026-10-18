"""Importance check (audit only): does each theme hold the day's most important news?

Reference stories come from outside (Google News topic feeds for Argentina, Techmeme for AI); if a
reference feed fails, "front-page leads" (the first items of each outlet's feed that several outlets
lead with) stand in. Each reference story is matched to the edition's stories by headline
similarity (same language first; if none, across languages with the cluster's cross-language rule),
and every miss gets a reason. Any failure only lowers the counts; nothing here may break the audit.
"""

from __future__ import annotations

import itertools
import logging
import re
from datetime import datetime, timezone

import feedparser

from .cluster import CROSS_LANG_THRESHOLD, Story, cluster, features, similarity
from .config import Source
from .fetch import SAFE_LINK, Article, _get
from .judge import MUSIC_CANDIDATE_WORDS, _kw_re, theme_key
from .lexicon import CONCEPTS, TOPIC_ALIASES, TOPIC_KEYWORDS
from .music import min_outlets
from .text import clean_html, normalize

log = logging.getLogger(__name__)

PER_THEME_REFS = 10
MATCH = 0.5   # same language: stricter than joining a story (0.42), so two market reports do not match
GNEWS = "https://news.google.com/rss/headlines/section/topic/{}?hl=es-419&gl=AR&ceid=AR:es-419"
TECHMEME = "https://www.techmeme.com/feed.xml"
# theme kind -> [(label, url, lang)]
REFERENCES = {
    "economy": [("google", GNEWS.format("BUSINESS"), "es")],
    "world": [("google", GNEWS.format("WORLD"), "es")],
    "ai": [("google", GNEWS.format("TECHNOLOGY"), "es"), ("techmeme", TECHMEME, "en")],
    "music": [("google", GNEWS.format("ENTERTAINMENT"), "es")],
}


def theme_kind(theme: str) -> str | None:
    """economy / world / ai / music, from the same names the app uses for themes."""
    t = f" {theme_key(theme)} "
    names = {k: [f" {w.replace('-', ' ')} " for w in TOPIC_ALIASES[k].split()] for k in ("economy", "world")}
    if any(w in t for w in (" musica ", " music ")):
        return "music"
    if any(w in t for w in (" ia ", " ai ", " inteligencia artificial ", " artificial intelligence ")):
        return "ai"
    for kind in ("economy", "world"):
        if any(w in t for w in names[kind]):
            return kind
    return None


def kind_words(kind: str) -> list[str] | None:
    if kind == "ai":
        return next(c["keywords"] for c in CONCEPTS if c["id"] == "ai")
    if kind == "music":
        return next(c["keywords"] for c in CONCEPTS if c["id"] == "music") + MUSIC_CANDIDATE_WORDS
    return TOPIC_KEYWORDS.get(kind)


def fits_kind(title: str, kind: str) -> bool:
    words = kind_words(kind)
    t = normalize(title)
    return bool(words) and any(_kw_re(normalize(w)).search(t) for w in words)


def parse_reference(content: bytes, lang: str, now: datetime | None = None) -> list[Article]:
    """Reference stories from a feed ("Headline - Outlet" in Google News)."""
    now = now or datetime.now(timezone.utc)
    out = []
    for e in feedparser.parse(content).entries:
        publisher = clean_html((e.get("source") or {}).get("title", ""))
        title = clean_html(e.get("title", ""))
        if publisher:
            title = re.sub(r"\s+-\s+" + re.escape(publisher) + r"\s*$", "", title)
        link = e.get("link", "")
        if not title or not SAFE_LINK.match(link):
            continue
        src = Source(id="ref", outlet=publisher or "reference", url="", lang=lang)
        out.append(Article(src, title, link, clean_html(e.get("summary", "")), now))
    return out


def fetch_references(kind: str, get=None, now: datetime | None = None) -> tuple[list[Article], str]:
    """Up to PER_THEME_REFS reference stories and the label of the feeds that answered."""
    get = get or _get
    batches, labels = [], []
    for label, url, lang in REFERENCES.get(kind, []):
        try:
            arts = parse_reference(get(url).content, lang, now)
        except Exception as exc:   # a broken reference only lowers the counts
            log.warning("importance reference %s failed: %s", label, exc)
            continue
        if label == "google" and kind in ("ai", "music"):
            arts = [a for a in arts if fits_kind(a.title, kind)]
        if arts:
            batches.append(arts)
            labels.append(label)
    mixed = [a for a in itertools.chain.from_iterable(itertools.zip_longest(*batches)) if a]
    return mixed[:PER_THEME_REFS], "+".join(labels)


def front_page_leads(articles: list[Article], kind: str, per_outlet: int = 5) -> list[Article]:
    """Fallback reference: the first items of each outlet's feed, led by several outlets at once
    (3, or 2 for music and AI) and fitting the theme by keyword."""
    seen: dict[str, list[Article]] = {}
    for a in articles:
        if len(seen.setdefault(a.source.id, [])) < per_outlet:
            seen[a.source.id].append(a)
    need = 2 if kind in ("ai", "music") else 3
    stories = [s for s in cluster([a for v in seen.values() for a in v])
               if len({a.outlet for a in s.articles}) >= need and fits_kind(s.articles[0].title, kind)]
    stories.sort(key=lambda s: -len({a.outlet for a in s.articles}))
    return [s.articles[0] for s in stories[:PER_THEME_REFS]]


def rank_accepted(accepted: list[Story], need: int) -> list[Story]:
    """Approximates the tab: confirmed stories (enough outlets or official) first, then by score."""
    def confirmed(s):
        return len(s.outlets) >= need or any(a.source.tier == "official" for a in s.articles)
    return sorted(accepted, key=lambda s: (not confirmed(s), -s.score))


def _hits(rf, stories: list[Story]) -> list[Story]:
    same = [s for s in stories if any(f.lang == rf.lang and similarity(rf, f) >= MATCH for f in s.feats)]
    if same:
        return same
    return [s for s in stories if any(f.lang != rf.lang and similarity(rf, f) >= CROSS_LANG_THRESHOLD for f in s.feats)]


def evaluate(refs: list[Article], stories: list[Story], cands: list[Story], capped: list[Story],
             accepted: list[Story], need: int, judged: list[Story] | None = None):
    """-> (top4, top10, misses[(reason, title)]). `cands` = all candidates, `capped` = after the cap,
    `judged` = those the model read (default: all capped)."""
    judged = capped if judged is None else judged
    ranked = {id(s): i + 1 for i, s in enumerate(rank_accepted(accepted, need))}
    ids = {name: {id(s) for s in lst} for name, lst in (("cands", cands), ("capped", capped), ("judged", judged))}
    top4 = top10 = 0
    misses = []
    for ref in refs:
        hits = _hits(features(ref), stories)
        pos = min((ranked[id(s)] for s in hits if id(s) in ranked), default=None)
        top4 += pos is not None and pos <= 4
        top10 += pos is not None and pos <= 10
        if pos is not None and pos <= 10:
            continue
        if not hits:
            reason = "not fetched"
        elif pos is not None:
            reason = "low rank"
        elif any(id(s) in ids["judged"] for s in hits):
            reason = "judge out"
        elif len(hits) >= 2:
            reason = "split"
        elif any(id(s) in ids["capped"] for s in hits):
            reason = "not judged (sample)"
        elif any(id(s) in ids["cands"] for s in hits):
            reason = "cut by cap"
        else:
            reason = "not a candidate"
        misses.append((reason, ref.title))
    return top4, top10, misses


def importance_lines(theme: str, stories: list[Story], cands: list[Story], capped: list[Story], judged: list[Story],
                     accepted: list[Story], articles: list[Article], references: dict | None = None,
                     get=None) -> list[str]:
    """The audit lines for one theme. `references` caches fetched references per kind."""
    try:
        kind = theme_kind(theme)
        if kind is None:
            return []
        if references is None:
            references = {}
        if kind not in references:
            references[kind] = fetch_references(kind, get)
        refs, label = references[kind]
        if not refs:
            refs, label = front_page_leads(articles, kind), "leads"
        top4, top10, misses = evaluate(refs, stories, cands, capped, accepted, min_outlets(theme), judged)
        n = len(refs)
        lines = [f"importance {theme}: top4 {top4}/{n} top10 {top10}/{n} (ref: {label}, rank approx.)"]
        lines += [f"  miss: {reason} — {title}" for reason, title in misses[:5]]
        return lines
    except Exception as exc:   # never fail the audit
        log.warning("importance %s failed: %s", theme, exc)
        return [f"importance {theme}: unavailable"]


def check_references(get=None) -> list[tuple[str, str, bool, str]]:
    """For `check-feeds`: (kind, url, ok, text) per reference feed."""
    get = get or _get
    out = []
    for kind, feeds in REFERENCES.items():
        for label, url, lang in feeds:
            try:
                n = len(parse_reference(get(url).content, lang))
                out.append((f"{kind}/{label}", url, n > 0, f"{n} items"))
            except Exception as exc:
                out.append((f"{kind}/{label}", url, False, str(exc)[:28]))
    return out
