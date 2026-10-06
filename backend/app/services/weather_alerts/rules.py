"""Smart Farm Weather Alerts: which forecast days contain an event worth the farmer's attention, and how serious it is.

Pure and deterministic: no I/O, no model, no randomness. The inputs are the REAL daily forecast the existing weather
client already returns (OpenWeather first, Open-Meteo backup); a value the provider did not supply is None and that rule is
simply skipped. Nothing is assumed, simulated or worded here: an alert is a CODE (type, severity, day) plus the measured
numbers; the app words it in English/Telugu.

Thresholds REUSE the ones the app already has (Farm plan rain/heat rules, weather-risk extreme heat) and add only what had
no rule yet (wind, cold, thunderstorm, very heavy rain). They are general rules of thumb: an agronomist/meteorologist should
review them for the region. Severity is a plain ladder, and ordinary weather is NOT an alert:

    info < watch < important < severe
"""
from datetime import date

from ..planning.agent import HOT_C, SIGNIFICANT_RAIN_MM, WET_FIELD_PREV_DAY_MM
from ..weather_risk import EXTREME_HEAT_C

# ---- reused (single source of truth lives elsewhere) ----
RAIN_WATCH_MM = SIGNIFICANT_RAIN_MM  # 10 mm in a day: the Farm plan's "significant rain"
RAIN_IMPORTANT_MM = WET_FIELD_PREV_DAY_MM  # 25 mm: the Farm plan's "very wet day"
HEAT_WATCH_C = HOT_C  # 35 C: the Farm plan's "hot day"
HEAT_IMPORTANT_C = EXTREME_HEAT_C  # 40 C: weather-risk "extreme heat"

# ---- new: no earlier rule existed ----
RAIN_SEVERE_MM = 64.5  # the IMD "heavy rain" class starts at 64.5 mm in 24 h
WIND_WATCH_MS = 10.8  # Beaufort 6, strong breeze (about 39 km/h)
WIND_IMPORTANT_MS = 17.2  # Beaufort 8, gale (about 62 km/h)
WIND_SEVERE_MS = 24.5  # Beaufort 10, storm
HEAT_SEVERE_C = 45.0
COLD_WATCH_C = 10.0  # a day's minimum at or below this
COLD_IMPORTANT_C = 5.0
COLD_SEVERE_C = 2.0  # frost risk
TEMP_SWING_C = 8.0  # day-to-day change of the maximum temperature that is worth a heads-up (info only)

SEVERITIES = ("info", "watch", "important", "severe")
RANK = {s: i for i, s in enumerate(SEVERITIES)}
TYPES = ("heavy_rain", "thunderstorm", "strong_wind", "high_temperature", "low_temperature", "temperature_change")


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _ladder(value: float | None, steps: list[tuple[float, str]], below: bool = False) -> str | None:
    """The highest severity whose threshold the value reaches (steps ordered from the most severe). `below` = the value must be AT OR UNDER it."""
    if value is None:
        return None
    for limit, sev in steps:
        if (value <= limit) if below else (value >= limit):
            return sev
    return None


def evaluate(days: list[dict], today: date) -> list[dict]:
    """days: the real daily forecast as dicts (date, rain_mm, temp_min_c, temp_max_c, rain_probability_pct, wind_ms, gust_ms, thunderstorm).
    Returns alert dicts {type, severity, event_date, values, key}. Days before `today` are ignored."""
    out: list[dict] = []
    ds = sorted((d for d in days if d.get("date") and d["date"] >= today.isoformat()), key=lambda d: d["date"])

    def add(kind: str, sev: str, d: dict, **values):
        out.append({"type": kind, "severity": sev, "event_date": d["date"], "key": f"{kind}|{d['date']}", "values": {k: v for k, v in values.items() if v is not None}})

    prev = None
    for d in ds:
        rain, tmax, tmin = _num(d.get("rain_mm")), _num(d.get("temp_max_c")), _num(d.get("temp_min_c"))
        wind, gust = _num(d.get("wind_ms")), _num(d.get("gust_ms"))
        sev = _ladder(rain, [(RAIN_SEVERE_MM, "severe"), (RAIN_IMPORTANT_MM, "important"), (RAIN_WATCH_MM, "watch")])
        if sev:
            add("heavy_rain", sev, d, rain_mm=rain, rain_probability_pct=_num(d.get("rain_probability_pct")))
        if d.get("thunderstorm") is True:
            strong = (rain or 0) >= RAIN_IMPORTANT_MM or (gust or wind or 0) >= WIND_IMPORTANT_MS
            add("thunderstorm", "important" if strong else "watch", d, rain_mm=rain, gust_ms=gust)
        speed = gust if gust is not None else wind  # a gust is what bends and breaks; the sustained speed is used when no gust is given
        sev = _ladder(speed, [(WIND_SEVERE_MS, "severe"), (WIND_IMPORTANT_MS, "important"), (WIND_WATCH_MS, "watch")])
        if sev:
            add("strong_wind", sev, d, wind_ms=wind, gust_ms=gust, speed_ms=speed)
        sev = _ladder(tmax, [(HEAT_SEVERE_C, "severe"), (HEAT_IMPORTANT_C, "important"), (HEAT_WATCH_C, "watch")])
        if sev:
            add("high_temperature", sev, d, temp_max_c=tmax)
        sev = _ladder(tmin, [(COLD_SEVERE_C, "severe"), (COLD_IMPORTANT_C, "important"), (COLD_WATCH_C, "watch")], below=True)
        if sev:
            add("low_temperature", sev, d, temp_min_c=tmin)
        if prev is not None and tmax is not None:
            ptmax = _num(prev.get("temp_max_c"))
            consecutive = (date.fromisoformat(d["date"]) - date.fromisoformat(prev["date"])).days == 1
            if ptmax is not None and consecutive and abs(tmax - ptmax) >= TEMP_SWING_C and not any(a["event_date"] in (d["date"], prev["date"]) and a["type"] in ("high_temperature", "low_temperature") for a in out):  # a heat/cold alert on either day already covers that swing
                add("temperature_change", "info", d, temp_max_c=tmax, previous_max_c=ptmax, change_c=round(tmax - ptmax, 1))
        prev = d
    out.sort(key=lambda a: (a["event_date"], -RANK[a["severity"]], a["type"]))
    return out
