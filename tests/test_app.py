"""The app in a real (headless) browser: choosing themes, tabs, swiping, opening a story."""
import functools
import http.server
import json
import os
import threading

import pytest

from conftest import NOW
from newsdesk.edition import build_edition, render

THEMES = {"v": 2, "themes": ["Economía argentina", "Mundo", "Ciencia"], "local": True}


@pytest.fixture
def site(articles, cfg, tmp_path, monkeypatch):
    monkeypatch.delenv("NEWSDESK_PASSWORD", raising=False)
    render(build_edition(cfg, articles=articles, now=NOW), cfg, out_dir=tmp_path / "site", data_path=tmp_path / "e.json")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(tmp_path / "site"))
    handler.log_message = lambda *a: None
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://localhost:{server.server_address[1]}/"
    server.shutdown()


@pytest.fixture
def browser():
    sync_api = pytest.importorskip("playwright.sync_api")
    exe = "/opt/pw-browsers/chromium" if os.path.exists("/opt/pw-browsers/chromium") else None
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch(executable_path=exe)
        except Exception as exc:
            pytest.skip(f"no browser available: {exc}")
        yield b
        b.close()


def open_app(browser, url, prefs=None):
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
    if prefs:
        ctx.add_init_script("if (!localStorage.getItem('newsdesk-prefs-v2')) "
                            f"localStorage.setItem('newsdesk-prefs-v2', {json.dumps(json.dumps(prefs))})")
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(url)
    page.wait_for_selector(".tab")
    page.errors = errors
    return page


@pytest.fixture
def app(site, browser):
    page = open_app(browser, site, THEMES)
    yield page
    assert not page.errors, page.errors


def tab_names(page):
    return page.eval_on_selector_all(".tab", "els => els.map(e => e.title || e.textContent)")


def panel_text(page, name):
    return page.text_content(f"#panel-{tab_names(page).index(name)}")


def test_first_run_asks_for_themes_and_builds_tabs(site, browser):
    page = open_app(browser, site)
    assert page.is_visible("#setdlg")               # asked straight away
    assert tab_names(page) == ["Lo más importante", "Tu país"]
    page.fill("#newtheme", "economía argentina")
    page.press("#newtheme", "Enter")
    assert page.locator("#pick option").count() > 40      # every known theme is in the list
    page.select_option("#pick", "Ciencia")
    assert page.locator('#pick option[value="Ciencia"]').is_disabled()   # can't add it twice
    assert page.input_value("#pick") == ""
    page.fill("#newtheme", "octopus")
    page.click("#addform button")
    assert "1 noticia ahora" in page.text_content("#tlist")
    page.click("#setsave")
    assert tab_names(page) == ["Lo más importante", "Tu país", "Economía argentina", "Ciencia", "Octopus"]
    assert "INDEC" in panel_text(page, "Economía argentina")
    assert "Gaza" not in panel_text(page, "Economía argentina")
    assert "octopus" in panel_text(page, "Octopus")
    page.reload()
    page.wait_for_selector(".tab")
    assert not page.is_visible("#setdlg")           # remembered on this device
    assert tab_names(page)[2] == "Economía argentina"
    assert not page.errors, page.errors


def test_themes_are_understood_in_either_language(site, browser):
    page = open_app(browser, site, {"v": 2, "themes": ["Medio Oriente", "Inflation"], "local": False})
    assert tab_names(page) == ["Lo más importante", "Medio Oriente", "Inflation"]
    assert "Gaza" in panel_text(page, "Medio Oriente") and "INDEC" not in panel_text(page, "Medio Oriente")
    assert "INDEC" in panel_text(page, "Inflation")


def test_tapping_a_tab_shows_that_section(app):
    app.click("text=Ciencia")
    i = tab_names(app).index("Ciencia")
    app.wait_for_function(f"Math.abs(pager.scrollLeft - {i} * pager.clientWidth) < 2")
    assert app.text_content('.tab[aria-selected="true"]') == "Ciencia"


def test_swiping_changes_tab(app):
    app.evaluate("pager.scrollTo({left: 2 * pager.clientWidth})")
    app.wait_for_function("document.querySelector('.tab[aria-selected=\"true\"]').textContent === 'Economía argentina'")
    app.evaluate("pager.scrollTo({left: 0})")
    app.wait_for_function("document.querySelector('.tab[aria-selected=\"true\"]').textContent === 'Lo más importante'")


def test_story_opens_with_sources(app):
    card = app.locator("#panel-0 .card").first
    assert not card.locator(".more").is_visible()
    card.locator(".row").click()
    assert card.locator(".more").is_visible()
    assert card.locator(".srcs a").count() == 3 and card.locator("a.read").is_visible()


