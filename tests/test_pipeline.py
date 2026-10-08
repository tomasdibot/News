import json

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
    assert "Lo más importante" in html and "3 medios" in html
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
