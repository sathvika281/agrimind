"""Adaptive Farm Planning Agent: the ONE agent of the Farm plan feature.

Deterministic and pure (no model call, no I/O, no database): it receives the real daily forecast, the farm's crop
facts, the latest stored crop check and the farmer's own planned activities, and returns a plan, a diff against the
previous plan version, and whether a NEW version is warranted. Output is coded (kinds, dates, reasons, numbers); the
frontend words it in English/Telugu, so nothing can be invented by wording.

Three steps inside this one agent:  assess (what changed?) -> decide (the plan) -> diff (what moved and why).
Only items AFFECTED by the new information change; everything else is carried over unchanged. If nothing material
changed, no new version is created. Scope: weather, crop condition and the farmer's own plan only (no soil, no market,
no chemical/product/dose advice, no crop-stage model, nothing simulated).
"""
import json
from dataclasses import dataclass, field
from datetime import date, timedelta

from ..insights import is_unclear

# ---- named thresholds (general rules of thumb: an agronomist should review them for the region) ----
SIGNIFICANT_RAIN_MM = 10.0  # a day with at least this much rain counts as significant rain
WET_FIELD_PREV_DAY_MM = 25.0  # a very wet previous day: the field may be too wet for work
DRY_DAY_MM = 3.0  # below this a day counts as dry
HOT_C = 35.0  # a hot day
FORECAST_RAIN_SHIFT_MM = 10.0  # a forecast day's rain moving by this much is a material forecast change
FORECAST_TEMP_SHIFT_C = 5.0  # a forecast day's maximum temperature moving by this much is material
CHECK_FRESH_DAYS = 14  # a crop check older than this no longer drives the plan
MAX_ACTIVITIES = 10
ACTIVITY_KINDS = ("sowing", "transplanting", "irrigation", "weeding", "harvest", "other")
PLANTING_KINDS = ("sowing", "transplanting")
FIELD_CONDITIONS = ("none", "waterlogged", "dry", "pests_seen", "wilting")
SECTION_ORDER = {"now": 0, "next": 1, "if": 2}


@dataclass
class CropState:
    """The farmer's latest stored check (None fields = unknown). Used only as an observation, never as a diagnosis."""

    check_id: int | None = None
    crop: str | None = None
    issue: str = ""
    severity: str = "unknown"
    uncertainty: str = "unknown"
    checked_on: date | None = None


@dataclass
class Previous:
    plan: dict
    inputs: dict
    forecast: list[dict] | None
    check_id: int | None


@dataclass
class Outcome:
    plan: dict
    changes: dict
    create: bool
    reasons: list[str] = field(default_factory=list)
    forecast_source: str = "none"  # live | last_snapshot | none


def _rain(d: dict | None) -> float:
    return float((d or {}).get("rain_mm") or 0.0)


def _tmax(d: dict | None) -> float | None:
    v = (d or {}).get("temp_max_c")
    return float(v) if isinstance(v, (int, float)) else None


def forecast_changed(prev: list[dict] | None, new: list[dict] | None) -> bool:
    """Did the forecast change MATERIALLY for any day that both forecasts cover?"""
    if not prev or not new:
        return False
    old = {d["date"]: d for d in prev}
    for d in new:
        p = old.get(d["date"])
        if p is None:
            continue
        if (_rain(p) >= SIGNIFICANT_RAIN_MM) != (_rain(d) >= SIGNIFICANT_RAIN_MM) or abs(_rain(p) - _rain(d)) >= FORECAST_RAIN_SHIFT_MM:
            return True
        a, b = _tmax(p), _tmax(d)
        if a is not None and b is not None and ((a >= HOT_C) != (b >= HOT_C) or abs(a - b) >= FORECAST_TEMP_SHIFT_C):
            return True
    return False


def _item(key: str, kind: str, section: str, status: str, when: str | None = None, reasons: list[str] | None = None,
          params: dict | None = None, check_id: int | None = None) -> dict:
    return {"key": key, "kind": kind, "section": section, "status": status, "when": when, "reasons": reasons or [],
            "params": params or {}, "check_id": check_id}


def _sig(item: dict) -> str:
    return json.dumps([item["status"], item["when"], item["reasons"], item["params"], item["section"]], sort_keys=True, default=str)


def items_signature(items: list[dict]) -> str:
    return json.dumps({i["key"]: _sig(i) for i in items}, sort_keys=True)


