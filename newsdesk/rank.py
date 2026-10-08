"""Scoring of stories: importance (independent coverage) x relevance (profile) x freshness."""

from __future__ import annotations

import math
from datetime import datetime, timedelta

from .cluster import Story
from .fetch import Article
from .lexicon import AGE_HINTS, COUNTRY_KEYWORDS, SENSATIONAL, TOPIC_KEYWORDS
from .text import contains_any, normalize

TIER_WEIGHT = {"wire": 1.0, "public": 1.0, "commercial": 0.85, "institutional": 0.7}
TIER_ORDER = {"wire": 0, "public": 1, "commercial": 2, "institutional": 3}
FRESHNESS_HALF_LIFE_H = 12


def _norm_list(words) -> list[str]:
    return [normalize(w) for w in words]


def topic_keywords(profile: dict) -> dict[str, list[str]]:
    kws = {name: list(words) for name, words in TOPIC_KEYWORDS.items()}
    for t in profile["topics"]:
        if t.get("keywords"):
            kws[t["name"]] = kws.get(t["name"], []) + _norm_list(t["keywords"])
    return kws


def sensational_hits(title: str) -> int:
    hits = len(contains_any(normalize(title), SENSATIONAL))
    if "!" in title:
        hits += 1
    shouty = [w for w in title.split() if len(w) > 3 and w.isupper() and w.isalpha()]
    if len(shouty) >= 2:
        hits += 1
    return hits


def age_hint_words(age) -> list[str]:
    if age is None:
        return []
    for lo, hi, words in AGE_HINTS:
        if lo <= int(age) < hi:
            return words
    return []


def pick_headline(story: Story, ui_lang: str) -> Article:
    """The most sober headline, preferring the reader's language and wire/public outlets."""
    return min(
        story.articles,
        key=lambda a: (
            sensational_hits(a.title),
            a.source.lang != ui_lang,
            TIER_ORDER.get(a.source.tier, 9),
            not a.summary,
            a.published,
        ),
    )


def score_stories(stories: list[Story], cfg: dict, now: datetime) -> list[Story]:
    profile = cfg["profile"]
    ui_lang = cfg["site"]["ui_language"]
    max_age = timedelta(hours=cfg["site"]["max_age_hours"])
    country = profile["country"]
    local_words = COUNTRY_KEYWORDS.get(country, [])
    hints = age_hint_words(profile.get("age")) if profile.get("use_age_hints", True) else []
    kws = topic_keywords(profile)
    weights = {t["name"]: float(t.get("weight", 1.0)) for t in profile["topics"]}
    muted = set(profile.get("muted_topics") or [])

    kept = []
    for s in stories:
        if now - s.latest > max_age:
            continue

        titles = normalize(" ".join(a.title for a in s.articles))
        bodies = normalize(" ".join(a.summary[:400] for a in s.articles))
        feed_hints = {t for a in s.articles for t in a.source.topics}
        tags = normalize(" ".join(t for a in s.articles for t in a.tags))

        # --- What is it about? ------------------------------------------------
        for name, words in kws.items():
            in_title = set(contains_any(titles, words))
            in_body = set(contains_any(bodies, words)) - in_title
            sc = 0.45 * len(in_title) + 0.2 * len(in_body)
            if name in feed_hints:
                sc += 0.5
            if normalize(name) in tags:
                sc += 0.3
            if sc:
                s.topic_scores[name] = min(1.0, sc)
        s.topic = max(s.topic_scores, key=s.topic_scores.get) if s.topic_scores else None
        if s.topic in muted:
            continue

        # --- Is it important? -------------------------------------------------
        # Coverage counts distinct outlets, weighted by trust tier: ten articles
        # from the same newsroom count once.
        best_tier = {}
        for a in s.articles:
            best_tier[a.outlet] = max(best_tier.get(a.outlet, 0), TIER_WEIGHT.get(a.source.tier, 0.8))
        coverage = sum(best_tier.values())
        importance = 1 + 1.6 * math.log2(1 + coverage) + 0.4 * (len(s.langs) - 1)

        # --- Is it relevant to me? ---------------------------------------------
        topic_rel = max((weights[n] * s.topic_scores.get(n, 0) for n in weights), default=0)
        local_hit = bool(local_words and contains_any(titles + " " + bodies, local_words))
        from_local_outlet = any(a.source.region.upper() == country for a in s.articles)
        local = 0.6 if local_hit else (0.2 if from_local_outlet else 0)
        s.local = local_hit
        age_rel = 0.15 if hints and contains_any(titles + " " + bodies, hints) else 0
        relevance = topic_rel + local + age_rel

        # --- Is it fresh, and is it told soberly? -------------------------------
        hours = max(0.0, (now - s.latest).total_seconds() / 3600)
        freshness = 0.3 + 0.7 * 0.5 ** (hours / FRESHNESS_HALF_LIFE_H)
        s.hype = sum(1 for a in s.articles if sensational_hits(a.title)) / len(s.articles)
        sobriety = 1 - 0.35 * s.hype

        s.score = importance * (0.4 + relevance) * freshness * sobriety
        # Parts the app needs to re-rank by the topics chosen on the phone:
        # score = base * (0.4 + fixed + best topic match x its weight)
        s.base = importance * freshness * sobriety
        s.fixed = local + age_rel
        s.headline = pick_headline(s, ui_lang)
        s.image = s.headline.image or next((a.image for a in s.articles if a.image), None)
        s.reasons = [n for n in weights if s.topic_scores.get(n, 0) >= 0.45]
        kept.append(s)

    kept.sort(key=lambda s: s.score, reverse=True)
    return kept


