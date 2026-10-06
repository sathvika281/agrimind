"""Crop economics arithmetic. Pure and deterministic: no I/O, no model call, no randomness, no invented numbers.

Every figure comes from what the farmer entered (area, yield, costs, market prices, transport) or from a real market quote.
A missing input is reported as missing; it is never silently replaced by a default and never becomes zero.

Units: area in the farmer's own area unit (acre or hectare), yield in quintals per that unit, prices in INR per quintal
(1 quintal = 100 kg), money in INR. Ranges are (low, high); a single value is a range with low == high.
"""
from datetime import date, timedelta

COST_CATEGORIES = ["seeds", "seedlings", "fertilizer", "labour", "irrigation", "machinery", "land_preparation", "harvesting", "transport", "storage", "other"]
STALE_DAYS = 7  # a quote older than this is shown as stale (still used, confidence lowered)
EXCLUDE_DAYS = 30  # a quote older than this is not used at all
TREND_MIN_POINTS = 3  # observations (distinct dates, one market) needed before a trend is stated
TREND_BAND_PCT = 3.0  # earlier-half vs later-half mean must differ by more than this to be called a trend
PRICE_FACTORS = [-10, -5, 0, 5, 10]  # percent
YIELD_FACTORS = [-20, -10, 0, 10]
COST_FACTORS = [-10, 0, 10, 20]


def _f(x) -> float | None:
    return None if x is None else float(x)


def _r(x: float | None, nd: int = 0):
    """Round for presentation only (never inside a calculation)."""
    if x is None:
        return None
    v = round(x + 1e-9, nd)
    return int(v) if nd == 0 else v


def _rng(lo: float | None, hi: float | None, nd: int = 0):
    return None if lo is None or hi is None else {"low": _r(lo, nd), "high": _r(hi, nd)}


# ---------------------------------------------------------------- production
def production(inp: dict) -> dict:
    """Area x yield, then the part that can be sold. Needs area, a yield range and a marketable share; says what is missing."""
    area, yl, yh = _f(inp.get("area")), _f(inp.get("yield_low")), _f(inp.get("yield_high"))
    ml, mh = _f(inp.get("marketable_low_pct")), _f(inp.get("marketable_high_pct"))
    missing = [k for k, v in (("area", area), ("yield", yl if yl is not None and yh is not None else None), ("marketable", ml if ml is not None and mh is not None else None)) if v is None]
    out = {"unit": inp.get("area_unit") or "acre", "area": area, "missing": missing, "production": None, "marketable": None, "yield": _rng(yl, yh, 1) if yl is not None and yh is not None else None,
           "marketable_pct": _rng(ml, mh, 0) if ml is not None and mh is not None else None}
    _lo = _hi = None
    if area and yl is not None and yh is not None:
        out["production"] = _rng(area * yl, area * yh, 1)
        _lo, _hi = area * yl, area * yh
    if _lo is not None and ml is not None and mh is not None:
        out["marketable"] = _rng(_lo * ml / 100, _hi * mh / 100, 1)
    out["_raw"] = {"mkt_low": (_lo * ml / 100) if _lo is not None and ml is not None else None, "mkt_high": (_hi * mh / 100) if _hi is not None and mh is not None else None}
    return out


# ---------------------------------------------------------------- costs
def costs(inp: dict, prod: dict) -> dict:
    """Total of the categories the farmer entered. Categories without an amount are listed as NOT INCLUDED (never counted as 0)."""
    given = {k: _f(v) for k, v in (inp.get("costs") or {}).items() if k in COST_CATEGORIES and v is not None}
    total = sum(given.values()) if given else None
    area = prod.get("area")
    raw = prod.get("_raw") or {}
    mk_low, mk_high = raw.get("mkt_low"), raw.get("mkt_high")
    per_q = None
    if total is not None and mk_low and mk_high:
        per_q = _rng(total / mk_high, total / mk_low, 0)  # more marketable produce -> lower cost per quintal
    return {
        "items": [{"key": k, "amount": _r(given[k]) if k in given else None, "included": k in given} for k in COST_CATEGORIES],
        "not_included": [k for k in COST_CATEGORIES if k not in given],
        "total": _r(total) if total is not None else None,
        "per_area": _r(total / area) if total is not None and area else None,
        "per_quintal": per_q,
        "complete": len(given) == len(COST_CATEGORIES),
        "_total": total,
    }


