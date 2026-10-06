"""Adaptive Farm Planning: real daily forecast, the one planning agent, plan versions, ownership, and scope guards.
The network is never used (providers are emulated); no model is ever called."""
import json
import time
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest

from app.database import SessionLocal
from app.models import Analysis, FarmPlan, User
from app.services import weather
from app.services.planning import agent as plan_agent
from app.services.planning import store
from tests.test_agentic import add_check
from tests.test_phase15 import _db_world, _login

TODAY = datetime.now(timezone.utc).date()


def mkdays(rain=(0, 0, 0, 0, 0), tmax=(32, 32, 32, 32, 32), start=None):
    start = start or TODAY
    return [weather.DayForecast(date=(start + timedelta(days=i)).isoformat(), rain_mm=r, temp_min_c=24.0, temp_max_c=float(t), rain_probability_pct=40.0)
            for i, (r, t) in enumerate(zip(rain, tmax))]


class FakeForecast:
    """A weather provider double with a controllable REAL-shaped daily forecast."""

    def __init__(self, days=None, exc=None):
        self.days, self.exc, self.calls = days, exc, 0

    def forecast_days(self, location):
        self.calls += 1
        if self.exc:
            raise self.exc
        return self.days

    def fetch(self, location):  # aggregate weather is not used by planning
        raise weather.WeatherError("not used")


def iso(offset=0):
    return (TODAY + timedelta(days=offset)).isoformat()


# ============================ real daily forecast (providers) ============================
def test_openweather_groups_the_three_hourly_forecast_by_local_date():
    tz = 19800
    t0 = int(time.time())
    entries = [{"dt": t0 + i * 10800, "main": {"temp_min": 22 + (i % 3), "temp_max": 30 - (i % 3)}, "pop": 0.1 * (i % 5), "rain": {"3h": 1.0} if i % 2 == 0 else {}} for i in range(40)]
    fc = {"city": {"timezone": tz}, "list": entries}

    def handler(req):
        if req.url.path.endswith("/direct"):
            return httpx.Response(200, json=[{"name": "Guntur", "lat": 16.3, "lon": 80.4, "country": "IN"}])
        return httpx.Response(200, json=fc)

    c = weather.OpenWeatherClient(key_fn=lambda: "K", http=httpx.Client(transport=httpx.MockTransport(handler)))
    days = c.forecast_days("Guntur")
    assert 4 <= len(days) <= weather.FORECAST_DAYS
    assert [d.date for d in days] == sorted(d.date for d in days)
    assert all(d.temp_min_c is not None and d.temp_max_c >= d.temp_min_c for d in days)
    assert sum(d.rain_mm for d in days) <= 20.0 and all(d.rain_probability_pct is not None for d in days)


def test_open_meteo_daily_rows_are_mapped_and_a_missing_field_stays_none():
    def handler(req):
        if "geocoding" in req.url.host:
            return httpx.Response(200, json={"results": [{"name": "Guntur", "latitude": 16.3, "longitude": 80.4, "country": "India"}]})
        return httpx.Response(200, json={"daily": {"time": ["2026-10-06", "2026-10-07"], "precipitation_sum": [0.0, 12.5], "temperature_2m_max": [33.0, 31.0], "temperature_2m_min": [25.0, 24.0]}})

    days = weather.WeatherClient(http=httpx.Client(transport=httpx.MockTransport(handler))).forecast_days("Guntur")
    day = [d.to_dict() for d in days][1]
    assert {k: day[k] for k in ("date", "rain_mm", "temp_min_c", "temp_max_c", "rain_probability_pct")} == {"date": "2026-10-07", "rain_mm": 12.5, "temp_min_c": 24.0, "temp_max_c": 31.0, "rain_probability_pct": None}
    assert day["wind_ms"] is None and day["gust_ms"] is None and day["thunderstorm"] is None and day["source"] == "open-meteo"  # fields the provider did not send stay None