def select_pool(stories: list[Story], cfg: dict, per_topic: int = 15, overall: int = 100) -> list[Story]:
    """Stories shipped to the app: the best overall plus the best of every topic,
    so any topic chosen in the app has something to show."""
    picked: dict[int, Story] = {}
    for s in stories[:overall]:
        picked[id(s)] = s
    names = set(topic_keywords(cfg["profile"]))
    for name in names:
        pool = [s for s in stories if s.topic_scores.get(name, 0) >= 0.45]
        pool.sort(key=lambda s: s.base * (0.5 + s.topic_scores[name]), reverse=True)
        for s in pool[:per_topic]:
            picked[id(s)] = s
    for s in [s for s in stories if s.local][:per_topic]:
        picked[id(s)] = s
    return sorted(picked.values(), key=lambda s: s.score, reverse=True)


def select_sections(stories: list[Story], cfg: dict) -> dict:
    """Split ranked stories into Top / Local / per-topic sections without repeats."""
    site = cfg["site"]
    used: set[int] = set()

    def take(pool, n, max_per_topic=None):
        out, per_topic = [], {}
        for s in pool:
            if id(s) in used or len(out) >= n:
                continue
            if max_per_topic and per_topic.get(s.topic, 0) >= max_per_topic:
                continue
            out.append(s)
            used.add(id(s))
            per_topic[s.topic] = per_topic.get(s.topic, 0) + 1
        return out

    # Top: corroborated stories first (2+ independent outlets); sober single-source ones only to fill gaps.
    corroborated = [s for s in stories if len(s.outlets) >= 2]
    top = take(corroborated, site["top_stories"], max_per_topic=3)
    if len(top) < site["top_stories"]:
        top += take([s for s in stories if not s.hype], site["top_stories"] - len(top))

    local = take([s for s in stories if s.local], site["local_stories"])

    topics = []
    for t in cfg["profile"]["topics"]:
        name = t["name"]
        pool = [s for s in stories if s.topic_scores.get(name, 0) >= 0.45]
        pool.sort(key=lambda s: s.score * (0.5 + s.topic_scores[name]), reverse=True)
        items = take(pool, site["stories_per_topic"])
        if items:
            topics.append((name, items))

    return {"top": top, "local": local, "topics": topics}
