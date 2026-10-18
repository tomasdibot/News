"""Different events must not be shown together, even when headlines chain through shared names."""
from datetime import datetime, timedelta, timezone

import pytest

from newsdesk.cluster import _merge_repeats, cluster
from newsdesk.config import Source
from newsdesk.edition import story_dict
from newsdesk.fetch import Article

T0 = datetime(2026, 10, 14, 12, tzinfo=timezone.utc)


def _art(outlet, title, i, lang="es", region="AR"):
    src = Source(id=outlet, outlet=outlet, url="x", lang=lang, region=region)
    return Article(source=src, title=title, link=f"https://x/{i}", summary="", published=T0 + timedelta(minutes=i))


# set name -> [(outlet, title, event id)]
RAW = {
"chain-milei": [("Clarín", "Milei anunció la baja de retenciones al trigo y la cebada", 0),
    ("Infobae", "Milei anunció la baja de retenciones al trigo y la cebada en Rosario", 0),
    ("La Nación", "Milei anunció en Rosario un acto con gobernadores y empresarios", 1),
    ("Página/12", "Milei encabezó en Rosario un acto con gobernadores sin Kicillof", 1)],
"chain-boca": [("Clarín", "Boca presentó a su nuevo técnico en La Bombonera", 0),
    ("Infobae", "Boca presentó a su nuevo técnico: cómo será el plantel en La Bombonera", 0),
    ("La Nación", "Cómo será el plantel de Boca y River para el Superclásico en La Bombonera", 1),
    ("Ámbito", "River prepara el Superclásico: el plantel para visitar La Bombonera", 1)],
"chain-artist": [("Clarín", "Dua Lipa confirmó show en River Plate: precio de entradas", 0),
    ("Infobae", "Dua Lipa en River: precio de entradas y fecha de venta", 0),
    ("Indie Hoy", "Entradas para River Plate: cuándo salen para Coldplay y otros shows", 1),
    ("Perfil", "Coldplay vuelve a River Plate: fechas, entradas y shows confirmados", 1)],
"first-word": [("Clarín", "Cristina Kirchner habló en el acto del PJ por el Día de la Lealtad", 0),
    ("Infobae", "Cristina Kirchner presentó un libro en Mendoza con críticas al Gobierno", 1),
    ("La Nación", "Cristina Kirchner: la Corte rechazó su pedido para levantar la prisión domiciliaria", 2),
    ("Ámbito", "Cristina Kirchner reclamó por su situación judicial", 2)],
"year-2026": [("Clarín", "Mundial 2026: Argentina sorteó su grupo y conoce a sus rivales", 0),
    ("Infobae", "Mundial 2026: las entradas ya tienen precios y fechas de venta", 1),
    ("La Nación", "Mundial 2026: cuánto cobrará cada jugador de la Selección", 2),
    ("Ámbito", "Mundial 2026: el fixture completo de Argentina", 3)],
"caputo": [("Clarín", "Caputo anunció medidas para bajar la inflación", 0),
    ("Infobae", "Caputo anunció medidas para el campo y las exportaciones", 1),
    ("La Nación", "Caputo anunció una reunión con el FMI en Washington", 2)],
}
# The owner's example: three events, English, artist-search style sources, one name shared by two.
OWNER = [("TicketNews", "Tame Impala tickets on sale in Montreal at Centre Bell", 0),
         ("Northern Transmissions", "Tame Impala announces new 2026 Tour Dates", 1),
         ("RTTNews", "Erykah Badu Cancels Several European Tour Dates Due To 'Unforeseen Circumstances'", 2)]


def _arts(rows, lang="es"):
    return [_art(o, t, i, lang=lang) for i, (o, t, _) in enumerate(rows)]


def _wrong_pairs(groups, gold):
    return sum(1 for g in groups for x in g for y in g if x < y and gold[x] != gold[y])


def _shown_groups(arts):
    """Per story, the indexes of the articles displayed as outlet rows."""
    from newsdesk.rank import pick_headline
    index = {a.link: i for i, a in enumerate(arts)}
    out = []
    for s in cluster(arts):
        s.headline = pick_headline(s, "es")
        out.append([index[a.link] for a in s.sources_for_display()])
    return out


