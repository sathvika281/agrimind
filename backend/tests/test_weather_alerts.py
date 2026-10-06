"""Smart Farm Weather Alerts (inside the existing Weather feature): provider parsing of wind/gust/thunderstorm, deterministic rules and
severity, identity/dedup, lifecycle, data freshness, ownership, the Farm plan link, and the guarantees (no fabricated weather, no extra
fetches, no re-planning from Weather). The network is never used (providers are emulated) and no model is ever called."""
import json
import time
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest

from app.models import FarmPlan, WeatherAlert
from app.services import weather
from app.services.planning import agent as plan_agent
from app.services.weather_alerts import impact, rules, store
from tests.test_phase15 import _db_world, _login

TODAY = datetime.now(timezone.utc).date()


def iso(n=0):
    return (TODAY + timedelta(days=n)).isoformat()


def D(offset=0, rain=0.0, tmax=31.0, tmin=24.0, wind=None, gust=None, storm=None, pop=40.0):
    return {"date": iso(offset), "rain_mm": rain, "temp_min_c": tmin, "temp_max_c": tmax, "rain_probability_pct": pop, "wind_ms": wind, "gust_ms": gust, "thunderstorm": storm}


def mkdays(rains=(0, 0, 0, 0, 0), age_min=1, source="openweather", **kw):
    fetched = (datetime.now(timezone.utc) - timedelta(minutes=age_min)).isoformat()
    return [weather.DayForecast(date=iso(i), rain_mm=r, temp_min_c=24.0, temp_max_c=32.0, rain_probability_pct=40.0, fetched_at=fetched, source=source, **kw) for i, r in enumerate(rains)]


class Fc:
    """A weather provider double: a controllable REAL-shaped daily forecast; records every call and the location asked for."""

    def __init__(self, days=None, exc=None):
        self.days, self.exc, self.calls, self.locations, self.fetches = days, exc, 0, [], 0

    def forecast_days(self, location):
        self.calls += 1
        self.locations.append(location)
        if self.exc:
            raise self.exc
        return self.days

    def fetch(self, location):
        self.fetches += 1
        raise weather.WeatherError("not used")


# ============================ provider parsing (the existing clients, extended) ============================
def _ow(entries, tz=0):
    def handler(req):
        if req.url.path.endswith("/direct"):
            return httpx.Response(200, json=[{"name": "Guntur", "lat": 16.3, "lon": 80.4, "country": "IN"}])
        return httpx.Response(200, json={"city": {"timezone": tz}, "list": entries})

    return weather.OpenWeatherClient(key_fn=lambda: "K", http=httpx.Client(transport=httpx.MockTransport(handler)))


def test_openweather_parsing_reads_wind_gust_and_thunderstorm_codes():
    t0 = int(time.time())
    entries = [
        {"dt": t0 + i * 10800, "main": {"temp_min": 22, "temp_max": 30}, "pop": 0.2, "rain": {"3h": 2.0},
         "wind": {"speed": 4.0 + i, "gust": 9.0 + i} if i < 8 else {"speed": 3.0},
         "weather": [{"id": 211 if i == 3 else 800}]}
        for i in range(24)
    ]
    days = _ow(entries).forecast_days("Guntur")
    first = days[0]
    assert first.source == "openweather" and first.fetched_at and datetime.fromisoformat(first.fetched_at).tzinfo is not None
    assert any(d.thunderstorm is True for d in days) and any(d.thunderstorm is False for d in days)
    assert max(d.wind_ms for d in days if d.wind_ms is not None) >= 4.0 and any(d.gust_ms is not None for d in days)
    # a provider without wind/weather fields leaves them None (never guessed)
    bare = _ow([{"dt": t0 + i * 10800, "main": {"temp_min": 22, "temp_max": 30}, "pop": 0.1} for i in range(8)]).forecast_days("Guntur")
    assert all(d.wind_ms is None and d.gust_ms is None and d.thunderstorm is None for d in bare)


