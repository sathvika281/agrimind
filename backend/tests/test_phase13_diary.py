"""Farm diary (what the farmer says they did). Scratch DB only."""
import json
import os
import sqlite3
import subprocess
import sys
import textwrap
from datetime import date, timedelta

import pytest

from app.services.ai import service
from app.services.ai.demo_provider import DemoAIProvider


class Spy(DemoAIProvider):
    def __init__(self):
        self.calls = []

    def analyze(self, ctx):
        self.calls.append(ctx)
        return super().analyze(ctx)


def _farm(c, name="F"):
    r = c.post("/farms", json={"name": name, "location": "Guntur", "soil_type": "Red soil"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _ev(c, farm_id, **kw):
    return c.post(f"/farms/{farm_id}/events", json={"kind": "irrigated", **kw})


def _check(c, farm_id):
    r = c.post("/analyses", json={"farm_id": farm_id, "crop": "Tomato", "symptoms": "yellow leaves with brown spots"})
    assert r.status_code == 201, r.text
    return r.json()


def test_diary_add_list_delete_roundtrip(register):
    c = register()
    fid = _farm(c)
    r = _ev(c, fid, note="  Drip for two hours  ")
    assert r.status_code == 201
    e = r.json()
    assert e["kind"] == "irrigated" and e["note"] == "Drip for two hours"
    assert e["event_date"] >= (date.today() - timedelta(days=1)).isoformat()
    older = _ev(c, fid, kind="sowed", event_date="2026-07-01", note="").json()
    assert older["note"] is None  # empty means "no note"
    listed = c.get(f"/farms/{fid}/events").json()
    assert [x["id"] for x in listed] == [e["id"], older["id"]]  # newest date first
    assert all(x["created_at"].endswith(("Z", "+00:00")) for x in listed)
    assert c.delete(f"/farms/{fid}/events/{e['id']}").status_code == 204
    assert [x["id"] for x in c.get(f"/farms/{fid}/events").json()] == [older["id"]]
    assert c.delete(f"/farms/{fid}/events/{e['id']}").status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"kind": "danced"},
        {"kind": 5},
        {},
        {"kind": "sowed", "event_date": "not-a-date"},
        {"kind": "sowed", "event_date": "1999-12-31"},
        {"kind": "sowed", "event_date": (date.today() + timedelta(days=20)).isoformat()},
        {"kind": "sowed", "note": "n" * 301},
        {"kind": "sowed", "note": ["x"]},
        {"kind": "sowed", "event_date": 20260701},
    ],
)
def test_diary_validation_is_a_clean_422_and_stores_nothing(register, body):
    c = register()
    fid = _farm(c)
    r = c.post(f"/farms/{fid}/events", json=body)
    assert r.status_code == 422 and "Traceback" not in r.text
    assert c.get(f"/farms/{fid}/events").json() == []
    assert c.post(f"/farms/{fid}/events", content=b"{bad", headers={"content-type": "application/json"}).status_code == 422


def test_diary_boundaries_and_telugu(register):
    c = register()
    fid = _farm(c)
    assert _ev(c, fid, event_date="2000-01-01", note="n" * 300).status_code == 201
    assert _ev(c, fid, event_date=date.today().isoformat()).status_code == 201
    assert _ev(c, fid, event_date="").status_code == 201  # blank date = today
    t = _ev(c, fid, kind="sprayed", note="ఉదయం పిచికారీ చేశాను").json()
    assert t["note"] == "ఉదయం పిచికారీ చేశాను"
    for k in ("sowed", "irrigated", "fertilised", "sprayed", "weeded", "harvested", "other"):
        assert _ev(c, fid, kind=k).status_code == 201


def test_diary_authorization_matrix(register, client):
    a, b = register("a@example.com"), register("b@example.com")
    fa, fb = _farm(a), _farm(b)
    mine = _ev(a, fa).json()
    other = _ev(b, fb).json()
    miss_get, miss_post, miss_del = b.get("/farms/999999/events"), _ev(b, 999999), b.delete("/farms/999999/events/1")
    assert [r.status_code for r in (miss_get, miss_post, miss_del)] == [404, 404, 404]
    assert b.get(f"/farms/{fa}/events").json() == miss_get.json()
    assert _ev(b, fa).json() == miss_post.json()
    assert b.delete(f"/farms/{fa}/events/{mine['id']}").json() == miss_del.json()
    for bad in ("99999999999999999999", "0", "-3"):
        assert b.get(f"/farms/{bad}/events").status_code == 404
        assert _ev(b, bad).status_code == 404
        assert b.delete(f"/farms/{bad}/events/1").status_code == 404
    assert b.get("/farms/abc/events").status_code == 422
    assert b.delete(f"/farms/{fb}/events/{mine['id']}").status_code == 404  # A's entry via MY farm id: not found
    assert b.delete(f"/farms/{fb}/events/99999999999999999999").status_code == 404
    assert [x["id"] for x in a.get(f"/farms/{fa}/events").json()] == [mine["id"]]  # untouched by every attempt
    assert [x["id"] for x in b.get(f"/farms/{fb}/events").json()] == [other["id"]]
    for call in (client.get(f"/farms/{fa}/events"), client.post(f"/farms/{fa}/events", json={"kind": "sowed"}), client.delete(f"/farms/{fa}/events/1")):
        assert call.status_code == 401


