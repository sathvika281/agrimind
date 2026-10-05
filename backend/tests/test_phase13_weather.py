"""Weather-aware hints: deterministic rules over the real forecast numbers. Scratch DB only."""
import json

import pytest

from app.services import weather
from app.services.ai.base import WeatherContext
from app.services.weather_risk import (
    DRY_RAIN_MM, EXTREME_HEAT_C, FUNGAL_HUMIDITY_PCT, FUNGAL_RAIN_MM, HEAVY_RAIN_MM, HOT_DRY_TEMP_C, MAX_HINTS, weather_risks,
)


def W(**kw):
    base = dict(humidity_pct=60.0, temp_max_c=30.0, past_3d_rain_mm=0.0, next_3d_rain_mm=0.0)
    base.update(kw)
    return base


def kinds(w):
    return [r["kind"] for r in weather_risks(w)]


def test_nothing_without_weather_and_nothing_for_ordinary_weather():
    assert weather_risks(None) == [] and weather_risks({}) == []
    assert weather_risks(W()) == []


def test_missing_inputs_skip_the_rule_instead_of_guessing():
    assert kinds({"humidity_pct": None, "past_3d_rain_mm": None, "next_3d_rain_mm": None, "temp_max_c": None}) == []
    assert kinds({"humidity_pct": 95.0}) == []  # humid but no rain figures: nothing is assumed
    assert kinds({"temp_max_c": HOT_DRY_TEMP_C + 3}) == []  # hot but unknown rain: not called "dry"
    assert kinds({"temp_max_c": HOT_DRY_TEMP_C + 3, "past_3d_rain_mm": 0.0}) == []


@pytest.mark.parametrize(
    "kind, at, below",
    [
        ("humid_wet", W(humidity_pct=FUNGAL_HUMIDITY_PCT, next_3d_rain_mm=FUNGAL_RAIN_MM), W(humidity_pct=FUNGAL_HUMIDITY_PCT - 0.1, next_3d_rain_mm=FUNGAL_RAIN_MM)),
        ("humid_wet", W(humidity_pct=FUNGAL_HUMIDITY_PCT, past_3d_rain_mm=FUNGAL_RAIN_MM), W(humidity_pct=FUNGAL_HUMIDITY_PCT, past_3d_rain_mm=FUNGAL_RAIN_MM - 0.1)),
        ("heavy_rain", W(next_3d_rain_mm=HEAVY_RAIN_MM), W(next_3d_rain_mm=HEAVY_RAIN_MM - 0.1)),
        ("hot_dry", W(temp_max_c=HOT_DRY_TEMP_C), W(temp_max_c=HOT_DRY_TEMP_C - 0.1)),
        ("extreme_heat", W(temp_max_c=EXTREME_HEAT_C, next_3d_rain_mm=20.0), W(temp_max_c=EXTREME_HEAT_C - 0.1, next_3d_rain_mm=20.0)),
    ],
)
def test_each_hint_fires_exactly_at_its_threshold_and_not_just_below(kind, at, below):
    assert kind in kinds(at)
    assert kind not in kinds(below)


def test_a_hot_day_with_rain_is_not_called_dry():
    assert "hot_dry" not in kinds(W(temp_max_c=37.0, next_3d_rain_mm=DRY_RAIN_MM))
    assert "hot_dry" not in kinds(W(temp_max_c=37.0, past_3d_rain_mm=DRY_RAIN_MM))


def test_priority_order_cap_and_determinism():
    w = W(humidity_pct=90.0, temp_max_c=41.0, past_3d_rain_mm=10.0, next_3d_rain_mm=60.0)  # heat + heavy rain + humid-wet all match
    out = weather_risks(w)
    assert [r["kind"] for r in out] == ["extreme_heat", "heavy_rain"] and len(out) == MAX_HINTS == 2
    assert out == weather_risks(dict(reversed(list(w.items()))))
    assert all(r["action"] in ("check_heat_stress", "check_drainage", "check_leaves", "check_soil_moisture") for r in out)


def test_hints_carry_only_the_real_numbers_and_nothing_else():
    r = weather_risks(W(humidity_pct=88.0, past_3d_rain_mm=12.0, next_3d_rain_mm=3.0))[0]
    assert r == {"kind": "humid_wet", "action": "check_leaves", "humidity_pct": 88.0, "rain_mm": 12.0, "temp_max_c": None}


# ---------------- API ----------------
def _farm(c, **kw):
    r = c.post("/farms", json={"name": "F", "location": "Guntur", **kw})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _fake(monkeypatch, **kw):
    ctx = WeatherContext(location_name="Guntur", temperature_c=30.0, humidity_pct=kw.get("humidity_pct", 60.0), wind_kmh=5.0, temp_min_c=24.0,
                         temp_max_c=kw.get("temp_max_c", 30.0), past_3d_rain_mm=kw.get("past", 0.0), next_3d_rain_mm=kw.get("next", 0.0), trend="x", fetched_at="2026-10-04T10:00:00+00:00")

    class Fake:
        def fetch(self, location):
            return ctx

    monkeypatch.setattr(weather, "client", Fake())


def test_api_returns_hints_from_the_real_forecast_and_none_when_unavailable(register, monkeypatch):
    c = register()
    fid = _farm(c)
    r = c.get(f"/farms/{fid}/weather").json()
    assert r["weather"] is None and r["risks"] == []  # offline: nothing is invented
    _fake(monkeypatch, humidity_pct=90.0, past=10.0, next=4.0)
    j = c.get(f"/farms/{fid}/weather").json()
    assert [x["kind"] for x in j["risks"]] == ["humid_wet"] and j["risks"][0]["humidity_pct"] == 90.0
    _fake(monkeypatch)
    assert c.get(f"/farms/{fid}/weather").json()["risks"] == []


def test_api_no_location_means_no_hints(register):
    c = register()
    fid = c.post("/farms", json={"name": "No place"}).json()["id"]
    j = c.get(f"/farms/{fid}/weather").json()
    assert j["weather"] is None and j["risks"] == []


def test_hints_never_call_the_model_and_contain_no_advice_text(register, monkeypatch):
    from app.services.ai import service

    def boom(*a, **k):
        raise AssertionError("must not be called")

    monkeypatch.setattr(service, "get_provider", boom)
    c = register()
    fid = _farm(c)
    _fake(monkeypatch, humidity_pct=90.0, temp_max_c=41.0, past=10.0, next=60.0)
    text = json.dumps(c.get(f"/farms/{fid}/weather").json()).lower()
    for banned in ("spray", "dose", "apply", "fertili", "irrigate", "will ", "caused"):
        assert banned not in text


def test_weather_endpoint_authorization_still_holds(register, client):
    a, b = register("a@example.com"), register("b@example.com")
    fa = _farm(a)
    miss = b.get("/farms/999999/weather")
    foreign = b.get(f"/farms/{fa}/weather")
    assert foreign.status_code == miss.status_code == 404 and foreign.json() == miss.json()
    assert client.get(f"/farms/{fa}/weather").status_code == 401
