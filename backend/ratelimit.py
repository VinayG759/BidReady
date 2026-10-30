"""Per-client request limits: a sliding window of timestamps per (bucket, client IP).

Kept in memory on purpose: limits reset when the server restarts, and each serverless instance on Vercel counts
on its own. That is enough to stop a visitor from draining Claude or Sarvam credits by accident or for fun; it is
not a billing-grade quota.
"""

import threading
import time
from collections import deque

from fastapi import HTTPException

HOUR = 3600

_hits = {}            # (bucket, ip) -> deque of timestamps
_lock = threading.Lock()


def client_ip(request):
    """The visitor's address. Vercel sits in front, so the first X-Forwarded-For entry is the real client."""
    fwd = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if fwd:
        return fwd
    return request.client.host if request.client else "unknown"


def allow(bucket, key, limit, window=HOUR):
    """Record one request; False when `key` already made `limit` requests in the last `window` seconds."""
    now = time.time()
    with _lock:
        q = _hits.setdefault((bucket, key), deque())
        while q and q[0] <= now - window:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        # drop other clients' empty windows now and then so memory stays small
        if len(_hits) > 5000:
            for k in [k for k, v in _hits.items() if not v or v[-1] <= now - window]:
                _hits.pop(k, None)
        return True


def enforce(request, bucket, limit, detail, window=HOUR):
    """Raise 429 with a plain-language detail when this client is over the limit."""
    if not allow(bucket, client_ip(request), limit, window):
        raise HTTPException(429, detail)


def reset():
    with _lock:
        _hits.clear()
