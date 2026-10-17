"""Group articles from different outlets that report the same event into Stories."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .fetch import Article
from .text import entities, figures, name_phrases, significant, tokens

SAME_LANG_THRESHOLD = 0.42
CROSS_LANG_THRESHOLD = 0.5
WINDOW = timedelta(hours=48)
DISPLAY_MIN = 0.3   # an outlet row needs at least this similarity to the story's lead headline


@dataclass
class _Features:
    lang: str
    title_tokens: set[str]
    all_tokens: set[str]
    title_ents: set[str]
    all_ents: set[str]
    figures: frozenset[str]  # significant numbers in the title
    names: tuple = ()        # name phrases: "Tame Impala" is one name, not two
    query: str = ""          # artist search that found it


def features(a: Article) -> _Features:
    summary = a.summary[:300]
    title_ents = entities(a.title, summary or None)
    return _Features(
        lang=a.source.lang,
        title_tokens=tokens(a.title),
        all_tokens=tokens(a.title + " " + summary),
        title_ents=title_ents,
        all_ents=title_ents | entities(summary),
        figures=frozenset(f for f in figures(a.title) if significant(f)),
        names=tuple(name_phrases(a.title, title_ents)),
        query=a.query,
    )


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def overlap(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def figures_match(a: frozenset, b: frozenset, tol: float = 0.01) -> bool:
    """Any figure equal, or within `tol` of one in the other title ($1.555 vs $1.560)."""
    return any(abs(float(x) - float(y)) <= tol * max(float(x), float(y)) for x in a for y in b)


def similarity(a: _Features, b: _Features) -> float:
    if a.lang == b.lang:
        if a.figures and b.figures and not figures_match(a.figures, b.figures):
            return 0.0  # different release (e.g. September vs August inflation)
        # Names found by the same artist search say nothing about the event (all are about that artist).
        same_search = bool(a.query) and a.query == b.query
        shared = 0 if same_search else sum(1 for p in a.names if any(p & q for q in b.names))
        # Overlap and shared names would inflate very short headlines ("Boca ganó" / "Boca perdió").
        short = min(len(a.title_tokens), len(b.title_tokens)) < 4
        return (0.7 * jaccard(a.title_tokens, b.title_tokens)
                + 0.3 * (jaccard if short else overlap)(a.title_tokens, b.title_tokens)
                + (0 if short else 0.12 * min(shared, 3)))
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
    fits: dict[str, bool] = field(default_factory=dict)  # theme key -> fits exactly (judge.py)

    @property
    def outlets(self) -> list[str]:
        """Outlets shown for the story: the same rows as `sources_for_display`."""
        return [a.outlet for a in self.sources_for_display()]

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
        """One link per outlet so the reader can compare coverage: the article closest to the lead
        headline, and only outlets whose article really tells the same story as the lead."""
        lead = self.headline or min(self.articles, key=lambda a: a.published)
        feats = self.feats if len(self.feats) == len(self.articles) else [features(a) for a in self.articles]
        fl = feats[self.articles.index(lead)]
        best: dict[str, tuple[float, int]] = {}
        for i, (a, f) in enumerate(zip(self.articles, feats)):
            sim = 1.0 if a is lead else similarity(fl, f)
            if a.outlet not in best or sim > best[a.outlet][0]:
                best[a.outlet] = (sim, i)
        rows = [(self.articles[i], sim) for sim, i in best.values() if sim >= DISPLAY_MIN]
        return [a for a, _ in sorted(rows, key=lambda r: r[0].published)]


def _margin(f: _Features, g: _Features) -> float:
    return similarity(f, g) - (SAME_LANG_THRESHOLD if g.lang == f.lang else CROSS_LANG_THRESHOLD)


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
            margin = _margin(f, story.feats[0])   # against the lead only: A~B~C must not chain events
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
