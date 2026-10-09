from datetime import datetime, timezone
from pathlib import Path

import pytest

from newsdesk.config import DEFAULTS, Source, deep_merge
from newsdesk.fetch import parse_feed

FIX = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)

SOURCES = {
    "bbc": Source(id="bbc", outlet="BBC", url="x", lang="en", region="global", tier="public", topics=["world"]),
    "dw": Source(id="dw", outlet="DW", url="x", lang="en", region="global", tier="public"),
    "infobae": Source(id="infobae", outlet="Infobae", url="x", lang="es", region="AR"),
    "lanacion": Source(id="lanacion", outlet="La Nación", url="x", lang="es", region="AR"),
}


@pytest.fixture
def articles():
    out = []
    for name, src in SOURCES.items():
        out += parse_feed(src, (FIX / f"{name}.xml").read_bytes(), now=NOW)
    return out


@pytest.fixture
def cfg():
    c = deep_merge(DEFAULTS, {
        "profile": {
            "age": 30, "country": "AR", "languages": ["es", "en"],
            "topics": [{"name": "world", "weight": 1.0}, {"name": "economy", "weight": 0.9},
                       {"name": "science", "weight": 0.7}],
            "muted_topics": ["sports"],
        },
        "site": {"ui_language": "es", "url": "https://example.github.io/News/"},
        "notification": {"timezone": "America/Argentina/Buenos_Aires", "headlines": 3},
    })
    c["_fetch_images"] = False
    return c


@pytest.fixture(autouse=True)
def no_real_ai_calls(monkeypatch):
    # Never reach a real AI provider from tests (the sandbox may have tokens set).
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("NEWSDESK_LOCAL_MODEL", raising=False)
    monkeypatch.delenv("NEWSDESK_THEMES", raising=False)
