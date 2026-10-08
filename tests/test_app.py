"""The app in a real (headless) browser: tabs, swiping, opening a story, topic settings."""
import functools
import http.server
import os
import threading

import pytest

from conftest import NOW
from newsdesk.edition import build_edition, render


@pytest.fixture
def app(articles, cfg, tmp_path, monkeypatch):
    sync_api = pytest.importorskip("playwright.sync_api")
    monkeypatch.delenv("NEWSDESK_PASSWORD", raising=False)
    render(build_edition(cfg, articles=articles, now=NOW), cfg, out_dir=tmp_path / "site", data_path=tmp_path / "e.json")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(tmp_path / "site"))
    handler.log_message = lambda *a: None
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    exe = "/opt/pw-browsers/chromium" if os.path.exists("/opt/pw-browsers/chromium") else None
    with sync_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch(executable_path=exe)
        except Exception as exc:
            pytest.skip(f"no browser available: {exc}")
        ctx = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"http://localhost:{server.server_address[1]}/")
        page.wait_for_selector(".tab")
        yield page
        assert not errors, errors
        browser.close()
    server.shutdown()


def tab_names(page):
    return page.eval_on_selector_all(".tab", "els => els.map(e => e.textContent)")


def active(page):
    return page.text_content('.tab[aria-selected="true"]')


def test_tabs_follow_profile_order(app):
    names = tab_names(app)
    assert names[:3] == ["Lo más importante", "Tu país", "Mundo"]
    assert "Economía" in names and "Ciencia" in names


def test_tapping_a_tab_shows_that_section(app):
    app.click("text=Economía")
    app.wait_for_function("document.querySelector('.tab[aria-selected=\"true\"]').textContent === 'Economía'")
    i = tab_names(app).index("Economía")
    app.wait_for_function(f"Math.abs(pager.scrollLeft - {i} * pager.clientWidth) < 2")
    assert "INDEC" in app.text_content(f"#panel-{i}")


def test_swiping_changes_tab(app):
    app.evaluate("pager.scrollTo({left: 2 * pager.clientWidth})")
    app.wait_for_function("document.querySelector('.tab[aria-selected=\"true\"]').textContent === 'Mundo'")
    app.evaluate("pager.scrollTo({left: 0})")
    app.wait_for_function("document.querySelector('.tab[aria-selected=\"true\"]').textContent === 'Lo más importante'")


def test_story_opens_with_sources(app):
    card = app.locator("#panel-0 .card").first
    assert not card.locator(".more").is_visible()
    card.locator(".row").click()
    assert card.locator(".more").is_visible()
    assert card.locator(".srcs a").count() == 3 and card.locator("a.read").is_visible()


def test_topics_are_configurable_in_the_app(app):
    app.click("#gear")
    app.uncheck('#tlist li[data-n="economy"] input')
    app.click('#tlist li[data-n="science"] .up')
    app.fill("#newname", "Pulpos")
    app.fill("#newkw", "octopus, pulpo")
    app.click("#addtopic")
    app.click("#setsave")
    names = tab_names(app)
    assert "Economía" not in names and names[-1] == "Pulpos"
    i = names.index("Pulpos")
    assert "octopus" in app.text_content(f"#panel-{i}")
    app.reload()
    app.wait_for_selector(".tab")
    assert tab_names(app) == names  # saved on the device
    app.click("#gear")
    app.click("#setreset")
    app.click("#setsave")
    assert "Economía" in tab_names(app) and "Pulpos" not in tab_names(app)
