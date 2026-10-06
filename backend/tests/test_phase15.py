"""Differentiation features: Investigation Dossier + competing hypotheses (this file grows with each feature group).
Deterministic, language-neutral, no model call, no scores. Reuses the agentic test harness."""
import json

import pytest

from app.schemas import AnalysisResult
from app.services.agents import environment, farm_memory
from app.services.agents.toolbox import AgentToolbox
from app.services.ai.base import HistoryItem, WeatherContext
from app.services.ai.demo_provider import DemoAIProvider
from app.services.graph import dossier as dossier_mod
from app.services.graph.state import CropAnalysis, KnowledgeEvidence
from tests.test_agentic import GOOD, KB, Prov, SPOTS, add_check, ctx_for, run, world  # noqa: F401  (world is a fixture)

WET = dict(location_name="Guntur", humidity_pct=90, past_3d_rain_mm=14, next_3d_rain_mm=9, temp_max_c=30)
HIST = [HistoryItem(date="2026-09-01", crop="Tomato", likely_issue="Possible fungal or bacterial leaf spot")]


def kinds(facts):
    return [f.kind for f in facts]


def by_kind(facts):
    return {f.kind: f for f in facts}


# ---------------- dossier: only real, coded facts ----------------
def test_dossier_reports_what_was_really_used_and_why(world):
    db, ua, fa, *_ = world
    for d in (3, 6, 10, 15):
        add_check(db, ua, fa, "Possible fungal or bacterial leaf spot", days_ago=d)
    ctx = ctx_for(fa, weather=WeatherContext(**WET), history=HIST)
    r = run(world, Prov([{**GOOD, "cited_source_ids": ["c1"]}]), KB, ctx)
    d = r.dossier
    assert d is not None
    ev = by_kind(d.evidence)
    assert ev["observation"].used and ev["history"].used and ev["history"].count == 4
    assert ev["weather"].used and ev["knowledge"].used and ev["knowledge"].count == 1
    assert ev["diary"].used is False  # nothing recorded: reported as not used, not faked
    why = kinds(d.why)
    assert len(why) <= 4 and "history_similar" in why and "weather_consistent" in why
    assert "planting_date_missing" in kinds(d.unknown)
    assert d.hypotheses and d.hypotheses[0].rank == "better_supported"


def test_dossier_has_no_scores_percentages_or_prose_certainty(world):
    r = run(world, Prov(), KB, ctx_for(world[2], weather=WeatherContext(**WET), history=HIST))
    blob = json.dumps(r.dossier.model_dump()).lower()
    assert "%" not in blob and "score" not in blob and "confidence" not in blob and "percent" not in blob
    assert all(f.kind and f.kind.replace("_", "").isalpha() for sec in (r.dossier.evidence, r.dossier.why, r.dossier.unknown, r.dossier.verify) for f in sec)


def test_dossier_says_so_when_there_is_no_history_weather_or_knowledge(world):
    r = run(world, Prov(), None, ctx_for(world[2]))  # no weather, no history, empty knowledge base
    d = r.dossier
    ev = by_kind(d.evidence)
    assert not ev["history"].used and not ev["weather"].used and ev["weather"].detail == "no_weather" and not ev["knowledge"].used
    unknown = kinds(d.unknown)
    for k in ("no_similar_history", "no_weather", "no_knowledge_base", "soil_missing" if not world[2].soil_type else "planting_date_missing"):
        assert k in unknown
    assert "history_similar" not in kinds(d.why) and "knowledge_describes" not in kinds(d.why) and "weather_consistent" not in kinds(d.why)
    assert any(s.agent == "knowledge" and s.status == "skipped" for s in r.agent_steps)


def test_a_clarification_has_no_dossier(world):
    r = run(world, Prov(), ctx=ctx_for(world[2], symptoms="my crop is not good"))
    assert r.dossier is None and r.quick_questions


