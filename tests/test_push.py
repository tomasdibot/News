import base64
import json
import struct

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from conftest import NOW
from newsdesk import push
from newsdesk.edition import build_edition, render
from newsdesk.notify import NotifyError, notify


def raw_pub(key):
    return key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def phone_decrypt(body: bytes, ua_key, auth: bytes) -> bytes:
    """Independent RFC 8291 decryption, as the phone's browser does it."""
    salt, (rs, idlen) = body[:16], struct.unpack("!IB", body[16:21])
    as_public = body[21:21 + idlen]
    ciphertext = body[21 + idlen:]
    shared = ua_key.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_public))
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    ikm = HKDF(hashes.SHA256(), 32, auth, b"WebPush: info\x00" + raw_pub(ua_key) + as_public).derive(shared)
    cek = HKDF(hashes.SHA256(), 16, salt, b"Content-Encoding: aes128gcm\x00").derive(ikm)
    nonce = HKDF(hashes.SHA256(), 12, salt, b"Content-Encoding: nonce\x00").derive(ikm)
    plain = AESGCM(cek).decrypt(nonce, ciphertext, None)
    assert rs == 4096 and plain.endswith(b"\x02")
    return plain[:-1]


@pytest.fixture
def device():
    key = ec.generate_private_key(ec.SECP256R1())
    auth = b"0123456789abcdef"
    sub = {"endpoint": "https://fcm.googleapis.com/fcm/send/abc123",
           "keys": {"p256dh": push.b64url(raw_pub(key)), "auth": push.b64url(auth)}}
    return key, auth, sub


def test_encryption_roundtrip(device):
    key, auth, _ = device
    body = push.encrypt("Tus noticias ✓".encode(), raw_pub(key), auth)
    assert phone_decrypt(body, key, auth).decode() == "Tus noticias ✓"


def test_vapid_signature_verifies(cfg, monkeypatch):
    monkeypatch.setenv("NEWSDESK_PASSWORD", "correct horse battery")
    key = push.vapid_key(cfg)
    header = push.vapid_header(key, "https://web.push.apple.com/abc", "https://example.github.io/News/")
    jwt = header.split("t=")[1].split(",")[0]
    k = header.split("k=")[1]
    head, claims, sig = jwt.split(".")
    pad = lambda s: s + "=" * (-len(s) % 4)  # noqa: E731
    assert json.loads(base64.urlsafe_b64decode(pad(claims)))["aud"] == "https://web.push.apple.com"
    raw = base64.urlsafe_b64decode(pad(sig))
    der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
    pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), base64.urlsafe_b64decode(pad(k)))
    pub.verify(der, f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))  # raises if invalid
    assert k == push.public_key_b64(cfg)  # same key the app subscribes with


def test_key_is_stable_and_tied_to_password(cfg, monkeypatch):
    monkeypatch.setenv("NEWSDESK_PASSWORD", "correct horse battery")
    a = push.public_key_b64(cfg)
    assert a == push.public_key_b64(cfg)
    monkeypatch.setenv("NEWSDESK_PASSWORD", "another long password")
    assert push.public_key_b64(cfg) != a
    monkeypatch.delenv("NEWSDESK_PASSWORD")
    assert push.public_key_b64(cfg) is None


def test_daily_push_reaches_every_device(articles, cfg, device, monkeypatch):
    key, auth, sub = device
    other = dict(sub, endpoint="https://web.push.apple.com/gone")
    code = push.b64url(json.dumps(sub).encode())
    monkeypatch.setenv("NEWSDESK_PASSWORD", "correct horse battery")
    monkeypatch.setenv("PUSH_SUBSCRIPTIONS", f"{code}\n{json.dumps(other)}\n")
    sent = []

    class Resp:
        def __init__(self, code):
            self.status_code, self.text = code, ""

    def fake_post(url, data, timeout, headers):
        sent.append((url, data, headers))
        return Resp(410 if "gone" in url else 201)

    monkeypatch.setattr(push.requests, "post", fake_post)
    edition = build_edition(cfg, articles=articles, now=NOW)
    notify(edition, cfg, provider="push")

    url, body, headers = sent[0]
    assert headers["Content-Encoding"] == "aes128gcm" and headers["Authorization"].startswith("vapid t=")
    msg = json.loads(phone_decrypt(body, key, auth))
    assert msg["title"] == "Tus noticias de hoy están listas"
    assert msg["body"].startswith("• ") and msg["body"].count("\n") == 2
    assert len(sent) == 2  # the expired device is reported, not fatal


def test_push_without_devices_explains_what_to_do(articles, cfg, monkeypatch):
    monkeypatch.setenv("NEWSDESK_PASSWORD", "correct horse battery")
    monkeypatch.delenv("PUSH_SUBSCRIPTIONS", raising=False)
    with pytest.raises(NotifyError, match="tap the bell"):
        notify(build_edition(cfg, articles=articles, now=NOW), cfg, provider="push")


def test_bell_gives_a_code_the_server_accepts(articles, cfg, tmp_path, monkeypatch):
    sync_api = pytest.importorskip("playwright.sync_api")
    import os
    monkeypatch.setenv("NEWSDESK_PASSWORD", "correct horse battery")
    monkeypatch.setenv("GITHUB_REPOSITORY", "someone/News")
    page_path = render(build_edition(cfg, articles=articles, now=NOW), cfg,
                       out_dir=tmp_path / "site", data_path=tmp_path / "e.json")
    exe = "/opt/pw-browsers/chromium" if os.path.exists("/opt/pw-browsers/chromium") else None
    # The real push service isn't reachable from tests: fake the browser's subscription.
    fake = """
      localStorage.setItem("newsdesk-prefs-v2", JSON.stringify({v: 2, themes: ["Economía"], local: true}));
      Notification.requestPermission = () => Promise.resolve("granted");
      PushManager.prototype.getSubscription = () => Promise.resolve(null);
      PushManager.prototype.subscribe = function (opts) {
        window.__key = btoa(String.fromCharCode(...new Uint8Array(opts.applicationServerKey)));
        return Promise.resolve({ options: opts, toJSON: () => ({ endpoint: "https://fcm.googleapis.com/fcm/send/x",
          expirationTime: null, keys: { p256dh: "BPub", auth: "QXV0aA" } }) });
      };
    """
    with sync_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch(executable_path=exe)
        except Exception as exc:
            pytest.skip(f"no browser available: {exc}")
        ctx = browser.new_context()
        ctx.add_init_script(fake)
        page = ctx.new_page()
        import functools
        import http.server
        import threading
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(tmp_path / "site"))
        handler.log_message = lambda *a: None
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        page.goto(f"http://localhost:{server.server_address[1]}/")
        page.fill("#pw", "correct horse battery")
        page.click("#go")
        page.click("#bell")
        page.wait_for_selector("#pushtext", state="visible", timeout=15000)
        code = page.input_value("#pushtext")
        assert page.get_attribute("a[href*='settings/secrets']", "href").startswith("https://github.com/someone/News/")
        assert "on" in page.get_attribute("#bell", "class")
        browser.close()
        server.shutdown()
    monkeypatch.setenv("PUSH_SUBSCRIPTIONS", code)
    assert push.load_subscriptions()[0]["endpoint"] == "https://fcm.googleapis.com/fcm/send/x"
