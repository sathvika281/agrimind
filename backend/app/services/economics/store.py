"""Economics persistence: ONE row per farm holding the farmer's economic assumptions (never the farm profile) and the last result.

The farm profile (crop, location, planting date, irrigation) is read through the shared farm context, not copied here.
Every function expects an already-verified owner (get_owned_farm) and still scopes the query by user AND farm.
"""
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import Farm, FarmEconomics, User
from .. import farm_context
from . import calc, graph

MAX_MARKETS = 5
MAX_PRICES = 10


def default_inputs() -> dict:
    return {"area": None, "area_unit": "acre", "yield_low": None, "yield_high": None, "marketable_low_pct": None, "marketable_high_pct": None,
            "days_to_harvest_low": None, "days_to_harvest_high": None, "harvest_start": None, "harvest_end": None, "costs": {}, "markets": []}


def normalise(raw: dict, previous: dict | None = None) -> dict:
    """Server-side shape of the inputs: fixed cost categories, bounded markets/prices, ids assigned here (never trusted blindly)."""
    kept = {m["id"] for m in (previous or {}).get("markets", [])}
    base = default_inputs()
    for k in base:
        if k in raw and k not in ("costs", "markets"):
            base[k] = raw[k]
    base["costs"] = {k: v for k, v in (raw.get("costs") or {}).items() if k in calc.COST_CATEGORIES and v is not None}
    markets, used = [], set()
    for m in (raw.get("markets") or [])[:MAX_MARKETS]:
        mid = m.get("id") if m.get("id") in kept and m.get("id") not in used else uuid.uuid4().hex[:8]
        used.add(mid)
        prices = sorted({(p["date"]): p["price"] for p in (m.get("prices") or [])[:MAX_PRICES]}.items())
        markets.append({"id": mid, "name": m["name"].strip()[:60], "distance_km": m.get("distance_km"), "transport_per_quintal": m.get("transport_per_quintal"),
                        "prices": [{"date": d, "price": p} for d, p in prices]})
    base["markets"] = markets
    return base


def row(db: Session, farm: Farm) -> FarmEconomics | None:
    return db.scalar(select(FarmEconomics).where(FarmEconomics.farm_id == farm.id, FarmEconomics.user_id == farm.user_id))


def compute(db: Session, user: User, farm: Farm, inputs: dict | None = None, today: date | None = None) -> dict:
    """Run the Economics graph for this farm with its saved (or the given) inputs. Pure read: nothing is written."""
    today = today or datetime.now(timezone.utc).date()
    saved = row(db, farm)
    inp = inputs if inputs is not None else (saved.inputs_json if saved else default_inputs())
    ctx = farm_context.load(db, user, farm, today)
    res = graph.run(ctx, inp, today)
    res["inputs"] = inp
    res["updated_at"] = saved.updated_at.isoformat() if saved else None
    return res


def save(db: Session, user: User, farm: Farm, raw: dict, today: date | None = None) -> dict:
    saved = row(db, farm)
    inp = normalise(raw, saved.inputs_json if saved else None)
    res = compute(db, user, farm, inp, today)
    now = datetime.now(timezone.utc)
    if saved is None:
        saved = FarmEconomics(user_id=user.id, farm_id=farm.id, inputs_json=inp, result_json=res, updated_at=now)
        db.add(saved)
    else:
        saved.inputs_json, saved.result_json, saved.updated_at = inp, res, now
    db.commit()
    res["updated_at"] = now.isoformat()
    return res
