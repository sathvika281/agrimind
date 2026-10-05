"""Typed contracts and the shared LangGraph state for the agentic investigation.

Every agent returns one of these small Pydantic models (never a free-form dict), and the graph passes
them around in AgriMindState. Nothing here stores reasoning text: only structured evidence summaries,
decisions, confidence, uncertainty and tool outcomes.
"""
from typing import Literal, TypedDict

from pydantic import BaseModel, Field

from ...schemas import AnalysisResult


class Clarification(BaseModel):
    """Ask the farmer for the one thing that would let the investigation continue."""

    reason: Literal["no_evidence", "poor_image", "too_vague"]
    question: str
    options: list[str] = Field(default_factory=list)


class Plan(BaseModel):
    """Which specialists the investigation needs for THIS request, and why the others are skipped."""

    nodes: list[str] = Field(default_factory=list)
    skipped: dict[str, str] = Field(default_factory=dict)
    clarify: Clarification | None = None


class CropAnalysis(BaseModel):
    observations: list[str] = Field(default_factory=list)
    candidate_issues: list[str] = Field(default_factory=list)
    confidence: float = 0.0  # 0..1, derived from the stated uncertainty level
    image_quality: str = "not_provided"
    uncertainties: list[str] = Field(default_factory=list)
    additional_evidence_needed: list[str] = Field(default_factory=list)


class MemoryAnalysis(BaseModel):
    """What this farm's own history says. 'No history' is a real, reported answer (never invented)."""

    checks_on_farm: int = 0
    historical_matches: list[str] = Field(default_factory=list)
    recurring_patterns: list[str] = Field(default_factory=list)
    changes_since_previous_check: list[str] = Field(default_factory=list)
    supporting_history: list[str] = Field(default_factory=list)
    contradicting_history: list[str] = Field(default_factory=list)
    recent_activities: list[str] = Field(default_factory=list)  # diary kinds only
    history_confidence: float = 0.0
    matches_by_candidate: dict[str, int] = Field(default_factory=dict)  # candidate issue -> earlier checks of it


class EnvironmentAnalysis(BaseModel):
    weather_relevance: Literal["high", "medium", "low", "unknown"] = "unknown"
    relevant_conditions: list[str] = Field(default_factory=list)
    supporting_signals: list[str] = Field(default_factory=list)
    contradicting_signals: list[str] = Field(default_factory=list)
    environmental_uncertainties: list[str] = Field(default_factory=list)
    signals_by_candidate: dict[str, dict[str, list[str]]] = Field(default_factory=dict)  # candidate -> {supports, contradicts} weather kinds


class KnowledgeItem(BaseModel):
    id: str  # stable id of the chunk; the ONLY way a source can be attached to an answer
    source: str
    title: str
    institution: str
    url: str
    crop: str = ""
    topic: str = ""
    relevance: float = 0.0
    excerpt: str


class KnowledgeEvidence(BaseModel):
    retrieved_evidence: list[KnowledgeItem] = Field(default_factory=list)
    knowledge_gaps: list[str] = Field(default_factory=list)


class Decision(BaseModel):
    """What the decision-support step proposes. Mapped into the existing AnalysisResult by the graph."""

    verdict: str = ""
    what_may_be_happening: str = ""
    evidence_for: list[str] = Field(default_factory=list)
    evidence_against: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    what_to_verify: list[str] = Field(default_factory=list)
    what_to_monitor: list[str] = Field(default_factory=list)
    when_to_seek_help: str = ""
    cited_source_ids: list[str] = Field(default_factory=list)


class SafetyVerdict(BaseModel):
    safe: bool
    violations: list[str] = Field(default_factory=list)
    required_changes: list[str] = Field(default_factory=list)
    retry_required: bool = False


class AgentStep(BaseModel):
    """One line of the audit trail shown to the farmer: who ran, how it ended. No reasoning text."""

    agent: str
    status: Literal["ok", "skipped", "failed", "retry"]
    note: str = ""


class AgriMindState(TypedDict, total=False):
    ctx: object  # AnalysisContext (kept as 'object' so this module has no import cycle)
    language: str
    plan: Plan
    crop_analysis: CropAnalysis
    base_result: AnalysisResult  # the validated crop-analysis result (starting point for the final answer)
    memory_analysis: MemoryAnalysis
    environmental_analysis: EnvironmentAnalysis
    knowledge_evidence: KnowledgeEvidence
    decision: Decision
    candidate_result: AnalysisResult
    safety_result: SafetyVerdict
    retry_count: int
    required_changes: list[str]
    clarification: Clarification | None
    final_result: AnalysisResult
    steps: list[AgentStep]
    errors: list[str]
