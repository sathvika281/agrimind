"""Crop Economics & Selling Intelligence: its own router and page. Every route is owner-scoped (the same 404 for a foreign or
missing farm). Pure calculation plus the Economics graph: no model call and no network call anywhere in here."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth.dependencies import current_user
from ..database import get_db
from ..models import User
from ..schemas import EconInputsIn
from ..services.economics import store
from .farms import get_owned_farm

router = APIRouter(prefix="/farms/{farm_id}/economics", tags=["economics"])


@router.get("", response_model=dict)
def get_economics(farm_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """The economics of this farm from its saved assumptions and the shared farm context (always freshly calculated: market data ages)."""
    farm = get_owned_farm(db, user, farm_id)
    return store.compute(db, user, farm)


@router.put("/inputs", response_model=dict)
def update_inputs(farm_id: int, body: EconInputsIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Save the farmer's economic assumptions for THIS farm (never the farm profile) and return the recalculated result."""
    farm = get_owned_farm(db, user, farm_id)
    return store.save(db, user, farm, body.model_dump(mode="json"))


@router.get("/market", response_model=dict)
def get_market(farm_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Just the market block: each market's latest price, freshness, range, trend and the net-value comparison."""
    farm = get_owned_farm(db, user, farm_id)
    r = store.compute(db, user, farm)
    return {"markets": r["markets"], "options": r["options"], "providers": r["providers"], "demo": r["demo"], "today": r["today"]}
