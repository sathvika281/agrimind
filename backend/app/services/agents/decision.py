"""Agent 6: Decision Support. Weighs the evidence the other agents collected and proposes the farmer-facing answer.

The second (and last) model call. It receives only structured evidence, may cite a source ONLY by the id of a
chunk that was really retrieved, and its output is merged into the validated crop-analysis result: it cannot change
the likely issue, the severity or lower the stated uncertainty, and it cannot add a source that was not retrieved.
Without a model that supports it (demo provider) or when the call fails, the validated crop-analysis result is kept
as is and the step is reported as such: no invented text.
"""
import json
import logging

from ...schemas import AnalysisResult, SourceRef
from ..graph.state import (CropAnalysis, Decision, EnvironmentAnalysis, KnowledgeEvidence, MemoryAnalysis)

log = logging.getLogger("agrimind.agents")

_STR = {"type": "STRING"}
_LIST = {"type": "ARRAY", "items": _STR}
DECISION_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "verdict": _STR, "what_may_be_happening": _STR, "evidence_for": _LIST, "evidence_against": _LIST, "unknowns": _LIST,
        "what_to_verify": _LIST, "what_to_monitor": _LIST, "when_to_seek_help": _STR, "cited_source_ids": _LIST,
    },
    "required": ["verdict", "what_may_be_happening", "what_to_verify", "what_to_monitor", "when_to_seek_help"],
}

_RULES = (
    "RULES: Use ONLY the evidence below. Do not add agricultural facts that are not in it. Separate what is observed "
    "from what is only possible. If the evidence is weak, say so. Weather and history are context, never proof of a "
    "cause ('is consistent with', never 'caused by'). NEVER recommend any pesticide, chemical, product, dose, quantity "
    "or spray schedule, and no treatment plan: only what to verify, what to monitor and when to ask an expert. "
    "Write for a farmer: say 'your earlier checks' (never 'farm memory' or the names of internal steps). "
    "cited_source_ids may contain ONLY ids from RETRIEVED_SOURCES that you actually relied on; use [] if none."
)


def build_prompt(crop: str, symptoms: str, base: AnalysisResult, ca: CropAnalysis, mem: MemoryAnalysis | None,
                 env: EnvironmentAnalysis | None, kn: KnowledgeEvidence | None, rules: dict | None, required_changes: list[str]) -> str:
    ev = {
        "crop": crop, "farmer_description": symptoms[:600],
        "crop_analysis": ca.model_dump(),
        "assessment_so_far": {"likely_issue": base.likely_issue, "severity": base.severity, "uncertainty_level": base.uncertainty_level},
        "farm_memory": mem.model_dump() if mem else "not consulted",
        "environment": env.model_dump() if env else "not consulted",
        "RETRIEVED_SOURCES": [i.model_dump(include={"id", "title", "institution", "excerpt"}) for i in kn.retrieved_evidence] if kn else [],
        "rule_based_next_step_from_previous_checks": rules or "not available",
    }
    fix = f"\nYour previous answer was rejected. Fix exactly this: {'; '.join(required_changes)}\n" if required_changes else "\n"
    return f"{_RULES}{fix}\nEVIDENCE (JSON):\n{json.dumps(ev, ensure_ascii=False, default=str)[:9000]}"


def synthesize(provider, language: str, prompt: str) -> Decision:
    fn = getattr(provider, "synthesize", None)
    if fn is None:
        raise NotImplementedError("provider has no synthesis step")
    return Decision.model_validate(fn(prompt, DECISION_SCHEMA, language))


def apply(base: AnalysisResult, d: Decision | None, kn: KnowledgeEvidence | None) -> AnalysisResult:
    """Merge a decision into the validated crop-analysis result. Issue, severity and uncertainty come from `base`."""
    if d is None:
        return base
    cited = {i.id: i for i in (kn.retrieved_evidence if kn else [])}
    sources, seen = [], set()
    for sid in dict.fromkeys(d.cited_source_ids):
        c = cited.get(sid)
        if c is not None and c.url not in seen:  # several passages of one document are one source
            seen.add(c.url)
            sources.append(SourceRef(title=c.title, institution=c.institution, url=c.url, excerpt=c.excerpt))
    immediate = [x for x in d.what_to_verify if x.strip()] or base.immediate_actions
    monitoring = [x for x in d.what_to_monitor if x.strip()] or base.monitoring_steps
    return base.model_copy(update={
        "verdict": d.verdict.strip() or base.verdict,
        "explanation": d.what_may_be_happening.strip() or base.explanation,
        "evidence_for": [x for x in d.evidence_for if x.strip()] or base.evidence_for,
        "evidence_against": [x for x in d.evidence_against if x.strip()] or base.evidence_against,
        "unknowns": [x for x in d.unknowns if x.strip()] or base.unknowns,
        "immediate_actions": immediate,
        "monitoring_steps": monitoring,
        "recommended_actions": [*immediate, *monitoring],
        "when_to_seek_help": d.when_to_seek_help.strip() or base.when_to_seek_help,
        "sources": sources,
    })