def test_open_meteo_parsing_reads_wind_and_weather_code_in_metres_per_second():
    seen = {}

    def handler(req):
        if "geocoding" in req.url.host:
            return httpx.Response(200, json={"results": [{"name": "Guntur", "latitude": 16.3, "longitude": 80.4, "country": "India"}]})
        seen.update(dict(req.url.params))
        return httpx.Response(200, json={"daily": {"time": ["2026-10-06", "2026-10-07", "2026-10-08"], "precipitation_sum": [0, 1, 2], "temperature_2m_max": [33, 31, 30],
                                                   "temperature_2m_min": [25, 24, 23], "weather_code": [3, 95, None], "wind_speed_10m_max": [5.0, 12.0, None], "wind_gusts_10m_max": [8.0, 18.5, None]}})

    days = weather.WeatherClient(http=httpx.Client(transport=httpx.MockTransport(handler))).forecast_days("Guntur")
    assert seen["wind_speed_unit"] == "ms" and "wind_gusts_10m_max" in seen["daily"] and "weather_code" in seen["daily"]
    assert [d.thunderstorm for d in days] == [False, True, None]
    assert (days[1].wind_ms, days[1].gust_ms) == (12.0, 18.5) and days[2].wind_ms is None and days[0].source == "open-meteo" and days[0].fetched_at


# ============================ rules and severity ============================
def types(alerts):
    return [(a["type"], a["severity"], a["event_date"]) for a in alerts]


def test_thresholds_reuse_the_app_rules_instead_of_a_second_definition():
    assert rules.RAIN_WATCH_MM == plan_agent.SIGNIFICANT_RAIN_MM and rules.RAIN_IMPORTANT_MM == plan_agent.WET_FIELD_PREV_DAY_MM and rules.HEAT_WATCH_C == plan_agent.HOT_C
    from app.services import weather_risk
    assert rules.HEAT_IMPORTANT_C == weather_risk.EXTREME_HEAT_C


@pytest.mark.parametrize("rain,sev", [(9.9, None), (10, "watch"), (24.9, "watch"), (25, "important"), (64.4, "important"), (64.5, "severe"), (120, "severe")])
def test_heavy_rain_severity_ladder(rain, sev):
    got = [a for a in rules.evaluate([D(1, rain=rain)], TODAY) if a["type"] == "heavy_rain"]
    assert (got[0]["severity"] if got else None) == sev
    if got:
        assert got[0]["values"]["rain_mm"] == rain


def test_ordinary_weather_is_not_an_alert():
    assert rules.evaluate([D(i, rain=4.0, tmax=33.0, tmin=22.0, wind=5.0, gust=8.0, storm=False) for i in range(5)], TODAY) == []  # rain tomorrow alone is not an alert


def test_thunderstorm_detection_and_severity():
    assert types(rules.evaluate([D(1, storm=True)], TODAY)) == [("thunderstorm", "watch", iso(1))]
    assert ("thunderstorm", "important", iso(1)) in types(rules.evaluate([D(1, storm=True, rain=30)], TODAY))
    assert ("thunderstorm", "important", iso(1)) in types(rules.evaluate([D(1, storm=True, gust=18)], TODAY))
    assert rules.evaluate([D(1, storm=False), D(2, storm=None)], TODAY) == []  # unknown is not a storm


@pytest.mark.parametrize("gust,wind,sev", [(10.7, None, None), (10.8, None, "watch"), (17.2, None, "important"), (24.5, None, "severe"), (None, 11.0, "watch"), (6.0, 15.0, None)])
def test_strong_wind_uses_the_gust_when_given_else_the_sustained_speed(gust, wind, sev):
    got = [a for a in rules.evaluate([D(1, gust=gust, wind=wind)], TODAY) if a["type"] == "strong_wind"]
    assert (got[0]["severity"] if got else None) == sev


@pytest.mark.parametrize("tmax,sev", [(34.9, None), (35, "watch"), (40, "important"), (45, "severe")])
def test_high_temperature_ladder(tmax, sev):
    got = [a for a in rules.evaluate([D(1, tmax=tmax)], TODAY) if a["type"] == "high_temperature"]
    assert (got[0]["severity"] if got else None) == sev


