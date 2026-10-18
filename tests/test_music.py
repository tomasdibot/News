"""Música: your artists first, then shows, then releases; and how many outlets confirm a story."""
from datetime import datetime, timezone

import pytest
from conftest import NOW, SOURCES

from newsdesk import judge
from newsdesk.artists import SHOW_QUERIES, parse_shows, show_search_url
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
    assert (d["artist"], d["mtier"]) == (None, 1)


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


RSS = """<?xml version="1.0"?><rss><channel>
<item><title>Coldplay confirma recital en Buenos Aires - Clarín</title><link>https://n/1</link>
  <pubDate>Mon, 12 Oct 2026 10:00:00 GMT</pubDate><source url="https://clarin.com">Clarín</source></item>
<item><title>Gira del presidente por Argentina: agenda oficial - Infobae</title><link>https://n/2</link>
  <pubDate>Mon, 12 Oct 2026 10:00:00 GMT</pubDate><source url="https://infobae.com">Infobae</source></item>
<item><title>Se agotaron las entradas del concierto en Buenos Aires - La Nación</title><link>https://n/3</link>
  <pubDate>Mon, 12 Oct 2026 10:00:00 GMT</pubDate><source url="https://lanacion.com.ar">La Nación</source></item>
<item><title>Detienen a una banda narco en Rosario - Clarín</title><link>https://n/4</link>
  <pubDate>Mon, 12 Oct 2026 10:00:00 GMT</pubDate><source url="https://clarin.com">Clarín</source></item>
<item><title>Obras en el estadio de River - Infobae</title><link>https://n/5</link>
  <pubDate>Mon, 12 Oct 2026 10:00:00 GMT</pubDate><source url="https://infobae.com">Infobae</source></item>
</channel></rss>""".encode()


def test_show_queries_keep_the_publisher_and_need_a_music_word_in_the_headline():
    got = parse_shows(RSS, datetime(2026, 10, 13, tzinfo=timezone.utc))
    assert [(a.outlet, a.title) for a in got] == [
        ("Clarín", "Coldplay confirma recital en Buenos Aires"),
        ("La Nación", "Se agotaron las entradas del concierto en Buenos Aires"),
    ]
    assert all(a.source.topics == ["culture"] for a in got)


def test_show_queries_use_the_argentine_edition_and_last_week():
    assert len(SHOW_QUERIES) >= 9
    for q in ["festival música Argentina", "entradas a la venta show", "gira 2026 Argentina",
              "show en Córdoba", "show en Rosario"]:
        assert q in SHOW_QUERIES
    url = show_search_url(SHOW_QUERIES[0])
    assert "gl=AR" in url and "when:14d" in url and "gira" in url


def test_show_queries_keep_articles_up_to_two_weeks_old_but_artist_news_stays_at_one():
    from newsdesk.artists import parse_search
    rss = RSS.replace(b"Mon, 12 Oct 2026", b"Wed, 07 Oct 2026")   # 8 days before "now"
    now = datetime(2026, 10, 15, tzinfo=timezone.utc)
    assert len(parse_shows(rss, now)) == 2
    assert parse_search(rss, "Coldplay", "es", now) == []


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


def test_show_and_artist_articles_outlive_the_normal_age_limit_but_normal_ones_do_not(cfg):
    from datetime import timedelta
    from newsdesk.artists import parse_search
    from newsdesk.cluster import cluster
    from newsdesk.judge import candidates
    from newsdesk.rank import score_stories
    five_days = NOW - timedelta(days=5)
    rss = RSS.replace(b"Mon, 12 Oct 2026 10:00:00", b"Fri, 03 Oct 2026 12:00:00")
    shows = parse_shows(rss, NOW)
    lali = parse_search(b"""<rss><channel><item><title>Lali anuncia recital - Clarin</title><link>https://n/9</link>
      <pubDate>Fri, 03 Oct 2026 12:00:00 GMT</pubDate><source url="https://clarin.com">Clarin</source></item></channel></rss>""",
                        "Lali", "es", NOW)
    assert shows and lali
    old_normal = Article(SOURCES["infobae"], "Nuevo recital de Lali en el Luna Park", "https://x/old", "", five_days)
    kept = score_stories(cluster(shows + lali + [old_normal]), cfg, NOW)
    titles = {a.title for s in kept for a in s.articles}
    assert "Coldplay confirma recital en Buenos Aires" in titles and "Lali anuncia recital" in titles
    assert old_normal.title not in titles
    assert any("Coldplay" in s.headline.title for s in candidates("Música: shows", kept))


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
    assert "gnews fallback:" in caplog.text and "artist +" in caplog.text
    # once the stored articles are older than their limits, nothing is reused
    assert A.fetch_google_news(["Tame Impala"], now + timedelta(days=30), cache) == []
    # no cache, no results
    assert A.fetch_google_news(["Tame Impala"], now, tmp_path / "none.json") == []


def test_google_news_fallback_works_per_list_and_only_for_current_artists(tmp_path, monkeypatch, caplog):
    import logging
    from datetime import datetime, timedelta, timezone
    from newsdesk import artists as A
    now = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)
    when = (now - timedelta(days=1)).strftime('%a, %d %b %Y %H:%M:%S GMT')
    item = lambda t: (f"<item><title>{t} - Rolling Stone</title><link>https://x/{t.replace(' ', '')}</link>"
                      f"<source url='https://rs'>Rolling Stone</source><pubDate>{when}</pubDate></item>")
    feed = lambda t: ("<rss><channel>" + item(t) + "</channel></rss>").encode()

    class R:
        def __init__(self, c): self.content = c

    def serve(show=True, artist=True):
        def get(url, *a, **k):
            if "when:14d" in url and show:
                return R(feed("Gran festival de rock en Rosario"))
            if "when:7d" in url and artist:
                name = "Tame Impala" if "Tame" in url else "Soda Stereo"
                return R(feed(f"{name} anuncia show en Buenos Aires"))
            raise RuntimeError("503")
        monkeypatch.setattr(A, "_get", get)

    cache = tmp_path / "c.json"
    serve()
    A.fetch_google_news(["Tame Impala", "Soda Stereo"], now, cache)
    serve(artist=False)   # artists down, shows fine: the stored artist items come back next to the live shows
    part = A.fetch_google_news(["Tame Impala", "Soda Stereo"], now, cache)
    assert sum(1 for a in part if a.query) == 2 and any("festival" in a.title for a in part)
    serve(show=False, artist=False)   # full outage: the artist items survived the partial one
    with caplog.at_level(logging.INFO):
        full = A.fetch_google_news(["Tame Impala"], now, cache)   # Soda Stereo was removed from the list
    assert [a.query for a in full if a.query] == ["tame impala"]
    assert any("festival" in a.title for a in full)
    assert "gnews fallback: 1 artist + 1 show" in caplog.text
