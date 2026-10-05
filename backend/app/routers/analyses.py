import hashlib
import json
import logging
import re
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import ratelimit
from ..auth.dependencies import current_user
from ..config import settings
from ..database import get_db
from ..errors import AppError
from ..models import Analysis, Farm, FarmEvent, User
from ..schemas import AnalysisCreate, AnalysisOut, AnalysisResult, RefineRequest, TranslateRequest, WeatherOut
from ..services import ai, images, storage, weather
from .farms import MAX_ID, get_owned_farm

log = logging.getLogger("agrimind.analyses")
router = APIRouter(prefix="/analyses", tags=["analyses"])

NEED_INPUT = "Please describe the problem or add a photo."
STORAGE_FAILURE = "We couldn't save your photo right now. Please try again."
KEY_CONFLICT = "This request was already used for a different analysis. Please start a new analysis."
HISTORY_LIMIT = 3
_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def _utc(dt):
    """SQLite returns naive datetimes; everything we store is UTC, so make every read consistent."""
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


_TELUGU = re.compile(r"[ఀ-౿]")


def effective_language(a: Analysis) -> str:
    """The language the stored result is REALLY in: a 'te' analysis whose text has no Telugu (a model can
    ignore the instruction) is English. Mirrors the frontend's check."""
    r = a.result_json or {}
    if a.language == "te" and _TELUGU.search(f"{r.get('likely_issue', '')} {r.get('explanation', '')}"):
        return "te"
    return "en"


def _translations(a: Analysis) -> dict[str, AnalysisResult]:
    out: dict[str, AnalysisResult] = {}
    original = effective_language(a)
    for lang, res in (a.translations_json or {}).items():
        if lang in ("en", "te") and lang != original:
            try:
                out[lang] = AnalysisResult.model_validate(res)
            except ValidationError:
                continue  # a malformed stored version is ignored, never shown
    return out


def _out(a: Analysis) -> AnalysisOut:
    return AnalysisOut(
        id=a.id,
        farm_id=a.farm_id,
        farm_name=a.farm.name,
        crop=a.crop,
        symptoms=a.symptoms,
        language=a.language,
        input_type=a.input_type or "text",
        has_image=bool(a.image_path),
        result=AnalysisResult.model_validate(a.result_json),
        weather=WeatherOut.model_validate(a.weather_json) if a.weather_json else None,
        weather_note=a.weather_note,
        translations=_translations(a),
        created_at=_utc(a.created_at),
        parent_id=a.parent_id,
        link_kind=a.link_kind,
    )


def _validation_detail(e: ValidationError) -> str:
    msgs = []
    for err in e.errors():
        field = ".".join(str(p) for p in err["loc"])
        msg = str(err["msg"]).removeprefix("Value error, ")
        msgs.append(f"{field}: {msg}" if field else msg)
    return "; ".join(msgs) or "Invalid request."


async def _parse_request(request: Request) -> tuple[AnalysisCreate, images.ValidatedImage | None]:
    """Accepts the Phase 1 JSON body or multipart/form-data with an optional image."""
    ctype = request.headers.get("content-type", "").lower()
    image: images.ValidatedImage | None = None
    form = None
    try:
        if ctype.startswith(("multipart/form-data", "application/x-www-form-urlencoded")):
            form = await request.form()
            body = AnalysisCreate(
                farm_id=form.get("farm_id"),
                crop=str(form.get("crop") or ""),
                symptoms=str(form.get("symptoms") or ""),
                language=form.get("language") if isinstance(form.get("language"), str) else None,
                follow_up_of=form.get("follow_up_of") if isinstance(form.get("follow_up_of"), str) else None,
            )
            upload = form.get("image")
            if upload is not None and not isinstance(upload, str) and getattr(upload, "filename", ""):
                limit = settings.max_image_bytes
                data = await upload.read(limit + 1)
                image = images.validate_image(data, upload.content_type, limit)
        else:
            try:
                payload = await request.json()
            except ValueError:
                raise AppError(422, "Invalid request.")
            body = AnalysisCreate.model_validate(payload)
    except ValidationError as e:
        raise AppError(422, _validation_detail(e))
    except images.ImageError as e:
        raise AppError(e.status, e.message, "image_too_large" if e.status == 413 else "image_invalid")
    finally:
        if form is not None:
            await form.close()  # releases spooled temp files
    if not body.symptoms and image is None:
        raise AppError(422, NEED_INPUT)
    return body, image