def test_a_failing_dossier_never_loses_the_answer(world, monkeypatch):
    monkeypatch.setattr(dossier_mod, "build", lambda **k: (_ for _ in ()).throw(RuntimeError("boom")))
    r = run(world)
    assert r.dossier is None and r.verdict and ("safety", "ok") in [(s.agent, s.status) for s in r.agent_steps]


def test_verify_suggestions_depend_on_the_photo(world):
    r = run(world)  # no photo at all
    assert "add_photo" in kinds(r.dossier.verify) and "recheck_later" in kinds(r.dossier.verify)


def test_the_dossier_survives_storage_as_plain_json(world):
    r = run(world)
    again = AnalysisResult.model_validate(json.loads(json.dumps(r.model_dump())))
    assert again.dossier == r.dossier
    assert AnalysisResult.model_validate({**r.model_dump(), "dossier": "garbage"}).dossier is None  # a bad value never breaks a stored result


# ---------------- competing hypotheses ----------------
def test_hypotheses_use_the_existing_candidates_and_never_say_diagnosis(world):
    r = run(world, ctx=ctx_for(world[2], weather=WeatherContext(**WET), history=HIST))
    hs = r.dossier.hypotheses
    assert 1 <= len(hs) <= 3 and hs[0].rank == "better_supported" and all(h.rank == "also_possible" for h in hs[1:])
    labels = [h.label for h in hs]
    assert r.likely_issue == labels[0]
    assert "diagnosis" not in json.dumps(r.dossier.model_dump()).lower()


def test_hypothesis_support_comes_from_history_weather_and_guidance(world):
    db, ua, fa, *_ = world
    for d in (3, 6, 10):
        add_check(db, ua, fa, "Possible fungal or bacterial leaf spot", days_ago=d)
    r = run(world, ctx=ctx_for(world[2], weather=WeatherContext(**WET), history=HIST), index=KB)
    first = r.dossier.hypotheses[0]
    sup = kinds(first.supporting)
    assert "current_observation" in sup and "history_match" in sup and "weather_consistent" in sup
    assert by_kind(first.supporting)["history_match"].count == 3


def test_hypotheses_are_hidden_for_a_no_diagnosis_result():
    base = AnalysisResult(likely_issue="Unable to pinpoint the problem from this description", explanation="x", recommended_actions=["a"], precautions=[], uncertainty="u")
    d = dossier_mod.build(base=base, final=base, crop_analysis=CropAnalysis(candidate_issues=["Unable to pinpoint the problem from this description"]), memory=None, env=None,
                          knowledge=None, farm_context={}, has_image=False, has_weather=False)
    assert d.hypotheses == []


def test_poor_photo_is_a_stated_limit_on_every_possibility(world):
    from app.services.ai.base import ImageInput

    ctx = ctx_for(world[2], image=ImageInput(b"x", "image/jpeg"))
    r = run(world, Prov(quality="poor"), ctx=ctx)
    assert "image_insufficient" in kinds(r.dossier.unknown)
    assert all("image_limited" in kinds(h.against_or_unknown) for h in r.dossier.hypotheses)


def test_how_to_tell_comes_from_the_models_own_alternatives(world):
    r = run(world)
    alts = {a.possibility.lower(): a.how_to_tell for a in r.possible_alternatives}
    for h in r.dossier.hypotheses:
        if h.label.lower() in alts:
            assert h.how_to_tell == alts[h.label.lower()]


# ---------------- per-candidate additions in the existing agents ----------------
def test_memory_counts_earlier_checks_per_candidate(world):
    db, ua, fa, *_ = world
    add_check(db, ua, fa, "Possible fungal or bacterial leaf spot")
    add_check(db, ua, fa, "Insect pest damage", days_ago=5)
    m = farm_memory.run(AgentToolbox(db, ua, fa, ctx_for(fa)), "Tomato", CropAnalysis(candidate_issues=["Fungal leaf spot", "Insect pest damage", "Nutrient deficiency"]))
    assert m.matches_by_candidate["Insect pest damage"] == 1 and m.matches_by_candidate["Nutrient deficiency"] == 0


