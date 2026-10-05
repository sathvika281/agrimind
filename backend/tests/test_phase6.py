import json
import re

import httpx
import pytest

from app.database import SessionLocal
from app.models import Analysis
from app.schemas import AnalysisResult
from app.services.ai import AIServiceError, AnalysisContext, HistoryItem, ImageInput, WeatherContext, analyze, service
from app.services.ai import demo_te
from app.services.ai.demo_provider import DemoAIProvider
from app.services.ai.gemini_provider import RESPONSE_SCHEMA, GeminiProvider
from app.services.ai.safety import IMAGE_GUIDANCE_TE, STANDARD_QUESTIONS_TE
from tests.test_phase2 import PNG, WX, _farm, _post, uploads_count

TELUGU = re.compile(r"[ఀ-౿]")
ENUMS = {"severity": {"low", "medium", "high", "unknown"}, "uncertainty_level": {"low", "some", "high", "unknown"},
         "image_quality": {"good", "limited", "poor", "not_provided"}}
SYMPTOMS_TE = "నా టమాటా ఆకులు పసుపు రంగులోకి మారుతున్నాయి, కింది ఆకులపై చిన్న మచ్చలు ఉన్నాయి"


def te_ctx(**kw) -> AnalysisContext:
    kw.setdefault("crop", "Tomato")
    kw.setdefault("symptoms", SYMPTOMS_TE)
    return AnalysisContext(language="te", **kw)


def te_payload(**over) -> dict:
    base = DemoAIProvider().analyze(te_ctx())
    base.update(over)
    return base


class Scripted:
    name = "scripted"

    def __init__(self, payload):
        self.payload = payload

    def analyze(self, ctx):
        return self.payload


def run_te(payload, **ctx_kw):
    return analyze(te_ctx(**ctx_kw), Scripted(payload))


def has_telugu(out: AnalysisResult) -> bool:
    return all(TELUGU.search(t) for t in [out.likely_issue, out.explanation, out.uncertainty, *out.recommended_actions, *out.precautions])


# ======================= language parameter plumbing =======================
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


def test_default_language_is_english_and_unchanged(register, capture):
    c = register()
    r = c.post("/analyses", json={"farm_id": _farm(c), "crop": "Tomato", "symptoms": "yellow leaves"})
    assert r.status_code == 201 and r.json()["language"] == "en" and capture.ctx.language == "en"
    assert not TELUGU.search(json.dumps(r.json()["result"], ensure_ascii=False))


def test_telugu_language_is_validated_stored_and_reaches_the_provider(register, capture):
    c = register()
    fid = _farm(c)
    r = c.post("/analyses", data={"farm_id": str(fid), "crop": "Tomato", "symptoms": SYMPTOMS_TE, "language": "te"})
    d = r.json()
    assert r.status_code == 201 and d["language"] == "te" and capture.ctx.language == "te"
    assert has_telugu(AnalysisResult.model_validate(d["result"]))
    # structured values are never translated
    assert d["result"]["severity"] in ENUMS["severity"] and d["result"]["uncertainty_level"] in ENUMS["uncertainty_level"]
    assert d["result"]["image_quality"] in ENUMS["image_quality"] and d["input_type"] in ("text", "image", "text+image")
    again = c.get(f"/analyses/{d['id']}").json()
    assert again["language"] == "te" and again["result"] == d["result"]  # stored language preserved, never regenerated


def test_language_in_json_body_and_form_variants(register, capture):
    c = register()
    fid = _farm(c)
    assert c.post("/analyses", json={"farm_id": fid, "crop": "Rice", "symptoms": "yellow", "language": "te"}).json()["language"] == "te"
    assert c.post("/analyses", data={"farm_id": str(fid), "crop": "Rice", "symptoms": "yellow", "language": "TE"}).json()["language"] == "te"
    assert c.post("/analyses", data={"farm_id": str(fid), "crop": "Rice", "symptoms": "yellow", "language": ""}).json()["language"] == "en"
    r = _post(c, fid, image=PNG)  # existing helper sends no language field
    assert r.status_code == 201 and r.json()["language"] == "en"