# ---------------- idempotency ----------------
_key_locks: dict[tuple[int, str], list] = {}
_key_locks_guard = threading.Lock()


@contextmanager
def _key_lock(user_id: int, key: str):
    """Serialises concurrent requests carrying the same (user, key) within this process."""
    k = (user_id, key)
    with _key_locks_guard:
        entry = _key_locks.setdefault(k, [threading.Lock(), 0])
        entry[1] += 1
    try:
        with entry[0]:
            yield
    finally:
        with _key_locks_guard:
            entry[1] -= 1
            if entry[1] == 0:
                _key_locks.pop(k, None)


def _request_hash(body: AnalysisCreate, image: images.ValidatedImage | None, link: str = "") -> str:
    """Fingerprint of the *meaningful* input, to detect a key reused for a different analysis."""
    norm = {
        "farm_id": body.farm_id,
        "crop": " ".join(body.crop.lower().split()),
        "symptoms": " ".join(body.symptoms.split()),
        "language": body.language,
        "image": hashlib.sha256(image.data).hexdigest() if image else "",
        "link": link,
    }
    return hashlib.sha256(json.dumps(norm, sort_keys=True).encode()).hexdigest()


def recent_history(db: Session, user: User, farm: Farm, crop: str) -> list[ai.HistoryItem]:
    """Up to 3 recent analyses for THIS user, THIS farm and the same crop (never other users')."""
    rows = db.scalars(
        select(Analysis)
        .where(Analysis.user_id == user.id, Analysis.farm_id == farm.id, func.lower(Analysis.crop) == crop.strip().lower())
        .order_by(Analysis.id.desc())
        .limit(HISTORY_LIMIT)
    ).unique()
    items = []
    for a in rows:
        res = a.result_json or {}
        items.append(
            ai.HistoryItem(
                date=a.created_at.date().isoformat() if a.created_at else "",
                crop=a.crop,
                likely_issue=str(res.get("likely_issue", ""))[:120],
                severity=str(res.get("severity", "unknown")),
                symptoms=(a.symptoms or "")[:120],
            )
        )
    return items


def _previous_context(a: Analysis) -> ai.PreviousCheck:
    """What the model may know about the earlier check: its date, assessment, summary, description and photo."""
    res = a.result_json or {}
    img = _stored_image(a)
    return ai.PreviousCheck(
        date=a.created_at.date().isoformat() if a.created_at else "",
        likely_issue=str(res.get("likely_issue", ""))[:160],
        severity=str(res.get("severity", "unknown")),
        verdict=str(res.get("verdict", ""))[:300],
        symptoms=(a.symptoms or "")[:300],
        image=ai.ImageInput(img.data, img.mime_type) if img else None,
    )


DIARY_DAYS, DIARY_ITEMS = 30, 5


def recent_diary(db: Session, user: User, farm: Farm) -> list[ai.DiaryItem]:
    """The farmer's own diary entries from the last 30 days (newest first, at most 5): kind and date only."""
    since = (datetime.now(timezone.utc) - timedelta(days=DIARY_DAYS)).date()
    rows = db.scalars(
        select(FarmEvent)
        .where(FarmEvent.user_id == user.id, FarmEvent.farm_id == farm.id, FarmEvent.event_date >= since)
        .order_by(FarmEvent.event_date.desc(), FarmEvent.id.desc())
        .limit(DIARY_ITEMS)
    ).all()
    return [ai.DiaryItem(date=e.event_date.isoformat(), kind=e.kind) for e in rows]


