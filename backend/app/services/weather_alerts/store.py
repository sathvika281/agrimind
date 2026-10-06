"""Smart Farm Weather Alerts: evaluation, identity, lifecycle and the Farm plan link, for ONE owner-verified farm.

Pipeline (each step is recorded as it really runs; a step that could not run is recorded as skipped, never faked):

    weather_context   the farm's saved location + crop/planting facts through the shared farm context
    forecast          the EXISTING weather client's cached daily forecast (OpenWeather first, Open-Meteo backup): no second fetch
    evaluate          rules.evaluate: deterministic alert events with severity
    reconcile         stable identity (farm + type + day): new -> active, changed -> updated, gone -> resolved
    plan_check        impact.plan_impact against the stored Farm plan (read only)

Weather never re-plans. The only plan action is the existing plan refresh, started by the farmer.
Every function expects an already-verified owner (get_owned_farm) and still scopes queries by user AND farm.
"""
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import Farm, User, WeatherAlert
from .. import farm_context, weather
from ..planning import store as plan_store
from ..planning.agent import FORECAST_RAIN_SHIFT_MM, FORECAST_TEMP_SHIFT_C
from . import impact, rules

STALE_AFTER_MIN = 180  # a forecast fetched longer ago than this is shown as "may be outdated"
RECENT_DAYS = 7  # resolved alerts stay visible in "Recent weather alerts" this long
WIND_SHIFT_MS = 5.0
# the one number that defines an alert's size, and how far it must move to count as a real update (reuses the plan's shift sizes)
PRIMARY = {"heavy_rain": ("rain_mm", FORECAST_RAIN_SHIFT_MM), "thunderstorm": ("rain_mm", FORECAST_RAIN_SHIFT_MM), "strong_wind": ("speed_ms", WIND_SHIFT_MS),
           "high_temperature": ("temp_max_c", FORECAST_TEMP_SHIFT_C), "low_temperature": ("temp_min_c", FORECAST_TEMP_SHIFT_C), "temperature_change": ("change_c", FORECAST_TEMP_SHIFT_C)}


def _utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _moved(kind: str, old: dict, new: dict) -> bool:
    key, shift = PRIMARY[kind]
    a, b = old.get(key), new.get(key)
    return a is not None and b is not None and abs(float(a) - float(b)) >= shift


def reconcile(db: Session, user: User, farm: Farm, found: list[dict], today: date, now: datetime, source: str | None, fetched_at: datetime | None) -> dict:
    """Make the stored alerts match the forecast. Returns counts; never creates a second alert for the same (type, day)."""
    rows = {r.fingerprint: r for r in db.scalars(select(WeatherAlert).where(WeatherAlert.farm_id == farm.id, WeatherAlert.user_id == user.id))}
    counts = {"new": 0, "updated": 0, "resolved": 0, "unchanged": 0}
    seen = set()
    for a in found:
        seen.add(a["key"])
        r = rows.get(a["key"])
        if r is None:
            db.add(WeatherAlert(user_id=user.id, farm_id=farm.id, fingerprint=a["key"], type=a["type"], severity=a["severity"], event_date=date.fromisoformat(a["event_date"]),
                                values_json=a["values"], source=source, forecast_fetched_at=fetched_at, status="active", first_seen_at=now, updated_at=now))
            counts["new"] += 1
            continue
        changed = r.severity != a["severity"] or _moved(a["type"], r.values_json or {}, a["values"])
        escalated = rules.RANK[a["severity"]] > rules.RANK.get(r.dismissed_severity or "", -1)
        r.values_json, r.source, r.forecast_fetched_at = a["values"], source, fetched_at  # always the latest real numbers
        if r.status == "resolved":
            r.status, r.resolved_at, r.updated_at, r.severity = "updated", None, now, a["severity"]
            counts["updated"] += 1
        elif r.status == "dismissed":
            if r.severity != a["severity"] and escalated:  # a dismissed alert comes back only if it got more serious
                r.status, r.severity, r.updated_at, r.dismissed_severity = "updated", a["severity"], now, None
                counts["updated"] += 1
            else:
                r.severity = a["severity"]
                counts["unchanged"] += 1
        elif changed:
            r.status, r.severity, r.updated_at = "updated", a["severity"], now
            counts["updated"] += 1
        else:
            counts["unchanged"] += 1
    for fp, r in rows.items():  # the event is gone from the forecast (or already past): resolve it
        if fp not in seen and r.status != "resolved":
            r.status, r.resolved_at = "resolved", now
            counts["resolved"] += 1
    db.commit()
    return counts


