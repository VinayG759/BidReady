"""Bid watch: what the wider web says about one GeM bid, found with TinyFish Search.

Tender aggregators (tender247, bidassist, indiantenders, ...) republish GeM bids and often post corrigenda,
extensions and cancellations. We search for the exact bid number, keep only results that really name that bid
(searches for "<bid> corrigendum" mostly return other bids' corrigenda), and flag words or closing dates that
disagree with what GeM's own document says. Every signal carries the snippet it came from, so a person can judge it.

Results are cached per bid for 12 hours in corpus/signals/ (each refresh costs two TinyFish searches).
"""

import json
import re
import time
import urllib.parse
from datetime import date, datetime, timezone
from pathlib import Path

from . import sources

CACHE_DIR = Path(__file__).resolve().parent / "corpus" / "signals"
TTL_SECONDS = 12 * 3600

_SEP = r"\s*[/\-_\s]\s*"
_BID_RE = re.compile(r"GEM" + _SEP + r"(\d{4})" + _SEP + r"B" + _SEP + r"(\d+)", re.I)

KINDS = [
    ("corrigendum", re.compile(r"\bcorrigend(?:um|a)\b|\baddendum\b", re.I), "mentions a corrigendum"),
    # no leading \b: listings glue words together ("12:00 pmextended once")
    ("extension", re.compile(r"extend(?:ed)?\b|extension\b", re.I), "mentions an extension"),
    ("cancelled", re.compile(r"\bcancel(?:l?ed|lation)?\b", re.I), "mentions a cancellation"),
    ("retender", re.compile(r"\bre-?\s?tender(?:ed|ing)?\b", re.I), "mentions a re-tender"),
]