def breakeven(c: dict, prod: dict) -> dict | None:
    """Total production cost / marketable quantity (a range, because the quantity is a range)."""
    raw = prod.get("_raw") or {}
    if c["_total"] is None or not raw.get("mkt_low") or not raw.get("mkt_high"):
        return None
    return _rng(c["_total"] / raw["mkt_high"], c["_total"] / raw["mkt_low"], 0)


# ---------------------------------------------------------------- market
def _age(d: date, today: date) -> int:
    return (today - d).days


def analyse_market(m: dict, today: date) -> dict:
    """One market: latest price, freshness, recent range and a trend only when there are enough dated observations."""
    pts = sorted(((date.fromisoformat(p["date"]), float(p["price"])) for p in m.get("prices", [])), key=lambda x: x[0])
    usable = [(d, p) for d, p in pts if 0 <= _age(d, today) <= EXCLUDE_DAYS]
    out = {"id": m.get("id"), "name": m.get("name"), "source": m.get("source", "farmer"), "distance_km": _f(m.get("distance_km")), "transport_per_quintal": _f(m.get("transport_per_quintal")),
           "observations": len(usable), "latest": None, "range": None, "trend": "insufficient_data", "status": "no_price"}
    if pts and not usable:
        out["status"] = "too_old"
        out["latest"] = {"date": pts[-1][0].isoformat(), "price": _r(pts[-1][1]), "age_days": _age(pts[-1][0], today)}
        return out
    if not usable:
        return out
    d, p = usable[-1]
    age = _age(d, today)
    out["latest"] = {"date": d.isoformat(), "price": _r(p), "age_days": age}
    out["status"] = "stale" if age > STALE_DAYS else "fresh"
    prices = [x[1] for x in usable]
    out["range"] = {"low": _r(min(prices)), "high": _r(max(prices))}
    if len({x[0] for x in usable}) >= TREND_MIN_POINTS:
        half = len(usable) // 2
        a = sum(x[1] for x in usable[:half]) / half
        b = sum(x[1] for x in usable[-half:]) / half
        pct = (b - a) / a * 100 if a else 0.0
        out["trend"] = "increasing" if pct > TREND_BAND_PCT else "decreasing" if pct < -TREND_BAND_PCT else "stable"
    out["points"] = [{"date": x[0].isoformat(), "price": _r(x[1])} for x in usable]
    out["_low"], out["_high"], out["_latest"] = min(prices), max(prices), p
    return out


def selling_options(markets: list[dict], prod: dict) -> list[dict]:
    """Net value after transport. Ranked by net price per quintal; a market without a transport cost is shown but never ranked above a complete one."""
    raw = prod.get("_raw") or {}
    q_lo, q_hi = raw.get("mkt_low"), raw.get("mkt_high")
    opts = []
    for m in markets:
        if m["status"] not in ("fresh", "stale"):
            opts.append({**_pub(m), "net_per_quintal": None, "net_value": None, "complete": False, "reason": m["status"]})
            continue
        t = m["transport_per_quintal"]
        p = m["_latest"]
        net = p - t if t is not None else None
        value = _rng(q_lo * net, q_hi * net, 0) if net is not None and q_lo and q_hi else None
        opts.append({**_pub(m), "gross_value": _rng(q_lo * p, q_hi * p, 0) if q_lo and q_hi else None, "net_per_quintal": _r(net) if net is not None else None, "net_value": value,
                     "complete": net is not None, "reason": "ok" if net is not None else "transport_missing"})
    opts.sort(key=lambda o: (not o["complete"], -(o["net_per_quintal"] if o["net_per_quintal"] is not None else (o["latest"]["price"] if o["latest"] else 0))))
    for i, o in enumerate(opts):
        o["rank"] = i + 1 if o["complete"] else None
    return opts


