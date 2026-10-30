"""Corrigendum monitor: a TinyFish search Monitor watches the web for corrigenda, extensions or cancellations of a
saved GeM bid.

TinyFish Monitors API (the same calls the `tinyfish monitor` CLI makes, base https://agent.tinyfish.ai, X-API-Key):
  POST   /v1/monitors            create + baseline run   -> {monitor, run}      (billed)
  GET    /v1/monitors            list                    -> {monitors: [...]}
  GET    /v1/monitors/{id}       one monitor (no runs)
  POST   /v1/monitors/{id}/runs  run a check now         -> {run}               (billed)
  DELETE /v1/monitors/{id}       delete                  -> {deleted, id}
The API returns run results only from create and run-now, so we keep the latest run in corpus/watches.json.
Every public function returns a dict and never raises; failures come back as {"error": ...}.
"""

from . import config  # noqa: F401  (loads .env first)

import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

# own variable: TINYFISH_AGENT_URL in .env is the Agent run endpoint (…/v1/automation/run), not an API base
BASE = (os.environ.get("TINYFISH_MONITORS_URL") or "https://agent.tinyfish.ai").rstrip("/")
WATCHES = Path(__file__).resolve().parent / "corpus" / "watches.json"
SCHEDULE = "0 3 * * *"          # daily; every completed run is billed, so once a day keeps cost low
RESULT_LIMIT = 10
CHANGE_WORDS = re.compile(r"corrigend|addend|amendment|extension|extended|extend|cancel|re-?tender|postpone", re.I)


class MonitorError(Exception):
    pass


def _now():
    return datetime.now(timezone.utc).isoformat()


