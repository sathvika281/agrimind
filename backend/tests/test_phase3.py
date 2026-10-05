import json

import httpx
import pytest

from app.database import SessionLocal
from app.models import Analysis
from app.schemas import AnalysisResult
from app.services import weather
from app.services.ai import AIServiceError, AnalysisContext, HistoryItem, ImageInput, analyze, service
from app.services.ai.demo_provider import DemoAIProvider
from app.services.ai.evidence import build_evidence
from app.services.ai.gemini_provider import GeminiProvider, build_prompt
from app.services.ai.safety import IMAGE_GUIDANCE, STANDARD_QUESTIONS, SafetyError, verify
from app.services.ai.service import SAFETY_FAILURE
from tests.test_phase2 import PNG, WX, FakeWeather, _farm, _post, uploads_count

LONG = "The lower leaves of my plants are turning yellow and some have brown spots"


def mk(**over) -> dict:
    base = {
        "likely_issue": "Possible nutrient or watering problem",
        "explanation": "Yellow lower leaves may point to a water or nutrient problem.",
        "observations": ["Lower leaves are yellow (you reported)"],
        "evidence_for": ["Yellowing starts on older leaves"],
        "evidence_against": ["No spots were described"],
        "unknowns": ["How widespread it is across the field"],
        "possible_alternatives": [
            {"possibility": "Water stress", "how_to_tell": "Check soil moisture a hand-depth down."},
            {"possibility": "Insect damage", "how_to_tell": "Look under the leaves."},
        ],
        "immediate_actions": ["Inspect more plants", "Check soil moisture"],
        "recommended_actions": ["Inspect more plants", "Check soil moisture"],
        "monitoring_steps": ["Watch whether new leaves are affected"],
        "precautions": ["Wear gloves if handling any inputs"],
        "follow_up_questions": [],
        "severity": "low",
        "when_to_seek_help": "If it spreads quickly or the cause stays unclear.",
        "uncertainty_level": "some",
        "uncertainty": "The exact cause is not confirmed.",
        "image_quality": "not_provided",
        "image_guidance": "",
    }
    base.update(over)
    return base


class Scripted:
    name = "scripted"

    def __init__(self, payload):
        self.payload = payload

    def analyze(self, ctx):
        return self.payload


def run(payload, **ctx_kw):
    ctx_kw.setdefault("crop", "Tomato")
    ctx_kw.setdefault("symptoms", LONG)
    return analyze(AnalysisContext(**ctx_kw), Scripted(payload))


IMG = ImageInput(PNG, "image/png")


# ======================= reasoning contract: nine scenarios =======================
SCENARIOS = {
    "healthy": (
        dict(symptoms="My tomato plants look healthy but I want to check there is nothing wrong"),
        mk(likely_issue="No clear problem seen", severity="low", uncertainty_level="low",
           possible_alternatives=[], evidence_for=["Plants are described as healthy"], evidence_against=[],
           explanation="From what you describe, nothing looks wrong at the moment."),
    ),
    "yellowing": (dict(), mk()),
    "leaf_spots_humid": (
        dict(symptoms="Round brown spots on the leaves after several rainy days", weather=WX),
        mk(likely_issue="Possible fungal leaf spot",
           explanation="Spots after wet weather can be consistent with a leaf-spot disease. These conditions may increase the likelihood of fungal problems.",
           evidence_for=["Round brown spots", "Recent rain and high humidity"]),
    ),
    "wilting_dry": (
        dict(symptoms="Plants wilt in the afternoon and the soil is very dry and cracked"),
        mk(likely_issue="Possible water stress", evidence_for=["Dry, cracked soil", "Wilting in the afternoon"],
           evidence_against=["No sign of root rot was described"]),
    ),
    "pest_holes": (
        dict(symptoms="There are small round holes in the leaves and I see tiny green insects"),
        mk(likely_issue="Possible insect pest damage", observations=["Small round holes", "Tiny green insects (you reported)"]),
    ),
    "ambiguous": (
        dict(symptoms="Something looks wrong with the plants lately but I am not sure what"),
        mk(likely_issue="Cannot tell from the information given", uncertainty_level="high",
           follow_up_questions=["Which part of the plant looks wrong?", "How long has it been like this?"]),
    ),
    "poor_image": (
        dict(symptoms="", image=IMG),
        mk(likely_issue="Cannot tell from the photo", image_quality="poor", uncertainty_level="low",
           observations=["The photo is too dark to see the leaf"]),
    ),
    "image_vs_symptoms_conflict": (
        dict(symptoms="Yellow patches on tomato leaves", image=IMG),
        mk(likely_issue="Photo and description may not match", image_quality="limited",
           observations=["The photo seems to show a different plant than described"],
           evidence_against=["The photo does not clearly match the description"]),
    ),
    "insufficient_evidence": (dict(symptoms="bad"), mk(uncertainty_level="low", follow_up_questions=[])),
}


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_scenario_contract(name):
    ctx_kw, payload = SCENARIOS[name]
    out = run(payload, **ctx_kw)
    assert isinstance(out, AnalysisResult)
    assert out.recommended_actions and out.uncertainty and out.likely_issue
    assert out.uncertainty_level in ("low", "some", "high")
    assert len(out.possible_alternatives) <= 3 and len(out.follow_up_questions) <= 4
    assert len(out.evidence_for) <= 5 and len(out.unknowns) <= 5