def _ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000


def _create(
    db: Session, user: User, body: AnalysisCreate, image: images.ValidatedImage | None, key: str | None, rhash: str,
    parent_id: int | None = None, link_kind: str | None = None, follow_up: Analysis | None = None,
) -> AnalysisOut:
    t_total = time.perf_counter()
    farm: Farm = get_owned_farm(db, user, body.farm_id)

    # Weather is optional context: never blocks (bounded by its own budget) and never fails the analysis.
    t = time.perf_counter()
    wx, wx_note = weather.try_weather(farm.location)
    weather_ms = _ms(t)

    ctx = ai.AnalysisContext(
        crop=body.crop,
        symptoms=body.symptoms,
        farm_location=farm.location,
        soil_type=farm.soil_type,
        language=body.language,
        image=ai.ImageInput(image.data, image.mime_type) if image else None,
        weather=wx,
        history=recent_history(db, user, farm, body.crop),
        previous=_previous_context(follow_up) if follow_up is not None else None,
        diary=recent_diary(db, user, farm),
    )
    t = time.perf_counter()
    try:
        if settings.agentic_analysis_enabled:  # LangGraph investigation; the legacy single call below is the default
            from ..services.agentic import agentic_analyze_check
            from ..services.agents.toolbox import AgentToolbox

            result = agentic_analyze_check(ctx, AgentToolbox(db, user, farm, ctx), farm_id=farm.id)
        else:
            result = ai.analyze(ctx)
    except ai.AIServiceError as e:
        log.warning("analysis_failed code=%s provider=%s ai_ms=%.0f weather_ms=%.0f", e.code, settings.ai_provider, _ms(t), weather_ms)
        raise AppError(503, str(e), e.code)
    ai_ms = _ms(t)

    # Persist: image file only after a verified result exists, and removed again if the row can't be committed.
    t = time.perf_counter()
    ref = None
    if image:
        try:
            ref = storage.storage.save(image.data, image.ext)
        except Exception as e:  # noqa: BLE001
            log.error("image_save_failed type=%s", type(e).__name__)
            raise AppError(503, STORAGE_FAILURE, "storage_unavailable")
    try:
        analysis = Analysis(
            user_id=user.id,
            farm_id=farm.id,
            crop=body.crop,
            symptoms=body.symptoms,
            language=ctx.language,
            input_type=ctx.input_type,
            image_path=ref,
            result_json=result.model_dump(),
            weather_json=wx.to_dict() if wx else None,
            weather_note=None if wx else wx_note,
            idempotency_key=key,
            request_hash=rhash if key else None,
            parent_id=parent_id,
            link_kind=link_kind,
        )
        analysis.farm = farm
        db.add(analysis)
        db.commit()
    except Exception as e:  # noqa: BLE001
        db.rollback()
        if ref:
            storage.storage.delete(ref)
        log.error("analysis_persist_failed type=%s image_cleaned=%s", type(e).__name__, bool(ref))
        raise
    db_ms = _ms(t)
    log.info(
        "analysis_done analysis_id=%s provider=%s input=%s weather=%s weather_ms=%.0f ai_ms=%.0f db_ms=%.0f total_ms=%.0f",
        analysis.id, settings.ai_provider, ctx.input_type, "yes" if wx else "no", weather_ms, ai_ms, db_ms, _ms(t_total),
    )
    return _out(analysis)