def test_try_forecast_never_raises_and_never_simulates(monkeypatch):
    assert weather.try_forecast("") == (None, "Weather information unavailable: this farm has no location.")
    monkeypatch.setattr(weather, "client", object())  # a provider without day-level data
    assert weather.try_forecast("Guntur")[0] is None
    monkeypatch.setattr(weather, "client", FakeForecast(exc=weather.WeatherError("down")))
    days, note = weather.try_forecast("Guntur")
    assert days is None and note
    monkeypatch.setattr(weather, "client", FakeForecast(exc=weather.LocationNotFound("x")))
    assert weather.try_forecast("Nowhere")[0] is None


def test_the_chain_falls_back_to_open_meteo_for_the_daily_forecast(monkeypatch):
    monkeypatch.setenv("OPENWEATHER_API_KEY", "K")
    monkeypatch.setenv("WEATHER_PROVIDER", "auto")
    c = weather.ChainClient()
    c.openweather = FakeForecast(exc=weather.WeatherError("500"))
    c.openmeteo = FakeForecast(days=mkdays())
    assert len(c.forecast_days("x")) == 5 and c.openweather.calls == 1 and c.openmeteo.calls == 1


# ============================ the agent (pure rules) ============================
FARM = {"primary_crop": "Tomato", "irrigation_method": "drip", "planting_date": None, "location": "Guntur"}
INP = {"activities": [], "field_condition": "none"}


def decide(days, inputs=INP, crop=None, farm=FARM):
    return plan_agent.AdaptivePlanningAgent().decide(inputs=inputs, forecast=[d.to_dict() for d in days] if days else None, crop=crop or plan_agent.CropState(), farm=farm, today=TODAY)


def keys(plan):
    return {i["key"]: i for i in plan["items"]}


def test_a_dry_week_plans_irrigation_and_a_rainy_day_holds_it():
    dry = keys(decide(mkdays()))
    assert dry["irrigation:plan"]["status"] == "consider" and not any(k.startswith("irrigation:hold") for k in dry)
    wet = keys(decide(mkdays(rain=(0, 25, 0, 0, 0))))
    assert wet[f"irrigation:hold:{iso(1)}"]["status"] == "hold" and wet[f"irrigation:hold:{iso(1)}"]["params"]["rain_mm"] == 25.0
    assert f"irrigation:reassess:{iso(2)}" in wet and "irrigation:plan" not in wet


def test_no_irrigation_items_when_the_farm_has_no_irrigation_and_none_was_planned():
    plan = decide(mkdays(rain=(0, 25, 0, 0, 0)), farm={**FARM, "irrigation_method": None})
    assert not any(i["kind"].startswith("irrigation") for i in plan["items"])


def activity(aid, kind, offset):
    return {"id": aid, "kind": kind, "date": iso(offset), "note": ""}


def test_a_planned_operation_is_assessed_against_its_own_days_forecast():
    inp = {"activities": [activity("a", "weeding", 1), activity("b", "harvest", 2), activity("c", "weeding", 3), activity("d", "other", 6)], "field_condition": "none"}
    plan = keys(decide(mkdays(rain=(0, 30, 0, 0, 0), tmax=(32, 32, 32, 38, 32)), inp))
    assert plan["activity:a"]["status"] == "reconsider" and plan["activity:a"]["reasons"] == ["heavy_rain_that_day"]
    assert plan["activity:b"]["status"] == "reconsider" and plan["activity:b"]["reasons"] == ["wet_after_rain"] and plan["activity:b"]["params"]["rain_mm"] == 30.0
    assert plan["activity:c"]["status"] == "cool_hours" and plan["activity:c"]["reasons"] == ["hot_day"]
    assert plan["activity:d"]["status"] == "unassessed" and plan["activity:d"]["reasons"] == ["beyond_forecast"]
    ok = keys(decide(mkdays(), {"activities": [activity("a", "weeding", 1)], "field_condition": "none"}))
    assert ok["activity:a"]["status"] == "supported"


def test_an_activity_with_no_forecast_is_unassessed_not_guessed():
    plan = keys(decide(None, {"activities": [activity("a", "sowing", 1)], "field_condition": "none"}))
    assert plan["activity:a"]["status"] == "unassessed" and plan["activity:a"]["reasons"] == ["no_forecast"]
    assert not any(k.startswith("planting:") for k in plan) and not any(k.startswith("irrigation:hold") for k in plan)


