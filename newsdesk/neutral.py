"""Neutral headlines: an AI model reads what every outlet reported and writes one plain, factual title.

Providers (config: neutral_titles.provider, default "auto"):
  local     - a small open model run by Ollama on the same machine (free, private). The workflow
              starts it and sets NEWSDESK_LOCAL_MODEL.
  anthropic - Claude, paid, needs ANTHROPIC_API_KEY.
  github    - GitHub Models (free with GITHUB_TOKEN; currently not answering, kept as an option).
  auto      - anthropic if ANTHROPIC_API_KEY is set, otherwise local if NEWSDESK_LOCAL_MODEL is set.
Results are cached between runs (build/neutral-cache.json, kept by the workflow), so each
story is written once. Anything that fails falls back to the cleaned-up original headline.
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


def _material(s: Story, excerpt: str, max_outlets: int = 5) -> dict:
    seen, outlets = set(), []
    for a in sorted(s.articles, key=lambda a: a.published):
        if a.outlet in seen:
            continue
        seen.add(a.outlet)
        outlets.append({"outlet": a.outlet, "headline": a.title, "excerpt": truncate(a.summary, 400)})
        if len(outlets) == max_outlets:
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


GITHUB_MODELS_URL = "https://models.github.ai/inference/chat/completions"


class OutOfQuota(RuntimeError):
    pass


_WORKING: list = []


def _github_candidates(model: str):
    """GitHub Models has had several addresses / API versions; try them in order."""
    if _WORKING:
        yield _WORKING[0]
    short = model.split("/", 1)[-1]
    yield GITHUB_MODELS_URL, "2026-03-10", model
    yield GITHUB_MODELS_URL, "2022-11-28", model
    yield GITHUB_MODELS_URL, None, model
    yield "https://models.inference.ai.azure.com/chat/completions", None, short


def _ask_github(token: str, model: str, language: str, batch: list[tuple[str, dict]]) -> dict[str, dict]:
    payload = [dict(id=k, **m) for k, m in batch]
    body = {
            "model": model,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM.format(language=language)
                 + '\n\nAnswer only with JSON: {"stories": [{"id": "...", "title": "...", "summary": "..."}]}'},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
    }
    last = None
    for url, version, model_id in _github_candidates(model):
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                   "Accept": "application/vnd.github+json"}
        if version:
            headers["X-GitHub-Api-Version"] = version
        resp = requests.post(url, headers=headers, json=dict(body, model=model_id), timeout=120)
        if resp.status_code == 429:
            raise OutOfQuota(f"GitHub Models said {resp.status_code}: {resp.text[:200]}")
        if resp.ok and "json" in resp.headers.get("Content-Type", ""):
            _WORKING[:] = [(url, version, model_id)]   # remember what works for the next batches
            break
        last = f"{resp.status_code} {resp.headers.get('Content-Type')} from {url} (api {version}): {resp.text[:120]!r}"
        log.info("neutral titles: GitHub Models attempt failed: %s", last)
    else:
        raise ValueError(f"no GitHub Models endpoint answered properly; last: {last}")
    try:
        text = resp.json()["choices"][0]["message"]["content"] or ""
        data = _parse_json(text)
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise ValueError(f"unreadable reply ({resp.status_code}): {resp.text[:300]!r}") from exc
    wanted = {k for k, _ in batch}
    return {e["id"]: e for e in data.get("stories", [])
            if isinstance(e, dict) and e.get("id") in wanted and str(e.get("title", "")).strip()}


def _parse_json(text: str) -> dict:
    """Models sometimes wrap JSON in ```json fences or add a sentence around it."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        text = text.rsplit("```", 1)[0]
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object in reply")
    return json.loads(text[start:end + 1])


OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
if not OLLAMA_URL.startswith("http"):
    OLLAMA_URL = "http://" + OLLAMA_URL


def _ask_local(model: str, language: str, batch: list[tuple[str, dict]]) -> dict[str, dict]:
    """One small batch to the local model; Ollama constrains the reply to our JSON schema."""
    payload = [dict(id=k, **m) for k, m in batch]
    resp = requests.post(f"{OLLAMA_URL}/api/chat", timeout=300, json={
        "model": model,
        "stream": False,
        "format": SCHEMA,
        "options": {"temperature": 0.2, "num_ctx": 4096},
        "messages": [
            {"role": "system", "content": SYSTEM.format(language=language)},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
    })
    resp.raise_for_status()
    data = _parse_json(resp.json()["message"]["content"])
    wanted = {k for k, _ in batch}
    return {e["id"]: e for e in data.get("stories", [])
            if isinstance(e, dict) and e.get("id") in wanted and str(e.get("title", "")).strip()}


def _provider(opts: dict, client) -> str | None:
    if client is not None:
        return "anthropic"
    choice = opts.get("provider", "auto")
    if choice in ("anthropic", "auto") and os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if choice in ("local", "auto") and os.environ.get("NEWSDESK_LOCAL_MODEL"):
        return "local"
    if choice == "github" and os.environ.get("GITHUB_TOKEN"):
        return "github"
    return None


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
    provider = _provider(opts, client)
    if todo and provider:
        local = provider == "local"
        todo = todo[: int(opts.get("max_new_per_run_local" if local else "max_new_per_run", 40))]
        language = LANG_NAMES.get(cfg["site"]["ui_language"], "English")
        limit = 700 if local else 1500   # small models: shorter material is faster and works better
        with cf.ThreadPoolExecutor(10) as pool:
            excerpts = list(pool.map(lambda ks: article_excerpt(ks[1].headline.link, limit), todo))
        material = [(k, _material(s, ex, 3 if local else 5)) for (k, s), ex in zip(todo, excerpts)]
        size = 3 if local else BATCH
        batches = [material[i:i + size] for i in range(0, len(material), size)]
        deadline = time.time() + float(opts.get("time_budget_seconds", 480))

        results = {}
        if provider == "anthropic":
            import anthropic

            client = client or anthropic.Anthropic()
            model = opts.get("model", "claude-opus-5-5")
            ask = lambda b: _ask_claude(client, model, language, b)  # noqa: E731
        elif local:
            model = os.environ["NEWSDESK_LOCAL_MODEL"]
            ask = lambda b: _ask_local(model, language, b)  # noqa: E731
        else:
            token, model = os.environ["GITHUB_TOKEN"], opts.get("github_model", "openai/gpt-4.1-mini")
            ask = lambda b: _ask_github(token, model, language, b)  # noqa: E731
        for batch in batches:  # one at a time: kind to rate limits
            if time.time() > deadline:
                log.info("neutral titles: time budget used; the rest waits for the next run")
                break
            try:
                results.update(ask(batch))
            except OutOfQuota as exc:
                log.warning("neutral titles: free quota used up for now (%s)", exc)
                break
            except Exception as exc:  # never let this break the edition
                log.warning("neutral titles: %s: %s; keeping original headlines", type(exc).__name__, exc)
        now = int(time.time())
        for key, s in todo:
            if key in results:
                entry = {"title": results[key]["title"].strip(), "summary": results[key]["summary"].strip(),
                         "n": len(s.outlets), "t": now}
                cache[key] = s.neutral = entry
                written += 1
        log.info("neutral titles (%s): %d written now", provider, written)

    # Forget stories older than three days.
    cutoff = time.time() - 3 * 86400
    cache = {k: v for k, v in cache.items() if v.get("t", 0) >= cutoff}
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    return written