def _call(method, path, body=None, timeout=60):
    """One HTTP call to the TinyFish Monitors API. -> parsed JSON; raises MonitorError. Tests replace this."""
    key = os.environ.get("TINYFISH_API_KEY", "").strip()
    if not key:
        raise MonitorError("TINYFISH_API_KEY is not set")
    data = json.dumps(body).encode() if body is not None else None
    headers = {"X-API-Key": key, "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = (json.loads(e.read().decode("utf-8")) or {}).get("error") or ""
        except (ValueError, OSError):
            pass
        if isinstance(detail, dict):
            detail = detail.get("message") or detail.get("code") or ""
        raise MonitorError(f"TinyFish Monitors HTTP {e.code}{': ' + str(detail) if detail else ''}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise MonitorError(f"could not reach TinyFish Monitors: {e}") from e
    try:
        return json.loads(raw) if raw else {}
    except ValueError as e:
        raise MonitorError("TinyFish Monitors returned invalid JSON") from e


# ---------- storage ----------

PREFIX = "BidReady · "     # every monitor we create is named "BidReady · <bid>"
_MEM = {}                   # monitor_id -> record: keeps last runs when the disk is read-only (Vercel)


def _load():
    try:
        d = json.loads(WATCHES.read_text(encoding="utf-8"))
        rows = d if isinstance(d, list) else []
    except (OSError, ValueError):
        rows = []
    ids = {r.get("monitor_id") for r in rows}
    rows = [_MEM.get(r.get("monitor_id"), r) for r in rows]
    return rows + [r for i, r in _MEM.items() if i not in ids]


def _save(rows):
    _MEM.clear()
    _MEM.update({r["monitor_id"]: r for r in rows if r.get("monitor_id")})
    try:
        WATCHES.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass  # read-only disk (e.g. Vercel): _MEM keeps this instance's copy


def _remote():
    """BidReady's monitors as TinyFish lists them (the source of truth), or None when TinyFish can't be reached."""
    try:
        r = _call("GET", "/v1/monitors")
    except MonitorError:
        return None
    return [m for m in (r.get("monitors") or []) if (m.get("name") or "").startswith(PREFIX)]


def _from_monitor(m):
    """A record for a monitor that exists at TinyFish but not in our file (made on a server that couldn't save it)."""
    bid = (m.get("name") or "")[len(PREFIX):].strip()
    t = {}
    try:
        from backend import main  # lazy: main imports this module
        t = next((x for x in main.TENDERS.values() if x.get("bid") == bid), {})
    except Exception:  # noqa: BLE001
        pass
    return {"monitor_id": m["id"], "bid": bid, "tender_id": t.get("id"), "title": t.get("title") or "",
            "buyer": t.get("buyer") or "", "query": (m.get("config") or {}).get("query") or query_for(bid),
            "schedule": m.get("schedule_cron") or SCHEDULE, "status": m.get("status") or "active",
            "created_at": m.get("created_at"), "last_error": m.get("last_error"), "last_run": None}


def _rows():
    """Watches = TinyFish's list, with our stored last runs. Falls back to our copy when TinyFish is unreachable."""
    local = _load()
    remote = _remote()
    if remote is None:
        return local
    by_id = {r.get("monitor_id"): r for r in local}
    out = []
    for m in remote:
        rec = by_id.get(m.get("id")) or _from_monitor(m)
        rec["status"] = m.get("status") or rec.get("status")
        out.append(rec)
    return out


def _find(rows, monitor_id):
    return next((r for r in rows if r.get("monitor_id") == monitor_id), None)


# ---------- change detection ----------

def _bid_pattern(bid):
    """GEM/2026/B/8096659 also matches 'GEM-2026-B-8096659' and 'GEM 2026 B 8096659'."""
    parts = [re.escape(p) for p in re.split(r"[/\-\s]+", bid or "") if p]
    return re.compile(r"[/\-\s]*".join(parts), re.I) if parts else None


# Aggregator boilerplate that names a change type without reporting one: "Corrigendum (if any)",
# or a menu such as "Pre-Bid Meeting Minutes · Amendments · FAQs".
BOILERPLATE = re.compile(r"\w+\s*\(if any\)|[·•|�]\s*[\w -]{0,30}\s*(?=[·•|�])", re.I)


def detect_changes(results, bid):
    """Positions of results that name this exact bid AND use a corrigendum / extension / cancellation word."""
    pat = _bid_pattern(bid)
    if not pat:
        return []
    hits = []
    for r in results or []:
        text = " ".join(str(r.get(k) or "") for k in ("title", "snippet", "url"))
        if pat.search(text) and CHANGE_WORDS.search(BOILERPLATE.sub(" ", text)):
            hits.append(r.get("position"))
    return hits


def _run_record(run, bid):
    run = run or {}
    results = [{k: r.get(k) for k in ("position", "site_name", "title", "snippet", "url", "date") if r.get(k) is not None}
               for r in (run.get("results") or []) if isinstance(r, dict) and not r.get("error")]
    hits = detect_changes(results, bid)
    return {"id": run.get("id"), "at": run.get("created_at") or _now(), "status_code": run.get("status_code"),
            "result_count": len(results), "results": results,
            "new_result_positions": run.get("new_result_positions") or [],
            "change_positions": hits, "change_detected": bool(hits),
            "error": run.get("error")}


def _public(rec):
    out = dict(rec)
    last = rec.get("last_run") or {}
    out["change_detected"] = bool(last.get("change_detected"))
    out["last_run_at"] = last.get("at")
    return out


# ---------- public API ----------

def query_for(bid):
    return f'"{bid}" corrigendum OR extension OR cancelled'


def create_watch(tender):
    """Start watching a tender. Billed once now (baseline run). Watching the same tender twice returns the first watch."""
    try:
        bid, tid = tender.get("bid"), tender.get("id")
        if not bid:
            return {"error": "tender has no bid number"}
        rows = _rows()
        existing = next((r for r in rows if (r.get("tender_id") == tid or r.get("bid") == bid)
                         and r.get("status") != "cancelled"), None)
        if existing:
            return dict(_public(existing), already_watching=True)
        body = {"type": "search", "schedule_cron": SCHEDULE, "name": f"BidReady · {bid}"[:100],
                "purpose": f"Corrigendum, extension or cancellation of GeM bid {bid}",
                "config": {"query": query_for(bid), "result_limit": RESULT_LIMIT}}
        resp = _call("POST", "/v1/monitors", body)
        mon = resp.get("monitor") or {}
        if not mon.get("id"):
            return {"error": "TinyFish did not return a monitor id"}
        rec = {"monitor_id": mon["id"], "bid": bid, "tender_id": tid, "title": tender.get("title") or "",
               "buyer": tender.get("buyer") or "", "query": body["config"]["query"],
               "schedule": mon.get("schedule_cron") or SCHEDULE, "status": mon.get("status") or "active",
               "created_at": mon.get("created_at") or _now(), "last_error": mon.get("last_error"),
               "last_run": _run_record(resp.get("run"), bid)}
        rows.append(rec)
        _save(rows)
        return _public(rec)
    except MonitorError as e:
        return {"error": str(e)}
    except Exception as e:  # noqa: BLE001  (contract: never raise)
        return {"error": f"create_watch failed: {e}"}


def list_watches():
    try:
        return {"watches": [_public(r) for r in _rows() if r.get("status") != "cancelled"]}
    except Exception as e:  # noqa: BLE001
        return {"error": f"list_watches failed: {e}"}


def get_watch(monitor_id):
    """Stored record (latest run results + change flag), refreshed with the monitor's live status."""
    try:
        rows = _rows()
        rec = _find(rows, monitor_id)
        if not rec:
            return {"error": f"no watch {monitor_id}"}
        try:
            mon = _call("GET", f"/v1/monitors/{monitor_id}")
            rec["status"] = mon.get("status") or rec.get("status")
            rec["last_error"] = mon.get("last_error")
            rec["schedule"] = mon.get("schedule_cron") or rec.get("schedule")
            _save(rows)
            out = _public(rec)
        except MonitorError as e:
            out = dict(_public(rec), live_error=str(e))
        return out
    except Exception as e:  # noqa: BLE001
        return {"error": f"get_watch failed: {e}"}


def run_watch(monitor_id):
    """Run a check now, outside the schedule. Billed."""
    try:
        rows = _rows()
        rec = _find(rows, monitor_id)
        if not rec:
            return {"error": f"no watch {monitor_id}"}
        resp = _call("POST", f"/v1/monitors/{monitor_id}/runs")
        rec["last_run"] = _run_record(resp.get("run"), rec.get("bid"))
        _save(rows)
        return _public(rec)
    except MonitorError as e:
        return {"error": str(e)}
    except Exception as e:  # noqa: BLE001
        return {"error": f"run_watch failed: {e}"}


def cancel_watch(monitor_id):
    """Delete the TinyFish monitor and forget the watch."""
    try:
        rows = _rows()
        if not _find(rows, monitor_id):
            return {"error": f"no watch {monitor_id}"}
        try:
            _call("DELETE", f"/v1/monitors/{monitor_id}")
        except MonitorError as e:
            if "HTTP 404" not in str(e):  # already gone at TinyFish: still forget it here
                return {"error": str(e)}
        _save([r for r in rows if r.get("monitor_id") != monitor_id])
        return {"deleted": True, "monitor_id": monitor_id}
    except Exception as e:  # noqa: BLE001
        return {"error": f"cancel_watch failed: {e}"}


# ---------- HTTP routes (Sara adds app.include_router(monitor.router)) ----------

router = APIRouter()


class WatchIn(BaseModel):
    tender_id: str


def _ok(res, missing_is_404=True):
    if "error" in res:
        code = 404 if missing_is_404 and res["error"].startswith("no watch") else 502
        raise HTTPException(code, res["error"])
    return res


@router.post("/api/watch")
def api_watch_create(body: WatchIn):
    from backend import main  # lazy: main imports this module
    t = main.TENDERS.get(body.tender_id)
    if not t:
        raise HTTPException(404, f"unknown tender {body.tender_id}")
    return _ok(create_watch(t))


@router.get("/api/watch")
def api_watch_list():
    return _ok(list_watches())


@router.get("/api/watch/{monitor_id}")
def api_watch_get(monitor_id: str):
    return _ok(get_watch(monitor_id))


@router.post("/api/watch/{monitor_id}/run")
def api_watch_run(monitor_id: str):
    return _ok(run_watch(monitor_id))


@router.delete("/api/watch/{monitor_id}")
def api_watch_cancel(monitor_id: str):
    return _ok(cancel_watch(monitor_id))