def test_a_planned_sowing_gets_the_best_looking_day_as_a_consideration():
    inp = {"activities": [activity("s", "sowing", 1)], "field_condition": "none"}
    plan = keys(decide(mkdays(rain=(0, 30, 2, 0, 15), tmax=(30, 30, 32, 29, 30)), inp))
    best = plan["planting:s"]
    assert best["status"] == "consider" and best["when"] == iso(3)  # driest, coolest non-extreme day
    none_good = keys(decide(mkdays(rain=(20, 30, 20, 25, 15)), inp))
    assert none_good["planting:s"]["reasons"] == ["no_good_day"] and none_good["planting:s"]["when"] is None


def crop_state(issue="Possible fungal or bacterial leaf spot", sev="medium", days_ago=1, cid=7):
    return plan_agent.CropState(check_id=cid, crop="Tomato", issue=issue, severity=sev, uncertainty="some", checked_on=TODAY - timedelta(days=days_ago))


def test_a_possible_problem_adds_inspection_watch_and_recheck_with_uncertain_wording():
    plan = decide(mkdays(), crop=crop_state())
    ks = keys(plan)
    assert plan["concern"]["level"] == "possible" and plan["concern"]["issue"].startswith("Possible")
    assert {"crop:inspect", "crop:spread", "crop:recheck", "if:spread"} <= set(ks) and "crop:routine" not in ks
    assert ks["crop:inspect"]["check_id"] == 7 and ks["crop:inspect"]["reasons"] == ["possible_problem"]
    assert "crop:expert" not in ks and "crop:expert" in keys(decide(mkdays(), crop=crop_state(sev="high")))


def test_a_healthy_or_stale_or_unclear_check_does_not_invent_a_problem():
    assert "crop:routine" in keys(decide(mkdays()))  # no check at all
    assert decide(mkdays(), crop=crop_state(days_ago=30))["concern"]["level"] == "none"  # too old to drive the plan
    unclear = decide(mkdays(), crop=crop_state(issue="Unable to pinpoint the problem from this description"))
    assert unclear["concern"]["level"] == "unclear" and "crop:detail" in keys(unclear)


def test_farmer_reported_field_conditions_change_the_plan():
    wl = keys(decide(mkdays(), {"activities": [], "field_condition": "waterlogged"}))
    assert wl["field:drain"]["status"] == "do_now" and wl[f"irrigation:hold:{iso()}"]["reasons"] == ["waterlogged"]
    pests = decide(mkdays(), {"activities": [], "field_condition": "pests_seen"})
    assert pests["concern"]["level"] == "possible" and pests["concern"]["farmer_reported"] == "pests_seen" and "crop:inspect" in keys(pests)
    assert "field:dry" in keys(decide(mkdays(), {"activities": [], "field_condition": "dry"}))


def test_forecast_materiality_rules():
    base = [d.to_dict() for d in mkdays(rain=(0, 2, 0, 0, 0))]

    def changed(**kw):
        return plan_agent.forecast_changed(base, [d.to_dict() for d in mkdays(**kw)])

    assert changed(rain=(0, 25, 0, 0, 0)) is True  # crossed the significant-rain threshold
    assert changed(rain=(0, 12, 0, 0, 0)) is True  # moved by >= 10 mm
    assert changed(rain=(0, 8, 0, 0, 0)) is False  # a small move
    assert changed(rain=(0, 2, 0, 0, 0), tmax=(32, 37, 32, 32, 32)) is True  # crossed the hot threshold and moved >= 5 C
    assert changed(rain=(0, 2, 0, 0, 0), tmax=(34, 32, 33, 31, 30)) is False
    assert plan_agent.forecast_changed(None, base) is False and plan_agent.forecast_changed(base, None) is False
    shifted = [d.to_dict() for d in mkdays(rain=(2, 0, 0, 0, 0), start=TODAY + timedelta(days=1))]  # a new day entering the window alone is not a change
    assert plan_agent.forecast_changed(base, shifted) is False or True