def test_environment_signals_are_per_candidate_and_worded_as_support_not_cause():
    w = WeatherContext(location_name="x", humidity_pct=92, past_3d_rain_mm=15, temp_max_c=30)
    e = environment.run(w, CropAnalysis(candidate_issues=["Fungal leaf spot", "Water stress from heat"]))
    assert e.signals_by_candidate["Fungal leaf spot"]["supports"]
    hot = environment.run(WeatherContext(location_name="x", temp_max_c=38, past_3d_rain_mm=0, next_3d_rain_mm=0, humidity_pct=30),
                          CropAnalysis(candidate_issues=["Fungal leaf spot", "Water stress from heat"]))
    assert hot.signals_by_candidate["Fungal leaf spot"]["contradicts"] and hot.signals_by_candidate["Water stress from heat"]["supports"]


# ================= Crop Journey + Before vs Now =================
from datetime import date, datetime, timedelta, timezone  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import Analysis, Farm, FarmEvent, User  # noqa: E402
from app.services import journey  # noqa: E402


def res(issue="Possible fungal or bacterial leaf spot", sev="medium", unc="some", obs=None, change=None):
    return {"likely_issue": issue, "severity": sev, "uncertainty_level": unc, "observations": obs or [], "change": change}


@pytest.mark.parametrize("prev,now,issue,direction", [
    (res(sev="medium"), res(sev="low"), "same", "improving"),
    (res(sev="medium"), res(sev="high"), "same", "worsening"),
    (res(sev="medium"), res(sev="medium"), "same", "stable"),
    (res(sev="medium", unc="high"), res(sev="high", unc="low"), "same", "mixed"),
    (res(sev="unknown", unc="unknown"), res(sev="unknown", unc="unknown"), "same", "unclear"),  # nothing real to compare
    (res(), res("Insect pest damage", sev="high"), "different", "unclear"),  # a different issue is not a trend
    (res("Unable to pinpoint the problem"), res(), "unclear", "unclear"),
    (res(sev="unknown"), res(sev="unknown", change={"status": "better", "note": ""}), "same", "improving"),  # the model's own follow-up verdict counts
    (res(sev="medium"), res(sev="medium", change={"status": "worse", "note": ""}), "same", "worsening"),
    (res(sev="medium"), res(sev="low", change={"status": "worse", "note": ""}), "same", "mixed"),
])
def test_compare_direction_is_only_chosen_from_real_evidence(prev, now, issue, direction):
    c = journey.compare(prev, now)
    assert c["issue"] == issue and c["direction"] == direction


def test_compare_uncertainty_and_observations_are_qualitative():
    prev = res(unc="high", obs=["Brown spots on lower leaves", "Leaf edges look dry"])
    now = res(unc="some", obs=["Brown spots on the lower leaves", "New yellow patches near the stem"])
    c = journey.compare(prev, now)
    assert c["uncertainty"] == {"previous": "high", "now": "some", "change": "down"}
    o = c["observations"]
    assert o["still_present"] == ["Brown spots on the lower leaves"] and o["new"] == ["New yellow patches near the stem"] and o["not_mentioned_now"] == ["Leaf edges look dry"]
    blob = str(c)
    assert "%" not in blob and "percent" not in blob.lower()


def test_compare_never_invents_a_severity_for_unrated_checks():
    c = journey.compare(res(sev="unknown"), res(sev="medium"))
    assert c["severity"]["change"] == "unknown"


def _db_world(register):
    register("a@example.com")
    register("b@example.com")
    db = SessionLocal()
    ua, ub = db.query(User).filter_by(email="a@example.com").one(), db.query(User).filter_by(email="b@example.com").one()
    fa = Farm(user_id=ua.id, name="A", location="Guntur", planting_date=datetime.now(timezone.utc).date() - timedelta(days=40))
    fb = Farm(user_id=ub.id, name="B", location="Tenali")
    db.add_all([fa, fb])
    db.commit()
    return db, ua, fa, ub, fb


