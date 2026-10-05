"""Phase 12: proactive intelligence. Deterministic, read-only, built only from stored evidence. Scratch DB only."""
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from app.services.decision_support import decide
from app.services.insights import build_insights
from app.services.proactive_intelligence import MAX_ITEMS, build_proactive_items

T0 = datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc)
BLIGHT = "Leaf spot disease (early blight)"
NUTR = "Possible nutrient deficiency or watering problem (leaf yellowing)"
PEST = "Insect pest damage"
UNCLEAR = "Unable to pinpoint the problem from this description"
FULL_CTX = {"primary_crop": "Tomato", "irrigation_method": "drip", "season": "kharif", "planting_date": "2026-07-01", "soil_type": "Red soil", "location": "Guntur"}


def row(i, issue=BLIGHT, severity="unknown", crop="Tomato", unc="some", quality="good", day=None):
    return {"id": i, "crop": crop, "created_at": T0 + timedelta(days=i if day is None else day), "likely_issue": issue, "severity": severity,
            "uncertainty_level": unc, "image_quality": quality, "input_type": "text"}


def run(rows, ctx=None):
    return build_proactive_items(build_insights(rows), decide(rows, ctx or {}))


def kinds(item):
    return [r["kind"] for r in item["reasons"]]


# ---------------- triggers ----------------
def test_zero_checks_is_quiet():
    r = run([])
    assert r == {"level": "none", "total_checks": 0, "items": []}


def test_one_low_check_shows_nothing():
    assert run([row(1, BLIGHT, "low")])["items"] == []


def test_unknown_severity_alone_never_raises_an_item():
    assert run([row(1, BLIGHT, "unknown")])["items"] == []
    assert run([row(i, f"Issue {i}", "unknown") for i in range(1, 4)])["items"] == []  # even several unrated, unrelated checks


def test_one_medium_check_is_an_attention_item_for_the_unresolved_follow_up():
    r = run([row(1, BLIGHT, "medium")])
    assert r["level"] == "attention" and len(r["items"]) == 1
    it = r["items"][0]
    assert kinds(it) == ["unresolved_verify"] and it["priority"] == "attention" and it["expert_suggested"] is False
    assert it["actions"] == ["inspect_plants"] and it["issue"] == BLIGHT and it["crop"] == "Tomato" and it["evidence_count"] == 1


def test_one_high_check_is_important_with_expert_suggested():
    r = run([row(1, BLIGHT, "high")])
    it = r["items"][0]
    assert r["level"] == "important" and kinds(it) == ["latest_high"] and it["priority"] == "important"
    assert it["expert_suggested"] is True and it["actions"] == ["consult_expert"]


def test_repeated_issue_uses_the_phase9_thresholds_exactly():
    rows = [row(1, BLIGHT, "medium"), row(2, NUTR, "medium"), row(3, BLIGHT, "medium"), row(4, NUTR, "medium"), row(5, BLIGHT, "medium")]
    items = run(rows)["items"]
    blight = next(i for i in items if i["issue"] == BLIGHT)
    assert "recurring" in kinds(blight) and blight["priority"] == "attention"
    rec = next(r for r in blight["reasons"] if r["kind"] == "recurring")
    assert (rec["count"], rec["window"]) == (3, 5) and [d["analysis_id"] for d in rec["dates"]] == [1, 3, 5]
    assert all(i["issue"] != NUTR for i in items)  # only 2 of 5: below the Phase 9 threshold, so nothing
    # one short of the threshold: no recurring item at all
    short = run([row(1, BLIGHT), row(2, NUTR), row(3, BLIGHT), row(4, PEST)])
    assert short["items"] == []


def test_more_frequent_issue_is_surfaced_without_inventing_recurrence():
    rows = [row(1, NUTR), row(2, NUTR), row(3, "Pest A"), row(4, BLIGHT), row(5, BLIGHT), row(6, "Pest B")]
    items = run(rows)["items"]
    assert len(items) == 1 and kinds(items[0]) == ["more_frequent"] and items[0]["issue"] == BLIGHT
    assert items[0]["reasons"][0]["earlier_count"] == 0 and items[0]["expert_suggested"] is False  # not the latest check's issue


