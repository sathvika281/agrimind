"""Phase 10: optional, farmer-provided farm context (create / edit / read), validation, authorization, migration safety.
Scratch DBs only (see conftest); never the live database."""
import sqlite3
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.database import migrate
from app.main import app

CTX = ("primary_crop", "irrigation_method", "season", "planting_date", "notes", "context_updated_at")


def _farm(c, **extra):
    r = c.post("/farms", json={"name": "F", "location": "Guntur", "soil_type": "Red soil", **extra})
    assert r.status_code == 201, r.text
    return r.json()


# ---------------- read / create / update ----------------
def test_new_farm_without_context_has_every_context_field_null(register):
    f = _farm(register())
    assert all(f[k] is None for k in CTX)


def test_create_with_context_stores_it_and_stamps_context_updated_at(register):
    c = register()
    f = _farm(c, primary_crop="Tomato", irrigation_method="drip", season="kharif", planting_date="2026-07-01", notes="Near the well")
    assert (f["primary_crop"], f["irrigation_method"], f["season"], f["planting_date"], f["notes"]) == ("Tomato", "drip", "kharif", "2026-07-01", "Near the well")
    assert f["context_updated_at"] and f["context_updated_at"].endswith(("Z", "+00:00"))
    assert c.get(f"/farms/{f['id']}").json() == f  # persisted exactly as returned
    assert c.get("/farms").json()[0] == f


def test_patch_changes_only_what_is_sent_and_clears_with_null_or_empty(register):
    c = register()
    f = _farm(c, primary_crop="Tomato", irrigation_method="drip", season="rabi", notes="n")
    r = c.patch(f"/farms/{f['id']}", json={"irrigation_method": "sprinkler"})
    assert r.status_code == 200
    j = r.json()
    assert j["irrigation_method"] == "sprinkler" and j["primary_crop"] == "Tomato" and j["season"] == "rabi" and j["name"] == "F" and j["soil_type"] == "Red soil"
    j = c.patch(f"/farms/{f['id']}", json={"season": None, "notes": "   ", "primary_crop": ""}).json()
    assert j["season"] is None and j["notes"] is None and j["primary_crop"] is None and j["irrigation_method"] == "sprinkler"
    j = c.patch(f"/farms/{f['id']}", json={"soil_type": None, "location": ""}).json()
    assert j["soil_type"] == "" and j["location"] == ""  # these two columns are never NULL; empty = "Not provided"
    assert c.patch(f"/farms/{f['id']}", json={}).json()["irrigation_method"] == "sprinkler"  # empty patch = no change


def test_context_updated_at_moves_only_when_context_really_changes(register):
    c = register()
    f = _farm(c, primary_crop="Tomato")
    first = f["context_updated_at"]
    same = c.patch(f"/farms/{f['id']}", json={"primary_crop": "Tomato", "name": "Renamed"}).json()
    assert same["context_updated_at"] == first and same["name"] == "Renamed"  # a rename is not a context change
    changed = c.patch(f"/farms/{f['id']}", json={"primary_crop": "Rice"}).json()
    assert changed["context_updated_at"] > first
    bare = _farm(c)  # no context given at creation -> still no stamp
    assert bare["context_updated_at"] is None
    assert c.patch(f"/farms/{bare['id']}", json={"name": "Only a rename"}).json()["context_updated_at"] is None


def test_telugu_text_round_trips(register):
    c = register()
    f = _farm(c, primary_crop="టమాటా", notes="బావి దగ్గర పొలం")
    assert c.get(f"/farms/{f['id']}").json()["primary_crop"] == "టమాటా"
    assert c.patch(f"/farms/{f['id']}", json={"soil_type": "ఎర్ర నేల"}).json()["soil_type"] == "ఎర్ర నేల"


# ---------------- validation: always a clean 422, never a 500 ----------------
@pytest.mark.parametrize(
    "body",
    [
        {"irrigation_method": "laser"},
        {"irrigation_method": 5},
        {"season": "monsoon"},
        {"season": ["kharif"]},
        {"planting_date": "not-a-date"},
        {"planting_date": "2026-13-45"},
        {"planting_date": "1999-12-31"},
        {"planting_date": (date.today() + timedelta(days=30)).isoformat()},
        {"planting_date": 20260701},
        {"planting_date": True},
        {"primary_crop": "x" * 101},
        {"notes": "n" * 501},
        {"primary_crop": 5},
        {"notes": ["a"]},
        {"name": ""},
        {"name": None},
        {"name": "x" * 121},
        {"location": "y" * 201},
        {"soil_type": "z" * 101},
        {"name": 123},
    ],
)
def test_invalid_patch_is_a_clean_422_and_changes_nothing(register, body):
    c = register()
    f = _farm(c, primary_crop="Tomato")
    r = c.patch(f"/farms/{f['id']}", json=body)
    assert r.status_code == 422, (body, r.status_code, r.text)
    assert "Traceback" not in r.text
    assert c.get(f"/farms/{f['id']}").json() == f