def test_healthy_keeps_low_uncertainty_when_evidence_is_adequate():
    ctx_kw, payload = SCENARIOS["healthy"]
    assert run(payload, **ctx_kw).uncertainty_level == "low"


def test_poor_image_gets_guidance_and_high_uncertainty():
    ctx_kw, payload = SCENARIOS["poor_image"]
    out = run(payload, **ctx_kw)
    assert out.image_quality == "poor" and out.image_guidance == IMAGE_GUIDANCE
    assert out.uncertainty_level == "high" and out.follow_up_questions == STANDARD_QUESTIONS[:3]


def test_conflicting_image_gets_guidance():
    ctx_kw, payload = SCENARIOS["image_vs_symptoms_conflict"]
    out = run(payload, **ctx_kw)
    assert out.image_guidance and out.evidence_against


def test_insufficient_evidence_raises_uncertainty_and_adds_questions():
    ctx_kw, payload = SCENARIOS["insufficient_evidence"]
    out = run(payload, **ctx_kw)
    assert out.uncertainty_level == "some" and len(out.follow_up_questions) == 3


def test_alternatives_evidence_and_questions_validate_and_trim():
    p = mk(
        possible_alternatives=[{"possibility": f"P{i}", "how_to_tell": "x"} for i in range(6)] + ["plain string"],
        evidence_for=[f"e{i}" for i in range(9)],
        unknowns=[f"u{i}" for i in range(9)],
        follow_up_questions=[f"q{i}?" for i in range(9)],
    )
    out = run(p)
    assert len(out.possible_alternatives) == 3 and len(out.evidence_for) == 5
    assert len(out.unknowns) == 5 and len(out.follow_up_questions) == 4
    out2 = AnalysisResult.model_validate(mk(possible_alternatives=["Just a name"]))
    assert out2.possible_alternatives[0].possibility == "Just a name" and out2.possible_alternatives[0].how_to_tell == ""


def test_new_fields_are_optional_and_enums_are_coerced():
    r = AnalysisResult.model_validate(
        {"likely_issue": "x", "explanation": "e", "recommended_actions": ["a"], "precautions": [], "uncertainty": "u"}
    )
    assert r.possible_alternatives == [] and r.uncertainty_level == "unknown" and r.image_quality == "not_provided"
    r = AnalysisResult.model_validate({**mk(), "severity": "catastrophic", "uncertainty_level": "99%", "image_quality": "meh",
                                       "evidence_for": None, "follow_up_questions": None})
    assert r.severity == "unknown" and r.uncertainty_level == "unknown" and r.image_quality == "not_provided"
    assert r.evidence_for == [] and r.follow_up_questions == []


def test_recommended_actions_filled_from_phase3_lists():
    out = run(mk(recommended_actions=[], immediate_actions=["Do A"], monitoring_steps=["Watch B"]))
    assert out.recommended_actions == ["Do A", "Watch B"]


def test_demo_provider_emits_phase3_fields_and_passes_verification():
    for crop, sym in [("Tomato", "yellow leaves"), ("Chilli", "holes caterpillar"), ("Rice", "brown spots and wilting"),
                      ("Quinoa", "something odd"), ("Rice", "")]:
        out = analyze(AnalysisContext(crop=crop, symptoms=sym or "x"), DemoAIProvider())
        assert out.immediate_actions and out.monitoring_steps and out.unknowns
        assert out.uncertainty_level in ("some", "high") and len(out.possible_alternatives) <= 3
        assert out.severity == "unknown"


# ======================= safety: hard failures =======================
def bad(**over):
    return mk(**over)


