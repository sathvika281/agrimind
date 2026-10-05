"""Crop Journey and Before-vs-Now. Pure and deterministic: no I/O, no model call, no new storage.

It only re-reads what AgriMind already stored (checks, diary events, the farm's planting date) and compares two
stored results with explicit rules. Everything is qualitative: no percentages, no symptom scores, no growth stages,
and no direction unless the stored evidence supports one ("unclear" is a normal answer).
"""
import re
from datetime import date, datetime, timezone

from .insights import is_unclear, issue_key

MAX_ITEMS = 30
SEV = {"unknown": 0, "low": 1, "medium": 2, "high": 3}
UNC = {"low": 0, "some": 1, "high": 2}  # higher = less sure
_TOKEN = re.compile(r"[a-zఀ-౿]{4,}")
OBS_MATCH = 0.4  # token overlap (Jaccard) for two observation texts to count as the same observation
OBS_LIMIT = 4


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _real_sev(v) -> str | None:
    return v if v in ("low", "medium", "high") else None


def _real_unc(v) -> str | None:
    return v if v in UNC else None


# ------------------------------------------------------------------------------------------------ journey
def build_journey(checks: list[dict], events: list[dict], planting_date: date | None, today: date) -> dict:
    """checks: id, crop, created_at, result_json, link_kind. events: id, kind, event_date. Chronological, newest kept."""
    items = []
    for c in checks:
        res = c.get("result_json") or {}
        issue = str(res.get("likely_issue", ""))
        items.append({
            "type": "check", "at": _utc(c["created_at"]), "analysis_id": c["id"], "crop": c["crop"], "issue": issue,
            "unclear": is_unclear(issue), "severity": _real_sev(res.get("severity")) or "unknown",
            "uncertainty_level": _real_unc(res.get("uncertainty_level")) or "unknown", "link": c.get("link_kind"),
        })
    for e in events:
        d = e["event_date"]
        items.append({"type": "diary", "at": datetime(d.year, d.month, d.day, tzinfo=timezone.utc), "kind": e["kind"], "event_id": e["id"]})
    items.sort(key=lambda x: (x["at"], 0 if x["type"] == "diary" else 1))
    truncated = len(items) > MAX_ITEMS
    items = items[-MAX_ITEMS:]
    days = (today - planting_date).days if planting_date and planting_date <= today else None
    return {"planting_date": planting_date, "days_since_planting": days, "items": items, "truncated": truncated}


# ------------------------------------------------------------------------------------------------ compare
def _toks(text: str) -> set[str]:
    return set(_TOKEN.findall((text or "").lower()))


def _same_text(a: str, b: str) -> bool:
    ta, tb = _toks(a), _toks(b)
    return bool(ta and tb) and len(ta & tb) / len(ta | tb) >= OBS_MATCH


def _change(prev, now, order: dict) -> str:
    if prev is None or now is None:
        return "unknown"
    return "up" if order[now] > order[prev] else "down" if order[now] < order[prev] else "same"


# Some observations only restate context (history, diary, weather, farm details), not what is seen on the crop.
_CONTEXT_OBS = re.compile(r"\b(weather|diary|earlier analys\w*|earlier check\w*|previous check\w*|your farm|soil type|farm location|verified diagnosis)\b", re.I)


def _crop_observations(result: dict) -> list[str]:
    return [o for o in (result.get("observations") or []) if isinstance(o, str) and o.strip() and not _CONTEXT_OBS.search(o)]


def compare(prev: dict, now: dict) -> dict:
    """prev / now: stored result dicts. Returns qualitative facts + a direction that is only chosen from real evidence."""
    pi, ni = str(prev.get("likely_issue", "")), str(now.get("likely_issue", ""))
    if is_unclear(pi) or is_unclear(ni):
        issue = "unclear"
    else:
        a, b = set(issue_key(pi).split()), set(issue_key(ni).split())
        issue = "same" if a and b and len(a & b) / min(len(a), len(b)) >= 0.6 else "different"

    ps, ns = _real_sev(prev.get("severity")), _real_sev(now.get("severity"))
    pu, nu = _real_unc(prev.get("uncertainty_level")), _real_unc(now.get("uncertainty_level"))
    sev = {"previous": ps or "unknown", "now": ns or "unknown", "change": _change(ps, ns, SEV)}
    unc = {"previous": pu or "unknown", "now": nu or "unknown", "change": _change(pu, nu, UNC)}

    po = _crop_observations(prev)
    no = _crop_observations(now)
    still = [o for o in no if any(_same_text(o, p) for p in po)]
    new = [o for o in no if not any(_same_text(o, p) for p in po)]
    gone = [p for p in po if not any(_same_text(p, o) for o in no)]
    obs = {"still_present": still[:OBS_LIMIT], "new": new[:OBS_LIMIT], "not_mentioned_now": gone[:OBS_LIMIT]}

    ch = (now.get("change") or {}).get("status") if isinstance(now.get("change"), dict) else None
    model_change = ch if ch in ("better", "same", "worse", "unclear") else None

    # direction: +1 improving, -1 worsening, 0 stable; a signal exists only where the stored evidence supports it
    signals: list[int] = []
    if model_change in ("better", "worse", "same"):
        signals.append({"better": 1, "worse": -1, "same": 0}[model_change])
    if issue == "same":
        if sev["change"] != "unknown":
            signals.append({"down": 1, "up": -1, "same": 0}[sev["change"]])
        if unc["change"] in ("down", "up"):
            signals.append(1 if unc["change"] == "down" else -1)
    if any(s > 0 for s in signals) and any(s < 0 for s in signals):
        direction = "mixed"
    elif any(s > 0 for s in signals):
        direction = "improving"
    elif any(s < 0 for s in signals):
        direction = "worsening"
    elif signals:
        direction = "stable"
    else:
        direction = "unclear"
    return {"issue": issue, "severity": sev, "uncertainty": unc, "observations": obs, "model_change": model_change, "direction": direction}