def test_reorder_and_remove_themes(app):
    app.click("#gear")
    app.click('#tlist li[data-i="2"] .up')            # Ciencia above Mundo
    app.click('#tlist li[data-i="0"] .rm')            # drop Economía argentina
    app.click("#setsave")
    assert tab_names(app) == ["Lo más importante", "Tu país", "Ciencia", "Mundo"]


@pytest.fixture
def ai_site(articles, cfg, tmp_path, monkeypatch):
    from datetime import timedelta

    from conftest import SOURCES
    from newsdesk.fetch import Article

    def art(src, title, summary, h):
        return Article(SOURCES[src], title, f"https://x/{abs(hash(title))}", summary, NOW - timedelta(hours=h))

    extra = [
        art("bbc", "OpenAI launches GPT-6 model for businesses", "The artificial intelligence company announced it.", 1),
        art("dw", "Teachers worry about AI use in school homework", "Parents debate artificial intelligence at home.", 2),
        art("bbc", "Candidate wins 229 votes in Huanuco election", "Results announced. Written with AI help.", 1),
        art("dw", "OpenAI fires three safety researchers after probe", "OpenAI announced the decision.", 1),
    ]
    monkeypatch.delenv("NEWSDESK_PASSWORD", raising=False)
    render(build_edition(cfg, articles=articles + extra, now=NOW), cfg, out_dir=tmp_path / "s2", data_path=tmp_path / "e2.json")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(tmp_path / "s2"))
    handler.log_message = lambda *a: None
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://localhost:{server.server_address[1]}/"
    server.shutdown()


def test_precise_ai_theme_keeps_launches_not_chatter(ai_site, browser):
    page = open_app(browser, ai_site, {"v": 2, "themes": ["Inteligencia artificial", "IA: lanzamientos y empresas"], "local": False})
    broad, precise = panel_text(page, "Inteligencia artificial"), panel_text(page, "IA: lanzamientos y empresas")
    assert "OpenAI" in broad and "homework" in broad
    assert "OpenAI" in precise and "homework" not in precise
    assert "Huanuco" not in precise and "fires" not in precise   # AI only in the text / company drama
    assert not page.errors, page.errors


def test_fine_tune_a_theme_with_must_and_exclude_words(ai_site, browser):
    page = open_app(browser, ai_site, {"v": 2, "themes": ["Inteligencia artificial"], "local": False})
    page.click("#gear")
    page.click('#tlist li[data-i="0"] .ed-btn')
    page.select_option("#tlist li.ed select.addword", "openai")      # suggested words come in a dropdown
    page.fill("#tlist li.ed input.not", "homework")
    page.click("#setsave")
    text = panel_text(page, "Inteligencia artificial")
    assert "OpenAI" in text and "homework" not in text
    page.reload()
    page.wait_for_selector(".tab")
    assert "homework" not in panel_text(page, "Inteligencia artificial")  # kept on the device
    assert not page.errors, page.errors


@pytest.fixture
def big_site(articles, cfg, tmp_path, monkeypatch):
    from datetime import timedelta

    from conftest import SOURCES
    from newsdesk.fetch import Article

    topics = ["parliament budget vote", "central bank interest rates", "telescope discovers planet",
              "hospital vaccine campaign", "wildfire forces evacuation", "chipmaker unveils processor",
              "summit on trade tariffs", "court rules on election law"]
    extra = [Article(SOURCES["bbc" if i % 2 else "dw"], f"Officials report {t} in region {i}", f"https://x/big{i}",
                     f"Details on {t}.", NOW - timedelta(hours=i + 1)) for i, t in enumerate(topics)]
    monkeypatch.delenv("NEWSDESK_PASSWORD", raising=False)
    render(build_edition(cfg, articles=articles + extra, now=NOW), cfg, out_dir=tmp_path / "s3", data_path=tmp_path / "e3.json")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(tmp_path / "s3"))
    handler.log_message = lambda *a: None
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://localhost:{server.server_address[1]}/"
    server.shutdown()


def test_each_tab_shows_four_stories_until_asked_for_more(big_site, browser):
    page = open_app(browser, big_site, {"v": 2, "themes": [], "local": False})
    visible = "els => els.filter(e => e.offsetParent !== null).length"
    total = page.eval_on_selector_all("#panel-0 .card", "els => els.length")
    assert total > 4
    assert page.eval_on_selector_all("#panel-0 .card", visible) == 4
    page.click("#panel-0 .moreall")
    assert page.eval_on_selector_all("#panel-0 .card", visible) == total
    assert page.text_content("#panel-0 .moreall") == "Ver menos"
    page.click("#panel-0 .moreall")
    assert page.eval_on_selector_all("#panel-0 .card", visible) == 4
    assert not page.errors, page.errors


