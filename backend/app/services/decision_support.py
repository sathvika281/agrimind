"""Rule-based decision support: evidence -> interpretation -> a CONSERVATIVE next step.

Deterministic and read-only: no model call, no randomness, no I/O. Identical input always gives identical output.
It returns KEYS and structured facts; the wording lives in the frontend dictionaries (English + Telugu).

Evidence boundary - the ONLY inputs:
  * the target check: issue, severity, uncertainty level, image quality, crop, input type, date
  * the Phase 9 history of this farm's checks up to and including the target (services/insights.py, same thresholds)
  * farmer-recorded Phase 10 context: crop, irrigation, season, planting date, soil, location
NEVER used: farm notes, sample telemetry, weather, the model-written action text, or anything inferred.
Missing information stays missing (it is reported as a limitation, never replaced by a guess).

The action catalogue is CLOSED: observation / verification actions only. There is no treatment, chemical,
fertiliser, irrigation-quantity, dosage, spraying or scheduling action anywhere in this module.
"""
from .insights import LIMITED_MAX, _utc, build_insights, is_unclear, issue_key

# ---- states (priority order: none -> expert -> verify -> monitor) ----
NONE, EXPERT, VERIFY, MONITOR = "no_actionable_evidence", "seek_expert_help", "verify", "monitor"

# ---- the closed action catalogue ----
ACTIONS = ("inspect_plants", "compare_plants", "check_spread", "record_clearer_photo", "recheck_if_changes", "consult_expert", "add_detail")
MAX_ACTIONS = 2

# ---- limitation keys, in display priority ----
# no_treatment is UNIVERSAL: present in every state, including "no actionable evidence".
LIMITATIONS = ("no_treatment", "severity_not_recorded", "history_insufficient", "no_farm_context", "context_not_causal")

EXPERT_REASONS = ("severity_high", "repeated_high", "recurring", "more_frequent")
HISTORY_ENOUGH = LIMITED_MAX + 1  # Phase 9: trends need at least 4 stored checks


def _context(farm: dict) -> list[dict]:
    """Only what the farmer actually provided. Notes are deliberately not an input here."""
    out = []
    for field in ("primary_crop", "irrigation_method", "season", "planting_date", "soil_type", "location"):
        v = farm.get(field)
        if v not in (None, ""):
            out.append({"field": field, "value": v.isoformat() if hasattr(v, "isoformat") else str(v)})
    return out


def _expert_reason(target_key: str, severity: str, trends: list[dict]) -> str | None:
    if severity == "high":  # a REAL rating only; "unknown" never counts
        return "severity_high"
    if any(t["kind"] == "repeated_high" for t in trends):
        return "repeated_high"
    for kind in ("recurring", "more_frequent"):
        if any(t["kind"] == kind and issue_key(t["issue"]) == target_key for t in trends):  # the SAME issue as this check
            return kind
    return None


def decide(rows: list[dict], farm: dict, target_id: int | None = None) -> dict:
    """rows: this farm's stored checks (any order) as dicts with id, crop, created_at, likely_issue, severity,
    uncertainty_level, image_quality, input_type. If target_id is given the decision is "as of" that check: only
    checks with id <= target_id are considered, so later checks can never influence an earlier decision."""
    if target_id is not None:
        rows = [r for r in rows if r["id"] <= target_id]
    insights = build_insights(rows)
    total = insights["total"]
    context = _context(farm)

    target = None
    if rows:
        target = next((r for r in rows if r["id"] == target_id), None) if target_id is not None else None
        if target is None:
            latest_id = insights["latest"]["analysis_id"]
            target = next(r for r in rows if r["id"] == latest_id)

    base = {
        "level": insights["level"],
        "history_total": total,
        "context": context,
        "analysis_id": target["id"] if target else None,
        "observed": None,
        "evidence": [],
        "actions": [],
        "expert_reason": None,
    }

    limitations = ["no_treatment"]  # universal safety boundary: every state, no exceptions

    def finish(state: str, actions: list[str]) -> dict:
        assert all(a in ACTIONS for a in actions)  # the catalogue is closed
        if target is not None and total < HISTORY_ENOUGH:
            limitations.append("history_insufficient")
        if not context:
            limitations.append("no_farm_context")
        else:
            limitations.append("context_not_causal")
        ordered = [k for k in LIMITATIONS if k in limitations]
        return {**base, "state": state, "actions": actions[:MAX_ACTIONS], "limitations": ordered}

    if target is None:
        return finish(NONE, [])

    issue = (target.get("likely_issue") or "").strip()
    severity = target.get("severity") if target.get("severity") in ("low", "medium", "high") else "unknown"
    uncertainty = target.get("uncertainty_level") or "unknown"
    quality = target.get("image_quality") or "not_provided"
    unclear = is_unclear(issue)
    key = issue_key(issue)
    base["observed"] = {
        "analysis_id": target["id"], "crop": (target.get("crop") or "").strip(), "issue": issue, "unclear": unclear,
        "severity": severity, "uncertainty": uncertainty, "image_quality": quality,
        "input_type": target.get("input_type") or "text", "checked_at": _utc(target["created_at"]),
    }

    evidence = [{"kind": "this_check", "value": "unclear" if unclear else "issue"}]
    evidence.append({"kind": "severity", "value": severity if severity != "unknown" else "not_recorded"})
    if severity == "unknown" and not unclear:
        limitations.append("severity_not_recorded")
    group = next((g for g in insights["issues"] if issue_key(g["label"]) == key), None) if not unclear else None
    if group and group["count"] >= 2:
        evidence.append({"kind": "history_same_issue", "count": group["count"], "dates": group["evidence"]})
    else:
        evidence.append({"kind": "history_insufficient" if total < 2 else "history_isolated", "count": total})
    for t in insights["trends"]:
        if t["kind"] in ("repeated_high",) or issue_key(t["issue"]) == key:
            evidence.append({"kind": "trend", "value": t["kind"], "count": t["count"], "window": t["window"], "dates": t["evidence"]})
    base["evidence"] = evidence

    if unclear:
        return finish(NONE, ["add_detail"])

    reason = _expert_reason(key, severity, insights["trends"])
    if reason:
        base["expert_reason"] = reason
        return finish(EXPERT, ["consult_expert", "check_spread"])

    if severity == "low":
        return finish(MONITOR, ["recheck_if_changes", "check_spread"])

    # medium or unknown severity with a clear issue: confirm it first
    if quality in ("poor", "limited"):
        second = "record_clearer_photo"
    elif uncertainty == "high":
        second = "compare_plants"
    else:
        second = "check_spread"
    return finish(VERIFY, ["inspect_plants", second])