class AdaptivePlanningAgent:
    # ------------------------------------------------------------------ step 2: decide
    def decide(self, *, inputs: dict, forecast: list[dict] | None, crop: CropState, farm: dict, today: date) -> dict:
        iso = today.isoformat()
        days = {d["date"]: d for d in (forecast or [])}
        ordered = [d for d in (forecast or []) if d["date"] >= iso]
        activities = [a for a in inputs.get("activities", []) if a["date"] >= iso]
        field_cond = inputs.get("field_condition") or "none"
        irrigation_relevant = bool(farm.get("irrigation_method")) or any(a["kind"] == "irrigation" for a in activities)
        items: list[dict] = []

        # ---- crop condition (an observation from the farmer's own check; wording stays "possible", never a diagnosis)
        fresh = bool(crop.checked_on and (today - crop.checked_on).days <= CHECK_FRESH_DAYS)
        level = "none"
        if crop.check_id and fresh:
            level = "unclear" if is_unclear(crop.issue) else "possible"
        if field_cond in ("pests_seen", "wilting") and level in ("none", "unclear"):
            level = "possible"
        concern = {"level": level, "issue": crop.issue if level == "possible" and crop.check_id and fresh else "",
                   "severity": crop.severity, "uncertainty": crop.uncertainty, "check_id": crop.check_id if fresh else None,
                   "checked_on": crop.checked_on.isoformat() if crop.checked_on else None, "farmer_reported": field_cond if field_cond in ("pests_seen", "wilting") else None}
        cid = concern["check_id"]
        if level == "possible":
            items.append(_item("crop:inspect", "inspect_plants", "now", "do_now", reasons=["possible_problem"], check_id=cid))
            items.append(_item("crop:spread", "watch_spread", "next", "consider", when=(today + timedelta(days=2)).isoformat() if (today + timedelta(days=2)).isoformat() in days or not days else None, reasons=["possible_problem"], check_id=cid))
            items.append(_item("crop:recheck", "recheck_crop", "next", "consider", reasons=["possible_problem"], check_id=cid))
            if crop.severity == "high":
                items.append(_item("crop:expert", "ask_expert", "now", "do_now", reasons=["severity_high"], check_id=cid))
        elif level == "unclear":
            items.append(_item("crop:detail", "add_detail", "now", "do_now", reasons=["check_unclear"], check_id=cid))
        else:
            items.append(_item("crop:routine", "monitor_routine", "now", "info"))

        # ---- the farmer's reported field condition
        if field_cond == "waterlogged":
            items.append(_item("field:drain", "drain_field", "now", "do_now", reasons=["farmer_reported"]))
        elif field_cond == "dry" and irrigation_relevant:
            items.append(_item("field:dry", "dry_field", "now", "consider", reasons=["farmer_reported"]))

        # ---- weather-driven irrigation (real forecast days only)
        rainy = [d for d in ordered if _rain(d) >= SIGNIFICANT_RAIN_MM]
        if irrigation_relevant and ordered:
            for d in rainy:
                items.append(_item(f"irrigation:hold:{d['date']}", "irrigation_hold", "now" if d["date"] == iso else "next", "hold",
                                   when=d["date"], reasons=["significant_rain"], params={"rain_mm": round(_rain(d), 1)}))
            if rainy:
                after = (date.fromisoformat(rainy[0]["date"]) + timedelta(days=1)).isoformat()
                if after in days:
                    items.append(_item(f"irrigation:reassess:{after}", "reassess_after_rain", "next", "consider", when=after, reasons=["after_rain"]))
            elif all(_rain(d) < DRY_DAY_MM for d in ordered):
                hot = any((_tmax(d) or 0) >= HOT_C for d in ordered)
                items.append(_item("irrigation:plan", "irrigation_plan", "next", "consider", when=ordered[0]["date"], reasons=["dry_spell"] + (["hot_days"] if hot else []),
                                   params={"hot": hot}))
        if field_cond == "waterlogged" and irrigation_relevant and not any(i["key"] == f"irrigation:hold:{iso}" for i in items):
            items.append(_item(f"irrigation:hold:{iso}", "irrigation_hold", "now", "hold", when=iso, reasons=["waterlogged"]))

        # ---- the farmer's planned activities, each assessed against ITS day's real forecast
        for a in activities:
            day = days.get(a["date"])
            prev_day = days.get((date.fromisoformat(a["date"]) - timedelta(days=1)).isoformat())
            params = {"activity": a["kind"], "date": a["date"], "note": a.get("note", "")}
            if not forecast:
                status, reasons = "unassessed", ["no_forecast"]
            elif day is None:
                status, reasons = "unassessed", ["beyond_forecast"]
            elif _rain(day) >= SIGNIFICANT_RAIN_MM:
                status, reasons, params["rain_mm"] = "reconsider", ["heavy_rain_that_day"], round(_rain(day), 1)
            elif prev_day is not None and _rain(prev_day) >= WET_FIELD_PREV_DAY_MM:
                status, reasons, params["rain_mm"] = "reconsider", ["wet_after_rain"], round(_rain(prev_day), 1)
            elif (_tmax(day) or 0) >= HOT_C:
                status, reasons, params["temp_max_c"] = "cool_hours", ["hot_day"], round(_tmax(day), 1)
            else:
                status, reasons = "supported", ["forecast_ok"]
            items.append(_item(f"activity:{a['id']}", "activity", "now" if a["date"] == iso else "next", status, when=a["date"], reasons=reasons, params=params))
            if a["kind"] in PLANTING_KINDS and forecast:
                good = [d for d in ordered if _rain(d) < SIGNIFICANT_RAIN_MM and (_tmax(d) or 0) < HOT_C]
                if good:
                    best = min(good, key=lambda d: (_rain(d), _tmax(d) or 0, d["date"]))
                    items.append(_item(f"planting:{a['id']}", "planting_window", "next", "consider", when=best["date"], reasons=["best_forecast_day"], params={"activity": a["kind"]}))
                else:
                    items.append(_item(f"planting:{a['id']}", "planting_window", "next", "consider", reasons=["no_good_day"], params={"activity": a["kind"]}))

        # ---- what to change if conditions change (standing rules, not predictions)
        items.append(_item("if:rain", "if_rain_arrives", "if", "info"))
        items.append(_item("if:forecast", "if_forecast_changes", "if", "info"))
        if any((_tmax(d) or 0) >= HOT_C for d in ordered):
            items.append(_item("if:heat", "if_heat_arrives", "if", "info"))
        if level == "possible":
            items.append(_item("if:spread", "if_symptoms_spread", "if", "info", check_id=cid))

        items.sort(key=lambda i: (SECTION_ORDER[i["section"]], i["when"] or "9999", i["key"]))
        pd = farm.get("planting_date")
        return {
            "crop": farm.get("primary_crop") or crop.crop, "generated_for": iso, "forecast_available": bool(forecast),
            "days_since_planting": (today - pd).days if isinstance(pd, date) and pd <= today else None,
            "horizon": [d["date"] for d in ordered], "concern": concern, "items": items,
        }

    # ------------------------------------------------------------------ step 3: diff
    @staticmethod
    def _reason_for(key: str, reasons: list[str]) -> str:
        family = key.split(":")[0]
        if family == "crop":
            return "new_check" if "new_check" in reasons else "farmer_edit" if "farmer_edit" in reasons else (reasons[0] if reasons else "first_plan")
        if family == "field":
            return "farmer_edit"
        for r in ("forecast_change", "farmer_edit", "new_check"):
            if r in reasons:
                return r
        return reasons[0] if reasons else "first_plan"

    def diff(self, prev_items: list[dict], new_items: list[dict], reasons: list[str]) -> dict:
        old, new = {i["key"]: i for i in prev_items}, {i["key"]: i for i in new_items}
        out = []
        for key in sorted(set(old) | set(new)):
            o, n = old.get(key), new.get(key)
            if o is None:
                out.append({"key": key, "change": "added", "kind": n["kind"], "reason": self._reason_for(key, reasons), "before": None, "after": {"status": n["status"], "when": n["when"]}})
            elif n is None:
                out.append({"key": key, "change": "removed", "kind": o["kind"], "reason": self._reason_for(key, reasons), "before": {"status": o["status"], "when": o["when"]}, "after": None})
            elif _sig(o) != _sig(n):
                out.append({"key": key, "change": "changed", "kind": n["kind"], "reason": self._reason_for(key, reasons),
                            "before": {"status": o["status"], "when": o["when"]}, "after": {"status": n["status"], "when": n["when"]}})
        return {"reasons": reasons, "items": out, "unchanged": sum(1 for k in new if k in old and _sig(old[k]) == _sig(new[k]))}

    # ------------------------------------------------------------------ step 1: assess, then run all three
    def run(self, *, inputs: dict, live_forecast: list[dict] | None, crop: CropState, farm: dict, today: date, prev: Previous | None) -> Outcome:
        snapshot = [d for d in (prev.forecast or []) if d["date"] >= today.isoformat()] if prev else []
        forecast = live_forecast or snapshot or None  # never simulated: live, else the last REAL snapshot, else nothing
        source = "live" if live_forecast else "last_snapshot" if snapshot else "none"
        plan = self.decide(inputs=inputs, forecast=forecast, crop=crop, farm=farm, today=today)
        if prev is None:
            return Outcome(plan, {"reasons": ["first_plan"], "items": [], "unchanged": 0}, True, ["first_plan"], source)
        reasons: list[str] = []
        if live_forecast and (forecast_changed(prev.forecast, live_forecast) or (not prev.forecast and live_forecast)):
            reasons.append("forecast_change")
        if (crop.check_id or None) != (prev.check_id or None):
            reasons.append("new_check")
        if inputs != prev.inputs:
            reasons.append("farmer_edit")
        if not reasons or items_signature(plan["items"]) == items_signature(prev.plan.get("items", [])):
            return Outcome(prev.plan, {"reasons": [], "items": [], "unchanged": len(prev.plan.get("items", []))}, False, reasons, source)
        return Outcome(plan, self.diff(prev.plan.get("items", []), plan["items"], reasons), True, reasons, source)
