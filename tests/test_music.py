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
    ("Se presenta en Luna Park y River el sábado", 3),
    ("Tour por Argentina de una banda", 1),
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
    assert len(SHOW_QUERIES) >= 4
    url = show_search_url(SHOW_QUERIES[0])
    assert "gl=AR" in url and "when:7d" in url and "gira" in url
