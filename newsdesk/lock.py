"""Password protection for the published page.

The rendered HTML is encrypted with AES-256-GCM using a key derived from the
password (PBKDF2-SHA256). The published page holds only the ciphertext and a
small unlock form; the browser decrypts it with the Web Crypto API. Without
the password the page reveals nothing but its title.

The salt is fixed per site (derived from its title and URL) so the key stays
the same across hourly rebuilds; that is what lets "remember me on this
device" keep working after each update.
"""

from __future__ import annotations

import base64
import hashlib
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

ITERATIONS = 600_000
MIN_PASSWORD_LENGTH = 10


class LockError(RuntimeError):
    pass


def site_salt(cfg: dict) -> bytes:
    ident = f"newsdesk:{cfg['site'].get('title', '')}:{cfg['site'].get('url', '')}"
    return hashlib.sha256(ident.encode()).digest()[:16]


def derive_key(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITERATIONS)
    return kdf.derive(password.encode("utf-8"))


def encrypt(html: str, password: str, salt: bytes) -> dict:
    iv = os.urandom(12)
    data = AESGCM(derive_key(password, salt)).encrypt(iv, html.encode("utf-8"), None)
    b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731
    return {"salt": b64(salt), "iv": b64(iv), "data": b64(data), "iterations": ITERATIONS}


def decrypt(payload: dict, password: str) -> str:
    """Python counterpart of the in-browser decryption (used by tests)."""
    raw = {k: base64.b64decode(payload[k]) for k in ("salt", "iv", "data")}
    return AESGCM(derive_key(password, raw["salt"])).decrypt(raw["iv"], raw["data"], None).decode("utf-8")


def password_from_env() -> str | None:
    password = os.environ.get("NEWSDESK_PASSWORD") or None
    if password and len(password) < MIN_PASSWORD_LENGTH:
        raise LockError(f"NEWSDESK_PASSWORD must have at least {MIN_PASSWORD_LENGTH} characters")
    if not password and os.environ.get("NEWSDESK_REQUIRE_PASSWORD"):
        raise LockError("NEWSDESK_PASSWORD is not set; refusing to publish the site unprotected")
    return password
