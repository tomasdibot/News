"""Group articles from different outlets that report the same event into Stories."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .fetch import Article
from .text import entities, tokens

SAME_LANG_THRESHOLD = 0.42
CROSS_LANG_THRESHOLD = 0.5
WINDOW = timedelta(hours=48)


@dataclass
class _Features:
    lang: str
    title_tokens: set[str]
    all_tokens: set[str]
    title_ents: set[str]
    all_ents: set[str]


def features(a: Article) -> _Features:
    summary = a.summary[:300]
    title_ents = entities(a.title, summary)
    return _Features(
        lang=a.source.lang,
        title_tokens=tokens(a.title),
        all_tokens=tokens(a.title + " " + summary),
        title_ents=title_ents,
        all_ents=title_ents | entities(summary),
    )


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def similarity(a: _Features, b: _Features) -> float:
    if a.lang == b.lang:
        shared = len(a.title_ents & b.title_ents)
        return (0.7 * jaccard(a.title_tokens, b.title_tokens)
                + 0.3 * jaccard(a.all_tokens, b.all_tokens)
                + 0.12 * min(shared, 3))
    # Across languages the words differ, so rely on names, places and figures:
    # several must be shared, and at least one of them must be in a headline.
    shared = a.all_ents & b.all_ents
    if len(shared) < 2 or not (shared & (a.title_ents | b.title_ents)):
        return 0.0
    return 0.12 * min(len(shared), 4) + 0.5 * jaccard(a.all_ents, b.all_ents)


@dataclass
class Story:
    articles: list[Article] = field(default_factory=list)
    feats: list[_Features] = field(default_factory=list)
    # Filled in by rank.py
    score: float = 0.0
    topic: str | None = None
    topic_scores: dict[str, float] = field(default_factory=dict)
    local: bool = False
    base: float = 0.0
    fixed: float = 0.0
    hype: float = 0.0  # share of the story's headlines with sensational wording
    reasons: list[str] = field(default_factory=list)
    headline: Article | None = None
    image: str | None = None
    neutral: dict | None = None  # {title, summary} written by Claude (neutral.py)

    @property
    def outlets(self) -> list[str]:
        seen: dict[str, None] = {}
        for a in sorted(self.articles, key=lambda a: a.published):
            seen.setdefault(a.outlet, None)
        return list(seen)

    @property
    def langs(self) -> set[str]:
        return {a.source.lang for a in self.articles}

    @property
    def latest(self) -> datetime:
        return max(a.published for a in self.articles)

    @property
    def earliest(self) -> datetime:
        return min(a.published for a in self.articles)

    def sources_for_display(self) -> list[Article]:
        """One link per outlet (the earliest), so the reader can compare coverage."""
        out: dict[str, Article] = {}
        for a in sorted(self.articles, key=lambda a: a.published):
            out.setdefault(a.outlet, a)
        return list(out.values())


def dedupe(articles: list[Article]) -> list[Article]:
    seen: set[str] = set()
    out = []
    for a in articles:
        key = a.link.split("?")[0].rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        out.append(a)
    return out


def cluster(articles: list[Article]) -> list[Story]:
    stories: list[Story] = []
    index: dict[str, set[int]] = defaultdict(set)  # token/entity -> story ids

    for art in sorted(dedupe(articles), key=lambda a: a.published):
        f = features(art)
        keys = {"t:" + t for t in f.title_tokens} | {"e:" + e for e in f.title_ents}
        candidates = set().union(*(index[k] for k in keys)) if keys else set()

        best, best_margin = None, 0.0
        for sid in candidates:
            story = stories[sid]
            if art.published - story.latest > WINDOW:
                continue
            margin = max(
                similarity(f, g) - (SAME_LANG_THRESHOLD if g.lang == f.lang else CROSS_LANG_THRESHOLD)
                for g in story.feats
            )
            if margin >= 0 and (best is None or margin > best_margin):
                best, best_margin = sid, margin

        if best is None:
            best = len(stories)
            stories.append(Story())
        stories[best].articles.append(art)
        stories[best].feats.append(f)
        for k in keys:
            index[k].add(best)
    return stories