_MONTHS = {m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
_MON = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
_DATE_PATTERNS = [
    (re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b"), "ymd"),
    (re.compile(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\b"), "dmy"),
    (re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?[\s\-]+" + _MON + r",?[\s\-]+(\d{4})\b", re.I), "d_mon_y"),
    (re.compile(r"\b" + _MON + r"\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", re.I), "mon_d_y"),
]
# Words that introduce the closing date on aggregator listings ("Submission: 26 Nov 2026", "Bid End Date ...").
_CLOSING_RE = re.compile(r"\b(submission|closing|closes|close|end|due|last date|deadline)\b", re.I)
_NEAR = 40  # characters after the keyword in which a date must start
# Site furniture that names the words without reporting anything ("Corrigendum (if any)", "corrigendum alerts",
# tender247's FAQ question; its answer "Yes, a corrigendum has been issued" is kept).
_BOILERPLATE = re.compile(r"\b(?:corrigend(?:um|a)|addendum|amendments?|extensions?)\s*\(if any\)|\bcorrigend(?:um|a)\s+alerts?\b"
                          r"|\bhas an? (?:corrigendum|extension) been issued[^?]*\?", re.I)


def bid_key(text):
    """(year, serial) for the first GeM bid number in text, e.g. 'GEM / 2026 / B /8096659' -> ('2026', '8096659')."""
    m = _BID_RE.search(text or "")
    return (m.group(1), str(int(m.group(2)))) if m else None


def mentions_bid(text, bid):
    """True when text names exactly this bid (any separator, any case, URL-encoded too); a longer serial never matches."""
    want = bid_key(bid)
    if not want or not text:
        return False
    text = urllib.parse.unquote(text)
    return any((m.group(1), str(int(m.group(2)))) == want for m in _BID_RE.finditer(text))


def about_other_bid(result, bid):
    """True when the page title names a different GeM bid: it lists ours only as a 'similar tender'."""
    want = bid_key(bid)
    keys = {(m.group(1), str(int(m.group(2)))) for m in _BID_RE.finditer(urllib.parse.unquote(result.get("title") or ""))}
    return bool(keys) and want not in keys


def _site(r):
    name = (r.get("site_name") or "").strip()
    if name:
        return name
    host = urllib.parse.urlparse(r.get("url") or "").netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _to_date(groups, kind):
    try:
        if kind == "ymd":
            y, m, d = int(groups[0]), int(groups[1]), int(groups[2])
        elif kind == "dmy":
            d, m, y = int(groups[0]), int(groups[1]), int(groups[2])
        elif kind == "d_mon_y":
            d, m, y = int(groups[0]), _MONTHS[groups[1][:3].lower()], int(groups[2])
        else:
            m, d, y = _MONTHS[groups[0][:3].lower()], int(groups[1]), int(groups[2])
        return date(y, m, d)
    except (ValueError, KeyError):
        return None


def closing_dates(text):
    """Full dates that follow a closing-date word within a few characters. A bare day ('Submission: 26') is skipped:
    we never guess the month."""
    out = []
    for k in _CLOSING_RE.finditer(text or ""):
        window = text[k.end():k.end() + _NEAR + 24]
        best = None
        for rx, kind in _DATE_PATTERNS:
            m = rx.search(window)
            if m and m.start() <= _NEAR and (best is None or m.start() < best[0]):
                d = _to_date(m.groups(), kind)
                if d:
                    best = (m.start(), d)
        if best and best[1] not in out:
            out.append(best[1])
    return out


def _fmt(d):
    return f"{d.day} {d.strftime('%b %Y')}"


def classify(result, tender):
    """Signals for one search result that already names the bid. -> [{kind, site, url, quote, detail}]"""
    text = _BOILERPLATE.sub(" ", " ".join(filter(None, [result.get("title"), result.get("snippet")])))
    base = {"site": _site(result), "url": result.get("url") or "", "quote": (result.get("snippet") or result.get("title") or "").strip()}
    found = [dict(base, kind=kind, detail=f"{base['site']} {what}") for kind, rx, what in KINDS if rx.search(text)]
    try:
        gem_close = date.fromisoformat((tender.get("closes") or "")[:10])
    except ValueError:
        gem_close = None
    if gem_close:
        for d in closing_dates(text):
            if d != gem_close:
                when = "later than" if d > gem_close else "earlier than"
                found.append(dict(base, kind="date_mismatch",
                                  detail=f"{base['site']} shows {_fmt(d)}, {when} GeM's closing date {_fmt(gem_close)}"))
                break
    return found


def _summary(listed, signals):
    if not listed:
        return "No other tender site lists this bid yet."
    sites = f"Listed on {len(listed)} site{'s' if len(listed) != 1 else ''}"
    if not signals:
        return sites + "; none mention a corrigendum, extension, cancellation or a different closing date."
    kinds = {"corrigendum": "a corrigendum", "extension": "an extension", "cancelled": "a cancellation",
             "retender": "a re-tender", "date_mismatch": "a different closing date"}
    seen = [kinds[k] for k in kinds if any(s["kind"] == k for s in signals)]
    flagged = len({s["site"] for s in signals})
    what = seen[0] if len(seen) == 1 else ", ".join(seen[:-1]) + " and " + seen[-1]
    return f"{sites}; {flagged} {'shows' if flagged == 1 else 'show'} {what}. Check GeM before bidding."


def queries(bid):
    return [f'"{bid}"', f'"{bid}" corrigendum OR extension']


def build(tender, payloads, ms=0):
    """Turn raw TinyFish Search payloads ([{"results": [...]}, ...]) into the Bid watch result. Pure: no network."""
    bid = tender.get("bid") or ""
    listed, signals, seen_sites, seen_signals = [], [], set(), set()
    for p in payloads:
        for r in (p or {}).get("results") or []:
            hay = " ".join(filter(None, [r.get("title"), r.get("snippet"), r.get("url")]))
            if not mentions_bid(hay, bid) or about_other_bid(r, bid):
                continue
            site = _site(r)
            if site not in seen_sites:
                seen_sites.add(site)
                listed.append({"site": site, "url": r.get("url") or "", "title": r.get("title") or "",
                               "snippet": r.get("snippet") or ""})
            for s in classify(r, tender):
                if (s["site"], s["kind"]) not in seen_signals:
                    seen_signals.add((s["site"], s["kind"]))
                    signals.append(s)
    return {"query": " | ".join(queries(bid)), "ms": ms,
            "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "listed_on": listed, "signals": signals, "summary": _summary(listed, signals), "cached": False}


def cache_path(bid):
    return CACHE_DIR / (re.sub(r"[^A-Za-z0-9]+", "-", bid).strip("-") + ".json")


def _read_cache(bid):
    try:
        return json.loads(cache_path(bid).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_cache(bid, result):
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_path(bid).write_text(json.dumps(dict(result, _ts=time.time()), ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass  # read-only disk (Vercel): serve the live result uncached


def _public(c, cached=True):
    out = {k: v for k, v in c.items() if not k.startswith("_")}
    out["cached"] = cached
    return out


def web_signals(tender, use_cache=True, live=True):
    """Bid watch for one tender. Never raises: failures come back as {"error": "..."}.
    live=False answers from the cache only (no TinyFish call)."""
    try:
        bid = (tender or {}).get("bid")
        if not bid_key(bid or ""):
            return {"error": "this tender has no GeM bid number to search for"}
        cached = _read_cache(bid) if (use_cache or not live) else None
        if cached and (not live or time.time() - cached.get("_ts", 0) < TTL_SECONDS):
            return _public(cached)
        if not live:
            return {"error": "no saved web signals for this bid yet"}

        t0 = time.perf_counter()
        payloads, errors = [], []
        for q in queries(bid):
            try:
                payloads.append(sources.tinyfish_search(q))
            except sources.SourceError as e:
                errors.append(str(e))
        if not payloads:
            return {"error": errors[0] if errors else "TinyFish Search returned nothing"}
        result = build(tender, payloads, ms=int((time.perf_counter() - t0) * 1000))
        if errors:
            result["partial"] = errors
        _write_cache(bid, result)
        return result
    except Exception as e:  # the page must still render if anything unexpected happens
        return {"error": f"web signals failed: {e}"}
