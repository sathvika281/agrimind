"""AI service boundary. The rest of AgriMind only calls analyze().

Pipeline (one model call, plain synchronous request):
  AnalysisContext -> provider.analyze() -> validate -> normalize -> safety.verify() -> AnalysisResult
Evidence extraction (evidence.build_evidence) runs inside the provider prompt builder.

Selecting a provider is explicit (AI_PROVIDER). There is deliberately NO silent
fallback from a real provider to the demo provider: a failure is reported.
"""
import logging

from pydantic import ValidationError

from ...config import settings
from ...schemas import AnalysisResult
from .base import AIProvider, AIServiceError, AnalysisContext
from .demo_provider import DemoAIProvider
from .gemini_provider import GeminiProvider
from .safety import SafetyError, verify

log = logging.getLogger("agrimind.ai")

GENERIC_FAILURE = "AI analysis is temporarily unavailable. Please try again."
SAFETY_FAILURE = (
    "We couldn't produce a safe analysis for this input. Please try again, or ask your local agricultural officer."
)


def get_provider() -> AIProvider:
    name = settings.ai_provider
    if name == "demo":
        return DemoAIProvider()
    if name == "gemini":
        return GeminiProvider()
    raise AIServiceError(f"Unknown AI provider '{name}'. Use AI_PROVIDER=demo or AI_PROVIDER=gemini.")


def _normalize(result: AnalysisResult) -> AnalysisResult:
    """Keep recommended_actions populated (Phase 1/2 contract) from the Phase 3 action lists."""
    if result.recommended_actions:
        return result
    combined = [*result.immediate_actions, *result.monitoring_steps]
    return result.model_copy(update={"recommended_actions": combined})


def analyze(ctx: AnalysisContext, provider: AIProvider | None = None) -> AnalysisResult:
    try:
        provider = provider or get_provider()
        raw = provider.analyze(ctx)
    except AIServiceError:
        raise
    except Exception:
        log.exception("AI provider failed")
        raise AIServiceError(GENERIC_FAILURE)
    try:
        result = AnalysisResult.model_validate(raw)
    except (ValidationError, TypeError, ValueError):
        log.warning("AI provider returned malformed output")
        raise AIServiceError(GENERIC_FAILURE)
    result = _normalize(result)
    if not result.recommended_actions:  # structural failure, same message as Phase 2
        log.warning("AI provider returned no recommended actions")
        raise AIServiceError(GENERIC_FAILURE)
    try:
        return verify(result, ctx)
    except SafetyError as e:
        # Log only the reason code, never the model text.
        log.warning("AI output rejected by safety verification: %s", e.code)
        raise AIServiceError(SAFETY_FAILURE, "ai_unsafe_output")
