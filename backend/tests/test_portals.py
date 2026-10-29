"""Portal parser, cache and API. No network: fetch is injected. Run: python -m pytest backend/tests/test_portals.py -q

REAL samples: backend/corpus/portals/_sample_<key>.md, saved TinyFish Fetch output of each portal home page
(29 Oct 2026). SAMPLE below is a hand-made plain markdown table, for the generic fallback parser.
"""

import json
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import portals, sources

SAMPLE = """# eProcurement System Government of India

Welcome to Central Public Procurement Portal

## Latest Tenders

| Tender Title | Reference No | Closing Date | Opening Date |
| --- | --- | --- | --- |
| 1. [Supply of 50 Desktop Computers for District Offices](/eprocure/app?page=FrontEndLatestActiveTenders&id=1) | DIT/2026/HW/114 | 12-Nov-2026 03:00 PM | 13-Nov-2026 03:30 PM |
| 2. [Construction of Boundary Wall at Block B](/eprocure/app?page=FrontEndLatestActiveTenders&id=2) | PWD/EE/2026/88 | 15-Nov-2026 11:00 AM | 16-Nov-2026 11:30 AM |
| 3. [SITC of CCTV Surveillance System at Port Office](https://eprocure.gov.in/eprocure/app?id=3) | VPT/ELEC/CCTV/07 | 2026-11-20 | 2026-11-21 |
| 4. **Annual maintenance of UPS systems** | CRPF/AMC/UPS/2 | 30/11/2026 | 01/12/2026 |
| 5. [Hiring of vehicles](/x) | MHA/VEH/9 | not a date | |

| Links | |
| --- | --- |
| Help | FAQ |
"""


REAL = Path(__file__).resolve().parent.parent / "corpus" / "portals"


def real(key):
    return (REAL / f"_sample_{key}.md").read_text(encoding="utf-8")


def test_real_cppp_flattened_gepnic_rows():
    rows = portals.parse_tenders(real("cppp"))
    assert len(rows) == 10  # the 10 "Latest Tenders"; the Corrigendum table after it is not included
    assert rows[0] == rows[0] | {"title": None, "reference": "Sout/Hamp/Hamp/3 Ka/24634763",
                                 "closing": "2026-11-05", "opening": "2026-11-06", "closing_text": "05-Nov-2026 10:00 AM"}
    assert rows[3]["reference"] == "AIIMS MG/Engineering Dept/NIT/2026-27/13"
    assert not any("Corrigendum" in (r["title"] or "") for r in rows)


def test_real_etenders_titles_when_present():
    rows = portals.parse_tenders(real("etenders"))
    assert len(rows) == 10
    assert rows[0]["title"] == "EOI for OEM for VSAT tender" and rows[0]["reference"] == "TCIL/ITTII/254/2026/VSAT/Pkg1"
    assert rows[3]["reference"] == "CWC/RO-BBSR/ENGG/ZMC_Zone13/30"  # markdown escape removed
    assert rows[8]["title"] is None  # the portal repeated the reference where the title should be


@pytest.mark.parametrize("key,n", [("maha", 8), ("tn", 10)])
def test_real_state_portals(key, n):
    rows = portals.parse_tenders(real(key))
    assert len(rows) == n and all(r["reference"] and r["closing"] for r in rows)


def fake_fetch(text=SAMPLE, ms=6900):
    calls = []

    def f(url):
        calls.append(url)
        return {"text": text, "title": "eProcurement System", "ms": ms}
    f.calls = calls
    return f


def test_parse_rows_and_columns():
    rows = portals.parse_tenders(SAMPLE, "https://eprocure.gov.in/eprocure/app")
    assert len(rows) == 5  # the "Links" table has no title column and is ignored
    r = rows[0]
    assert r["title"] == "Supply of 50 Desktop Computers for District Offices"
    assert r["reference"] == "DIT/2026/HW/114"
    assert r["closing"] == "2026-11-12" and r["closing_text"] == "12-Nov-2026 03:00 PM"
    assert r["link"] == "https://eprocure.gov.in/eprocure/app?page=FrontEndLatestActiveTenders&id=1"
    assert rows[2]["link"] == "https://eprocure.gov.in/eprocure/app?id=3"
    assert rows[3]["title"] == "Annual maintenance of UPS systems" and rows[3]["link"] is None
    assert rows[3]["closing"] == "2026-11-30"
    assert rows[4]["closing"] is None  # unparseable date stays None, text kept
    assert rows[0]["organisation"] is None  # this table has no organisation column


