"""Resilient JSON-over-HTTP helper used for Gemini and Open-Meteo.

- split timeouts, an overall `deadline`, and a streamed response-size cap
- strictly bounded retry (default 1 retry) with short backoff
- TRANSIENT (retried): timeouts, connection/transport errors, HTTP 408/429/5xx
- PERMANENT (never retried): other 4xx (bad key/request/model), non-JSON, oversize
Failures carry only a category/status/attempt count: never bodies, URLs or keys.
"""
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

import httpx

_sleep = time.sleep  # patched in tests
_clock = time.monotonic  # patched in tests

MAX_BYTES = 1_000_000
TRANSIENT_STATUS = {408, 429}


class HttpFailure(Exception):
    transient = False

    def __init__(self, category: str, status: int | None = None, attempts: int = 1):
        super().__init__(category)
        self.category = category
        self.status = status
        self.attempts = attempts


class Transient(HttpFailure):
    transient = True


class Permanent(HttpFailure):
    transient = False


def _timeout_for(base: httpx.Timeout, remaining: float | None) -> httpx.Timeout:
    if remaining is None:
        return base
    r = max(0.1, remaining)

    def cap(v):
        return min(v, r) if v is not None else r

    return httpx.Timeout(connect=cap(base.connect), read=cap(base.read), write=cap(base.write), pool=cap(base.pool))


def _once(client: httpx.Client, method: str, url: str, timeout: httpx.Timeout, max_bytes: int, **kw):
    try:
        with client.stream(method, url, timeout=timeout, **kw) as r:
            status = r.status_code
            if status in TRANSIENT_STATUS or status >= 500:
                raise Transient(f"http_{status}", status)
            if status < 200 or status >= 300:
                raise Permanent(f"http_{status}", status)
            buf = bytearray()
            for chunk in r.iter_bytes():
                buf += chunk
                if len(buf) > max_bytes:
                    raise Permanent("response_too_large", status)
    except HttpFailure:
        raise
    except (httpx.TimeoutException,):
        raise Transient("timeout") from None
    except (httpx.NetworkError, httpx.ProtocolError):
        raise Transient("connection") from None
    except httpx.HTTPError:
        raise Permanent("http_error") from None
    import json

    try:
        return json.loads(bytes(buf))
    except ValueError:
        raise Permanent("bad_response", status) from None


_pool = ThreadPoolExecutor(max_workers=16, thread_name_prefix="agri-http")


def _attempt(client, method, url, timeout, max_bytes, remaining, kw):
    """One attempt. httpx timeouts apply per phase (connect / TLS / read) and DNS is unbounded, so
    their sum can exceed the budget. When there is a deadline, enforce a hard wall-clock cap by
    waiting on a worker thread; an abandoned worker ends on its own within httpx's phase timeouts."""

    def run():
        if client is not None:
            return _once(client, method, url, timeout, max_bytes, **kw)
        with httpx.Client() as c:
            return _once(c, method, url, timeout, max_bytes, **kw)

    if remaining is None:
        return run()
    fut = _pool.submit(run)
    try:
        return fut.result(timeout=max(0.05, remaining))
    except FutureTimeout:
        fut.cancel()
        raise Transient("timeout") from None


def request_json(
    method: str,
    url: str,
    *,
    timeout: httpx.Timeout,
    client: httpx.Client | None = None,
    retries: int = 1,
    backoff: float = 0.6,
    deadline: float | None = None,  # absolute time on `_clock`
    max_bytes: int = MAX_BYTES,
    **kw,
):
    """Return (parsed_json, attempts). Raises Transient / Permanent (with .attempts)."""
    attempt = 0
    while True:
        attempt += 1
        remaining = None if deadline is None else deadline - _clock()
        if remaining is not None and remaining <= 0:
            raise Transient("deadline", attempts=attempt - 1 or 1)
        try:
            data = _attempt(client, method, url, _timeout_for(timeout, remaining), max_bytes, remaining, kw)
            return data, attempt
        except HttpFailure as e:
            e.attempts = attempt
            if not e.transient or attempt > retries:
                raise
            wait = backoff * attempt
            if deadline is not None and _clock() + wait >= deadline:
                raise
            _sleep(wait)
