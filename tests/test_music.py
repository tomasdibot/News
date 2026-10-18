"""Música: your artists first, then shows, then releases; and how many outlets confirm a story."""
from datetime import datetime, timezone

import pytest
from conftest import NOW, SOURCES

from newsdesk import judge
from newsdesk.cluster import Story
from newsdesk.edition import build_edition, story_dict, theme_dictionary
from newsdesk.fetch import Article
from newsdesk.music import MAX_ARTISTS, artist_rank, music_tier, min_outlets


def story(*titles):
    return Story(articles=[Article(SOURCES["infobae"], t, f"https://x/{i}", "", NOW) for i, t in enumerate(titles)])


ARTISTS = ["Lali", "Charly García", "Wos"]


def test_artist_rank_is_the_position_of_the_first_artist_in_any_headline():
    assert artist_rank(story("Lali anuncia gira"), ARTISTS) == 0
    assert artist_rank(story("Nada de música", "Nuevo show de Wos en el Movistar Arena"), ARTISTS) == 2
    assert artist_rank(story("Wos y Lali juntos"), ARTISTS) == 0           # the one you rank higher
    assert artist_rank(story("Concierto de otro cantante"), ARTISTS) is None
    assert artist_rank(story("Lali anuncia gira"), []) is None


def test_artist_rank_ignores_case_and_accents_but_needs_whole_words():
    assert artist_rank(story("CHARLY GARCIA vuelve a los escenarios"), ARTISTS) == 1
    assert artist_rank(story("Charly García en Buenos Aires"), ["charly garcia"]) == 0
    assert artist_rank(story("Wosniak presenta su libro"), ARTISTS) is None
    assert artist_rank(story("Valentina Lalibertad gana premio"), ARTISTS) is None


@pytest.mark.parametrize("title,tier", [
    ("Coldplay anuncia un show en Buenos Aires", 1),
    ("Gira mundial: la banda tocará en el Estadio River", 1),
    ("Tour 2027 confirmado", 1),
    ("Gran recital en Luna Park", 1),
    ("Dua Lipa lanza su nuevo álbum", 2),
    ("Estrena single la banda inglesa", 2),
    ("Lanzamiento del disco más esperado", 2),
    ("Premios y homenajes a un cantante", 3),
    ("Dua Lipa lanza su nuevo álbum en Argentina", 2),     # a place alone is not a show
    ("Se presenta en Luna Park y River el sábado", 1),     # named music venues count on their own
    ("Palito Ortega se presenta en el Teatro Ópera", 1),
    ("Abel Pintos llena el Gran Rex", 1),
    ("Fiesta en Niceto y Vorterix este finde", 1),
    ("Ciclo en el Movistar Arena", 1),
    ("Estreno de una obra de teatro con Dady Brieva", 3),   # plays are not shows
    ("Milei en Buenos Aires", 3),                          # a city alone is not a show
    ("Festival en el Hipódromo de Palermo", 1),
    ("Tour por Argentina de una banda", 1),
    ("Lollapalooza 2027 confirmó su line up", 1),
    ("Cosquín Rock: la grilla completa", 1),
    ("Primavera Sound llega a Buenos Aires", 1),
    ("Entradas agotadas para Dua Lipa", 1),
    ("Turf anuncia fecha en Obras", 1),
    ("Fecha confirmada para el recital de Divididos", 1),
    ("Anses confirmó la fecha de cobro de jubilaciones", 3),
    ("Nueva fecha del Mundial de Clubes", 3),
    ("Banda narco: fecha de juicio", 3),
])
def test_music_tier_shows_before_releases_before_the_rest(title, tier):
    assert music_tier(story(title), None) == tier


