"""Official Argentine numbers (free public APIs, no keys). Every item is fetched on its own;
a failure or an unexpected shape skips that item and never raises."""
from __future__ import annotations

import logging
import math
from datetime import datetime

from .fetch import _get

log = logging.getLogger(__name__)

TIMEOUT = 8
DOLAR = "https://dolarapi.com/v1/dolares/"
ARGDATA = "https://api.argentinadatos.com/v1/finanzas/indices/"


def _number(v) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    return v


def _day(v) -> str | None:
    return v[:10] if isinstance(v, str) and len(v) >= 10 and v[4] == "-" else None


def _dollar(data) -> tuple[float, str | None] | None:
    if not isinstance(data, dict) or (v := _number(data.get("venta"))) is None or v <= 0:
        return None
    return v, _day(data.get("fechaActualizacion"))


def _risk(data) -> tuple[float, str | None] | None:
    if not isinstance(data, dict) or (v := _number(data.get("valor"))) is None or v <= 0:
        return None
    return v, _day(data.get("fecha"))


def _inflation(data) -> tuple[float, str | None] | None:
    rows = [r for r in data if isinstance(r, dict) and _number(r.get("valor")) is not None and _day(r.get("fecha"))] \
        if isinstance(data, list) else []
    if not rows:
        return None
    last = max(rows, key=lambda r: r["fecha"])
    return last["valor"], _day(last["fecha"])


# key, label key in lexicon, unit, endpoint, parser, source shown, page to open
ITEMS = [
    ("inflation", "econ_inflation", "%", ARGDATA + "inflacion", _inflation,
     "INDEC · argentinadatos.com", "https://www.indec.gob.ar/"),
    ("official", "econ_official", "ARS", DOLAR + "oficial", _dollar,
     "BCRA · dolarapi.com", "https://dolarapi.com/"),
    ("blue", "econ_blue", "ARS", DOLAR + "blue", _dollar,
     "Mercado · dolarapi.com", "https://dolarapi.com/"),
    ("risk", "econ_risk", "pts", ARGDATA + "riesgo-pais/ultimo", _risk,
     "JP Morgan EMBI · argentinadatos.com", "https://argentinadatos.com/"),
]


def fetch_item(key: str) -> dict | None:
    for k, label_key, unit, url, parse, source, page in ITEMS:
        if k != key:
            continue
        try:
            got = parse(_get(url, timeout=TIMEOUT).json())
        except Exception as exc:
            log.warning("econ %s: %s", key, exc)
            return None
        if got is None:
            log.warning("econ %s: unexpected data from %s", key, url)
            return None
        value, date = got
        return {"key": key, "label_key": label_key, "value": value, "unit": unit,
                "date": date or "", "source": source, "url": page}
    return None


def fetch_econ(now: datetime | None = None) -> list[dict]:
    return [it for it in (fetch_item(k[0]) for k in ITEMS) if it]


def check() -> list[tuple[str, str, bool, str]]:
    """For `check-feeds`: (key, url, ok, text) per endpoint."""
    out = []
    for key, _, unit, url, *_ in ITEMS:
        it = fetch_item(key)
        out.append((key, url, bool(it), f"{it['value']} {unit} ({it['date']})" if it else "no data"))
    return out
