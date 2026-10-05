from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import User
from .security import decode_token


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    unauth = HTTPException(status_code=401, detail="Please log in to continue.")
    token = request.cookies.get(settings.cookie_name)
    if not token:
        raise unauth
    user_id = decode_token(token)
    if user_id is None:
        raise unauth
    user = db.get(User, user_id)
    if user is None:
        raise unauth
    return user
