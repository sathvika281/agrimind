"""Farm plan: the Adaptive Farm Planning feature. Own router, own page; every route is owner-scoped (same 404 for a
foreign or missing farm) and rate-limited like weather. No model call anywhere in here."""
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import ratelimit
from ..auth.dependencies import current_user
from ..database import get_db
from ..models import FarmPlan, User
from ..schemas import PlanInputsIn, PlanOut, PlanVersionOut
from ..services.planning import store
from .farms import get_owned_farm

router = APIRouter(prefix="/farms/{farm_id}/plan", tags=["plan"])


def _out(db: Session, row: FarmPlan, changed: bool = False, source: str = "none", note: str | None = None) -> PlanOut:
    created = row.created_at if row.created_at.tzinfo else row.created_at.replace(tzinfo=__import__("datetime").timezone.utc)
    n = db.scalar(select(func.count()).select_from(FarmPlan).where(FarmPlan.farm_id == row.farm_id)) or 1
    return PlanOut(
        farm_id=row.farm_id, version=row.version, created_at=created, trigger=row.trigger, inputs=row.inputs_json, plan=row.plan_json,
        changes=row.changes_json, forecast=row.forecast_json or [], changed=changed, forecast_source=source, forecast_note=note, versions=n,
    )


@router.get("", response_model=PlanOut | None)
def get_plan(farm_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """The stored current plan (no weather call). null if there is none yet."""
    farm = get_owned_farm(db, user, farm_id)
    row = store.latest(db, farm)
    return _out(db, row) if row else None


@router.post("/refresh", response_model=PlanOut)
def refresh_plan(farm_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Fetch the real forecast, re-assess the plan, and store a NEW version only if something material changed."""
    ratelimit.check_weather(user.id)
    farm = get_owned_farm(db, user, farm_id)
    row, created, source, note = store.refresh(db, user, farm)
    return _out(db, row, created, source, note)


@router.put("/inputs", response_model=PlanOut)
def update_inputs(farm_id: int, body: PlanInputsIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """The farmer's planned activities and reported field condition. Re-assesses the plan with them."""
    ratelimit.check_weather(user.id)
    farm = get_owned_farm(db, user, farm_id)
    row, created, source, note = store.refresh(db, user, farm, new_inputs=body.model_dump(mode="json"))
    return _out(db, row, created, source, note)


@router.get("/history", response_model=list[PlanVersionOut])
def plan_history(farm_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    farm = get_owned_farm(db, user, farm_id)
    return [
        PlanVersionOut(version=r.version, created_at=r.created_at if r.created_at.tzinfo else r.created_at.replace(tzinfo=__import__("datetime").timezone.utc),
                       trigger=r.trigger, changes=r.changes_json, items=len(r.plan_json.get("items", [])))
        for r in store.history(db, farm)
    ]
