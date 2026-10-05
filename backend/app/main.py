import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import settings
from .database import SessionLocal, init_db
from .errors import default_code
from .logging_config import request_id_var, setup_logging
from .middleware import BodyLimitMiddleware, RequestContextMiddleware
from .models import Analysis
from .production import validate_production
from .routers import analyses, auth, farms, health
from .services import storage

setup_logging()
log = logging.getLogger("agrimind")


def _sweep_orphan_uploads() -> None:
    """Remove uploads no analysis references (older than 1 h). Never blocks startup."""
    try:
        with SessionLocal() as db:
            referenced = {r for (r,) in db.execute(select(Analysis.image_path).where(Analysis.image_path.is_not(None)))}
        removed = storage.sweep_orphans(referenced)
        if removed:
            log.info("orphan_uploads_removed count=%s", removed)
    except Exception as e:  # noqa: BLE001
        log.warning("orphan_sweep_failed type=%s", type(e).__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.jwt_secret  # fail fast if JWT_SECRET is missing or too short
    validate_production()  # APP_ENV=production refuses unsafe settings (no-op otherwise)
    init_db()
    _sweep_orphan_uploads()
    yield


app = FastAPI(title="AgriMind API", lifespan=lifespan)

# Added innermost -> outermost: body guard, CORS, then request context (ids, headers, access log, 500s).
app.add_middleware(BodyLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "Idempotency-Key", "X-Request-ID"],
    expose_headers=["X-Request-ID", "Retry-After", "Idempotent-Replay"],
)
app.add_middleware(RequestContextMiddleware)

for router in (auth.router, farms.router, analyses.router, health.router):
    app.include_router(router)


@app.get("/health")
def health_check():
    """Liveness only: the app process is up. Never depends on Gemini, weather or the database."""
    return {"status": "ok"}


def _error_body(status: int, detail, code: str) -> dict:
    body = {"detail": detail, "code": code}
    if status >= 500:  # support id for server-side failures; 4xx bodies stay identical for equivalent failures
        body["request_id"] = request_id_var.get()
    return body


@app.exception_handler(StarletteHTTPException)
async def http_error(_: Request, exc: StarletteHTTPException):
    code = getattr(exc, "code", None) or default_code(exc.status_code)
    return JSONResponse(_error_body(exc.status_code, exc.detail, code), status_code=exc.status_code, headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def validation_handler(_: Request, exc: RequestValidationError):
    msgs = []
    for e in exc.errors():
        field = ".".join(str(p) for p in e["loc"] if p not in ("body", "query", "path"))
        msg = str(e["msg"]).removeprefix("Value error, ")
        msgs.append(f"{field}: {msg}" if field else msg)
    return JSONResponse(_error_body(422, "; ".join(msgs) or "Invalid request.", "invalid_request"), status_code=422)
