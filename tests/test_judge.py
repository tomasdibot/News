from datetime import timedelta

from conftest import NOW, SOURCES

from newsdesk import judge
from newsdesk.cluster import cluster
from newsdesk.config import Source
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
    assert "8/13 right" in report and "should be OUT" in report and "Overall: 8/13" in report
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


def test_each_theme_logs_candidates_accepted_and_multi_outlet(monkeypatch, cfg, tmp_path, caplog):
    monkeypatch.setenv("NEWSDESK_THEMES", THEME)
    monkeypatch.setenv("NEWSDESK_LOCAL_MODEL", "fake")
    monkeypatch.setattr(judge, "_ask_one", lambda *a: True)
    with caplog.at_level("INFO", logger="newsdesk.judge"):
        judge.judge_themes(stories(cfg), cfg, cache_path=tmp_path / "c.json")
    line = next(r.getMessage() for r in caplog.records if r.getMessage().startswith("theme "))
    assert line.startswith(f"theme {THEME}: candidates=")
    assert "accepted=" in line and "multi_outlet=" in line
    assert "confirmed=" in line


def test_music_theme_logs_confirmed_by_two_and_the_order_with_samples(monkeypatch, cfg, tmp_path, caplog):
    arts = [Article(SOURCES[src], title, f"https://x/m{i}{src}", "", NOW - timedelta(hours=1))
            for i, title in enumerate(["Lali anuncia show en Buenos Aires", "Coldplay lanza nuevo álbum"])
            for src in ("bbc", "dw")] + [
        Article(SOURCES["bbc"], "Un cantante gana un premio de música", "https://x/m9", "", NOW - timedelta(hours=1))]
    monkeypatch.setenv("NEWSDESK_THEMES", "Música: Lanzamientos")
    monkeypatch.setenv("NEWSDESK_ARTISTS", "Lali")
    monkeypatch.setenv("NEWSDESK_LOCAL_MODEL", "fake")
    monkeypatch.setattr(judge, "_ask_one", lambda *a: True)
    with caplog.at_level("INFO", logger="newsdesk.judge"):
        judge.judge_themes(score_stories(cluster(arts), cfg, NOW), cfg, cache_path=tmp_path / "c.json")
    lines = [r.getMessage() for r in caplog.records]
    assert any(l.startswith("theme Música: Lanzamientos:") and "accepted=3" in l and "confirmed=2" in l for l in lines)
    assert "music order: artist=1 shows=0 releases=1" in lines
    assert "music artist: Lali anuncia show en Buenos Aires" in lines


MUSIC = "Música: Lanzamientos"
INDIE = Source(id="indiehoy", outlet="Indie Hoy", url="", lang="es", region="AR", tier="specialist",
               topics=["culture"], gnews="indiehoy.com")
DIARIO = Source(id="diario", outlet="Diario", url="x", lang="es", region="AR", tier="commercial")


def titled(cfg, src, *titles):
    arts = [Article(src, t, f"https://x/{src.id}{i}", "", NOW - timedelta(hours=1)) for i, t in enumerate(titles)]
    return score_stories(cluster(arts), cfg, NOW)


def test_music_candidates_admit_culture_specialist_outlets_whatever_the_words(cfg):
    ts = ["Divididos vuelve al Movistar Arena con dos fechas en diciembre",
          "Primavera Sound Buenos Aires: Charli XCX y Bad Bunny confirmados",
          "Turf anuncia fecha en Obras"]
    got = {s.headline.title for s in judge.candidates(MUSIC, titled(cfg, INDIE, *ts))}
    assert got == set(ts)


def test_music_candidates_widen_the_words_for_any_outlet(cfg):
    ts = ["Wos presenta 'Ojo de Pez', su nuevo EP", "Entradas agotadas para Dua Lipa en River",
          "Lollapalooza: la grilla completa del festival"]
    got = {s.headline.title for s in judge.candidates(MUSIC, titled(cfg, DIARIO, *ts))}
    assert got == set(ts)


def test_music_candidates_still_leave_out_politics_and_other_outlets_stay_narrow(cfg):
    politics = titled(cfg, DIARIO, "El Senado debate el presupuesto 2027")
    assert judge.candidates(MUSIC, politics) == []
    assert judge.candidates(MUSIC, titled(cfg, DIARIO, "Wos presenta su nuevo EP")) != []
    # the extra music words are for music themes only
    assert judge.candidates("Economía", titled(cfg, DIARIO, "Entradas agotadas para Dua Lipa en River")) == []
    assert judge.candidates(THEME, titled(cfg, INDIE, "Turf anuncia fecha en Obras")) == []


