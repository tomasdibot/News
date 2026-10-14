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


def test_artist_news_keeps_each_outlet_and_needs_the_artist_in_the_headline():
    from datetime import datetime, timezone

    from newsdesk.artists import parse_search

    rss = b"""<?xml version="1.0"?><rss><channel>
    <item><title>Lali anuncia una gira por Espa\xc3\xb1a - Clar\xc3\xadn</title><link>https://n/1</link>
      <pubDate>Mon, 12 Oct 2026 10:00:00 GMT</pubDate><source url="https://clarin.com">Clar\xc3\xadn</source></item>
    <item><title>La agenda del finde - Infobae</title><link>https://n/2</link>
      <pubDate>Mon, 12 Oct 2026 10:00:00 GMT</pubDate><source url="https://infobae.com">Infobae</source></item>
    </channel></rss>"""
    got = parse_search(rss, "Lali", "es", datetime(2026, 10, 13, tzinfo=timezone.utc))
    assert [(a.outlet, a.title) for a in got] == [("Clarín", "Lali anuncia una gira por España")]


def test_candidates_put_official_launches_before_mere_mentions(cfg):
    from datetime import timedelta

    from conftest import NOW, SOURCES

    from newsdesk.cluster import cluster
    from newsdesk.config import Source
    from newsdesk.fetch import Article
    from newsdesk.rank import score_stories

    official = Source(id="oa", outlet="OpenAI (official)", url="", lang="en", tier="official")
    arts = [Article(SOURCES["bbc"], "Shares rise as investors bet on artificial intelligence", "https://x/a", "", NOW - timedelta(hours=1)),
            Article(SOURCES["dw"], "Shares rise as investors bet on artificial intelligence boom", "https://x/b", "", NOW - timedelta(hours=1)),
            Article(official, "Introducing GPT-6: our new AI model", "https://x/c", "", NOW - timedelta(hours=5))]
    ss = score_stories(cluster(arts), cfg, NOW)
    got = judge.candidates("Inteligencia artificial: modelos y lanzamientos", ss)
    assert got[0].headline.title.startswith("Introducing GPT-6")


def test_artists_from_the_app(monkeypatch, cfg):
    monkeypatch.setenv("NEWSDESK_ARTISTS", "Lali\nColdplay, Wos\n-")
    assert judge.configured_artists(cfg) == ["Lali", "Coldplay", "Wos"]
