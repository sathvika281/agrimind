from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth.dependencies import current_user
from ..database import get_db
from ..models import Analysis, Farm, FarmEvent, User
from .. import ratelimit
from ..schemas import DecisionOut, EventCreate, EventOut, FarmCreate, FarmOut, FarmUpdate, FarmWeatherOut, InsightsOut, ProactiveOut, WeatherOut
from ..services import decision_support as decision_service
from ..services import insights as insights_service
from ..services import proactive_intelligence as proactive_service
from ..services import weather as weather_service
from ..services import weather_risk

router = APIRouter(prefix="/farms", tags=["farms"])


CONTEXT_FIELDS = ("primary_crop", "irrigation_method", "season", "planting_date", "notes")
MAX_ID = 2**63 - 1  # SQLite INTEGER range; larger ids can't exist and must not reach the driver (it raises -> 500)


def get_owned_farm(db: Session, user: User, farm_id: int) -> Farm:
    """Single ownership check. Missing, foreign and out-of-range farms give the same 404."""
    if not 0 < farm_id <= MAX_ID:
        raise HTTPException(404, "Farm not found.")
    farm = db.scalar(select(Farm).where(Farm.id == farm_id, Farm.user_id == user.id))
    if farm is None:
        raise HTTPException(404, "Farm not found.")
    return farm


