"""Agent 2: Crop Analysis. The model-backed observer: what is visible/described, which explanations are candidates,
and how sure it is. It reuses the existing, validated provider call (same prompt, model, timeouts), so image
handling, language and the structured schema are unchanged. Final safety verification happens later, at the end.
"""
import logging

from pydantic import ValidationError

from ...schemas import AnalysisResult
from ..ai.base import AIProvider, AIServiceError, AnalysisContext
from ..ai.service import GENERIC_FAILURE, _normalize
from ..graph.state import CropAnalysis

log = logging.getLogger("agrimind.agents")

# 'uncertainty_level' says how unsure the model is; confidence is its complement, never above 0.9.
_CONFIDENCE = {"low": 0.8, "some": 0.5, "high": 0.2, "unknown": 0.0}


def run(ctx: AnalysisContext, provider: AIProvider) -> tuple[AnalysisResult, CropAnalysis]:
    try:
        raw = provider.analyze(ctx)
    except AIServiceError:
        raise
    except Exception:  # noqa: BLE001
        log.exception("crop analysis provider failed")
        raise AIServiceError(GENERIC_FAILURE)
    try:
        result = _normalize(AnalysisResult.model_validate(raw))
    except (ValidationError, TypeError, ValueError):
        log.warning("crop analysis returned malformed output")
        raise AIServiceError(GENERIC_FAILURE)
    if not result.recommended_actions:
        raise AIServiceError(GENERIC_FAILURE)
    candidates = [result.likely_issue, *[a.possibility for a in result.possible_alternatives if a.possibility]]
    return result, CropAnalysis(
        observations=list(result.observations),
        candidate_issues=[c for c in dict.fromkeys(candidates) if c][:4],
        confidence=_CONFIDENCE.get(result.uncertainty_level, 0.0),
        image_quality=result.image_quality,
        uncertainties=list(result.unknowns),
        additional_evidence_needed=list(result.follow_up_questions),
    )
