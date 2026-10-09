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
    return page.eval_on_selector_all(".tab", "els => els.map(e => e.textContent)")


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
