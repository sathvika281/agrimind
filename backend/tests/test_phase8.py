"""Phase 8 hardening: authorization matrix, token edge cases and input-contract boundaries.

All on the scratch test database (see conftest); never touches the live database.
"""
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


def _farm(c, name="A farm", location="Guntur"):
    return c.post("/farms", json={"name": name, "location": location, "soil_type": "Red soil"}).json()["id"]


def _check(c, farm_id, crop="Rice", symptoms="yellow leaves with brown spots", language="en"):
    r = c.post("/analyses", json={"farm_id": farm_id, "crop": crop, "symptoms": symptoms, "language": language})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _same(a, b):
    return a.status_code == b.status_code and a.json() == b.json()


# ---------------- authorization matrix: User A must learn nothing about User B's resources ----------------
def test_authorization_matrix_foreign_equals_missing(register):
    a = register("a@example.com")
    b = register("b@example.com")
    farm_b = _farm(b)
    an_b = _check(b, farm_b)

    cases = [
        ("get", f"/farms/{farm_b}", "/farms/999999"),
        ("get", f"/farms/{farm_b}/weather", "/farms/999999/weather"),
        ("get", f"/analyses/{an_b}", "/analyses/999999"),
        ("get", f"/analyses/{an_b}/image", "/analyses/999999/image"),
    ]
    for method, foreign, missing in cases:
        rf, rm = getattr(a, method)(foreign), getattr(a, method)(missing)
        assert rf.status_code == 404, foreign
        assert _same(rf, rm), f"{foreign} leaks existence"

    rf = a.post(f"/analyses/{an_b}/translate", json={"language": "te"})
    rm = a.post("/analyses/999999/translate", json={"language": "te"})
    assert rf.status_code == 404 and _same(rf, rm)

    # creating a check against someone else's farm is the same 404 as a missing farm
    body = {"crop": "Rice", "symptoms": "yellow leaves"}
    rf = a.post("/analyses", json={**body, "farm_id": farm_b})
    rm = a.post("/analyses", json={**body, "farm_id": 999999})
    assert rf.status_code == 404 and _same(rf, rm)

    # B's data is unchanged and A's lists are empty
    assert a.get("/analyses").json() == [] and a.get("/farms").json() == []
    assert len(b.get("/analyses").json()) == 1


def test_garbage_ids_are_clean_422_not_500(register):
    a = register()
    for path in ("/farms/abc", "/farms/-1/weather", "/analyses/abc", "/analyses/1.5/image", "/analyses/99999999999999999999"):
        r = a.get(path)
        assert r.status_code in (404, 422), (path, r.status_code)
    assert a.post("/analyses/abc/translate", json={"language": "te"}).status_code == 422

    # Regression (Phase 8): an id beyond SQLite's INTEGER range used to reach the driver and return 500.
    huge = 99999999999999999999
    missing = a.get("/farms/999999")
    for path in (f"/farms/{huge}", f"/farms/{huge}/weather", f"/analyses/{huge}", f"/analyses/{huge}/image", "/farms/0", "/farms/-1"):
        r = a.get(path)
        assert r.status_code == 404 and r.json()["detail"].endswith("not found."), path
    assert a.get(f"/farms/{huge}").json() == missing.json()
    assert a.post(f"/analyses/{huge}/translate", json={"language": "te"}).status_code == 404
    r = a.post("/analyses", json={"farm_id": huge, "crop": "Rice", "symptoms": "yellow leaves"})
    assert r.status_code == 404 and r.json() == missing.json()
    for bad in ({"farm_id": "abc"}, {"farm_id": None}, {"farm_id": -5}, {"farm_id": 1.5}, {}):
        r = a.post("/analyses", json={"crop": "Rice", "symptoms": "yellow leaves", **bad})
        assert r.status_code in (404, 422), (bad, r.status_code)


def _client_with_cookie(value):
    c = TestClient(app)
    c.cookies.set(settings.cookie_name, value)
    return c


def test_bad_tokens_are_401(register):
    register()  # make sure tables exist
    now = datetime.now(timezone.utc)
    secret = settings.jwt_secret
    tokens = {
        "garbage": "not-a-jwt",
        "empty-ish": ".",
        "expired": jwt.encode({"sub": "1", "exp": now - timedelta(minutes=1)}, secret, algorithm="HS256"),
        "wrong-secret": jwt.encode({"sub": "1", "exp": now + timedelta(hours=1)}, "x" * 40, algorithm="HS256"),
        "no-exp": jwt.encode({"sub": "1"}, secret, algorithm="HS256"),
        "alg-none": jwt.encode({"sub": "1", "exp": now + timedelta(hours=1)}, None, algorithm="none"),
        "non-numeric-sub": jwt.encode({"sub": "abc", "exp": now + timedelta(hours=1)}, secret, algorithm="HS256"),
        "missing-user": jwt.encode({"sub": "987654", "exp": now + timedelta(hours=1)}, secret, algorithm="HS256"),
    }
    for name, tok in tokens.items():
        c = _client_with_cookie(tok)
        for path in ("/auth/me", "/farms", "/analyses"):
            r = c.get(path)
            assert r.status_code == 401, (name, path, r.status_code)
            assert r.json()["detail"] == "Please log in to continue."


def test_valid_token_for_a_deleted_user_is_rejected(register):
    from app.database import SessionLocal
    from app.models import User

    c = register("gone@example.com")
    assert c.get("/auth/me").status_code == 200
    with SessionLocal() as db:
        db.delete(db.query(User).filter_by(email="gone@example.com").one())
        db.commit()
    assert c.get("/auth/me").status_code == 401