@pytest.mark.parametrize("bad", ["fr", "telugu", "te-IN", "<script>"])
def test_unsupported_language_is_rejected_cleanly(register, bad):
    c = register()
    r = c.post("/analyses", json={"farm_id": _farm(c), "crop": "Rice", "symptoms": "yellow", "language": bad})
    assert r.status_code == 422 and r.json()["code"] == "invalid_request"
    assert c.get("/analyses").json() == [] and uploads_count() == 0


def test_idempotency_key_with_a_different_language_is_a_conflict(register, capture):
    c = register()
    fid = _farm(c)
    h = {"Idempotency-Key": "lang-key-00000001"}
    base = {"farm_id": str(fid), "crop": "Tomato", "symptoms": "yellow leaves with spots"}
    a = c.post("/analyses", data={**base, "language": "te"}, headers=h)
    same = c.post("/analyses", data={**base, "language": "te"}, headers=h)
    other = c.post("/analyses", data={**base, "language": "en"}, headers=h)
    assert a.status_code == 201 and same.status_code == 200 and same.json()["id"] == a.json()["id"]
    assert other.status_code == 409 and other.json()["code"] == "idempotency_conflict"
    assert len(c.get("/analyses").json()) == 1


def test_old_english_results_are_untouched_when_ui_language_differs(register):
    """Existing analyses keep the language they were generated in (never regenerated or relabelled)."""
    c = register()
    fid = _farm(c)
    uid = c.get("/auth/me").json()["id"]
    old = {"likely_issue": "Old issue", "explanation": "e", "recommended_actions": ["a"], "precautions": ["p"], "uncertainty": "u"}
    with SessionLocal() as db:
        db.add(Analysis(user_id=uid, farm_id=fid, crop="Rice", symptoms="old", language="en", result_json=old))
        db.commit()
    c.post("/analyses", data={"farm_id": str(fid), "crop": "Rice", "symptoms": SYMPTOMS_TE, "language": "te"})
    items = {i["symptoms"]: i for i in c.get("/analyses").json()}
    assert items["old"]["language"] == "en" and items["old"]["result"]["likely_issue"] == "Old issue"
    assert items[SYMPTOMS_TE]["language"] == "te"


# ======================= Gemini (mocked HTTP): prompt + structured output =======================
def gemini_with(handler):
    calls = []

    def wrapped(request):
        calls.append(json.loads(request.content))
        return handler(request)

    return GeminiProvider(api_key="k", http=httpx.Client(transport=httpx.MockTransport(wrapped))), calls


def reply(payload):
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps(payload, ensure_ascii=False)}]}}]})


def test_gemini_prompt_asks_for_natural_telugu_and_english_enums_with_one_call():
    p, calls = gemini_with(lambda r: reply(te_payload()))
    out = analyze(te_ctx(), p)
    assert len(calls) == 1 and has_telugu(out)
    sys_prompt = calls[0]["systemInstruction"]["parts"][0]["text"]
    assert "Telugu" in sys_prompt and "తెలుగు" in sys_prompt
    assert "conversational" in sys_prompt and "do not force English or formal Telugu" in sys_prompt
    assert "enum values (severity, uncertainty_level, image_quality) in English" in sys_prompt
    assert "{language" not in sys_prompt  # placeholders fully substituted
    for word in ("OBSERVATION", "LIKELY INTERPRETATION", "RECOMMENDED NEXT STEP", "UNCERTAINTY"):
        assert word in sys_prompt  # existing safety framing intact
    assert "Never give pesticide" in sys_prompt or "Never give" in sys_prompt


def test_gemini_english_prompt_is_unchanged_in_substance():
    p, calls = gemini_with(lambda r: reply(DemoAIProvider().analyze(AnalysisContext(crop="Rice", symptoms="yellow leaves with brown spots"))))
    analyze(AnalysisContext(crop="Rice", symptoms="yellow leaves with brown spots"), p)
    sp = calls[0]["systemInstruction"]["parts"][0]["text"]
    assert "Write all free-text values in English." in sp and "Telugu" not in sp


def test_response_schema_enum_values_stay_english():
    props = RESPONSE_SCHEMA["properties"]
    assert set(props["severity"]["enum"]) == ENUMS["severity"] - set() or set(props["severity"]["enum"]) <= ENUMS["severity"]
    assert set(props["uncertainty_level"]["enum"]) <= ENUMS["uncertainty_level"]
    assert set(props["image_quality"]["enum"]) <= ENUMS["image_quality"]


