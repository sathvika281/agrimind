"""Phase 11: rule-based decision support. Deterministic, read-only, evidence-bounded. Scratch DB only (see conftest)."""
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from app.services.decision_support import ACTIONS, EXPERT, MONITOR, NONE, VERIFY, decide

T0 = datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc)
BLIGHT = "Leaf spot disease (early blight)"
NUTR = "Possible nutrient deficiency or watering problem (leaf yellowing)"
UNCLEAR = "Unable to pinpoint the problem from this description"
NO_CTX = {}
FULL_CTX = {"primary_crop": "Tomato", "irrigation_method": "drip", "season": "kharif", "planting_date": "2026-07-01", "soil_type": "Red soil", "location": "Guntur"}


def row(i, issue=BLIGHT, severity="unknown", crop="Tomato", unc="some", quality="good", day=None):
    return {"id": i, "crop": crop, "created_at": T0 + timedelta(days=i if day is None else day), "likely_issue": issue, "severity": severity,
            "uncertainty_level": unc, "image_quality": quality, "input_type": "text"}


def many(n, issue=BLIGHT, severity="unknown"):
    return [row(i, issue, severity) for i in range(1, n + 1)]


# ---------------- states and their exact triggers ----------------
def test_no_checks_is_no_actionable_evidence_and_says_nothing_about_treatment():
    d = decide([], NO_CTX)
    assert d["state"] == NONE and d["actions"] == [] and d["observed"] is None and d["level"] == "none"
    assert "no_treatment" in d["limitations"]


def test_unclear_issue_is_no_actionable_evidence_with_only_add_detail():
    d = decide([row(1, UNCLEAR)], NO_CTX)
    assert d["state"] == NONE and d["actions"] == ["add_detail"] and d["observed"]["unclear"] is True


def test_one_medium_check_is_verify_not_expert():
    d = decide([row(1, BLIGHT, "medium")], NO_CTX)
    assert d["state"] == VERIFY and d["actions"] == ["inspect_plants", "check_spread"] and d["expert_reason"] is None


def test_one_low_check_is_monitor():
    d = decide([row(1, BLIGHT, "low")], NO_CTX)
    assert d["state"] == MONITOR and d["actions"] == ["recheck_if_changes", "check_spread"]


def test_unknown_severity_never_becomes_high_or_expert():
    d = decide(many(6, BLIGHT, "unknown")[:3], NO_CTX)  # 3 identical unrated checks
    assert d["state"] == VERIFY and d["expert_reason"] is None and d["observed"]["severity"] == "unknown"
    assert any(e["kind"] == "severity" and e["value"] == "not_recorded" for e in d["evidence"])
    assert "severity_not_recorded" in d["limitations"]


def test_real_high_severity_is_expert_help_with_a_reason():
    d = decide([row(1, BLIGHT, "high")], NO_CTX)
    assert d["state"] == EXPERT and d["expert_reason"] == "severity_high" and d["actions"] == ["consult_expert", "check_spread"]


def test_repeated_high_is_expert_one_high_is_not():
    two_high = [row(1, "A", "medium"), row(2, "B", "high"), row(3, "C", "unknown"), row(4, "D", "high"), row(5, "E", "medium")]
    d = decide(two_high, NO_CTX)
    assert d["state"] == EXPERT and d["expert_reason"] == "repeated_high"
    one_high = [row(1, "A", "medium"), row(2, "B", "high"), row(3, "C"), row(4, "D"), row(5, "E", "medium")]
    assert decide(one_high, NO_CTX)["state"] == VERIFY  # one short of the Phase 9 threshold: no escalation


def test_recurring_same_issue_as_this_check_is_expert():
    rows = [row(1, BLIGHT), row(2, NUTR), row(3, BLIGHT), row(4, NUTR), row(5, BLIGHT)]
    d = decide(rows, NO_CTX)
    assert d["state"] == EXPERT and d["expert_reason"] == "recurring"
    assert any(e["kind"] == "history_same_issue" and e["count"] == 3 for e in d["evidence"])
    assert [x["analysis_id"] for x in next(e for e in d["evidence"] if e["kind"] == "history_same_issue")["dates"]] == [1, 3, 5]


def test_recurring_of_a_DIFFERENT_issue_does_not_escalate_this_check():
    rows = [row(1, BLIGHT), row(2, NUTR), row(3, BLIGHT), row(4, BLIGHT), row(5, "Insect pest damage")]
    d = decide(rows, NO_CTX)  # blight recurs, but the check being described is the insect one
    assert d["state"] == VERIFY and d["expert_reason"] is None