def test_header_order_does_not_matter():
    text = "| Closing Date | Organisation | Title |\n|---|---|---|\n| 05-Dec-2026 | NIC | Supply of laptops |\n"
    (r,) = portals.parse_tenders(text)
    assert r == r | {"title": "Supply of laptops", "organisation": "NIC", "closing": "2026-12-05"}


@pytest.mark.parametrize("s,iso", [("05-Nov-2026 03:00 PM", "2026-11-05"), ("5 November 2026", "2026-11-05"),
                                   ("2026-11-05", "2026-11-05"), ("05/11/2026", "2026-11-05"),
                                   ("31-Feb-2026", None), ("", None)])
def test_parse_date(s, iso):
    assert portals.parse_date(s) == iso


def test_it_filter():
    rows = portals.parse_tenders(SAMPLE)
    assert [portals.is_it(r) for r in rows] == [True, False, True, True, False]
    assert not portals.is_it({"title": "Supply of upside-down signage"})  # 'ups' must be a whole word


def test_cache_ttl_and_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(portals, "CACHE_DIR", tmp_path)
    f = fake_fetch()
    a = portals.read_portal("cppp", fetch=f)
    assert a["cached"] is False and len(a["tenders"]) == 5 and a["raw_chars"] == len(SAMPLE) and a["ms"] == 6900
    b = portals.read_portal("cppp", fetch=f)
    assert b["cached"] is True and len(f.calls) == 1  # second read served from cache
    data = json.loads((tmp_path / "cppp.json").read_text(encoding="utf-8"))
    data["_ts"] = time.time() - portals.TTL_SECONDS - 1
    (tmp_path / "cppp.json").write_text(json.dumps(data), encoding="utf-8")
    portals.read_portal("cppp", fetch=f)
    assert len(f.calls) == 2  # expired -> fetched again

    def boom(url):
        raise sources.SourceError("TinyFish Fetch: proxy_error")
    r = portals.read_portal("cppp", use_cache=False, fetch=boom)
    assert r["error"].endswith("proxy_error") and r["stale"]["tenders"]  # old data offered, clearly marked
    assert portals.read_portal("nope")["error"].startswith("unknown portal")


def test_cache_write_failure_is_swallowed(monkeypatch):
    class RO:
        def mkdir(self, *a, **k):
            raise PermissionError("read-only")
    monkeypatch.setattr(portals, "CACHE_DIR", RO())
    monkeypatch.setattr(portals, "_read_cache", lambda key: None)
    assert len(portals.read_portal("cppp", fetch=fake_fetch())["tenders"]) == 5


def test_api(tmp_path, monkeypatch):
    monkeypatch.setattr(portals, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(sources, "tinyfish_fetch", fake_fetch())
    app = FastAPI()
    app.include_router(portals.router)
    c = TestClient(app)
    assert [p["key"] for p in c.get("/api/portals").json()] == ["cppp", "etenders", "maha", "tn"]
    r = c.get("/api/portals/cppp?it_only=1").json()
    assert r["total"] == 5 and r["it_count"] == 3 and len(r["tenders"]) == 3 and r["it_only"] is True
    assert c.get("/api/portals").json()[0]["last"]["tenders"] == 5
    assert c.get("/api/portals/zzz").status_code == 404

    def boom(url):
        raise sources.SourceError("TinyFish Fetch HTTP 401")
    monkeypatch.setattr(sources, "tinyfish_fetch", boom)
    r = c.get("/api/portals/etenders?refresh=1")
    assert r.status_code == 200 and r.json()["error"] == "TinyFish Fetch HTTP 401"