@router.post("", response_model=FarmOut, status_code=201)
def create_farm(body: FarmCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    farm = Farm(user_id=user.id, **body.model_dump())
    if any(getattr(body, f) is not None for f in CONTEXT_FIELDS):
        farm.context_updated_at = datetime.now(timezone.utc)
    db.add(farm)
    db.commit()
    return farm


@router.get("", response_model=list[FarmOut])
def list_farms(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return db.scalars(select(Farm).where(Farm.user_id == user.id).order_by(Farm.id.desc())).all()


@router.get("/{farm_id}", response_model=FarmOut)
def get_farm(farm_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return get_owned_farm(db, user, farm_id)


@router.patch("/{farm_id}", response_model=FarmOut)
def update_farm(farm_id: int, body: FarmUpdate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Edit what the farmer entered about THIS farm. Omitted fields are unchanged; null/empty clears an optional one.
    Never touches any stored analysis. Same 404 for foreign/missing farms."""
    farm = get_owned_farm(db, user, farm_id)
    context_changed = False
    for field, value in body.model_dump(exclude_unset=True).items():
        if field in ("location", "soil_type") and value is None:
            value = ""  # these two columns are never NULL
        if getattr(farm, field) != value:
            setattr(farm, field, value)
            context_changed = context_changed or field in CONTEXT_FIELDS
    if context_changed:
        farm.context_updated_at = datetime.now(timezone.utc)
    db.commit()
    return farm


@router.get("/{farm_id}/weather", response_model=FarmWeatherOut)
def get_farm_weather(farm_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Real weather for this farm's saved location (Open-Meteo, cached, bounded). Never fails the page:
    if weather can't be fetched the answer is {weather: null, note: why}."""
    ratelimit.check_weather(user.id)
    farm = get_owned_farm(db, user, farm_id)
    wx, note = weather_service.try_weather(farm.location)
    return FarmWeatherOut(
        weather=WeatherOut.model_validate(wx.to_dict()) if wx else None,
        note=None if wx else note,
        risks=weather_risk.weather_risks(wx.to_dict()) if wx else [],
    )


INSIGHTS_LIMIT = 100  # newest checks considered; one column-only query, no joins


def _without_refined_parents(found):
    """A refinement (answers to the quick questions) replaces the check it refines, so one incident is not counted twice
    in history, trends or attention. Follow-ups are separate observations over time and are kept."""
    superseded = {r.parent_id for r in found if r.link_kind == "refine" and r.parent_id is not None}
    return [r for r in found if r.id not in superseded]


@router.get("/{farm_id}/insights", response_model=InsightsOut)
def get_farm_insights(farm_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """What THIS farm's stored checks show over time. Deterministic (no model call) and built only from the
    farmer's own completed checks; never from sample telemetry or weather. Same 404 for foreign/missing farms."""
    farm = get_owned_farm(db, user, farm_id)
    rows = db.execute(
        select(Analysis.id, Analysis.crop, Analysis.created_at, Analysis.result_json, Analysis.parent_id, Analysis.link_kind)
        .where(Analysis.user_id == user.id, Analysis.farm_id == farm.id)
        .order_by(Analysis.id.desc())
        .limit(INSIGHTS_LIMIT)
    ).all()
    rows = _without_refined_parents(rows)
    checks = [
        {
            "id": r.id,
            "crop": r.crop,
            "created_at": r.created_at,
            "likely_issue": (r.result_json or {}).get("likely_issue", ""),
            "severity": (r.result_json or {}).get("severity"),
        }
        for r in rows
    ]
    return InsightsOut(farm_id=farm.id, **insights_service.build_insights(checks))


@router.get("/{farm_id}/decision-support", response_model=DecisionOut)
def get_farm_decision_support(
    farm_id: int, analysis_id: int | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    """A conservative, RULE-BASED next step from evidence AgriMind already stores (the check, this farm's history up
    to that check, and what the farmer recorded). Read-only and deterministic: no model call, no writes. Without
    analysis_id it describes the farm's latest check; with one, the farm AS OF that check. Foreign, missing or
    impossible ids all give the same 404."""
    farm = get_owned_farm(db, user, farm_id)
    q = select(Analysis.id, Analysis.crop, Analysis.created_at, Analysis.input_type, Analysis.result_json, Analysis.parent_id, Analysis.link_kind).where(
        Analysis.user_id == user.id, Analysis.farm_id == farm.id
    )
    if analysis_id is not None:
        if not 0 < analysis_id <= MAX_ID:
            raise HTTPException(404, "Analysis not found.")
        q = q.where(Analysis.id <= analysis_id)  # time-correct: later checks never influence an earlier decision
    found = db.execute(q.order_by(Analysis.id.desc()).limit(INSIGHTS_LIMIT)).all()
    if analysis_id is not None and (not found or found[0].id != analysis_id):
        raise HTTPException(404, "Analysis not found.")  # same answer for another user's, another farm's, or a missing check
    found = _without_refined_parents(found)
    rows = []
    for r in found:
        res = r.result_json or {}
        rows.append({
            "id": r.id, "crop": r.crop, "created_at": r.created_at, "input_type": r.input_type,
            "likely_issue": res.get("likely_issue", ""), "severity": res.get("severity"),
            "uncertainty_level": res.get("uncertainty_level"), "image_quality": res.get("image_quality"),
        })
    context = {f: getattr(farm, f) for f in ("primary_crop", "irrigation_method", "season", "planting_date", "soil_type", "location")}
    return DecisionOut(farm_id=farm.id, **decision_service.decide(rows, context, analysis_id))


@router.get("/{farm_id}/proactive", response_model=ProactiveOut)
def get_farm_proactive(farm_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """What in THIS farm's stored checks deserves attention now (at most 3 items). Read-only and deterministic: it only
    combines the Phase 9 history statistics and the Phase 11 decision for the latest check. No model call, no
    external request, no writes. Foreign, missing or impossible farm ids all give the same 404."""
    farm = get_owned_farm(db, user, farm_id)
    found = db.execute(
        select(Analysis.id, Analysis.crop, Analysis.created_at, Analysis.input_type, Analysis.result_json, Analysis.parent_id, Analysis.link_kind)
        .where(Analysis.user_id == user.id, Analysis.farm_id == farm.id)
        .order_by(Analysis.id.desc())
        .limit(INSIGHTS_LIMIT)
    ).all()
    found = _without_refined_parents(found)
    rows = []
    for r in found:
        res = r.result_json or {}
        rows.append({
            "id": r.id, "crop": r.crop, "created_at": r.created_at, "input_type": r.input_type,
            "likely_issue": res.get("likely_issue", ""), "severity": res.get("severity"),
            "uncertainty_level": res.get("uncertainty_level"), "image_quality": res.get("image_quality"),
        })
    context = {f: getattr(farm, f) for f in ("primary_crop", "irrigation_method", "season", "planting_date", "soil_type", "location")}
    insights = insights_service.build_insights(rows)
    decision = decision_service.decide(rows, context)
    return ProactiveOut(farm_id=farm.id, **proactive_service.build_proactive_items(insights, decision))


EVENTS_LIMIT = 100  # newest diary entries returned
EVENTS_MAX = 1000  # per farm, so one account can't grow without bound


@router.get("/{farm_id}/events", response_model=list[EventOut])
def list_farm_events(farm_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """The farmer's own diary for THIS farm, newest first. Same 404 for foreign/missing farms."""
    farm = get_owned_farm(db, user, farm_id)
    return db.scalars(
        select(FarmEvent)
        .where(FarmEvent.user_id == user.id, FarmEvent.farm_id == farm.id)
        .order_by(FarmEvent.event_date.desc(), FarmEvent.id.desc())
        .limit(EVENTS_LIMIT)
    ).all()


@router.post("/{farm_id}/events", response_model=EventOut, status_code=201)
def add_farm_event(farm_id: int, body: EventCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    farm = get_owned_farm(db, user, farm_id)
    count = db.scalar(select(func.count()).select_from(FarmEvent).where(FarmEvent.farm_id == farm.id))
    if count >= EVENTS_MAX:
        raise HTTPException(409, "The diary for this farm is full.")
    ev = FarmEvent(user_id=user.id, farm_id=farm.id, kind=body.kind, note=body.note, event_date=body.event_date or datetime.now(timezone.utc).date())
    db.add(ev)
    db.commit()
    return ev


@router.delete("/{farm_id}/events/{event_id}", status_code=204)
def delete_farm_event(farm_id: int, event_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    farm = get_owned_farm(db, user, farm_id)
    ev = db.scalar(select(FarmEvent).where(FarmEvent.id == event_id, FarmEvent.farm_id == farm.id, FarmEvent.user_id == user.id)) if 0 < event_id <= MAX_ID else None
    if ev is None:
        raise HTTPException(404, "Diary entry not found.")
    db.delete(ev)
    db.commit()
