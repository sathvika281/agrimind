import pytest

from app.schemas import AnalysisResult
from app.services.ai import AIServiceError, AnalysisContext, analyze
from app.services.ai.demo_provider import DemoAIProvider


def test_demo_provider_returns_valid_result():
    out = analyze(AnalysisContext(crop="Tomato", symptoms="leaves turning yellow"), DemoAIProvider())
    assert isinstance(out, AnalysisResult)
    assert "yellow" in out.likely_issue.lower()


def test_demo_provider_varies_by_symptoms():
    a = analyze(AnalysisContext(crop="Tomato", symptoms="yellow leaves"), DemoAIProvider())
    b = analyze(AnalysisContext(crop="Chilli", symptoms="caterpillar eating holes"), DemoAIProvider())
    assert a.likely_issue != b.likely_issue


def test_unknown_symptoms_give_safe_generic_response():
    out = analyze(AnalysisContext(crop="Quinoa", symptoms="something odd happened"), DemoAIProvider())
    assert "uncertain" in out.uncertainty.lower()
    assert out.recommended_actions
    assert any("agricultural officer" in p.lower() for p in out.precautions)


def test_no_pesticide_dosages_in_any_rule():
    for s in ["yellow", "spots", "wilting", "insect holes", "powdery mildew", "stunted", "nothing"]:
        text = str(DemoAIProvider().analyze(AnalysisContext(crop="x", symptoms=s))).lower()
        for unit in (" ml", " ml/", "grams per", " g/l", "ml per", "kg/acre", "per litre"):
            assert unit not in text


class _Bad:
    name = "bad"

    def __init__(self, payload):
        self.payload = payload

    def analyze(self, ctx):
        return self.payload


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"likely_issue": "x"},
        {"likely_issue": "", "explanation": "e", "recommended_actions": ["a"], "precautions": [], "uncertainty": "u"},
        {"likely_issue": "x", "explanation": "e", "recommended_actions": "not a list", "precautions": [], "uncertainty": "u"},
        {"likely_issue": "x", "explanation": "e", "recommended_actions": [], "precautions": [], "uncertainty": "u"},
        "just a string",
    ],
)
def test_malformed_provider_output_is_rejected(payload):
    with pytest.raises(AIServiceError):
        analyze(AnalysisContext(crop="a", symptoms="b"), _Bad(payload))


def test_provider_exception_is_wrapped_without_leaking_details():
    class Boom:
        name = "boom"

        def analyze(self, ctx):
            raise RuntimeError("db password is hunter2")

    with pytest.raises(AIServiceError) as e:
        analyze(AnalysisContext(crop="a", symptoms="b"), Boom())
    assert "hunter2" not in str(e.value)
