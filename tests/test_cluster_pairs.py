"""Headline-pair fixture for cross-outlet clustering of Argentine news (titles only, as in gnews items)."""
from datetime import datetime, timedelta, timezone

import pytest

from newsdesk.cluster import SAME_LANG_THRESHOLD, cluster, features, similarity
from newsdesk.config import Source
from newsdesk.fetch import Article
from newsdesk.text import entities, tokens

T0 = datetime(2026, 10, 14, 12, tzinfo=timezone.utc)


def _src(outlet):
    return Source(id=outlet, outlet=outlet, url="x", lang="es", region="AR")


def _art(outlet, title, i, summary=""):
    return Article(source=_src(outlet), title=title, link=f"https://x/{i}", summary=summary,
                   published=T0 + timedelta(minutes=i))


def _merges(oa, ta, ob, tb):
    fa, fb = features(_art(oa, ta, 0)), features(_art(ob, tb, 1))
    return similarity(fa, fb) >= SAME_LANG_THRESHOLD


# (outletA, titleA, outletB, titleB)
SAME = [
("Clarín","La inflación de septiembre fue 1,9%, la más baja del año, según el INDEC","Infobae","El INDEC informó que la inflación de septiembre fue de 1,9%"),
("Página/12","Inflación de septiembre: 1,9% mensual y acumulado del 24,1% en el año","La Nación","Inflación de septiembre: el IPC marcó 1,9% y el Gobierno lo celebró"),
("Clarín","El riesgo país cayó a 648 puntos y marcó el nivel más bajo en meses","Ámbito","Riesgo país: bajó a 648 puntos básicos tras el anuncio del Tesoro"),
("Infobae","Milei anunció la eliminación de retenciones al trigo y la cebada","Página/12","Milei oficializó baja de retenciones para el agro: trigo y cebada"),
("La Nación","Milei viajará a Estados Unidos para reunirse con Trump y Bessent","Clarín","Javier Milei viaja a Washington: se reunirá con Donald Trump"),
("Clarín","El dólar blue subió $20 y cerró a $1555","Ámbito","Dólar blue hoy: cerró a $1.555 tras una suba de $20"),
("Infobae","Paro de la CGT: cómo funcionará el transporte este jueves","Página/12","La CGT confirmó el paro general del jueves: qué servicios funcionan"),
("La Nación","Boca venció a Racing 2-1 con un gol en el final","Clarín","Boca le ganó a Racing por 2 a 1 con gol agónico"),
("Infobae","Detuvieron al sospechoso del crimen del kiosquero en La Matanza","Clarín","Crimen del kiosquero en La Matanza: detienen a un sospechoso"),
("Página/12","Diputados aprobó la reforma laboral tras una sesión maratónica","La Nación","La Cámara de Diputados dio media sanción a la reforma laboral"),
("Clarín","El FMI aprobó el desembolso de 1.000 millones de dólares para la Argentina","Infobae","FMI: el Directorio aprobó un giro de USD 1.000 millones para el país"),
("Ámbito","El Banco Central compró US$ 150 millones y acumula reservas récord","Infobae","El BCRA compró 150 millones de dólares en el mercado"),
("La Nación","Murió el actor Federico Luppi a los 85 años","Página/12","Falleció Federico Luppi, figura del cine argentino"),
("Clarín","Alerta amarilla por tormentas en Buenos Aires y el conurbano","Infobae","Tormentas en el AMBA: el SMN emitió alerta amarilla para este martes"),
("Infobae","Caputo anunció nuevas medidas para bajar la inflación y atraer inversiones","Clarín","Luis Caputo presentó medidas económicas: qué cambia para las inversiones"),
]
DIFF = [
("Clarín","La inflación de septiembre fue 1,9% según el INDEC","Infobae","La inflación de agosto fue 2,1% según el INDEC"),
("Clarín","El INDEC informó que la desocupación fue de 6,8% en el segundo trimestre","Infobae","El INDEC informó que la pobreza bajó al 31,6% en el primer semestre"),
("Infobae","Milei anunció la baja de retenciones al trigo","Clarín","Milei anunció un nuevo gabinete con cambios en Justicia"),
("La Nación","Boca venció a Racing 2-1","Clarín","River venció a Racing 2-1"),
("Infobae","El riesgo país cayó a 648 puntos","Clarín","El riesgo país subió a 720 puntos"),
("Clarín","Detuvieron a un sospechoso por el crimen en Rosario","Infobae","Detuvieron a un sospechoso por el crimen en Córdoba"),
("Infobae","El dólar blue subió $20 y cerró a $1555","Clarín","El dólar oficial subió $20 y cerró a $1535"),
("Clarín","Tormentas en Buenos Aires: alerta amarilla para el martes","Infobae","Tormentas en Mendoza: alerta amarilla para el miércoles"),
("La Nación","Diputados aprobó la reforma laboral","Página/12","Senado aprobó la reforma tributaria"),
("Clarín","Milei viajará a Estados Unidos para reunirse con Trump","Infobae","Milei viajará a Italia para reunirse con Meloni"),
]


