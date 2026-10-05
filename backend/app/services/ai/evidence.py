"""Evidence extraction: a deterministic OBSERVED / UNKNOWN ledger built by the app.

No AI is involved. The ledger states what was actually provided and what was not, so
the model cannot turn assumptions into observations. The model's own INFERRED reasoning
comes back in the assessment (evidence_for / evidence_against / explanation).
"""
from dataclasses import dataclass, field

from .base import AnalysisContext

WEAK_TEXT_CHARS = 25


@dataclass
class Evidence:
    observed: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)
    weak: bool = False  # little to go on: no usable photo and a very short description


def is_weak(ctx: AnalysisContext) -> bool:
    return ctx.image is None and len(ctx.symptoms.strip()) < WEAK_TEXT_CHARS


def build_evidence(ctx: AnalysisContext) -> Evidence:
    ev = Evidence(weak=is_weak(ctx))
    o, u = ev.observed, ev.unknown

    o.append(f"Crop: {ctx.crop}")
    if ctx.symptoms.strip():
        o.append(f"Farmer's description: {ctx.symptoms.strip()}")
    else:
        u.append("Farmer's description: not provided (see photo)")
    if ctx.image:
        o.append("Photo: attached")
    else:
        u.append("Photo: none")

    if ctx.farm_location:
        o.append(f"Farm location (text): {ctx.farm_location}")
    else:
        u.append("Farm location: not provided")
    if ctx.soil_type:
        o.append(f"Soil type (farmer-entered text, not a lab test): {ctx.soil_type}")
    else:
        u.append("Soil type: not provided")

    w = ctx.weather
    if w:
        o.append(f"Weather context (from a weather service, for {w.location_name}):")

        def add(label, v, unit):
            if v is not None:
                o.append(f"  - {label}: {v:g}{unit}")

        add("Temperature now", w.temperature_c, " °C")
        add("Humidity now", w.humidity_pct, " %")
        add("Wind now", w.wind_kmh, " km/h")
        add("Today's min temperature", w.temp_min_c, " °C")
        add("Today's max temperature", w.temp_max_c, " °C")
        add("Rain in the last 3 days", w.past_3d_rain_mm, " mm")
        add("Rain forecast, next few days", w.next_3d_rain_mm, " mm")
        if w.fetched_at:
            o.append(f"  - Data fetched at: {w.fetched_at}")
    else:
        u.append("Weather context: not available")

    u.append("Exact cause (nothing is laboratory-confirmed)")
    u.append("Soil chemistry (pH, nutrients, salinity, moisture) - not provided")
    return ev
