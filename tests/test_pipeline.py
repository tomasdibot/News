import json
import re

from conftest import NOW
from newsdesk.cluster import cluster
from newsdesk.config import load_config
from newsdesk.edition import build_edition, render
from newsdesk.fetch import upgrade_image
from newsdesk.notify import compose_message
from newsdesk.rank import score_stories, sensational_hits


def by_title(stories, needle):
    return next(s for s in stories if any(needle in a.title for a in s.articles))


def test_opinion_pieces_are_dropped(articles):
    assert not any("Opinion" in a.title for a in articles)


def test_images_extracted_from_every_feed_style(articles):
    imgs = {a.link.rsplit("/", 1)[-1]: a.image for a in articles}
    assert imgs["a1"] == "https://ichef.bbci.co.uk/ace/standard/800/cpsprodpb/abc.jpg"  # thumbnail, upscaled
    assert imgs["b1"].endswith("b1_800.jpg")  # enclosure
    assert imgs["c1"].endswith("c1.jpg")      # <img> inside description
    assert imgs["c3"].endswith("c3.jpg")      # media:content


def test_same_event_is_grouped_across_outlets_and_languages(articles):
    stories = cluster(articles)
    gaza = by_title(stories, "Gaza ceasefire")
    assert set(gaza.outlets) == {"BBC", "DW", "Infobae"}
    inflation = by_title(stories, "INDEC informó")
    assert set(inflation.outlets) == {"BBC", "Infobae", "La Nación"}
    octopus = by_title(stories, "octopus")
    assert octopus.outlets == ["DW"]


def test_corroborated_news_outranks_hype(articles, cfg):
    ranked = score_stories(cluster(articles), cfg, NOW)
    titles = [s.headline.title for s in ranked]
    hype = next(i for i, t in enumerate(titles) if "IMPACTANTE" in t)
    assert hype > 1
    assert ranked[0].outlets and len(ranked[0].outlets) == 3


def test_muted_topics_disappear(articles, cfg):
    ranked = score_stories(cluster(articles), cfg, NOW)
    assert not any("superclásico" in s.headline.title for s in ranked)


def test_local_story_flagged_and_headline_in_reader_language(articles, cfg):
    ranked = score_stories(cluster(articles), cfg, NOW)
    inflation = by_title(ranked, "INDEC informó")
    assert inflation.local
    assert inflation.headline.source.lang == "es"
    assert inflation.topic == "economy"


def test_sensational_detection():
    assert sensational_hits("¡IMPACTANTE! El video viral") >= 2
    assert sensational_hits("Central bank holds interest rates") == 0


def test_build_render_and_message(articles, cfg, tmp_path):
    edition = build_edition(cfg, articles=articles, now=NOW)
    assert edition["top"][0]["image"]
    page = render(edition, cfg, out_dir=tmp_path / "site", data_path=tmp_path / "edition.json")
    html = page.read_text()
    data = json.loads(re.search(r'<script type="application/json" id="nd-data">(.*?)</script>', html, re.S).group(1))
    assert data["t"]["top"] == "Lo más importante" and data["t"]["many"] == "{n} medios"
    concepts = {c["id"] for c in data["themes"]["concepts"]}
    assert {"economy", "world", "sports", "ai", "f1"} <= concepts
    assert "Economía" in data["themes"]["suggested"] and "argentina" in data["themes"]["country_names"]
    first = data["stories"][0]
    assert first["base"] > 0 and "topics" in first and len(first["outlets"]) == 3
    assert json.loads((tmp_path / "edition.json").read_text())["top"]
    assert not (tmp_path / "site" / "edition.json").exists()
    msg = compose_message(edition, cfg, now=NOW)
    assert msg.startswith("*¡Buen día! Tus noticias del jueves 8 de octubre*")
    assert "https://example.github.io/News/" in msg
    assert msg.count("\n1. ") == 1 and "\n4. " not in msg


def test_private_profile_override(monkeypatch):
    monkeypatch.setenv("NEWSDESK_PROFILE", "profile:\n  age: 41\n  country: es\n")
    cfg = load_config()
    assert cfg["profile"]["age"] == 41 and cfg["profile"]["country"] == "ES"
    assert cfg["profile"]["topics"]  # untouched keys survive the merge


def test_bbc_image_upgrade_leaves_others_alone():
    assert upgrade_image("https://example.com/240/x.jpg") == "https://example.com/240/x.jpg"


