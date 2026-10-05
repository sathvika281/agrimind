"""Agent 3: Farm Memory. What THIS farm's own history says about the current problem.

Deterministic: it reads the owner-bound toolbox (stored checks, the existing Phase 9 insights, the farmer's diary
kinds, the earlier check of a follow-up) and compares. 'No history' is a real answer; nothing is invented. Past
checks are historical OBSERVATIONS, never verified diagnoses, and the wording keeps that distinction.
"""
from ..graph.state import CropAnalysis, MemoryAnalysis
from ..insights import is_unclear, issue_key
from .toolbox import AgentToolbox


def _same_issue(a: str, b: str) -> bool:
    ka, kb = set(issue_key(a).split()), set(issue_key(b).split())
    if not ka or not kb or is_unclear(a) or is_unclear(b):
        return False
    return len(ka & kb) / min(len(ka), len(kb)) >= 0.6


def run(tb: AgentToolbox, crop: str, analysis: CropAnalysis, base_change_status: str | None = None) -> MemoryAnalysis:
    rows = [r for r in tb.recent_checks() if r["crop"].strip().lower() == crop.strip().lower()]
    out = MemoryAnalysis(checks_on_farm=len(rows), recent_activities=[f"{d.kind} ({d.date})" for d in tb.diary()])

    candidates = analysis.candidate_issues
    for r in rows:
        when = r["created_at"].date().isoformat() if r["created_at"] else "earlier"
        issue = r["likely_issue"]
        if any(_same_issue(issue, c) for c in candidates):
            out.historical_matches.append(f"{when}: {issue} (severity {r['severity'] or 'unknown'})")
        elif issue and not is_unclear(issue):
            out.contradicting_history.append(f"{when}: a different issue was noted ({issue})")
    out.contradicting_history = out.contradicting_history[:3]
    out.supporting_history = list(out.historical_matches[:3])

    for t in tb.farm_insights().get("trends", []):
        if t["kind"] in ("recurring", "repeated_high", "more_frequent") and any(_same_issue(t["issue"], c) for c in candidates):
            out.recurring_patterns.append(f"{t['kind']}: {t['issue']} ({t['count']} of {t['window']} recent checks)")

    prev = tb.previous_check()
    if prev is not None:
        match = any(_same_issue(prev.likely_issue, c) for c in candidates)
        out.changes_since_previous_check.append(
            f"previous check {prev.date}: {prev.likely_issue} (severity {prev.severity}); the issue now looks "
            + ("similar" if match else "different or unclear")
        )
        if base_change_status in ("better", "same", "worse"):
            out.changes_since_previous_check.append(f"the new check compared with the earlier one: {base_change_status}")

    out.history_confidence = round(min(1.0, len(rows) / 6), 2) if rows else 0.0
    return out