def _process(
    db: Session, user: User, body: AnalysisCreate, image: images.ValidatedImage | None, key: str | None,
    parent_id: int | None = None, link_kind: str | None = None,
) -> tuple[AnalysisOut, bool]:
    """Returns (analysis, replayed). Idempotency is always scoped to the authenticated user."""
    follow_up = None
    if body.follow_up_of is not None:
        # The earlier check must be the farmer's own and on THIS farm, otherwise it is the same 404 as a missing one.
        follow_up = _owned(db, user, body.follow_up_of)
        if follow_up.farm_id != body.farm_id:
            raise AppError(404, "Analysis not found.")
        parent_id, link_kind = follow_up.id, "followup"
    rhash = _request_hash(body, image, f"{link_kind or ''}:{parent_id or ''}")
    if not key:
        return _create(db, user, body, image, None, rhash, parent_id, link_kind, follow_up), False
    with _key_lock(user.id, key):
        existing = db.scalars(
            select(Analysis).where(Analysis.user_id == user.id, Analysis.idempotency_key == key)
        ).unique().first()
        if existing is not None:
            if existing.request_hash != rhash:
                raise AppError(409, KEY_CONFLICT, "idempotency_conflict")
            log.info("analysis_replayed analysis_id=%s", existing.id)
            return _out(existing), True
        return _create(db, user, body, image, key, rhash, parent_id, link_kind, follow_up), False


@router.post("", response_model=AnalysisOut, status_code=201)
async def create_analysis(
    request: Request, response: Response, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    ratelimit.check_analysis(user.id)
    body, image = await _parse_request(request)
    raw_key = request.headers.get("idempotency-key")
    key = raw_key if raw_key and _IDEMPOTENCY_KEY.match(raw_key) else None  # invalid keys are ignored
    # Blocking work (weather + AI HTTP calls, DB) runs off the event loop.
    out, replayed = await run_in_threadpool(_process, db, user, body, image, key)
    if replayed:
        response.status_code = 200
        response.headers["Idempotent-Replay"] = "true"
    return out


@router.get("", response_model=list[AnalysisOut])
def list_analyses(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Analysis).where(Analysis.user_id == user.id).order_by(Analysis.id.desc())
    ).unique()
    return [_out(a) for a in rows]


def _owned(db: Session, user: User, analysis_id: int) -> Analysis:
    if not 0 < analysis_id <= MAX_ID:  # impossible ids are the same 404 as any missing one (never a driver error)
        raise AppError(404, "Analysis not found.")
    a = db.scalars(
        select(Analysis).where(Analysis.id == analysis_id, Analysis.user_id == user.id)
    ).unique().first()
    if a is None:
        raise AppError(404, "Analysis not found.")
    return a