@pytest.mark.parametrize("tmin,sev", [(10.1, None), (10, "watch"), (5, "important"), (2, "severe"), (-1, "severe")])
def test_low_temperature_ladder(tmin, sev):
    got = [a for a in rules.evaluate([D(1, tmin=tmin)], TODAY) if a["type"] == "low_temperature"]
    assert (got[0]["severity"] if got else None) == sev


def test_temperature_swing_is_info_only_between_consecutive_days_and_not_when_a_heat_or_cold_alert_covers_it():
    got = rules.evaluate([D(1, tmax=27), D(2, tmax=19)], TODAY)
    assert types(got) == [("temperature_change", "info", iso(2))] and got[0]["values"]["change_c"] == -8.0
    assert rules.evaluate([D(1, tmax=31), D(2, tmax=26)], TODAY) == []  # only 5 C
    assert not any(a["type"] == "temperature_change" for a in rules.evaluate([D(1, tmax=27), D(2, tmax=36)], TODAY))  # the heat alert already says it
    assert rules.evaluate([D(1, tmax=27), D(3, tmax=19)], TODAY) == []  # not consecutive days
    cooling = rules.evaluate([D(1, tmax=41), D(2, tmax=32)], TODAY)  # back to normal the day after a heat alert: no second, redundant alert
    assert [x["type"] for x in cooling] == ["high_temperature"]


def test_incomplete_forecast_and_past_days_never_crash_or_alert():
    blank = {"date": iso(1), "rain_mm": None, "temp_min_c": None, "temp_max_c": None}
    assert rules.evaluate([blank, {"date": iso(2)}], TODAY) == []
    assert rules.evaluate([D(-2, rain=80, tmax=44)], TODAY) == []  # a day that has passed is not an alert
    assert rules.evaluate([], TODAY) == []


def test_multiple_events_on_one_day_are_all_reported_most_serious_first():
    got = rules.evaluate([D(1, rain=70, storm=True, gust=20, tmax=41)], TODAY)
    assert {a["type"] for a in got} == {"heavy_rain", "thunderstorm", "strong_wind", "high_temperature"}
    assert got[0]["severity"] == "severe" and [rules.RANK[a["severity"]] for a in got] == sorted((rules.RANK[a["severity"]] for a in got), reverse=True)
    assert len({a["key"] for a in got}) == len(got)  # every identity is distinct


# ============================ plan impact (pure) ============================
PLAN = {"items": [
    {"key": "activity:a1", "kind": "activity", "when": iso(1), "status": "supported", "params": {"activity": "irrigation"}},
    {"key": "activity:a2", "kind": "activity", "when": iso(2), "status": "supported", "params": {"activity": "weeding"}},
    {"key": "irrigation:plan", "kind": "irrigation_plan", "when": iso(1), "status": "consider", "params": {}},
    {"key": "crop:inspect", "kind": "inspect_plants", "when": None, "status": "do_now", "params": {}},
]}


def test_plan_impact_lists_only_items_on_the_alert_day_that_the_weather_type_bears_on():
    r = impact.plan_impact({"type": "heavy_rain", "event_date": iso(1)}, PLAN, None, None, 3)
    assert r["has_plan"] and r["plan_version"] == 3 and sorted(a["key"] for a in r["affected"]) == ["activity:a1", "irrigation:plan"]
    assert impact.plan_impact({"type": "heavy_rain", "event_date": iso(3)}, PLAN, None, None, 3)["affected"] == []  # nothing planned that day
    assert [a["key"] for a in impact.plan_impact({"type": "high_temperature", "event_date": iso(2)}, PLAN, None, None, 1)["affected"]] == ["activity:a2"]
    assert impact.plan_impact({"type": "low_temperature", "event_date": iso(1)}, PLAN, None, None, 1)["affected"] == []  # cold bears on planting only
    assert impact.plan_impact({"type": "temperature_change", "event_date": iso(1)}, PLAN, None, None, 1)["affected"] == []
    assert impact.plan_impact({"type": "heavy_rain", "event_date": iso(1)}, None, None, None, None) == {"has_plan": False, "plan_version": None, "affected": [], "plan_may_be_outdated": False}


