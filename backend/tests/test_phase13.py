"""Round 2 (clarity, refine, follow-up, diary, weather risk). Scratch DB only; the demo provider or stubs, never live Gemini."""
import pytest

from app.schemas import AnalysisResult, Change, QuickQuestion
from app.services.ai import service
from app.services.ai.demo_provider import DemoAIProvider

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
GOOD = {"likely_issue": "x", "explanation": "y", "recommended_actions": ["Inspect the plants"], "precautions": ["Wear gloves"], "uncertainty": "u"}


def _farm(c, name="F", **kw):
    r = c.post("/farms", json={"name": name, "location": "Guntur", "soil_type": "Red soil", **kw})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _check(c, farm_id, symptoms="yellow leaves with brown spots", language="en", image=False):
    if image:
        r = c.post("/analyses", data={"farm_id": str(farm_id), "crop": "Tomato", "symptoms": symptoms, "language": language}, files={"image": ("a.png", PNG, "image/png")})
    else:
        r = c.post("/analyses", json={"farm_id": farm_id, "crop": "Tomato", "symptoms": symptoms, "language": language})
    assert r.status_code == 201, r.text
    return r.json()


class Spy(DemoAIProvider):
    def __init__(self):
        self.calls = []

    def analyze(self, ctx):
        self.calls.append(ctx)
        return super().analyze(ctx)


# ---------------- A: the new result fields ----------------
def test_demo_results_carry_a_verdict_and_tap_questions_in_both_languages(register):
    c = register()
    fid = _farm(c)
    en = _check(c, fid)["result"]
    assert en["verdict"].startswith("Most likely") and 2 <= len(en["quick_questions"]) <= 3
    assert all(2 <= len(q["options"]) <= 4 for q in en["quick_questions"])
    te = _check(c, fid, "నా ఆకులు పసుపు రంగులోకి మారుతున్నాయి", "te")["result"]
    assert te["verdict"] and any("ఀ" <= ch <= "౿" for ch in te["verdict"])
    unsure = _check(c, fid, "something odd")["result"]
    assert unsure["verdict"].startswith("Not enough to tell yet")


def test_old_results_without_the_new_fields_still_validate_with_defaults():
    r = AnalysisResult.model_validate(GOOD)
    assert r.verdict == "" and r.quick_questions == [] and r.change is None


def test_quick_questions_are_cleaned_and_capped():
    raw = {**GOOD, "quick_questions": [
        {"question": "Which leaves first?", "options": ["Old", "New", "old", "  ", "Fruit", "Stems", "Not sure"]},  # dupes/blank/too many
        {"question": "One option only?", "options": ["Yes"]},  # no real choice -> dropped
        {"question": "", "options": ["a", "b"]},  # no question -> dropped
        {"question": "Spreading?", "options": ["Yes", "No"]},
        {"question": "Q3", "options": ["a", "b"]},
        {"question": "Q4", "options": ["a", "b"]},  # over the cap of 3
        "not a dict",
    ]}
    qs = AnalysisResult.model_validate(raw).quick_questions
    assert [q.question for q in qs] == ["Which leaves first?", "Spreading?", "Q3"]
    assert qs[0].options == ["Old", "New", "Fruit", "Stems"]  # de-duplicated, blanks removed, max 4


def test_change_status_is_constrained_and_defaults_to_unclear():
    assert Change(status="WORSE", note=" a ").status == "worse"
    assert Change(status="catastrophic").status == "unclear"
    assert AnalysisResult.model_validate({**GOOD, "change": "junk"}).change is None
    assert AnalysisResult.model_validate({**GOOD, "change": {"status": "better", "note": "Fewer spots"}}).change.status == "better"


def test_stored_old_result_loads_through_the_api(register):
    from app.database import SessionLocal
    from app.models import Analysis, Farm

    c = register()
    fid = _farm(c)
    with SessionLocal() as db:
        db.add(Analysis(user_id=db.get(Farm, fid).user_id, farm_id=fid, crop="Rice", symptoms="x", language="en", result_json=GOOD))
        db.commit()
    got = c.get("/analyses").json()[0]
    assert got["result"]["verdict"] == "" and got["result"]["quick_questions"] == [] and got["parent_id"] is None and got["link_kind"] is None


@pytest.mark.parametrize("verdict", ["Spray 5 ml per litre now.", "Definitely early blight, guaranteed.", "Mix 10 g in 1 litre of water."])
def test_unsafe_verdicts_are_rejected_like_any_other_text(register, monkeypatch, verdict):
    class Bad:
        name = "stub"

        def analyze(self, ctx):
            return {**GOOD, "verdict": verdict}

    monkeypatch.setattr(service, "get_provider", lambda: Bad())
    c = register()
    fid = _farm(c)
    r = c.post("/analyses", json={"farm_id": fid, "crop": "Tomato", "symptoms": "yellow leaves"})
    assert r.status_code == 503 and c.get("/analyses").json() == []