def _login(email):
    from tests.conftest import make_client

    c = make_client()
    assert c.post("/auth/login", json={"email": email, "password": "password123"}).status_code == 200
    return c


def test_journey_is_chronological_with_planting_days_and_diary(register):
    db, ua, fa, ub, fb = _db_world(register)
    a1 = add_check(db, ua, fa, "Possible fungal or bacterial leaf spot", days_ago=10)
    db.add(FarmEvent(user_id=ua.id, farm_id=fa.id, kind="irrigated", event_date=date.today() - timedelta(days=7)))
    a2 = add_check(db, ua, fa, "Possible fungal or bacterial leaf spot", days_ago=2, severity="high")
    db.commit()
    c = _login("a@example.com")
    j = c.get(f"/farms/{fa.id}/journey").json()
    assert j["days_since_planting"] == 40 and j["truncated"] is False
    assert [i["type"] for i in j["items"]] == ["check", "diary", "check"]
    assert [i.get("analysis_id") for i in j["items"] if i["type"] == "check"] == [a1.id, a2.id]
    assert j["items"][1]["kind"] == "irrigated" and j["items"][2]["severity"] == "high"


def test_journey_without_planting_date_invents_no_stage(register):
    db, ua, fa, ub, fb = _db_world(register)
    fb2 = Farm(user_id=ua.id, name="NoDate", location="")
    db.add(fb2)
    db.commit()
    j = _login("a@example.com").get(f"/farms/{fb2.id}/journey").json()
    assert j["planting_date"] is None and j["days_since_planting"] is None and j["items"] == []


def test_journey_hides_a_refined_parent(register):
    db, ua, fa, ub, fb = _db_world(register)
    p = add_check(db, ua, fa, "Not clear yet", days_ago=3)
    ref = add_check(db, ua, fa, "Possible fungal or bacterial leaf spot", days_ago=2)
    ref.parent_id, ref.link_kind = p.id, "refine"
    db.commit()
    j = _login("a@example.com").get(f"/farms/{fa.id}/journey").json()
    assert [i["analysis_id"] for i in j["items"]] == [ref.id]


def test_comparison_uses_the_previous_check_of_the_same_crop_and_farm(register):
    db, ua, fa, ub, fb = _db_world(register)
    add_check(db, ua, fa, "Insect pest damage", crop="Rice", days_ago=9)  # other crop: ignored
    p = add_check(db, ua, fa, "Possible fungal or bacterial leaf spot", days_ago=6, severity="high")
    n = add_check(db, ua, fa, "Possible fungal or bacterial leaf spot", days_ago=1, severity="medium")
    c = _login("a@example.com")
    r = c.get(f"/analyses/{n.id}/comparison").json()
    assert r["previous"]["analysis_id"] == p.id and r["now"]["analysis_id"] == n.id
    assert r["compare"]["issue"] == "same" and r["compare"]["direction"] == "improving" and r["compare"]["severity"]["change"] == "down"
    assert c.get(f"/analyses/{p.id}/comparison").json() is None  # nothing earlier for this crop


def test_comparison_prefers_the_followup_parent_and_skips_a_refinements_own_parent(register):
    db, ua, fa, ub, fb = _db_world(register)
    add_check(db, ua, fa, "Possible fungal or bacterial leaf spot", days_ago=20)
    parent = add_check(db, ua, fa, "Possible fungal or bacterial leaf spot", days_ago=5)
    fu = add_check(db, ua, fa, "Possible fungal or bacterial leaf spot", days_ago=3)
    fu.parent_id, fu.link_kind = parent.id, "followup"
    ref = add_check(db, ua, fa, "Possible fungal or bacterial leaf spot", days_ago=2)
    ref.parent_id, ref.link_kind = fu.id, "refine"
    db.commit()
    c = _login("a@example.com")
    assert c.get(f"/analyses/{fu.id}/comparison").json()["previous"]["analysis_id"] == parent.id
    assert c.get(f"/analyses/{ref.id}/comparison").json()["previous"]["analysis_id"] == parent.id  # not compared with the check it refines


