"""Does a weather alert touch the farmer's CURRENT Farm plan? Pure and deterministic; it reads the stored plan, never changes it.

Weather only EXPLAINS the relationship ("your plan has irrigation that day"). The Farm plan stays the one place that plans:
the actual re-assessment is the existing plan refresh, whose own material-change rules (forecast_changed) decide whether a
new plan version is made. No agronomic consequence is claimed here: the only statement is "a planned item falls on the
alert's day", never "this will harm the crop".
"""
from ..planning.agent import forecast_changed

# which planned things a weather type can reasonably bear on (by the plan item's activity / kind). Everything outdoors for
# rain/storm/wind; heat bears on watering and field work; cold on planting.
OUTDOOR = {"irrigation", "sowing", "transplanting", "weeding", "harvest", "other"}
AFFECTS = {
    "heavy_rain": OUTDOOR,
    "thunderstorm": OUTDOOR,
    "strong_wind": OUTDOOR,
    "high_temperature": {"irrigation", "weeding", "harvest", "sowing", "transplanting"},
    "low_temperature": {"sowing", "transplanting"},
    "temperature_change": set(),  # information only
}
# plan items the planner itself generated (not the farmer's activities) that are about water/field work on a date
AGENT_KINDS = {
    "heavy_rain": {"irrigation_plan", "irrigation_hold", "reassess_after_rain", "planting_window"},
    "thunderstorm": {"planting_window"},
    "strong_wind": set(),
    "high_temperature": {"irrigation_plan", "planting_window"},
    "low_temperature": {"planting_window"},
    "temperature_change": set(),
}


def _activity(item: dict) -> str | None:
    if item.get("kind") == "activity":
        return str((item.get("params") or {}).get("activity") or "other")
    return None


def plan_impact(alert: dict, plan: dict | None, plan_forecast: list[dict] | None, current_forecast: list[dict] | None, plan_version: int | None) -> dict:
    """alert: {type, event_date}. plan: the stored plan_json (or None). Returns the structured relationship."""
    if not plan:
        return {"has_plan": False, "plan_version": None, "affected": [], "plan_may_be_outdated": False}
    kinds, acts = AGENT_KINDS.get(alert["type"], set()), AFFECTS.get(alert["type"], set())
    affected = []
    for it in plan.get("items", []):
        if it.get("when") != alert["event_date"]:
            continue
        act = _activity(it)
        if (act is not None and act in acts) or (act is None and it.get("kind") in kinds):
            affected.append({"key": it["key"], "kind": it["kind"], "activity": act, "status": it.get("status"), "when": it.get("when")})
    # the plan was made from an older forecast: the existing rule decides whether the difference is material
    outdated = bool(affected) and forecast_changed(plan_forecast, current_forecast)
    return {"has_plan": True, "plan_version": plan_version, "affected": affected, "plan_may_be_outdated": outdated}