UNSAFE = {
    "dosage_ml_per_litre": dict(immediate_actions=["Spray 10 ml of fungicide per litre of water."]),
    "dosage_per_acre": dict(monitoring_steps=["Apply 2 kg per acre every week."]),
    "dosage_grams": dict(explanation="Mix mancozeb at 2 g/L and spray weekly."),
    "concentration_percent": dict(precautions=["Use a 0.5% solution of copper."]),
    "concentration_ppm": dict(precautions=["Keep the spray at 200 ppm."]),
    "dilution_ratio": dict(explanation="Dilute 1:100 with water before spraying."),
    "prohibition_without_safeguard": dict(precautions=["Never use more than 10 ml per litre."]),
    "guaranteed_definitely": dict(likely_issue="This is definitely early blight"),
    "guaranteed_100": dict(explanation="This is 100% a fungal infection."),
    "guaranteed_cure": dict(explanation="The treatment will cure the plants."),
    "guaranteed_outcome": dict(explanation="Your yield is guaranteed to recover."),
    "lab_confirmed": dict(observations=["Laboratory confirmed fungal infection"]),
    "lab_results_show": dict(evidence_for=["Test results show a fungal infection"]),
    "weather_caused": dict(explanation="The heavy rain caused the leaf spots."),
    "weather_due_to": dict(explanation="The problem is due to the recent rainfall."),
    "chem_directive_while_uncertain": dict(immediate_actions=["Spray a fungicide on all plants today."]),
    "image_claim_without_image": dict(observations=["The photo shows brown circular spots"]),
    "weather_numbers_without_weather": dict(observations=["Rainfall of 20 mm recently"]),
    "no_actions": dict(recommended_actions=[], immediate_actions=[], monitoring_steps=[]),
}


@pytest.mark.parametrize("case", list(UNSAFE))
def test_unsafe_output_is_rejected(case):
    with pytest.raises(AIServiceError):
        run(bad(**UNSAFE[case]))


def test_rejection_message_does_not_leak_details():
    with pytest.raises(AIServiceError) as e:
        run(bad(**UNSAFE["dosage_ml_per_litre"]))
    assert str(e.value) == SAFETY_FAILURE
    assert "ml" not in str(e.value) and "dosage" not in str(e.value).lower()


def test_verify_raises_codes_for_logs():
    r = AnalysisResult.model_validate(bad(**UNSAFE["guaranteed_definitely"]))
    with pytest.raises(SafetyError) as e:
        verify(r, AnalysisContext(crop="x", symptoms=LONG))
    assert e.value.code == "guaranteed_claim"


# ======================= safety: legitimate language must pass =======================
ALLOWED = {
    "user_example_disclaimer": dict(
        precautions=["Do not use a 10 ml/L dosage unless that exact amount is provided on the product label."]
    ),
    "never_with_label": dict(precautions=["Never mix chemicals at 5 ml per litre unless your agricultural officer confirms it."]),
    "negated_guarantee": dict(uncertainty="AgriMind does not guarantee a diagnosis, and this is not a guaranteed answer."),
    "cannot_say_definitely": dict(explanation="I cannot say this definitely from the information given."),
    "hedged_weather": dict(explanation="These wet conditions may increase the likelihood of fungal problems."),
    "weather_hedged_cause": dict(explanation="Heavy rain can cause some leaf diseases, but that is not confirmed here."),
    "not_lab_confirmed": dict(observations=["This is not laboratory confirmed."]),
    "irrigation_volume_is_not_a_dose": dict(immediate_actions=["Water each plant with 2 litres of water in the morning."]),
    "chem_with_safeguard": dict(immediate_actions=["Ask your officer which fungicide to use, and follow the product label."]),
    "chem_prohibition": dict(immediate_actions=["Do not spray any fungicide until the cause is confirmed."]),
    "cm_and_days_are_fine": dict(immediate_actions=["Remove the top 5 cm of affected growth and check again in 3 days."]),
}


@pytest.mark.parametrize("case", list(ALLOWED))
def test_legitimate_language_is_allowed(case):
    out = run(mk(**ALLOWED[case]))
    assert isinstance(out, AnalysisResult)


def test_image_and_weather_observations_allowed_when_inputs_exist():
    out = run(mk(observations=["The photo shows brown circular spots", "Rainfall of 22 mm in the last 3 days"],
                 image_quality="good"), image=IMG, weather=WX)
    assert out.observations and out.image_quality == "good"