def test_journey_and_comparison_never_leak_across_users(register):
    from tests.conftest import make_client

    db, ua, fa, ub, fb = _db_world(register)
    add_check(db, ua, fa, "Possible fungal or bacterial leaf spot", days_ago=6)
    a_last = add_check(db, ua, fa, "Possible fungal or bacterial leaf spot", days_ago=1)
    b_one = add_check(db, ub, fb, "Secret B issue", days_ago=2)
    a, b = _login("a@example.com"), _login("b@example.com")
    assert b.get(f"/farms/{fa.id}/journey").status_code == 404  # another farmer's farm
    assert b.get(f"/analyses/{a_last.id}/comparison").status_code == 404  # another farmer's check
    assert b.get("/farms/999999/journey").status_code == 404 and b.get("/analyses/999999/comparison").status_code == 404
    assert b.get(f"/analyses/{b_one.id}/comparison").json() is None
    assert "Secret B issue" not in a.get(f"/farms/{fa.id}/journey").text
    assert a.get(f"/analyses/{b_one.id}/comparison").status_code == 404
    assert b.get(f"/farms/{fb.id}/journey").json()["items"][0]["issue"] == "Secret B issue"
    anon = make_client()
    assert anon.get(f"/farms/{fa.id}/journey").status_code == 401 and anon.get(f"/analyses/{a_last.id}/comparison").status_code == 401


# ================= Farm Patterns =================
from app.services import patterns  # noqa: E402

ISSUE = "Possible fungal or bacterial leaf spot"
HUMID = {"location_name": "x", "humidity_pct": 90.0, "past_3d_rain_mm": 14.0, "next_3d_rain_mm": 9.0, "temp_max_c": 30.0}
DRY = {"location_name": "x", "humidity_pct": 40.0, "past_3d_rain_mm": 0.0, "next_3d_rain_mm": 0.0, "temp_max_c": 30.0}


def prow(i, issue=ISSUE, days_ago=1, weather=None, sev="medium"):
    return {"id": i, "crop": "Tomato", "created_at": datetime.now(timezone.utc) - timedelta(days=days_ago), "likely_issue": issue, "severity": sev, "weather": weather}


def test_fewer_than_four_checks_is_not_enough_history():
    out = patterns.build_patterns([prow(1, days_ago=9), prow(2, days_ago=5), prow(3, days_ago=1)], [])
    assert out == {"enough": False, "total": 3, "patterns": []}


def test_enough_checks_but_no_repeats_reports_no_pattern_not_a_made_up_one():
    issues = ["Insect pest damage", ISSUE, "Possible nutrient deficiency", "Wilting from water stress"]
    out = patterns.build_patterns([prow(i, issue=x, days_ago=20 - i * 3) for i, x in enumerate(issues, 1)], [])
    assert out["enough"] is True and out["patterns"] == []


def test_recurring_issue_with_matching_weather_is_a_strong_pattern_with_real_counts():
    rows = [prow(i, days_ago=30 - i * 4, weather=HUMID) for i in range(1, 5)] + [prow(9, "Insect pest damage", days_ago=1)]
    out = patterns.build_patterns(rows, [])
    p = out["patterns"][0]
    assert p["issue"] == ISSUE and p["label"] == "strong" and p["recurring"] is True
    assert p["count"] == 4 and p["window"] == 5  # 4 of the last 5 checks (only 5 exist)
    assert p["environment"] == [{"kind": "humid_wet", "count": 4, "of": 4}]


def test_weather_that_was_not_stored_with_the_checks_is_never_counted():
    rows = [prow(i, days_ago=30 - i * 4, weather=None) for i in range(1, 5)]
    p = patterns.build_patterns(rows, [])["patterns"][0]
    assert p["environment"] == [] and p["label"] == "possible"  # recurring on its own, no environmental claim