def test_chain_sets_show_few_wrong_pairs():
    wrong = 0
    for rows in RAW.values():
        gold = [g for *_, g in rows]
        wrong += _wrong_pairs(_shown_groups(_arts(rows)), gold)
    assert wrong <= 8, f"{wrong} wrong pairs shown"  # single-link clustering gave 24


@pytest.mark.parametrize("name", list(RAW))
def test_chain_set_never_clusters_distant_events(name):
    rows = RAW[name]
    gold = [g for *_, g in rows]
    arts = _arts(rows)
    index = {a.link: i for i, a in enumerate(arts)}
    groups = [[index[a.link] for a in s.articles] for s in cluster(arts)]
    assert _wrong_pairs(groups, gold) <= 4


def test_owner_example_three_events_never_shown_together():
    arts = _arts(OWNER, lang="en")
    for g in _shown_groups(arts):
        assert len(g) == 1, f"shown together: {g}"


def test_owner_example_story_dict_lists_one_outlet_each():
    arts = _arts(OWNER, lang="en")
    from newsdesk.rank import pick_headline
    for s in cluster(arts):
        s.headline = pick_headline(s, "en")
        s.topic_scores = {}
        d = story_dict(s, "en")
        assert [x["outlet"] for x in d["sources"]] == d["outlets"] == [s.headline.outlet]


def test_outlet_row_is_the_article_closest_to_the_lead():
    a = _art("Clarín", "El INDEC informó que la inflación de septiembre fue de 1,9%", 0)
    early = _art("Infobae", "Inflación: qué dijo Caputo sobre el dólar y las tasas", 1)
    close = _art("Infobae", "Inflación de septiembre: el INDEC informó que fue de 1,9%", 2)
    from newsdesk.cluster import Story, features
    s = Story(articles=[a, early, close], feats=[features(x) for x in (a, early, close)])
    s.headline = a
    shown = {x.outlet: x for x in s.sources_for_display()}
    assert shown["Infobae"] is close
    assert s.outlets == ["Clarín", "Infobae"]


def test_dissimilar_outlet_rows_are_dropped_and_counts_follow():
    from newsdesk.cluster import Story, features
    a = _art("Clarín", "El INDEC informó que la inflación de septiembre fue de 1,9%", 0)
    b = _art("Infobae", "Inflación de septiembre: el INDEC informó que fue de 1,9%", 1)
    c = _art("Ámbito", "Boca presentó a su nuevo técnico en La Bombonera", 2)
    s = Story(articles=[a, b, c], feats=[features(x) for x in (a, b, c)])
    s.headline = a
    assert s.outlets == ["Clarín", "Infobae"]
    assert [x.outlet for x in s.sources_for_display()] == ["Clarín", "Infobae"]


def test_multi_outlet_sample_logs_each_outlets_own_title(caplog):
    import logging
    from newsdesk.cluster import Story, features
    from newsdesk.edition import log_multi_outlet_sample
    arts = [_art("Clarín", "El INDEC informó que la inflación de septiembre fue de 1,9%", 0),
            _art("Infobae", "Inflación de septiembre: el INDEC informó que fue de 1,9%", 1)]
    s = Story(articles=arts, feats=[features(a) for a in arts])
    s.headline = arts[0]
    with caplog.at_level(logging.INFO):
        log_multi_outlet_sample([s])
    assert "Infobae(?): Inflación de septiembre: el INDEC informó que fue de 1,9%" in caplog.text


def test_a_name_counts_once_and_generic_tour_words_are_not_names():
    from newsdesk.text import entities, name_phrases
    t = "Tame Impala announces new 2026 Tour Dates"
    ents = entities(t, None)
    assert "tour" not in ents and "dates" not in ents
    assert name_phrases(t, ents) == [frozenset({"tame", "impala"})]


def test_items_from_the_same_artist_search_share_no_name_bonus():
    from newsdesk.cluster import features, similarity
    a = _art("Rolling Stone", "Tool anuncia gira por Sudamérica con fecha en Buenos Aires", 0, lang="es")
    b = _art("Infobae", "Tool lanza video nuevo con Maynard James Keenan", 1, lang="es")
    free = similarity(features(a), features(b))
    a.query = b.query = "tool"
    assert similarity(features(a), features(b)) < free