def test_isolated_issue_is_never_called_recurring_and_below_threshold_does_not_escalate():
    for rows in (many(2), many(3), [row(1, BLIGHT), row(2, NUTR), row(3, BLIGHT), row(4, "Pest")]):
        d = decide(rows, NO_CTX)
        assert d["state"] == VERIFY and d["expert_reason"] is None
        assert not any(e["kind"] == "trend" for e in d["evidence"])


def test_more_frequent_same_issue_is_expert_with_six_checks():
    rows = [row(1, NUTR), row(2, NUTR), row(3, "Pest A"), row(4, BLIGHT), row(5, BLIGHT), row(6, BLIGHT)]
    d = decide(rows, NO_CTX)
    assert d["state"] == EXPERT and d["expert_reason"] in ("recurring", "more_frequent")


def test_second_action_depends_on_photo_quality_and_uncertainty():
    assert decide([row(1, BLIGHT, "medium", quality="poor")], NO_CTX)["actions"] == ["inspect_plants", "record_clearer_photo"]
    assert decide([row(1, BLIGHT, "medium", quality="limited")], NO_CTX)["actions"][1] == "record_clearer_photo"
    assert decide([row(1, BLIGHT, "medium", unc="high")], NO_CTX)["actions"] == ["inspect_plants", "compare_plants"]
    assert decide([row(1, BLIGHT, "medium", unc="some")], NO_CTX)["actions"] == ["inspect_plants", "check_spread"]


# ---------------- universal safety boundary ----------------
SCENARIOS = {
    "none": [],
    "unclear": [row(1, UNCLEAR)],
    "verify": [row(1, BLIGHT, "medium")],
    "monitor": [row(1, BLIGHT, "low")],
    "expert": [row(1, BLIGHT, "high")],
    "recurring": [row(1, BLIGHT), row(2, NUTR), row(3, BLIGHT), row(4, NUTR), row(5, BLIGHT)],
}


@pytest.mark.parametrize("name", list(SCENARIOS))
@pytest.mark.parametrize("ctx", [NO_CTX, FULL_CTX])
def test_no_treatment_limitation_is_present_in_EVERY_state(name, ctx):
    d = decide(SCENARIOS[name], ctx)
    assert d["limitations"][0] == "no_treatment", (name, d["limitations"])
    assert len(d["actions"]) <= 2 and set(d["actions"]) <= set(ACTIONS)


def test_action_catalogue_is_closed_and_has_no_treatment_actions():
    assert ACTIONS == ("inspect_plants", "compare_plants", "check_spread", "record_clearer_photo", "recheck_if_changes", "consult_expert", "add_detail")
    banned = ("spray", "apply", "dose", "dosage", "fertil", "irrigat", "pesticide", "fungicide", "treat", "water")
    assert not [a for a in ACTIONS if any(b in a for b in banned)]


# ---------------- evidence boundary ----------------
def test_notes_and_unknown_inputs_never_enter_the_output():
    d = decide(many(2), {**FULL_CTX, "notes": "PRIVATE-NOTE-123"})
    assert "PRIVATE-NOTE-123" not in json.dumps(d, default=str)
    assert {c["field"] for c in d["context"]} == {"primary_crop", "irrigation_method", "season", "planting_date", "soil_type", "location"}


def test_context_is_background_only_and_missing_context_is_a_limitation():
    with_ctx = decide(many(2), FULL_CTX)
    assert "context_not_causal" in with_ctx["limitations"] and "no_farm_context" not in with_ctx["limitations"]
    assert with_ctx["state"] == decide(many(2), NO_CTX)["state"]  # context never changes the decision
    assert with_ctx["actions"] == decide(many(2), NO_CTX)["actions"]
    without = decide(many(2), NO_CTX)
    assert "no_farm_context" in without["limitations"] and without["context"] == []
    partial = decide(many(2), {"primary_crop": "Tomato", "irrigation_method": None, "season": "", "planting_date": None})
    assert [c["field"] for c in partial["context"]] == ["primary_crop"]  # missing stays missing; nothing is filled in


def test_missing_crop_does_not_crash_or_get_invented():
    d = decide([row(1, BLIGHT, crop="")], NO_CTX)
    assert d["observed"]["crop"] == "" and d["state"] == VERIFY


def test_extra_model_text_fields_are_never_read():
    r = row(1, BLIGHT, "medium")
    r.update({"immediate_actions": ["Spray 5 ml per litre"], "recommended_actions": ["Apply fertiliser"], "explanation": "Use pesticide X"})
    out = json.dumps(decide([r], NO_CTX), default=str)
    for bad in ("Spray", "5 ml", "fertiliser", "pesticide"):
        assert bad not in out