def test_gemini_telugu_output_with_english_enum_values_is_accepted_and_stored(register, monkeypatch):
    payload = te_payload(severity="medium", uncertainty_level="some")
    p, calls = gemini_with(lambda r: reply(payload))
    monkeypatch.setattr(service, "get_provider", lambda: p)
    c = register()
    r = c.post("/analyses", data={"farm_id": str(_farm(c)), "crop": "Tomato", "symptoms": SYMPTOMS_TE, "language": "te"})
    d = r.json()
    assert r.status_code == 201 and len(calls) == 1
    assert d["result"]["severity"] == "medium" and d["result"]["uncertainty_level"] == "some" and has_telugu(AnalysisResult.model_validate(d["result"]))
    assert "తెలుగు" in calls[0]["systemInstruction"]["parts"][0]["text"]


def test_gemini_telugu_unsafe_output_is_rejected_and_nothing_stored(register, monkeypatch):
    bad = te_payload(immediate_actions=["ఒక లీటరు నీటికి 10 మి.లీ పురుగుమందు కలపండి."], recommended_actions=["ఒక లీటరు నీటికి 10 మి.లీ పురుగుమందు కలపండి."])
    p, _ = gemini_with(lambda r: reply(bad))
    monkeypatch.setattr(service, "get_provider", lambda: p)
    c = register()
    r = c.post("/analyses", data={"farm_id": str(_farm(c)), "crop": "Tomato", "symptoms": SYMPTOMS_TE, "language": "te"},
               files={"image": ("a.png", PNG, "image/png")})
    assert r.status_code == 503 and r.json()["code"] == "ai_unsafe_output"
    assert "మి.లీ" not in r.text and "Traceback" not in r.text
    assert c.get("/analyses").json() == [] and uploads_count() == 0


# ======================= demo provider in Telugu =======================
@pytest.mark.parametrize(
    "symptoms",
    [
        "Leaves are turning yellow",                      # English input, Telugu output
        SYMPTOMS_TE,                                      # Telugu input (keyword match)
        "నా టమాటా leaves yellow అవుతున్నాయి",            # mixed Telugu + English (the spec's example)
        "ఆకులపై మచ్చలు ఉన్నాయి",
        "మొక్కలు వాడిపోతున్నాయి",
        "ఆకులలో రంధ్రాలు, పురుగులు కనిపిస్తున్నాయి",
        "ఆకులపై తెల్లటి పొర, బూజు",
        "ఎదుగుదల లేదు, ఆకులు ముడుచుకు పోతున్నాయి",
        "ఏదో తేడాగా ఉంది కానీ ఏమిటో తెలియదు",           # unknown -> safe generic
    ],
)
def test_demo_telugu_output_is_telugu_valid_and_passes_safety(symptoms):
    out = analyze(te_ctx(symptoms=symptoms), DemoAIProvider())
    assert has_telugu(out) and out.immediate_actions and out.monitoring_steps and out.when_to_seek_help
    assert out.severity in ENUMS["severity"] and out.uncertainty_level in ENUMS["uncertainty_level"]
    assert out.image_quality in ENUMS["image_quality"]
    assert TELUGU.search(out.when_to_seek_help) and all(TELUGU.search(x) for x in out.monitoring_steps)


def test_demo_telugu_keeps_safety_semantics():
    out = analyze(te_ctx(), DemoAIProvider())
    assert any("అధికారి" in p and "లేబుల్" in p for p in out.precautions)  # check with officer + follow the label
    assert "హామీ ఇవ్వదు" in out.uncertainty  # no guaranteed diagnosis
    assert out.uncertainty_level in ("some", "high") and out.severity == "unknown"
    assert not any(re.search(r"\d+\s*(?:మి\.?\s?లీ|గ్రా|కిలో|లీటర్)", x) for x in out.recommended_actions + out.precautions)


def test_demo_telugu_generic_fallback_is_uncertain_with_questions():
    out = analyze(te_ctx(symptoms="ఏదో తేడాగా ఉంది కానీ ఏమిటో తెలియదు"), DemoAIProvider())
    assert out.uncertainty_level == "high" and out.follow_up_questions and len(out.possible_alternatives) <= 3


