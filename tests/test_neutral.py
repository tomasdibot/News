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


def test_free_github_models_provider(articles, cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(neutral, "article_excerpt", lambda url: "")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "ghs_test")
    sent = []

    class Resp:
        status_code = 200
        text = ""

        def __init__(self, body):
            self.body = body

        def raise_for_status(self):
            pass

        def json(self):
            return self.body

    def fake_post(url, headers, json, timeout):
        sent.append((url, headers, json))
        stories = __import__("json").loads(json["messages"][1]["content"])
        out = {"stories": [{"id": s["id"], "title": "Libre: " + s["outlets"][0]["headline"][:20], "summary": "R."}
                           for s in stories]}
        return Resp({"choices": [{"message": {"content": __import__("json").dumps(out)}}]})

    monkeypatch.setattr(neutral.requests, "post", fake_post)
    stories = score_stories(cluster(articles), cfg, NOW)
    assert neutral.neutralize(stories, cfg, cache_path=tmp_path / "c.json") == len(stories)
    url, headers, body = sent[0]
    assert url == "https://models.github.ai/inference/chat/completions"
    assert headers["Authorization"] == "Bearer ghs_test" and body["model"] == "openai/gpt-4.1-mini"
    assert all(s.neutral["title"].startswith("Libre: ") for s in stories)


def test_free_quota_used_up_keeps_original_headlines(articles, cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(neutral, "article_excerpt", lambda url: "")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "ghs_test")
    calls = []

    def fake_post(*a, **k):
        calls.append(1)
        return SimpleNamespace(status_code=429, text="rate limit")

    monkeypatch.setattr(neutral.requests, "post", fake_post)
    stories = score_stories(cluster(articles), cfg, NOW)
    assert neutral.neutralize(stories, cfg, cache_path=tmp_path / "c.json") == 0
    assert len(calls) == 1 and not any(s.neutral for s in stories)   # stops after the first refusal


def test_reply_wrapped_in_code_fences_is_understood():
    assert neutral._parse_json('```json\n{"stories": []}\n```') == {"stories": []}
    assert neutral._parse_json('Here you go: {"stories": [{"id": "a"}]} Done.') == {"stories": [{"id": "a"}]}