def test_unsafe_quick_question_options_are_rejected_too(register, monkeypatch):
    class Bad:
        name = "stub"

        def analyze(self, ctx):
            return {**GOOD, "quick_questions": [{"question": "How much?", "options": ["Use 5 ml per litre", "Not sure"]}]}

    monkeypatch.setattr(service, "get_provider", lambda: Bad())
    c = register()
    fid = _farm(c)
    assert c.post("/analyses", json={"farm_id": fid, "crop": "Tomato", "symptoms": "yellow leaves"}).status_code == 503


# ---------------- A: refine ----------------
def _offered_answers(check, n=2):
    return [{"question": q["question"], "answer": q["options"][0]} for q in check["result"]["quick_questions"][:n]]


def test_refine_makes_one_linked_check_from_the_stored_text_photo_and_answers(register, monkeypatch):
    spy = Spy()
    monkeypatch.setattr(service, "get_provider", lambda: spy)
    c = register()
    fid = _farm(c)
    parent = _check(c, fid, "yellow leaves with brown spots", image=True)
    assert len(spy.calls) == 1
    answers = _offered_answers(parent)
    r = c.post(f"/analyses/{parent['id']}/refine", json={"answers": answers})
    assert r.status_code == 201, r.text
    child = r.json()
    assert child["id"] != parent["id"] and child["parent_id"] == parent["id"] and child["link_kind"] == "refine"
    assert child["farm_id"] == parent["farm_id"] and child["crop"] == parent["crop"] and child["has_image"] is True
    assert "yellow leaves with brown spots" in child["symptoms"] and answers[0]["answer"] in child["symptoms"] and answers[0]["question"] in child["symptoms"]
    assert len(spy.calls) == 2  # exactly one more model call
    assert spy.calls[1].image is not None and spy.calls[1].image.data == PNG  # the stored photo was reused
    assert len(c.get("/analyses").json()) == 2


def test_refine_only_accepts_answers_the_check_actually_offered(register):
    c = register()
    fid = _farm(c)
    parent = _check(c, fid)
    q = parent["result"]["quick_questions"][0]
    for bad in (
        [{"question": q["question"], "answer": "Spray 5 ml of chemical"}],  # an option that was never offered
        [{"question": "A question we never asked?", "answer": q["options"][0]}],
        [{"question": q["question"], "answer": q["options"][0].upper() + "!"}],
    ):
        r = c.post(f"/analyses/{parent['id']}/refine", json={"answers": bad})
        assert r.status_code == 422 and r.json()["code"] == "invalid_answer", bad
    assert len(c.get("/analyses").json()) == 1  # nothing was stored


def test_refine_request_shape_is_validated(register):
    c = register()
    fid = _farm(c)
    parent = _check(c, fid)
    url = f"/analyses/{parent['id']}/refine"
    assert c.post(url, json={"answers": []}).status_code == 422
    assert c.post(url, json={}).status_code == 422
    assert c.post(url, json={"answers": [{"question": "q", "answer": "a"}] * 4}).status_code == 422
    assert c.post(url, json={"answers": [{"question": "q" * 301, "answer": "a"}]}).status_code == 422
    assert c.post(url, json={"answers": "nope"}).status_code == 422
    assert c.post(url, json={"answers": _offered_answers(parent, 1), "language": "fr"}).status_code == 422
    assert c.post(url, content=b"{bad", headers={"content-type": "application/json"}).status_code == 422


def test_refine_authorization_matrix(register, client):
    a, b = register("a@example.com"), register("b@example.com")
    parent = _check(a, _farm(a))
    body = {"answers": _offered_answers(parent, 1)}
    miss = b.post("/analyses/999999/refine", json=body)
    foreign = b.post(f"/analyses/{parent['id']}/refine", json=body)
    assert foreign.status_code == miss.status_code == 404 and foreign.json() == miss.json()
    for bad in ("99999999999999999999", "0", "-3"):
        assert b.post(f"/analyses/{bad}/refine", json=body).json() == miss.json()
    assert b.post("/analyses/abc/refine", json=body).status_code == 422
    assert client.post(f"/analyses/{parent['id']}/refine", json=body).status_code == 401
    assert len(a.get("/analyses").json()) == 1 and b.get("/analyses").json() == []


