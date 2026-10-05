import json
import os
from pathlib import Path

import httpx
import pytest

from app.config import settings
from app.schemas import AnalysisResult
from app.services import images, weather
from app.services.ai import AIServiceError, AnalysisContext, ImageInput, WeatherContext, analyze, service
from app.services.ai.base import AnalysisContext as Ctx
from app.services.ai.demo_provider import DemoAIProvider
from app.services.ai.gemini_provider import NOT_CONFIGURED, GeminiProvider

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
WEBP = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 32

GOOD_MODEL_JSON = {
    "likely_issue": "Possible nutrient deficiency",
    "explanation": "Yellowing may indicate a deficiency.",
    "observations": ["Yellow lower leaves"],
    "recommended_actions": ["Check soil moisture", "Compare with healthy plants", "Take a soil test"],
    "precautions": ["Wear gloves"],
    "severity": "low",
    "when_to_seek_help": "If it spreads quickly.",
    "uncertainty": "Cause not confirmed.",
}


def gemini_http(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def gemini_reply(payload):
    return {"candidates": [{"content": {"parts": [{"text": payload if isinstance(payload, str) else json.dumps(payload)}]}}]}


def uploads_count() -> int:
    d = settings.uploads_dir
    return len(list(d.iterdir())) if d.exists() else 0


def _farm(c, location="Guntur"):
    return c.post("/farms", json={"name": "F", "location": location, "soil_type": "Red soil"}).json()["id"]


def _post(c, farm_id, crop="Tomato", symptoms="yellow leaves", image=None, ctype="image/png", name="leaf.png"):
    data = {"farm_id": str(farm_id), "crop": crop, "symptoms": symptoms}
    files = {"image": (name, image, ctype)} if image is not None else None
    return c.post("/analyses", data=data, files=files)


class Capture:
    name = "capture"

    def __init__(self):
        self.ctx = None

    def analyze(self, ctx):
        self.ctx = ctx
        return DemoAIProvider().analyze(ctx)


@pytest.fixture()
def capture(monkeypatch):
    cap = Capture()
    monkeypatch.setattr(service, "get_provider", lambda: cap)
    return cap


class FakeWeather:
    def __init__(self, wx=None, exc=None):
        self.wx, self.exc = wx, exc

    def fetch(self, location):
        if self.exc:
            raise self.exc
        return self.wx


WX = WeatherContext(
    location_name="Guntur, Andhra Pradesh, India", temperature_c=31.0, humidity_pct=82.0,
    precipitation_mm=0.2, wind_kmh=9.0, temp_min_c=24.0, temp_max_c=33.0,
    past_3d_rain_mm=22.5, next_3d_rain_mm=14.0, trend="22.5 mm of rain in the last 3 days",
)


# ---------------- AI providers ----------------
def test_demo_provider_still_works_with_new_fields():
    out = analyze(Ctx(crop="Tomato", symptoms="yellow leaves"), DemoAIProvider())
    assert isinstance(out, AnalysisResult) and out.severity == "unknown" and out.when_to_seek_help


def test_gemini_provider_instantiates_and_model_is_configurable(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "some-other-model")
    assert GeminiProvider().model == "some-other-model"
    monkeypatch.delenv("GEMINI_MODEL")
    assert GeminiProvider().model  # has a default from config only


def test_gemini_without_key_raises_clean_error(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(AIServiceError) as e:
        analyze(Ctx(crop="a", symptoms="b"), GeminiProvider())
    assert str(e.value) == NOT_CONFIGURED


def test_api_with_gemini_selected_and_no_key_is_503_and_no_fallback(register, monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "gemini")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    c = register()
    r = _post(c, _farm(c), image=PNG)
    assert r.status_code == 503
    assert "GEMINI_API_KEY" in r.json()["detail"]
    assert c.get("/analyses").json() == []  # nothing stored, no demo output
    assert uploads_count() == 0  # image not saved on failure


def test_unknown_provider_name_is_clean_error(register, monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "nope")
    c = register()
    assert _post(c, _farm(c)).status_code == 503


def test_gemini_success_with_mocked_http_sends_image_weather_and_key_in_header():
    seen = {}

    def handler(request: httpx.Request):
        seen["body"] = json.loads(request.content)
        seen["headers"] = request.headers
        seen["url"] = str(request.url)
        return httpx.Response(200, json=gemini_reply(GOOD_MODEL_JSON))

    p = GeminiProvider(api_key="secret-key-123", model="m1", http=gemini_http(handler))
    ctx = AnalysisContext(crop="Rice", symptoms="yellow", farm_location="Guntur",
                          image=ImageInput(PNG, "image/png"), weather=WX)
    out = analyze(ctx, p)
    assert out.severity == "low" and out.observations == ["Yellow lower leaves"]
    body = seen["body"]
    parts = body["contents"][0]["parts"]
    assert any("inline_data" in x for x in parts)
    assert "22.5" in parts[0]["text"] and "Rice" in parts[0]["text"]
    assert seen["headers"]["x-goog-api-key"] == "secret-key-123"
    assert "secret-key-123" not in seen["url"] and "secret-key-123" not in json.dumps(body)
    assert "m1:generateContent" in seen["url"]
    sys_prompt = body["systemInstruction"]["parts"][0]["text"]
    for word in ("OBSERVATION", "LIKELY INTERPRETATION", "RECOMMENDED NEXT STEP", "UNCERTAINTY"):
        assert word in sys_prompt


def test_gemini_without_weather_says_not_available():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=gemini_reply(GOOD_MODEL_JSON))

    analyze(Ctx(crop="Rice", symptoms="x"), GeminiProvider(api_key="k", http=gemini_http(handler)))
    assert "Weather context: not available" in seen["body"]["contents"][0]["parts"][0]["text"]
    assert not any("inline_data" in p for p in seen["body"]["contents"][0]["parts"])


@pytest.mark.parametrize(
    "reply",
    [
        gemini_reply("this is not json"),
        gemini_reply({"likely_issue": "x"}),
        gemini_reply({**GOOD_MODEL_JSON, "recommended_actions": []}),
        gemini_reply({**GOOD_MODEL_JSON, "recommended_actions": "nope"}),
        gemini_reply("[1, 2, 3]"),
        {"candidates": []},
        {"promptFeedback": {"blockReason": "SAFETY"}},
    ],
)
def test_gemini_malformed_output_is_rejected(reply):
    p = GeminiProvider(api_key="k", http=gemini_http(lambda r: httpx.Response(200, json=reply)))
    with pytest.raises(AIServiceError) as e:
        analyze(Ctx(crop="a", symptoms="b"), p)
    assert "temporarily unavailable" in str(e.value)


def test_gemini_http_failure_is_clean_and_does_not_leak_key():
    p = GeminiProvider(api_key="super-secret-key", http=gemini_http(lambda r: httpx.Response(500, text="boom super-secret-key")))
    with pytest.raises(AIServiceError) as e:
        analyze(Ctx(crop="a", symptoms="b"), p)
    assert "super-secret-key" not in str(e.value)

    def raise_timeout(request):
        raise httpx.ConnectTimeout("timeout", request=request)

    p = GeminiProvider(api_key="super-secret-key", http=gemini_http(raise_timeout))
    with pytest.raises(AIServiceError) as e:
        analyze(Ctx(crop="a", symptoms="b"), p)
    assert "super-secret-key" not in str(e.value)


def test_invalid_model_output_is_not_stored_via_api(register, monkeypatch):
    class Bad:
        name = "bad"

        def analyze(self, ctx):
            return {"likely_issue": "x"}

    monkeypatch.setattr(service, "get_provider", lambda: Bad())
    c = register()
    r = _post(c, _farm(c), image=PNG)
    assert r.status_code == 503 and "Traceback" not in r.text
    assert c.get("/analyses").json() == [] and uploads_count() == 0


# ---------------- image validation ----------------
def test_validate_image_accepts_supported_types():
    for data, mime in ((PNG, "image/png"), (JPG, "image/jpeg"), (WEBP, "image/webp"), (JPG, "image/jpg")):
        assert images.validate_image(data, mime, 1000).mime_type in images.ALLOWED


@pytest.mark.parametrize(
    "data,mime",
    [
        (b"hello world, not an image", "image/png"),
        (b"<svg xmlns='http://www.w3.org/2000/svg'></svg>", "image/svg+xml"),
        (PNG, "image/jpeg"),  # declared type disagrees with content
        (PNG, "application/pdf"),
        (PNG, None),
        (b"GIF89a....", "image/gif"),
    ],
)
def test_validate_image_rejects(data, mime):
    with pytest.raises(images.ImageError) as e:
        images.validate_image(data, mime, 1000)
    assert e.value.status == 422 and "supported image" in e.value.message


def test_validate_image_too_large_and_empty():
    with pytest.raises(images.ImageError) as e:
        images.validate_image(PNG + b"0" * 2000, "image/png", 1000)
    assert e.value.status == 413
    with pytest.raises(images.ImageError):
        images.validate_image(b"", "image/png", 1000)


def test_api_accepts_valid_images(register):
    c = register()
    fid = _farm(c)
    for data, mime, name in ((PNG, "image/png", "a.png"), (JPG, "image/jpeg", "b.jpg"), (WEBP, "image/webp", "c.webp")):
        r = _post(c, fid, image=data, ctype=mime, name=name)
        assert r.status_code == 201, r.text
        assert r.json()["has_image"] is True


def test_api_rejects_unsupported_and_spoofed_files(register):
    c = register()
    fid = _farm(c)
    r = _post(c, fid, image=b"just text", ctype="text/plain", name="notes.txt")
    assert r.status_code == 422 and "supported image" in r.json()["detail"]
    r = _post(c, fid, image=b"<?php echo 1; ?>", ctype="image/png", name="shell.png")  # spoofed
    assert r.status_code == 422
    assert uploads_count() == 0 and c.get("/analyses").json() == []


def test_api_rejects_oversized_image(register):
    c = register()
    big = PNG + b"0" * (settings.max_image_bytes + 10)
    r = _post(c, _farm(c), image=big)
    assert r.status_code == 413 and "too large" in r.json()["detail"]
    assert uploads_count() == 0


def test_uploaded_filename_is_never_used(register):
    c = register()
    r = _post(c, _farm(c), image=PNG, name="../../etc/passwd.png")
    assert r.status_code == 201
    names = [p.name for p in Path(settings.uploads_dir).iterdir()]
    assert len(names) == 1 and "passwd" not in names[0] and names[0].endswith(".png") and len(names[0]) == 36


# ---------------- analysis modes ----------------
def test_text_only_json_still_works(register, capture):
    c = register()
    r = c.post("/analyses", json={"farm_id": _farm(c), "crop": "Tomato", "symptoms": "yellow leaves"})
    assert r.status_code == 201
    d = r.json()
    assert d["input_type"] == "text" and d["has_image"] is False
    assert capture.ctx.image is None and capture.ctx.input_type == "text"


def test_image_only_analysis(register, capture):
    c = register()
    r = _post(c, _farm(c), symptoms="", image=PNG)
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["input_type"] == "image" and d["has_image"] and d["symptoms"] == ""
    assert capture.ctx.image.mime_type == "image/png" and capture.ctx.image.data == PNG
    assert capture.ctx.symptoms == ""


def test_text_plus_image_analysis(register, capture):
    c = register()
    r = _post(c, _farm(c), symptoms="spots on leaves", image=JPG, ctype="image/jpeg", name="x.jpg")
    assert r.status_code == 201
    assert r.json()["input_type"] == "text+image"
    assert capture.ctx.input_type == "text+image" and capture.ctx.symptoms == "spots on leaves"


def test_neither_text_nor_image_rejected(register):
    c = register()
    r = _post(c, _farm(c), symptoms="  ")
    assert r.status_code == 422 and "photo" in r.json()["detail"]


def test_result_schema_validates_with_new_fields(register):
    c = register()
    d = _post(c, _farm(c), image=PNG).json()
    AnalysisResult.model_validate(d["result"])
    for k in ("severity", "observations", "when_to_seek_help"):
        assert k in d["result"]


# ---------------- weather ----------------
def test_weather_success_is_in_context_and_response(register, capture, monkeypatch):
    monkeypatch.setattr(weather, "client", FakeWeather(wx=WX))
    c = register()
    r = _post(c, _farm(c))
    assert r.status_code == 201
    d = r.json()
    assert capture.ctx.weather.humidity_pct == 82.0
    assert d["weather"]["temperature_c"] == 31.0 and d["weather_note"] is None
    # persisted and reloaded
    again = c.get(f"/analyses/{d['id']}").json()
    assert again["weather"]["past_3d_rain_mm"] == 22.5


@pytest.mark.parametrize("exc", [weather.WeatherError("down"), weather.LocationNotFound("x"), RuntimeError("weird"), httpx.ReadTimeout("slow")])
def test_weather_failure_is_non_fatal(register, capture, monkeypatch, exc):
    monkeypatch.setattr(weather, "client", FakeWeather(exc=exc))
    c = register()
    r = _post(c, _farm(c))
    assert r.status_code == 201
    d = r.json()
    assert d["weather"] is None and d["weather_note"] and capture.ctx.weather is None


def test_unresolved_or_empty_location_does_not_crash(register, capture):
    c = register()
    r = _post(c, _farm(c, location=""))
    assert r.status_code == 201 and r.json()["weather"] is None and "no location" in r.json()["weather_note"]


def _openmeteo_handler(request: httpx.Request):
    if "geocoding" in request.url.host:
        if request.url.params["name"].startswith("Nowhere"):
            return httpx.Response(200, json={})
        return httpx.Response(200, json={"results": [{"name": "Guntur", "admin1": "Andhra Pradesh", "country": "India", "latitude": 16.3, "longitude": 80.4}]})
    return httpx.Response(200, json={
        "current": {"temperature_2m": 30.5, "relative_humidity_2m": 80, "precipitation": 0.0, "wind_speed_10m": 7.2},
        "daily": {
            "temperature_2m_max": [30, 31, 32, 33, 34, 33, 32],
            "temperature_2m_min": [22, 23, 24, 25, 24, 23, 22],
            "precipitation_sum": [5.0, 10.0, None, 0.0, 4.0, 6.0, 4.0],
        },
    })


def test_open_meteo_client_parsing_and_cache():
    calls = []

    def handler(req):
        calls.append(str(req.url))
        return _openmeteo_handler(req)

    wc = weather.WeatherClient(http=httpx.Client(transport=httpx.MockTransport(handler)))
    w = wc.fetch("Guntur, Andhra Pradesh")
    assert w.location_name == "Guntur, Andhra Pradesh, India"
    assert w.temperature_c == 30.5 and w.humidity_pct == 80
    assert w.past_3d_rain_mm == 15.0 and w.next_3d_rain_mm == 14.0
    assert w.temp_max_c == 33 and w.temp_min_c == 25
    n = len(calls)
    wc.resolve_location("guntur,  andhra pradesh")
    assert len(calls) == n  # coordinates cached


def test_open_meteo_unknown_location_raises():
    wc = weather.WeatherClient(http=httpx.Client(transport=httpx.MockTransport(_openmeteo_handler)))
    with pytest.raises(weather.LocationNotFound):
        wc.fetch("Nowhere-land")


def test_try_weather_never_raises(monkeypatch):
    monkeypatch.setattr(weather, "client", FakeWeather(exc=ValueError("x")))
    wx, note = weather.try_weather("Guntur")
    assert wx is None and "could not be retrieved" in note


# ---------------- ownership of images ----------------
def test_owner_can_fetch_image_with_safe_headers(register):
    c = register()
    aid = _post(c, _farm(c), image=PNG).json()["id"]
    r = c.get(f"/analyses/{aid}/image")
    assert r.status_code == 200 and r.content == PNG
    assert r.headers["content-type"] == "image/png" and r.headers["x-content-type-options"] == "nosniff"


def test_other_user_cannot_fetch_image_and_gets_same_404_as_missing(register):
    a = register("a@example.com")
    b = register("b@example.com")
    aid = _post(a, _farm(a), image=PNG).json()["id"]
    foreign = b.get(f"/analyses/{aid}/image")
    missing = b.get("/analyses/999999/image")
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()
    assert b.get(f"/analyses/{aid}").status_code == 404
    assert b.get("/analyses").json() == []


def test_image_requires_auth_and_text_analysis_has_no_image(register, client):
    c = register()
    aid = _post(c, _farm(c)).json()["id"]
    assert c.get(f"/analyses/{aid}/image").status_code == 404
    client.cookies.clear()
    assert client.get(f"/analyses/{aid}/image").status_code == 401


def test_uploads_are_not_publicly_served(register, client):
    c = register()
    _post(c, _farm(c), image=PNG)
    name = next(Path(settings.uploads_dir).iterdir()).name
    for path in (f"/uploads/{name}", f"/static/{name}", f"/{name}"):
        assert client.get(path).status_code == 404


def test_image_ref_cannot_traverse_paths():
    from app.services.storage import LocalImageStorage

    s = LocalImageStorage()
    for bad in ("../test.db", "..\\x.png", "a" * 32 + ".png/../x", "/etc/passwd", ""):
        assert s.read(bad) is None


def test_image_analysis_belongs_to_submitting_user(register):
    a = register("a@example.com")
    b = register("b@example.com")
    _post(a, _farm(a), image=PNG)
    assert len(a.get("/analyses").json()) == 1 and b.get("/analyses").json() == []
    assert _post(b, _farm(a), image=PNG).status_code == 404  # foreign farm


# ---------------- migration & history ----------------
def test_migration_adds_columns_and_preserves_phase1_rows(tmp_path):
    import sqlite3

    from sqlalchemy import create_engine, text

    from app.database import migrate

    dbfile = tmp_path / "old.db"
    con = sqlite3.connect(dbfile)
    con.executescript(
        """
        CREATE TABLE users (id INTEGER PRIMARY KEY, email VARCHAR(255) UNIQUE, password_hash VARCHAR(255), created_at DATETIME);
        CREATE TABLE farms (id INTEGER PRIMARY KEY, user_id INTEGER, name VARCHAR(120), location VARCHAR(200), soil_type VARCHAR(100), created_at DATETIME);
        CREATE TABLE analyses (id INTEGER PRIMARY KEY, user_id INTEGER, farm_id INTEGER, crop VARCHAR(100), symptoms TEXT,
                               language VARCHAR(10), result_json JSON, created_at DATETIME);
        INSERT INTO users VALUES (1,'o@example.com','x','2026-01-01 00:00:00');
        INSERT INTO farms VALUES (1,1,'Old farm','Guntur','Red','2026-01-01 00:00:00');
        INSERT INTO analyses VALUES (1,1,1,'Tomato','yellow','en',
          '{"likely_issue":"Old","explanation":"e","recommended_actions":["a"],"precautions":["p"],"uncertainty":"u"}','2026-01-01 00:00:00');
        """
    )
    con.commit()
    con.close()
    eng = create_engine(f"sqlite:///{dbfile}")
    added = migrate(eng)
    assert {"analyses.image_path", "analyses.input_type", "analyses.weather_json", "analyses.weather_note"} <= set(added)
    assert migrate(eng) == []  # idempotent
    with eng.connect() as conn:
        row = conn.execute(text("SELECT crop, input_type, image_path FROM analyses WHERE id=1")).one()
    assert row == ("Tomato", "text", None)


def test_phase1_style_stored_result_still_renders(register):
    """A row whose result_json lacks the Phase 2 fields must still load via the API."""
    from app.database import SessionLocal
    from app.models import Analysis

    c = register()
    fid = _farm(c)
    uid = c.get("/auth/me").json()["id"]
    with SessionLocal() as db:
        db.add(Analysis(
            user_id=uid, farm_id=fid, crop="Rice", symptoms="old", language="en",
            result_json={"likely_issue": "Old issue", "explanation": "e", "recommended_actions": ["a"],
                         "precautions": ["p"], "uncertainty": "u"},
        ))
        db.commit()
    items = c.get("/analyses").json()
    assert items[0]["result"]["likely_issue"] == "Old issue"
    assert items[0]["input_type"] == "text" and items[0]["has_image"] is False and items[0]["weather"] is None


def test_history_shows_input_type(register):
    c = register()
    fid = _farm(c)
    _post(c, fid)
    _post(c, fid, image=PNG)
    kinds = [a["input_type"] for a in c.get("/analyses").json()]
    assert kinds == ["text+image", "text"]
    assert [a["has_image"] for a in c.get("/analyses").json()] == [True, False]
