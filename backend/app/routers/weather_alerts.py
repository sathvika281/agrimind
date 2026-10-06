"""Smart Farm Weather Alerts. They live INSIDE the existing Weather feature (the same /farms/{id}/weather path family): no separate page,
no second weather fetch (the existing cached client is used), no model call. Every route is owner-scoped: a foreign or missing farm
gives the same 404, and every query is also scoped by user and farm."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import ratelimit
from ..auth.dependencies import current_user
from ..database import get_db
from ..models import User
from ..services.weather_alerts import store
from .farms import get_owned_farm

router = APIRouter(prefix="/farms/{farm_id}/weather/alerts", tags=["weather-alerts"])


@router.get("", response_model=dict)
def get_alerts(farm_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Evaluate the real forecast for this farm and return its active alerts, recent resolved ones, data freshness, the farm plan link and the
    real executed steps. Repeating the call never duplicates an alert (identity = farm + type + day)."""
    ratelimit.check_weather(user.id)
    farm = get_owned_farm(db, user, farm_id)
    return store.run(db, user, farm)


@router.post("/{alert_id}/dismiss", response_model=dict)
def dismiss_alert(farm_id: int, alert_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Hide an alert. It comes back only if it later becomes MORE serious."""
    farm = get_owned_farm(db, user, farm_id)
    if not store.dismiss(db, user, farm, alert_id):
        raise HTTPException(404, "Alert not found.")
    return {"ok": True}