def test_boundary_values_are_accepted(register):
    c = register()
    f = _farm(c)
    today = date.today().isoformat()
    r = c.patch(f"/farms/{f['id']}", json={"planting_date": today, "primary_crop": "c" * 100, "notes": "n" * 500, "name": "n" * 120})
    assert r.status_code == 200 and r.json()["planting_date"] == today
    assert c.patch(f"/farms/{f['id']}", json={"planting_date": "2000-01-01"}).status_code == 200
    assert c.patch(f"/farms/{f['id']}", json={"planting_date": ""}).json()["planting_date"] is None
    for choice in ("rainfed", "drip", "sprinkler", "flood", "other"):
        assert c.patch(f"/farms/{f['id']}", json={"irrigation_method": choice}).status_code == 200
    for choice in ("kharif", "rabi", "summer"):
        assert c.patch(f"/farms/{f['id']}", json={"season": choice}).status_code == 200


def test_malformed_json_and_create_validation(register):
    c = register()
    f = _farm(c)
    assert c.patch(f"/farms/{f['id']}", content=b"{nope", headers={"content-type": "application/json"}).status_code == 422
    assert c.post("/farms", json={"name": "ok", "season": "monsoon"}).status_code == 422
    assert c.post("/farms", json={"name": "ok", "planting_date": "2999-01-01"}).status_code == 422
    assert len(c.get("/farms").json()) == 1  # nothing was created by the rejected requests


# ---------------- authorization ----------------
def test_patch_authorization_matrix(register, client):
    a, b = register("a@example.com"), register("b@example.com")
    fa, fb = _farm(a, primary_crop="Tomato"), _farm(b, primary_crop="Rice")
    miss = b.patch("/farms/999999", json={"notes": "x"})
    foreign = b.patch(f"/farms/{fa['id']}", json={"notes": "hacked", "primary_crop": "Hacked"})
    assert foreign.status_code == miss.status_code == 404 and foreign.json() == miss.json()
    for bad in ("99999999999999999999", "0", "-3"):
        r = b.patch(f"/farms/{bad}", json={"notes": "x"})
        assert r.status_code == 404 and r.json() == miss.json()
    assert b.patch("/farms/abc", json={"notes": "x"}).status_code == 422
    assert client.patch(f"/farms/{fa['id']}", json={"notes": "x"}).status_code == 401
    assert a.get(f"/farms/{fa['id']}").json() == fa  # untouched by the foreign attempts
    # editing A never changes B, and each user can edit their own
    assert a.patch(f"/farms/{fa['id']}", json={"primary_crop": "Chilli"}).status_code == 200
    assert b.get(f"/farms/{fb['id']}").json()["primary_crop"] == "Rice"


def test_responses_contain_no_user_id(register):
    c = register()
    f = _farm(c, primary_crop="Tomato")
    assert "user_id" not in str(c.patch(f"/farms/{f['id']}", json={"notes": "n"}).json())


# ---------------- history and AI are untouched ----------------
def test_editing_context_never_modifies_stored_analyses(register):
    c = register()
    f = _farm(c)
    c.post("/analyses", json={"farm_id": f["id"], "crop": "Rice", "symptoms": "yellow leaves"})
    before = c.get("/analyses").json()
    c.patch(f"/farms/{f['id']}", json={"primary_crop": "Cotton", "irrigation_method": "drip", "season": "rabi", "soil_type": "Black soil", "notes": "x"})
    after = c.get("/analyses").json()
    assert after == before  # crop, result, language, timestamps: byte-for-byte the same historical record


def test_new_context_fields_are_not_sent_to_the_ai_provider(register, monkeypatch):
    from app.services.ai import service
    from app.services.ai.demo_provider import DemoAIProvider

    seen = []

    class Spy(DemoAIProvider):
        def analyze(self, ctx):
            seen.append(ctx)
            return super().analyze(ctx)

    monkeypatch.setattr(service, "get_provider", lambda: Spy())
    c = register()
    f = _farm(c, primary_crop="SECRETCROP", irrigation_method="drip", season="rabi", planting_date="2026-07-01", notes="SECRETNOTE")
    assert c.post("/analyses", json={"farm_id": f["id"], "crop": "Rice", "symptoms": "yellow leaves"}).status_code == 201
    blob = repr(seen[0])
    for banned in ("SECRETCROP", "SECRETNOTE", "drip", "rabi", "2026-07-01"):
        assert banned not in blob


def test_notes_never_leak_into_insights(register):
    c = register()
    f = _farm(c, notes="PRIVATE-NOTE", primary_crop="Tomato")
    assert "PRIVATE-NOTE" not in c.get(f"/farms/{f['id']}/insights").text


