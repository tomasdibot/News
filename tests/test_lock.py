import json
import re

import pytest

from conftest import NOW
from newsdesk.edition import build_edition, render
from newsdesk.lock import LockError, decrypt, password_from_env

PASSWORD = "correct horse battery"


def locked_page(articles, cfg, tmp_path):
    edition = build_edition(cfg, articles=articles, now=NOW)
    return render(edition, cfg, out_dir=tmp_path / "site", data_path=tmp_path / "edition.json", password=PASSWORD)


def payload_of(html: str) -> dict:
    return json.loads(re.search(r"var P = (\{.*?\});", html).group(1))


def test_locked_page_reveals_no_news(articles, cfg, tmp_path):
    html = locked_page(articles, cfg, tmp_path).read_text()
    assert "INDEC" not in html and "Gaza" not in html and "noindex" in html
    assert "Lo más importante" in decrypt(payload_of(html), PASSWORD)


def test_same_key_across_rebuilds(articles, cfg, tmp_path):
    # "Remember me" stores the derived key, so the salt must not change between hourly builds.
    a = payload_of(locked_page(articles, cfg, tmp_path).read_text())
    b = payload_of(locked_page(articles, cfg, tmp_path).read_text())
    assert a["salt"] == b["salt"] and a["iv"] != b["iv"]


def test_password_rules(monkeypatch):
    monkeypatch.delenv("NEWSDESK_PASSWORD", raising=False)
    assert password_from_env() is None
    monkeypatch.setenv("NEWSDESK_REQUIRE_PASSWORD", "1")
    with pytest.raises(LockError):
        password_from_env()
    monkeypatch.setenv("NEWSDESK_PASSWORD", "short")
    with pytest.raises(LockError):
        password_from_env()


def test_browser_unlocks(articles, cfg, tmp_path):
    sync_api = pytest.importorskip("playwright.sync_api")
    page_path = locked_page(articles, cfg, tmp_path)
    import os
    exe = "/opt/pw-browsers/chromium" if os.path.exists("/opt/pw-browsers/chromium") else None
    with sync_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch(executable_path=exe)
        except Exception as exc:
            pytest.skip(f"no browser available: {exc}")
        # Web Crypto needs a secure context: serve over http://localhost.
        page = browser.new_page()
        page.route("http://localhost/", lambda r: r.fulfill(body=page_path.read_text(), content_type="text/html"))
        page.goto("http://localhost/")
        page.fill("#pw", "wrong password!")
        page.click("#go")
        page.wait_for_selector("#err:has-text('incorrecta')", timeout=20000)
        page.fill("#pw", PASSWORD)
        page.click("#go")
        page.wait_for_selector("text=Lo más importante", timeout=20000)
        # Remembered: a reload opens straight away.
        page.reload()
        page.wait_for_selector("text=Lo más importante", timeout=20000)
        browser.close()
