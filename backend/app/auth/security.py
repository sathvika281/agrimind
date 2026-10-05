from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from ..config import settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


def create_token(user_id: int) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=settings.token_hours)
    return jwt.encode({"sub": str(user_id), "exp": exp}, settings.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> int | None:
    try:
        # exp and sub are mandatory: a token without an expiry must never be accepted as "valid forever".
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"], options={"require": ["exp", "sub"]})
        return int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None
