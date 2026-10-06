"""Persistence + orchestration for the Farm plan: versions are kept, the agent decides whether a new one is needed.

All queries are scoped by user AND farm; the router has already checked ownership with get_owned_farm().
"""
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ...models import Analysis, Farm, FarmPlan, User
from .. import weather
from ..insights import is_unclear
from .agent import (ACTIVITY_KINDS, FIELD_CONDITIONS, MAX_ACTIVITIES, AdaptivePlanningAgent, CropState, Previous)

MAX_VERSIONS = 100  # per farm; the oldest are pruned beyond this
agent = AdaptivePlanningAgent()


def latest(db: Session, farm: Farm) -> FarmPlan | None:
    return db.scalars(select(FarmPlan).where(FarmPlan.farm_id == farm.id).order_by(FarmPlan.version.desc()).limit(1)).first()


def history(db: Session, farm: Farm, limit: int = 50) -> list[FarmPlan]:
    return list(db.scalars(select(FarmPlan).where(FarmPlan.farm_id == farm.id).order_by(FarmPlan.version.desc()).limit(limit)))


def default_inputs() -> dict:
    return {"activities": [], "field_condition": "none"}


def normalise_inputs(raw: dict, previous: dict | None = None) -> dict:
    """Server-side shape of the farmer's inputs: fixed kinds, bounded count, ids assigned here (never trusted blindly)."""
    kept_ids = {a["id"] for a in (previous or {}).get("activities", [])}
    out, used = [], set()
    for a in (raw.get("activities") or [])[:MAX_ACTIVITIES]:
        aid = a.get("id") if a.get("id") in kept_ids and a.get("id") not in used else uuid.uuid4().hex[:8]
        used.add(aid)
        out.append({"id": aid, "kind": a["kind"], "date": a["date"], "note": (a.get("note") or "").strip()[:120]})
    out.sort(key=lambda a: (a["date"], a["id"]))
    fc = raw.get("field_condition") or "none"
    return {"activities": out, "field_condition": fc if fc in FIELD_CONDITIONS else "none"}


def latest_check(db: Session, user: User, farm: Farm) -> CropState:
    from ...routers.farms import _without_refined_parents  # lazy: routers import services

    rows = db.execute(
        select(Analysis.id, Analysis.crop, Analysis.created_at, Analysis.result_json, Analysis.parent_id, Analysis.link_kind)
        .where(Analysis.user_id == user.id, Analysis.farm_id == farm.id).order_by(Analysis.id.desc()).limit(20)
    ).all()
    rows = _without_refined_parents(rows)
    if not rows:
        return CropState()
    r = rows[0]
    res = r.result_json or {}
    sev, unc = res.get("severity"), res.get("uncertainty_level")
    created = r.created_at if r.created_at.tzinfo else r.created_at.replace(tzinfo=timezone.utc)
    return CropState(check_id=r.id, crop=r.crop, issue=str(res.get("likely_issue", "")), severity=sev if sev in ("low", "medium", "high") else "unknown",
                     uncertainty=unc if unc in ("low", "some", "high") else "unknown", checked_on=created.astimezone(timezone.utc).date())


def _farm_facts(farm: Farm) -> dict:
    return {"primary_crop": farm.primary_crop, "irrigation_method": farm.irrigation_method, "planting_date": farm.planting_date, "location": farm.location}


def _sources(crop: CropState, plan: dict) -> list[dict]:
    """Background passages from the existing local corpus, only when a possible problem exists and passages really match."""
    if plan["concern"]["level"] != "possible" or not plan["concern"]["issue"]:
        return []
    try:
        from ..agents.knowledge import display_title
        from ..rag.retrieval import get_index

        idx = get_index()
        hits = idx.search(f"{crop.crop or ''} {plan['concern']['issue']}", crop=crop.crop or "", k=2)
    except Exception:  # noqa: BLE001  (a missing/broken corpus just means no sources)
        return []
    seen, out = set(), []
    for c, _s in hits:
        if c.source_url not in seen:
            seen.add(c.source_url)
            out.append({"title": display_title(c.title, c.crop, c.topic, c.source_url), "institution": c.institution, "url": c.source_url})
    return out


def refresh(db: Session, user: User, farm: Farm, new_inputs: dict | None = None, today: date | None = None) -> tuple[FarmPlan, bool, str, str | None]:
    """Fetch the REAL forecast, run the agent, store a new version only if something material changed.
    Returns (current version, created_new, forecast_source, forecast_note)."""
    today = today or datetime.now(timezone.utc).date()
    prev_row = latest(db, farm)
    prev = Previous(prev_row.plan_json, prev_row.inputs_json, prev_row.forecast_json, prev_row.check_id) if prev_row else None
    inputs = normalise_inputs(new_inputs, prev_row.inputs_json if prev_row else None) if new_inputs is not None else (prev_row.inputs_json if prev_row else default_inputs())
    days, note = weather.try_forecast(farm.location, budget=weather.ROUTE_BUDGET_S)
    live = [d.to_dict() for d in days] if days else None
    # a forecast whose first day is already behind us would be stale: use only days from today on
    if live:
        live = [d for d in live if d["date"] >= today.isoformat()] or None
        # the provider's local date can be ahead of or behind UTC by hours: align "today" to the first real day
        if live and live[0]["date"] > today.isoformat():
            today = max(today, date.fromisoformat(live[0]["date"]))
    crop = latest_check(db, user, farm)
    out = agent.run(inputs=inputs, live_forecast=live, crop=crop, farm=_farm_facts(farm), today=today, prev=prev)
    if not out.create and prev_row is not None:
        return prev_row, False, out.forecast_source, None if out.forecast_source == "live" else note
    plan = {**out.plan, "sources": _sources(crop, out.plan)}
    version = (prev_row.version + 1) if prev_row else 1
    row = FarmPlan(user_id=user.id, farm_id=farm.id, version=version, trigger=",".join(out.reasons)[:60] or "first_plan", inputs_json=inputs, plan_json=plan,
                   changes_json=out.changes, forecast_json=(live if live else (prev_row.forecast_json if prev_row and out.forecast_source == "last_snapshot" else None)), check_id=crop.check_id)
    db.add(row)
    db.flush()
    count = db.scalar(select(func.count()).select_from(FarmPlan).where(FarmPlan.farm_id == farm.id)) or 0
    if count > MAX_VERSIONS:  # keep the newest MAX_VERSIONS
        old = db.scalars(select(FarmPlan.id).where(FarmPlan.farm_id == farm.id).order_by(FarmPlan.version.asc()).limit(count - MAX_VERSIONS)).all()
        db.execute(delete(FarmPlan).where(FarmPlan.id.in_(old)))
    db.commit()
    return row, True, out.forecast_source, None if out.forecast_source == "live" else note
