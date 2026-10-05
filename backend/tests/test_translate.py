"""POST /analyses/{id}/translate: write the SAME check again in the other language (one cached model call)."""
import sqlite3

import pytest

from app.database import SessionLocal, migrate
from app.models import Analysis
from app.services import weather
from app.services.ai import service
from app.services.ai.demo_provider import DemoAIProvider
from tests.test_phase2 import PNG, WX, FakeWeather, _farm, _post
from tests.test_phase6 import SYMPTOMS_TE, TELUGU, te_payload


class Counting:
    name = "counting"

    def __init__(self, payload_for=None):
        self.calls = []
        self.payload_for = payload_for

    def analyze(self, ctx):
        self.calls.append(ctx)
        return self.payload_for(ctx) if self.payload_for else DemoAIProvider().analyze(ctx)


@pytest.fixture()
def prov(monkeypatch):
    p = Counting()
    monkeypatch.setattr(service, "get_provider", lambda: p)
    return p


def make_te(c, image=None, farm_kw=None):
    fid = c.post("/farms", json={"name": "F", "location": "Guntur", "soil_type": "Red soil", **(farm_kw or {})}).json()["id"]
    data = {"farm_id": str(fid), "crop": "టమాటా", "symptoms": SYMPTOMS_TE, "language": "te"}
    files = {"image": ("a.png", image, "image/png")} if image else None
    r = c.post("/analyses", data=data, files=files)
    assert r.status_code == 201, r.text
    return r.json()


def tr(c, aid, lang="en"):
    return c.post(f"/analyses/{aid}/translate", json={"language": lang})


def test_translate_writes_the_same_check_in_the_other_language_and_keeps_the_original(register, prov):
    c = register()
    orig = make_te(c)
    assert TELUGU.search(orig["result"]["likely_issue"])
    calls_before = len(prov.calls)
    r = tr(c, orig["id"], "en")
    d = r.json()
    assert r.status_code == 200 and len(prov.calls) == calls_before + 1
    assert prov.calls[-1].language == "en"
    assert "en" in d["translations"] and not TELUGU.search(d["translations"]["en"]["likely_issue"])
    # the original is untouched
    assert d["language"] == "te" and d["result"] == orig["result"] and d["symptoms"] == orig["symptoms"]
    # structured values stay English and valid
    t = d["translations"]["en"]
    assert t["severity"] in ("low", "medium", "high", "unknown") and t["uncertainty_level"] in ("low", "some", "high", "unknown")
    # persisted: a fresh GET shows both versions
    again = c.get(f"/analyses/{orig['id']}").json()
    assert again["translations"]["en"] == t and again["result"] == orig["result"]
    assert c.get("/analyses").json()[0]["translations"]["en"] == t


def test_second_request_for_the_same_language_is_served_from_storage_without_a_model_call(register, prov):
    c = register()
    orig = make_te(c)
    tr(c, orig["id"], "en")
    n = len(prov.calls)
    r = tr(c, orig["id"], "en")
    assert r.status_code == 200 and len(prov.calls) == n and "en" in r.json()["translations"]


def test_same_language_as_the_original_is_a_no_op(register, prov):
    c = register()
    orig = make_te(c)
    n = len(prov.calls)
    r = tr(c, orig["id"], "te")
    assert r.status_code == 200 and len(prov.calls) == n and r.json()["translations"] == {} and r.json()["result"] == orig["result"]


def test_english_check_can_be_written_in_telugu_too(register, prov):
    c = register()
    fid = _farm(c)
    en = c.post("/analyses", json={"farm_id": fid, "crop": "Tomato", "symptoms": "yellow leaves with brown spots"}).json()
    r = tr(c, en["id"], "te").json()
    assert en["language"] == "en" and TELUGU.search(r["translations"]["te"]["likely_issue"]) and r["result"] == en["result"]