@router.get("/{analysis_id}", response_model=AnalysisOut)
def get_analysis(analysis_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _out(_owned(db, user, analysis_id))


def _context_from_stored(a: Analysis, language: str) -> ai.AnalysisContext:
    """Rebuild the model input for an existing check from what was STORED (never from the client)."""
    from dataclasses import fields

    wx = None
    if a.weather_json:
        allowed = {f.name for f in fields(ai.WeatherContext)}
        wx = ai.WeatherContext(**{k: v for k, v in a.weather_json.items() if k in allowed})
    image = None
    if a.image_path:
        data = storage.storage.read(a.image_path)
        if data is not None:
            ext = a.image_path.rsplit(".", 1)[-1]
            image = ai.ImageInput(data, images.EXT_TO_MIME.get(ext, "image/jpeg"))
    return ai.AnalysisContext(
        crop=a.crop,
        symptoms=a.symptoms,
        farm_location=a.farm.location,
        soil_type=a.farm.soil_type,
        language=language,
        image=image,
        weather=wx,
    )


def _translate(db: Session, user: User, analysis_id: int, language: str) -> AnalysisOut:
    a = _owned(db, user, analysis_id)
    if language == effective_language(a) or language in _translations(a):
        return _out(a)  # already have this language: no model call
    with _key_lock(user.id, f"translate-{analysis_id}-{language}"):
        db.refresh(a)  # another request may have just stored it
        if language in _translations(a):
            return _out(a)
        try:
            result = ai.analyze(_context_from_stored(a, language))  # same single pipeline + safety verifier
        except ai.AIServiceError as e:
            log.warning("translate_failed analysis_id=%s language=%s code=%s", analysis_id, language, e.code)
            raise AppError(503, str(e), e.code)
        try:
            versions = dict(a.translations_json or {})
            versions[language] = result.model_dump()
            a.translations_json = versions  # a NEW dict so the change is detected; result_json/language untouched
            db.commit()
        except Exception:
            db.rollback()
            raise
        log.info("translate_done analysis_id=%s language=%s", analysis_id, language)
    return _out(a)


@router.post("/{analysis_id}/translate", response_model=AnalysisOut)
async def translate_analysis(
    analysis_id: int, body: TranslateRequest, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    """Write THIS check again in the other language from its original stored inputs (one model call, cached).
    It is a re-generation, not a literal translation. The original result and language are never changed."""
    ratelimit.check_analysis(user.id)
    return await run_in_threadpool(_translate, db, user, analysis_id, body.language)


def _offered(a: Analysis) -> set[tuple[str, str]]:
    """Every (question, option) pair this check actually offered, in any stored language version."""
    versions = [a.result_json or {}, *[v for v in (a.translations_json or {}).values() if isinstance(v, dict)]]
    out: set[tuple[str, str]] = set()
    for v in versions:
        for q in v.get("quick_questions") or []:
            for o in q.get("options") or []:
                out.add((q.get("question"), o))
    return out


def _stored_image(a: Analysis) -> images.ValidatedImage | None:
    if not a.image_path:
        return None
    data = storage.storage.read(a.image_path)
    if data is None:
        return None
    ext = a.image_path.rsplit(".", 1)[-1]
    return images.ValidatedImage(data=data, mime_type=images.EXT_TO_MIME.get(ext, "image/jpeg"), ext=ext)


def _refine(db: Session, user: User, analysis_id: int, body: RefineRequest, key: str | None) -> tuple[AnalysisOut, bool]:
    parent = _owned(db, user, analysis_id)  # foreign / missing / impossible ids: the same 404 as everywhere
    offered = _offered(parent)
    for pair in body.answers:
        if (pair.question, pair.answer) not in offered:
            raise AppError(422, "Please pick one of the offered answers.", "invalid_answer")
    extra = "\n\nFarmer's answers to follow-up questions:\n" + "\n".join(f"- {p.question} {p.answer}" for p in body.answers)
    symptoms = parent.symptoms[: max(0, 4000 - len(extra))] + extra  # stays inside the normal 4000-character limit
    create = AnalysisCreate(farm_id=parent.farm_id, crop=parent.crop, symptoms=symptoms, language=body.language or effective_language(parent))
    return _process(db, user, create, _stored_image(parent), key, parent_id=parent.id, link_kind="refine")


@router.post("/{analysis_id}/refine", response_model=AnalysisOut, status_code=201)
async def refine_analysis(
    analysis_id: int, body: RefineRequest, request: Request, response: Response,
    user: User = Depends(current_user), db: Session = Depends(get_db),
):
    """Answer the quick questions of a stored check: ONE new check is made from the stored text and photo plus the
    farmer's answers (same pipeline, rate limit, safety and idempotency as a normal check) and linked to the original."""
    ratelimit.check_analysis(user.id)
    raw_key = request.headers.get("idempotency-key")
    key = raw_key if raw_key and _IDEMPOTENCY_KEY.match(raw_key) else None
    out, replayed = await run_in_threadpool(_refine, db, user, analysis_id, body, key)
    if replayed:
        response.status_code = 200
        response.headers["Idempotent-Replay"] = "true"
    return out


@router.get("/{analysis_id}/image")
def get_analysis_image(analysis_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Only way to fetch an uploaded image: authenticated and ownership-checked."""
    a = _owned(db, user, analysis_id)
    data = storage.storage.read(a.image_path) if a.image_path else None
    if data is None:
        raise AppError(404, "Image not found.")
    ext = a.image_path.rsplit(".", 1)[-1]
    return Response(
        content=data,
        media_type=images.EXT_TO_MIME.get(ext, "application/octet-stream"),
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=3600"},
    )
