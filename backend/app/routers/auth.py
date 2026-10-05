from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import ratelimit
from ..auth.dependencies import current_user
from ..auth.security import create_token, hash_password, verify_password
from ..config import settings
from ..database import get_db
from ..models import Analysis, Farm, FarmEvent, User
from ..schemas import EventOut, FarmOut, LoginRequest, RegisterRequest, UserOut
from ..services import storage

router = APIRouter(prefix="/auth", tags=["auth"])

# Verified against when the email is unknown, so timing doesn't reveal which emails exist.
_DUMMY_HASH = hash_password("not-a-real-password")


def _set_cookie(response: Response, user_id: int) -> None:
    response.set_cookie(
        settings.cookie_name,
        create_token(user_id),
        max_age=settings.token_hours * 3600,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )


@router.post("/register", response_model=UserOut, status_code=201)
def register(request: Request, body: RegisterRequest, response: Response, db: Session = Depends(get_db)):
    ratelimit.check_register(ratelimit.client_ip(request))
    if db.scalar(select(User).where(User.email == body.email)):
        raise HTTPException(409, "An account with this email already exists.")
    user = User(email=body.email, password_hash=hash_password(body.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "An account with this email already exists.")
    _set_cookie(response, user.id)
    return user


@router.post("/login", response_model=UserOut)
def login(request: Request, body: LoginRequest, response: Response, db: Session = Depends(get_db)):
    ip = ratelimit.client_ip(request)
    ratelimit.check_login(ip, body.email)
    user = db.scalar(select(User).where(User.email == body.email))
    ok = verify_password(body.password, user.password_hash if user else _DUMMY_HASH)
    if not user or not ok:
        raise HTTPException(401, "Incorrect email or password.")
    ratelimit.login_succeeded(ip, body.email)
    _set_cookie(response, user.id)
    return user


@router.post("/logout", status_code=204)
def logout(response: Response):
    response.delete_cookie(settings.cookie_name, path="/")


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user


class DeleteAccountRequest(BaseModel):
    password: str = Field(max_length=200)


@router.delete("/me", status_code=204)
def delete_me(body: DeleteAccountRequest, request: Request, response: Response, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Delete the signed-in account and EVERYTHING it owns (diary, checks and their photos, farms). Needs the password."""
    ip = ratelimit.client_ip(request)
    ratelimit.check_login(ip, user.email)  # same throttle as login: no password guessing through this door
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(403, "Incorrect password.")
    ratelimit.login_succeeded(ip, user.email)
    refs = [r for (r,) in db.execute(select(Analysis.image_path).where(Analysis.user_id == user.id, Analysis.image_path.is_not(None)))]
    try:
        db.execute(delete(FarmEvent).where(FarmEvent.user_id == user.id))
        db.execute(delete(Analysis).where(Analysis.user_id == user.id))
        db.execute(delete(Farm).where(Farm.user_id == user.id))
        db.execute(delete(User).where(User.id == user.id))
        db.commit()  # all or nothing
    except Exception:
        db.rollback()
        raise
    for ref in refs:  # photo files go only after the rows are really gone
        storage.storage.delete(ref)
    response.delete_cookie(settings.cookie_name, path="/")


@router.get("/me/export")
def export_me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Everything the signed-in farmer has stored, as JSON (no password hash, no other user's data, no photo bytes)."""
    from .analyses import _out

    farms = db.scalars(select(Farm).where(Farm.user_id == user.id).order_by(Farm.id)).all()
    checks = db.scalars(select(Analysis).where(Analysis.user_id == user.id).order_by(Analysis.id)).unique().all()
    events = db.scalars(select(FarmEvent).where(FarmEvent.user_id == user.id).order_by(FarmEvent.id)).all()
    payload = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "user": {"email": user.email, "created_at": UserOut.model_validate(user).created_at.isoformat()},
        "farms": [FarmOut.model_validate(f).model_dump(mode="json") for f in farms],
        "checks": [_out(a).model_dump(mode="json") for a in checks],
        "diary": [{**EventOut.model_validate(e).model_dump(mode="json"), "farm_id": e.farm_id} for e in events],
    }
    return JSONResponse(payload, headers={"Content-Disposition": 'attachment; filename="agrimind-data.json"', "Cache-Control": "no-store"})
