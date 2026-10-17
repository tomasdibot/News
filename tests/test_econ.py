import logging

import pytest

from conftest import NOW
from newsdesk import econdata
from newsdesk.edition import build_edition

OFICIAL = {"moneda": "USD", "casa": "oficial", "compra": 1380, "venta": 1430.5,
           "fechaActualizacion": "2026-10-16T18:03:00.000Z"}
BLUE = {"moneda": "USD", "casa": "blue", "compra": 1470, "venta": 1490,
        "fechaActualizacion": "2026-10-16T17:40:00.000Z"}
RIESGO = {"fecha": "2026-10-16", "valor": 612}
INFLACION = [{"fecha": "2026-07-31", "valor": 1.9}, {"fecha": "2026-08-31", "valor": 1.9},
             {"fecha": "2026-09-30", "valor": 2.1}]

PAYLOADS = {
    "dolarapi.com/v1/dolares/oficial": OFICIAL,
    "dolarapi.com/v1/dolares/blue": BLUE,
    "riesgo-pais/ultimo": RIESGO,
    "indices/inflacion": INFLACION,
}


class Resp:
    def __init__(self, data):
        self.data = data

    def json(self):
        if isinstance(self.data, Exception):
            raise self.data
        return self.data


def fake_get(payloads):
    def get(url, **kw):
        for part, data in payloads.items():
            if part in url:
                if isinstance(data, Exception) and not isinstance(data, ValueError):
                    raise data
                return Resp(data)
        raise AssertionError(f"unexpected url {url}")
    return get


def by_key(items):
    return {i["key"]: i for i in items}


def test_each_api_shape_is_parsed(monkeypatch):
    monkeypatch.setattr(econdata, "_get", fake_get(PAYLOADS))
    items = by_key(econdata.fetch_econ(NOW))
    assert list(items) == ["inflation", "official", "blue", "risk"]
    assert items["inflation"]["value"] == 2.1 and items["inflation"]["date"] == "2026-09-30"
    assert items["official"]["value"] == 1430.5 and items["official"]["date"] == "2026-10-16"
    assert items["blue"]["value"] == 1490
    assert items["risk"]["value"] == 612 and items["risk"]["date"] == "2026-10-16"
    for it in items.values():
        assert it["label_key"] and it["unit"] and it["url"].startswith("https://")
    assert "INDEC" in items["inflation"]["source"] and "argentinadatos.com" in items["inflation"]["source"]
    assert "dolarapi.com" in items["official"]["source"]
    assert "JP Morgan" in items["risk"]["source"]


@pytest.mark.parametrize("bad", [RuntimeError("down"), ValueError("not json"), {}, [], None, "x",
                                 {"venta": "n/a"}, {"venta": None, "fechaActualizacion": "2026-10-16"}])
def test_a_failing_or_odd_item_is_skipped_and_the_rest_survive(monkeypatch, caplog, bad):
    monkeypatch.setattr(econdata, "_get", fake_get({**PAYLOADS, "dolarapi.com/v1/dolares/blue": bad, "indices/inflacion": bad}))
    with caplog.at_level(logging.WARNING):
        items = by_key(econdata.fetch_econ(NOW))
    assert set(items) == {"official", "risk"}
    assert any(r.levelno == logging.WARNING and "blue" in r.getMessage() for r in caplog.records)


def test_inflation_takes_the_latest_by_date_even_if_unordered(monkeypatch):
    monkeypatch.setattr(econdata, "_get", fake_get({**PAYLOADS, "indices/inflacion": list(reversed(INFLACION))}))
    assert by_key(econdata.fetch_econ(NOW))["inflation"]["date"] == "2026-09-30"


def test_everything_down_gives_an_empty_list(monkeypatch):
    monkeypatch.setattr(econdata, "_get", lambda url, **kw: (_ for _ in ()).throw(OSError("offline")))
    assert econdata.fetch_econ(NOW) == []


def test_edition_carries_econ_for_argentina_only(monkeypatch, articles, cfg, caplog):
    monkeypatch.setattr(econdata, "_get", fake_get(PAYLOADS))
    with caplog.at_level(logging.INFO):
        assert len(build_edition(cfg, articles=articles, now=NOW)["econ"]) == 4
    assert any("econ data: 4/4" in r.getMessage() for r in caplog.records)
    cfg["profile"]["country"] = "ES"
    monkeypatch.setattr(econdata, "_get", lambda *a, **k: pytest.fail("fetched outside AR"))
    assert build_edition(cfg, articles=articles, now=NOW)["econ"] == []


def test_check_feeds_prints_each_econ_endpoint(monkeypatch, cfg, capsys):
    from newsdesk.__main__ import cmd_check_feeds
    monkeypatch.setattr("newsdesk.fetch.fetch_source", lambda s: [])
    monkeypatch.setattr(econdata, "_get", fake_get({**PAYLOADS, "dolarapi.com/v1/dolares/blue": RuntimeError("down")}))
    cmd_check_feeds(cfg, None)
    lines = [l for l in capsys.readouterr().out.splitlines() if "dolarapi.com" in l or "argentinadatos" in l]
    assert len(lines) == 4
    assert any(l.startswith("OK ") and "612" in l and "riesgo-pais" in l for l in lines)
    assert any(l.startswith("FAIL") and "dolares/blue" in l for l in lines)
