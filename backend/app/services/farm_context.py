"""The shared, structured FARM CONTEXT: one place that reads what AgriMind already knows about a farm.

Features read this instead of asking the farmer again. It only reads data the farmer or AgriMind really stored; every
field says where it came from, and `used` lists exactly which sources were read (this is what the Economics page shows
as "context used": nothing in it is invented). Callers must already have verified farm ownership (get_owned_farm); all
queries are additionally scoped by user AND farm, so one farm's context can never include another's.
"""
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Analysis, Farm, FarmEvent, User

RECENT_CHECK_DAYS = 14


@dataclass
class FarmContext:
    farm_id: int
    name: str
    location: str = ""
    crop: str | None = None
    crop_source: str | None = None  # profile | latest_check
    planting_date: date | None = None
    planting_source: str | None = None  # profile | diary
    irrigation: str | None = None
    season: str | None = None
    latest_check: dict | None = None  # {id, crop, severity, checked_on, recent}
    checks_count: int = 0
    diary_count: int = 0
    diary_kinds: list[str] = field(default_factory=list)
    used: list[dict] = field(default_factory=list)

    def public(self) -> dict:
        d = asdict(self)
        d["planting_date"] = self.planting_date.isoformat() if self.planting_date else None
        return d


def load(db: Session, user: User, farm: Farm, today: date | None = None) -> FarmContext:
    today = today or datetime.now(timezone.utc).date()
    ctx = FarmContext(farm_id=farm.id, name=farm.name, location=farm.location or "", irrigation=farm.irrigation_method, season=farm.season)
    used = ctx.used

    profile_fields = [k for k, v in (("crop", farm.primary_crop), ("location", farm.location), ("planting_date", farm.planting_date), ("irrigation", farm.irrigation_method), ("season", farm.season)) if v]
    used.append({"source": "farm_profile", "fields": profile_fields, "count": len(profile_fields)})
    if farm.primary_crop:
        ctx.crop, ctx.crop_source = farm.primary_crop, "profile"
    if farm.planting_date:
        ctx.planting_date, ctx.planting_source = farm.planting_date, "profile"

    n = db.scalar(select(func.count()).select_from(Analysis).where(Analysis.user_id == user.id, Analysis.farm_id == farm.id)) or 0
    ctx.checks_count = n
    row = db.execute(
        select(Analysis.id, Analysis.crop, Analysis.created_at, Analysis.result_json).where(Analysis.user_id == user.id, Analysis.farm_id == farm.id).order_by(Analysis.id.desc()).limit(1)
    ).first()
    if row:
        created = row.created_at if row.created_at.tzinfo else row.created_at.replace(tzinfo=timezone.utc)
        on = created.astimezone(timezone.utc).date()
        sev = (row.result_json or {}).get("severity")
        ctx.latest_check = {"id": row.id, "crop": row.crop, "severity": sev if sev in ("low", "medium", "high") else "unknown", "checked_on": on.isoformat(), "recent": (today - on) <= timedelta(days=RECENT_CHECK_DAYS)}
        if not ctx.crop:
            ctx.crop, ctx.crop_source = row.crop, "latest_check"
    used.append({"source": "crop_checks", "fields": ["latest_check"] if row else [], "count": n})

    events = db.execute(select(FarmEvent.kind, FarmEvent.event_date).where(FarmEvent.user_id == user.id, FarmEvent.farm_id == farm.id).order_by(FarmEvent.event_date.asc())).all()
    ctx.diary_count = len(events)
    ctx.diary_kinds = sorted({e.kind for e in events})
    if ctx.planting_date is None:
        sowed = [e.event_date for e in events if e.kind == "sowed"]
        if sowed:
            ctx.planting_date, ctx.planting_source = sowed[0], "diary"
    used.append({"source": "farm_diary", "fields": ["planting_date"] if ctx.planting_source == "diary" else [], "count": len(events)})
    return ctx