def test_it_regenerates_from_the_STORED_inputs_including_photo_and_weather(register, prov, monkeypatch):
    monkeypatch.setattr(weather, "client", FakeWeather(wx=WX))
    c = register()
    orig = make_te(c, image=PNG)
    assert orig["has_image"] and orig["weather"]["humidity_pct"] == 82.0
    # now the weather service is DOWN: the translation must use the saved snapshot, not re-fetch
    monkeypatch.setattr(weather, "client", FakeWeather(exc=weather.WeatherError("down")))
    tr(c, orig["id"], "en")
    ctx = prov.calls[-1]
    assert ctx.crop == "టమాటా" and ctx.symptoms == SYMPTOMS_TE
    assert ctx.farm_location == "Guntur" and ctx.soil_type == "Red soil" and ctx.language == "en"
    assert ctx.image is not None and ctx.image.data == PNG and ctx.image.mime_type == "image/png"
    assert ctx.weather is not None and ctx.weather.humidity_pct == 82.0 and ctx.weather.past_3d_rain_mm == 22.5
    assert ctx.history == []


def test_owner_only_and_identical_404_for_foreign_and_missing(register, prov, client):
    a = register("a@example.com")
    b = register("b@example.com")
    orig = make_te(a)
    n = len(prov.calls)
    foreign, missing = tr(b, orig["id"]), tr(b, 999999)
    assert foreign.status_code == missing.status_code == 404 and foreign.json() == missing.json()
    assert len(prov.calls) == n  # no model call, nothing leaked
    client.cookies.clear()
    assert tr(client, orig["id"]).status_code == 401
    assert a.get(f"/analyses/{orig['id']}").json()["translations"] == {}  # B's attempt changed nothing


@pytest.mark.parametrize("bad", ["fr", "", "te-IN", "EN"])
def test_unsupported_language_is_rejected(register, prov, bad):
    c = register()
    orig = make_te(c)
    r = c.post(f"/analyses/{orig['id']}/translate", json={"language": bad})
    assert r.status_code == 422 and r.json()["code"] == "invalid_request"
    assert c.post(f"/analyses/{orig['id']}/translate", json={}).status_code == 422


def test_unsafe_output_is_rejected_and_nothing_is_stored(register, monkeypatch):
    c = register()
    safe = Counting()
    monkeypatch.setattr(service, "get_provider", lambda: safe)
    orig = make_te(c)
    unsafe = Counting(lambda ctx: {**DemoAIProvider().analyze(ctx), "explanation": "Mix 10 ml per litre of fungicide."})
    monkeypatch.setattr(service, "get_provider", lambda: unsafe)
    r = tr(c, orig["id"], "en")
    assert r.status_code == 503 and r.json()["code"] == "ai_unsafe_output" and "10 ml" not in r.text
    got = c.get(f"/analyses/{orig['id']}").json()
    assert got["translations"] == {} and got["result"] == orig["result"]


def test_provider_failure_is_a_clean_503_and_a_retry_can_succeed(register, monkeypatch):
    c = register()
    ok = Counting()
    monkeypatch.setattr(service, "get_provider", lambda: ok)
    orig = make_te(c)

    class Boom:
        name = "boom"

        def analyze(self, ctx):
            raise RuntimeError("secret internal detail")

    monkeypatch.setattr(service, "get_provider", lambda: Boom())
    r = tr(c, orig["id"], "en")
    assert r.status_code == 503 and "secret" not in r.text and "Traceback" not in r.text
    monkeypatch.setattr(service, "get_provider", lambda: ok)
    assert tr(c, orig["id"], "en").status_code == 200  # nothing half-stored blocks the retry


def test_translate_is_rate_limited_like_analyses(register, prov, monkeypatch):
    monkeypatch.setenv("RL_ANALYSIS_PER_USER", "3")
    c = register()
    orig = make_te(c)  # 1
    assert tr(c, orig["id"], "en").status_code == 200  # 2
    assert tr(c, orig["id"], "en").status_code == 200  # 3 (cached, but still counted)
    r = tr(c, orig["id"], "en")
    assert r.status_code == 429 and "retry-after" in r.headers


def test_old_rows_without_translations_load_and_the_original_is_never_modified(register):
    c = register()
    fid = _farm(c)
    uid = c.get("/auth/me").json()["id"]
    old = {"likely_issue": "Old issue", "explanation": "e", "recommended_actions": ["a"], "precautions": ["p"], "uncertainty": "u"}
    with SessionLocal() as db:
        row = Analysis(user_id=uid, farm_id=fid, crop="Rice", symptoms="old", language="en", result_json=old)
        db.add(row)
        db.commit()
        rid = row.id
    got = c.get(f"/analyses/{rid}").json()
    assert got["translations"] == {} and got["result"]["likely_issue"] == "Old issue"
    tr(c, rid, "te")
    with SessionLocal() as db:
        row = db.get(Analysis, rid)
        assert row.result_json == old and row.language == "en" and list(row.translations_json) == ["te"]