def test_with_artists_configured_only_your_artists_get_the_show_tier():
    assert music_tier(story("Coldplay anuncia un show en Buenos Aires"), None, artists=True) == 3
    assert music_tier(story("Lollapalooza 2027 confirmó su line up"), None, artists=True) == 3
    assert music_tier(story("Dua Lipa lanza su nuevo álbum"), None, artists=True) == 2
    assert music_tier(story("Lali anuncia un show en Buenos Aires"), 0, artists=True) == 0
    assert music_tier(story("Coldplay anuncia un show en Buenos Aires"), None) == 1   # no artists configured: as before


def test_music_tier_puts_your_artist_first_whatever_the_headline_says():
    assert music_tier(story("Lali lanza su nuevo álbum"), 0) == 0
    assert music_tier(story("Noticias"), 2) == 0
    assert music_tier(story("Tour mundial"), None) == 1       # whole words: "Tourism" is not a tour
    assert music_tier(story("Tourism numbers up"), None) == 3


def test_story_dict_carries_artist_and_mtier_for_stories_from_any_feed(cfg):
    s = story("Charly García anuncia show en Argentina")
    s.headline = s.articles[0]
    s.topic_scores = {}
    d = story_dict(s, "es", ARTISTS)
    assert (d["artist"], d["mtier"]) == (1, 0)
    other = story("Se agota el show de Coldplay en Argentina")
    other.headline = other.articles[0]
    d = story_dict(other, "es", ARTISTS)
    assert (d["artist"], d["mtier"]) == (None, 3)   # with artists set, others get no show tier


def test_your_artists_keep_their_order_and_stop_at_the_cap(monkeypatch, cfg):
    names = [f"Artist {i}" for i in range(30)]
    monkeypatch.setenv("NEWSDESK_ARTISTS", "\n".join(names + ["artist 3"]))
    got = judge.configured_artists(cfg)
    assert MAX_ARTISTS == 20 and got == names[:20]


def test_min_outlets_is_2_for_music_and_ai_and_3_otherwise():
    assert min_outlets("Música") == 2
    assert min_outlets("Música: Lanzamientos") == 2          # music, not AI
    assert min_outlets("Shows y music en vivo") == 2
    assert min_outlets("Inteligencia artificial") == 2
    assert min_outlets("IA: lanzamientos y empresas") == 2    # AI, not music
    assert min_outlets("AI news") == 2
    assert min_outlets("Economía argentina") == 3
    assert min_outlets("Mundo") == 3
    assert min_outlets("Maria y la Dialéctica") == 3          # "ia" only as a whole word


def test_theme_dictionary_gives_each_theme_its_threshold(monkeypatch, cfg):
    monkeypatch.setenv("NEWSDESK_THEMES", "Música: Lanzamientos\nIA: lanzamientos y empresas\nPolítica")
    got = theme_dictionary(cfg)["min_outlets"]
    assert got["musica lanzamientos"] == 2 and got["ia lanzamientos y empresas"] == 2 and got["politica"] == 3
    assert got["musica"] == 2 and got["economia"] == 3          # the built-in themes too


def test_real_sources_yaml_has_argentine_music_outlets_and_teleshow_counts_as_infobae(cfg):
    from newsdesk.config import load_sources
    from newsdesk.fetch import feed_url
    by_id = {s.id: s for s in load_sources({"profile": {"languages": ["es", "en"], "country": "AR"}})}
    for id_ in ("indiehoy", "billboard-ar", "rockcomar"):
        s = by_id[id_]
        assert s.region == "AR" and s.lang == "es" and s.topics == ["culture"] and s.gnews
    tele = by_id["infobae-teleshow"]
    assert tele.outlet == by_id["infobae"].outlet == "Infobae" and tele.lean == by_id["infobae"].lean
    assert "site:infobae.com/teleshow" in feed_url(tele)