def test_plan_may_be_outdated_uses_the_existing_material_change_rule():
    old = [{"date": iso(1), "rain_mm": 2.0, "temp_max_c": 31.0}]
    small = [{"date": iso(1), "rain_mm": 6.0, "temp_max_c": 31.0}]
    big = [{"date": iso(1), "rain_mm": 40.0, "temp_max_c": 31.0}]
    a = {"type": "heavy_rain", "event_date": iso(1)}
    assert impact.plan_impact(a, PLAN, old, small, 1)["plan_may_be_outdated"] is plan_agent.forecast_changed(old, small)
    assert impact.plan_impact(a, PLAN, old, big, 1)["plan_may_be_outdated"] is True
    assert plan_agent.forecast_changed(old, big) is True


# ============================ API: lifecycle, identity, freshness ============================
@pytest.fixture
def world(register, monkeypatch):
    db, ua, fa, ub, fb = _db_world(register)
    fc = Fc(mkdays(rains=(0, 30, 0, 0, 0)))
    monkeypatch.setattr(weather, "client", fc)
    return db, ua, fa, ub, fb, fc, _login("a@example.com")


def alerts(c, farm_id):
    r = c.get(f"/farms/{farm_id}/weather/alerts")
    assert r.status_code == 200, r.text
    return r.json()


def test_a_heavy_rain_forecast_creates_one_farm_specific_alert_with_real_numbers(world):
    db, ua, fa, ub, fb, fc, a = world
    r = alerts(a, fa.id)
    assert [(x["type"], x["severity"], x["event_date"], x["status"]) for x in r["alerts"]] == [("heavy_rain", "important", iso(1), "active")]
    assert r["alerts"][0]["values"] == {"rain_mm": 30.0, "rain_probability_pct": 40.0} and r["alerts"][0]["source"] == "openweather"
    assert r["farm"]["name"] == "A" and r["farm"]["location"] == "Guntur"
    assert fc.locations == ["Guntur"]  # the farm's own stored location, nothing else


def test_repeated_refresh_never_duplicates_an_alert(world):
    db, ua, fa, ub, fb, fc, a = world
    ids = {alerts(a, fa.id)["alerts"][0]["id"] for _ in range(4)}
    assert len(ids) == 1 and db.query(WeatherAlert).count() == 1
    assert alerts(a, fa.id)["alerts"][0]["status"] == "active"  # unchanged forecast: still just active


def test_each_request_makes_exactly_one_forecast_call_and_no_other_weather_call(world):
    db, ua, fa, ub, fb, fc, a = world
    alerts(a, fa.id)
    alerts(a, fa.id)
    assert fc.calls == 2 and fc.fetches == 0  # one (cached-by-the-client) forecast per request; the aggregate weather is never fetched


def test_alert_updates_when_the_forecast_changes_materially_and_not_for_a_wobble(world):
    db, ua, fa, ub, fb, fc, a = world
    first = alerts(a, fa.id)["alerts"][0]
    fc.days = mkdays(rains=(0, 33, 0, 0, 0))  # 3 mm wobble: same alert, still "active"
    again = alerts(a, fa.id)["alerts"][0]
    assert again["id"] == first["id"] and again["status"] == "active" and again["values"]["rain_mm"] == 33.0  # the latest real number is kept
    fc.days = mkdays(rains=(0, 70, 0, 0, 0))  # severity changes: the SAME alert is updated, not a new one
    up = alerts(a, fa.id)["alerts"][0]
    assert up["id"] == first["id"] and up["status"] == "updated" and up["severity"] == "severe"
    assert db.query(WeatherAlert).count() == 1


