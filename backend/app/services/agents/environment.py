"""Agent 4: Environment. Whether the weather is relevant to the candidate explanations, and what it can/can't say.

Deterministic: it applies the existing weather thresholds (services/weather_risk.py) to the weather the server
already fetched. Wording is deliberately "consistent with", never "caused by": weather for a village area is
context, not proof of a cause for one field.
"""
import re

from ..graph.state import CropAnalysis, EnvironmentAnalysis
from ..ai.base import WeatherContext
from ..weather_risk import weather_risks

# Candidate wording that suggests a moisture-driven problem / a heat-or-water-stress problem.
_MOIST = re.compile(r"fung|bacteri|blight|mildew|mould|mold|rot|leaf spot|spot|rust|wilt", re.I)
_STRESS = re.compile(r"water stress|drought|heat|scorch|nutrient|yellow", re.I)


def run(w: WeatherContext | None, analysis: CropAnalysis, planting_date: str | None = None) -> EnvironmentAnalysis:
    out = EnvironmentAnalysis()
    if w is None:
        out.environmental_uncertainties.append("no weather data was available for this farm")
        return out
    risks = weather_risks(w.to_dict())
    text = " ".join(analysis.candidate_issues)
    moist, stress = bool(_MOIST.search(text)), bool(_STRESS.search(text))
    out.relevant_conditions = [k["kind"] for k in risks]

    for k in risks:
        kind = k["kind"]
        if kind in ("humid_wet", "heavy_rain"):
            if moist:
                out.supporting_signals.append(
                    f"{kind}: recent wet/humid weather is consistent with conditions that can support some moisture-related crop problems")
        elif kind in ("hot_dry", "extreme_heat"):
            if stress:
                out.supporting_signals.append(f"{kind}: hot, dry weather is consistent with conditions that can stress crops")
            elif moist:
                out.contradicting_signals.append(f"{kind}: hot, dry weather makes some moisture-related explanations less likely")
    out.relevant_conditions = list(dict.fromkeys(out.relevant_conditions))

    if risks and (moist or stress):
        out.weather_relevance = "high" if (out.supporting_signals or out.contradicting_signals) else "medium"
    elif risks:
        out.weather_relevance = "medium"
    else:
        out.weather_relevance = "low"
    out.environmental_uncertainties = [
        "the weather is for the village area, not measured in this field",
        "soil moisture and irrigation timing were not measured",
        *(["the planting date is not known, so the crop stage is unknown"] if not planting_date else []),
    ]
    return out