def test_artist_articles_outlive_the_normal_age_limit_but_normal_ones_do_not(cfg):
    from datetime import timedelta
    from newsdesk.artists import parse_search
    from newsdesk.cluster import cluster
    from newsdesk.rank import score_stories
    five_days = NOW - timedelta(days=5)
    lali = parse_search(b"""<rss><channel><item><title>Lali anuncia recital - Clarin</title><link>https://n/9</link>
      <pubDate>Fri, 03 Oct 2026 12:00:00 GMT</pubDate><source url="https://clarin.com">Clarin</source></item></channel></rss>""",
                        "Lali", "es", NOW)
    assert lali
    old_normal = Article(SOURCES["infobae"], "Nuevo recital de Lali en el Luna Park", "https://x/old", "", five_days)
    kept = score_stories(cluster(lali + [old_normal]), cfg, NOW)
    titles = {a.title for s in kept for a in s.articles}
    assert "Lali anuncia recital" in titles and old_normal.title not in titles


def test_artist_rank_ignores_a_passing_mention():
    assert artist_rank(story("Nsqk dijo que escuchó Radiohead en su infancia"), ["Radiohead"]) is None
    assert artist_rank(story("Radiohead anuncia gira"), ["Radiohead"]) == 0
    assert artist_rank(story("Tras años de silencio, la gira de Radiohead sorprende"), ["Radiohead"]) == 0
    assert artist_rank(story("Nsqk dijo que escuchó Radiohead en su infancia", "Radiohead lanza single"), ["Radiohead"]) == 0


def test_artist_rank_keeps_headlines_about_returns_tickets_and_dates():
    assert artist_rank(story("El regreso de Tool"), ["Tool"]) == 0
    assert artist_rank(story("Cuánto cuestan las entradas de Tool en Argentina"), ["Tool"]) == 0
    assert artist_rank(story("Nsqk dijo que escuchó Radiohead en su infancia"), ["Radiohead"]) is None


def test_google_news_outage_reuses_the_last_good_results(tmp_path, monkeypatch, caplog):
    import logging
    from datetime import datetime, timedelta, timezone
    from newsdesk import artists as A
    now = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)
    fresh = lambda t: f"<item><title>{t} - Rolling Stone</title><link>https://x/{t.replace(' ', '')}</link>" \
                      f"<source url='https://rs'>Rolling Stone</source><pubDate>{(now - timedelta(days=1)).strftime('%a, %d %b %Y %H:%M:%S GMT')}</pubDate></item>"
    feed = lambda *t: ("<rss><channel>" + "".join(fresh(x) for x in t) + "</channel></rss>").encode()

    class R:
        def __init__(self, c): self.content = c

    cache = tmp_path / "gnews-cache.json"
    monkeypatch.setattr(A, "_get", lambda url, *a, **k: R(feed("Tame Impala anuncia show en Buenos Aires")))
    good = A.fetch_google_news(["Tame Impala"], now, cache)
    assert good and cache.exists()

    def down(url, *a, **k):
        raise RuntimeError("503")
    monkeypatch.setattr(A, "_get", down)
    with caplog.at_level(logging.INFO):
        again = A.fetch_google_news(["Tame Impala"], now + timedelta(hours=1), cache)
    assert {a.link for a in again} == {a.link for a in good}
    assert any(a.query == "tame impala" for a in again)
    assert "gnews fallback:" in caplog.text and "artist articles" in caplog.text
    # once the stored articles are older than their limits, nothing is reused
    assert A.fetch_google_news(["Tame Impala"], now + timedelta(days=30), cache) == []
    # no cache, no results
    assert A.fetch_google_news(["Tame Impala"], now, tmp_path / "none.json") == []