def test_alert_resolves_when_the_event_leaves_the_forecast_and_returns_as_updated(world):
    db, ua, fa, ub, fb, fc, a = world
    first = alerts(a, fa.id)["alerts"][0]
    fc.days = mkdays(rains=(0, 2, 0, 0, 0))
    r = alerts(a, fa.id)
    assert r["alerts"] == [] and [x["id"] for x in r["recent"]] == [first["id"]] and r["recent"][0]["status"] == "resolved" and r["recent"][0]["resolved_at"]
    fc.days = mkdays(rains=(0, 30, 0, 0, 0))
    back = alerts(a, fa.id)
    assert [x["id"] for x in back["alerts"]] == [first["id"]] and back["alerts"][0]["status"] == "updated" and back["recent"] == []


def test_no_alert_when_nothing_important_is_forecast(world):
    db, ua, fa, ub, fb, fc, a = world
    fc.days = mkdays(rains=(0, 3, 0, 4, 0))
    r = alerts(a, fa.id)
    assert r["alerts"] == [] and r["recent"] == [] and r["freshness"]["state"] == "live"


def test_dismissed_alert_stays_hidden_until_it_gets_more_serious(world):
    db, ua, fa, ub, fb, fc, a = world
    first = alerts(a, fa.id)["alerts"][0]
    assert a.post(f"/farms/{fa.id}/weather/alerts/{first['id']}/dismiss").json() == {"ok": True}
    assert alerts(a, fa.id)["alerts"] == []
    fc.days = mkdays(rains=(0, 32, 0, 0, 0))
    assert alerts(a, fa.id)["alerts"] == []  # same severity: still dismissed
    fc.days = mkdays(rains=(0, 70, 0, 0, 0))
    back = alerts(a, fa.id)["alerts"]
    assert len(back) == 1 and back[0]["severity"] == "severe" and back[0]["status"] == "updated"


# ============================ data freshness: never pretend ============================
def test_forecast_unavailable_keeps_known_alerts_marked_and_creates_or_resolves_nothing(world):
    db, ua, fa, ub, fb, fc, a = world
    alerts(a, fa.id)
    fc.exc = weather.WeatherError("down")
    r = alerts(a, fa.id)
    assert r["freshness"]["state"] == "unavailable" and r["freshness"]["last_known_at"] and r["freshness"]["fetched_at"] is None
    assert [x["type"] for x in r["alerts"]] == ["heavy_rain"] and r["recent"] == []  # not resolved: we simply do not know
    steps = {s["node"]: s["status"] for s in r["steps"]}
    assert steps["forecast"] == "skipped" and steps["evaluate"] == "skipped" and steps["reconcile"] == "skipped"


def test_unavailable_forecast_with_no_history_shows_no_alerts_and_invents_nothing(world):
    db, ua, fa, ub, fb, fc, a = world
    fc.exc = weather.WeatherError("down")
    r = alerts(a, fa.id)
    assert r["alerts"] == [] and r["freshness"]["state"] == "unavailable" and r["forecast"] == [] and db.query(WeatherAlert).count() == 0


def test_stale_forecast_is_flagged_and_does_not_change_alerts(world):
    db, ua, fa, ub, fb, fc, a = world
    alerts(a, fa.id)
    fc.days = mkdays(rains=(0, 2, 0, 0, 0), age_min=store.STALE_AFTER_MIN + 30)  # an old forecast that would "resolve" the alert
    r = alerts(a, fa.id)
    assert r["freshness"]["state"] == "stale" and r["freshness"]["age_minutes"] >= store.STALE_AFTER_MIN and [x["type"] for x in r["alerts"]] == ["heavy_rain"]


def test_freshness_reports_the_real_fetch_time_age_and_provider(world):
    db, ua, fa, ub, fb, fc, a = world
    fc.days = mkdays(rains=(0, 30, 0, 0, 0), age_min=18, source="open-meteo")
    f = alerts(a, fa.id)["freshness"]
    assert f["state"] == "live" and f["source"] == "open-meteo" and 17 <= f["age_minutes"] <= 19  # the backup provider is named truthfully
    assert alerts(a, fa.id)["alerts"][0]["source"] == "open-meteo"


