"""Agentic (LangGraph) investigation: planner, each agent, graph routing, clarification, safety retry, failure
handling, ownership, and the feature flag. The model is a fake with a scripted synthesis step: no network."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from app.database import SessionLocal
from app.models import Analysis, Farm, User
from app.schemas import AnalysisResult
from app.services.agentic import agentic_analyze_check
from app.services.agents import crop_analysis, environment, farm_memory, investigation, knowledge, safety_agent
from app.services.agents.toolbox import AgentToolbox
from app.services.ai import AIServiceError, AnalysisContext
from app.services.ai.base import DiaryItem, HistoryItem, ImageInput, PreviousCheck, WeatherContext
from app.services.ai.demo_provider import DemoAIProvider
from app.services.graph.state import CropAnalysis, KnowledgeEvidence
from app.services.rag.models import Chunk
from app.services.rag.retrieval import Index

SPOTS = "brown spots on the lower leaves"
GOOD = dict(verdict="Most likely a fungal leaf spot, not yet confirmed.", what_may_be_happening="The spots fit a fungal or bacterial leaf spot; the cause is not confirmed.",
            evidence_for=["Brown spots on lower leaves"], evidence_against=[], unknowns=["How many plants are affected"],
            what_to_verify=["Check whether nearby plants show the same spots"], what_to_monitor=["Watch whether new leaves are affected"],
            when_to_seek_help="Contact your agricultural officer if it spreads quickly.", cited_source_ids=[])


class Prov:
    """A scripted provider: analyze() is the real demo answer; synthesize() returns the next scripted decision."""

    name = "fake"

    def __init__(self, decisions=None, fail_synth=False, quality=None, synth=True):
        self.decisions, self.fail_synth, self.quality = list(decisions or [dict(GOOD)]), fail_synth, quality
        self.analyze_calls = self.synth_calls = 0
        self.prompts: list[str] = []

    def analyze(self, ctx):
        self.analyze_calls += 1
        out = DemoAIProvider().analyze(ctx)
        if self.quality:
            out["image_quality"] = self.quality
        return out

    def synthesize(self, prompt, schema, language):
        self.synth_calls += 1
        self.prompts.append(prompt)
        if self.fail_synth:
            raise AIServiceError("down")
        d = self.decisions[min(self.synth_calls - 1, len(self.decisions) - 1)]
        return json.loads(json.dumps(d))


@pytest.fixture()
def world(register):
    """Two farmers with farms; A has stored checks. Returns (db, userA, farmA, userB, farmB)."""
    register("a@example.com")
    register("b@example.com")
    db = SessionLocal()
    ua, ub = db.query(User).filter_by(email="a@example.com").one(), db.query(User).filter_by(email="b@example.com").one()
    fa = Farm(user_id=ua.id, name="A farm", location="Guntur", soil_type="Red soil", primary_crop="Tomato")
    fb = Farm(user_id=ub.id, name="B farm", location="Tenali", soil_type="")
    db.add_all([fa, fb])
    db.commit()
    yield db, ua, fa, ub, fb
    db.close()


def add_check(db, user, farm, issue, crop="Tomato", days_ago=1, severity="medium"):
    r = {"likely_issue": issue, "explanation": "x", "recommended_actions": ["a"], "precautions": ["p"], "uncertainty": "u",
         "severity": severity, "uncertainty_level": "some", "image_quality": "good"}
    a = Analysis(user_id=user.id, farm_id=farm.id, crop=crop, symptoms="spots", language="en", input_type="text", result_json=r,
                 created_at=datetime.now(timezone.utc) - timedelta(days=days_ago))
    db.add(a)
    db.commit()
    return a


def ctx_for(farm, symptoms=SPOTS, **kw):
    return AnalysisContext(crop="Tomato", symptoms=symptoms, farm_location=farm.location, soil_type=farm.soil_type, **kw)


def run(world_, prov=None, index=None, ctx=None, **kw):
    db, ua, fa, *_ = world_
    ctx = ctx or ctx_for(fa)
    return agentic_analyze_check(ctx, AgentToolbox(db, ua, fa, ctx), prov or Prov(), index if index is not None else Index([]), farm_id=fa.id, **kw)


def steps(r):
    return [(s.agent, s.status) for s in r.agent_steps]


def chunk(i, text, crop="tomato", url="https://example.ac.in/doc"):
    return Chunk(id=f"c{i}", source_url=url, title="Tomato leaf spot guide", institution="Test University", crop=crop, topic="leaf spot",
                 content_hash=f"h{i}", text=text)


KB = Index([chunk(1, "Early blight causes brown spots with concentric rings on the lower tomato leaves, favoured by warm humid weather. " * 3)])


# ============================ Investigation (planner) ============================
def test_planner_clarifies_when_there_is_no_evidence_or_it_is_vague():
    for text in ("", "My crop is not good."):
        p = investigation.plan(AnalysisContext(crop="Tomato", symptoms=text), has_history=False, knowledge_available=True)
        assert p.clarify and p.nodes == [] and p.clarify.question and len(p.clarify.options) >= 2
    assert investigation.plan(AnalysisContext(crop="Tomato", symptoms=""), has_history=False, knowledge_available=True).clarify.reason == "no_evidence"


def test_planner_never_asks_a_follow_up_or_more_than_twice():
    vague = AnalysisContext(crop="Tomato", symptoms="not good")
    assert investigation.plan(vague, has_history=False, knowledge_available=False, clarification_round=2).clarify is None
    fu = AnalysisContext(crop="Tomato", symptoms="not good", previous=PreviousCheck(date="2026-01-01", likely_issue="x"))
    assert investigation.plan(fu, has_history=False, knowledge_available=False).clarify is None


def test_planner_routes_by_evidence_and_records_skips():
    ctx = AnalysisContext(crop="Tomato", symptoms=SPOTS)
    p = investigation.plan(ctx, has_history=False, knowledge_available=False)
    assert p.nodes == ["crop_analysis"] and p.skipped == {"farm_memory": "no_history", "environment": "no_weather", "knowledge": "no_knowledge_base"}
    ctx.weather = WeatherContext(location_name="Guntur", humidity_pct=90)
    p = investigation.plan(ctx, has_history=True, knowledge_available=True)
    assert p.nodes == ["crop_analysis", "farm_memory", "environment", "knowledge"] and not p.skipped


# ============================ graph: scenarios A-G ============================
def test_scenario_A_clear_evidence_runs_the_specialists_then_decision_and_safety(world):
    db, ua, fa, *_ = world
    add_check(db, ua, fa, "Possible fungal or bacterial leaf spot")
    ctx = ctx_for(fa, weather=WeatherContext(location_name="Guntur", humidity_pct=90, past_3d_rain_mm=12, temp_max_c=30),
                  history=[HistoryItem(date="2026-09-01", crop="Tomato", likely_issue="Possible fungal or bacterial leaf spot")])
    prov = Prov([{**GOOD, "cited_source_ids": ["c1"]}])
    r = run(world, prov, KB, ctx)
    assert [a for a, _ in steps(r)] == ["investigation", "crop_analysis", "farm_memory", "environment", "knowledge", "decision_support", "safety"]
    assert r.verdict.startswith("Most likely") and "not confirmed" in r.explanation
    assert [s.url for s in r.sources] == ["https://example.ac.in/doc"]
    assert prov.analyze_calls == 1 and prov.synth_calls == 1  # exactly two model calls


def test_scenario_B_vague_question_asks_instead_of_inventing_a_diagnosis(world):
    prov = Prov()
    r = run(world, prov, ctx=ctx_for(world[2], symptoms="My crop is not good."))
    assert prov.analyze_calls == 0 and prov.synth_calls == 0
    assert r.quick_questions and "Not enough" in r.verdict and r.uncertainty_level == "high" and r.severity == "unknown"
    assert ("investigation", "ok") in steps(r) and any(s.note == "clarification:too_vague" for s in r.agent_steps)
    assert not r.sources


def test_clarification_is_in_telugu_for_a_telugu_farmer(world):
    r = run(world, ctx=ctx_for(world[2], symptoms="బాగాలేదు", language="te"))
    assert any("ఀ" <= ch <= "౿" for ch in r.verdict) and r.quick_questions


def test_scenario_C_recurring_problem_is_recognised_by_farm_memory(world):
    db, ua, fa, *_ = world
    for d in (3, 6, 10, 15, 20, 25):  # 6 checks on distinct days: enough history for a recurring pattern
        add_check(db, ua, fa, "Possible fungal or bacterial leaf spot", days_ago=d)
    ca = CropAnalysis(candidate_issues=["Possible fungal or bacterial leaf spot"])
    ctx = ctx_for(fa)
    m = farm_memory.run(AgentToolbox(db, ua, fa, ctx), "Tomato", ca)
    assert len(m.historical_matches) == 6 and m.recurring_patterns and m.history_confidence > 0
    assert "recurring" in m.recurring_patterns[0]


def test_scenario_D_new_problem_has_no_supporting_history_and_nothing_is_invented(world):
    db, ua, fa, *_ = world
    add_check(db, ua, fa, "Insect pest damage")
    m = farm_memory.run(AgentToolbox(db, ua, fa, ctx_for(fa)), "Tomato", CropAnalysis(candidate_issues=["Possible fungal or bacterial leaf spot"]))
    assert m.historical_matches == [] and m.supporting_history == [] and m.recurring_patterns == []
    empty = farm_memory.run(AgentToolbox(db, ua, fa, ctx_for(fa)), "Chilli", CropAnalysis(candidate_issues=["x"]))
    assert empty.checks_on_farm == 0 and empty.history_confidence == 0.0 and not empty.historical_matches


def test_scenario_E_poor_image_with_nothing_written_asks_for_a_better_photo(world):
    ctx = ctx_for(world[2], symptoms="", image=ImageInput(b"x", "image/jpeg"))
    r = run(world, Prov(quality="poor"), ctx=ctx)
    assert any(s.note == "clarification:poor_image" for s in r.agent_steps) and r.quick_questions
    ctx2 = ctx_for(world[2], image=ImageInput(b"x", "image/jpeg"))  # same poor photo but the farmer described spots
    r2 = run(world, Prov(quality="poor"), ctx=ctx2)
    assert not any("clarification" in s.note for s in r2.agent_steps) and r2.verdict


def test_scenario_F_weather_failure_does_not_stop_the_investigation(world, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("weather exploded")

    monkeypatch.setattr(environment, "run", boom)
    ctx = ctx_for(world[2], weather=WeatherContext(location_name="Guntur", humidity_pct=90))
    r = run(world, ctx=ctx)
    assert ("environment", "failed") in steps(r) and ("safety", "ok") in steps(r) and r.verdict
    # and with no weather at all: skipped, never faked
    r2 = run(world)
    assert ("environment", "skipped") in steps(r2)


def test_scenario_G_unsafe_decision_is_rejected_then_corrected_within_the_retry_bound(world):
    bad = {**GOOD, "what_to_verify": ["Spray 2 ml per litre of water on all plants"]}
    prov = Prov([bad, GOOD])
    r = run(world, prov)
    assert prov.synth_calls == 2 and ("decision_support", "retry") in steps(r) and ("safety", "retry") in steps(r)
    assert "ml per litre" not in json.dumps(r.model_dump()).lower() and r.verdict.startswith("Most likely")
    assert "Fix exactly this" in prov.prompts[1]


def test_unsafe_forever_falls_back_to_the_verified_crop_analysis_after_bounded_retries(world):
    bad = {**GOOD, "what_to_verify": ["Spray 2 ml per litre of water on all plants"]}
    prov = Prov([bad])
    r = run(world, prov)
    assert prov.synth_calls <= 3 and ("safety", "ok") in steps(r) and any(s.note == "fallback_to_crop_analysis" for s in r.agent_steps)
    assert "ml per litre" not in json.dumps(r.model_dump()).lower()


# ============================ failure handling & fail-closed ============================
def test_safety_agent_failure_fails_closed(world, monkeypatch):
    monkeypatch.setattr(safety_agent, "check", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("safety down")))
    with pytest.raises(AIServiceError) as e:
        run(world)
    assert e.value.code == "ai_unsafe_output"


def test_crop_analysis_failure_is_the_same_user_safe_error_as_legacy(world, monkeypatch):
    monkeypatch.setattr(crop_analysis, "run", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(AIServiceError):
        run(world)


def test_synthesis_failure_keeps_the_verified_crop_analysis(world):
    r = run(world, Prov(fail_synth=True))
    assert ("decision_support", "failed") in steps(r) and r.likely_issue and ("safety", "ok") in steps(r)


def test_provider_without_synthesis_still_answers(world):
    class NoSynth:
        name = "nosynth"

        def analyze(self, ctx):
            return DemoAIProvider().analyze(ctx)

    r = run(world, NoSynth())
    assert any(s.note == "no_synthesis_provider" for s in r.agent_steps) and r.likely_issue


def test_retrieval_failure_is_reported_and_the_answer_continues(world, monkeypatch):
    monkeypatch.setattr(knowledge, "run", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("index broke")))
    r = run(world, index=KB)
    assert ("knowledge", "failed") in steps(r) and not r.sources and r.verdict


# ============================ RAG sources are never fabricated ============================
def test_a_cited_id_that_was_not_retrieved_is_dropped_and_no_sources_are_shown(world):
    r = run(world, Prov([{**GOOD, "cited_source_ids": ["made-up-id"]}]), KB)
    assert r.sources == []


def test_sources_appear_only_when_retrieved_and_cited(world):
    assert run(world, Prov([{**GOOD, "cited_source_ids": ["c1"]}]), Index([])).sources == []  # empty knowledge base
    r = run(world, Prov([{**GOOD, "cited_source_ids": ["c1"]}]), KB)
    assert len(r.sources) == 1 and r.sources[0].institution == "Test University"
    assert run(world, Prov([GOOD]), KB).sources == []  # retrieved but not relied on: not shown


def test_safety_rejects_a_source_that_was_not_retrieved(world):
    base = AnalysisResult.model_validate(DemoAIProvider().analyze(ctx_for(world[2])))
    from app.schemas import SourceRef
    cand = base.model_copy(update={"sources": [SourceRef(title="t", institution="i", url="https://fake.example/x")]})
    v, ok = safety_agent.check(cand, base, ctx_for(world[2]), set())
    assert not v.safe and "source_not_retrieved" in v.violations and ok is None


def test_safety_rejects_certainty_lowered_uncertainty_and_changed_issue(world):
    ctx = ctx_for(world[2])
    base = AnalysisResult.model_validate(DemoAIProvider().analyze(ctx))
    v, _ = safety_agent.check(base.model_copy(update={"verdict": "This is definitely early blight."}), base, ctx, set())
    assert "unsupported_certainty" in v.violations
    v, _ = safety_agent.check(base.model_copy(update={"uncertainty_level": "low"}), base, ctx, set())
    assert "uncertainty_lowered" in v.violations
    v, _ = safety_agent.check(base.model_copy(update={"likely_issue": "Something else"}), base, ctx, set())
    assert "issue_or_severity_changed" in v.violations
    v, ok = safety_agent.check(base, base, ctx, set())
    assert v.safe and ok is not None


# ============================ Environment agent wording ============================
def test_environment_is_worded_as_consistent_with_never_as_cause():
    w = WeatherContext(location_name="Guntur", humidity_pct=92, past_3d_rain_mm=15, temp_max_c=30)
    e = environment.run(w, CropAnalysis(candidate_issues=["Possible fungal leaf spot"]))
    assert e.weather_relevance == "high" and e.supporting_signals
    text = " ".join(e.supporting_signals).lower()
    assert "consistent with" in text and "caused" not in text and e.environmental_uncertainties


def test_environment_hot_dry_counts_against_a_moisture_explanation_and_no_weather_is_unknown():
    w = WeatherContext(location_name="x", temp_max_c=38, past_3d_rain_mm=0, next_3d_rain_mm=0, humidity_pct=30)
    e = environment.run(w, CropAnalysis(candidate_issues=["Possible fungal leaf spot"]))
    assert e.contradicting_signals
    assert environment.run(None, CropAnalysis()).weather_relevance == "unknown"


# ============================ Ownership: tools cannot reach another farmer's data ============================
def test_toolbox_never_returns_another_farmers_data(world):
    db, ua, fa, ub, fb = world
    add_check(db, ua, fa, "Possible fungal or bacterial leaf spot")
    add_check(db, ub, fb, "Secret B issue")
    mine = AgentToolbox(db, ua, fa, ctx_for(fa))
    assert [r["likely_issue"] for r in mine.recent_checks()] == ["Possible fungal or bacterial leaf spot"]
    # even a forged pairing (A's identity with B's farm) returns nothing of B's
    forged = AgentToolbox(db, ua, fb, ctx_for(fb))
    assert forged.recent_checks() == [] and forged.farm_insights()["total"] == 0
    assert "Secret B issue" not in json.dumps(mine.farm_insights(), default=str) + json.dumps(mine.proactive(), default=str)


# ============================ Feature flag (API level) ============================
def _post(c, farm_id, symptoms=SPOTS):
    return c.post("/analyses", data={"crop": "Tomato", "symptoms": symptoms, "language": "en", "farm_id": str(farm_id)})


def test_flag_off_by_default_uses_the_legacy_pipeline(register):
    c = register()
    fid = c.post("/farms", json={"name": "F", "location": "", "soil_type": ""}).json()["id"]
    r = _post(c, fid)
    assert r.status_code == 201 and r.json()["result"]["agent_steps"] == []


def test_flag_on_runs_the_investigation_and_a_vague_question_is_answered_with_a_question(register, monkeypatch):
    monkeypatch.setenv("AGENTIC_ANALYSIS_ENABLED", "true")
    c = register()
    fid = c.post("/farms", json={"name": "F", "location": "", "soil_type": ""}).json()["id"]
    r = _post(c, fid)
    assert r.status_code == 201
    res = r.json()["result"]
    ran = [s["agent"] for s in res["agent_steps"] if s["status"] != "skipped"]
    assert ran[:2] == ["investigation", "crop_analysis"] and ran[-1] == "safety"
    v = _post(c, fid, "not good")
    vr = v.json()["result"]
    assert vr["quick_questions"] and "Not enough" in vr["verdict"]
    # the existing refine endpoint takes the farmer's tap-answer on that question
    q = vr["quick_questions"][0]
    ref = c.post(f"/analyses/{v.json()['id']}/refine", json={"answers": [{"question": q["question"], "answer": q["options"][0]}]})
    assert ref.status_code in (200, 201), ref.text


def test_two_cited_passages_of_one_document_are_one_source(world):
    kb = Index([chunk(1, "Early blight causes brown spots on lower tomato leaves in warm humid weather. " * 4),
                chunk(2, "Concentric rings are typical of early blight on tomato leaves and stems. " * 4)])
    r = run(world, Prov([{**GOOD, "cited_source_ids": ["c1", "c2"]}]), kb)
    assert len(r.sources) == 1


def test_generic_page_titles_are_replaced_by_crop_and_topic():
    assert knowledge.display_title("ORGANIC FARMING :: Home", "tomato", "tomato diseases, symptoms", "https://x.ac.in/a") == "Tomato: tomato diseases, symptoms"
    assert knowledge.display_title("https://x.ac.in/pdf/9.pdf", "", "horticultural crop diseases", "https://x.ac.in/pdf/9.pdf") == "General: horticultural crop diseases"
    assert knowledge.display_title("Early blight of tomato: symptoms", "tomato", "x", "u") == "Early blight of tomato: symptoms"


def test_the_decision_prompt_tells_the_model_not_to_use_internal_names(world):
    prov = Prov()
    run(world, prov)
    assert "never 'farm memory'" in prov.prompts[0]