# ---------------- determinism and time-correctness ----------------
def test_output_is_deterministic_and_independent_of_input_order():
    rows = [row(3, BLIGHT), row(1, NUTR), row(5, BLIGHT), row(2, BLIGHT), row(4, NUTR)]
    a = decide(rows, FULL_CTX)
    assert a == decide(list(reversed(rows)), FULL_CTX) == decide(sorted(rows, key=lambda r: r["id"]), FULL_CTX) == decide(rows, FULL_CTX)


def test_a_check_is_described_as_of_that_check_later_checks_cannot_change_it():
    rows = [row(1, BLIGHT), row(2, NUTR), row(3, BLIGHT), row(4, NUTR), row(5, BLIGHT), row(6, BLIGHT, "high")]
    early = decide(rows, NO_CTX, target_id=3)
    assert early == decide(rows[:3], NO_CTX, target_id=3) == decide(rows[:3], NO_CTX)
    assert early["state"] == VERIFY and early["history_total"] == 3 and early["analysis_id"] == 3
    assert decide(rows, NO_CTX, target_id=5)["state"] == EXPERT  # at check 5 blight had recurred
    assert decide(rows, NO_CTX)["analysis_id"] == 6 and decide(rows, NO_CTX)["state"] == EXPERT


def test_history_insufficient_limitation_below_four_checks():
    assert "history_insufficient" in decide(many(3), NO_CTX)["limitations"]
    assert "history_insufficient" not in decide([row(i, f"Issue {i}") for i in range(1, 5)], NO_CTX)["limitations"]


# ---------------- API ----------------
def _farm(c, **kw):
    r = c.post("/farms", json={"name": "F", "location": "Guntur", "soil_type": "Red soil", **kw})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _insert(farm_id, issue, severity="unknown", day=0, crop="Tomato", unc="some", quality="good"):
    from app.database import SessionLocal
    from app.models import Analysis, Farm

    with SessionLocal() as db:
        farm = db.get(Farm, farm_id)
        a = Analysis(user_id=farm.user_id, farm_id=farm_id, crop=crop, symptoms="x", language="en",
                     result_json={"likely_issue": issue, "explanation": "SECRET-EXPLANATION", "recommended_actions": ["Spray 5 ml per litre"], "precautions": ["p"],
                                  "uncertainty": "u", "severity": severity, "uncertainty_level": unc, "image_quality": quality, "immediate_actions": ["Apply fertiliser now"]},
                     created_at=T0 + timedelta(days=day))
        db.add(a); db.commit()
        return a.id


def test_api_zero_checks_is_200_no_actionable_evidence(register):
    c = register()
    r = c.get(f"/farms/{_farm(c)}/decision-support")
    assert r.status_code == 200
    j = r.json()
    assert j["state"] == "no_actionable_evidence" and j["analysis_id"] is None and "no_treatment" in j["limitations"] and j["observed"] is None


def test_api_latest_by_default_and_as_of_with_analysis_id(register):
    c = register()
    fid = _farm(c)
    ids = [_insert(fid, BLIGHT if i in (1, 3, 5) else NUTR, "medium", day=i) for i in range(1, 6)]
    latest = c.get(f"/farms/{fid}/decision-support").json()
    assert latest["analysis_id"] == ids[-1] and latest["state"] == "seek_expert_help" and latest["expert_reason"] == "recurring"
    third = c.get(f"/farms/{fid}/decision-support", params={"analysis_id": ids[2]}).json()
    assert third["analysis_id"] == ids[2] and third["state"] == "verify" and third["history_total"] == 3  # later checks don't leak in
    trend = next(e for e in latest["evidence"] if e["kind"] == "history_same_issue")
    assert [d["analysis_id"] for d in trend["dates"]] == [ids[0], ids[2], ids[4]]
    assert all(d["at"].endswith(("Z", "+00:00")) for d in trend["dates"]) and latest["observed"]["checked_at"].endswith(("Z", "+00:00"))