def test_missing_location_means_no_forecast_no_alerts_and_no_weather_call(register, monkeypatch):
    db, ua, fa, ub, fb = _db_world(register)
    fa.location = ""
    db.commit()
    fc = Fc(mkdays(rains=(0, 90, 0, 0, 0)))
    monkeypatch.setattr(weather, "client", fc)
    r = alerts(_login("a@example.com"), fa.id)
    assert r["freshness"]["state"] == "no_location" and r["alerts"] == [] and fc.calls == 0


def test_every_alert_value_comes_from_the_forecast_numbers(world):
    db, ua, fa, ub, fb, fc, a = world
    fc.days = mkdays(rains=(0, 41.5, 0, 0, 0), gust_ms=19.0, wind_ms=9.0, thunderstorm=True)
    r = alerts(a, fa.id)
    blob = json.dumps(fc.days[1].to_dict())
    for al in r["alerts"]:
        for v in al["values"].values():
            assert str(v).rstrip("0").rstrip(".") in blob.replace(".0", "") or v in (fc.days[1].rain_mm, fc.days[1].gust_ms, fc.days[1].wind_ms, 19.0, 9.0, 41.5, 40.0), (al["type"], v)


# ============================ Farm plan link (real) ============================
def _plan_with_irrigation(a, fa, offset=1):
    return a.put(f"/farms/{fa.id}/plan/inputs", json={"activities": [{"kind": "irrigation", "date": iso(offset), "note": ""}], "field_condition": "none"})


def test_alert_points_to_the_planned_irrigation_without_changing_the_plan(world):
    db, ua, fa, ub, fb, fc, a = world
    assert _plan_with_irrigation(a, fa).status_code == 200
    versions = db.query(FarmPlan).filter_by(farm_id=fa.id).count()
    r = alerts(a, fa.id)
    imp = r["alerts"][0]["plan_impact"]
    assert imp["has_plan"] and imp["plan_version"] >= 1 and any(x["kind"] == "activity" and x["activity"] == "irrigation" and x["when"] == iso(1) for x in imp["affected"])
    assert r["plan"]["has_plan"] and next(s for s in r["steps"] if s["node"] == "plan_check")["status"] == "ok"
    db.expire_all()
    assert db.query(FarmPlan).filter_by(farm_id=fa.id).count() == versions  # Weather never re-plans


def test_no_plan_means_no_impact_and_no_plan_step(world):
    db, ua, fa, ub, fb, fc, a = world
    r = alerts(a, fa.id)
    assert r["alerts"][0]["plan_impact"] == {"has_plan": False, "plan_version": None, "affected": [], "plan_may_be_outdated": False}
    assert next(s for s in r["steps"] if s["node"] == "plan_check") == {"node": "plan_check", "status": "skipped", "note": "no_plan"}


def test_forecast_shift_marks_the_plan_outdated_and_the_existing_refresh_clears_it(world):
    db, ua, fa, ub, fb, fc, a = world
    fc.days = mkdays(rains=(0, 3, 0, 0, 0))  # the plan is made on a mild forecast
    assert _plan_with_irrigation(a, fa).status_code == 200
    fc.days = mkdays(rains=(0, 45, 0, 0, 0))  # then heavy rain appears
    imp = alerts(a, fa.id)["alerts"][0]["plan_impact"]
    assert imp["affected"] and imp["plan_may_be_outdated"] is True
    ref = a.post(f"/farms/{fa.id}/plan/refresh")  # the EXISTING plan mechanism decides (material change gives a new version)
    assert ref.status_code == 200 and ref.json()["changed"] is True
    assert alerts(a, fa.id)["alerts"][0]["plan_impact"]["plan_may_be_outdated"] is False


