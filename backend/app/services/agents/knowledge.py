"""Agent 5: Agricultural Knowledge (RAG). Retrieves cited passages from the local trusted corpus.

Deterministic retrieval (BM25 + crop filter, see services/rag). It returns EVIDENCE with full source metadata; it
never writes a diagnosis and never creates a source: every item comes from a stored chunk of an included source.
"""
from urllib.parse import urlparse

from ..graph.state import CropAnalysis, KnowledgeEvidence, KnowledgeItem
from ..rag.retrieval import Index

EXCERPT_CHARS = 450
TOP_K = 4


def display_title(title: str, crop: str, topic: str, url: str) -> str:
    """Page titles are often generic ("ORGANIC FARMING :: Home") or a URL: show crop and topic instead."""
    t = (title or "").strip()
    if t and "::" not in t and not t.lower().startswith("http") and len(t) >= 8 and t.lower() not in ("crop protection", "nutrient management"):
        return t
    label = f"{crop.title() if crop else 'General'}: {topic}" if topic else (crop.title() or urlparse(url).path.rsplit("/", 1)[-1])
    return label[:90]


def run(index: Index, crop: str, symptoms: str, analysis: CropAnalysis) -> KnowledgeEvidence:
    if len(index) == 0:
        return KnowledgeEvidence(knowledge_gaps=["no_knowledge_base"])
    query = " ".join([crop, symptoms, *analysis.candidate_issues, *analysis.observations])
    hits = index.search(query, crop=crop, k=TOP_K)
    if not hits:
        return KnowledgeEvidence(knowledge_gaps=["nothing_relevant_found"])
    return KnowledgeEvidence(retrieved_evidence=[
        KnowledgeItem(
            id=c.id, source=urlparse(c.source_url).hostname or c.source_url, title=display_title(c.title, c.crop, c.topic, c.source_url), institution=c.institution, url=c.source_url,
            crop=c.crop, topic=c.topic, relevance=round(s / (s + 6.0), 2), excerpt=c.text[:EXCERPT_CHARS],
        )
        for c, s in hits
    ])