def test_api_uses_recorded_context_only_as_background(register):
    c = register()
    fid = _farm(c, primary_crop="Tomato", irrigation_method="drip", notes="PRIVATE-NOTE-XYZ")
    _insert(fid, BLIGHT, "medium", day=1)
    j = c.get(f"/farms/{fid}/decision-support").json()
    assert {x["field"]: x["value"] for x in j["context"]}["irrigation_method"] == "drip" and "context_not_causal" in j["limitations"]
    assert "PRIVATE-NOTE-XYZ" not in json.dumps(j)
    bare = _farm(c)
    _insert(bare, BLIGHT, "medium", day=1)
    jb = c.get(f"/farms/{bare}/decision-support").json()
    assert {x["field"] for x in jb["context"]} == {"location", "soil_type"}  # only what exists; nothing added
    assert "primary_crop" not in {x["field"] for x in jb["context"]}  # Phase 10 fields NULL -> unknown, not guessed
    assert j["state"] == jb["state"]  # context never changes the state


def test_api_authorization_and_id_matrix(register, client):
    a, b = register("a@example.com"), register("b@example.com")
    fa, fb = _farm(a), _farm(b)
    ia = _insert(fa, BLIGHT, "high", day=1)
    ib = _insert(fb, BLIGHT, day=1)
    miss = b.get("/farms/999999/decision-support")
    foreign = b.get(f"/farms/{fa}/decision-support")
    assert foreign.status_code == miss.status_code == 404 and foreign.json() == miss.json()
    for bad in ("99999999999999999999", "0", "-3"):
        r = b.get(f"/farms/{bad}/decision-support")
        assert r.status_code == 404 and r.json() == miss.json()
    assert b.get("/farms/abc/decision-support").status_code == 422
    assert client.get(f"/farms/{fa}/decision-support").status_code == 401
    # another user's check on MY farm, my check on another farm, missing / impossible check ids: one identical 404
    ref = b.get(f"/farms/{fb}/decision-support", params={"analysis_id": 999999})
    assert ref.status_code == 404
    for aid in (ia, 0, -1, 99999999999999999999):
        r = b.get(f"/farms/{fb}/decision-support", params={"analysis_id": aid})
        assert r.status_code == 404 and r.json() == ref.json(), aid
    farm_b2 = _farm(b, name="B2")
    assert b.get(f"/farms/{farm_b2}/decision-support", params={"analysis_id": ib}).status_code == 404  # my check, but a different farm
    assert b.get(f"/farms/{fb}/decision-support", params={"analysis_id": "abc"}).status_code == 422
    assert a.get(f"/farms/{fa}/decision-support").status_code == 200 and b.get(f"/farms/{fb}/decision-support", params={"analysis_id": ib}).status_code == 200


def test_api_is_read_only_and_leaks_nothing(register, monkeypatch):
    from app.database import SessionLocal
    from sqlalchemy import text
    from app.services import weather
    from app.services.ai import service

    def boom(*a, **k):
        raise AssertionError("must not be called")

    c = register()
    fid = _farm(c, notes="PRIVATE")
    for i in range(1, 6):
        _insert(fid, BLIGHT, "medium", day=i)
    monkeypatch.setattr(service, "get_provider", boom)
    monkeypatch.setattr(weather.client, "fetch", boom)

    def snapshot():
        with SessionLocal() as db:
            return {t: [tuple(map(str, r)) for r in db.execute(text(f"select * from {t} order by id")).all()] for t in ("users", "farms", "analyses")}

    before = snapshot()
    r1 = c.get(f"/farms/{fid}/decision-support")
    r2 = c.get(f"/farms/{fid}/decision-support", params={"analysis_id": 2})
    assert r1.status_code == r2.status_code == 200
    assert snapshot() == before  # nothing written, nothing modified
    assert c.get(f"/farms/{fid}/decision-support").json() == r1.json()  # deterministic
    body = r1.text
    for banned in ("user_id", "SECRET-EXPLANATION", "Spray", "fertiliser", "PRIVATE", "explanation", "recommended_actions", "temperature", "Traceback"):
        assert banned not in body, banned


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
        INSERT INTO analyses (id,user_id,farm_id,crop,symptoms,language,result_json,created_at) VALUES
          (1,1,1,'Rice','x','en','{"likely_issue":"Old leaf spot","explanation":"e","recommended_actions":["a"],"precautions":["p"],"uncertainty":"u","severity":"medium"}','2026-10-01 11:00:00');
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
            r = c.get("/farms/1/decision-support")
            print(json.dumps({{"s": r.status_code, "j": r.json()}}))
        """
    )
    r = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, cwd=os.path.dirname(os.path.dirname(__file__)))
    assert r.returncode == 0, r.stderr[-600:]
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["s"] == 200 and out["j"]["state"] == "verify" and out["j"]["context"][0]["field"] in ("location", "soil_type")
    assert "primary_crop" not in {x["field"] for x in out["j"]["context"]} and "no_treatment" in out["j"]["limitations"]