def test_refine_failure_stores_nothing(register, monkeypatch):
    c = register()
    fid = _farm(c)
    parent = _check(c, fid)

    class Down:
        name = "stub"

        def analyze(self, ctx):
            raise service.AIServiceError("down")

    monkeypatch.setattr(service, "get_provider", lambda: Down())
    r = c.post(f"/analyses/{parent['id']}/refine", json={"answers": _offered_answers(parent, 1)})
    assert r.status_code == 503 and len(c.get("/analyses").json()) == 1


def test_refine_is_idempotent_and_not_replayable_as_another_check(register, monkeypatch):
    spy = Spy()
    monkeypatch.setattr(service, "get_provider", lambda: spy)
    c = register()
    fid = _farm(c)
    parent = _check(c, fid)
    other = _check(c, fid, "yellow leaves with brown spots")  # identical text, different parent
    body = {"answers": _offered_answers(parent, 1)}
    h = {"Idempotency-Key": "refine-key-0001"}
    first = c.post(f"/analyses/{parent['id']}/refine", json=body, headers=h)
    again = c.post(f"/analyses/{parent['id']}/refine", json=body, headers=h)
    assert first.status_code == 201 and again.status_code == 200 and again.json()["id"] == first.json()["id"]
    assert again.headers.get("Idempotent-Replay") == "true"
    assert len(c.get("/analyses").json()) == 3  # parent, other, ONE refinement
    calls = len(spy.calls)
    conflict = c.post(f"/analyses/{other['id']}/refine", json={"answers": _offered_answers(other, 1)}, headers=h)
    assert conflict.status_code == 409 and len(spy.calls) == calls  # the same key for a different parent never returns the old result


def test_refine_in_telugu_keeps_the_language_and_answers(register):
    c = register()
    fid = _farm(c)
    parent = _check(c, fid, "నా ఆకులు పసుపు రంగులోకి మారుతున్నాయి", "te")
    r = c.post(f"/analyses/{parent['id']}/refine", json={"answers": _offered_answers(parent)})
    assert r.status_code == 201 and r.json()["language"] == "te" and r.json()["link_kind"] == "refine"


# ---------------- B: follow-up checks ----------------
def _follow(c, parent, symptoms="the spots look worse and more spread", image=False, **extra):
    if image:
        return c.post("/analyses", data={"farm_id": str(parent["farm_id"]), "crop": parent["crop"], "symptoms": symptoms, "language": "en", "follow_up_of": str(parent["id"])}, files={"image": ("b.png", PNG + b"2", "image/png")})
    return c.post("/analyses", json={"farm_id": parent["farm_id"], "crop": parent["crop"], "symptoms": symptoms, "follow_up_of": parent["id"], **extra})


def test_follow_up_is_linked_and_gets_a_comparison(register, monkeypatch):
    spy = Spy()
    monkeypatch.setattr(service, "get_provider", lambda: spy)
    c = register()
    fid = _farm(c)
    parent = _check(c, fid, image=True)
    r = _follow(c, parent, image=True)
    assert r.status_code == 201, r.text
    child = r.json()
    assert child["parent_id"] == parent["id"] and child["link_kind"] == "followup"
    assert child["result"]["change"]["status"] == "worse" and child["result"]["change"]["note"]
    ctx = spy.calls[-1]
    assert ctx.previous and ctx.previous.likely_issue == parent["result"]["likely_issue"] and ctx.previous.image.data == PNG  # the EARLIER photo
    assert ctx.image.data == PNG + b"2"  # and the current one is separate
    assert len(spy.calls) == 2  # one model call for the follow-up
    assert "followup" == c.get(f"/analyses/{child['id']}").json()["link_kind"]


def test_follow_up_without_photos_still_works_and_unclear_is_allowed(register):
    c = register()
    fid = _farm(c)
    parent = _check(c, fid)
    child = _follow(c, parent, "same as before, nothing new").json()
    assert child["result"]["change"]["status"] == "unclear"


def test_a_normal_check_never_keeps_a_comparison_even_if_the_model_invents_one(register, monkeypatch):
    class Inventive:
        name = "stub"

        def analyze(self, ctx):
            return {**GOOD, "change": {"status": "better", "note": "Looks great now"}}

    monkeypatch.setattr(service, "get_provider", lambda: Inventive())
    c = register()
    fid = _farm(c)
    assert _check(c, fid)["result"]["change"] is None