def test_demo_telugu_with_photo_weather_and_history():
    ctx = te_ctx(image=ImageInput(PNG, "image/png"), weather=WX,
                 history=[HistoryItem(date="2026-09-01", crop="Tomato", likely_issue="x", severity="low", symptoms="s")])
    out = analyze(ctx, DemoAIProvider())
    assert out.image_quality == "limited" and TELUGU.search(out.image_guidance)
    assert any("వాతావరణ" in o for o in out.observations)  # weather summarised in Telugu from numbers
    assert any("తనిఖీ" in o for o in out.observations)


def test_demo_telugu_multiple_matches_use_telugu_alternatives():
    out = analyze(te_ctx(symptoms="ఆకులు పసుపు రంగులో ఉన్నాయి మరియు మచ్చలు కూడా ఉన్నాయి, పురుగులు కూడా కనిపిస్తున్నాయి"), DemoAIProvider())
    assert out.uncertainty_level == "high" and all(TELUGU.search(a.possibility) for a in out.possible_alternatives)


def test_every_telugu_demo_rule_text_passes_the_verifier_on_its_own():
    for i in range(len(demo_te.RULES_TE)):
        kw = demo_te.KEYWORDS_TE[i][0]
        analyze(te_ctx(symptoms=f"నా పంటలో {kw} కనిపిస్తోంది, గత వారం నుండి ఇలా ఉంది"), DemoAIProvider())


# ======================= Telugu safety: rejected =======================
UNSAFE_TE = {
    "dosage_ml_per_litre": dict(immediate_actions=["ఒక లీటరు నీటికి 10 మి.లీ పురుగుమందు కలపండి."]),
    "dosage_telugu_digits": dict(immediate_actions=["ఎకరాకు ౫౦౦ గ్రాముల యూరియా వేయండి."]),
    "dosage_rate_per_acre": dict(monitoring_steps=["ఎకరాకు 2 కిలోలు ఎరువు వేయాలి."]),
    "dosage_in_explanation": dict(explanation="శిలీంద్రనాశిని 2 గ్రాములు ఒక లీటరు నీటిలో కలపాలి."),
    "concentration_percent": dict(precautions=["0.5% ద్రావణం పిచికారీ చేయండి."]),
    "concentration_ppm": dict(precautions=["పిచికారీ గాఢత 200 పీపీఎం ఉండాలి."]),
    "prohibition_without_safeguard": dict(precautions=["10 మి.లీ కంటే ఎక్కువ మందు వాడవద్దు."]),
    "guaranteed_certainly": dict(likely_issue="ఇది ఖచ్చితంగా ఫంగస్ తెగులు"),
    "guaranteed_no_doubt": dict(explanation="సందేహం లేదు, ఇది బూజు తెగులే."),
    "guaranteed_cure": dict(explanation="ఈ మందు వాడితే పూర్తిగా నయం అవుతుంది."),
    "guaranteed_hundred": dict(explanation="100% ఇదే కారణం."),
    "guaranteed_english_word": dict(explanation="This is definitely early blight, ఇదే కారణం."),
    "lab_confirmed": dict(observations=["ప్రయోగశాల పరీక్షలో ఫంగస్ నిర్ధారణ అయింది"]),
    "weather_caused": dict(explanation="వర్షం వల్ల ఆకు మచ్చలు వచ్చాయి."),
    "chem_directive": dict(immediate_actions=["ఈ రోజే అన్ని మొక్కలపై శిలీంద్రనాశిని పిచికారీ చేయండి."]),
    "image_claim_without_image": dict(observations=["ఫోటోలో గోధుమ రంగు మచ్చలు కనిపిస్తున్నాయి"]),
    "weather_numbers_without_weather": dict(observations=["గత 3 రోజుల్లో 20 మి.మీ వర్షం పడింది"]),
    "english_dosage_inside_telugu": dict(explanation="మందు 2 ml/L చొప్పున కలపండి."),
}