def _pub(m: dict) -> dict:
    return {k: v for k, v in m.items() if not k.startswith("_")}


def reference_market(markets: list[dict], opts: list[dict]) -> dict | None:
    """The market the outlook is based on: the best complete net value, else the highest fresh price (flagged: transport unknown)."""
    by_id = {m["id"]: m for m in markets}
    complete = [o for o in opts if o["complete"]]
    if complete:
        return by_id[complete[0]["id"]]
    usable = [m for m in markets if m["status"] in ("fresh", "stale")]
    return max(usable, key=lambda m: m["_latest"]) if usable else None


# ---------------------------------------------------------------- outlook + scenarios
def _outlook(q_lo, q_hi, p_lo, p_hi, t, cost, yield_f=0.0, price_f=0.0, cost_f=0.0):
    """Revenue, margin and break-even for one set of factors (percent changes). Returns None parts when an input is missing."""
    if None in (q_lo, q_hi, p_lo, p_hi, cost):
        return None
    ql, qh = q_lo * (1 + yield_f / 100), q_hi * (1 + yield_f / 100)
    pl, ph = p_lo * (1 + price_f / 100), p_hi * (1 + price_f / 100)
    tt = t or 0.0
    c = cost * (1 + cost_f / 100)
    rev_lo, rev_hi = ql * (pl - tt), qh * (ph - tt)
    return {"marketable": _rng(ql, qh, 1), "revenue": _rng(rev_lo, rev_hi), "cost": _r(c), "margin": _rng(rev_lo - c, rev_hi - c), "breakeven": _rng(c / qh, c / ql) if ql and qh else None}


def outlook(prod: dict, c: dict, ref: dict | None) -> dict | None:
    raw = prod.get("_raw") or {}
    if ref is None:
        return None
    t = ref["transport_per_quintal"]
    o = _outlook(raw.get("mkt_low"), raw.get("mkt_high"), ref["_low"], ref["_high"], t, c["_total"])
    if o is None:
        return None
    o["market_id"], o["transport_included"] = ref["id"], t is not None
    return o


def scenario_grid(prod: dict, c: dict, ref: dict | None) -> dict | None:
    """Every price x yield x cost combination, calculated here so the screen only picks a cell (no arithmetic in the browser or a model)."""
    raw = prod.get("_raw") or {}
    if ref is None or c["_total"] is None or not raw.get("mkt_low"):
        return None
    cells = {}
    for pf in PRICE_FACTORS:
        for yf in YIELD_FACTORS:
            for cf in COST_FACTORS:
                cells[f"{pf}|{yf}|{cf}"] = _outlook(raw["mkt_low"], raw["mkt_high"], ref["_low"], ref["_high"], ref["transport_per_quintal"], c["_total"], yf, pf, cf)
    return {"price": PRICE_FACTORS, "yield": YIELD_FACTORS, "cost": COST_FACTORS, "cells": cells}


def harvest_window(inp: dict, planting: date | None) -> dict:
    """The farmer's own window, or planting date + the farmer's days-to-harvest estimate. Nothing is guessed from the crop name."""
    s, e = inp.get("harvest_start"), inp.get("harvest_end")
    if s and e:
        return {"start": s, "end": e, "source": "farmer"}
    dl, dh = inp.get("days_to_harvest_low"), inp.get("days_to_harvest_high")
    if planting and dl is not None and dh is not None:
        return {"start": (planting + timedelta(days=int(dl))).isoformat(), "end": (planting + timedelta(days=int(dh))).isoformat(), "source": "planting_plus_estimate"}
    return {"start": None, "end": None, "source": "unavailable"}
