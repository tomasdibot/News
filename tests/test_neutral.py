"""Neutral titles, with a stand-in for Claude (no network, no cost)."""
import json
from types import SimpleNamespace

from conftest import NOW
from newsdesk import neutral
from newsdesk.cluster import cluster
from newsdesk.edition import build_edition
from newsdesk.rank import score_stories


class FakeClaude:
    def __init__(self):
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kw):
        self.calls.append(kw)
        stories = json.loads(kw["messages"][0]["content"])
        out = {"stories": [{"id": s["id"], "title": "Neutral: " + s["outlets"][0]["headline"][:30],
                            "summary": "Resumen."} for s in stories]}
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=json.dumps(out))])


def test_titles_are_rewritten_once_and_cached(articles, cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(neutral, "article_excerpt", lambda url: "Texto del artículo.")
    stories = score_stories(cluster(articles), cfg, NOW)
    fake, cache = FakeClaude(), tmp_path / "cache.json"
    assert neutral.neutralize(stories, cfg, cache_path=cache, client=fake) == len(stories)
    req = fake.calls[0]
    assert req["model"] == "claude-opus-5-5" and req["output_config"]["effort"] == "low"
    sent = json.loads(req["messages"][0]["content"])
    gaza = next(s for s in sent if any("Gaza" in o["headline"] for o in s["outlets"]))
    assert len(gaza["outlets"]) == 3 and gaza["article_text"] == "Texto del artículo."
    assert "Spanish" in req["system"]
    assert all(s.neutral["title"].startswith("Neutral: ") for s in stories)

    # Next hourly run: same stories come from the cache, Claude is not called again.
    again = score_stories(cluster(articles), cfg, NOW)
    fake2 = FakeClaude()
    assert neutral.neutralize(again, cfg, cache_path=cache, client=fake2) == 0
    assert not fake2.calls and all(s.neutral for s in again)


def test_without_api_key_original_headlines_stay(articles, cfg, tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(neutral, "CACHE_PATH", tmp_path / "c.json")
    stories = score_stories(cluster(articles), cfg, NOW)
    assert neutral.neutralize(stories, cfg, cache_path=tmp_path / "c.json") == 0
    assert not any(s.neutral for s in stories)


def test_edition_uses_neutral_title_and_marks_it(articles, cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(neutral, "article_excerpt", lambda url: "")
    fake = FakeClaude()
    monkeypatch.setattr(neutral, "CACHE_PATH", tmp_path / "c.json")
    real = neutral.neutralize
    monkeypatch.setattr("newsdesk.edition.neutralize", lambda pool, c: real(pool, c, cache_path=tmp_path / "c.json", client=fake))
    edition = build_edition(cfg, articles=articles, now=NOW)
    top = edition["top"][0]
    assert top["title"].startswith("Neutral: ") and top["ai"] and top["summary"] == "Resumen."