def test_chem_directive_allowed_only_when_uncertainty_is_low():
    p = mk(uncertainty_level="low", immediate_actions=["Spray a fungicide on all plants today."],
           recommended_actions=["Spray a fungicide on all plants today."])
    # evidence adequate + model says low: not blocked by the uncertainty rule (dosage rules still apply)
    assert run(p).uncertainty_level == "low"
    with pytest.raises(AIServiceError):
        run({**p, "uncertainty_level": "some"})


# ======================= verification repairs =======================
def test_severity_high_is_capped_without_escalation_signals():
    assert run(mk(severity="high")).severity == "medium"


def test_severity_high_kept_when_inputs_show_escalation():
    out = run(mk(severity="high"), symptoms="Most of the plants are dying and it is spreading fast")
    assert out.severity == "high"


def test_unknown_uncertainty_level_is_derived_from_evidence():
    assert run(mk(uncertainty_level="unknown")).uncertainty_level == "some"
    assert run(mk(uncertainty_level="unknown"), symptoms="bad").uncertainty_level == "high"  # weak evidence
    assert run(mk(uncertainty_level="unknown"), symptoms="", image=IMG, ).uncertainty_level == "some"


def test_image_fields_cleared_when_no_image_was_provided():
    out = run(mk(image_quality="good", image_guidance="Nice photo"))
    assert out.image_quality == "not_provided" and out.image_guidance == ""


def test_repairs_never_invent_agronomy_beyond_fixed_texts():
    out = run(mk(follow_up_questions=[]), symptoms="bad")
    assert set(out.follow_up_questions) <= set(STANDARD_QUESTIONS)
    assert out.likely_issue == mk()["likely_issue"] and out.explanation == mk()["explanation"]


# ======================= evidence ledger / prompt =======================
def test_evidence_ledger_separates_observed_and_unknown():
    ev = build_evidence(AnalysisContext(crop="Rice", symptoms=LONG, farm_location="Guntur", soil_type="Black soil"))
    obs, unk = " | ".join(ev.observed), " | ".join(ev.unknown)
    assert "Rice" in obs and "Guntur" in obs and "Black soil" in obs and "not a lab test" in obs
    assert "Photo: none" in unk and "Weather context: not available" in unk
    assert "pH" in unk and "laboratory" in unk
    assert not ev.weak
    assert build_evidence(AnalysisContext(crop="Rice", symptoms="bad")).weak


def test_gemini_prompt_carries_context_ledger_and_history():
    ctx = AnalysisContext(
        crop="Rice", symptoms=LONG, farm_location="Guntur", soil_type="Black soil", weather=WX,
        history=[HistoryItem(date="2026-09-01", crop="Rice", likely_issue="Possible leaf spot", severity="low", symptoms="spots")],
    )
    text = build_prompt(ctx)
    for needle in ("OBSERVED", "UNKNOWN", "Guntur", "Black soil", "22.5", "NOT verified diagnoses", "Possible leaf spot"):
        assert needle in text


def test_gemini_still_makes_exactly_one_call_and_validates_phase3_output():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps(mk())}]}}]})

    p = GeminiProvider(api_key="k", http=httpx.Client(transport=httpx.MockTransport(handler)))
    out = analyze(AnalysisContext(crop="Rice", symptoms=LONG), p)
    assert len(calls) == 1 and out.possible_alternatives and out.unknowns


