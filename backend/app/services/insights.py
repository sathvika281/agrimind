"""Farm history insights, derived ONLY from completed checks that AgriMind actually stored.

Pure functions (no I/O, no model call). Inputs per check: id, created_at, crop, likely_issue, severity.
Nothing here ever looks at sample telemetry or weather, and nothing is guessed: when a rule's minimum
amount of history isn't met, no trend is reported.

Honest limits (also shown to the farmer): the issue is free text written by the model in the language of the
check, so grouping is by normalised wording. Differently worded or differently languaged checks are counted
separately, which can UNDER-count a recurring problem but never invents one.
"""
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone

# History level by number of completed checks.
LEVEL_NONE, LEVEL_ONE, LEVEL_LIMITED, LEVEL_ENOUGH = "none", "one", "limited", "enough"
LIMITED_MAX = 3  # 2-3 checks: changes can be compared, recurring patterns are not reliable

RECURRING_WINDOW, RECURRING_MIN, RECURRING_MIN_DAYS = 6, 3, 2
FREQ_MIN_CHECKS, FREQ_MIN_DIFF = 6, 2
HIGH_WINDOW, HIGH_MIN = 5, 2
STABLE_RUN = 3
RECENT_LIMIT = 8
SEVERITIES = ("low", "medium", "high", "unknown")

_PAREN = re.compile(r"[(（\[].*?[)）\]]")
_FILLER = re.compile(r"\b(possible|possibly|probable|probably|likely|may be|might be|maybe|suspected)\b")
_PUNCT = re.compile(r"[^\wఀ-౿ ]+")
# A non-diagnosis (the model said it can't tell). It is NEVER counted as a recurring issue.
_UNCLEAR = re.compile(r"unable to|cannot determine|can't determine|not enough information|unclear|స్పష్టంగా చెప్పలేము|చెప్పలేము", re.I)


def issue_key(issue: str) -> str:
    s = (issue or "").lower()
    s = _PAREN.sub(" ", s)
    s = _FILLER.sub(" ", s)
    s = _PUNCT.sub(" ", s)
    return " ".join(s.split())


def is_unclear(issue: str) -> bool:
    return bool(_UNCLEAR.search(issue or "")) or not issue_key(issue)


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def level_for(total: int) -> str:
    if total <= 0:
        return LEVEL_NONE
    if total == 1:
        return LEVEL_ONE
    return LEVEL_LIMITED if total <= LIMITED_MAX else LEVEL_ENOUGH


def _sev(v) -> str:
    return v if v in SEVERITIES else "unknown"


def _ev(c: dict) -> dict:
    return {"analysis_id": c["id"], "at": c["at"]}


def _norm(rows) -> list[dict]:
    out = [
        {
            "id": r["id"],
            "at": _utc(r["created_at"]),
            "crop": (r.get("crop") or "").strip(),
            "issue": (r.get("likely_issue") or "").strip(),
            "key": issue_key(r.get("likely_issue") or ""),
            "unclear": is_unclear(r.get("likely_issue") or ""),
            "severity": _sev(r.get("severity")),
        }
        for r in rows
    ]
    out.sort(key=lambda c: (c["at"], c["id"]))  # chronological, whatever order the caller used
    return out


def _distinct_days(checks: list[dict]) -> int:
    return len({c["at"].date() for c in checks})