def test_google_news_fallback_only_brings_back_artists_still_in_your_list(tmp_path, monkeypatch, caplog):
    import logging
    from datetime import datetime, timedelta, timezone
    from newsdesk import artists as A
    now = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)
    when = (now - timedelta(days=1)).strftime('%a, %d %b %Y %H:%M:%S GMT')
    item = lambda t: (f"<item><title>{t} - Rolling Stone</title><link>https://x/{t.replace(' ', '')}</link>"
                      f"<source url='https://rs'>Rolling Stone</source><pubDate>{when}</pubDate></item>")

    class R:
        def __init__(self, c): self.content = c

    def serve(up):
        def get(url, *a, **k):
            if not up:
                raise RuntimeError("503")
            name = "Tame Impala" if "Tame" in url else "Soda Stereo"
            return R(("<rss><channel>" + item(f"{name} anuncia show en Buenos Aires") + "</channel></rss>").encode())
        monkeypatch.setattr(A, "_get", get)

    cache = tmp_path / "c.json"
    serve(True)
    A.fetch_google_news(["Tame Impala", "Soda Stereo"], now, cache)
    serve(False)
    with caplog.at_level(logging.INFO):
        full = A.fetch_google_news(["Tame Impala"], now, cache)   # Soda Stereo was removed from the list
    assert [a.query for a in full] == ["tame impala"]
    assert "gnews fallback: 1 artist articles" in caplog.text


def test_story_dict_gives_the_show_tier_only_to_your_artists():
    s = story("Coldplay anuncia un show en Buenos Aires")
    s.topic_scores = {}
    s.headline = s.articles[0]
    assert story_dict(s, "es", ["Lali"])["mtier"] == 3
    assert story_dict(s, "es", [])["mtier"] == 1
    assert story_dict(s, "es", ["Coldplay"])["mtier"] == 0


def _music_stories(cfg, monkeypatch, rows, artists="Lali\nWos"):
    """rows: (headline, [outlets], hours ago). Judged with a model that accepts everything."""
    monkeypatch.setenv("NEWSDESK_THEMES", "Música")
    monkeypatch.setenv("NEWSDESK_ARTISTS", artists)
    monkeypatch.setenv("NEWSDESK_LOCAL_MODEL", "fake")
    monkeypatch.setattr(judge, "_ask_one", lambda *a: True)
    from datetime import timedelta
    from newsdesk.cluster import cluster
    from newsdesk.rank import score_stories
    out = []
    for i, (title, outlets, hours) in enumerate(rows):
        for j, o in enumerate(outlets):
            out.append(Article(SOURCES[o], title if j == 0 else title + " hoy", f"https://x/{i}-{j}", "",
                               NOW - timedelta(hours=hours)))
    return score_stories(cluster(out), cfg, NOW)


def test_music_theme_keeps_one_story_per_artist(cfg, monkeypatch, tmp_path, caplog):
    import logging
    rows = [("Lali anuncia gira por Argentina", ["infobae"], 5),
            ("Lali lanza su nuevo álbum", ["infobae", "lanacion"], 4),      # more outlets: wins
            ("Wos presenta single nuevo", ["infobae"], 3),
            ("Wos lanza su nuevo disco", ["infobae"], 2)]                    # same outlets, release vs release: newest
    ss = _music_stories(cfg, monkeypatch, rows)
    with caplog.at_level(logging.INFO):
        judge.judge_themes(ss, cfg, cache_path=tmp_path / "c.json")
    fits = {s.headline.title: s.fits[judge.theme_key("Música")] for s in ss}
    assert fits == {"Lali anuncia gira por Argentina": False, "Lali lanza su nuevo álbum": True,
                    "Wos presenta single nuevo": False, "Wos lanza su nuevo disco": True}
    assert "music: kept 1 per artist (2 dropped)" in caplog.text


def test_one_per_artist_prefers_shows_over_releases_and_leaves_other_stories_alone(cfg, monkeypatch, tmp_path):
    rows = [("Lali lanza su nuevo álbum", ["infobae"], 1),
            ("Lali anuncia show en Buenos Aires", ["infobae"], 9),
            ("Nuevo disco de una banda de Rosario", ["infobae"], 2)]
    ss = _music_stories(cfg, monkeypatch, rows)
    judge.judge_themes(ss, cfg, cache_path=tmp_path / "c.json")
    tk = judge.theme_key("Música")
    fits = {s.headline.title: s.fits[tk] for s in ss}
    assert fits["Lali anuncia show en Buenos Aires"] is True and fits["Lali lanza su nuevo álbum"] is False
    assert fits["Nuevo disco de una banda de Rosario"] is True      # no artist: not grouped