def test_music_themes_read_up_to_60_candidates_others_40(monkeypatch, cfg, tmp_path, caplog):
    ss = titled(cfg, INDIE, "Wos presenta su nuevo EP")
    monkeypatch.setattr(judge, "candidates", lambda theme, stories: ss * 70)
    monkeypatch.setenv("NEWSDESK_THEMES", MUSIC + "\n" + "Economía")
    monkeypatch.setenv("NEWSDESK_LOCAL_MODEL", "fake")
    monkeypatch.setattr(judge, "_ask_one", lambda *a: True)
    with caplog.at_level("INFO", logger="newsdesk.judge"):
        judge.judge_themes(ss, cfg, cache_path=tmp_path / "c.json")
    lines = [r.getMessage() for r in caplog.records]
    assert any(l.startswith(f"theme {MUSIC}: candidates=60 ") for l in lines)
    assert any(l.startswith("theme Economía: candidates=40 ") for l in lines)


def test_music_and_ai_themes_log_candidates_and_accepted_per_outlet(monkeypatch, cfg, tmp_path, caplog):
    arts = [Article(INDIE, "Wos presenta su nuevo EP", "https://x/a", "", NOW - timedelta(hours=1)),
            Article(DIARIO, "Wos presenta su nuevo EP", "https://x/b", "", NOW - timedelta(hours=1)),
            Article(INDIE, "Turf anuncia fecha en Obras", "https://x/c", "", NOW - timedelta(hours=1)),
            Article(Source(id="gn-clarin", outlet="Clarín", url="", lang="es", tier="commercial", topics=["culture"]),
                    "Gira de una banda por el país", "https://x/d", "", NOW - timedelta(hours=1))]
    monkeypatch.setenv("NEWSDESK_THEMES", MUSIC)
    monkeypatch.setenv("NEWSDESK_LOCAL_MODEL", "fake")
    monkeypatch.setattr(judge, "_ask_one", lambda p, c, m, t, material: "Wos" in material["headlines"][0])
    with caplog.at_level("INFO", logger="newsdesk.judge"):
        judge.judge_themes(score_stories(cluster(arts), cfg, NOW), cfg, cache_path=tmp_path / "c.json")
    line = next(r.getMessage() for r in caplog.records if r.getMessage().startswith("sources "))
    assert line.startswith(f"sources {MUSIC}: ")
    assert "Indie Hoy 2/1" in line and "Diario 1/1" in line and "Clarín 1/0" in line


def test_ia_launch_rule_has_the_new_examples_and_music_does_not():
    ia = judge.one_system("IA: lanzamientos")
    for e in ("Paper in Science: AI model maps new antibiotics", "Lab presents a new open-weights language model",
              "Developer builds an AI agent to plan his meals", "Retailer says AI helps it cut delivery times"):
        assert e in ia
    assert "antibiotics" not in judge.one_system("Música: Lanzamientos")
    assert judge.VERSION == 9


def test_official_ai_blogs_read_through_google_news_mark_their_stories_official(cfg):
    from newsdesk.config import load_sources
    from newsdesk.edition import story_dict
    from newsdesk.fetch import feed_url

    by_id = {s.id: s for s in load_sources({"profile": {"languages": ["es", "en"], "country": "AR"}})}
    for id_, site in (("anthropic-news", "anthropic.com/news"), ("meta-ai", "ai.meta.com/blog"),
                      ("mistral-news", "mistral.ai/news")):
        s = by_id[id_]
        assert s.tier == "official" and s.region == "global" and s.lang == "en" and s.topics == ["technology"]
        assert f"site:{site}" in feed_url(s)
    ss = titled(cfg, by_id["anthropic-news"], "Introducing a new Claude model")
    assert story_dict(ss[0], cfg)["official"] is True


def test_official_ai_blogs_search_a_week_and_keep_their_items_a_week(cfg):
    from newsdesk.config import load_sources
    from newsdesk.fetch import feed_url

    by_id = {s.id: s for s in load_sources({"profile": {"languages": ["es", "en"], "country": "AR"}})}
    for id_ in ("anthropic-news", "meta-ai", "mistral-news"):
        assert "+when:7d&" in feed_url(by_id[id_]) and by_id[id_].max_age_hours == 7 * 24
    assert "+when:2d&" in feed_url(by_id["infobae-teleshow"])

    old = NOW - timedelta(days=5)
    art = Article(by_id["anthropic-news"], "Introducing a new Claude model", "https://x/c", "", old)
    assert score_stories(cluster([art]), cfg, NOW)


def _count_posts(monkeypatch):
    sent = []

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"message": {"content": '{"fits": true}'}}

    monkeypatch.setattr(judge.requests, "post", lambda url, timeout, json: sent.append(json) or Resp())
    return sent


def test_customer_stories_are_rejected_in_ai_themes_without_asking_the_model(monkeypatch):
    sent = _count_posts(monkeypatch)
    items = [("a", {"headlines": ["How Itaú is building generative AI for its entire customer base"]}),
             ("b", {"headlines": ["Cómo Mercado Libre usa la IA para vender más"]}),
             ("c", {"headlines": ["OpenAI launches GPT-6"]})]
    got = judge.ask_many("local", None, "m", "IA: lanzamientos", items)
    assert got == {"a": False, "b": False, "c": True} and len(sent) == 1
    sent.clear()   # other themes are untouched
    got = judge.ask_many("local", None, "m", "Economía", items[:1])
    assert got == {"a": True} and len(sent) == 1


