"""Agent 7: Safety / Policy. The last gate before anything reaches the farmer. Deterministic and fail-closed.

It layers new policy checks over the existing verifier (services/ai/safety.py, EN + TE dose/product/spray scans),
which stays the authority on treatment advice. Checks here: the answer may not claim more certainty than the
evidence allowed, may not lower the uncertainty the analysis stated, may not change the issue or lower the
severity, may not cite a source that was not retrieved, and must still contain actions to take.
If this function itself raises, the graph treats it as unsafe and returns no answer (fail closed).
"""
import re

from ...schemas import AnalysisResult
from ..ai.base import AnalysisContext
from ..ai.safety import SafetyError, verify
from ..graph.state import SafetyVerdict

_CERTAIN = re.compile(
    r"\b(definitely|certainly|for sure|without (?:a )?doubt|guaranteed?|100\s?%|surely|undoubtedly|no doubt)\b|ఖచ్చితంగా|నిస్సందేహంగా", re.I)
_UNC_ORDER = {"low": 0, "some": 1, "high": 2}  # higher = less sure
_SEV_ORDER = {"unknown": 0, "low": 1, "medium": 2, "high": 3}


def check(candidate: AnalysisResult, base: AnalysisResult, ctx: AnalysisContext, retrieved_urls: set[str]) -> tuple[SafetyVerdict, AnalysisResult | None]:
    violations: list[str] = []
    fixes: list[str] = []
    verified: AnalysisResult | None = None
    try:
        verified = verify(candidate, ctx)
    except SafetyError as e:
        violations.append(f"treatment_or_unsafe_content:{e.code}")
        fixes.append("remove any pesticide, product, dose, quantity or spray-schedule advice")

    text = " ".join([candidate.verdict, candidate.likely_issue, candidate.explanation])
    if candidate.uncertainty_level != "low" and _CERTAIN.search(text):
        violations.append("unsupported_certainty")
        fixes.append("remove words that claim certainty; the evidence is not conclusive")
    b, c = _UNC_ORDER.get(base.uncertainty_level), _UNC_ORDER.get(candidate.uncertainty_level)
    if b is not None and (c is None or c < b):
        violations.append("uncertainty_lowered")
        fixes.append("keep the stated level of uncertainty")
    if candidate.likely_issue != base.likely_issue or _SEV_ORDER.get(candidate.severity, 0) < _SEV_ORDER.get(base.severity, 0):
        violations.append("issue_or_severity_changed")
        fixes.append("do not change the likely issue or lower the severity")
    if any(s.url not in retrieved_urls for s in candidate.sources):
        violations.append("source_not_retrieved")
        fixes.append("cite only retrieved sources")
    if not (candidate.immediate_actions or candidate.monitoring_steps or candidate.recommended_actions):
        violations.append("no_actions")
        fixes.append("include what to verify or monitor")

    safe = not violations
    return SafetyVerdict(safe=safe, violations=violations, required_changes=fixes, retry_required=not safe), (verified if safe else None)
