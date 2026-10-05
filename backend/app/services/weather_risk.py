"""Weather-aware hints from the REAL forecast numbers only. Pure, deterministic, no model, no I/O.

A hint is "what this weather MAY mean for a crop and what to look at", never a prediction and never a cause:
the thresholds below are conservative general-agronomy rules of thumb (they should be reviewed by an agronomist
for the region). A rule whose input is missing is skipped; nothing is ever assumed. At most MAX_HINTS are returned.
"""

# ---- thresholds (one place, named, easy to review) ----
FUNGAL_HUMIDITY_PCT = 80.0  # humid air ...
FUNGAL_RAIN_MM = 5.0  # ... together with rain in the last or next 3 days
HEAVY_RAIN_MM = 40.0  # forecast rain over the next 3 days
HOT_DRY_TEMP_C = 35.0  # today's maximum ...
DRY_RAIN_MM = 1.0  # ... with (almost) no rain in the last and next 3 days
EXTREME_HEAT_C = 40.0  # a very hot day
MAX_HINTS = 2

# priority order: the first matching hints win
PRIORITY = ("extreme_heat", "heavy_rain", "humid_wet", "hot_dry")
ACTIONS = {"extreme_heat": "check_heat_stress", "heavy_rain": "check_drainage", "humid_wet": "check_leaves", "hot_dry": "check_soil_moisture"}


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def weather_risks(w: dict | None) -> list[dict]:
    if not w:
        return []
    hum, tmax = _num(w.get("humidity_pct")), _num(w.get("temp_max_c"))
    past, nxt = _num(w.get("past_3d_rain_mm")), _num(w.get("next_3d_rain_mm"))
    found: dict[str, dict] = {}
    if tmax is not None and tmax >= EXTREME_HEAT_C:
        found["extreme_heat"] = {"temp_max_c": tmax}
    if nxt is not None and nxt >= HEAVY_RAIN_MM:
        found["heavy_rain"] = {"rain_mm": nxt}
    if hum is not None and hum >= FUNGAL_HUMIDITY_PCT and ((past or 0) >= FUNGAL_RAIN_MM or (nxt or 0) >= FUNGAL_RAIN_MM):
        found["humid_wet"] = {"humidity_pct": hum, "rain_mm": max(past or 0, nxt or 0)}
    if tmax is not None and tmax >= HOT_DRY_TEMP_C and past is not None and nxt is not None and past < DRY_RAIN_MM and nxt < DRY_RAIN_MM:
        found["hot_dry"] = {"temp_max_c": tmax}
    out = []
    for kind in PRIORITY:
        if kind in found:
            out.append({"kind": kind, "action": ACTIONS[kind], "humidity_pct": None, "rain_mm": None, "temp_max_c": None, **found[kind]})
    return out[:MAX_HINTS]