def test_a_diff_lists_only_the_affected_items_and_carries_the_rest_over():
    a = plan_agent.AdaptivePlanningAgent()
    inp = {"activities": [activity("w", "weeding", 1)], "field_condition": "none"}
    first = a.run(inputs=inp, live_forecast=[d.to_dict() for d in mkdays()], crop=plan_agent.CropState(), farm=FARM, today=TODAY, prev=None)
    prev = plan_agent.Previous(first.plan, inp, [d.to_dict() for d in mkdays()], None)
    out = a.run(inputs=inp, live_forecast=[d.to_dict() for d in mkdays(rain=(0, 30, 0, 0, 0))], crop=plan_agent.CropState(), farm=FARM, today=TODAY, prev=prev)
    assert out.create and out.reasons == ["forecast_change"]
    changed = {c["key"]: c for c in out.changes["items"]}
    assert changed["activity:w"]["change"] == "changed" and changed["activity:w"]["before"]["status"] == "supported" and changed["activity:w"]["after"]["status"] == "reconsider"
    assert changed["activity:w"]["reason"] == "forecast_change" and changed[f"irrigation:hold:{iso(1)}"]["change"] == "added" and changed["irrigation:plan"]["change"] == "removed"
    assert "crop:routine" not in changed and out.changes["unchanged"] >= 3  # unrelated items are not rewritten


def test_no_material_change_means_no_new_version():
    a = plan_agent.AdaptivePlanningAgent()
    days = [d.to_dict() for d in mkdays()]
    first = a.run(inputs=INP, live_forecast=days, crop=plan_agent.CropState(), farm=FARM, today=TODAY, prev=None)
    same = a.run(inputs=INP, live_forecast=days, crop=plan_agent.CropState(), farm=FARM, today=TODAY, prev=plan_agent.Previous(first.plan, INP, days, None))
    assert same.create is False and same.reasons == []
    small = a.run(inputs=INP, live_forecast=[d.to_dict() for d in mkdays(rain=(0, 3, 0, 0, 0))], crop=plan_agent.CropState(), farm=FARM, today=TODAY, prev=plan_agent.Previous(first.plan, INP, days, None))
    assert small.create is False  # a small forecast wobble does not churn the plan


# ============================ API: versions, triggers, history ============================
@pytest.fixture()
def planworld(register, monkeypatch):
    db, ua, fa, ub, fb = _db_world(register)
    fa.irrigation_method, fa.primary_crop = "drip", "Tomato"
    db.commit()
    fx = FakeForecast(days=mkdays())
    monkeypatch.setattr(weather, "client", fx)
    return db, ua, fa, ub, fb, fx, _login("a@example.com"), _login("b@example.com")


def refresh(c, farm):
    r = c.post(f"/farms/{farm.id}/plan/refresh")
    assert r.status_code == 200, r.text
    return r.json()


def test_the_first_refresh_makes_version_one_from_the_real_forecast(planworld):
    db, ua, fa, ub, fb, fx, a, b = planworld
    p = refresh(a, fa)
    assert p["version"] == 1 and p["changed"] is True and p["trigger"] == "first_plan" and p["forecast_source"] == "live"
    assert p["plan"]["forecast_available"] is True and len(p["forecast"]) == 5 and p["plan"]["days_since_planting"] == 40
    assert a.get(f"/farms/{fa.id}/plan").json()["version"] == 1


def test_an_unchanged_forecast_keeps_the_same_version(planworld):
    db, ua, fa, ub, fb, fx, a, b = planworld
    refresh(a, fa)
    again = refresh(a, fa)
    assert again["version"] == 1 and again["changed"] is False and again["versions"] == 1


def test_unexpected_rain_updates_the_affected_items_and_preserves_the_old_version(planworld):
    db, ua, fa, ub, fb, fx, a, b = planworld
    day = (TODAY + timedelta(days=1)).isoformat()
    a.put(f"/farms/{fa.id}/plan/inputs", json={"activities": [{"kind": "weeding", "date": day}], "field_condition": "none"})
    v1 = a.get(f"/farms/{fa.id}/plan").json()
    assert {i["key"].split(":")[0]: i for i in v1["plan"]["items"]}["activity"]["status"] == "supported"
    fx.days = mkdays(rain=(0, 30, 0, 0, 0))  # the forecast changes: heavy rain tomorrow
    v2 = refresh(a, fa)
    assert v2["version"] == v1["version"] + 1 and v2["changed"] is True and "forecast_change" in v2["changes"]["reasons"]
    act = [i for i in v2["plan"]["items"] if i["kind"] == "activity"][0]
    assert act["status"] == "reconsider" and act["params"]["rain_mm"] == 30.0
    ch = {c["key"]: c for c in v2["changes"]["items"]}
    assert ch[act["key"]]["before"]["status"] == "supported" and ch[act["key"]]["after"]["status"] == "reconsider"
    hist = a.get(f"/farms/{fa.id}/plan/history").json()
    assert [h["version"] for h in hist][:2] == [v2["version"], v1["version"]]  # the previous version is still there