def test_repeated_high_is_important_and_carries_the_phase11_expert_flag():
    rows = [row(1, "A", "medium"), row(2, "B", "high"), row(3, "C"), row(4, "D", "high"), row(5, "E", "medium")]
    r = run(rows)
    it = next(i for i in r["items"] if "repeated_high" in kinds(i))
    assert it["priority"] == "important" and it["expert_suggested"] is True and it["actions"] == ["consult_expert"] and it["issue"] == "D"
    assert [d["analysis_id"] for d in it["reasons"][0]["dates"]] == [2, 4]
    one_high = run([row(1, "A", "medium"), row(2, "B", "high"), row(3, "C"), row(4, "D"), row(5, "E", "medium")])
    assert not any("repeated_high" in kinds(i) for i in one_high["items"])  # one high only: no repeated-high item


# ---------------- deduplication / cap / ordering ----------------
def test_high_plus_recurring_plus_expert_is_ONE_item_with_several_reasons():
    rows = [row(1, BLIGHT, "medium"), row(2, NUTR), row(3, BLIGHT, "medium"), row(4, NUTR), row(5, BLIGHT, "high")]
    r = run(rows)
    mine = [i for i in r["items"] if i["issue"] == BLIGHT]
    assert len(mine) == 1  # one issue -> one item, never three alerts
    it = mine[0]
    assert kinds(it) == ["latest_high", "recurring"] and it["priority"] == "important" and it["expert_suggested"] is True
    assert it["evidence_count"] == 3 and [d["analysis_id"] for d in it["reasons"][1]["dates"]] == [1, 3, 5]
    assert it["analysis_id"] == 5  # navigation target: the most recent check for that issue


def test_at_most_three_items_and_deterministic_order():
    def trend(kind, issue, day, count=3):
        return {"kind": kind, "issue": issue, "count": count, "window": 6, "earlier_count": 0, "evidence": [{"analysis_id": day, "at": T0 + timedelta(days=day)}]}
    insights = {"total": 8, "trends": [trend("recurring", "Alpha", 1), trend("recurring", "Beta", 5), trend("more_frequent", "Gamma", 4), trend("recurring", "Delta", 6), trend("repeated_high", "Epsilon", 2)],
                "recent": [{"analysis_id": d, "crop": "Tomato"} for d in range(1, 9)]}
    decision = {"observed": None, "analysis_id": None, "state": "no_actionable_evidence", "expert_reason": None, "actions": []}
    r = build_proactive_items(insights, decision)
    assert len(r["items"]) == MAX_ITEMS == 3
    assert [i["issue"] for i in r["items"]] == ["Epsilon", "Delta", "Beta"]  # important first, then recurring newest-first; more_frequent/older dropped
    assert r["items"][0]["priority"] == "important" and r["level"] == "important"
    again = build_proactive_items(insights, decision)
    assert again == r


def test_output_is_deterministic_and_independent_of_input_order():
    rows = [row(3, BLIGHT, "medium"), row(1, NUTR), row(5, BLIGHT, "medium"), row(2, BLIGHT, "medium"), row(4, NUTR)]
    a = run(rows)
    assert a == run(list(reversed(rows))) == run(sorted(rows, key=lambda r: r["id"])) == run(rows)


def test_unclear_latest_check_creates_no_item_by_itself():
    assert run([row(1, UNCLEAR, "unknown")])["items"] == []


# ---------------- evidence boundary ----------------
def test_context_alone_never_creates_an_item_and_never_changes_items():
    assert run([], FULL_CTX)["items"] == []
    assert run([row(1, BLIGHT, "low")], FULL_CTX)["items"] == []
    rows = [row(1, BLIGHT, "medium"), row(2, NUTR), row(3, BLIGHT, "medium"), row(4, NUTR), row(5, BLIGHT, "medium")]
    assert run(rows, FULL_CTX) == run(rows, {})  # NULL vs present Phase 10 context: identical output


