"""Farm Patterns: recurring relationships that are already present in this farm's own stored history.

Pure and deterministic: no I/O, no model call, no new storage, no forecasting, no causal claim. It reuses the
Phase 9 statistics (insights), the weather already stored WITH each check (through the existing weather thresholds)
and the farmer's own diary entries. A pattern is only reported with a count of the real checks behind it, and its label
(strong / possible / limited) comes from fixed rules, never from a score.

  enough=False  fewer than MIN_CHECKS stored checks: "not enough history to identify a reliable pattern"
"""
from collections import defaultdict
from datetime import date, timedelta

from .insights import build_insights, is_unclear, issue_key
from .weather_risk import weather_risks

MIN_CHECKS = 4
WINDOW = 6  # "N of the last 6 checks", the same window Phase 9 uses for recurrence
MIN_COINCIDENT = 2  # a weather/diary relationship needs at least two real checks
DIARY_DAYS = 7  # a diary entry counts as "before" a check if it is dated within this many days earlier
MAX_PATTERNS = 3
LABEL_RANK = {"strong": 0, "possible": 1, "limited": 2}


def _day(dt) -> date:
    return dt.date() if hasattr(dt, "date") else dt


def build_patterns(rows: list[dict], events: list[dict]) -> dict:
    """rows: this farm's stored checks (newest first or any order) as dicts with id, crop, created_at, likely_issue,
    severity, weather (the weather stored with the check, or None). events: diary entries with kind and event_date."""
    ordered = sorted(rows, key=lambda r: (r["created_at"], r["id"]), reverse=True)
    ins = build_insights(ordered)
    total = ins["total"]
    if total < MIN_CHECKS:
        return {"enough": False, "total": total, "patterns": []}

    recent = ordered[:WINDOW]
    recurring_keys = {issue_key(t["issue"]) for t in ins["trends"] if t["kind"] in ("recurring", "more_frequent")}
    by_key: dict[str, list[dict]] = defaultdict(list)
    for r in ordered:
        if not is_unclear(r["likely_issue"]):
            by_key[issue_key(r["likely_issue"])].append(r)

    patterns = []
    for key, checks in by_key.items():
        if len(checks) < 2:
            continue
        in_window = sum(1 for r in recent if issue_key(r["likely_issue"]) == key and not is_unclear(r["likely_issue"]))
        # weather that was stored with these checks (never fetched now), counted per risk kind
        with_wx = [r for r in checks if r.get("weather")]
        env = []
        if len(with_wx) >= MIN_COINCIDENT:
            kinds: dict[str, int] = defaultdict(int)
            for r in with_wx:
                for k in {x["kind"] for x in weather_risks(r["weather"])}:
                    kinds[k] += 1
            env = [{"kind": k, "count": n, "of": len(with_wx)} for k, n in sorted(kinds.items(), key=lambda kv: -kv[1]) if n >= MIN_COINCIDENT]
        # diary entries of the same kind shortly before these checks
        diary = []
        by_kind: dict[str, int] = defaultdict(int)
        for r in checks:
            d = _day(r["created_at"])
            seen = {e["kind"] for e in events if d - timedelta(days=DIARY_DAYS) <= e["event_date"] <= d}
            for k in seen:
                by_kind[k] += 1
        diary = [{"kind": k, "count": n, "of": len(checks)} for k, n in sorted(by_kind.items(), key=lambda kv: -kv[1]) if n >= MIN_COINCIDENT]

        recurring = key in recurring_keys
        context = bool(env or diary)
        label = "strong" if recurring and context else "possible" if (recurring or context) else "limited"
        patterns.append({
            "issue": checks[0]["likely_issue"], "count": in_window if in_window >= 2 else len(checks), "window": min(WINDOW, total) if in_window >= 2 else total,
            "label": label, "recurring": recurring, "environment": env, "diary": diary,
        })
    patterns.sort(key=lambda p: (LABEL_RANK[p["label"]], -p["count"]))
    return {"enough": True, "total": total, "patterns": patterns[:MAX_PATTERNS]}