def _alert_out(r: WeatherAlert, impact_: dict | None) -> dict:
    return {"id": r.id, "type": r.type, "severity": r.severity, "event_date": r.event_date.isoformat(), "values": r.values_json or {}, "status": r.status, "source": r.source,
            "first_seen_at": _utc(r.first_seen_at).isoformat(), "updated_at": _utc(r.updated_at).isoformat(), "resolved_at": _utc(r.resolved_at).isoformat() if r.resolved_at else None,
            "forecast_fetched_at": _utc(r.forecast_fetched_at).isoformat() if r.forecast_fetched_at else None, "plan_impact": impact_}


def run(db: Session, user: User, farm: Farm, today: date | None = None, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    today = today or now.date()
    steps: list[dict] = []
    ctx = farm_context.load(db, user, farm, today)
    steps.append({"node": "weather_context", "status": "ok" if farm.location.strip() else "skipped", "note": "location_resolved" if farm.location.strip() else "no_location"})

    days, note = weather.try_forecast(farm.location, budget=weather.ROUTE_BUDGET_S)
    dd = [d.to_dict() for d in days] if days else None
    fetched = _utc(datetime.fromisoformat(dd[0]["fetched_at"])) if dd and dd[0].get("fetched_at") else None
    source = (dd[0].get("source") if dd else None)
    age_min = round((now - fetched).total_seconds() / 60) if fetched else None
    if dd is None:
        state = "no_location" if not farm.location.strip() else "unavailable"
    elif age_min is not None and age_min > STALE_AFTER_MIN:
        state = "stale"
    else:
        state = "live"
    steps.append({"node": "forecast", "status": "ok" if dd else "skipped", "note": (source or "unavailable") if dd else state})

    counts = None
    if dd is not None and state == "live":
        found = rules.evaluate(dd, today)
        steps.append({"node": "evaluate", "status": "ok", "note": f"{len(found)}"})
        counts = reconcile(db, user, farm, found, today, now, source, fetched)
        steps.append({"node": "reconcile", "status": "ok", "note": f"{counts['new']}/{counts['updated']}/{counts['resolved']}"})
    else:
        steps.append({"node": "evaluate", "status": "skipped", "note": "forecast_" + state})
        steps.append({"node": "reconcile", "status": "skipped", "note": "forecast_" + state})  # an unknown forecast never resolves or creates alerts

    rows = list(db.scalars(select(WeatherAlert).where(WeatherAlert.farm_id == farm.id, WeatherAlert.user_id == user.id).order_by(WeatherAlert.event_date, WeatherAlert.id)))
    plan_row = plan_store.latest(db, farm)
    plan_json, plan_fc = (plan_row.plan_json, plan_row.forecast_json) if plan_row else (None, None)
    steps.append({"node": "plan_check", "status": "ok" if plan_row else "skipped", "note": f"v{plan_row.version}" if plan_row else "no_plan"})

    active = []
    for r in rows:
        if r.status in ("active", "updated") and r.event_date >= today:
            imp = impact.plan_impact({"type": r.type, "event_date": r.event_date.isoformat()}, plan_json, plan_fc, dd, plan_row.version if plan_row else None)
            active.append(_alert_out(r, imp))
    recent = [_alert_out(r, None) for r in rows if r.status == "resolved" and r.resolved_at and _utc(r.resolved_at) >= now - timedelta(days=RECENT_DAYS)]
    recent.sort(key=lambda a: a["resolved_at"], reverse=True)
    active.sort(key=lambda a: (a["event_date"], -rules.RANK[a["severity"]]))
    last_known = max((_utc(r.forecast_fetched_at) for r in rows if r.forecast_fetched_at), default=None)
    return {
        "farm": {"id": farm.id, "name": farm.name, "location": farm.location, "crop": ctx.crop, "irrigation": ctx.irrigation, "planting_date": ctx.planting_date.isoformat() if ctx.planting_date else None},
        "freshness": {"state": state, "source": source, "fetched_at": fetched.isoformat() if fetched else None, "age_minutes": age_min,
                      "last_known_at": last_known.isoformat() if last_known else None, "note": note},
        "alerts": active, "recent": recent[:10], "steps": steps, "plan": {"has_plan": plan_row is not None, "version": plan_row.version if plan_row else None},
        "counts": counts, "forecast": dd or [], "today": today.isoformat(),
    }


def dismiss(db: Session, user: User, farm: Farm, alert_id: int) -> bool:
    r = db.scalar(select(WeatherAlert).where(WeatherAlert.id == alert_id, WeatherAlert.farm_id == farm.id, WeatherAlert.user_id == user.id))
    if r is None:
        return False
    r.status, r.dismissed_severity = "dismissed", r.severity
    db.commit()
    return True