@pytest.mark.parametrize("case", list(UNSAFE_TE))
def test_unsafe_telugu_output_is_rejected(case):
    payload = te_payload(**UNSAFE_TE[case])
    if "immediate_actions" in UNSAFE_TE[case]:
        payload["recommended_actions"] = UNSAFE_TE[case]["immediate_actions"] + ["పొలాన్ని గమనించండి."]
    with pytest.raises(AIServiceError) as e:
        run_te(payload)
    assert "మి.లీ" not in str(e.value) and "dosage" not in str(e.value).lower()


# ======================= Telugu safety: legitimate wording allowed =======================
ALLOWED_TE = {
    "your_example_disclaimer": dict(precautions=["10 మి.లీ మోతాదు వాడవద్దు, ప్యాకెట్‌పై లేబుల్‌లో ఉన్న మోతాదు మాత్రమే పాటించండి."]),
    "negated_guarantee": dict(uncertainty="AgriMind నిర్ధారణకు హామీ ఇవ్వదు."),
    "cannot_say_certainly": dict(explanation="ఇది ఖచ్చితంగా ఏమిటో ఇప్పుడే చెప్పలేము."),
    "irrigation_volume": dict(immediate_actions=["ప్రతి మొక్కకు ఉదయం 2 లీటర్ల నీరు పోయండి."]),
    "ask_officer_first": dict(immediate_actions=["శిలీంద్రనాశిని వాడే ముందు అధికారి సలహా తీసుకోండి, లేబుల్ చూడండి."]),
    "do_not_spray_until_sure": dict(immediate_actions=["కారణం తెలిసే వరకు శిలీంద్రనాశిని పిచికారీ చేయవద్దు."]),
    "hedged_weather": dict(explanation="వర్షం వల్ల కొన్ని తెగుళ్లు పెరగవచ్చు, కానీ ఇక్కడ అది నిర్ధారణ కాలేదు."),
    "not_lab_confirmed": dict(observations=["ఇది ప్రయోగశాలలో నిర్ధారించబడలేదు."]),
}


@pytest.mark.parametrize("case", list(ALLOWED_TE))
def test_legitimate_telugu_wording_is_allowed(case):
    payload = te_payload(**ALLOWED_TE[case])
    if "immediate_actions" in ALLOWED_TE[case]:
        payload["recommended_actions"] = ALLOWED_TE[case]["immediate_actions"] + ["పొలాన్ని గమనించండి."]
    assert isinstance(run_te(payload), AnalysisResult)


def test_ambiguous_telugu_dosage_is_rejected_not_repaired():
    # prohibition word but NO safeguard: could be an instruction in disguise -> reject
    with pytest.raises(AIServiceError):
        run_te(te_payload(precautions=["ఒక లీటరుకు 5 మి.లీ మందు మించి వాడవద్దు."]))
    # safeguard word but NO prohibition/condition: reads as a recommendation -> reject
    with pytest.raises(AIServiceError):
        run_te(te_payload(precautions=["లేబుల్ ప్రకారం ఒక లీటరుకు 5 మి.లీ మందు కలపండి."]))


# ======================= repairs in Telugu =======================
def test_telugu_repairs_use_telugu_standard_text_only():
    out = run_te(te_payload(follow_up_questions=[], uncertainty_level="low"), symptoms="చెడు")
    assert out.follow_up_questions == STANDARD_QUESTIONS_TE and out.uncertainty_level == "some"
    poor = run_te(te_payload(image_quality="poor", image_guidance="", uncertainty_level="low", follow_up_questions=[]),
                  symptoms="", image=ImageInput(PNG, "image/png"))
    assert poor.image_guidance == IMAGE_GUIDANCE_TE and poor.uncertainty_level == "high"
    assert out.likely_issue == te_payload()["likely_issue"]  # repairs never rewrite the content itself


def test_telugu_severity_is_never_silently_downgraded():
    assert run_te(te_payload(severity="high")).severity == "high"
    # English behaviour is unchanged (capped without escalation signals)
    from tests.test_phase3 import mk, run
    assert run(mk(severity="high")).severity == "medium"


def test_english_safety_still_applies_to_english_and_numeric_text_in_telugu_mode():
    with pytest.raises(AIServiceError):
        run_te(te_payload(explanation="Mix 10 ml per litre of fungicide."))
    with pytest.raises(AIServiceError):
        run_te(te_payload(likely_issue="This is definitely early blight"))