def test_different_events_with_shared_names_stay_apart():
    from datetime import timedelta

    from conftest import SOURCES
    from newsdesk.fetch import Article

    def art(src, title, summary="", minutes=0):
        return Article(SOURCES[src], title, f"https://x/{src}/{abs(hash(title))}", summary, NOW - timedelta(minutes=minutes))

    stories = cluster([
        art("bbc", "Trump meets Xi in Beijing to discuss trade", "Talks focused on chips."),
        art("infobae", "Trump amenaza a China con nuevos aranceles al acero", "El anuncio fue en Washington.", 5),
        art("dw", "Israel strikes targets in Lebanon", "The army said Hezbollah sites were hit.", 10),
        art("bbc", "Israel and Hamas agree to ceasefire in Gaza", "Egypt and Qatar mediated.", 15),
    ])
    assert len(stories) == 4


def test_installable_on_phone(articles, cfg, tmp_path):
    site = tmp_path / "site"
    render(build_edition(cfg, articles=articles, now=NOW), cfg, out_dir=site, data_path=tmp_path / "e.json")
    manifest = json.loads((site / "manifest.webmanifest").read_text())
    assert manifest["display"] == "standalone" and manifest["start_url"] == "./"
    for icon in manifest["icons"]:
        assert (site / icon["src"]).exists()
    assert "newsdesk-" in (site / "sw.js").read_text()
    html = (site / "index.html").read_text()
    assert 'rel="manifest"' in html and "apple-touch-icon" in html and "viewport-fit=cover" in html


def test_greenapi_sends_photo_to_own_chat(monkeypatch):
    from newsdesk import notify as n

    calls = []

    class Resp:
        status_code = 200
        text = "{}"

    monkeypatch.setattr(n.requests, "post", lambda url, json, timeout: calls.append((url, json)) or Resp())
    monkeypatch.setenv("WHATSAPP_PHONE", "+5491122334455")
    monkeypatch.setenv("GREENAPI_ID_INSTANCE", "1101")
    monkeypatch.setenv("GREENAPI_API_TOKEN", "tok")
    monkeypatch.setenv("GREENAPI_API_URL", "https://7103.api.greenapi.com/")
    n.send_greenapi("hola", "https://img/x.jpg")
    url, body = calls[0]
    assert url == "https://7103.api.greenapi.com/waInstance1101/sendFileByUrl/tok"
    assert body["chatId"] == "5491122334455@c.us" and body["caption"] == "hola"


def test_ads_filler_and_foreign_editions_are_dropped(articles):
    titles = " | ".join(a.title for a in articles)
    assert "ofertas" not in titles and "Horóscopo" not in titles and "Sheinbaum" not in titles


def test_url_section_decides_the_topic(articles, cfg):
    cfg["profile"]["muted_topics"] = []
    ranked = score_stories(cluster(articles), cfg, NOW)
    club = by_title(ranked, "renovación del plantel")
    assert club.topic == "sports"  # despite "presidente" and "gobierno" in the text


def test_exclusion_rules():
    from newsdesk.filters import exclusion_reason, section_topics

    assert exclusion_reason("Así es el nuevo hotel", "https://www.clarin.com/brandstudio/hotel_0_a.html", [], "AR", "AR")
    assert exclusion_reason("Ofertas imperdibles en el Hot Sale", "https://www.clarin.com/sociedad/x.html", [], "AR", "AR")
    assert exclusion_reason("Dólar blue hoy: a cuánto cotiza", "https://www.infobae.com/economia/2026/10/08/x/", [], "AR", "AR")
    assert exclusion_reason("Nota", "https://www.lanacion.com.ar/sociedad/x-nid08102026/", ["Contenido patrocinado"], "AR", "AR")
    # real news that merely contains tricky words stays
    assert not exclusion_reason("El Gobierno lanzó una oferta de canje de deuda", "https://www.infobae.com/economia/2026/10/08/x/", [], "AR", "AR")
    assert not exclusion_reason("Así quedó el sorteo del Mundial 2026", "https://www.clarin.com/deportes/x.html", [], "AR", "AR")
    # other countries' local editions only matter to readers there
    assert exclusion_reason("Plan de seguridad", "https://www.infobae.com/mexico/2026/10/08/x/", [], "AR", "AR")
    assert not exclusion_reason("Plan de seguridad", "https://www.infobae.com/mexico/2026/10/08/x/", [], "MX", "MX")
    assert section_topics("https://www.france24.com/es/econom%C3%ADa/20261008-x") == {"economy"}


def test_headline_cleanup():
    from newsdesk.text import clean_headline as c

    assert c("EN VIVO | Milei habla en el Congreso") == "Milei habla en el Congreso"
    assert c("¡IMPACTANTE! El video viral del cruce") == "El video viral del cruce"
    assert c("El INDEC informó la inflación | Infobae") == "El INDEC informó la inflación"
    assert c("Trump DESTROYS rival in debate") == "Trump destroys rival in debate"
    assert c("¿Qué pasará con el dólar?") == "¿Qué pasará con el dólar?"