def test_multi_outlet_sample_also_logs_up_to_five_non_local_stories(caplog):
    import logging
    from newsdesk.cluster import Story, features
    from newsdesk.edition import log_multi_outlet_sample
    stories = []
    for k in range(7):
        arts = [_art("Clarín", f"Tema{k} uno dos tres cuatro", 2 * k), _art("Infobae", f"Tema{k} uno dos tres cuatro", 2 * k + 1)]
        s = Story(articles=arts, feats=[features(a) for a in arts])
        s.headline = arts[0]
        stories.append(s)
    with caplog.at_level(logging.INFO):
        log_multi_outlet_sample(stories)
    assert caplog.text.count("multi-outlet sample:") == 5


def _later(outlet, title, i, hours, lang="en"):
    a = _art(outlet, title, i, lang=lang)
    a.published = T0 + timedelta(hours=hours)
    return a


def test_second_pass_merges_the_same_event_reported_days_apart(caplog):
    import logging
    badu = [_later("TicketNews", "Erykah Badu cancels 5 European shows due to 'unforeseen circumstances'", 0, 0),
            _later("RTTNews", "Erykah Badu Cancels Several European Tour Dates Due To 'Unforeseen Circumstances'", 1, 50)]
    bts = [_later("Billboard", "BTS announce 2027 world tour with Buenos Aires stadium show", 2, 0),
           _later("Rolling Stone", "BTS world tour 2027 dates, tickets and stadium shows in Buenos Aires confirmed", 3, 55)]
    with caplog.at_level(logging.INFO):
        stories = cluster(badu + bts)
    assert sorted(len(s.articles) for s in stories) == [2, 2]
    assert [sorted(s.outlets) for s in stories if "Badu" in s.articles[0].title] == [["RTTNews", "TicketNews"]]
    assert "second-pass merges: 2" in caplog.text and "Erykah Badu" in caplog.text


def test_second_pass_keeps_distant_or_different_stories_apart():
    far = [_later("A", "Erykah Badu cancels 5 European shows", 0, 0),
           _later("B", "Erykah Badu Cancels Several European Tour Dates", 1, 100)]      # more than 72 h apart
    other = [_later("A", "Erykah Badu cancels 5 European shows", 2, 0),
             _later("B", "Tame Impala announces new 2026 Tour Dates", 3, 50)]
    cross = [_later("A", "Erykah Badu cancels 5 European shows", 4, 0, "en"),
             _later("B", "Erykah Badu cancela cinco shows en Europa", 5, 50, "es")]
    for arts in (far, other, cross):
        assert len(cluster(arts)) == 2


def test_second_pass_skips_index_keys_shared_by_many_stories(monkeypatch):
    import newsdesk.cluster as c
    def word(n, k):   # letters only, unique per (story, slot)
        return "".join(chr(97 + (n * 31 + k * 7) // 26 ** j % 26) for j in range(4)) + "qz"
    arts = [_later("A", f"{word(n, 1)} {word(n, 2)} {word(n, 3)} {word(n, 4)}", n, 0) for n in range(60)]
    stories = cluster(arts)
    assert len(stories) == 60
    calls = []
    real = c.similarity
    monkeypatch.setattr(c, "similarity", lambda f, g: calls.append(1) or real(f, g))
    c._merge_repeats(stories, {"common": set(range(60))})      # one key shared by 60 stories (> 50): ignored
    assert calls == []
    c._merge_repeats(stories, {"common": set(range(10))})      # a small group is still compared
    assert len(calls) == 45


def test_second_pass_keeps_short_template_titles_apart():
    stories = [cluster([_later("A", "Finance workflows with ChatGPT Work", 0, 0, "en")])[0],
               cluster([_later("B", "Operations workflows with ChatGPT Work", 1, 5, "en")])[0]]
    assert len(_merge_repeats(stories, {"workf": {0, 1}})) == 2


def test_second_pass_still_merges_the_f1_rwanda_pair():
    stories = [cluster([_later("A", "Formula 1: Rwanda to bring sport back to Africa", 0, 0, "en")])[0],
               cluster([_later("B", "Formula One in Rwanda: Sportswashing claims vs. hopes for African legacy", 1, 5, "en")])[0]]
    assert len(_merge_repeats(stories, {"rwand": {0, 1}})) == 1