def test_error_bodies_do_not_leak_internals(register):
    a = register()
    for r in (a.get("/farms/999999"), a.get("/analyses/abc"), a.post("/analyses", json={"farm_id": 1}), TestClient(app).get("/farms")):
        text = r.text
        assert "Traceback" not in text and "sqlalchemy" not in text.lower() and 'File "' not in text


# ---------------- contract / validation boundaries ----------------
def test_farm_input_boundaries(register):
    a = register()
    assert a.post("/farms", json={"name": "x" * 121}).status_code == 422
    assert a.post("/farms", json={"name": "ok", "location": "y" * 201}).status_code == 422
    assert a.post("/farms", json={"name": "ok", "soil_type": "z" * 101}).status_code == 422
    assert a.post("/farms", json={"name": "x" * 120}).status_code == 201
    assert a.post("/farms", json={"name": 123}).status_code == 422
    assert a.post("/farms", content=b"{bad json", headers={"content-type": "application/json"}).status_code == 422
    r = a.post("/farms", json={"name": "  Trim me  ", "location": "  Tenali "})
    assert r.json()["name"] == "Trim me" and r.json()["location"] == "Tenali"


def test_analysis_input_boundaries(register):
    a = register()
    fid = _farm(a)
    base = {"farm_id": fid, "crop": "Rice", "symptoms": "yellow leaves"}
    # whitespace-only input counts as missing
    assert a.post("/analyses", json={**base, "symptoms": "   "}).status_code == 422
    assert a.post("/analyses", json={**base, "crop": "   "}).status_code == 422
    assert a.post("/analyses", json={**base, "crop": "x" * 101}).status_code == 422
    assert a.post("/analyses", json={**base, "symptoms": "s" * 5001}).status_code == 422
    assert a.post("/analyses", json={**base, "language": "fr"}).status_code == 422
    assert a.post("/analyses", json={**base, "crop": 5}).status_code == 422
    assert a.post("/analyses", json={**base, "symptoms": ["list"]}).status_code == 422
    # still nothing was stored by the rejected requests
    assert a.get("/analyses").json() == []
    # a valid one works and the response matches the contract the frontend relies on
    r = a.post("/analyses", json=base)
    assert r.status_code == 201
    out = r.json()
    for key in ("id", "farm_id", "farm_name", "crop", "symptoms", "language", "input_type", "has_image", "result", "weather", "weather_note", "translations", "created_at"):
        assert key in out, key
    assert out["weather"] is None and isinstance(out["weather_note"], str)  # offline weather: null + note, never invented
    assert out["created_at"].endswith(("Z", "+00:00"))  # explicit UTC so the browser never guesses the zone


def test_translate_rejects_bad_language(register):
    a = register()
    an = _check(a, _farm(a))
    for lang in ("fr", "", None, 5):
        assert a.post(f"/analyses/{an}/translate", json={"language": lang}).status_code == 422


def test_weather_endpoint_without_location_is_a_note_not_fake_data(register):
    a = register()
    fid = a.post("/farms", json={"name": "No place"}).json()["id"]
    r = a.get(f"/farms/{fid}/weather")
    assert r.status_code == 200
    assert r.json()["weather"] is None and r.json()["note"]


def test_login_and_register_contract(register, client):
    assert client.post("/auth/login", json={"email": "nobody@example.com", "password": "password123"}).status_code == 401
    assert client.post("/auth/login", json={"email": "not-an-email", "password": "x"}).status_code == 422
    assert client.post("/auth/register", json={"email": "a@example.com", "password": "short"}).status_code == 422
    assert client.post("/auth/register", json={"email": "a@example.com", "password": "p" * 73}).status_code == 422
    assert client.post("/auth/login", json={"email": "a@example.com"}).status_code == 422
    # email is case-insensitive and trimmed
    register("Case@Example.com")
    c = TestClient(app)
    assert c.post("/auth/login", json={"email": "  case@example.COM ", "password": "password123"}).status_code == 200
    assert c.post("/auth/register", json={"email": "CASE@example.com", "password": "password123"}).status_code == 409


@pytest.mark.parametrize("path", ["/farms", "/analyses", "/analyses/1", "/analyses/1/image", "/farms/1/weather", "/auth/me"])
def test_every_data_route_requires_login(client, path):
    assert client.get(path).status_code == 401


# ---------------- AI failure kinds: truthful 503, no row, no invented advice ----------------
class _Prov:
    name = "stub"

    def __init__(self, behaviour):
        self.behaviour = behaviour

    def analyze(self, ctx):
        if isinstance(self.behaviour, Exception):
            raise self.behaviour
        return self.behaviour


_GOOD = {"likely_issue": "x", "explanation": "y", "recommended_actions": ["a"], "precautions": ["p"], "uncertainty": "u"}


@pytest.mark.parametrize(
    "behaviour",
    [
        RuntimeError("provider exploded with secret-ish details"),
        TimeoutError("slow"),
        {},  # incomplete
        {"likely_issue": "only this"},  # incomplete
        {**_GOOD, "recommended_actions": "not a list"},  # invalid schema
        {**_GOOD, "recommended_actions": []},  # nothing actionable
        None,  # unexpected response
        "garbage string",
    ],
)
def test_ai_failures_are_truthful_503_and_store_nothing(register, monkeypatch, behaviour):
    from app.services.ai import service

    monkeypatch.setattr(service, "get_provider", lambda: _Prov(behaviour))
    a = register()
    fid = _farm(a)
    r = a.post("/analyses", json={"farm_id": fid, "crop": "Rice", "symptoms": "yellow leaves"})
    assert r.status_code == 503, r.text
    body = r.json()
    assert body["code"] and "request_id" in body
    assert "exploded" not in r.text and "Traceback" not in r.text  # provider internals never reach the user
    assert "likely_issue" not in r.text and "recommended_actions" not in r.text  # nothing fabricated
    assert a.get("/analyses").json() == []
