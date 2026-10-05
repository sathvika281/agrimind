import logging
import os
import re
import threading
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.main import app
from app.models import Analysis
from app.routers import health
from app.services import http as H
from app.services import storage, weather
from app.services.ai import AIServiceError, AnalysisContext, analyze, service
from app.services.ai.demo_provider import DemoAIProvider
from app.services.ai.gemini_provider import GeminiProvider
from tests.conftest import SLEEPS, make_client
from tests.test_phase2 import PNG, WX, FakeWeather, _farm, _post, gemini_http, gemini_reply, uploads_count
from tests.test_phase3 import mk

TO = httpx.Timeout(5.0)
SECRET_KEY = "super-secret-gemini-key-123"


def client_with(handler):
    calls = []

    def wrapped(request):
        calls.append(request)
        return handler(request, len(calls))

    return httpx.Client(transport=httpx.MockTransport(wrapped)), calls


def timeout_error(request):
    raise httpx.ReadTimeout("slow", request=request)


@pytest.fixture()
def logs():
    """Capture the 'agrimind' logs (propagation is off by design, so attach directly)."""
    buf = []

    class H_(logging.Handler):
        def emit(self, record):
            buf.append(self.format(record))

    handler = H_()
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
    lg = logging.getLogger("agrimind")
    lg.addHandler(handler)
    old = lg.level
    lg.setLevel(logging.DEBUG)
    yield buf
    lg.removeHandler(handler)
    lg.setLevel(old)


# ============================ resilient HTTP helper ============================
def test_helper_retries_transient_timeout_once_then_succeeds():
    c, calls = client_with(lambda r, n: timeout_error(r) if n == 1 else httpx.Response(200, json={"ok": 1}))
    data, attempts = H.request_json("GET", "https://x.test/a", client=c, timeout=TO)
    assert data == {"ok": 1} and attempts == 2 and len(calls) == 2 and SLEEPS == [0.6]


def test_helper_gives_up_after_exactly_one_retry():
    c, calls = client_with(lambda r, n: timeout_error(r))
    with pytest.raises(H.Transient) as e:
        H.request_json("GET", "https://x.test/a", client=c, timeout=TO)
    assert len(calls) == 2 and e.value.attempts == 2 and e.value.category == "timeout"


@pytest.mark.parametrize("status", [500, 502, 503, 504, 408, 429])
def test_helper_retries_transient_http_statuses(status):
    c, calls = client_with(lambda r, n: httpx.Response(status, text="boom") if n == 1 else httpx.Response(200, json={"a": 1}))
    assert H.request_json("GET", "https://x.test/a", client=c, timeout=TO)[1] == 2
    assert len(calls) == 2


def test_helper_connection_errors_are_transient():
    def boom(r, n):
        raise httpx.ConnectError("refused", request=r)

    c, calls = client_with(boom)
    with pytest.raises(H.Transient):
        H.request_json("GET", "https://x.test/a", client=c, timeout=TO)
    assert len(calls) == 2


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_helper_never_retries_permanent_errors(status):
    c, calls = client_with(lambda r, n: httpx.Response(status, text="nope"))
    with pytest.raises(H.Permanent) as e:
        H.request_json("GET", "https://x.test/a", client=c, timeout=TO)
    assert len(calls) == 1 and SLEEPS == [] and e.value.status == status


def test_helper_bad_body_and_oversize_are_permanent_and_not_retried():
    c, calls = client_with(lambda r, n: httpx.Response(200, text="<html>not json</html>"))
    with pytest.raises(H.Permanent) as e:
        H.request_json("GET", "https://x.test/a", client=c, timeout=TO)
    assert e.value.category == "bad_response" and len(calls) == 1
    c, calls = client_with(lambda r, n: httpx.Response(200, content=b"[" + b"1," * 5000 + b"1]"))
    with pytest.raises(H.Permanent) as e:
        H.request_json("GET", "https://x.test/a", client=c, timeout=TO, max_bytes=1000)
    assert e.value.category == "response_too_large" and len(calls) == 1


def test_helper_retries_zero_means_single_attempt():
    c, calls = client_with(lambda r, n: httpx.Response(503))
    with pytest.raises(H.Transient):
        H.request_json("GET", "https://x.test/a", client=c, timeout=TO, retries=0)
    assert len(calls) == 1