# ---------------- migration: old databases keep working ----------------
def _old_db(path):
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE users (id INTEGER PRIMARY KEY, email VARCHAR(255), password_hash VARCHAR(255), created_at DATETIME);
        CREATE TABLE farms (id INTEGER PRIMARY KEY, user_id INTEGER, name VARCHAR(120), location VARCHAR(200), soil_type VARCHAR(100), created_at DATETIME);
        CREATE TABLE analyses (id INTEGER PRIMARY KEY, user_id INTEGER, farm_id INTEGER, crop VARCHAR(100), symptoms TEXT, language VARCHAR(10),
          result_json JSON, created_at DATETIME, image_path VARCHAR(255), input_type VARCHAR(20) DEFAULT 'text' NOT NULL, weather_json JSON,
          weather_note VARCHAR(300), idempotency_key VARCHAR(64), request_hash VARCHAR(64), translations_json JSON);
        INSERT INTO users VALUES (1,'old@example.com','x','2026-10-01 10:00:00');
        INSERT INTO farms VALUES (1,1,'Old Farm','Guntur','Red soil','2026-10-01 10:00:00');
        INSERT INTO farms VALUES (2,1,'No Soil','','','2026-10-02 10:00:00');
        INSERT INTO analyses (id,user_id,farm_id,crop,symptoms,language,result_json,created_at) VALUES
          (1,1,1,'Rice','yellow','en','{"likely_issue":"Keep me","explanation":"e","recommended_actions":["a"],"precautions":["p"],"uncertainty":"u"}','2026-10-01 11:00:00');
        """
    )
    con.commit()
    con.close()


def test_migration_is_additive_preserves_every_old_row_and_old_data_still_loads(tmp_path):
    from sqlalchemy import create_engine

    f = tmp_path / "old.db"
    _old_db(f)
    snap = lambda: sqlite3.connect(f).execute("SELECT id,user_id,name,location,soil_type,created_at FROM farms ORDER BY id").fetchall()
    a_snap = lambda: sqlite3.connect(f).execute("SELECT id,user_id,farm_id,crop,symptoms,language,result_json,created_at,image_path,input_type,weather_json,weather_note,idempotency_key,request_hash,translations_json FROM analyses ORDER BY id").fetchall()
    farms_before, an_before = snap(), a_snap()
    eng = create_engine(f"sqlite:///{f}")
    added = migrate(eng)
    assert added == ["farms.primary_crop", "farms.irrigation_method", "farms.season", "farms.planting_date", "farms.notes", "farms.context_updated_at", "analyses.parent_id", "analyses.link_kind"]
    assert migrate(eng) == []  # idempotent
    assert snap() == farms_before and a_snap() == an_before  # every old value byte-identical
    new_cols = sqlite3.connect(f).execute("SELECT primary_crop,irrigation_method,season,planting_date,notes,context_updated_at FROM farms").fetchall()
    assert new_cols == [(None,) * 6, (None,) * 6]  # old farms: "not provided", never a fake default
    assert sqlite3.connect(f).execute("SELECT count(*) FROM users").fetchone()[0] == 1
    assert sqlite3.connect(f).execute("SELECT count(*) FROM analyses").fetchone()[0] == 1


def test_app_runs_on_a_migrated_old_database_end_to_end(tmp_path):
    """Old farms and old analyses load through the real API after the additive migration (separate process, scratch DB)."""
    import json, os, subprocess, sys, textwrap

    f = tmp_path / "old.db"
    _old_db(f)
    script = textwrap.dedent(
        f"""
        import os
        os.environ.update(DATABASE_URL="sqlite:///{f.as_posix()}", UPLOADS_DIR=r"{(tmp_path / 'up').as_posix()}", JWT_SECRET="t"*40, AI_PROVIDER="demo", COOKIE_SECURE="false", GEMINI_API_KEY="")
        from fastapi.testclient import TestClient
        from app.auth.security import create_token
        from app.main import app
        from app.config import settings
        import json
        with TestClient(app) as c:
            c.cookies.set(settings.cookie_name, create_token(1))
            farms = c.get("/farms").json()
            an = c.get("/analyses").json()
            ins = c.get("/farms/1/insights").json()
            p = c.patch("/farms/1", json={{"primary_crop": "Rice"}})
            print(json.dumps({{"farms": farms, "an": [a["result"]["likely_issue"] for a in an], "ins_total": ins["total"], "patch": p.status_code}}))
        """
    )
    r = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, cwd=os.path.dirname(os.path.dirname(__file__)))
    assert r.returncode == 0, r.stderr[-800:]
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert [x["name"] for x in out["farms"]] == ["No Soil", "Old Farm"]
    assert all(x["primary_crop"] is None and x["context_updated_at"] is None for x in out["farms"])
    assert out["an"] == ["Keep me"] and out["ins_total"] == 1 and out["patch"] == 200
