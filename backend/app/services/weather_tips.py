"""Weather tips: how a farmer can cope with the weather that is actually forecast for this farm.

Pure and deterministic: no model, no I/O. It reads the same numbers the Weather tab shows and returns CODED tips plus
the real measured conditions that triggered them; the frontend words them (English/Telugu). Rules reuse the thresholds
in services/weather_risk.py and add three named constants below (general rules of thumb: an agronomist should review
them for the region). A rule whose input is missing is skipped; nothing is assumed.

The tips are NON-CHEMICAL cultural practice only: drainage, support, shade, mulch, when to water, what to watch.
Like everywhere else in AgriMind there is no pesticide, product, dose or spray advice.
"""
from .weather_risk import DRY_RAIN_MM, EXTREME_HEAT_C, FUNGAL_HUMIDITY_PCT, FUNGAL_RAIN_MM, HEAVY_RAIN_MM, HOT_DRY_TEMP_C

WIND_STRONG_KMH = 30.0  # current wind
COLD_NIGHT_C = 10.0  # today's minimum
MAX_TIPS = 6

# condition -> the tips it brings (kind, group). Order = priority: the first conditions' tips are kept if the cap bites.
CATALOGUE: dict[str, list[tuple[str, str]]] = {
    "extreme_heat": [("irrigate_cool_hours", "water"), ("shade_seedlings", "protect"), ("avoid_midday_work", "protect"), ("mulch", "water"), ("check_soil_before_irrigating", "water")],
    "heavy_rain": [("clear_drains", "protect"), ("avoid_wet_field_work", "protect"), ("harvest_before_rain", "protect"), ("store_dry", "protect"), ("support_tall_plants", "protect")],
    "humid_wet": [("water_at_base_morning", "water"), ("keep_airflow", "protect"), ("remove_affected_leaves", "protect"), ("scout_often", "watch")],
    "hot_dry": [("irrigate_cool_hours", "water"), ("mulch", "water"), ("shade_seedlings", "protect"), ("check_soil_before_irrigating", "water")],
    "strong_wind": [("stake_and_tie", "protect"), ("shelter_seedlings", "protect")],
    "cold_night": [("cover_seedlings", "protect")],
    "dry_spell": [("plan_irrigation", "water"), ("mulch", "water")],
}
NORMAL = [("regular_checks", "watch")]


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def conditions(w: dict | None) -> list[dict]:
    """The conditions present in this weather, each with the real number behind it (never invented)."""
    if not w:
        return []
    hum, tmax, tmin, wind = _num(w.get("humidity_pct")), _num(w.get("temp_max_c")), _num(w.get("temp_min_c")), _num(w.get("wind_kmh"))
    past, nxt = _num(w.get("past_3d_rain_mm")), _num(w.get("next_3d_rain_mm"))
    out: list[dict] = []
    if tmax is not None and tmax >= EXTREME_HEAT_C:
        out.append({"kind": "extreme_heat", "value": tmax})
    if nxt is not None and nxt >= HEAVY_RAIN_MM:
        out.append({"kind": "heavy_rain", "value": nxt})
    if hum is not None and hum >= FUNGAL_HUMIDITY_PCT and ((past or 0) >= FUNGAL_RAIN_MM or (nxt or 0) >= FUNGAL_RAIN_MM):
        out.append({"kind": "humid_wet", "value": hum})
    hot_dry = tmax is not None and tmax >= HOT_DRY_TEMP_C and past is not None and nxt is not None and past < DRY_RAIN_MM and nxt < DRY_RAIN_MM
    if hot_dry:
        out.append({"kind": "hot_dry", "value": tmax})
    if wind is not None and wind >= WIND_STRONG_KMH:
        out.append({"kind": "strong_wind", "value": wind})
    if tmin is not None and tmin <= COLD_NIGHT_C:
        out.append({"kind": "cold_night", "value": tmin})
    # a dry spell needs the forecast to be known; the past is used only if it is known too
    if nxt is not None and nxt < DRY_RAIN_MM and (past is None or past < DRY_RAIN_MM) and not hot_dry:
        out.append({"kind": "dry_spell", "value": nxt})
    return out


def _select(tips: list[dict]) -> list[dict]:
    """Within the cap, keep at least one tip from each group (protect / water / watch) when the weather brings them,
    then fill by priority. The original (priority) order is preserved."""
    if len(tips) <= MAX_TIPS:
        return tips
    chosen: list[dict] = []
    for g in ("protect", "water", "watch"):
        first = next((t for t in tips if t["group"] == g), None)
        if first:
            chosen.append(first)
    for t in tips:
        if len(chosen) >= MAX_TIPS:
            break
        if t not in chosen:
            chosen.append(t)
    return [t for t in tips if t in chosen]


def tips_for(w: dict | None) -> dict:
    """{'conditions': [{kind, value}], 'tips': [{kind, group}]}. Empty when there is no weather."""
    if not w:
        return {"conditions": [], "tips": []}
    conds = conditions(w)
    tips: list[dict] = []
    seen: set[str] = set()
    for c in conds:
        for kind, group in CATALOGUE[c["kind"]]:
            if kind not in seen:
                seen.add(kind)
                tips.append({"kind": kind, "group": group})
    if not conds:
        tips = [{"kind": k, "group": g} for k, g in NORMAL]
    kept = _select(tips)
    return {"conditions": conds, "tips": kept}