def test_helper_enforces_a_hard_wall_clock_cap_even_if_the_server_is_slow():
    """httpx timeouts are per-phase; the deadline must bound the WHOLE attempt."""

    def slow(request, n):
        time.sleep(1.5)  # a stalled upstream
        return httpx.Response(200, json={"late": True})

    c, calls = client_with(slow)
    t = time.perf_counter()
    with pytest.raises(H.Transient) as e:
        H.request_json("GET", "https://x.test/a", client=c, timeout=httpx.Timeout(30.0), deadline=H._clock() + 0.3, retries=1)
    elapsed = time.perf_counter() - t
    assert elapsed < 1.0, f"call was not capped (took {elapsed:.2f}s)"
    assert e.value.category == "timeout" and len(calls) == 1  # no retry: backoff would pass the deadline


def test_helper_respects_deadline_and_skips_retry(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(H, "_clock", lambda: now[0])
    c, calls = client_with(lambda r, n: httpx.Response(503))
    with pytest.raises(H.Transient):
        # backoff 0.6 would run past the 0.5 s deadline -> no retry, no sleep
        H.request_json("GET", "https://x.test/a", client=c, timeout=TO, deadline=100.5)
    assert len(calls) == 1 and SLEEPS == []
    # already expired deadline -> no call at all
    c2, calls2 = client_with(lambda r, n: httpx.Response(200, json={}))
    now[0] = 200.0
    with pytest.raises(H.Transient) as e:
        H.request_json("GET", "https://x.test/a", client=c2, timeout=TO, deadline=150.0)
    assert e.value.category == "deadline" and calls2 == []


# ============================ Gemini reliability (mocked) ============================
def gemini(handler, key=SECRET_KEY):
    c, calls = client_with(handler)
    return GeminiProvider(api_key=key, http=c), calls


CTX = AnalysisContext(crop="Rice", symptoms="The lower leaves are yellow and have brown spots")


def test_gemini_timeout_retries_once_then_clean_error(logs):
    p, calls = gemini(lambda r, n: timeout_error(r))
    with pytest.raises(AIServiceError) as e:
        analyze(CTX, p)
    assert len(calls) == 2 and "temporarily unavailable" in str(e.value)
    assert e.value.code == "ai_unavailable"
    assert any("gemini_failed kind=transient category=timeout" in line and "attempts=2" in line for line in logs)


def test_gemini_500_is_retried_once_and_can_recover():
    p, calls = gemini(lambda r, n: httpx.Response(500) if n == 1 else httpx.Response(200, json=gemini_reply(mk())))
    out = analyze(CTX, p)
    assert len(calls) == 2 and out.likely_issue


def test_gemini_persistent_500_fails_cleanly_after_one_retry():
    p, calls = gemini(lambda r, n: httpx.Response(500, text="internal " + SECRET_KEY))
    with pytest.raises(AIServiceError) as e:
        analyze(CTX, p)
    assert len(calls) == 2 and SECRET_KEY not in str(e.value) and "internal" not in str(e.value)


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_gemini_permanent_errors_are_not_retried(status, logs):
    p, calls = gemini(lambda r, n: httpx.Response(status, text="API key not valid " + SECRET_KEY))
    with pytest.raises(AIServiceError) as e:
        analyze(CTX, p)
    assert len(calls) == 1 and SLEEPS == []
    assert SECRET_KEY not in str(e.value) and not any(SECRET_KEY in line for line in logs)
    assert any("kind=permanent" in line for line in logs)


def test_gemini_malformed_response_is_not_retried():
    p, calls = gemini(lambda r, n: httpx.Response(200, json=gemini_reply("not json at all")))
    with pytest.raises(AIServiceError):
        analyze(CTX, p)
    assert len(calls) == 1


def test_gemini_never_logs_key_or_prompt_content(logs):
    p, calls = gemini(lambda r, n: timeout_error(r))
    with pytest.raises(AIServiceError):
        analyze(AnalysisContext(crop="Rice", symptoms="my private farm note: gate code 9981"), p)
    text = "\n".join(logs)
    assert SECRET_KEY not in text and "gate code" not in text and "9981" not in text


def test_no_silent_fallback_to_demo_when_gemini_fails(register, monkeypatch):
    monkeypatch.setattr(service, "get_provider", lambda: gemini(lambda r, n: httpx.Response(500))[0])
    c = register()
    r = _post(c, _farm(c), image=PNG)
    assert r.status_code == 503 and r.json()["code"] == "ai_unavailable"
    assert c.get("/analyses").json() == [] and uploads_count() == 0
    assert "demo" not in r.text.lower()


# ============================ weather reliability + caching ============================
class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def geo_ok(name="Guntur"):
    return {"results": [{"name": name, "admin1": "Andhra Pradesh", "country": "India", "latitude": 16.3, "longitude": 80.4}]}


FORECAST = {
    "current": {"temperature_2m": 30.5, "relative_humidity_2m": 80, "precipitation": 0.0, "wind_speed_10m": 7.2},
    "daily": {
        "temperature_2m_max": [30, 31, 32, 33, 34, 33, 32],
        "temperature_2m_min": [22, 23, 24, 25, 24, 23, 22],
        "precipitation_sum": [5.0, 10.0, None, 0.0, 4.0, 6.0, 4.0],
    },
}


def wx_client(handler, clock=None):
    c, calls = client_with(handler)
    return weather.WeatherClient(http=c, clock=clock or FakeClock()), calls


def ok_handler(request, n):
    return httpx.Response(200, json=geo_ok() if "geocoding" in request.url.host else FORECAST)


def test_weather_geocode_timeout_is_retried_then_succeeds():
    wc, calls = wx_client(lambda r, n: timeout_error(r) if n == 1 else ok_handler(r, n))
    w = wc.fetch("Guntur")
    assert w.temperature_c == 30.5 and len(calls) == 3  # geocode x2 + forecast


def test_weather_total_failure_is_bounded_and_try_weather_never_raises():
    wc, calls = wx_client(lambda r, n: httpx.Response(500))
    with pytest.raises(weather.WeatherError):
        wc.fetch("Guntur")
    assert len(calls) == 2  # one attempt + exactly one retry, then stop
    old = weather.client
    weather.client = wc
    try:
        wx, note = weather.try_weather("Guntur")
    finally:
        weather.client = old
    assert wx is None and "could not be retrieved" in note


def test_weather_forecast_failure_after_good_geocode_is_non_fatal():
    def handler(r, n):
        return httpx.Response(200, json=geo_ok()) if "geocoding" in r.url.host else httpx.Response(503)

    wc, _ = wx_client(handler)
    with pytest.raises(weather.WeatherError):
        wc.fetch("Guntur")


def test_weather_permanent_failure_is_not_retried():
    wc, calls = wx_client(lambda r, n: httpx.Response(400, text="bad"))
    with pytest.raises(weather.WeatherError):
        wc.fetch("Guntur")
    assert len(calls) == 1


def test_coordinates_are_cached_and_expire():
    clock = FakeClock()
    wc, calls = wx_client(ok_handler, clock)
    wc.resolve_location("Guntur")
    wc.resolve_location("  guntur ")
    assert len(calls) == 1
    clock.t += weather.COORD_TTL + 1
    wc.resolve_location("Guntur")
    assert len(calls) == 2


def test_weather_result_is_cached_with_original_fetched_at_then_refreshed():
    clock = FakeClock()
    wc, calls = wx_client(ok_handler, clock)
    first = wc.fetch("Guntur")
    n = len(calls)
    second = wc.fetch("Guntur")
    assert len(calls) == n and second.fetched_at == first.fetched_at and first.fetched_at.endswith("+00:00")
    clock.t += weather.WEATHER_TTL + 1
    wc.fetch("Guntur")
    assert len(calls) == n + 1  # forecast refetched (coordinates still cached)


def test_unknown_location_is_negatively_cached_but_transient_errors_are_not():
    clock = FakeClock()
    wc, calls = wx_client(lambda r, n: httpx.Response(200, json={}), clock)
    for _ in range(3):
        with pytest.raises(weather.LocationNotFound):
            wc.fetch("Zzqx Nowhere")
    assert len(calls) == 1  # one geocode request, then served from the negative cache
    clock.t += weather.MISSING_TTL + 1
    with pytest.raises(weather.LocationNotFound):
        wc.fetch("Zzqx Nowhere")
    assert len(calls) == 2
    # a transient failure is never cached as a result: after the short cooldown it tries again and succeeds
    state = {"fail": True}

    def flaky(r, n):
        return httpx.Response(503) if state["fail"] else ok_handler(r, n)

    clock2 = FakeClock()
    wc2, calls2 = wx_client(flaky, clock2)
    with pytest.raises(weather.WeatherError):
        wc2.fetch("Guntur")
    state["fail"] = False
    clock2.t += weather.COOLDOWN_S + 1
    assert wc2.fetch("Guntur").temperature_c == 30.5


def test_transient_failure_starts_a_cooldown_so_the_next_analysis_does_not_wait_again():
    clock = FakeClock()
    state = {"fail": True}
    wc, calls = wx_client(lambda r, n: httpx.Response(503) if state["fail"] else ok_handler(r, n), clock)
    with pytest.raises(weather.WeatherError):
        wc.fetch("Guntur")
    made = len(calls)
    state["fail"] = False
    for _ in range(3):  # during the cooldown: instant failure, NO network requests
        with pytest.raises(weather.WeatherError) as e:
            wc.fetch("Guntur")
        assert str(e.value) == "cooldown"
    assert len(calls) == made
    clock.t += weather.COOLDOWN_S + 1
    assert wc.fetch("Guntur").temperature_c == 30.5


def test_cached_weather_is_still_served_during_a_cooldown():
    wc, calls = wx_client(ok_handler)
    first = wc.fetch("Guntur")
    wc._cooldown_until = wc._clock() + 100
    assert wc.fetch("Guntur").fetched_at == first.fetched_at


def test_permanent_weather_errors_do_not_trigger_a_cooldown():
    wc, calls = wx_client(lambda r, n: httpx.Response(400, text="bad"))
    for _ in range(2):
        with pytest.raises(weather.WeatherError):
            wc.fetch("Guntur")
    assert len(calls) == 2  # each attempt really tried (no cooldown, and no retry within an attempt)


def test_weather_budget_is_short():
    assert weather.BUDGET_S <= 4.0 and weather.TIMEOUT.read <= 2.0


def test_weather_cache_is_size_bounded():
    wc, _ = wx_client(ok_handler)
    for i in range(weather.MAX_ENTRIES + 20):
        wc._coords.put(f"k{i}", (1.0, 2.0, "x"), 1000)
    assert len(wc._coords._d) <= weather.MAX_ENTRIES


def test_analysis_continues_when_weather_times_out_or_500s(register, monkeypatch):
    for handler in (lambda r, n: timeout_error(r), lambda r, n: httpx.Response(500)):
        wc, _ = wx_client(handler)
        monkeypatch.setattr(weather, "client", wc)
        c = register(f"w{id(handler)}@example.com")
        r = _post(c, _farm(c))
        d = r.json()
        assert r.status_code == 201 and d["weather"] is None and d["weather_note"]


def test_geocoding_failure_still_allows_analysis(register, monkeypatch):
    wc, _ = wx_client(lambda r, n: httpx.Response(200, json={}))
    monkeypatch.setattr(weather, "client", wc)
    c = register()
    r = _post(c, _farm(c, "Zzqx"))
    assert r.status_code == 201 and "could not be found" in r.json()["weather_note"]


def test_fetched_at_is_exposed_and_persisted(register, monkeypatch):
    wc, _ = wx_client(ok_handler)
    monkeypatch.setattr(weather, "client", wc)
    c = register()
    d = _post(c, _farm(c)).json()
    assert d["weather"]["fetched_at"]
    assert c.get(f"/analyses/{d['id']}").json()["weather"]["fetched_at"] == d["weather"]["fetched_at"]


# ============================ idempotency ============================
class Counting:
    name = "counting"

    def __init__(self, delay=0.0):
        self.calls = 0
        self.delay = delay
        self.lock = threading.Lock()

    def analyze(self, ctx):
        with self.lock:
            self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        return DemoAIProvider().analyze(ctx)


@pytest.fixture()
def counting(monkeypatch):
    p = Counting()
    monkeypatch.setattr(service, "get_provider", lambda: p)
    return p


def post_key(c, farm_id, key, crop="Tomato", symptoms="yellow leaves with spots", image=None):
    data = {"farm_id": str(farm_id), "crop": crop, "symptoms": symptoms}
    files = {"image": ("a.png", image, "image/png")} if image is not None else None
    return c.post("/analyses", data=data, files=files, headers={"Idempotency-Key": key} if key else {})


def test_same_key_twice_returns_same_analysis_and_calls_ai_once(register, counting):
    c = register()
    fid = _farm(c)
    first = post_key(c, fid, "key-aaaaaaaa-0001")
    second = post_key(c, fid, "key-aaaaaaaa-0001")
    assert first.status_code == 201 and second.status_code == 200
    assert second.headers["idempotent-replay"] == "true" and "idempotent-replay" not in first.headers
    assert first.json() == second.json() and counting.calls == 1
    assert len(c.get("/analyses").json()) == 1


def test_json_body_also_supports_the_key(register, counting):
    c = register()
    body = {"farm_id": _farm(c), "crop": "Tomato", "symptoms": "yellow leaves"}
    h = {"Idempotency-Key": "json-key-00000001"}
    a, b = c.post("/analyses", json=body, headers=h), c.post("/analyses", json=body, headers=h)
    assert a.json()["id"] == b.json()["id"] and counting.calls == 1


def test_different_keys_or_no_key_create_separate_analyses(register, counting):
    c = register()
    fid = _farm(c)
    post_key(c, fid, "key-aaaaaaaa-0001")
    post_key(c, fid, "key-aaaaaaaa-0002")
    post_key(c, fid, None)
    post_key(c, fid, None)
    assert len(c.get("/analyses").json()) == 4


def test_invalid_key_is_ignored_not_trusted(register, counting):
    c = register()
    fid = _farm(c)
    for bad in ("x", "short", "has space in it 12345", "a" * 65, "semi;colon-12345"):
        post_key(c, fid, bad)
    assert len(c.get("/analyses").json()) == 5 and counting.calls == 5


def test_key_reused_with_different_input_is_a_conflict_and_never_returns_the_old_result(register, counting):
    c = register()
    fid = _farm(c)
    other_farm = _farm(c)
    first = post_key(c, fid, "key-conflict-0001").json()
    variants = [
        dict(crop="Chilli"),
        dict(symptoms="completely different problem description"),
        dict(image=PNG),
    ]
    for kw in variants:
        r = post_key(c, fid, "key-conflict-0001", **kw)
        assert r.status_code == 409 and r.json()["code"] == "idempotency_conflict"
        assert str(first["id"]) not in r.text and "likely_issue" not in r.text
    assert post_key(c, other_farm, "key-conflict-0001").status_code == 409
    assert len(c.get("/analyses").json()) == 1 and counting.calls == 1
    assert uploads_count() == 0  # conflict never stores the image


def test_cosmetic_differences_still_replay(register, counting):
    c = register()
    fid = _farm(c)
    a = post_key(c, fid, "key-cosmetic-0001", crop="Tomato", symptoms="yellow   leaves  with spots")
    b = post_key(c, fid, "key-cosmetic-0001", crop="  tomato ", symptoms="yellow leaves with spots")
    assert b.status_code == 200 and a.json()["id"] == b.json()["id"]


def test_key_is_scoped_to_the_authenticated_user(register, counting):
    a = register("a@example.com")
    b = register("b@example.com")
    fa, fb = _farm(a), _farm(b)
    ra = post_key(a, fa, "shared-key-00000001").json()
    rb = post_key(b, fb, "shared-key-00000001")  # same key string, different user
    assert rb.status_code == 201 and rb.json()["id"] != ra["id"] and counting.calls == 2
    assert rb.json()["farm_name"] and len(b.get("/analyses").json()) == 1
    # B cannot use A's farm, with or without A's key
    assert post_key(b, fa, "shared-key-00000001").status_code in (404, 409)
    r = post_key(b, fa, "brand-new-key-00001")
    assert r.status_code == 404 and str(ra["id"]) not in r.text
    assert [x["id"] for x in a.get("/analyses").json()] == [ra["id"]]


def test_retry_after_failure_is_not_blocked_and_after_success_replays_even_if_ai_now_fails(register, monkeypatch):
    c = register()
    fid = _farm(c)

    class Boom:
        name = "boom"

        def analyze(self, ctx):
            raise RuntimeError("down")

    monkeypatch.setattr(service, "get_provider", lambda: Boom())
    assert post_key(c, fid, "key-retry-00000001").status_code == 503  # failed: key not consumed
    good = Counting()
    monkeypatch.setattr(service, "get_provider", lambda: good)
    ok = post_key(c, fid, "key-retry-00000001")
    assert ok.status_code == 201
    monkeypatch.setattr(service, "get_provider", lambda: Boom())  # "timed out client retries" later
    again = post_key(c, fid, "key-retry-00000001")
    assert again.status_code == 200 and again.json()["id"] == ok.json()["id"]


def test_concurrent_duplicates_create_exactly_one_analysis(register, monkeypatch):
    slow = Counting(delay=0.5)
    monkeypatch.setattr(service, "get_provider", lambda: slow)
    c = register()
    fid = _farm(c)
    results = []

    def worker():
        cc = make_client()
        cc.cookies.update(c.cookies)
        results.append(post_key(cc, fid, "key-parallel-00001"))

    threads = [threading.Thread(target=worker) for _ in range(3)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(r.status_code for r in results) == [200, 200, 201]
    assert len({r.json()["id"] for r in results}) == 1 and slow.calls == 1
    assert len(c.get("/analyses").json()) == 1


# ============================ database atomicity / image cleanup ============================
def test_commit_failure_rolls_back_cleans_image_and_server_stays_usable(register, monkeypatch, logs):
    c = register()
    fid = _farm(c)
    real_commit = Session.commit
    state = {"fail": True}

    def flaky_commit(self):
        if state["fail"] and any(isinstance(o, Analysis) for o in self.new):
            raise RuntimeError("db is down: secret-internal-detail")
        return real_commit(self)

    monkeypatch.setattr(Session, "commit", flaky_commit)
    r = _post(c, fid, image=PNG)
    assert r.status_code == 500
    body = r.json()
    assert body["code"] == "server_error" and body["request_id"] == r.headers["x-request-id"]
    assert "secret-internal-detail" not in r.text and "Traceback" not in r.text
    assert uploads_count() == 0  # image written before the failed commit was removed
    assert any("analysis_persist_failed" in line and "image_cleaned=True" in line for line in logs)
    state["fail"] = False
    assert c.get("/analyses").json() == []  # nothing partially stored
    assert _post(c, fid, image=PNG).status_code == 201  # server still works
    assert uploads_count() == 1


def test_image_storage_failure_is_a_clean_503_and_nothing_is_stored(register, monkeypatch):
    c = register()
    fid = _farm(c)

    def broken_save(data, ext):
        raise OSError("disk full at C:\\secret\\path")

    monkeypatch.setattr(storage.storage, "save", broken_save)
    r = _post(c, fid, image=PNG)
    assert r.status_code == 503 and r.json()["code"] == "storage_unavailable"
    assert "secret" not in r.text and "disk" not in r.text
    assert c.get("/analyses").json() == []
    # text-only analyses don't touch storage and still work
    assert c.post("/analyses", json={"farm_id": fid, "crop": "Rice", "symptoms": "yellow leaves"}).status_code == 201


def test_ai_failure_after_image_upload_leaves_no_orphan(register, monkeypatch):
    c = register()
    fid = _farm(c)
    monkeypatch.setattr(service, "get_provider", lambda: gemini(lambda r, n: timeout_error(r))[0])
    r = _post(c, fid, image=PNG)
    assert r.status_code == 503 and uploads_count() == 0 and c.get("/analyses").json() == []


def test_orphan_sweep_removes_only_old_unreferenced_files(register):
    c = register()
    fid = _farm(c)
    kept = _post(c, fid, image=PNG).json()
    ref = storage.storage.read  # noqa: F841 (keep reference semantics obvious)
    root = settings.uploads_dir
    old_orphan = storage.storage.save(PNG, "png")
    new_orphan = storage.storage.save(PNG, "png")
    long_ago = time.time() - 7200
    os.utime(root / old_orphan, (long_ago, long_ago))
    referenced_file = next(p.name for p in root.iterdir() if p.name not in (old_orphan, new_orphan))
    os.utime(root / referenced_file, (long_ago, long_ago))  # old but referenced -> must stay
    with SessionLocal() as db:
        referenced = {a.image_path for a in db.query(Analysis).all() if a.image_path}
    assert referenced == {referenced_file}
    assert storage.sweep_orphans(referenced) == 1
    names = {p.name for p in root.iterdir()}
    assert names == {referenced_file, new_orphan}
    assert c.get(f"/analyses/{kept['id']}/image").status_code == 200


def test_orphan_sweep_ignores_foreign_filenames(register):
    root = settings.uploads_dir
    root.mkdir(parents=True, exist_ok=True)
    (root / "notes.txt").write_text("keep me")
    old = time.time() - 7200
    os.utime(root / "notes.txt", (old, old))
    assert storage.sweep_orphans(set()) == 0 and (root / "notes.txt").exists()


# ============================ image / upload safety ============================
def test_oversized_body_is_rejected_early_with_friendly_message(register):
    c = register()
    huge = PNG + b"0" * (settings.max_image_bytes + 400_000)  # beyond limit + multipart overhead
    r = _post(c, _farm(c), image=huge)
    assert r.status_code == 413 and r.json()["code"] == "image_too_large"
    assert "too large" in r.json()["detail"] and uploads_count() == 0


def test_oversized_chunked_body_is_cut_off_without_content_length(register):
    c = register()
    fid = _farm(c)

    def gen():
        yield b"--b\r\nContent-Disposition: form-data; name=\"farm_id\"\r\n\r\n" + str(fid).encode() + b"\r\n"
        for _ in range(40):
            yield b"0" * 100_000  # 4 MB total, streamed with no Content-Length

    r = c.post("/analyses", content=gen(), headers={"Content-Type": "multipart/form-data; boundary=b"})
    assert r.status_code == 413 and uploads_count() == 0


def test_other_endpoints_have_a_small_body_limit(client):
    r = client.post("/auth/register", content=b"x" * 200_000, headers={"Content-Type": "application/json"})
    assert r.status_code == 413 and r.json()["code"] == "payload_too_large"


def test_malformed_but_magic_valid_images_do_not_crash_the_server(register):
    c = register()
    fid = _farm(c)
    for blob in (PNG[:8], b"\xff\xd8\xff" + os.urandom(500), b"RIFF\x00\x00\x00\x00WEBP" + os.urandom(300)):
        mime = "image/png" if blob.startswith(b"\x89PNG") else "image/jpeg" if blob.startswith(b"\xff\xd8") else "image/webp"
        r = _post(c, fid, image=blob, ctype=mime)
        assert r.status_code == 201  # never decoded server-side
    assert _post(c, fid, image=b"\x00" * 100, ctype="image/png").status_code == 422
    assert c.get("/health").status_code == 200


# ============================ request ids / error model / headers ============================
def test_request_id_is_generated_when_missing(client):
    r = client.get("/health")
    assert re.fullmatch(r"[0-9a-f]{32}", r.headers["x-request-id"])
    assert r.headers["x-request-id"] != client.get("/health").headers["x-request-id"]


def test_valid_request_id_is_preserved(client):
    r = client.get("/health", headers={"X-Request-ID": "client-req.ID_123"})
    assert r.headers["x-request-id"] == "client-req.ID_123"


@pytest.mark.parametrize("bad", ["short", "has space in it", "a" * 65, "semi;colon;id!!", "<script>alert(1)</script>"])
def test_invalid_request_id_is_replaced(client, bad):
    r = client.get("/health", headers={"X-Request-ID": bad})
    rid = r.headers["x-request-id"]
    assert rid != bad and re.fullmatch(r"[0-9a-f]{32}", rid)


def test_request_id_appears_in_logs_and_5xx_bodies(register, monkeypatch, logs):
    c = register()
    monkeypatch.setattr(service, "get_provider", lambda: gemini(lambda r, n: httpx.Response(500))[0])
    r = _post(c, _farm(c))
    rid = r.headers["x-request-id"]
    assert r.status_code == 503 and r.json()["request_id"] == rid
    c.get("/farms", headers={"X-Request-ID": "trace-me-0000001"})
    assert any("method=GET path=/farms status=200" in line for line in logs)


def test_access_log_has_method_path_status_duration_and_no_query_or_secrets(register, logs):
    c = register()
    c.get("/analyses?token=abc-secret-query&x=1")
    token = c.cookies.get("agrimind_token")
    text = "\n".join(logs)
    assert re.search(r"request method=GET path=/analyses status=200 duration_ms=\d+", text)
    assert "abc-secret-query" not in text and (token or "") not in text and "password123" not in text


def test_error_model_has_code_everywhere_and_4xx_bodies_stay_identical(register, client):
    assert client.get("/farms").json() == {"detail": "Please log in to continue.", "code": "unauthorized"}
    c = register()
    assert c.get("/farms/999999").json() == {"detail": "Farm not found.", "code": "not_found"}
    r = c.post("/farms", json={"name": ""})
    assert r.status_code == 422 and r.json()["code"] == "invalid_request" and "Farm name" in r.json()["detail"]
    assert c.get("/no-such-route").json()["code"] == "not_found"
    assert "request_id" not in c.get("/farms/999999").json()


def test_security_headers_present_and_image_cache_policy_kept(register):
    c = register()
    r = c.get("/farms")
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "no-referrer" and r.headers["cache-control"] == "no-store"
    aid = _post(c, _farm(c), image=PNG).json()["id"]
    img = c.get(f"/analyses/{aid}/image")
    assert img.headers["cache-control"].startswith("private") and img.headers["x-content-type-options"] == "nosniff"


def test_unhandled_exception_is_a_clean_500_with_id_and_server_survives(register, monkeypatch):
    c = register()
    from app.routers import farms as farms_router

    def explode(*a, **k):
        raise RuntimeError("kaboom secret-detail")

    monkeypatch.setattr(farms_router, "get_owned_farm", explode)
    r = c.get("/farms/1")
    assert r.status_code == 500 and r.json()["code"] == "server_error"
    assert r.json()["request_id"] == r.headers["x-request-id"]
    assert "kaboom" not in r.text and "Traceback" not in r.text
    monkeypatch.undo()
    assert c.get("/farms").status_code == 200


# ============================ health ============================
def test_health_is_plain_liveness(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_dependencies_degrade_without_failing_the_endpoint(client, monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    r = client.get("/health/dependencies")  # weather probe is patched to "unreachable" in conftest
    d = r.json()
    assert r.status_code == 200 and d["status"] == "degraded"
    assert d["database"] == "ok" and d["weather"] == "unavailable"
    assert d["ai"] == {"provider": "gemini", "status": "not_configured"}


def test_dependencies_ok_when_everything_is_healthy(client, monkeypatch):
    monkeypatch.setattr(weather, "check_reachable", lambda: True)
    d = client.get("/health/dependencies").json()
    assert d["status"] == "ok" and d["ai"] == {"provider": "demo", "status": "ok"}


def test_dependencies_never_expose_secrets_or_error_text(client, monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", SECRET_KEY)

    def boom():
        raise RuntimeError("upstream exploded: " + SECRET_KEY)

    monkeypatch.setattr(weather, "check_reachable", boom)
    r = client.get("/health/dependencies")
    assert SECRET_KEY not in r.text and "exploded" not in r.text
    assert r.status_code == 200 and r.json()["weather"] == "unavailable" and r.json()["ai"]["status"] == "ok"


def test_database_down_marks_dependencies_unavailable_but_liveness_stays_ok(client, monkeypatch):
    monkeypatch.setattr(health, "_db_ok", lambda: False)
    r = client.get("/health/dependencies")
    assert r.status_code == 503 and r.json()["status"] == "unavailable" and r.json()["database"] == "unavailable"
    assert client.get("/health").status_code == 200


def test_external_outage_never_breaks_core_endpoints(register, monkeypatch):
    c = register()
    monkeypatch.setattr(weather, "client", FakeWeather(exc=weather.WeatherError("down")))
    assert c.get("/health").status_code == 200 and c.get("/farms").status_code == 200
    assert _post(c, _farm(c)).status_code == 201


# ============================ rate limiting ============================
def bad_login(c, email="victim@example.com"):
    return c.post("/auth/login", json={"email": email, "password": "wrong-password-1"})


def test_login_is_limited_per_account_with_retry_after(register, monkeypatch):
    monkeypatch.setenv("RL_LOGIN_PER_EMAIL", "3")
    register("victim@example.com")
    c = make_client()
    assert [bad_login(c).status_code for _ in range(3)] == [401, 401, 401]
    r = bad_login(c)
    assert r.status_code == 429 and r.json()["code"] == "rate_limited" and int(r.headers["retry-after"]) >= 1
    assert "wait" in r.json()["detail"].lower()
    # another account from the same IP is unaffected
    register("other@example.com")
    assert c.post("/auth/login", json={"email": "other@example.com", "password": "password123"}).status_code == 200


def test_successful_login_resets_the_account_counter(register, monkeypatch):
    monkeypatch.setenv("RL_LOGIN_PER_EMAIL", "3")
    register("victim@example.com")
    c = make_client()
    for _ in range(2):
        assert bad_login(c).status_code == 401
    assert c.post("/auth/login", json={"email": "victim@example.com", "password": "password123"}).status_code == 200
    for _ in range(2):
        assert bad_login(c).status_code == 401  # counter was cleared by the success


def test_register_is_limited_per_ip(monkeypatch, client):
    monkeypatch.setenv("RL_REGISTER_PER_IP", "2")
    codes = [client.post("/auth/register", json={"email": f"u{i}@example.com", "password": "password123"}).status_code for i in range(3)]
    assert codes == [201, 201, 429]


def test_analysis_limit_is_per_user_and_blocks_before_work(register, monkeypatch, counting):
    monkeypatch.setenv("RL_ANALYSIS_PER_USER", "2")
    a = register("a@example.com")
    b = register("b@example.com")
    fa, fb = _farm(a), _farm(b)
    assert [_post(a, fa).status_code for _ in range(2)] == [201, 201]
    r = _post(a, fa, image=PNG)
    assert r.status_code == 429 and r.json()["code"] == "rate_limited" and "retry-after" in r.headers
    assert counting.calls == 2 and uploads_count() == 0  # blocked before parsing/AI/storage
    assert _post(b, fb).status_code == 201  # other user unaffected


def test_rate_limiting_can_be_disabled(register, monkeypatch):
    monkeypatch.setenv("RL_LOGIN_PER_EMAIL", "1")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    register("victim@example.com")
    c = make_client()
    assert all(bad_login(c).status_code == 401 for _ in range(5))


def test_default_limits_are_generous_for_normal_use(register):
    register("farmer1@example.com")
    c = make_client()
    for _ in range(25):  # far more than any manual testing session
        assert c.post("/auth/login", json={"email": "farmer1@example.com", "password": "password123"}).status_code == 200
    for _ in range(12):
        assert bad_login(c, "farmer1@example.com").status_code in (401,)  # still below the per-account cap of 15