def test_gemini_unsafe_output_is_rejected_after_single_call():
    calls = []

    def handler(request):
        calls.append(1)
        payload = mk(**UNSAFE["dosage_ml_per_litre"])
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps(payload)}]}}]})

    p = GeminiProvider(api_key="k", http=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(AIServiceError):
        analyze(AnalysisContext(crop="Rice", symptoms=LONG), p)
    assert len(calls) == 1  # no retry / second call


# ======================= API: storage, cleanup, context, history, ownership =======================
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


def test_unsafe_model_output_is_not_stored_and_image_is_cleaned_up(register, monkeypatch):
    monkeypatch.setattr(service, "get_provider", lambda: Scripted(mk(**UNSAFE["guaranteed_definitely"])))
    c = register()
    r = _post(c, _farm(c), image=PNG)
    assert r.status_code == 503 and r.json()["detail"] == SAFETY_FAILURE
    assert "Traceback" not in r.text and "definitely" not in r.text
    assert c.get("/analyses").json() == []
    assert uploads_count() == 0  # image never persisted for a rejected analysis


def test_valid_phase3_result_is_stored_and_returned(register, monkeypatch):
    monkeypatch.setattr(service, "get_provider", lambda: Scripted(mk()))
    c = register()
    d = _post(c, _farm(c)).json()
    assert d["result"]["possible_alternatives"][0]["possibility"] == "Water stress"
    assert d["result"]["uncertainty_level"] == "some" and d["result"]["monitoring_steps"]
    again = c.get(f"/analyses/{d['id']}").json()
    assert again["result"] == d["result"]


def test_soil_and_location_reach_the_provider(register, capture):
    c = register()
    fid = c.post("/farms", json={"name": "F", "location": "Guntur", "soil_type": "Black soil"}).json()["id"]
    assert _post(c, fid).status_code == 201
    assert capture.ctx.soil_type == "Black soil" and capture.ctx.farm_location == "Guntur"


def test_weather_reaches_provider_when_available_and_is_optional(register, capture, monkeypatch):
    c = register()
    fid = _farm(c)
    monkeypatch.setattr(weather, "client", FakeWeather(wx=WX))
    assert _post(c, fid).status_code == 201 and capture.ctx.weather.humidity_pct == 82.0
    monkeypatch.setattr(weather, "client", FakeWeather(exc=weather.WeatherError("down")))
    r = _post(c, fid)
    assert r.status_code == 201 and capture.ctx.weather is None and r.json()["weather_note"]


def test_history_is_small_same_farm_same_crop_and_newest_first(register, capture):
    c = register()
    fid = _farm(c)
    other_farm = _farm(c)
    ids = [_post(c, fid, crop="Tomato", symptoms=f"yellow leaves {i}").json()["id"] for i in range(5)]
    _post(c, fid, crop="Chilli", symptoms="holes")  # other crop
    _post(c, other_farm, crop="Tomato", symptoms="other farm")  # other farm
    assert _post(c, fid, crop="tomato", symptoms="yellow again").status_code == 201  # case-insensitive crop
    hist = capture.ctx.history
    assert len(hist) == 3 and all(h.crop.lower() == "tomato" for h in hist)
    assert [h.symptoms for h in hist] == ["yellow leaves 4", "yellow leaves 3", "yellow leaves 2"]
    assert all(h.likely_issue for h in hist) and ids  # earlier assessments only


def test_history_never_includes_another_users_analyses(register, capture):
    a = register("a@example.com")
    b = register("b@example.com")
    fa, fb = _farm(a), _farm(b)
    for i in range(3):
        _post(a, fa, crop="Tomato", symptoms=f"A secret {i}")
    assert _post(b, fb, crop="Tomato", symptoms="B first").status_code == 201
    assert capture.ctx.history == []  # B sees none of A's analyses
    assert _post(b, fa, crop="Tomato", symptoms="B on A farm").status_code == 404  # foreign farm still blocked
    _post(a, fa, crop="Tomato", symptoms="A again")
    assert all("B " not in h.symptoms for h in capture.ctx.history)


def test_old_phase1_and_phase2_results_still_load(register):
    c = register()
    fid = _farm(c)
    uid = c.get("/auth/me").json()["id"]
    p1 = {"likely_issue": "Old issue", "explanation": "e", "recommended_actions": ["a"], "precautions": ["p"], "uncertainty": "u"}
    p2 = {**p1, "likely_issue": "P2 issue", "severity": "low", "observations": ["o"], "when_to_seek_help": "w"}
    with SessionLocal() as db:
        for res, sym in ((p1, "old1"), (p2, "old2")):
            db.add(Analysis(user_id=uid, farm_id=fid, crop="Rice", symptoms=sym, language="en", result_json=res))
        db.commit()
    items = {i["symptoms"]: i for i in c.get("/analyses").json()}
    for key in ("old1", "old2"):
        r = items[key]["result"]
        assert r["possible_alternatives"] == [] and r["immediate_actions"] == [] and r["follow_up_questions"] == []
        assert r["uncertainty_level"] == "unknown" and r["image_quality"] == "not_provided"
        assert r["recommended_actions"] == ["a"]
    assert items["old2"]["result"]["severity"] == "low" and items["old2"]["result"]["observations"] == ["o"]
    one = c.get(f"/analyses/{items['old1']['id']}")
    assert one.status_code == 200


def test_text_only_json_api_still_works_with_demo_pipeline(register):
    c = register()
    r = c.post("/analyses", json={"farm_id": _farm(c), "crop": "Tomato", "symptoms": "Leaves are turning yellow"})
    assert r.status_code == 201
    res = r.json()["result"]
    assert res["immediate_actions"] and res["monitoring_steps"] and res["recommended_actions"]
