from datetime import timedelta

from conftest import NOW, SOURCES

from newsdesk import judge
from newsdesk.cluster import cluster
from newsdesk.fetch import Article
from newsdesk.rank import score_stories

THEME = "Avances de la IA de fuentes oficiales, modelos y desarrollo"


def stories(cfg):
    arts = [
        Article(SOURCES["bbc"], "OpenAI releases GPT-6 language model", "https://x/1", "The company announced it.", NOW - timedelta(hours=1)),
        Article(SOURCES["dw"], "Startup builds AI agent that helps people cut calories", "https://x/2", "A diet app.", NOW - timedelta(hours=2)),
        Article(SOURCES["bbc"], "Central bank raises interest rates", "https://x/3", "Inflation worries.", NOW - timedelta(hours=1)),
    ]
    return score_stories(cluster(arts), cfg, NOW)


def test_theme_key_matches_the_app():
    assert judge.theme_key("  Avances de la IA: ¡modelos!  ") == "avances de la ia modelos"


def test_themes_come_from_the_secret(monkeypatch, cfg):
    monkeypatch.setenv("NEWSDESK_THEMES", "Fútbol argentino\n- IA oficial\n\nfutbol argentino")
    assert judge.configured_themes(cfg) == ["Fútbol argentino", "IA oficial"]


def test_only_candidates_are_read_and_verdicts_are_cached(monkeypatch, cfg, tmp_path):
    monkeypatch.setenv("NEWSDESK_THEMES", THEME)
    monkeypatch.setenv("NEWSDESK_LOCAL_MODEL", "fake")
    asked = []

    def fake_ask(provider, client, model, theme, material):   # one story at a time
        asked.append(material["headlines"][0])
        return "GPT-6" in material["headlines"][0]

    monkeypatch.setattr(judge, "_ask_one", fake_ask)
    ss = stories(cfg)
    keys = judge.judge_themes(ss, cfg, cache_path=tmp_path / "c.json")
    tk = judge.theme_key(THEME)
    assert keys == [tk]
    assert not any("Central bank" in h for h in asked)          # not about AI: never sent to the model
    fits = {s.headline.title: s.fits.get(tk) for s in ss}
    assert fits["OpenAI releases GPT-6 language model"] is True
    assert fits["Startup builds AI agent that helps people cut calories"] is False
    assert "Central bank raises interest rates" not in [t for t, v in fits.items() if v is not None]

    asked.clear()
    ss = stories(cfg)
    judge.judge_themes(ss, cfg, cache_path=tmp_path / "c.json")
    assert asked == []                                            # second run: from the cache
    assert any(s.fits.get(tk) is True for s in ss)


def test_without_a_model_nothing_is_filtered(monkeypatch, cfg, tmp_path):
    monkeypatch.setenv("NEWSDESK_THEMES", THEME)
    ss = stories(cfg)
    assert judge.judge_themes(ss, cfg, cache_path=tmp_path / "c.json") == []


def test_local_model_gets_short_ids_and_a_capped_answer(monkeypatch):
    sent = {}

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"message": {"content": '{"results": [{"id": "1", "fits": true}, {"id": "2", "fits": false}]}'}}

    def post(url, timeout, json):
        sent.update(json)
        return Resp()

    monkeypatch.setattr(judge.requests, "post", post)
    got = judge._ask("local", None, "m", "Música: lanzamientos", [("ab:111", {"headlines": ["x"]}), ("ab:222", {"headlines": ["y"]})])
    assert got == {"ab:111": True, "ab:222": False}
    assert '"id": "1"' in sent["messages"][1]["content"] and "ab:111" not in sent["messages"][1]["content"]
    assert sent["options"]["num_predict"] <= 60


def test_audit_scores_known_examples_and_lists_todays_verdicts(monkeypatch, cfg, articles):
    from newsdesk import audit

    monkeypatch.setenv("NEWSDESK_THEMES", "Música: Lanzamientos, Shows\nAlgo sin ejemplos")
    monkeypatch.setenv("NEWSDESK_LOCAL_MODEL", "fake")
    monkeypatch.setattr(audit, "fetch_all", lambda *a, **k: articles)
    # A fake model that says "in" to everything: the test must catch its mistakes.
    monkeypatch.setattr(audit, "ask_many", lambda p, c, m, t, items, mode="single": {k: True for k, _ in items})
    out = []
    assert audit.run(cfg, out=out.append) == 0
    report = out[0]
    assert "5/10 right" in report and "should be OUT" in report and "Overall: 5/10" in report
    assert "no example stories" in report
    assert "## 2. Today's news" in report


def test_one_story_per_request_with_a_tiny_answer(monkeypatch):
    sent = []

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"message": {"content": '{"fits": true}'}}

    monkeypatch.setattr(judge.requests, "post", lambda url, timeout, json: sent.append(json) or Resp())
    got = judge.ask_many("local", None, "m", "Música", [("a", {"headlines": ["x"]}), ("b", {"headlines": ["y"]})])
    assert got == {"a": True, "b": True} and len(sent) == 2
    assert "Section: Música" in sent[0]["messages"][1]["content"] and sent[0]["options"]["num_predict"] <= 12
