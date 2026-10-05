from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from ..config import settings
from ..database import engine
from ..services import weather

router = APIRouter(tags=["health"])


def _db_ok() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001 - never leak details
        return False


def _uploads_ok() -> bool:
    try:
        d = settings.uploads_dir
        d.mkdir(parents=True, exist_ok=True)
        probe = d / ".healthcheck"
        probe.write_bytes(b"ok")
        probe.unlink(missing_ok=True)
        return True
    except Exception:  # noqa: BLE001
        return False


def _ai_status() -> dict:
    name = settings.ai_provider
    if name == "demo":
        return {"provider": "demo", "status": "ok"}
    if name == "gemini":
        return {"provider": "gemini", "status": "ok" if settings.gemini_api_key else "not_configured"}
    return {"provider": name, "status": "not_configured"}


def _weather_status() -> str:
    try:
        return "ok" if weather.check_reachable() else "unavailable"
    except Exception:  # noqa: BLE001
        return "unavailable"


@router.get("/health/dependencies")
def dependencies():
    """High-level dependency status. Only the database can make this return 503;
    Gemini / Open-Meteo problems are reported as degraded without failing the endpoint.
    No secrets and no provider error text are exposed."""
    db = _db_ok()
    uploads = _uploads_ok()
    ai = _ai_status()
    wx = _weather_status()
    degraded = (not uploads) or ai["status"] != "ok" or wx != "ok"
    overall = "unavailable" if not db else ("degraded" if degraded else "ok")
    body = {
        "status": overall,
        "database": "ok" if db else "unavailable",
        "uploads": "ok" if uploads else "unavailable",
        "ai": ai,
        "weather": wx,
    }
    return JSONResponse(body, status_code=200 if db else 503)