def test_notes_and_extra_fields_never_enter_the_output():
    r = row(1, BLIGHT, "medium")
    r.update({"explanation": "SECRET-EXPLANATION", "recommended_actions": ["Spray 5 ml per litre"], "immediate_actions": ["Apply fertiliser"]})
    out = json.dumps(run([r], {**FULL_CTX, "notes": "PRIVATE-NOTE"}), default=str)
    for bad in ("SECRET-EXPLANATION", "Spray", "fertiliser", "PRIVATE-NOTE", "irrigation", "drip"):
        assert bad not in out


def test_missing_crop_does_not_crash_or_get_invented():
    it = run([row(1, BLIGHT, "high", crop="")])["items"][0]
    assert it["crop"] == ""


def test_actions_stay_inside_the_closed_phase11_catalogue_and_no_active_state_wording():
    from app.services.decision_support import ACTIONS

    rows = [row(1, BLIGHT, "medium"), row(2, NUTR), row(3, BLIGHT, "medium"), row(4, NUTR), row(5, BLIGHT, "high")]
    out = run(rows)
    assert all(set(i["actions"]) <= set(ACTIONS) and len(i["actions"]) == 1 for i in out["items"])
    text = json.dumps(out, default=str).lower()
    for banned in ("currently", "still present", "spreading", "is affected", "active"):
        assert banned not in text


# ---------------- API ----------------
def _farm(c, **kw):
    r = c.post("/farms", json={"name": "F", "location": "Guntur", "soil_type": "Red soil", **kw})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _insert(farm_id, issue, severity="unknown", day=0, crop="Tomato"):
    from app.database import SessionLocal
    from app.models import Analysis, Farm

    with SessionLocal() as db:
        farm = db.get(Farm, farm_id)
        a = Analysis(user_id=farm.user_id, farm_id=farm_id, crop=crop, symptoms="x", language="en",
                     result_json={"likely_issue": issue, "explanation": "SECRET-EXPLANATION", "recommended_actions": ["Spray 5 ml per litre"], "precautions": ["p"],
                                  "uncertainty": "u", "severity": severity, "uncertainty_level": "some", "image_quality": "good", "immediate_actions": ["Apply fertiliser now"]},
                     created_at=T0 + timedelta(days=day))
        db.add(a); db.commit()
        return a.id


def test_api_empty_and_quiet_farms_are_200_with_no_items(register):
    c = register()
    fid = _farm(c)
    j = c.get(f"/farms/{fid}/proactive").json()
    assert j["level"] == "none" and j["items"] == [] and j["total_checks"] == 0
    _insert(fid, BLIGHT, "low", day=1)
    assert c.get(f"/farms/{fid}/proactive").json()["items"] == []


def test_api_combined_item_evidence_dates_match_real_checks_and_links_are_only_this_farms(register):
    c = register()
    fid, other = _farm(c), _farm(c, name="Other")
    ids = [_insert(fid, BLIGHT if i in (1, 3, 5) else NUTR, "high" if i == 5 else "medium", day=i) for i in range(1, 6)]
    _insert(other, BLIGHT, "high", day=2)
    j = c.get(f"/farms/{fid}/proactive").json()
    it = next(i for i in j["items"] if i["issue"] == BLIGHT)
    assert it["priority"] == "important" and [r["kind"] for r in it["reasons"]] == ["latest_high", "recurring"] and it["expert_suggested"] is True
    shown = {d["analysis_id"] for i in j["items"] for r in i["reasons"] for d in r["dates"]} | {i["analysis_id"] for i in j["items"]}
    assert shown <= set(ids)  # every referenced check is one of THIS farm's stored checks
    assert all(d["at"].endswith(("Z", "+00:00")) for i in j["items"] for r in i["reasons"] for d in r["dates"]) and it["latest_at"].endswith(("Z", "+00:00"))