def test_alert_for_a_day_with_nothing_planned_has_no_affected_items(world):
    db, ua, fa, ub, fb, fc, a = world
    _plan_with_irrigation(a, fa, offset=3)
    imp = alerts(a, fa.id)["alerts"][0]["plan_impact"]
    assert imp["has_plan"] and not any(x["kind"] == "activity" for x in imp["affected"])  # the farmer's day-3 irrigation is not on the alert day
    assert [x["kind"] for x in imp["affected"]] == ["irrigation_hold"]  # only the planner's own hold for that rainy day (it already reacted)


# ============================ steps, ownership, export, delete ============================
def test_the_executed_steps_are_the_real_ones_in_order(world):
    db, ua, fa, ub, fb, fc, a = world
    steps = alerts(a, fa.id)["steps"]
    assert [s["node"] for s in steps] == ["weather_context", "forecast", "evaluate", "reconcile", "plan_check"]
    assert steps[1]["note"] == "openweather" and steps[2]["note"] == "1" and steps[3]["note"] == "1/0/0"


def test_ownership_other_farmers_get_the_same_404_and_cannot_dismiss_foreign_alerts(world):
    db, ua, fa, ub, fb, fc, a = world
    first = alerts(a, fa.id)["alerts"][0]
    b = _login("b@example.com")
    for path in (f"/farms/{fa.id}/weather/alerts", "/farms/99999/weather/alerts"):
        r = b.get(path)
        assert r.status_code == 404 and r.json()["detail"] == "Farm not found."
    assert b.post(f"/farms/{fa.id}/weather/alerts/{first['id']}/dismiss").status_code == 404
    assert b.post(f"/farms/{fb.id}/weather/alerts/{first['id']}/dismiss").status_code == 404  # A's alert id through B's own farm
    assert alerts(a, fa.id)["alerts"][0]["status"] == "active"
    assert alerts(b, fb.id)["alerts"][0]["type"] == "heavy_rain" and db.query(WeatherAlert).filter_by(farm_id=fb.id).count() == 1
    from tests.conftest import make_client
    assert make_client().get(f"/farms/{fa.id}/weather/alerts").status_code == 401


def test_alerts_follow_the_farms_own_location_for_two_farms_of_one_farmer(register, monkeypatch):
    db, ua, fa, ub, fb = _db_world(register)
    from app.models import Farm
    f2 = Farm(user_id=ua.id, name="A2", location="Tenali")
    db.add(f2)
    db.commit()
    fc = Fc(mkdays(rains=(0, 30, 0, 0, 0)))
    monkeypatch.setattr(weather, "client", fc)
    a = _login("a@example.com")
    alerts(a, fa.id)
    alerts(a, f2.id)
    assert fc.locations == ["Guntur", "Tenali"] and db.query(WeatherAlert).filter_by(farm_id=fa.id).count() == 1 and db.query(WeatherAlert).filter_by(farm_id=f2.id).count() == 1


def test_export_includes_only_own_alerts_and_delete_removes_them(world):
    db, ua, fa, ub, fb, fc, a = world
    ua_id, ub_id = ua.id, ub.id
    alerts(a, fa.id)
    b = _login("b@example.com")
    alerts(b, fb.id)
    exp = a.get("/auth/me/export").json()
    assert [x["farm_id"] for x in exp["weather_alerts"]] == [fa.id] and exp["weather_alerts"][0]["type"] == "heavy_rain"
    assert a.request("DELETE", "/auth/me", json={"password": "password123"}).status_code in (200, 204)
    db.expire_all()
    assert db.query(WeatherAlert).filter_by(user_id=ua_id).count() == 0 and db.query(WeatherAlert).filter_by(user_id=ub_id).count() == 1


def test_existing_weather_endpoint_is_untouched_by_alerts(world):
    db, ua, fa, ub, fb, fc, a = world
    r = a.get(f"/farms/{fa.id}/weather")
    assert r.status_code == 200 and set(r.json()) >= {"weather", "note", "risks"}


def test_no_model_or_llm_is_involved_in_alert_evaluation():
    import inspect
    import re
    src = inspect.getsource(rules) + inspect.getsource(impact) + inspect.getsource(store)
    assert not re.search(r"import (openai|anthropic|google)|genai|AIProvider|\.analyze\(", src)