def test_real_sources_yaml_has_the_extra_ai_outlets_named_like_existing_ones(cfg):
    from newsdesk.config import load_sources
    from newsdesk.fetch import feed_url
    by_id = {s.id: s for s in load_sources({"profile": {"languages": ["es", "en"], "country": "AR"}})}
    outlets = {s.outlet for s in by_id.values()}
    for id_, outlet, lang in [("xataka", "Xataka", "es"), ("hipertextual", "Hipertextual", "es"),
                              ("infobae-tecno", "Infobae", "es"), ("lanacion-tecno", "La Nación", "es"),
                              ("elpais-tecno", "El País", "es"), ("wired-es", "WIRED en español", "es"),
                              ("the-decoder", "The Decoder", "en"),
                              ("mit-news", "MIT News", "en"), ("apple-ml", "Apple ML (official)", "en"),
                              ("xai-news", "xAI (official)", "en")]:
        s = by_id[id_]
        assert (s.outlet, s.lang, s.topics) == (outlet, lang, ["technology"]) and s.gnews and "site:" in feed_url(s)
    assert by_id["apple-ml"].tier == by_id["xai-news"].tier == "official"
    assert by_id["xai-news"].gnews_days == 7
    assert by_id["infobae-tecno"].outlet == by_id["infobae"].outlet and by_id["lanacion-tecno"].outlet == by_id["lanacion"].outlet


def test_one_per_artist_also_merges_repeats_across_languages(cfg, monkeypatch, tmp_path):
    rows = [("Tame Impala tickets on sale in Montreal at Centre Bell", ["bbc"], 3),          # English story
            ("Tame Impala lanza su nuevo álbum sorpresa", ["infobae"], 2)]  # Spanish story, same artist
    ss = _music_stories(cfg, monkeypatch, rows, artists="Tame Impala")
    assert len(ss) == 2                                                        # the clusterer keeps languages apart
    judge.judge_themes(ss, cfg, cache_path=tmp_path / "c.json")
    assert sum(bool(s.fits[judge.theme_key("Música")]) for s in ss) == 1


def test_artist_search_keeps_only_headlines_with_the_artist_as_a_whole_word():
    from newsdesk.artists import parse_search
    rss = b"""<rss><channel>
      <item><title>Nuevo stool de diseno - Clarin</title><link>https://n/1</link><pubDate>Fri, 09 Oct 2026 12:00:00 GMT</pubDate><source url="https://c.com">Clarin</source></item>
      <item><title>Toolbox gratis para musicos - Clarin</title><link>https://n/2</link><pubDate>Fri, 09 Oct 2026 12:00:00 GMT</pubDate><source url="https://c.com">Clarin</source></item>
      <item><title>Tool anuncia gira por Sudamerica - Clarin</title><link>https://n/3</link><pubDate>Fri, 09 Oct 2026 12:00:00 GMT</pubDate><source url="https://c.com">Clarin</source></item>
      </channel></rss>"""
    assert [a.title for a in parse_search(rss, "Tool", "es", NOW)] == ["Tool anuncia gira por Sudamerica"]


def test_artist_search_handles_names_with_symbols_and_accents():
    from newsdesk.artists import parse_search
    rss = """<rss><channel>
      <item><title>AC/DC anuncia gira - Clarin</title><link>https://n/1</link><pubDate>Fri, 09 Oct 2026 12:00:00 GMT</pubDate><source url="https://c.com">Clarin</source></item>
      <item><title>BabasonÃ­cos vuelven al Luna Park - Clarin</title><link>https://n/2</link><pubDate>Fri, 09 Oct 2026 12:00:00 GMT</pubDate><source url="https://c.com">Clarin</source></item>
      </channel></rss>""".encode()
    assert len(parse_search(rss, "AC/DC", "es", NOW)) == 1 and len(parse_search(rss, "Babasónicos", "es", NOW)) == 1
