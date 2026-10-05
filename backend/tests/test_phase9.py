"""Phase 9: farm insights. Deterministic statistics from stored checks only. Scratch DB (see conftest)."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.insights import build_insights, is_unclear, issue_key

T0 = datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc)
BLIGHT = "Leaf spot disease (early blight)"
NUTR = "Possible nutrient deficiency or watering problem (leaf yellowing)"
UNCLEAR = "Unable to pinpoint the problem from this description"


def row(i, issue, severity="unknown", crop="Tomato", day=None):
    return {"id": i, "crop": crop, "created_at": T0 + timedelta(days=i if day is None else day), "likely_issue": issue, "severity": severity}


def kinds(r):
    return [t["kind"] for t in r["trends"]]


# ---------------- pure logic ----------------
def test_issue_key_ignores_hedging_parentheses_case_and_punctuation():
    assert issue_key("Possible Nutrient Deficiency (Nitrogen)!") == issue_key("nutrient deficiency")
    assert issue_key("Leaf spot, disease") == "leaf spot disease"
    assert issue_key("నత్రజని లోపం (Nitrogen deficiency)") == "నత్రజని లోపం"  # Telugu kept as written


def test_unclear_issues_are_detected_in_both_languages():
    assert is_unclear(UNCLEAR) and is_unclear("ఈ వివరణతో సమస్య ఏమిటో స్పష్టంగా చెప్పలేము") and is_unclear("")
    assert not is_unclear(BLIGHT)


def test_no_checks():
    r = build_insights([])
    assert r["level"] == "none" and r["total"] == 0 and r["latest"] is None and r["trends"] == [] and r["comparison"] is None
    assert r["recent"] == [] and r["issues"] == [] and r["severity_counts"] == {"low": 0, "medium": 0, "high": 0, "unknown": 0}


def test_one_check_has_no_trend_and_no_comparison():
    r = build_insights([row(1, BLIGHT, "medium")])
    assert r["level"] == "one" and r["total"] == 1 and r["trends"] == [] and r["comparison"] is None
    assert r["latest"]["issue"] == BLIGHT and r["severity_counts"]["medium"] == 1


def test_two_and_three_checks_compare_but_never_claim_a_trend():
    r2 = build_insights([row(1, BLIGHT), row(2, BLIGHT)])
    assert r2["level"] == "limited" and r2["trends"] == []
    assert r2["comparison"]["same_issue"] is True and r2["comparison"]["comparable"] is True
    r3 = build_insights([row(1, BLIGHT), row(2, BLIGHT), row(3, BLIGHT)])
    assert r3["level"] == "limited" and r3["trends"] == []  # three identical checks are still "limited history"


def test_comparison_reports_a_change_and_does_not_compare_unclear_checks():
    r = build_insights([row(1, BLIGHT, "low"), row(2, NUTR, "medium")])
    c = r["comparison"]
    assert c["same_issue"] is False and c["severity_changed"] is True and c["previous"]["analysis_id"] == 1 and c["latest"]["analysis_id"] == 2
    u = build_insights([row(1, BLIGHT), row(2, UNCLEAR)])["comparison"]
    assert u["comparable"] is False and u["same_issue"] is False


def test_recurring_needs_3_of_last_6_on_2_days_and_enough_history():
    rows = [row(1, BLIGHT), row(2, NUTR), row(3, BLIGHT), row(4, NUTR), row(5, BLIGHT)]
    r = build_insights(rows)
    rec = [t for t in r["trends"] if t["kind"] == "recurring"]
    assert r["level"] == "enough" and [t["issue"] for t in rec] == [BLIGHT]  # blight 3 of 5; nutrient only 2 -> not reported
    blight = rec[0]
    assert blight["count"] == 3 and blight["window"] == 5
    assert [e["analysis_id"] for e in blight["evidence"]] == [1, 3, 5]  # the evidence IS the matching records


def test_one_short_of_the_threshold_claims_nothing():
    r = build_insights([row(1, BLIGHT), row(2, NUTR), row(3, BLIGHT), row(4, "Insect pest damage")])
    assert r["level"] == "enough" and "recurring" not in kinds(r)  # only 2 of 4


def test_same_day_repeats_are_not_recurrence():
    rows = [row(i, BLIGHT, day=0) for i in range(1, 4)] + [row(4, NUTR, day=0)]
    assert "recurring" not in kinds(build_insights(rows))


def test_unclear_checks_never_count_as_a_recurring_issue():
    rows = [row(i, UNCLEAR) for i in range(1, 6)]
    r = build_insights(rows)
    assert r["trends"] == [] and r["unclear_count"] == 5 and r["issues"] == []


def test_frequency_trends_need_six_checks_and_a_difference_of_two():
    more = [row(1, NUTR), row(2, NUTR), row(3, "Pest A"), row(4, BLIGHT), row(5, BLIGHT), row(6, BLIGHT)]
    r = build_insights(more)
    assert any(t["kind"] == "more_frequent" and t["issue"] == BLIGHT and t["count"] == 3 and t["earlier_count"] == 0 for t in r["trends"])
    less = [row(1, BLIGHT), row(2, BLIGHT), row(3, BLIGHT), row(4, NUTR), row(5, NUTR), row(6, "Pest B")]
    assert any(t["kind"] == "less_frequent" and t["issue"] == BLIGHT for t in build_insights(less)["trends"])
    five = build_insights([row(1, BLIGHT), row(2, BLIGHT), row(3, NUTR), row(4, NUTR), row(5, NUTR)])
    assert "more_frequent" not in kinds(five) and "less_frequent" not in kinds(five)
    small_diff = build_insights([row(1, BLIGHT), row(2, NUTR), row(3, "P"), row(4, BLIGHT), row(5, BLIGHT), row(6, "Q")])
    assert not any(t["kind"] in ("more_frequent", "less_frequent") and t["issue"] == BLIGHT for t in small_diff["trends"])


def test_repeated_high_uses_only_real_high_never_unknown():
    r = build_insights([row(1, NUTR), row(2, BLIGHT, "high"), row(3, "Pest", "unknown"), row(4, "Pest2", "unknown"), row(5, BLIGHT, "high")])
    t = next(t for t in r["trends"] if t["kind"] == "repeated_high")
    assert t["count"] == 2 and [e["analysis_id"] for e in t["evidence"]] == [2, 5]
    none = build_insights([row(i, f"Issue {i}", "unknown") for i in range(1, 7)])
    assert "repeated_high" not in kinds(none)
    one = build_insights([row(i, f"Issue {i}", "high" if i == 6 else "unknown") for i in range(1, 7)])
    assert "repeated_high" not in kinds(one)


def test_stable_requires_same_issue_and_same_severity_in_last_three():
    rows = [row(1, "Pest"), row(2, "Other"), row(3, NUTR, "medium"), row(4, NUTR, "medium"), row(5, NUTR, "medium")]
    got = build_insights(rows)
    assert "stable" in kinds(got) and "recurring" in kinds(got)
    st = next(t for t in got["trends"] if t["kind"] == "stable")
    assert st["severity"] == "medium" and [e["analysis_id"] for e in st["evidence"]] == [3, 4, 5]
    changed = [row(1, "Pest"), row(2, "Other"), row(3, NUTR, "low"), row(4, NUTR, "medium"), row(5, NUTR, "medium")]
    assert "stable" not in kinds(build_insights(changed))


def test_order_of_input_does_not_matter_and_timestamps_are_utc():
    rows = [row(3, BLIGHT), row(1, NUTR), row(2, BLIGHT), row(4, "X")]
    shuffled = build_insights(rows)
    ordered = build_insights(sorted(rows, key=lambda r: r["id"]))
    assert shuffled == ordered
    assert shuffled["latest"]["analysis_id"] == 4 and shuffled["recent"][0]["analysis_id"] == 4
    naive = dict(row(9, BLIGHT)); naive["created_at"] = datetime(2026, 8, 1, 9, 0)  # SQLite returns naive UTC
    assert build_insights([naive])["latest"]["at"].tzinfo is not None


def test_severity_distribution_and_issue_frequency():
    rows = [row(1, BLIGHT, "low"), row(2, BLIGHT, "medium"), row(3, NUTR, "unknown"), row(4, NUTR, "bogus")]
    r = build_insights(rows)
    assert r["severity_counts"] == {"low": 1, "medium": 1, "high": 0, "unknown": 2}
    assert [(g["label"], g["count"]) for g in r["issues"]] == [(NUTR, 2), (BLIGHT, 2)]  # tie -> most recently seen first
    assert sum(len(g["evidence"]) for g in r["issues"]) == 4


# ---------------- API ----------------
def _farm(c, name="F", location="Guntur"):
    return c.post("/farms", json={"name": name, "location": location}).json()["id"]


def _insert(farm_id, issue, severity="unknown", day=0, crop="Tomato", weather=None):
    from app.database import SessionLocal
    from app.models import Analysis, Farm

    with SessionLocal() as db:
        farm = db.get(Farm, farm_id)
        a = Analysis(user_id=farm.user_id, farm_id=farm_id, crop=crop, symptoms="x", language="en",
                     result_json={"likely_issue": issue, "explanation": "e", "recommended_actions": ["a"], "precautions": ["p"], "uncertainty": "u", "severity": severity},
                     created_at=T0 + timedelta(days=day), weather_json=weather)
        db.add(a); db.commit()
        return a.id


def test_empty_farm_insights(register):
    c = register()
    r = c.get(f"/farms/{_farm(c)}/insights")
    assert r.status_code == 200
    j = r.json()
    assert j["level"] == "none" and j["total"] == 0 and j["trends"] == [] and j["latest"] is None


def test_one_and_many_checks_via_api_and_evidence_matches_records(register):
    c = register()
    fid = _farm(c)
    ids = [_insert(fid, BLIGHT if i in (1, 3, 5) else NUTR, "medium", day=i) for i in range(1, 6)]
    j = c.get(f"/farms/{fid}/insights").json()
    assert j["level"] == "enough" and j["total"] == 5 and j["latest"]["analysis_id"] == ids[-1]
    rec = next(t for t in j["trends"] if t["kind"] == "recurring")
    assert [e["analysis_id"] for e in rec["evidence"]] == [ids[0], ids[2], ids[4]]
    assert all(e["at"].endswith(("Z", "+00:00")) for e in rec["evidence"])
    # every evidence id is a real analysis of THIS farm
    assert {e["analysis_id"] for t in j["trends"] for e in t["evidence"]} <= set(ids)


def test_one_check_via_api(register):
    c = register()
    fid = _farm(c)
    _insert(fid, BLIGHT, "low")
    j = c.get(f"/farms/{fid}/insights").json()
    assert j["level"] == "one" and j["total"] == 1 and j["trends"] == [] and j["comparison"] is None


def test_only_this_farms_checks_are_used(register):
    c = register()
    f1, f2 = _farm(c, "A"), _farm(c, "B")
    _insert(f1, BLIGHT, day=1); _insert(f2, NUTR, day=2); _insert(f2, NUTR, day=3)
    assert c.get(f"/farms/{f1}/insights").json()["total"] == 1
    assert c.get(f"/farms/{f2}/insights").json()["total"] == 2


def test_other_users_farm_missing_farm_and_garbage_ids_are_the_same_404(register):
    a, b = register("a@example.com"), register("b@example.com")
    fa = _farm(a); _insert(fa, BLIGHT)
    miss = b.get("/farms/999999/insights")
    foreign = b.get(f"/farms/{fa}/insights")
    assert foreign.status_code == miss.status_code == 404 and foreign.json() == miss.json()
    for bad in ("99999999999999999999", "0", "-3"):
        r = b.get(f"/farms/{bad}/insights")
        assert r.status_code == 404 and r.json() == miss.json()
    assert b.get("/farms/abc/insights").status_code == 422
    assert a.get(f"/farms/{fa}/insights").status_code == 200


def test_requires_login(client):
    assert client.get("/farms/1/insights").status_code == 401


def test_response_has_no_user_ids_no_weather_and_no_telemetry(register):
    c = register()
    fid = _farm(c)
    _insert(fid, BLIGHT, day=1, weather={"location_name": "X", "temperature_c": 33.0, "trend": "wetter"})
    _insert(fid, NUTR, day=2)
    text = c.get(f"/farms/{fid}/insights").text
    for banned in ("user_id", "temperature", "weather", "ndvi", "moisture", "sensor", "nitrogen_mg", "symptoms", "wetter"):
        assert banned not in text.lower(), banned


def test_insights_make_one_query_and_never_call_the_ai_or_weather(register, monkeypatch):
    from app.services import weather
    from app.services.ai import service

    def boom(*a, **k):
        raise AssertionError("must not be called")

    monkeypatch.setattr(service, "get_provider", boom)
    monkeypatch.setattr(weather.client, "fetch", boom)
    c = register()
    fid = _farm(c)
    for i in range(1, 8):
        _insert(fid, BLIGHT, day=i)
    assert c.get(f"/farms/{fid}/insights").status_code == 200


def test_only_the_newest_100_checks_are_considered(register):
    c = register()
    fid = _farm(c)
    for i in range(1, 106):
        _insert(fid, f"Issue {i}", day=i)
    j = c.get(f"/farms/{fid}/insights").json()
    assert j["total"] == 100 and j["latest"]["issue"] == "Issue 105"
