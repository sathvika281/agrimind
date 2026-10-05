"""Investigation Dossier: what the investigation really looked at, why it reached its assessment, what is still unknown,
what would help verify it, and the competing explanations. Pure and deterministic: it only SUMMARISES the structured
outputs the agents already produced (no model call, no I/O, no reasoning text, no scores or percentages).

Everything is returned as language-neutral coded facts (`Fact`); the frontend words them in English/Telugu. A source
that was not used is reported as not used; nothing is ever invented to fill a section.
"""
import re

from ...schemas import AnalysisResult, Dossier, Fact, HypothesisOut
from ..insights import is_unclear
from .state import CropAnalysis, EnvironmentAnalysis, KnowledgeEvidence, MemoryAnalysis

MAX_WHY = 4
MAX_HYPOTHESES = 3
_TOKEN = re.compile(r"[a-z]{4,}")
_CONTEXT_FIELDS = ("soil_type", "location", "primary_crop", "irrigation_method", "season", "planting_date")


def _tokens(text: str) -> set[str]:
    return set(_TOKEN.findall((text or "").lower()))


def _knowledge_hits(kn: KnowledgeEvidence | None, label: str) -> int:
    """How many retrieved passages actually mention words of this explanation (>= 2 shared words)."""
    if not kn:
        return 0
    want = _tokens(label)
    return sum(1 for i in kn.retrieved_evidence if len(want & _tokens(i.excerpt + " " + i.title)) >= 2)


def build(*, base: AnalysisResult, final: AnalysisResult, crop_analysis: CropAnalysis, memory: MemoryAnalysis | None,
          env: EnvironmentAnalysis | None, knowledge: KnowledgeEvidence | None, farm_context: dict, has_image: bool,
          has_weather: bool) -> Dossier:
    d = Dossier()
    poor_image = has_image and base.image_quality in ("poor", "limited")
    ctx_present = [f for f in _CONTEXT_FIELDS if farm_context.get(f)]
    retrieved = len(knowledge.retrieved_evidence) if knowledge else 0

    # ---- what was considered (a source that was not used says so) ----
    d.evidence = [
        Fact(kind="observation", used=True, count=len(crop_analysis.observations)),
        Fact(kind="history", used=bool(memory and memory.checks_on_farm), count=memory.checks_on_farm if memory else 0),
        Fact(kind="weather", used=env is not None, detail=env.weather_relevance if env else ("no_weather" if not has_weather else "")),
        Fact(kind="knowledge", used=retrieved > 0, count=retrieved),
        Fact(kind="farm_context", used=bool(ctx_present), count=len(ctx_present)),
        Fact(kind="diary", used=bool(memory and memory.recent_activities), count=len(memory.recent_activities) if memory else 0),
    ]

    # ---- why this conclusion: only true, concise factors ----
    why: list[Fact] = []
    if crop_analysis.observations:
        why.append(Fact(kind="observation_matches", count=len(crop_analysis.observations)))
    if memory and memory.historical_matches:
        why.append(Fact(kind="history_similar", count=len(memory.historical_matches)))
    if memory and memory.recurring_patterns:
        why.append(Fact(kind="recurring_pattern", count=len(memory.recurring_patterns)))
    if env and env.supporting_signals:
        why.append(Fact(kind="weather_consistent", detail=",".join(env.relevant_conditions)))
    if retrieved:
        why.append(Fact(kind="knowledge_describes", count=len(final.sources) or retrieved))
    d.why = why[:MAX_WHY]

    # ---- what is still unknown ----
    unk: list[Fact] = []
    if not (memory and memory.historical_matches):
        unk.append(Fact(kind="no_similar_history"))
    if not has_weather:
        unk.append(Fact(kind="no_weather"))
    if poor_image:
        unk.append(Fact(kind="image_insufficient"))
    if not farm_context.get("soil_type"):
        unk.append(Fact(kind="soil_missing"))
    if not farm_context.get("planting_date"):
        unk.append(Fact(kind="planting_date_missing"))
    if retrieved == 0:
        unk.append(Fact(kind="no_guidance_found" if knowledge is not None and "no_knowledge_base" not in knowledge.knowledge_gaps else "no_knowledge_base"))
    d.unknown = unk

    # ---- what would help verify ----
    ver: list[Fact] = []
    if not has_image:
        ver.append(Fact(kind="add_photo"))
    elif poor_image:
        ver.append(Fact(kind="clearer_photo"))
    ver.append(Fact(kind="compare_nearby_plants"))
    ver.append(Fact(kind="recheck_later"))
    d.verify = ver

    # ---- competing explanations (from the Crop Analysis candidates; none for an unclear/no-diagnosis result) ----
    if not is_unclear(base.likely_issue):
        alts = {a.possibility.strip().lower(): a.how_to_tell for a in base.possible_alternatives}
        for i, label in enumerate(crop_analysis.candidate_issues[:MAX_HYPOTHESES]):
            sup: list[Fact] = []
            gap: list[Fact] = []
            if i == 0 and crop_analysis.observations:
                sup.append(Fact(kind="current_observation"))
            m = memory.matches_by_candidate.get(label, 0) if memory else 0
            if m:
                sup.append(Fact(kind="history_match", count=m))
            elif memory is not None:
                gap.append(Fact(kind="no_history_match"))
            sig = (env.signals_by_candidate.get(label) if env else None) or {}
            if sig.get("supports"):
                sup.append(Fact(kind="weather_consistent", detail=",".join(sig["supports"])))
            if sig.get("contradicts"):
                gap.append(Fact(kind="weather_less_likely", detail=",".join(sig["contradicts"])))
            k = _knowledge_hits(knowledge, label)
            if k:
                sup.append(Fact(kind="guidance_describes", count=k))
            elif retrieved:
                gap.append(Fact(kind="no_guidance_match"))
            if poor_image:
                gap.append(Fact(kind="image_limited"))
            d.hypotheses.append(HypothesisOut(
                label=label, rank="better_supported" if i == 0 else "also_possible", supporting=sup, against_or_unknown=gap,
                how_to_tell=alts.get(label.strip().lower(), ""),
            ))
    return d