def test_unsafe_comparison_text_is_rejected(register, monkeypatch):
    class Bad:
        name = "stub"

        def analyze(self, ctx):
            return {**GOOD, "change": {"status": "better", "note": "Spray 5 ml per litre to keep improving."}}

    c = register()
    fid = _farm(c)
    parent = _check(c, fid)
    monkeypatch.setattr(service, "get_provider", lambda: Bad())
    assert _follow(c, parent).status_code == 503 and len(c.get("/analyses").json()) == 1


def test_follow_up_parent_rules_and_404_matrix(register):
    a, b = register("a@example.com"), register("b@example.com")
    fa, fa2 = _farm(a), _farm(a, name="Second")
    parent = _check(a, fa)
    body = lambda pid, farm=fa: {"farm_id": farm, "crop": "Tomato", "symptoms": "worse", "follow_up_of": pid}
    ref = a.post("/analyses", json=body(999999))
    assert ref.status_code == 404
    for bad in (0, -3, 99999999999999999999):
        r = a.post("/analyses", json=body(bad))
        assert r.status_code == 404 and r.json() == ref.json(), bad
    assert a.post("/analyses", json=body(parent["id"], fa2)).status_code == 404  # my check, but a different farm
    fb = _farm(b)
    foreign = b.post("/analyses", json={"farm_id": fb, "crop": "Tomato", "symptoms": "worse", "follow_up_of": parent["id"]})
    assert foreign.status_code == 404 and foreign.json() == ref.json()
    assert a.post("/analyses", json={**body(parent["id"]), "follow_up_of": "abc"}).status_code == 422
    assert a.post("/analyses", json={**body(parent["id"]), "follow_up_of": None}).status_code == 201  # null = a normal check
    assert len(a.get("/analyses").json()) == 2 and b.get("/analyses").json() == []


def test_follow_up_failure_stores_nothing(register, monkeypatch):
    c = register()
    fid = _farm(c)
    parent = _check(c, fid)

    class Down:
        name = "stub"

        def analyze(self, ctx):
            raise service.AIServiceError("down")

    monkeypatch.setattr(service, "get_provider", lambda: Down())
    assert _follow(c, parent).status_code == 503 and len(c.get("/analyses").json()) == 1


def test_gemini_request_carries_the_earlier_photo_and_the_follow_up_note():
    from app.services.ai import ImageInput, PreviousCheck, AnalysisContext
    from app.services.ai.gemini_provider import GeminiProvider, RESPONSE_SCHEMA, SYSTEM_PROMPT, build_prompt

    ctx = AnalysisContext(crop="Tomato", symptoms="worse", image=ImageInput(PNG + b"now", "image/png"),
                          previous=PreviousCheck(date="2026-10-01", likely_issue="Leaf spot", severity="medium", verdict="Most likely leaf spot.", symptoms="spots", image=ImageInput(PNG + b"then", "image/png")))
    parts = GeminiProvider(api_key="k")._payload(ctx)["contents"][0]["parts"]
    kinds = ["image" if "inline_data" in p else p["text"][:12] for p in parts]
    assert kinds == ["Farmer-provi", "EARLIER phot", "image", "CURRENT phot", "image"]
    prompt = build_prompt(ctx)
    assert "FOLLOW-UP" in prompt and "2026-10-01" in prompt and "Leaf spot" in prompt
    assert "verdict" in RESPONSE_SCHEMA["required"] and "quick_questions" in RESPONSE_SCHEMA["required"] and "change" in RESPONSE_SCHEMA["properties"]
    assert "Most likely" in SYSTEM_PROMPT and "Never give pesticide" in SYSTEM_PROMPT  # clarity added, safety rules intact
    plain = build_prompt(AnalysisContext(crop="Tomato", symptoms="x"))
    assert "FOLLOW-UP" not in plain


def test_a_refinement_replaces_its_parent_in_history_a_follow_up_does_not(register):
    c = register()
    fid = _farm(c)
    parent = _check(c, fid)
    assert c.get(f"/farms/{fid}/insights").json()["total"] == 1
    child = c.post(f"/analyses/{parent['id']}/refine", json={"answers": _offered_answers(parent, 1)}).json()
    ins = c.get(f"/farms/{fid}/insights").json()
    assert ins["total"] == 1 and ins["latest"]["analysis_id"] == child["id"]  # one incident, counted once, the better answer wins
    dec = c.get(f"/farms/{fid}/decision-support").json()
    assert dec["analysis_id"] == child["id"] and dec["history_total"] == 1
    assert c.get(f"/farms/{fid}/proactive").json()["total_checks"] == 1
    _follow(c, child)
    assert c.get(f"/farms/{fid}/insights").json()["total"] == 2  # a later re-check is a separate observation
    assert len(c.get("/analyses").json()) == 3  # nothing was deleted: all three checks are still stored