def test_api_analysis_ids_cannot_be_used_to_read_someone_elses_check(register):
    a, b = register("a@example.com"), register("b@example.com")
    fa = _farm(a)
    _insert(fa, BLIGHT, "high", day=1)
    ref = a.get(f"/farms/{fa}/proactive").json()["items"][0]["analysis_id"]
    assert a.get(f"/analyses/{ref}").status_code == 200  # the owner can open it
    miss = b.get("/analyses/999999")
    foreign = b.get(f"/analyses/{ref}")  # another user holding the id gets the same 404 as a missing check
    assert foreign.status_code == 404 and foreign.json() == miss.json()
    assert b.get(f"/analyses/{ref}/image").status_code == 404 and b.get(f"/analyses/{ref}/translate").status_code in (404, 405)


def test_api_authorization_and_id_matrix(register, client):
    a, b = register("a@example.com"), register("b@example.com")
    fa = _farm(a)
    _insert(fa, BLIGHT, "high", day=1)
    miss = b.get("/farms/999999/proactive")
    foreign = b.get(f"/farms/{fa}/proactive")
    assert foreign.status_code == miss.status_code == 404 and foreign.json() == miss.json()
    for bad in ("99999999999999999999", "0", "-3"):
        r = b.get(f"/farms/{bad}/proactive")
        assert r.status_code == 404 and r.json() == miss.json()
    assert b.get("/farms/abc/proactive").status_code == 422
    assert client.get(f"/farms/{fa}/proactive").status_code == 401
    assert a.get(f"/farms/{fa}/proactive").status_code == 200


def test_api_is_read_only_makes_no_model_or_weather_calls_and_leaks_nothing(register, monkeypatch):
    from sqlalchemy import text

    from app.database import SessionLocal
    from app.services import weather
    from app.services.ai import service

    def boom(*a, **k):
        raise AssertionError("must not be called")

    c = register()
    fid = _farm(c, notes="PRIVATE-NOTE", primary_crop="Tomato", irrigation_method="drip")
    for i in range(1, 6):
        _insert(fid, BLIGHT, "high" if i == 5 else "medium", day=i)
    monkeypatch.setattr(service, "get_provider", boom)
    monkeypatch.setattr(weather.client, "fetch", boom)

    def snapshot():
        with SessionLocal() as db:
            return {t: [tuple(map(str, r)) for r in db.execute(text(f"select * from {t} order by id")).all()] for t in ("users", "farms", "analyses")}

    before = snapshot()
    r1 = c.get(f"/farms/{fid}/proactive")
    assert r1.status_code == 200 and c.get(f"/farms/{fid}/proactive").json() == r1.json()
    assert snapshot() == before  # nothing written, nothing modified
    for banned in ("user_id", "SECRET-EXPLANATION", "Spray", "fertiliser", "PRIVATE-NOTE", "drip", "explanation", "recommended_actions", "temperature", "Traceback"):
        assert banned not in r1.text, banned
    assert len(r1.json()["items"]) <= 3


def test_api_works_on_an_old_shape_database_after_the_scratch_migration(tmp_path):
    import os, subprocess, sys, textwrap

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
        INSERT INTO farms VALUES (2,1,'Quiet Farm','','','2026-10-01 10:00:00');
        INSERT INTO analyses (id,user_id,farm_id,crop,symptoms,language,result_json,created_at) VALUES
          (1,1,1,'Rice','x','en','{"likely_issue":"Old leaf spot","explanation":"e","recommended_actions":["a"],"precautions":["p"],"uncertainty":"u","severity":"high"}','2026-10-01 11:00:00');
        """
    )
    con.commit(); con.close()
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
            print(json.dumps({{"busy": c.get("/farms/1/proactive").json(), "quiet": c.get("/farms/2/proactive").json()}}))
        """
    )
    r = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, cwd=os.path.dirname(os.path.dirname(__file__)))
    assert r.returncode == 0, r.stderr[-600:]
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["busy"]["level"] == "important" and out["busy"]["items"][0]["reasons"][0]["kind"] == "latest_high"
    assert out["quiet"] == {"farm_id": 2, "level": "none", "total_checks": 0, "items": []}