@pytest.fixture
def judged_site(articles, cfg, tmp_path, monkeypatch):
    from datetime import timedelta

    from conftest import SOURCES
    from newsdesk import judge
    from newsdesk.fetch import Article

    extra = [
        Article(SOURCES["bbc"], "OpenAI releases GPT-6 language model", "https://x/j1", "The company announced it.", NOW - timedelta(hours=1)),
        Article(SOURCES["dw"], "Startup builds AI agent that helps people cut calories", "https://x/j2", "A diet app.", NOW - timedelta(hours=1)),
    ]
    monkeypatch.setenv("NEWSDESK_THEMES", "Avances de la IA de fuentes oficiales")
    monkeypatch.setenv("GITHUB_REPOSITORY", "me/News")
    monkeypatch.setenv("GITHUB_REF_NAME", "main")
    monkeypatch.setenv("NEWSDESK_LOCAL_MODEL", "fake")
    monkeypatch.setattr(judge, "CACHE_PATH", tmp_path / "tc.json")
    monkeypatch.setattr(judge, "_ask", lambda p, c, m, t, batch: {k: "GPT-6" in x["headlines"][0] for k, x in batch})
    monkeypatch.setattr("newsdesk.edition.neutralize", lambda *a, **k: 0)
    monkeypatch.delenv("NEWSDESK_PASSWORD", raising=False)
    cfg = dict(cfg, _fetch_images=False)
    render(build_edition(cfg, articles=articles + extra, now=NOW), cfg, out_dir=tmp_path / "s4", data_path=tmp_path / "e4.json")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(tmp_path / "s4"))
    handler.log_message = lambda *a: None
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://localhost:{server.server_address[1]}/"
    server.shutdown()


def test_ai_filter_keeps_only_exact_matches(judged_site, browser):
    page = open_app(browser, judged_site, {"v": 2, "themes": ["Avances de la IA de fuentes oficiales"], "local": False})
    text = panel_text(page, "Avances de la IA de fuentes oficiales")
    assert "GPT-6" in text and "calories" not in text
    page.click("#gear")
    assert "Filtro IA activo" in page.text_content("#aistate")
    page.click("#setcancel")
    # A theme the filter doesn't know yet: connect GitHub once, then saving sends the themes.
    page = open_app(browser, judged_site, {"v": 2, "themes": ["Inteligencia artificial"], "local": False})
    calls = []

    def github(route):
        req = route.request
        calls.append((req.method, req.url.split("/repos/me/News")[1], req.post_data_json, req.headers.get("authorization")))
        route.fulfill(status=404 if req.method == "PATCH" and len(calls) == 1 else 204, body="")

    page.route("https://api.github.com/**", github)
    page.click("#gear")
    assert "conectá GitHub" in page.text_content("#aistate")
    page.fill("#aikey", "github_pat_test")
    page.click("#aiform button")
    page.wait_for_function("document.getElementById('aistate').textContent.includes('enviados')")
    assert calls[0][:2] == ("PATCH", "/actions/variables/NEWSDESK_THEMES")
    assert calls[1][:3] == ("POST", "/actions/variables", {"name": "NEWSDESK_THEMES", "value": "Inteligencia artificial"})
    assert calls[2][:3] == ("POST", "/actions/workflows/newsdesk.yml/dispatches", {"ref": "main"})
    assert calls[1][3] == "Bearer github_pat_test"
    assert not page.is_visible("#aikey")                       # connected: the key box is gone
    page.fill("#newtheme", "Fútbol")
    page.click("#addform button")
    page.click("#setsave")
    page.wait_for_timeout(300)
    assert calls[3][2] == {"name": "NEWSDESK_THEMES", "value": "Inteligencia artificial\nFútbol"}
    assert not page.errors, page.errors


def test_long_themes_get_short_tab_names_and_sections_chain(ai_site, browser):
    page = open_app(browser, ai_site, {"v": 2, "themes": ["Avances de la inteligencia artificial de fuentes oficiales",
                                                         "Noticias sobre vehículos eléctricos en Europa"], "local": False})
    texts = page.eval_on_selector_all(".tab", "els => els.map(e => e.textContent)")
    assert texts[1] == "IA"                          # a known concept: its short name
    assert texts[2] == "Vehículos"
    assert page.text_content("#panel-1 .flag h2") == "IA"
    page.click("#panel-0 .nextsec")                  # "Sección siguiente" at the bottom of each page
    page.wait_for_function("document.querySelector('.tab[aria-selected=\"true\"]').dataset.i === '1'")
    # The tab name can be changed in ⚙ → ✎.
    page.click("#gear")
    page.click('#tlist li[data-i="1"] .ed-btn')
    page.fill("#tlist li.ed input.short", "Autos UE")
    page.click("#setsave")
    assert page.eval_on_selector_all(".tab", "els => els.map(e => e.textContent)")[2] == "Autos UE"
    assert not page.errors, page.errors
