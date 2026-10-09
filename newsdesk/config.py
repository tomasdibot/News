"""Loading of config.yaml / sources.yaml, with private overrides from the environment."""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent

DEFAULTS: dict = {
    "profile": {
        "age": None,
        "country": "",
        "city": "",
        "languages": ["es", "en"],
        "use_age_hints": True,
        "topics": [{"name": "world", "weight": 1.0}],
        "muted_topics": [],
    },
    "site": {
        "title": "Newsdesk",
        "ui_language": "en",
        "url": "",
        "max_age_hours": 36,
        "top_stories": 8,
        "local_stories": 6,
        "stories_per_topic": 6,
    },
    "notification": {
        "time": "08:00",
        "timezone": "UTC",
        "provider": "console",
        "headlines": 5,
    },
    "neutral_titles": {"enabled": True, "provider": "auto", "github_model": "openai/gpt-4.1-mini",
                       "model": "claude-opus-5-5", "max_stories": 120, "max_new_per_run": 30},
    "refresh_minutes": 60,
}


@dataclass
class Source:
    id: str
    outlet: str
    url: str
    lang: str
    region: str = "global"
    tier: str = "commercial"
    topics: list[str] = field(default_factory=list)


def deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config(path: str | Path | None = None) -> dict:
    path = Path(path or os.environ.get("NEWSDESK_CONFIG") or ROOT / "config.yaml")
    cfg = deep_merge(DEFAULTS, yaml.safe_load(path.read_text(encoding="utf-8")) or {})

    # Private overrides (age, city, ...) that should not live in a public repo.
    private = os.environ.get("NEWSDESK_PROFILE", "").strip()
    if private:
        cfg = deep_merge(cfg, yaml.safe_load(private) or {})

    if os.environ.get("NEWSDESK_SITE_URL"):
        cfg["site"]["url"] = os.environ["NEWSDESK_SITE_URL"]

    cfg["profile"]["country"] = str(cfg["profile"].get("country") or "").upper()
    cfg["profile"]["topics"] = [
        t if isinstance(t, dict) else {"name": str(t), "weight": 1.0}
        for t in cfg["profile"].get("topics") or []
    ]
    return cfg


def load_sources(cfg: dict, path: str | Path | None = None) -> list[Source]:
    """Sources for this profile: global ones + those of the user's country, in the user's languages."""
    path = Path(path or os.environ.get("NEWSDESK_SOURCES") or ROOT / "sources.yaml")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    langs = set(cfg["profile"]["languages"])
    country = cfg["profile"]["country"]
    sources = [Source(**item) for item in raw]
    return [
        s for s in sources
        if s.lang in langs and (s.region == "global" or s.region.upper() == country)
    ]