def test_diary_is_bounded(register, monkeypatch):
    from app.routers import farms

    c = register()
    fid = _farm(c)
    monkeypatch.setattr(farms, "EVENTS_MAX", 3)
    for _ in range(3):
        assert _ev(c, fid).status_code == 201
    assert _ev(c, fid).status_code == 409 and len(c.get(f"/farms/{fid}/events").json()) == 3
    monkeypatch.setattr(farms, "EVENTS_MAX", 1000)
    monkeypatch.setattr(farms, "EVENTS_LIMIT", 2)
    assert len(c.get(f"/farms/{fid}/events").json()) == 2  # reads return only the newest N


def test_only_recent_diary_kinds_and_dates_reach_the_model_never_notes(register, monkeypatch):
    spy = Spy()
    monkeypatch.setattr(service, "get_provider", lambda: spy)
    a, b = register("a@example.com"), register("b@example.com")
    fa, other_farm = _farm(a), _farm(a, name="Other")
    today = date.today()
    _ev(a, fa, kind="sprayed", note="PRIVATE-NOTE-77 used 5 ml per litre")
    _ev(a, fa, kind="sowed", event_date=(today - timedelta(days=45)).isoformat())  # too old
    _ev(a, other_farm, kind="harvested")  # a different farm
    _ev(b, _farm(b), kind="weeded")  # another user
    for i in range(1, 8):
        _ev(a, fa, kind="irrigated", event_date=(today - timedelta(days=i)).isoformat())
    _check(a, fa)
    ctx = spy.calls[-1]
    kinds = [d.kind for d in ctx.diary]
    assert len(ctx.diary) == 5 and "sowed" not in kinds and "harvested" not in kinds and "weeded" not in kinds
    assert ctx.diary[0].date >= ctx.diary[-1].date
    assert "PRIVATE-NOTE-77" not in repr(ctx)  # free text is never sent
    from app.services.ai.gemini_provider import build_prompt

    prompt = build_prompt(ctx)
    assert "diary" in prompt.lower() and "PRIVATE-NOTE-77" not in prompt


def test_diary_notes_never_leak_into_other_endpoints(register):
    c = register()
    fid = _farm(c)
    _ev(c, fid, note="PRIVATE-NOTE-88")
    _check(c, fid)
    for path in (f"/farms/{fid}/insights", f"/farms/{fid}/decision-support", f"/farms/{fid}/proactive", f"/farms/{fid}", "/analyses", "/farms"):
        assert "PRIVATE-NOTE-88" not in c.get(path).text, path


def test_old_database_gets_the_diary_table_without_touching_existing_rows(tmp_path):
    f = tmp_path / "old.db"
    con = sqlite3.connect(f)
    con.executescript(
        """
        CREATE TABLE users (id INTEGER PRIMARY KEY, email VARCHAR(255), password_hash VARCHAR(255), created_at DATETIME);
        CREATE TABLE farms (id INTEGER PRIMARY KEY, user_id INTEGER, name VARCHAR(120), location VARCHAR(200), soil_type VARCHAR(100), created_at DATETIME);
        CREATE TABLE analyses (id INTEGER PRIMARY KEY, user_id INTEGER, farm_id INTEGER, crop VARCHAR(100), symptoms TEXT, language VARCHAR(10),
          result_json JSON, created_at DATETIME, image_path VARCHAR(255), input_type VARCHAR(20) DEFAULT 'text' NOT NULL, weather_json JSON,
          weather_note VARCHAR(300), idempotency_key VARCHAR(64), request_hash VARCHAR(64), translations_json JSON);
        INSERT INTO users VALUES (1,'old@example.com','x','2026-10-01 10:00:00');
        INSERT INTO farms VALUES (1,1,'Old Farm','Guntur','Red soil','2026-10-01 10:00:00');
        INSERT INTO analyses (id,user_id,farm_id,crop,symptoms,language,result_json,created_at) VALUES
          (1,1,1,'Rice','x','en','{"likely_issue":"Keep me","explanation":"e","recommended_actions":["a"],"precautions":["p"],"uncertainty":"u"}','2026-10-01 11:00:00');
        """
    )
    con.commit()
    con.close()
    cols = "id,user_id,farm_id,crop,symptoms,language,result_json,created_at"
    before = sqlite3.connect(f).execute(f"SELECT {cols} FROM analyses").fetchall()
    script = textwrap.dedent(
        f"""
        import os, json
        os.environ.update(DATABASE_URL="sqlite:///{f.as_posix()}", UPLOADS_DIR=r"{(tmp_path / 'up').as_posix()}", JWT_SECRET="t"*40, AI_PROVIDER="demo", COOKIE_SECURE="false", GEMINI_API_KEY="")
        from fastapi.testclient import TestClient
        from app.auth.security import create_token
        from app.main import app
        from app.config import settings
        with TestClient(app) as c:
            c.cookies.set(settings.cookie_name, create_token(1))
            e = c.post("/farms/1/events", json={{"kind": "sowed"}}).status_code
            a = c.get("/analyses").json()
            print(json.dumps({{"event": e, "n": len(a), "issue": a[0]["result"]["likely_issue"], "parent": a[0]["parent_id"]}}))
        """
    )
    r = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, cwd=os.path.dirname(os.path.dirname(__file__)))
    assert r.returncode == 0, r.stderr[-600:]
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out == {"event": 201, "n": 1, "issue": "Keep me", "parent": None}
    assert sqlite3.connect(f).execute(f"SELECT {cols} FROM analyses").fetchall() == before