def test_a_single_weather_coincidence_is_not_a_pattern():
    rows = [prow(1, days_ago=20, weather=HUMID), prow(2, days_ago=14, weather=DRY), prow(3, days_ago=8, weather=DRY), prow(4, days_ago=2, weather=DRY)]
    p = patterns.build_patterns(rows, [])["patterns"][0]
    assert p["environment"] == []  # 1 humid of 4 is below the two-check minimum


def test_diary_entries_shortly_before_checks_are_counted_only_when_they_coincide_twice():
    today = date.today()
    rows = [prow(i, days_ago=40 - i * 8) for i in range(1, 5)]  # checks 32, 24, 16, 8 days ago
    ev = [{"kind": "irrigated", "event_date": today - timedelta(days=34)}, {"kind": "irrigated", "event_date": today - timedelta(days=26)},
          {"kind": "sprayed", "event_date": today - timedelta(days=17)}]
    p = patterns.build_patterns(rows, ev)["patterns"][0]
    assert p["diary"] == [{"kind": "irrigated", "count": 2, "of": 4}]  # sprayed coincided once only


def test_limited_evidence_label_when_repeated_but_not_recurring_in_the_window():
    rows = [prow(1, days_ago=60), prow(2, days_ago=50), prow(3, "Insect pest damage", days_ago=10), prow(4, "Wilting from water stress", days_ago=8),
            prow(5, "Possible nutrient deficiency", days_ago=6), prow(6, "Possible root rot", days_ago=4), prow(7, "Leaf scorch", days_ago=2),
            prow(8, "Mite damage", days_ago=1)]
    out = patterns.build_patterns(rows, [])
    p = out["patterns"][0]
    assert p["label"] == "limited" and p["recurring"] is False and p["count"] == 2


def test_unclear_checks_are_never_a_pattern():
    rows = [prow(i, "Unable to pinpoint the problem from this description", days_ago=30 - i * 3) for i in range(1, 6)]
    assert patterns.build_patterns(rows, [])["patterns"] == []


def test_patterns_output_has_no_scores_or_causal_wording_fields():
    rows = [prow(i, days_ago=30 - i * 4, weather=HUMID) for i in range(1, 6)]
    blob = str(patterns.build_patterns(rows, [])).lower()
    for banned in ("score", "percent", "%", "predict", "cause", "will "):
        assert banned not in blob


def test_patterns_endpoint_is_owner_scoped_and_uses_stored_weather(register):
    db, ua, fa, ub, fb = _db_world(register)
    for d in (30, 24, 18, 12, 6):
        a = add_check(db, ua, fa, ISSUE, days_ago=d)
        a.weather_json = HUMID
    add_check(db, ub, fb, "Secret B issue", days_ago=1)
    db.commit()
    a_client, b_client = _login("a@example.com"), _login("b@example.com")
    out = a_client.get(f"/farms/{fa.id}/patterns").json()
    assert out["enough"] is True and out["patterns"][0]["label"] == "strong" and out["patterns"][0]["environment"][0]["kind"] == "humid_wet"
    assert b_client.get(f"/farms/{fa.id}/patterns").status_code == 404
    assert b_client.get("/farms/999999/patterns").status_code == 404
    assert "Secret B issue" not in a_client.get(f"/farms/{fa.id}/patterns").text
    assert b_client.get(f"/farms/{fb.id}/patterns").json() == {"farm_id": fb.id, "enough": False, "total": 1, "patterns": []}


def test_context_lines_are_not_compared_as_crop_observations():
    ctx_lines = ["You have 3 earlier analyses for this crop on this farm (not a verified diagnosis).", "Weather context: wetter than usual.", "You reported in your diary: irrigated on 2026-10-05."]
    c = journey.compare(res(obs=["Brown spots on lower leaves", *ctx_lines]), res(obs=["Brown spots on the lower leaves", *ctx_lines]))
    assert c["observations"]["still_present"] == ["Brown spots on the lower leaves"]
    assert c["observations"]["new"] == [] and c["observations"]["not_mentioned_now"] == []
