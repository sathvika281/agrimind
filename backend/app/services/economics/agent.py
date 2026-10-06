"""The CROP ECONOMICS & SELLING INTELLIGENCE AGENT.

Its single job: interpret the structured economic state that the earlier graph steps prepared, and say what drives the
result, how sure it is, what is missing and which selling option currently looks stronger. It never computes the
figures (calc.py did, deterministically) and it never calls a model: every statement is a CODE plus numbers copied from
that calculated state, rendered to English/Telugu text by the app's dictionaries. So it cannot invent a price, a yield, a
cost or a promise of profit. Confidence is a plain level with reasons, never a percentage.
"""
from dataclasses import dataclass, field


@dataclass
class Reading:
    outlook: str = "insufficient"  # margin_positive | margin_uncertain | margin_negative | insufficient
    confidence: dict = field(default_factory=lambda: {"level": "limited", "reasons": []})
    drivers: list[dict] = field(default_factory=list)  # strongest first: {factor, swing}
    missing: list[str] = field(default_factory=list)
    best_market: dict | None = None
    price_vs_breakeven: str | None = None  # above | within | below
    notes: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=lambda: ["estimate_not_promise", "actual_may_differ"])

    def public(self) -> dict:
        return {"outlook": self.outlook, "confidence": self.confidence, "drivers": self.drivers, "missing": self.missing, "best_market": self.best_market,
                "price_vs_breakeven": self.price_vs_breakeven, "notes": self.notes, "limitations": self.limitations}


def _mid(r: dict | None):
    return None if not r else (r["low"] + r["high"]) / 2


def interpret(state: dict) -> Reading:
    """state: the graph's calculated state (production, costs, breakeven, markets, options, outlook, grid, context)."""
    r = Reading()
    prod, costs, be, outlook, grid, ctx = state["production"], state["costs"], state["breakeven"], state["outlook"], state["grid"], state["context"]
    markets, options = state["markets"], state["options"]

    # what is missing, most important first (each is a real gap, never filled in)
    missing = list(prod["missing"])
    if costs["total"] is None:
        missing.append("costs")
    if not any(m["status"] in ("fresh", "stale") for m in markets):
        missing.append("market_price")
    if state["window"]["source"] == "unavailable":
        missing.append("harvest_timing")
    r.missing = missing

    # confidence: farmer estimates cap it at "moderate"; any gap or stale/absent market lowers it to "limited"
    reasons = ["yield_farmer_estimate"] if prod["yield"] else []
    level = "moderate"
    if missing and set(missing) & {"area", "yield", "marketable", "costs", "market_price"}:
        level = "limited"
        reasons.append("inputs_missing")
    if markets and all(m["status"] == "stale" for m in markets if m["status"] in ("fresh", "stale")) and any(m["status"] == "stale" for m in markets):
        level = "limited"
        reasons.append("market_stale")
    elif any(m["status"] == "fresh" for m in markets):
        reasons.append("market_fresh")
    if not costs["complete"] and costs["total"] is not None:
        reasons.append("costs_incomplete")
    if outlook and not outlook["transport_included"]:
        reasons.append("transport_unknown")
    if any(m["source"] == "demo" for m in markets if m["status"] in ("fresh", "stale")):
        level = "limited"
        reasons.append("demo_data")
    r.confidence = {"level": level, "reasons": reasons}

    if outlook:
        lo, hi = outlook["margin"]["low"], outlook["margin"]["high"]
        r.outlook = "margin_positive" if lo > 0 else "margin_negative" if hi < 0 else "margin_uncertain"

    # drivers: how much the margin moves for a +/-10% change in price, yield or cost (read from the calculated grid)
    if grid:
        def swing(key_hi, key_lo):
            a, b = _mid(grid["cells"][key_hi]["margin"]), _mid(grid["cells"][key_lo]["margin"])
            return abs(a - b) if a is not None and b is not None else 0
        r.drivers = sorted(
            [{"factor": "price", "swing": round(swing("10|0|0", "-10|0|0"))}, {"factor": "yield", "swing": round(swing("0|10|0", "0|-10|0"))}, {"factor": "cost", "swing": round(swing("0|0|10", "0|0|-10"))}],
            key=lambda d: -d["swing"],
        )

    # selling options: report which currently looks stronger and by how much (net, after the transport the farmer entered)
    complete = [o for o in options if o["complete"]]
    if complete:
        top = complete[0]
        gap = (top["net_per_quintal"] - complete[1]["net_per_quintal"]) if len(complete) > 1 else None
        r.best_market = {"id": top["id"], "name": top["name"], "reason": "best_net_value", "net_per_quintal": top["net_per_quintal"], "gap_per_quintal": gap, "compared": len(complete)}
    elif any(m["status"] in ("fresh", "stale") for m in markets):
        top = max((m for m in markets if m["status"] in ("fresh", "stale")), key=lambda m: m["_latest"])
        r.best_market = {"id": top["id"], "name": top["name"], "reason": "highest_price_transport_unknown", "net_per_quintal": None, "gap_per_quintal": None, "compared": 0}

    # where today's price sits against the break-even range
    ref = state["reference"]
    if be and ref:
        p = ref["_latest"] - (ref["transport_per_quintal"] or 0)
        r.price_vs_breakeven = "above" if p >= be["high"] else "below" if p < be["low"] else "within"

    notes = []
    if ref and ref["trend"] != "insufficient_data":
        notes.append(f"trend_{ref['trend']}")
    elif ref:
        notes.append("trend_insufficient")
    if state["window"]["source"] == "planting_plus_estimate":
        notes.append("harvest_from_planting_date")
    lc = ctx.get("latest_check")
    if lc and lc["recent"] and lc["severity"] == "high":
        notes.append("crop_check_high_severity")  # context only: no number is changed because of it
    if ctx.get("planting_source") == "diary":
        notes.append("planting_from_diary")
    if not markets:
        notes.append("no_market_data")
    r.notes = notes
    return r