def test_same_event_pairs_mostly_merge():
    merged = sum(_merges(*p) for p in SAME)
    # Names count once ("Federico Luppi" is one name), so 3 paraphrased pairs (BCRA/Banco Central,
    # Luppi murió/falleció, alerta/tormentas) split: wrong merges matter more than paraphrase recall.
    assert merged >= 12, f"{merged}/15 same-event pairs merged"


def test_different_event_pairs_rarely_merge():
    wrong = sum(_merges(*p) for p in DIFF)
    assert wrong <= 4, f"{wrong}/10 different-event pairs merged"


@pytest.mark.parametrize("pair", [DIFF[0], DIFF[4], DIFF[6]], ids=["indec-sep-vs-aug", "riesgo-648-vs-720", "blue-vs-oficial"])
def test_conflicting_figures_never_merge(pair):
    assert not _merges(*pair)


def test_figures_are_one_key_across_formats():
    assert tokens("inflación de 1,9%") == tokens("inflación de 1.9%")
    assert tokens("inflación de 1,9%") != tokens("inflación de 2,1%")
    assert tokens("cerró a $1.555") == tokens("cerró a 1555")
    assert entities("cerró a $1.555") == entities("cerró a 1555")


def test_single_digits_are_not_tokens():
    assert tokens("ganó 2 a 1") == tokens("ganó")


def test_first_word_name_counts_when_summary_is_empty():
    assert "cuadernos" in entities("Cuadernos declaró el empresario", None)
    assert "cuadernos" not in entities("Cuadernos declaró el empresario", "Habló en tribunales")  # summary exists, name absent


def test_features_of_summaryless_article_use_first_word():
    assert "cuadernos" in features(_art("Clarín", "Cuadernos declaró el empresario", 0)).title_ents


def test_cluster_groups_three_outlets_on_same_indec_figure():
    arts = [
        _art("Clarín", SAME[0][1], 0),
        _art("Infobae", SAME[0][3], 1),
        _art("La Nación", "Inflación de septiembre: 1,9%, la más baja del año, informó el INDEC", 2),   # close to the lead
        _art("Ámbito", "El INDEC informó que la desocupación fue de 6,8% en el segundo trimestre", 3),
    ]
    stories = cluster(arts)
    sizes = sorted(len(s.outlets) for s in stories)
    assert sizes == [1, 3]
    big = max(stories, key=lambda s: len(s.outlets))
    assert set(big.outlets) == {"Clarín", "Infobae", "La Nación"}


@pytest.mark.parametrize("pair", [
    ("Clarín", "Boca ganó", "Infobae", "Boca perdió"),
    ("Clarín", "Dólar hoy", "Infobae", "Dólar hoy: cuánto cotiza en Mendoza"),
], ids=["boca-ganó-perdió", "dolar-hoy-short"])
def test_very_short_headlines_do_not_merge_on_overlap(pair):
    assert not _merges(*pair)


def test_close_figures_still_match():
    assert _merges("Clarín", "Dólar blue cerró a $1.555", "Ámbito", "Dólar blue hoy: cerró a $1.560")
