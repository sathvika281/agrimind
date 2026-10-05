"""Phase 7 / Part A: Gemini hardening + the live-validation script. NOTHING here makes a real network call."""
import importlib.util
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from app.schemas import AnalysisResult
from app.services.ai import AIServiceError, AnalysisContext, analyze
from app.services.ai.demo_provider import DemoAIProvider
from app.services.ai.gemini_provider import GeminiProvider
from tests.test_phase6 import SYMPTOMS_TE, Scripted, te_ctx, te_payload

BACKEND = Path(__file__).resolve().parent.parent
SCRIPT = BACKEND / "scripts" / "validate_gemini.py"
FAKE_KEY = "fake-test-key-DO-NOT-LEAK-12345"


def load_script():
    spec = importlib.util.spec_from_file_location("validate_gemini", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------- Gemini provider hardening (mocked HTTP) ----------------
def test_output_token_budget_leaves_room_for_thinking_and_telugu():
    p = GeminiProvider(api_key="k")
    cfg = p._payload(AnalysisContext(crop="a", symptoms="b"))["generationConfig"]
    assert cfg["maxOutputTokens"] >= 8192
    assert cfg["responseMimeType"] == "application/json" and cfg["responseSchema"]["type"] == "OBJECT"


def _gem(handler):
    return GeminiProvider(api_key=FAKE_KEY, http=httpx.Client(transport=httpx.MockTransport(handler)))


@pytest.fixture()
def agri_logs():
    buf = []

    class H(logging.Handler):
        def emit(self, record):
            buf.append(self.format(record))

    h = H()
    h.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    lg = logging.getLogger("agrimind")
    lg.addHandler(h)
    old = lg.level
    lg.setLevel(logging.DEBUG)
    yield buf
    lg.removeHandler(h)
    lg.setLevel(old)


@pytest.mark.parametrize("finish", ["MAX_TOKENS", "SAFETY", "RECITATION"])
def test_truncated_or_blocked_output_is_clean_error_with_diagnosable_log(finish, agri_logs):
    secret_text = '{"likely_issue": "private farm note gate code 9981", "expl'  # cut off mid-JSON
    body = {"candidates": [{"finishReason": finish, "content": {"parts": [{"text": secret_text}]}}]}
    with pytest.raises(AIServiceError) as e:
        analyze(AnalysisContext(crop="Rice", symptoms="yellow leaves with spots"), _gem(lambda r: httpx.Response(200, json=body)))
    assert "temporarily unavailable" in str(e.value)
    text = "\n".join(agri_logs)
    assert f"finish_reason={finish}" in text and "chars=" in text
    assert "gate code" not in text and "9981" not in text and FAKE_KEY not in text  # reason is logged, content/key never


def test_missing_finish_reason_and_non_object_json_are_handled(agri_logs):
    for text in ("[1,2,3]", "not json", ""):
        body = {"candidates": [{"content": {"parts": [{"text": text}]}}]}
        with pytest.raises(AIServiceError):
            analyze(AnalysisContext(crop="a", symptoms="yellow leaves with spots"), _gem(lambda r: httpx.Response(200, json=body)))
    assert any("finish_reason=unknown" in line for line in agri_logs)


def test_blocked_prompt_without_candidates_is_clean(agri_logs):
    body = {"promptFeedback": {"blockReason": "SAFETY"}}
    with pytest.raises(AIServiceError):
        analyze(AnalysisContext(crop="a", symptoms="yellow leaves with spots"), _gem(lambda r: httpx.Response(200, json=body)))


def test_request_has_the_real_api_shape_for_text_image_and_telugu():
    """Pins the REST shape we rely on (cannot be proven live without a key)."""
    from tests.test_phase2 import PNG

    from app.services.ai import ImageInput

    seen = {}

    def handler(request):
        seen["url"], seen["body"], seen["h"] = str(request.url), json.loads(request.content), request.headers
        good = DemoAIProvider().analyze(AnalysisContext(crop="Rice", symptoms="yellow leaves with brown spots", language="te"))
        return httpx.Response(200, json={"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(good, ensure_ascii=False)}]}}]})

    p = _gem(handler)
    p._model = "gemini-2.5-flash"
    analyze(te_ctx(image=ImageInput(PNG, "image/png")), p)
    b = seen["body"]
    assert seen["url"].endswith("/models/gemini-2.5-flash:generateContent") and "key=" not in seen["url"]
    assert seen["h"]["x-goog-api-key"] == FAKE_KEY
    parts = b["contents"][0]["parts"]
    assert "text" in parts[0] and parts[1]["inline_data"]["mime_type"] == "image/png" and parts[1]["inline_data"]["data"]
    assert b["generationConfig"]["responseSchema"]["properties"]["uncertainty_level"]["enum"] == ["low", "some", "high"]
    assert "systemInstruction" in b and "తెలుగు" in b["systemInstruction"]["parts"][0]["text"]
    assert SYMPTOMS_TE in parts[0]["text"]  # Telugu farmer text reaches the model unchanged


# ---------------- the live-validation script ----------------
def test_script_refuses_without_key_and_makes_no_call():
    env = {**os.environ, "GEMINI_API_KEY": "", "AI_PROVIDER": "demo"}  # empty wins over any value in .env
    r = subprocess.run([sys.executable, str(SCRIPT)], cwd=BACKEND, env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 2
    assert "REFUSING TO RUN" in r.stdout and "No live Gemini validation was performed" in r.stdout


def test_script_checks_accept_a_good_result_and_catch_bad_ones():
    s = load_script()
    good = analyze(te_ctx(), DemoAIProvider())
    assert all(ok for _, ok, _ in s.check_result(good, "te", False, SYMPTOMS_TE))
    # English output where Telugu was requested is flagged
    en = analyze(AnalysisContext(crop="Rice", symptoms="yellow leaves with brown spots"), DemoAIProvider())
    assert not all(ok for _, ok, _ in s.check_result(en, "te", False, "x" * 40))
    # Telugu where English was requested is flagged
    assert not all(ok for _, ok, _ in s.check_result(good, "en", False, "x" * 40))
    # a claimed image when none was sent is flagged
    r = AnalysisResult.model_validate({**te_payload(), "image_quality": "good"})
    assert not all(ok for _, ok, _ in s.check_result(r, "te", False, SYMPTOMS_TE))
    # thin evidence + 'low' uncertainty is flagged
    low = AnalysisResult.model_validate({**te_payload(), "uncertainty_level": "low"})
    assert any(n.startswith("uncertainty not 'low'") and not ok for n, ok, _ in s.check_result(low, "te", False, "bad"))


def test_script_review_words_are_reported_for_a_human_not_failed():
    s = load_script()
    r = AnalysisResult.model_validate({**te_payload(), "uncertainty": "AgriMind నిర్ధారణకు హామీ ఇవ్వదు, ఇది ఖచ్చితంగా చెప్పలేము."})
    checks = s.check_result(r, "te", False, SYMPTOMS_TE)
    review = [c for c in checks if "HUMAN REVIEW" in c[0]][0]
    assert review[1] is True and "హామీ" in review[2]


def test_run_case_reports_verifier_rejection_without_crashing():
    s = load_script()
    unsafe = te_payload(immediate_actions=["ఒక లీటరు నీటికి 10 మి.లీ పురుగుమందు కలపండి."], recommended_actions=["ఒక లీటరు నీటికి 10 మి.లీ పురుగుమందు కలపండి."])
    rec = s.run_case(s.CASES[1], Scripted(unsafe), None)
    assert rec["status"] == "FAILED" and rec["error_code"] == "ai_unsafe_output" and "మి.లీ" not in json.dumps(rec, ensure_ascii=False)
    ok = s.run_case(s.CASES[1], Scripted(te_payload()), None)
    assert ok["status"] == "PASSED" and ok["language"] == "te" and ok["input_type"] == "text" and ok["latency_ms"] >= 0


def test_script_main_skips_photo_case_without_photo_never_prints_key_and_never_fabricates(monkeypatch, capsys, tmp_path):
    s = load_script()
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)

    class FakeGemini:  # stands in for the real provider: no network
        model = "fake-model"

        def analyze(self, ctx):
            return DemoAIProvider().analyze(ctx)

    monkeypatch.setattr("app.services.ai.gemini_provider.GeminiProvider", FakeGemini)
    out_json = tmp_path / "r.json"
    code = s.main(["--json", str(out_json)])
    out = capsys.readouterr().out
    assert FAKE_KEY not in out and FAKE_KEY not in out_json.read_text(encoding="utf-8")
    results = json.loads(out_json.read_text(encoding="utf-8"))
    by_case = {r["case"]: r for r in results}
    assert by_case[3]["status"] == "NOT_EXECUTED" and "no real crop photo" in by_case[3]["reason"]
    assert [by_case[i]["status"] for i in (1, 2, 4)] == ["PASSED"] * 3 and code == 0
    assert "NOT_EXECUTED" in out and "Nothing was fabricated" in out