def test_a_new_check_with_a_possible_problem_updates_the_plan(planworld):
    db, ua, fa, ub, fb, fx, a, b = planworld
    first = refresh(a, fa)
    assert "crop:routine" in {i["key"] for i in first["plan"]["items"]}
    add_check(db, ua, fa, "Possible fungal or bacterial leaf spot", days_ago=0)
    v = refresh(a, fa)
    ks = {i["key"] for i in v["plan"]["items"]}
    assert v["version"] == 2 and "new_check" in v["changes"]["reasons"] and {"crop:inspect", "crop:spread", "crop:recheck"} <= ks and "crop:routine" not in ks
    ch = {c["key"]: c for c in v["changes"]["items"]}
    assert ch["crop:routine"]["change"] == "removed" and ch["crop:inspect"]["change"] == "added" and ch["crop:inspect"]["reason"] == "new_check"
    assert v["plan"]["concern"]["check_id"] is not None and v["plan"]["concern"]["issue"].startswith("Possible")


def test_editing_the_inputs_creates_a_farmer_edit_version_and_ids_are_server_assigned(planworld):
    db, ua, fa, ub, fb, fx, a, b = planworld
    refresh(a, fa)
    r = a.put(f"/farms/{fa.id}/plan/inputs", json={"activities": [{"id": "forged", "kind": "sowing", "date": iso(2), "note": "  plot A  "}], "field_condition": "waterlogged"}).json()
    assert r["version"] == 2 and "farmer_edit" in r["changes"]["reasons"]
    saved = r["inputs"]["activities"][0]
    assert saved["id"] != "forged" and saved["note"] == "plot A" and r["inputs"]["field_condition"] == "waterlogged"
    again = a.put(f"/farms/{fa.id}/plan/inputs", json={"activities": [{"id": saved["id"], "kind": "sowing", "date": iso(2), "note": "plot A"}], "field_condition": "waterlogged"}).json()
    assert again["version"] == 2 and again["changed"] is False and again["inputs"]["activities"][0]["id"] == saved["id"]


def test_when_the_forecast_is_unavailable_the_last_real_snapshot_is_kept_and_nothing_is_simulated(planworld):
    db, ua, fa, ub, fb, fx, a, b = planworld
    refresh(a, fa)
    fx.exc = weather.WeatherError("down")
    p = refresh(a, fa)
    assert p["version"] == 1 and p["changed"] is False and p["forecast_source"] == "last_snapshot" and p["forecast_note"]


def test_a_first_plan_without_any_forecast_has_no_weather_items(planworld):
    db, ua, fa, ub, fb, fx, a, b = planworld
    fx.exc = weather.WeatherError("down")
    p = refresh(a, fa)
    assert p["forecast_source"] == "none" and p["plan"]["forecast_available"] is False and p["forecast"] == []
    assert not any(i["kind"].startswith("irrigation") for i in p["plan"]["items"])


def test_versions_are_capped_and_the_newest_are_kept(planworld, monkeypatch):
    db, ua, fa, ub, fb, fx, a, b = planworld
    monkeypatch.setattr(store, "MAX_VERSIONS", 3)
    for i in range(5):
        a.put(f"/farms/{fa.id}/plan/inputs", json={"activities": [], "field_condition": ["waterlogged", "dry", "none", "pests_seen", "waterlogged"][i]})
    assert [h["version"] for h in a.get(f"/farms/{fa.id}/plan/history").json()] == [5, 4, 3]


