"""Daily reminder as a notification from the installed app (Web Push).

No third-party service is involved: the message is encrypted for your device
(RFC 8291) and handed to the push service your phone already uses (Apple or
Google), which cannot read it. The sender is identified with VAPID (RFC 8292).

Keys: the VAPID key pair is derived from NEWSDESK_PASSWORD (or taken from
VAPID_PRIVATE_KEY), so there is nothing extra to generate. Changing the
password means tapping the bell in the app again to re-enable notifications.

Subscriptions: when you enable notifications in the app it shows a code; save
it as the PUSH_SUBSCRIPTIONS secret (one code per line for several devices).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import struct
import time
from urllib.parse import urlsplit

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .lexicon import UI
from .lock import site_salt

log = logging.getLogger(__name__)

P256_ORDER = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
RECORD_SIZE = 4096


class PushError(RuntimeError):
    pass


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def b64url_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _raw_public(key: ec.EllipticCurvePrivateKey | ec.EllipticCurvePublicKey) -> bytes:
    pub = key.public_key() if isinstance(key, ec.EllipticCurvePrivateKey) else key
    return pub.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


# --- Keys -------------------------------------------------------------------

def vapid_key(cfg: dict) -> ec.EllipticCurvePrivateKey | None:
    explicit = os.environ.get("VAPID_PRIVATE_KEY", "").strip()
    if explicit:
        return ec.derive_private_key(int.from_bytes(b64url_decode(explicit), "big"), ec.SECP256R1())
    password = os.environ.get("NEWSDESK_PASSWORD")
    if not password:
        return None
    seed = HKDF(algorithm=hashes.SHA256(), length=32, salt=site_salt(cfg), info=b"newsdesk vapid").derive(
        password.encode("utf-8"))
    return ec.derive_private_key(int.from_bytes(seed, "big") % (P256_ORDER - 1) + 1, ec.SECP256R1())


def public_key_b64(cfg: dict) -> str | None:
    """What the app passes to pushManager.subscribe() as applicationServerKey."""
    key = vapid_key(cfg)
    return b64url(_raw_public(key)) if key else None


# --- RFC 8292: VAPID ----------------------------------------------------------

def vapid_header(key: ec.EllipticCurvePrivateKey, endpoint: str, subject: str) -> str:
    parts = urlsplit(endpoint)
    claims = {"aud": f"{parts.scheme}://{parts.netloc}", "exp": int(time.time()) + 12 * 3600, "sub": subject}
    signing_input = (b64url(json.dumps({"typ": "JWT", "alg": "ES256"}).encode()) + "."
                     + b64url(json.dumps(claims, separators=(",", ":")).encode()))
    r, s = decode_dss_signature(key.sign(signing_input.encode(), ec.ECDSA(hashes.SHA256())))
    jwt = signing_input + "." + b64url(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
    return f"vapid t={jwt}, k={b64url(_raw_public(key))}"


# --- RFC 8291: message encryption --------------------------------------------

def _hmac(key: bytes, data: bytes) -> bytes:
    return hmac.new(key, data, hashlib.sha256).digest()


def encrypt(payload: bytes, ua_public: bytes, auth_secret: bytes,
            salt: bytes | None = None, as_key: ec.EllipticCurvePrivateKey | None = None) -> bytes:
    salt = salt or os.urandom(16)
    as_key = as_key or ec.generate_private_key(ec.SECP256R1())
    as_public = _raw_public(as_key)
    ua_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public)
    shared = as_key.exchange(ec.ECDH(), ua_key)

    prk_key = _hmac(auth_secret, shared)
    ikm = _hmac(prk_key, b"WebPush: info\x00" + ua_public + as_public + b"\x01")
    prk = _hmac(salt, ikm)
    cek = _hmac(prk, b"Content-Encoding: aes128gcm\x00\x01")[:16]
    nonce = _hmac(prk, b"Content-Encoding: nonce\x00\x01")[:12]

    if len(payload) > RECORD_SIZE - 17 - 86:
        raise PushError("notification payload too large")
    ciphertext = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)
    header = salt + struct.pack("!IB", RECORD_SIZE, len(as_public)) + as_public
    return header + ciphertext


# --- Sending ------------------------------------------------------------------

def load_subscriptions() -> list[dict]:
    """PUSH_SUBSCRIPTIONS: codes copied from the app, one per line (or a JSON list)."""
    raw = os.environ.get("PUSH_SUBSCRIPTIONS", "").strip()
    if not raw:
        return []
    if raw.startswith("["):
        items = json.loads(raw)
    else:
        items = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            items.append(json.loads(line if line.startswith("{") else b64url_decode(line)))
    for sub in items:
        if not (sub.get("endpoint") and sub.get("keys", {}).get("p256dh") and sub["keys"].get("auth")):
            raise PushError("a PUSH_SUBSCRIPTIONS entry is not a valid code from the app")
    return items


def build_payload(edition: dict, cfg: dict) -> dict:
    ui = UI.get(cfg["site"]["ui_language"], UI["en"])
    stories, seen = [], set()
    for s in edition["top"] + edition["local"]:
        if s["link"] not in seen:
            seen.add(s["link"])
            stories.append(s)
    n = min(3, cfg["notification"]["headlines"])
    body = "\n".join(f"• {s['title']}" for s in stories[:n]) or ui["empty"]
    return {
        "title": ui["push_title"],
        "body": body,
        "image": next((s["image"] for s in stories[:1] if s.get("image")), None),
        "url": "./",
        "tag": "daily-news",
    }


def send_push(edition: dict, cfg: dict) -> int:
    key = vapid_key(cfg)
    if key is None:
        raise PushError("set NEWSDESK_PASSWORD (or VAPID_PRIVATE_KEY) to send notifications")
    subs = load_subscriptions()
    if not subs:
        raise PushError("PUSH_SUBSCRIPTIONS is empty: open the app, tap the bell and save the code it shows")
    payload = json.dumps(build_payload(edition, cfg), ensure_ascii=False).encode("utf-8")
    subject = os.environ.get("VAPID_SUBJECT") or cfg["site"].get("url") or "mailto:newsdesk@example.com"
    if subject.startswith("http://"):
        subject = "mailto:newsdesk@example.com"

    sent = 0
    for sub in subs:
        body = encrypt(payload, b64url_decode(sub["keys"]["p256dh"]), b64url_decode(sub["keys"]["auth"]))
        resp = requests.post(sub["endpoint"], data=body, timeout=30, headers={
            "Authorization": vapid_header(key, sub["endpoint"], subject),
            "Content-Encoding": "aes128gcm",
            "Content-Type": "application/octet-stream",
            "TTL": str(12 * 3600),
            "Urgency": "normal",
        })
        host = urlsplit(sub["endpoint"]).netloc
        if resp.status_code in (404, 410):
            log.warning("device on %s is no longer subscribed: tap the bell in the app again", host)
        elif resp.status_code >= 300:
            log.warning("push to %s failed: %s %s", host, resp.status_code, resp.text[:200])
        else:
            sent += 1
    if not sent:
        raise PushError("no device accepted the notification (see warnings above)")
    log.info("notification sent to %d of %d device(s)", sent, len(subs))
    return sent
