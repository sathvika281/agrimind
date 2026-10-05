"""Proactive intelligence: what in the STORED checks deserves the farmer's attention when the app is opened.

Pure and deterministic: no I/O, no model call, no external request, no database write, no user-facing prose.
It only COMBINES what Phase 9 (history statistics) and Phase 11 (decision support) already computed, so there is
no second recurrence/trend/decision engine here and no new threshold.

Triggers (each needs stored evidence; farm context alone never creates an item):
  latest_high        the latest stored check has a REAL high severity
  repeated_high      Phase 9 repeated_high trend
  recurring          Phase 9 recurring trend (Phase 9 thresholds, unchanged)
  more_frequent      Phase 9 more_frequent trend
  unresolved_verify  Phase 11 state is "verify" AND the latest check's severity is a real "medium"
                     (an unrated check on its own is not evidence of anything needing attention)
A Phase 11 "seek_expert_help" state always rests on one of the reasons above, so it merges into them and only
sets expert_suggested; it never creates a separate item.

Deliberately NOT implemented: "no recent check" (there is no evidence-based interval and none is invented).

One issue -> one item (reasons merged by the Phase 9 normalised issue wording); at most MAX_ITEMS items.
Next steps come only from the closed Phase 11 action catalogue.
"""
from .insights import issue_key

MAX_ITEMS = 3
IMPORTANT_KINDS = ("latest_high", "repeated_high")
REASON_RANK = {"latest_high": 0, "repeated_high": 1, "recurring": 2, "more_frequent": 3, "unresolved_verify": 4}
TREND_REASONS = ("recurring", "more_frequent", "repeated_high")


def build_proactive_items(insights: dict, decision: dict) -> dict:
    items: dict[str, dict] = {}

    def add(key: str, issue: str, reason: dict) -> None:
        it = items.setdefault(key, {"issue": issue, "reasons": []})  # first wording wins (the latest check's, added first)
        if all(r["kind"] != reason["kind"] for r in it["reasons"]):
            it["reasons"].append(reason)

    obs = decision.get("observed")
    latest_key = None
    if obs and not obs["unclear"]:
        latest_key = issue_key(obs["issue"])
        here = {"analysis_id": decision["analysis_id"], "at": obs["checked_at"]}
        if obs["severity"] == "high":
            add(latest_key, obs["issue"], {"kind": "latest_high", "dates": [here]})
        elif decision["state"] == "verify" and obs["severity"] == "medium":
            add(latest_key, obs["issue"], {"kind": "unresolved_verify", "dates": [here]})

    for t in insights["trends"]:
        if t["kind"] in TREND_REASONS:
            add(issue_key(t["issue"]), t["issue"], {
                "kind": t["kind"], "count": t["count"], "window": t["window"], "earlier_count": t.get("earlier_count"), "dates": t["evidence"],
            })

    crops = {c["analysis_id"]: c["crop"] for c in insights["recent"]}
    out = []
    for key, it in items.items():
        reasons = sorted(it["reasons"], key=lambda r: REASON_RANK[r["kind"]])
        dates = {}
        for r in reasons:
            for d in r["dates"]:
                dates[d["analysis_id"]] = d
        newest = max(dates.values(), key=lambda d: (d["at"], d["analysis_id"]))
        is_latest = key == latest_key
        important = any(r["kind"] in IMPORTANT_KINDS for r in reasons)
        # Phase 11 escalates the latest check's issue, and (for repeated_high) the farm as a whole
        expert = decision["state"] == "seek_expert_help" and (is_latest or (decision.get("expert_reason") == "repeated_high" and any(r["kind"] == "repeated_high" for r in reasons)))
        out.append({
            "priority": "important" if important else "attention",
            "issue": it["issue"],
            "crop": obs["crop"] if is_latest else crops.get(newest["analysis_id"], ""),
            "reasons": reasons,
            "actions": decision["actions"][:1] if (is_latest or expert) and decision["actions"] else ["inspect_plants"],
            "expert_suggested": expert,
            "evidence_count": len(dates),
            "latest_at": newest["at"],
            "analysis_id": newest["analysis_id"],  # navigation reference only (the Result page enforces ownership)
            "_sort": (0 if important else 1, REASON_RANK[reasons[0]["kind"]], -newest["at"].timestamp(), key),
        })
    out.sort(key=lambda i: i["_sort"])
    top = [{k: v for k, v in i.items() if k != "_sort"} for i in out[:MAX_ITEMS]]
    level = "none" if not top else "important" if any(i["priority"] == "important" for i in top) else "attention"
    return {"level": level, "total_checks": insights["total"], "items": top}