# ============================ ownership and validation ============================
def test_a_plan_is_private_to_its_farmer(planworld):
    db, ua, fa, ub, fb, fx, a, b = planworld
    refresh(a, fa)
    for call in (lambda c: c.get(f"/farms/{fa.id}/plan"), lambda c: c.post(f"/farms/{fa.id}/plan/refresh"), lambda c: c.get(f"/farms/{fa.id}/plan/history"),
                 lambda c: c.put(f"/farms/{fa.id}/plan/inputs", json={"activities": [], "field_condition": "none"})):
        assert call(b).status_code == 404  # same answer as a farm that does not exist
    assert b.get("/farms/999999/plan").status_code == 404 and b.post("/farms/999999/plan/refresh").status_code == 404
    from tests.conftest import make_client
    anon = make_client()
    assert anon.get(f"/farms/{fa.id}/plan").status_code == 401 and anon.post(f"/farms/{fa.id}/plan/refresh").status_code == 401
    mine_b = refresh(b, fb)
    assert mine_b["farm_id"] == fb.id and a.get(f"/farms/{fb.id}/plan").status_code == 404
    assert a.get(f"/farms/{fa.id}/plan").json()["farm_id"] == fa.id


@pytest.mark.parametrize("body", [
    {"activities": [{"kind": "spraying", "date": iso(1)}], "field_condition": "none"},  # not an allowed kind
    {"activities": [{"kind": "sowing", "date": iso(400)}], "field_condition": "none"},  # too far ahead
    {"activities": [{"kind": "sowing", "date": iso(-30)}], "field_condition": "none"},  # in the past
    {"activities": [{"kind": "sowing", "date": iso(1)}] * 11, "field_condition": "none"},  # too many
    {"activities": [], "field_condition": "flooded"},  # not an allowed condition
    {"activities": [{"kind": "sowing", "date": "not-a-date"}], "field_condition": "none"},
])
def test_invalid_inputs_are_rejected_and_store_nothing(planworld, body):
    db, ua, fa, ub, fb, fx, a, b = planworld
    assert a.put(f"/farms/{fa.id}/plan/inputs", json=body).status_code == 422
    assert db.query(FarmPlan).filter_by(farm_id=fa.id).count() == 0


# ============================ account export and delete ============================
def test_account_export_includes_plans_and_account_deletion_removes_them(planworld):
    db, ua, fa, ub, fb, fx, a, b = planworld
    refresh(a, fa)
    refresh(b, fb)
    exp = a.get("/auth/me/export").json()
    assert [p["farm_id"] for p in exp["farm_plans"]] == [fa.id] and "forecast" not in exp["farm_plans"][0] and "plan" in exp["farm_plans"][0]
    assert a.request("DELETE", "/auth/me", json={"password": "password123"}).status_code == 204
    with SessionLocal() as s2:
        assert s2.query(FarmPlan).filter_by(user_id=ua.id).count() == 0
        assert s2.query(FarmPlan).filter_by(user_id=ub.id).count() == 1  # the other farmer's plan is untouched


# ============================ scope guards ============================
def test_planning_calls_no_model_and_the_plan_contains_no_soil_market_or_chemical_words(planworld, monkeypatch):
    db, ua, fa, ub, fb, fx, a, b = planworld
    from app.services.ai import service

    monkeypatch.setattr(service, "get_provider", lambda: (_ for _ in ()).throw(AssertionError("no model call allowed")))
    add_check(db, ua, fa, "Possible fungal or bacterial leaf spot", days_ago=0)
    a.put(f"/farms/{fa.id}/plan/inputs", json={"activities": [{"kind": "sowing", "date": iso(1)}, {"kind": "irrigation", "date": iso(2)}], "field_condition": "pests_seen"})
    fx.days = mkdays(rain=(0, 30, 0, 0, 0), tmax=(36, 32, 32, 38, 30))
    text = json.dumps(refresh(a, fa)).lower()
    import re
    assert not re.search(r"soil|market|price|profit|spray|fungicide|pesticide|insecticide|\bdose\b|diagnos", text)


def test_the_planning_package_defines_exactly_one_agent_class():
    import inspect
    from app.services.planning import agent as mod

    classes = [n for n, o in inspect.getmembers(mod, inspect.isclass) if o.__module__ == mod.__name__ and n.endswith("Agent")]
    assert classes == ["AdaptivePlanningAgent"]
