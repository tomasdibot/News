"""Precise themes: an AI model reads each candidate story and decides if it fits a theme exactly.

Themes come from the NEWSDESK_THEMES secret (one per line; the app's ⚙ has a button that
copies them) and from `themes:` in config.yaml. The app keeps working without this (it then
matches themes by keywords); with it, a theme like "AI advances from official sources" only
shows stories that are really about that, not every story that mentions AI.

Uses the same model as the neutral titles (free local model, or Claude with ANTHROPIC_API_KEY).
Verdicts are cached (build/theme-cache.json), so each story is judged once per theme.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from pathlib import Path

import requests

from .cluster import Story
from .config import ROOT
from .lexicon import CONCEPTS, TOPIC_ALIASES, TOPIC_KEYWORDS
from .neutral import OLLAMA_URL, _parse_json, _provider, story_key
from .text import normalize, truncate

log = logging.getLogger(__name__)

CACHE_PATH = ROOT / "build" / "theme-cache.json"
BATCH = 10
PER_THEME = 40   # a tab shows at most 15 stories: only the best candidates need reading

SYSTEM = """You filter news for one reader. The reader described a theme in their own words. For each story, decide if it fits the theme EXACTLY.

Rules:
- Respect every detail and qualifier of the theme. Example: for "AI advances from official sources, models and development", a new model or research result announced by an AI company fits; a person or a small business using an AI tool (e.g. a diet app with an AI agent), opinion pieces, lawsuits, scandals or stock moves do NOT fit.
- The theme must be the main subject of the story, not a side mention.
- Ignore notes like "written with AI help" in the text.
- When in doubt, answer false.

