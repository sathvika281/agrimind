"""The LangGraph that runs the agentic investigation.

    investigate -> (clarify | crop_analysis -> [farm_memory] -> [environment] -> [knowledge] -> decision -> safety)
    safety -> finalize (safe)  |  decision again (unsafe, at most MAX_RETRIES)  |  fallback to the verified crop analysis

Which specialists run is decided by the Investigation plan; skipped ones are recorded as skipped, never faked.
Bounded everywhere: clarification rounds, safety retries, and every optional specialist is failure-tolerant.
Crop analysis failing, or the safety gate itself failing, ends the run with the same user-safe errors as the legacy
pipeline (fail closed: nothing unverified is returned).
"""
import logging
import time
from dataclasses import dataclass

from langgraph.graph import END, START, StateGraph

from ...schemas import AgentStepOut, AnalysisResult
from ..agents import crop_analysis, decision, environment, farm_memory, investigation, knowledge, safety_agent
from ..agents.toolbox import AgentToolbox
from ..ai.base import AIProvider, AIServiceError, AnalysisContext
from ..ai.safety import SafetyError, verify
from ..ai.service import GENERIC_FAILURE, SAFETY_FAILURE
from ..rag.retrieval import Index
from .state import AgentStep, AgriMindState, KnowledgeEvidence

log = logging.getLogger("agrimind.agents")

MAX_RETRIES = 2  # safety-triggered rewrites of the decision before falling back
_ORDER = ["farm_memory", "environment", "knowledge"]


@dataclass
class Runtime:
    ctx: AnalysisContext
    provider: AIProvider
    toolbox: AgentToolbox
    index: Index
    farm_id: int = 0
    clarification_round: int = 0


def _step(state: AgriMindState, agent: str, status: str, note: str = "") -> list[AgentStep]:
    return [*state.get("steps", []), AgentStep(agent=agent, status=status, note=note)]


def _timed(rt: Runtime, agent: str, t0: float, status: str) -> None:
    log.info("agent_done agent=%s status=%s duration_ms=%.0f farm_id=%s", agent, status, (time.perf_counter() - t0) * 1000, rt.farm_id)


def _next(state: AgriMindState, after: str) -> str:
    """The next planned specialist after `after`, else the decision step."""
    plan = state["plan"]
    order = ["crop_analysis", *_ORDER]
    for n in order[order.index(after) + 1:]:
        if n in plan.nodes:
            return n
    return "decision"


def _with_steps(r: AnalysisResult, steps: list[AgentStep]) -> AnalysisResult:
    return r.model_copy(update={"agent_steps": [AgentStepOut(agent=s.agent, status=s.status, note=s.note) for s in steps]})