def test_a_malformed_stored_version_is_ignored_not_shown(register):
    c = register()
    fid = _farm(c)
    uid = c.get("/auth/me").json()["id"]
    good = DemoAIProvider().analyze(__import__("app.services.ai", fromlist=["AnalysisContext"]).AnalysisContext(crop="Rice", symptoms="yellow leaves with spots"))
    with SessionLocal() as db:
        row = Analysis(user_id=uid, farm_id=fid, crop="Rice", symptoms="x", language="en", result_json=good,
                       translations_json={"te": {"likely_issue": ""}, "fr": good})
        db.add(row)
        db.commit()
        rid = row.id
    assert c.get(f"/analyses/{rid}").json()["translations"] == {}


def test_migration_adds_the_column_to_an_existing_database_and_is_idempotent(tmp_path):
    from sqlalchemy import create_engine, text

    f = tmp_path / "old.db"
    con = sqlite3.connect(f)
    con.executescript(
        """
        CREATE TABLE users (id INTEGER PRIMARY KEY, email VARCHAR(255), password_hash VARCHAR(255), created_at DATETIME);
        CREATE TABLE farms (id INTEGER PRIMARY KEY, user_id INTEGER, name VARCHAR(120), location VARCHAR(200), soil_type VARCHAR(100), created_at DATETIME);
        CREATE TABLE analyses (id INTEGER PRIMARY KEY, user_id INTEGER, farm_id INTEGER, crop VARCHAR(100), symptoms TEXT, language VARCHAR(10),
          result_json JSON, created_at DATETIME, image_path VARCHAR(255), input_type VARCHAR(20) DEFAULT 'text' NOT NULL, weather_json JSON,
          weather_note VARCHAR(300), idempotency_key VARCHAR(64), request_hash VARCHAR(64));
        INSERT INTO analyses (id,user_id,farm_id,crop,symptoms,language,result_json) VALUES (1,1,1,'Rice','x','en','{"likely_issue":"Keep me"}');
        """
    )
    con.commit()
    con.close()
    eng = create_engine(f"sqlite:///{f}")
    # the old-shape DB gets every column added since (all nullable); nothing else changes
    assert migrate(eng) == [
        "farms.primary_crop", "farms.irrigation_method", "farms.season", "farms.planting_date", "farms.notes",
        "farms.context_updated_at", "analyses.translations_json", "analyses.parent_id", "analyses.link_kind",
    ]
    assert migrate(eng) == []
    with eng.connect() as conn:
        row = conn.execute(text("SELECT crop, result_json, translations_json FROM analyses WHERE id=1")).one()
    assert row[0] == "Rice" and "Keep me" in row[1] and row[2] is None


def test_a_te_tagged_result_that_came_back_in_english_can_still_be_written_in_telugu(register, monkeypatch):
    """The model can ignore the language instruction. Then 'te' is NOT really present and must be generated."""
    c = register()
    english_for_te = Counting(lambda ctx: DemoAIProvider().analyze(type(ctx)(crop=ctx.crop, symptoms=ctx.symptoms, language="en")))
    monkeypatch.setattr(service, "get_provider", lambda: english_for_te)
    fid = _farm(c)
    r = c.post("/analyses", data={"farm_id": str(fid), "crop": "Tomato", "symptoms": "yellow leaves with spots", "language": "te"}).json()
    assert r["language"] == "te" and not TELUGU.search(r["result"]["likely_issue"])  # tagged te, written in English
    proper = Counting()
    monkeypatch.setattr(service, "get_provider", lambda: proper)
    out = tr(c, r["id"], "te").json()
    assert len(proper.calls) == 1 and TELUGU.search(out["translations"]["te"]["likely_issue"])
    assert tr(c, r["id"], "en").json()["translations"].keys() == {"te"}  # English is the original: no-op