Return one entry per story id: {"id": ..., "fits": true/false}."""

SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "string"}, "fits": {"type": "boolean"}},
                "required": ["id", "fits"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["results"],
    "additionalProperties": False,
}

STOP = set(("de del la el los las lo y e o en a al con para por un una unos unas sobre que se su sus mas "
            "the of and or in on at to for with a an about from news noticias tema temas todo").split())


def words(text: str) -> list[str]:
    return [w for w in re.split(r"[^a-z0-9]+", normalize(text or "")) if len(w) > 1 and w not in STOP]


def theme_key(label: str) -> str:
    """The same key the app computes for a theme (lowercase, no accents, words only)."""
    return " ".join(w for w in re.split(r"[^a-z0-9]+", normalize(label or "")) if w)


def configured_themes(cfg: dict) -> list[str]:
    raw = os.environ.get("NEWSDESK_THEMES", "")
    themes = [t.strip(" -•\t") for t in raw.replace(";", "\n").splitlines()]
    themes += [str(t) for t in cfg.get("themes") or []]
    out, seen = [], set()
    for t in themes:
        k = theme_key(t)
        if k and k not in seen:
            seen.add(k)
            out.append(t.strip())
    return out


def _concept_parts():
    parts = []
    for topic, kws in TOPIC_KEYWORDS.items():
        names = TOPIC_ALIASES.get(topic, "").replace("-", " ").split() + [topic]
        parts.append((names, kws, topic))
    for c in CONCEPTS:
        parts.append((c["names"] + list(c["label"].values()), c["keywords"], c["topic"]))
    return parts


def candidates(theme: str, stories: list[Story]) -> list[Story]:
    """Cheap first pass so the model only reads stories that could fit."""
    t = " " + " ".join(words(theme)) + " "
    kws, topics = set(), set()
    named = sorted(((" ".join(words(n)), kw, tp) for names, kw, tp in _concept_parts() for n in names),
                   key=lambda x: -len(x[0]))
    for name, kw, tp in named:
        if name and f" {name} " in t:
            kws.update(normalize(k) for k in kw)
            if tp and kw is TOPIC_KEYWORDS.get(tp):
                topics.add(tp)
            t = t.replace(f" {name} ", " ")
    stems = {w[:5] for w in t.split() if len(w) >= 3}
    out = []
    for s in stories:
        text = normalize(" ".join([s.headline.title, s.headline.summary or ""]
                                  + [a.title for a in s.articles[:5]]
                                  + ([s.neutral["title"]] if s.neutral else [])))
        if kws or topics:
            hit = any(s.topic_scores.get(tp, 0) >= 0.3 for tp in topics) or any(
                re.search(r"(^|[^a-z0-9])" + re.escape(k) + r"($|[^a-z0-9])", text) for k in kws)
        else:
            hit = bool(stems & {w[:5] for w in words(text)})
        if hit:
            out.append(s)
    return out


def _material(s: Story) -> dict:
    heads, seen = [], set()
    for a in sorted(s.articles, key=lambda a: a.published):
        if a.outlet not in seen:
            seen.add(a.outlet)
            heads.append(a.title)
        if len(heads) == 3:
            break
    return {"headlines": heads, "excerpt": truncate(s.headline.summary or "", 180)}


def _ask(provider: str, client, model: str, theme: str, batch: list[tuple[str, dict]]) -> dict[str, bool]:
    # Short ids ("1", "2", …) keep the small model's answer short and fast.
    ids = {str(i + 1): k for i, (k, _) in enumerate(batch)}
    user = json.dumps({"theme": theme, "stories": [dict(id=str(i + 1), **m) for i, (_, m) in enumerate(batch)]},
                      ensure_ascii=False)
    if provider == "anthropic":
        response = client.beta.messages.create(
            model=model, max_tokens=4000, system=SYSTEM,
            messages=[{"role": "user", "content": user}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        )
        text = next(b.text for b in response.content if b.type == "text")
    else:
        resp = requests.post(f"{OLLAMA_URL}/api/chat", timeout=150, json={
            "model": model, "stream": False, "format": SCHEMA,
            # num_predict caps the answer (~12 tokens per story), so a confused model can't run on for minutes.
            "options": {"temperature": 0, "num_ctx": 4096, "num_predict": 30 + 14 * len(batch)},
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
        })
        resp.raise_for_status()
        text = resp.json()["message"]["content"]
    return {ids[str(e["id"])]: bool(e["fits"]) for e in _parse_json(text).get("results", [])
            if isinstance(e, dict) and str(e.get("id")) in ids and "fits" in e}


def judge_themes(stories: list[Story], cfg: dict, cache_path: Path = CACHE_PATH, client=None) -> list[str]:
    """Set `s.fits[theme_key] = True/False` on judged stories. Returns the keys of the themes used."""
    themes = configured_themes(cfg)
    opts = cfg.get("theme_filter") or {}
    provider = _provider(cfg.get("neutral_titles") or {}, client)
    if not themes or not opts.get("enabled", True):
        return []
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    if provider == "anthropic":
        import anthropic

        client = client or anthropic.Anthropic()
        model = (cfg.get("neutral_titles") or {}).get("model", "claude-opus-5-5")
    else:
        model = os.environ.get("NEWSDESK_LOCAL_MODEL", "")
    deadline = time.time() + float(opts.get("time_budget_seconds", 300))
    now, judged, keys, queues = int(time.time()), 0, [], []
    for theme in themes:
        tk = theme_key(theme)
        th = hashlib.sha1(tk.encode()).hexdigest()[:8]
        keys.append(tk)
        todo = []
        for s in candidates(theme, stories)[:PER_THEME]:
            ck = f"{th}:{story_key(s)}"
            if ck in cache:
                cache[ck]["t"] = now
                s.fits[tk] = cache[ck]["f"]
            else:
                todo.append((ck, s))
                s.fits[tk] = None   # not read yet: the app falls back to keywords
        queues.append((theme, tk, todo))
    # Take turns between themes, so every theme makes progress within the time budget.
    while provider and any(q[2] for q in queues) and time.time() < deadline:
        for theme, tk, todo in queues:
            if not todo or time.time() > deadline:
                continue
            part, todo[:] = todo[:BATCH], todo[BATCH:]
            try:
                got = _ask(provider, client, model, theme, [(ck, _material(s)) for ck, s in part])
            except Exception as exc:  # never let this break the edition
                log.warning("themes: %s: %s", type(exc).__name__, exc)
                continue
            for ck, s in part:
                if ck in got:
                    cache[ck] = {"f": got[ck], "t": now}
                    s.fits[tk] = got[ck]
                    judged += 1
    if not provider:
        return []
    log.info("themes (%s): %d themes, %d stories judged now%s", provider, len(themes), judged,
                 "; time budget used, the rest waits for the next run" if time.time() > deadline else "")
    cutoff = now - 3 * 86400
    cache = {k: v for k, v in cache.items() if v.get("t", 0) >= cutoff}
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache), encoding="utf-8")
    return keys