def build(rt: Runtime):
    ctx = rt.ctx

    def investigate(state: AgriMindState):
        t0 = time.perf_counter()
        has_history = bool(ctx.history)
        p = investigation.plan(ctx, has_history=has_history, knowledge_available=len(rt.index) > 0, clarification_round=rt.clarification_round)
        _timed(rt, "investigation", t0, "ok")
        steps = _step(state, "investigation", "ok", "clarify" if p.clarify else "planned")
        for n, why in p.skipped.items():
            steps = [*steps, AgentStep(agent=n, status="skipped", note=why)]
        return {"plan": p, "clarification": p.clarify, "steps": steps}

    def route_after_investigate(state: AgriMindState):
        return "clarify" if state["plan"].clarify else "crop_analysis"

    def crop_node(state: AgriMindState):
        t0 = time.perf_counter()
        result, ca = crop_analysis.run(ctx, rt.provider)  # failure here ends the run (same errors as the legacy pipeline)
        _timed(rt, "crop_analysis", t0, "ok")
        out = {"base_result": result, "crop_analysis": ca, "steps": _step(state, "crop_analysis", "ok")}
        c = investigation.image_needs_replacing(ctx, ca.image_quality, rt.clarification_round)
        if c:
            out["clarification"] = c
        return out

    def route_after_crop(state: AgriMindState):
        return "clarify" if state.get("clarification") else _next(state, "crop_analysis")

    def memory_node(state: AgriMindState):
        t0 = time.perf_counter()
        try:
            m = farm_memory.run(rt.toolbox, ctx.crop, state["crop_analysis"], state["base_result"].change.status if state["base_result"].change else None)
            _timed(rt, "farm_memory", t0, "ok")
            return {"memory_analysis": m, "steps": _step(state, "farm_memory", "ok", f"matches:{len(m.historical_matches)}")}
        except Exception:  # noqa: BLE001
            log.exception("farm_memory failed")
            return {"steps": _step(state, "farm_memory", "failed")}

    def environment_node(state: AgriMindState):
        t0 = time.perf_counter()
        try:
            e = environment.run(rt.toolbox.weather(), state["crop_analysis"], rt.toolbox.farm_context().get("planting_date"))
            _timed(rt, "environment", t0, "ok")
            return {"environmental_analysis": e, "steps": _step(state, "environment", "ok", f"relevance:{e.weather_relevance}")}
        except Exception:  # noqa: BLE001
            log.exception("environment failed")
            return {"steps": _step(state, "environment", "failed")}

    def knowledge_node(state: AgriMindState):
        t0 = time.perf_counter()
        try:
            k = knowledge.run(rt.index, ctx.crop, ctx.symptoms, state["crop_analysis"])
            _timed(rt, "knowledge", t0, "ok")
            return {"knowledge_evidence": k, "steps": _step(state, "knowledge", "ok", f"sources:{len(k.retrieved_evidence)}")}
        except Exception:  # noqa: BLE001
            log.exception("knowledge retrieval failed")
            return {"knowledge_evidence": KnowledgeEvidence(knowledge_gaps=["retrieval_failed"]), "steps": _step(state, "knowledge", "failed")}

    def decision_node(state: AgriMindState):
        t0 = time.perf_counter()
        base, retry = state["base_result"], state.get("retry_count", 0)
        kn = state.get("knowledge_evidence")
        d = None
        status, note = "ok", ""
        if hasattr(rt.provider, "synthesize"):
            try:
                try:
                    rules = {k: v for k, v in rt.toolbox.decision_support().items() if k in ("state", "actions", "limitations")}
                except Exception:  # noqa: BLE001
                    rules = None
                prompt = decision.build_prompt(ctx.crop, ctx.symptoms, base, state["crop_analysis"], state.get("memory_analysis"),
                                               state.get("environmental_analysis"), kn, rules, state.get("required_changes", []))
                d = decision.synthesize(rt.provider, ctx.language, prompt)
            except Exception as e:  # noqa: BLE001
                log.warning("decision synthesis failed type=%s", type(e).__name__)
                status, note = "failed", "kept_crop_analysis"
        else:
            status, note = "ok", "no_synthesis_provider"
        cand = decision.apply(base, d, kn)
        _timed(rt, "decision_support", t0, status)
        return {"decision": d, "candidate_result": cand, "steps": _step(state, "decision_support", status if retry == 0 else "retry", note)}

    def safety_node(state: AgriMindState):
        t0 = time.perf_counter()
        kn = state.get("knowledge_evidence")
        urls = {i.url for i in kn.retrieved_evidence} if kn else set()
        try:
            verdict, verified = safety_agent.check(state["candidate_result"], state["base_result"], ctx, urls)
        except Exception:  # noqa: BLE001
            log.exception("safety agent failed: failing closed")
            raise AIServiceError(SAFETY_FAILURE, "ai_unsafe_output")
        _timed(rt, "safety", t0, "ok" if verdict.safe else "retry")
        out = {"safety_result": verdict, "required_changes": verdict.required_changes}
        if verdict.safe:
            out.update(final_result=verified, steps=_step(state, "safety", "ok"))
        else:
            log.warning("agent_safety_rejected violations=%s retry=%s", ",".join(verdict.violations), state.get("retry_count", 0))
            out.update(steps=_step(state, "safety", "retry", ",".join(verdict.violations)[:120]), retry_count=state.get("retry_count", 0) + 1)
        return out

    def route_after_safety(state: AgriMindState):
        if state["safety_result"].safe:
            return "finalize"
        can_retry = state.get("retry_count", 0) <= MAX_RETRIES and state.get("decision") is not None
        return "decision" if can_retry else "fallback"

    def fallback_node(state: AgriMindState):
        """The rewritten answer kept failing the gate: return the crop analysis itself, if IT passes the existing verifier."""
        try:
            safe = verify(state["base_result"], ctx)
        except SafetyError as e:
            log.warning("agent_fallback_unsafe code=%s", e.code)
            raise AIServiceError(SAFETY_FAILURE, "ai_unsafe_output")
        return {"final_result": safe, "steps": _step(state, "safety", "ok", "fallback_to_crop_analysis")}

    def clarify_node(state: AgriMindState):
        c = state["clarification"]
        try:
            res = verify(investigation.clarification_result(ctx, c), ctx)
        except SafetyError:
            raise AIServiceError(GENERIC_FAILURE)
        return {"final_result": res, "steps": _step(state, "investigation", "ok", f"clarification:{c.reason}")}

    def finalize_node(state: AgriMindState):
        return {"final_result": _with_steps(state["final_result"], state["steps"])}

    g = StateGraph(AgriMindState)
    for name, fn in [("investigate", investigate), ("crop_analysis", crop_node), ("farm_memory", memory_node), ("environment", environment_node),
                     ("knowledge", knowledge_node), ("decision", decision_node), ("safety", safety_node), ("fallback", fallback_node),
                     ("clarify", clarify_node), ("finalize", finalize_node)]:
        g.add_node(name, fn)
    g.add_edge(START, "investigate")
    g.add_conditional_edges("investigate", route_after_investigate, ["clarify", "crop_analysis"])
    g.add_conditional_edges("crop_analysis", route_after_crop, ["clarify", "farm_memory", "environment", "knowledge", "decision"])
    for n in _ORDER:
        g.add_conditional_edges(n, (lambda after: (lambda s: _next(s, after)))(n), [x for x in _ORDER if x != n] + ["decision"])
    g.add_edge("decision", "safety")
    g.add_conditional_edges("safety", route_after_safety, ["finalize", "decision", "fallback"])
    g.add_edge("fallback", "finalize")
    g.add_edge("clarify", "finalize")
    g.add_edge("finalize", END)
    return g.compile()


def run(rt: Runtime) -> AnalysisResult:
    out = build(rt).invoke({"steps": [], "retry_count": 0, "required_changes": []}, {"recursion_limit": 40})
    return out["final_result"]
