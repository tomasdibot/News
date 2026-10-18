from datetime import timedelta

from conftest import NOW, SOURCES

from newsdesk import importance
from newsdesk.cluster import cluster
from newsdesk.config import Source
from newsdesk.fetch import Article

GOOGLE = b"""<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>El INDEC informo que la inflacion de septiembre fue de 2,1% - Infobae</title><link>https://g/1</link>
<source url="https://infobae.com">Infobae</source></item>
<item><title>Nuevo modelo de IA de OpenAI llega a Argentina - Clarin</title><link>https://g/3</link>
<source url="https://clarin.com">Clarin</source></item>
<item><title>Receta de pan casero en 30 minutos - Clarin</title><link>https://g/4</link>
<source url="https://clarin.com">Clarin</source></item>
</channel></rss>"""

SPANISH = [SOURCES["infobae"], SOURCES["lanacion"], Source(id="clarin", outlet="Clarín", url="x", lang="es", region="AR")]
INFLATION = "El INDEC informo que la inflacion de septiembre fue de 2,1%"


def art(src, title, hours=1):
    return Article(src, title, f"https://x/{abs(hash((src.id, title)))}", "", NOW - timedelta(hours=hours))


def ref(title, lang="es"):
    return Article(Source(id="ref", outlet="ref", url="", lang=lang), title, "https://r/1", "", NOW)


def story(title, hours=1):
    return cluster([art(SPANISH[0], title, hours)])[0]


def test_parse_reference_strips_the_outlet():
    got = importance.parse_reference(GOOGLE, "es", NOW)
    assert got[0].title == INFLATION
    assert [a.source.lang for a in got] == ["es"] * 3


def test_theme_kinds_follow_the_existing_names():
    assert importance.theme_kind("Economía argentina") == "economy"
    assert importance.theme_kind("Noticias del mundo") == "world"
    assert importance.theme_kind("Avances de la IA") == "ai"
    assert importance.theme_kind("Música y shows") == "music"
    assert importance.theme_kind("Fútbol") is None


def test_references_are_filtered_by_subject_and_a_failed_feed_only_lowers_the_count():
    class Resp:
        content = GOOGLE

    refs, label = importance.fetch_references("ai", get=lambda url: 1 / 0 if "techmeme" in url else Resp())
    assert [a.title for a in refs] == ["Nuevo modelo de IA de OpenAI llega a Argentina"]
    assert label == "google"
    assert importance.fetch_references("ai", get=lambda url: 1 / 0) == ([], "")


def test_hits_and_every_miss_reason():
    reserves = "El BCRA compro USD 150 millones y suben las reservas"
    lowrank = "Fuerte caida de las exportaciones de soja en octubre"
    split = "Milei firma el decreto de la reforma laboral en Casa Rosada"
    judged_out = "Venden la mayor empresa textil del pais a un grupo brasileno"
    capped = "Cierra la planta automotriz de Cordoba tras acuerdo sindical"
    lead, low, out, cut = story(INFLATION), story(lowrank), story(judged_out), story(capped)
    twins = [story(split, hours=1), story(split, hours=100)]    # same event, far apart: two stories
    assert len(twins) == 2 and twins[0].articles != twins[1].articles
    filler = [story(f"Noticia distinta {w} sobre {w}{w} del dia", hours=2) for w in "abcdefghij"]
    for i, s in enumerate(filler):
        s.score = 10 - i
    accepted = filler + [low, lead]          # lead has the best rank among equal scores only if confirmed
    lead.score = 99
    low.score = -5
    stories = [lead, low, out, cut, *twins, *filler]
    in_cap = [s for s in stories if s is not cut and s not in twins]
    refs = [ref(INFLATION), ref(reserves), ref(lowrank), ref(split), ref(judged_out), ref(capped)]
    top4, top10, misses = importance.evaluate(refs, stories, stories, in_cap, accepted, need=3)
    assert (top4, top10) == (1, 1)
    assert dict((t, r) for r, t in misses) == {
        reserves: "not fetched", lowrank: "low rank", split: "split",
        judged_out: "judge out", capped: "cut by cap"}


