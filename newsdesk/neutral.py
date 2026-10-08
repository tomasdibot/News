"""Neutral headlines: Claude reads what every outlet reported and writes one plain, factual title.

Only runs when ANTHROPIC_API_KEY is set. Results are cached between runs
(build/neutral-cache.json, kept by the workflow), so each story is written once.
"""

from __future__ import annotations

import concurrent.futures as cf
import hashlib
import json
import logging
import os
import time
from html.parser import HTMLParser
from pathlib import Path

import requests

from .cluster import Story
from .config import ROOT
from .fetch import USER_AGENT
from .text import clean_html, truncate

log = logging.getLogger(__name__)

CACHE_PATH = ROOT / "build" / "neutral-cache.json"
BATCH = 15
LANG_NAMES = {"es": "Spanish (rioplatense neutral register, no voseo)", "en": "English"}

SYSTEM = """You write headlines for a strictly neutral news digest read by one person who wants facts, not spin.

For each story you get the headline and excerpt from every outlet that covered it, and sometimes part of the article text. Write in {language}:

- title: one plain, factual headline (max 14 words). Say who did what, with the key number or place. No judgement adjectives, no hype, no clickbait, no questions, no exclamation marks, no quotes used as the headline, no loaded or partisan wording. Prefer the most neutral common term for contested things.
- summary: one sentence (max 30 words) with the most important facts a reader needs.

Use only what is in the material; never add facts, numbers or context from elsewhere. If something is an allegation, a claim by one side, or reported by only one outlet, attribute it ("según ...", "according to ..."). If outlets disagree on a fact, say so briefly in the summary.

Return one entry per story id you were given."""

SCHEMA = {
    "type": "object",
    "properties": {
        "stories": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "string"}, "title": {"type": "string"}, "summary": {"type": "string"}},
                "required": ["id", "title", "summary"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["stories"],
    "additionalProperties": False,
}


def story_key(s: Story) -> str:
    first = min(s.articles, key=lambda a: a.published)
    return hashlib.sha1(first.link.encode()).hexdigest()[:16]


class _Paragraphs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "p":
            self.depth += 1

    def handle_endtag(self, tag):
        if tag == "p" and self.depth:
            self.depth -= 1

    def handle_data(self, data):
        if self.depth:
            self.parts.append(data)


def article_excerpt(url: str, limit: int = 1500) -> str:
    """The first paragraphs of the article itself (best effort: paywalls just give less)."""
    try:
        resp = requests.get(url, timeout=8, headers={"User-Agent": USER_AGENT}, stream=True)
        html = resp.raw.read(600_000, decode_content=True).decode(resp.encoding or "utf-8", "ignore")
        resp.close()
        p = _Paragraphs()
        p.feed(html)
        text = clean_html(" ".join(t for t in p.parts if len(t.strip()) > 40))
        return truncate(text, limit)
    except Exception as exc:
        log.debug("article text for %s failed: %s", url, exc)
        return ""


def _material(s: Story, excerpt: str) -> dict:
    seen, outlets = set(), []
    for a in sorted(s.articles, key=lambda a: a.published):
        if a.outlet in seen:
            continue
        seen.add(a.outlet)
        outlets.append({"outlet": a.outlet, "headline": a.title, "excerpt": truncate(a.summary, 400)})
        if len(outlets) == 5:
            break
    item = {"outlets": outlets}
    if excerpt:
        item["article_text"] = excerpt
    return item


def _ask_claude(client, model: str, language: str, batch: list[tuple[str, dict]]) -> dict[str, dict]:
    payload = [dict(id=k, **m) for k, m in batch]
    response = client.beta.messages.create(
        model=model,
        max_tokens=16000,
        system=SYSTEM.format(language=language),
        messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if response.stop_reason != "end_turn":
        log.warning("neutral titles: batch stopped (%s), keeping original headlines", response.stop_reason)
        return {}
    text = next(b.text for b in response.content if b.type == "text")
    wanted = {k for k, _ in batch}
    return {e["id"]: e for e in json.loads(text)["stories"] if e["id"] in wanted and e["title"].strip()}


def load_cache(path: Path = CACHE_PATH) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def neutralize(stories: list[Story], cfg: dict, cache_path: Path = CACHE_PATH, client=None) -> int:
    """Give stories a `neutral` dict ({title, summary}). Returns how many were newly written."""
    opts = cfg.get("neutral_titles") or {}
    cache = load_cache(cache_path)
    todo = []
    for s in stories[: int(opts.get("max_stories", 120))]:
        key, n = story_key(s), len(s.outlets)
        hit = cache.get(key)
        # Re-write when two or more new outlets joined: there is more to go on.
        if hit and n < hit.get("n", 0) + 2:
            hit["t"] = int(time.time())  # still in the news: keep it
            s.neutral = hit
        else:
            todo.append((key, s))

    written = 0
    if todo and (client or os.environ.get("ANTHROPIC_API_KEY")):
        todo = todo[: int(opts.get("max_new_per_run", 40))]
        import anthropic

        client = client or anthropic.Anthropic()
        model = opts.get("model", "claude-opus-5-5")
        language = LANG_NAMES.get(cfg["site"]["ui_language"], "English")
        with cf.ThreadPoolExecutor(10) as pool:
            excerpts = list(pool.map(lambda ks: article_excerpt(ks[1].headline.link), todo))
        material = [(k, _material(s, ex)) for (k, s), ex in zip(todo, excerpts)]
        batches = [material[i:i + BATCH] for i in range(0, len(material), BATCH)]

        def run(batch):
            try:
                return _ask_claude(client, model, language, batch)
            except Exception as exc:  # never let this break the edition
                log.warning("neutral titles: %s: %s; keeping original headlines", type(exc).__name__, exc)
                return {}

        with cf.ThreadPoolExecutor(4) as pool:
            results = {}
            for r in pool.map(run, batches):
                results.update(r)
        now = int(time.time())
        for key, s in todo:
            if key in results:
                entry = {"title": results[key]["title"].strip(), "summary": results[key]["summary"].strip(),
                         "n": len(s.outlets), "t": now}
                cache[key] = s.neutral = entry
                written += 1
        log.info("neutral titles: %d written now", written)

    # Forget stories older than three days.
    cutoff = time.time() - 3 * 86400
    cache = {k: v for k, v in cache.items() if v.get("t", 0) >= cutoff}
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    return written
