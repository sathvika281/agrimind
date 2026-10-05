"""Entry point of the agentic investigation, beside (never instead of) the legacy ai.analyze().

    legacy:   ai.analyze(ctx)                       one model call -> validate -> safety.verify
    agentic:  agentic_analyze_check(ctx, toolbox)   LangGraph of specialists -> decision -> safety gate

Selected per request by settings.agentic_analysis_enabled (AGENTIC_ANALYSIS_ENABLED, default false). Returns the
same AnalysisResult the legacy path returns (plus optional sources / agent_steps) and raises the same AIServiceError.
"""
import logging

from ..schemas import AnalysisResult
from .agents.toolbox import AgentToolbox
from .ai.base import AIProvider, AIServiceError, AnalysisContext
from .ai import service as ai_service
from .ai.service import GENERIC_FAILURE
from .graph.workflow import Runtime, run
from .rag.retrieval import Index, get_index

log = logging.getLogger("agrimind.agents")


def agentic_analyze_check(
    ctx: AnalysisContext, toolbox: AgentToolbox, provider: AIProvider | None = None, index: Index | None = None,
    clarification_round: int = 0, farm_id: int = 0,
) -> AnalysisResult:
    try:
        provider = provider or ai_service.get_provider()  # looked up per call so tests/tools can swap it, like the legacy path
        if index is None:
            try:
                index = get_index()
            except Exception:  # noqa: BLE001  (a broken corpus is "no knowledge base", never a failed check)
                log.exception("knowledge index unavailable")
                index = Index([])
        log.info("investigation_started farm_id=%s input=%s", farm_id, ctx.input_type)
        result = run(Runtime(ctx=ctx, provider=provider, toolbox=toolbox, index=index, farm_id=farm_id, clarification_round=clarification_round))
        log.info("final_response farm_id=%s steps=%s sources=%s", farm_id, len(result.agent_steps), len(result.sources))
        return result
    except AIServiceError:
        raise
    except Exception:  # noqa: BLE001
        log.exception("agentic investigation failed")
        raise AIServiceError(GENERIC_FAILURE)