def test_a_second_ranked_story_counts_in_the_top_4():
    a, b = story(INFLATION), story("Fuerte caida de las exportaciones de soja en octubre")
    a.score, b.score = 1, 5
    got = importance.evaluate([ref(INFLATION)], [a, b], [a, b], [a, b], [a, b], need=3)
    assert got == (1, 1, [])


def test_unrelated_headlines_in_another_language_do_not_match():
    s = story(INFLATION)
    top4, top10, misses = importance.evaluate([ref("Brazil central bank holds rates", lang="en")], [s], [s], [s], [s], need=3)
    assert (top4, top10, misses) == (0, 0, [("not fetched", "Brazil central bank holds rates")])


def test_front_page_leads_need_several_outlets_and_the_theme():
    arts = [art(SPANISH[0], INFLATION), art(SPANISH[1], INFLATION + " segun el INDEC"),
            art(SPANISH[0], "Receta de pan casero en 30 minutos"), art(SPANISH[1], "Receta de pan casero en 30 minutos hoy")]
    assert importance.front_page_leads(arts, "economy") == []      # two outlets are not enough
    arts.append(art(SPANISH[2], INFLATION + " en Argentina"))
    assert [a.title for a in importance.front_page_leads(arts, "economy")] == [INFLATION]
    assert importance.front_page_leads(arts, "ai") == []           # right outlets, wrong subject


def test_importance_lines_fall_back_to_leads_when_references_fail():
    arts = [art(SPANISH[0], INFLATION), art(SPANISH[1], INFLATION + " segun el INDEC"),
            art(SPANISH[2], INFLATION + " en Argentina")]
    ss = cluster(arts)
    lines = importance.importance_lines("Economía", ss, ss, ss, ss, ss, arts, get=lambda url: 1 / 0)
    assert lines == ["importance Economía: top4 1/1 top10 1/1 (ref: leads, rank approx.)"]


def test_importance_never_raises():
    lines = importance.importance_lines("Economía", None, None, None, None, None, None, get=lambda url: 1 / 0)
    assert lines == ["importance Economía: unavailable"]


def test_a_cross_language_story_counts_as_a_hit():
    en = "INDEC reports September inflation of 2.1% in Argentina"
    s = cluster([art(SOURCES["bbc"], en)])[0]
    s.score = 1
    got = importance.evaluate([ref("El INDEC informó inflación de 2,1% en Argentina en septiembre")], [s], [s], [s], [s], need=3)
    assert got == (1, 1, [])


def test_two_unrelated_economy_headlines_do_not_match():
    s = story("El dólar blue cierra a la baja en Argentina")
    got = importance.evaluate([ref("Subió la tasa de interés del Banco Central")], [s], [s], [s], [s], need=3)
    assert got[:2] == (0, 0) and got[2][0][0] == "not fetched"


def test_a_story_that_was_never_a_candidate_cut_by_the_cap_or_not_sampled():
    never, cut, sampled = story(INFLATION), story("Fuerte caida de las exportaciones de soja"), story("Venden la mayor empresa textil del pais")
    stories = [never, cut, sampled]
    refs = [ref(INFLATION), ref("Fuerte caida de las exportaciones de soja"), ref("Venden la mayor empresa textil del pais")]
    _, _, misses = importance.evaluate(refs, stories, [cut, sampled], [sampled], [], need=3, judged=[])
    assert [r for r, _ in misses] == ["not a candidate", "cut by cap", "not judged (sample)"]


def test_judge_out_wins_over_split_when_a_hit_was_read():
    title = "Milei firma el decreto de la reforma laboral en Casa Rosada"
    a, b = story(title, hours=1), story(title, hours=100)
    assert importance.evaluate([ref(title)], [a, b], [a, b], [a, b], [], need=3)[2][0][0] == "judge out"
    assert importance.evaluate([ref(title)], [a, b], [], [], [], need=3)[2][0][0] == "split"