def _trends(checks: list[dict]) -> list[dict]:
    """Conservative rules. Each returns the exact checks that support it (evidence)."""
    trends: list[dict] = []
    n = len(checks)

    # recurring: the same (clear) issue in >=3 of the last 6 checks, on >=2 different days
    window = checks[-RECURRING_WINDOW:]
    by_key: dict[str, list[dict]] = defaultdict(list)
    for c in window:
        if not c["unclear"]:
            by_key[c["key"]].append(c)
    for key, hits in sorted(by_key.items(), key=lambda kv: -len(kv[1])):
        if len(hits) >= RECURRING_MIN and _distinct_days(hits) >= RECURRING_MIN_DAYS:
            trends.append({"kind": "recurring", "issue": hits[-1]["issue"], "count": len(hits), "window": len(window), "evidence": [_ev(c) for c in hits]})

    # more / less frequent: needs >=6 checks; later half vs earlier half
    if n >= FREQ_MIN_CHECKS:
        half = n // 2
        early, late = checks[:half], checks[n - half:]  # equal-sized halves (a middle check is left out if n is odd)
        keys = {c["key"] for c in checks if not c["unclear"]}
        for key in sorted(keys):
            e = [c for c in early if c["key"] == key and not c["unclear"]]
            l = [c for c in late if c["key"] == key and not c["unclear"]]
            diff = len(l) - len(e)
            if diff >= FREQ_MIN_DIFF or -diff >= FREQ_MIN_DIFF:
                kind = "more_frequent" if diff > 0 else "less_frequent"
                last = (l or e)[-1]
                trends.append({"kind": kind, "issue": last["issue"], "count": len(l), "earlier_count": len(e), "window": half, "evidence": [_ev(c) for c in (e + l)]})

    # repeated high severity: REAL "high" ratings only ("unknown" is never treated as high)
    recent = checks[-HIGH_WINDOW:]
    highs = [c for c in recent if c["severity"] == "high"]
    if len(highs) >= HIGH_MIN:
        trends.append({"kind": "repeated_high", "issue": highs[-1]["issue"], "count": len(highs), "window": len(recent), "evidence": [_ev(c) for c in highs]})

    # stable: the last 3 checks share the same clear issue AND the same severity
    last3 = checks[-STABLE_RUN:]
    if len(last3) == STABLE_RUN and all(not c["unclear"] for c in last3) and len({c["key"] for c in last3}) == 1 and len({c["severity"] for c in last3}) == 1:
        trends.append({"kind": "stable", "issue": last3[-1]["issue"], "count": STABLE_RUN, "window": STABLE_RUN, "severity": last3[-1]["severity"], "evidence": [_ev(c) for c in last3]})
    return trends


def _comparison(checks: list[dict]) -> dict | None:
    if len(checks) < 2:
        return None
    prev, last = checks[-2], checks[-1]

    def brief(c):
        return {"analysis_id": c["id"], "at": c["at"], "crop": c["crop"], "issue": c["issue"], "severity": c["severity"]}

    both_clear = not prev["unclear"] and not last["unclear"]
    return {
        "previous": brief(prev),
        "latest": brief(last),
        "same_issue": both_clear and prev["key"] == last["key"],
        "comparable": both_clear,  # an unclear check can't be compared by issue
        "same_crop": prev["crop"].lower() == last["crop"].lower(),
        "severity_changed": prev["severity"] != last["severity"],
    }


def build_insights(rows) -> dict:
    checks = _norm(rows)
    total = len(checks)
    sev = Counter(c["severity"] for c in checks)
    groups: dict[str, list[dict]] = defaultdict(list)
    for c in checks:
        if not c["unclear"]:
            groups[c["key"]].append(c)
    issues = [
        {"label": hits[-1]["issue"], "count": len(hits), "last_seen": hits[-1]["at"], "evidence": [_ev(c) for c in hits]}
        for hits in groups.values()
    ]
    issues.sort(key=lambda g: (-g["count"], -g["last_seen"].timestamp()))
    latest = checks[-1] if checks else None
    return {
        "level": level_for(total),
        "total": total,
        "first_at": checks[0]["at"] if checks else None,
        "last_at": latest["at"] if latest else None,
        "latest": None if latest is None else {"analysis_id": latest["id"], "at": latest["at"], "crop": latest["crop"], "issue": latest["issue"], "severity": latest["severity"]},
        "severity_counts": {k: sev.get(k, 0) for k in SEVERITIES},
        "unclear_count": sum(1 for c in checks if c["unclear"]),
        "issues": issues,
        "recent": [
            {"analysis_id": c["id"], "at": c["at"], "crop": c["crop"], "issue": c["issue"], "severity": c["severity"]}
            for c in reversed(checks[-RECENT_LIMIT:])
        ],
        # Trends are only claimed with enough history; below that the level itself is the (honest) answer.
        "trends": _trends(checks) if total > LIMITED_MAX else [],
        "comparison": _comparison(checks),
    }