def test_case_study_rule_leaves_lab_posts_how_tos_and_research_to_the_model(monkeypatch):
    sent = _count_posts(monkeypatch)
    heads = ["How we're building safer AI", "How we built GPT-6", "How OpenAI built GPT-6 using AI",
             "How Anthropic is building a safer Claude with AI", "Cómo usar la IA de Google en tu celular",
             "How researchers built an AI model that predicts storms", "How Google is using AI to forecast floods"]
    got = judge.ask_many("local", None, "m", "IA: lanzamientos", [(str(i), {"headlines": [h]}) for i, h in enumerate(heads)])
    assert all(got.values()) and len(sent) == len(heads)
    assert judge.is_case_study("IA", {"headlines": ["How Itaú is building generative AI for its entire customer base"]})
    assert judge.is_case_study("IA", {"headlines": ["Cómo Mercado Libre usa la IA para vender más"]})


def test_show_news_in_music_themes_is_accepted_without_asking_the_model(monkeypatch):
    sent = _count_posts(monkeypatch)
    yes = ["BTS en Argentina: cómo serán los shows en La Plata", "U2 confirmó los precios de sus shows en Argentina",
           "Iron Maiden announce 2027 world tour", "La banda Airbag anuncia show en Córdoba",
           "Fechas y entradas para Wos en el Gran Rex"]
    no = ["Festival Daltónica en Escobar", "Milei en Buenos Aires", "Gira del Presidente por Europa en 2026",
          "El ministro anunció una gira por Argentina",
          "Festival de cine de Mar del Plata 2026", "Festival de cine de Cannes 2026",
          "Gira de Boca por Estados Unidos 2026", "Tour de Francia 2026", "Show de drones en Buenos Aires",
          "Entradas Copa Argentina 2026", "El show de Messi en Argentina",
          "Precios de los alquileres 2026 en Buenos Aires", "Show en Santiago del Estero"]
    for h in yes:
        assert judge.is_show_news(h)
    for h in no:
        assert not judge.is_show_news(h)
    got = judge.ask_many("local", None, "m", "Música", [(str(i), {"headlines": [h]}) for i, h in enumerate(yes)])
    assert got == {str(i): True for i in range(len(yes))} and not sent
    got = judge.ask_many("local", None, "m", "Música", [(str(i), {"headlines": [h]}) for i, h in enumerate(no)])
    assert len(got) == len(no) and len(sent) == len(no)   # all of these still go to the model
    sent.clear()   # other themes are untouched
    judge.ask_many("local", None, "m", "Economía", [("a", {"headlines": [yes[0]]})])
    assert len(sent) == 1


def test_show_rule_needs_music_evidence_the_lead_headline_or_your_artist():
    assert not judge.is_show_news("Shows de drones en Buenos Aires 2026")
    assert judge.is_show_news("Show de Lali en Argentina", artist=True)       # your artist is the evidence
    assert not judge.is_show_news("Show de Lali en Argentina")
    assert judge.is_show_news("Lollapalooza Argentina 2026: festival y entradas")
    story = {"headlines": ["Festival de cine de Mar del Plata 2026", "U2 confirmó los precios de sus shows en Argentina"]}
    assert judge.rule_verdict("Música", story) is None                        # the lead decides, not the second headline
    assert judge.rule_verdict("Música", story, lead=story["headlines"][1]) is True


def test_rules_win_over_cached_verdicts(monkeypatch, cfg, tmp_path):
    monkeypatch.setenv("NEWSDESK_THEMES", "Música\nIA: lanzamientos")
    monkeypatch.setenv("NEWSDESK_LOCAL_MODEL", "fake")
    cache = tmp_path / "c.json"

    def arts():
        return score_stories(cluster([
            Article(SOURCES["bbc"], "U2 confirmó los precios de sus shows en Argentina", "https://x/1", "", NOW - timedelta(hours=1)),
            Article(SOURCES["dw"], "How Itaú is building generative AI for its entire customer base", "https://x/2", "", NOW - timedelta(hours=1)),
        ]), cfg, NOW)

    with monkeypatch.context() as m:   # an old run, before the rules: the opposite verdicts get cached
        m.setattr(judge, "rule_verdict", lambda theme, material, *a: None)
        m.setattr(judge, "_ask_one", lambda p, c, mo, theme, material: "shows" not in material["headlines"][0])
        judge.judge_themes(arts(), cfg, cache_path=cache)
    ss = arts()
    asked = []
    monkeypatch.setattr(judge, "_ask_one", lambda *a: asked.append(a) or True)
    judge.judge_themes(ss, cfg, cache_path=cache)
    fits = {s.headline.title[:2]: s.fits for s in ss}
    assert fits["U2"][judge.theme_key("Música")] is True       # cached False -> show rule
    assert fits["Ho"][judge.theme_key("IA: lanzamientos")] is False   # cached True -> case-study rule
    assert asked == []