def feed(*items):
    body = "".join(f"<item><title>{t}</title><link>https://g/{i}</link>{f'<source url=\"https://x\">{o}</source>' if o else ''}"
                   f"<pubDate>Thu, 08 Oct 2026 11:00:00 GMT</pubDate></item>" for i, (t, o) in enumerate(items))
    return f'<?xml version="1.0"?><rss version="2.0"><channel>{body}</channel></rss>'.encode()


class Resp:
    def __init__(self, content):
        self.content = content


def test_junk_reference_items_are_dropped_and_counted():
    junk = ["Dólar hoy - Video - Infobae", "Mercados (audio) - Clarin", "EN VIVO: la sesión", "Quiniela de hoy",
            "Horóscopo de hoy", "Minuto a minuto del dólar", "El clima en Buenos Aires"]
    good = "El INDEC informo que la inflacion de septiembre fue de 2,1%"
    got = Resp(feed(*[(t, None) for t in junk], (good, "Infobae")))
    refs, label, dropped = importance._fetch("economy", lambda url: got, NOW)
    assert [a.title for a in refs] == [good] and dropped == len(junk)


def test_real_news_with_junk_looking_words_is_kept():
    keep = ["Cumbre del clima: acuerdo de la COP", "El clima de tensión en el Congreso", "Pronóstico de crecimiento del FMI para 2027",
            "Duki en vivo en el Estadio Vélez"]
    assert not any(importance.is_junk(t) for t in keep)
    assert all(importance.is_junk(t) for t in ["Dólar hoy - Video", "Mercados (audio)", "EN VIVO: la sesión",
                                              "Horóscopo de hoy", "El clima en Buenos Aires", "Pronóstico del tiempo"])


def test_artists_without_any_news_say_so_instead_of_falling_back():
    got = importance.importance_lines("Música", [], [], [], [], [], [], artists=["Duki"], get=lambda url, timeout=None: Resp(feed()))
    assert got == ["importance Música: no artist references"]


def test_music_reference_is_the_news_of_your_artists_one_each_from_the_last_two_days():
    def get(url, timeout=None):
        assert "Duki" in url and "when:2d" in url or "Wos" in url
        name = "Duki" if "Duki" in url else "Wos"
        return Resp(feed((f"{name} anuncia show en Buenos Aires - Rolling Stone", "Rolling Stone"),
                         (f"{name} lanza disco nuevo - Clarin", "Clarin")))
    refs, label, _ = importance._fetch("music", get, NOW, artists=["Duki", "Wos"])
    assert [a.title for a in refs] == ["Duki anuncia show en Buenos Aires", "Wos anuncia show en Buenos Aires"]
    assert label == "artists (self-check)"


def test_music_without_artists_is_skipped():
    assert importance.importance_lines("Música", [], [], [], [], [], [], artists=[]) == \
        ["importance Música: skipped (no artists)"]


def test_every_miss_is_printed_with_reasons_and_the_outlets_google_names():
    titles = [f"Noticia economica numero {w} sobre {w}{w}{w} del dia" for w in "abcdefg"]
    got = Resp(feed(*[(f"{t} - {'Ambito' if i < 5 else 'Infobae'}", "Ambito" if i < 5 else "Infobae")
                      for i, t in enumerate(titles)]))
    lines = importance.importance_lines("Economía", [], [], [], [], [], [], get=lambda url: got)
    misses = [l for l in lines if l.startswith("  miss:")]
    assert len(misses) == 7
    assert misses[0] == f"  miss: not fetched — {titles[0]} [Ambito]"
    assert "reasons Economía: not fetched 7" in lines
    assert "missing outlets Economía: Ambito 5, Infobae 2" in lines


def test_outlet_comes_from_the_title_suffix_when_there_is_no_source_element():
    refs = importance.parse_reference(feed(("Fuerte caida de las exportaciones - La Nacion", None)), "es", NOW)
    assert refs[0].title == "Fuerte caida de las exportaciones" and refs[0].outlet == "La Nacion"
