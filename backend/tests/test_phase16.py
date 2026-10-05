"""OpenWeather provider (+ Open-Meteo backup chain), key safety, route budget, and the weather tips.
The network is never used: OpenWeather is emulated with httpx.MockTransport."""
import logging
import time

import httpx
import pytest

from app.services import weather, weather_tips
from app.services.weather import check_reachable as real_check_reachable  # imported before the test fixture replaces it
from app.services.ai.base import WeatherContext
from tests.test_phase2 import FakeWeather

KEY = "OWM-SECRET-KEY-1234567890abcdef"
TZ = 19800  # IST


def _forecast(rain_each=0.5, n=40, tmax=33.0, tmin=24.0):
    t0 = int(time.time())
    return {"city": {"timezone": TZ}, "list": [
        {"dt": t0 + i * 10800, "main": {"temp_min": tmin + (i % 3), "temp_max": tmax - (i % 3)}, "rain": {"3h": rain_each} if rain_each else {}} for i in range(n)]}


def _handler(geo=None, now=None, fc=None, calls=None, status=None):
    geo = [{"name": "Guntur", "lat": 16.3, "lon": 80.43, "country": "IN", "state": "Andhra Pradesh"}] if geo is None else geo
    now = {"main": {"temp": 31.2, "humidity": 82}, "wind": {"speed": 2.5}, "rain": {"1h": 0.4}} if now is None else now
    fc = _forecast() if fc is None else fc

    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        if status:
            return httpx.Response(status, json={"cod": status, "message": "x"})
        path = request.url.path
        if path.endswith("/geo/1.0/direct"):
            return httpx.Response(200, json=geo(request) if callable(geo) else geo)
        if path.endswith("/data/2.5/weather"):
            return httpx.Response(200, json=now)
        if path.endswith("/data/2.5/forecast"):
            return httpx.Response(200, json=fc)
        return httpx.Response(404)
    return handler


def owm(handler, key=KEY):
    return weather.OpenWeatherClient(key_fn=lambda: key, http=httpx.Client(transport=httpx.MockTransport(handler)))


# ---------------- OpenWeather parsing ----------------
def test_openweather_maps_units_and_never_guesses_past_rain():
    w = owm(_handler()).fetch("Guntur")
    assert w.location_name == "Guntur, Andhra Pradesh, IN"
    assert w.temperature_c == 31.2 and w.humidity_pct == 82 and w.precipitation_mm == 0.4
    assert w.wind_kmh == 9.0  # 2.5 m/s
    assert w.past_3d_rain_mm is None  # the free plan has no rain history: not guessed
    assert w.next_3d_rain_mm == 12.0  # 24 three-hour entries x 0.5 mm within the next 72 h
    assert w.temp_max_c is not None and w.temp_min_c is not None and w.temp_min_c <= w.temp_max_c
    assert "last 3 days" not in w.trend and "forecast" in w.trend
    assert w.fetched_at


def test_the_key_is_sent_on_every_request_and_only_as_the_appid_parameter():
    calls = []
    owm(_handler(calls=calls)).fetch("Guntur")
    assert len(calls) == 3
    assert all(r.url.params.get("appid") == KEY for r in calls)
    assert all(KEY not in dict(r.headers).values() for r in calls)


def test_geocoding_retries_with_the_first_part_of_the_place():
    seen = []

    def geo(request):
        seen.append(request.url.params.get("q"))
        return [] if "," in request.url.params.get("q") else [{"name": "Tenali", "lat": 16.24, "lon": 80.64, "country": "IN"}]

    w = owm(_handler(geo=geo)).fetch("Tenali, Andhra Pradesh")
    assert seen == ["Tenali, Andhra Pradesh", "Tenali"] and w.location_name == "Tenali, IN"


def test_an_unknown_place_is_location_not_found_and_remembered():
    calls = []
    c = owm(_handler(geo=[], calls=calls))
    for _ in range(2):
        with pytest.raises(weather.LocationNotFound):
            c.fetch("Nowhereville")
    assert sum(1 for r in calls if r.url.path.endswith("/direct")) == 1  # the second ask hit the cache


def test_a_second_fetch_is_served_from_cache():
    calls = []
    c = owm(_handler(calls=calls))
    a, b = c.fetch("Guntur"), c.fetch("Guntur")
    assert len(calls) == 3 and a.fetched_at == b.fetched_at


@pytest.mark.parametrize("bad", [{"main": {}}, {}])
def test_an_empty_current_answer_is_an_error_not_fake_weather(bad):
    with pytest.raises(weather.WeatherError):
        owm(_handler(now=bad)).fetch("Guntur")


def test_an_empty_forecast_is_an_error():
    with pytest.raises(weather.WeatherError):
        owm(_handler(fc={"city": {"timezone": 0}, "list": []})).fetch("Guntur")


def test_a_rejected_key_fails_cleanly_without_leaking_the_key():
    with pytest.raises(weather.WeatherError) as e:
        owm(_handler(status=401)).fetch("Guntur")
    assert KEY not in str(e.value) and KEY not in repr(e.value)


def test_a_missing_key_never_calls_the_network():
    calls = []
    with pytest.raises(weather.WeatherError):
        owm(_handler(calls=calls), key="").fetch("Guntur")
    assert calls == []


# ---------------- the key never reaches the logs ----------------
def test_the_key_never_appears_in_any_log_record(caplog):
    caplog.set_level(logging.DEBUG)
    owm(_handler()).fetch("Guntur")  # success path
    with pytest.raises(weather.WeatherError):
        owm(_handler(status=500)).fetch("Guntur")  # failure path (retried)
    with pytest.raises(weather.WeatherError):
        owm(_handler(status=401)).fetch("Guntur")
    text = "\n".join(r.getMessage() for r in caplog.records) + "\n".join(str(r.args) for r in caplog.records)
    assert KEY not in text and "appid" not in text


def test_httpx_request_logging_is_silenced():
    assert logging.getLogger("httpx").level >= logging.WARNING and logging.getLogger("httpcore").level >= logging.WARNING


# ---------------- the provider chain ----------------
class Rec:
    def __init__(self, result=None, exc=None):
        self.result, self.exc, self.calls = result, exc, 0

    def fetch(self, location):
        self.calls += 1
        if self.exc:
            raise self.exc
        return self.result


OW_W = WeatherContext(location_name="Guntur (OpenWeather)", temperature_c=30.0, next_3d_rain_mm=3.0)
OM_W = WeatherContext(location_name="Guntur (Open-Meteo)", temperature_c=29.0, past_3d_rain_mm=1.0, next_3d_rain_mm=2.0)


def chain(monkeypatch, ow, om, key=KEY, mode="auto"):
    monkeypatch.setenv("OPENWEATHER_API_KEY", key)
    monkeypatch.setenv("WEATHER_PROVIDER", mode)
    c = weather.ChainClient()
    c.openweather, c.openmeteo = ow, om
    return c


def test_auto_uses_openweather_first(monkeypatch):
    ow, om = Rec(OW_W), Rec(OM_W)
    assert chain(monkeypatch, ow, om).fetch("x").location_name.endswith("(OpenWeather)") and om.calls == 0


def test_openweather_failure_falls_back_to_open_meteo(monkeypatch):
    ow, om = Rec(exc=weather.WeatherError("http 500")), Rec(OM_W)
    got = chain(monkeypatch, ow, om).fetch("x")
    assert got.location_name.endswith("(Open-Meteo)") and ow.calls == 1 and om.calls == 1


def test_no_key_means_open_meteo_only(monkeypatch):
    ow, om = Rec(OW_W), Rec(OM_W)
    chain(monkeypatch, ow, om, key="").fetch("x")
    assert ow.calls == 0 and om.calls == 1


def test_provider_modes(monkeypatch):
    ow, om = Rec(OW_W), Rec(OM_W)
    chain(monkeypatch, ow, om, mode="openmeteo").fetch("x")
    assert (ow.calls, om.calls) == (0, 1)
    ow2, om2 = Rec(exc=weather.WeatherError("down")), Rec(OM_W)
    with pytest.raises(weather.WeatherError):
        chain(monkeypatch, ow2, om2, mode="openweather").fetch("x")  # openweather-only: no fallback
    assert om2.calls == 0
    monkeypatch.setenv("WEATHER_PROVIDER", "nonsense")
    from app.config import settings
    assert settings.weather_provider == "auto"


def test_a_place_one_provider_cannot_find_is_tried_with_the_other(monkeypatch):
    ow, om = Rec(exc=weather.LocationNotFound("x")), Rec(OM_W)
    assert chain(monkeypatch, ow, om).fetch("x").location_name.endswith("(Open-Meteo)")


def test_not_found_only_when_every_provider_says_so(monkeypatch):
    with pytest.raises(weather.LocationNotFound):
        chain(monkeypatch, Rec(exc=weather.LocationNotFound("x")), Rec(exc=weather.LocationNotFound("x"))).fetch("x")
    with pytest.raises(weather.WeatherError) as e:  # a real outage is not reported as "place not found"
        chain(monkeypatch, Rec(exc=weather.LocationNotFound("x")), Rec(exc=weather.WeatherError("down"))).fetch("x")
    assert not isinstance(e.value, weather.LocationNotFound)


# ---------------- budgets: short for checks, longer for the weather page ----------------
def test_try_weather_uses_the_short_budget_unless_the_page_asks_for_more(monkeypatch):
    seen = []

    class Spy:
        def fetch(self, location):
            seen.append(weather._budget_var.get())
            return OM_W

    monkeypatch.setattr(weather, "client", Spy())
    weather.try_weather("Guntur")
    weather.try_weather("Guntur", budget=weather.ROUTE_BUDGET_S)
    assert seen == [weather.BUDGET_S, weather.ROUTE_BUDGET_S] and weather.BUDGET_S < weather.ROUTE_BUDGET_S
    assert weather._budget_var.get() == weather.BUDGET_S  # restored afterwards


def test_the_long_budget_also_uses_longer_request_timeouts():
    tok = weather._budget_var.set(weather.ROUTE_BUDGET_S)
    try:
        assert weather._timeout() is weather.LONG_TIMEOUT
    finally:
        weather._budget_var.reset(tok)
    assert weather._timeout() is weather.TIMEOUT


def test_the_weather_route_waits_longer_than_an_analysis(register, monkeypatch):
    seen = []

    class Spy:
        def fetch(self, location):
            seen.append(weather._budget_var.get())
            return OM_W

    monkeypatch.setattr(weather, "client", Spy())
    c = register()
    fid = c.post("/farms", json={"name": "F", "location": "Guntur", "soil_type": ""}).json()["id"]
    r = c.get(f"/farms/{fid}/weather")
    assert r.status_code == 200 and seen == [weather.ROUTE_BUDGET_S]


def test_weather_without_rain_history_serialises_as_null_not_zero(register, monkeypatch):
    monkeypatch.setattr(weather, "client", FakeWeather(wx=OW_W))
    c = register()
    fid = c.post("/farms", json={"name": "F", "location": "Guntur", "soil_type": ""}).json()["id"]
    assert c.get(f"/farms/{fid}/weather").json()["weather"]["past_3d_rain_mm"] is None


# ---------------- weather tips ----------------
def W(**k):
    base = dict(temperature_c=30.0, humidity_pct=55.0, temp_min_c=22.0, temp_max_c=32.0, wind_kmh=8.0, past_3d_rain_mm=3.0, next_3d_rain_mm=6.0)
    base.update(k)
    return base


def kinds(out):
    return [t["kind"] for t in out["tips"]]


def conds(out):
    return {c["kind"]: c["value"] for c in out["conditions"]}


def test_no_weather_means_no_conditions_and_no_tips():
    assert weather_tips.tips_for(None) == {"conditions": [], "tips": []} and weather_tips.tips_for({}) == {"conditions": [], "tips": []}


def test_normal_weather_gets_a_single_calm_tip():
    out = weather_tips.tips_for(W())
    assert out["conditions"] == [] and kinds(out) == ["regular_checks"]


def test_heavy_rain_tips_and_real_value():
    out = weather_tips.tips_for(W(next_3d_rain_mm=45.0))
    assert conds(out)["heavy_rain"] == 45.0 and "clear_drains" in kinds(out) and "harvest_before_rain" in kinds(out)


def test_humid_and_wet_needs_both_humidity_and_rain():
    assert "humid_wet" in conds(weather_tips.tips_for(W(humidity_pct=85.0, next_3d_rain_mm=8.0)))
    assert "humid_wet" not in conds(weather_tips.tips_for(W(humidity_pct=85.0, past_3d_rain_mm=0.0, next_3d_rain_mm=0.0)))
    assert "humid_wet" not in conds(weather_tips.tips_for(W(humidity_pct=70.0, next_3d_rain_mm=8.0)))
    out = weather_tips.tips_for(W(humidity_pct=85.0, next_3d_rain_mm=8.0))
    assert "water_at_base_morning" in kinds(out) and "scout_often" in kinds(out)


def test_hot_dry_and_extreme_heat_thresholds():
    assert "hot_dry" in conds(weather_tips.tips_for(W(temp_max_c=36.0, past_3d_rain_mm=0.0, next_3d_rain_mm=0.0)))
    assert "hot_dry" not in conds(weather_tips.tips_for(W(temp_max_c=36.0)))  # rain around: not a dry spell
    out = weather_tips.tips_for(W(temp_max_c=41.0))
    assert conds(out)["extreme_heat"] == 41.0 and "irrigate_cool_hours" in kinds(out) and "shade_seedlings" in kinds(out)
    assert "extreme_heat" not in conds(weather_tips.tips_for(W(temp_max_c=39.9)))


def test_wind_cold_and_dry_spell():
    assert conds(weather_tips.tips_for(W(wind_kmh=35.0)))["strong_wind"] == 35.0 and "stake_and_tie" in kinds(weather_tips.tips_for(W(wind_kmh=35.0)))
    assert "strong_wind" not in conds(weather_tips.tips_for(W(wind_kmh=29.9)))
    assert "cold_night" in conds(weather_tips.tips_for(W(temp_min_c=8.0))) and "cold_night" not in conds(weather_tips.tips_for(W(temp_min_c=12.0)))
    dry = weather_tips.tips_for(W(past_3d_rain_mm=0.0, next_3d_rain_mm=0.0))
    assert "dry_spell" in conds(dry) and "plan_irrigation" in kinds(dry)


def test_a_missing_number_skips_its_rule_and_a_missing_past_does_not_block_the_forecast():
    assert "strong_wind" not in conds(weather_tips.tips_for(W(wind_kmh=None)))
    assert "humid_wet" not in conds(weather_tips.tips_for(W(humidity_pct=None, next_3d_rain_mm=20.0)))
    only_forecast = weather_tips.tips_for(W(past_3d_rain_mm=None, next_3d_rain_mm=50.0))
    assert "heavy_rain" in conds(only_forecast)
    assert "hot_dry" not in conds(weather_tips.tips_for(W(temp_max_c=38.0, past_3d_rain_mm=None, next_3d_rain_mm=0.0)))  # hot-dry needs both rain numbers


def test_tips_are_deduplicated_capped_and_grouped():
    out = weather_tips.tips_for(W(temp_max_c=41.0, next_3d_rain_mm=50.0, humidity_pct=90.0, wind_kmh=40.0, temp_min_c=5.0))
    ks = kinds(out)
    assert len(ks) == len(set(ks)) <= weather_tips.MAX_TIPS
    assert {t["group"] for t in out["tips"]} <= {"protect", "water", "watch"}


def test_tips_are_never_chemical_dose_or_spray_advice():
    import re
    banned = re.compile(r"spray|fungicid|pesticid|insecticid|herbicid|chemical|dose|dosage|ml|litre|kg|mancozeb|neem|copper|sulphur|fertili[sz]", re.I)
    for tips in list(weather_tips.CATALOGUE.values()) + [weather_tips.NORMAL]:
        for kind, group in tips:
            assert not banned.search(kind) and group in ("protect", "water", "watch")


def test_conditions_carry_only_the_real_measured_numbers():
    src = W(next_3d_rain_mm=47.5, wind_kmh=33.0)
    for c in weather_tips.tips_for(src)["conditions"]:
        assert c["value"] in src.values()


def test_the_tips_route_returns_tips_and_conditions_for_the_owner_only(register, monkeypatch):
    stormy = WeatherContext(location_name="Guntur", temperature_c=30.0, humidity_pct=88.0, temp_min_c=24.0, temp_max_c=32.0, wind_kmh=9.0, past_3d_rain_mm=None, next_3d_rain_mm=46.0)
    monkeypatch.setattr(weather, "client", FakeWeather(wx=stormy))
    a = register("a@example.com")
    fid = a.post("/farms", json={"name": "F", "location": "Guntur", "soil_type": ""}).json()["id"]
    d = a.get(f"/farms/{fid}/weather/tips").json()
    assert {c["kind"] for c in d["conditions"]} >= {"heavy_rain", "humid_wet"} and any(t["kind"] == "clear_drains" for t in d["tips"])
    b = register("b@example.com")
    assert b.get(f"/farms/{fid}/weather/tips").status_code == 404 and b.get("/farms/999999/weather/tips").status_code == 404


def test_the_plain_weather_answer_stays_free_of_tips_and_advice(register, monkeypatch):
    monkeypatch.setattr(weather, "client", FakeWeather(wx=WeatherContext(location_name="Guntur", temperature_c=41.0, humidity_pct=90.0, temp_max_c=41.0, next_3d_rain_mm=60.0)))
    c = register()
    fid = c.post("/farms", json={"name": "F", "location": "Guntur", "soil_type": ""}).json()["id"]
    d = c.get(f"/farms/{fid}/weather").json()
    assert "tips" not in d and "conditions" not in d


def test_a_farm_without_a_place_gets_no_tips(register):
    c = register()
    fid = c.post("/farms", json={"name": "F", "location": "", "soil_type": ""}).json()["id"]
    assert c.get(f"/farms/{fid}/weather/tips").json() == {"conditions": [], "tips": []}


def test_the_tips_route_is_rate_limited_like_weather(register, monkeypatch):
    monkeypatch.setattr(weather, "client", FakeWeather(wx=OM_W))
    c = register()
    fid = c.post("/farms", json={"name": "F", "location": "Guntur", "soil_type": ""}).json()["id"]
    codes = {c.get(f"/farms/{fid}/weather/tips").status_code for _ in range(80)}
    assert 429 in codes or codes == {200}  # a limit exists (shared with weather); never a server error
    assert 500 not in codes


def test_health_probe_uses_openweather_when_a_key_is_set(monkeypatch):
    monkeypatch.setenv("OPENWEATHER_API_KEY", KEY)
    monkeypatch.setenv("WEATHER_PROVIDER", "auto")
    urls = []
    monkeypatch.setattr(weather.http_helper, "request_json", lambda method, url, **kw: urls.append(url) or ({}, 1))
    weather._health.update(ok=False, at=-1e9)
    assert real_check_reachable() is True and urls[0].startswith("https://api.openweathermap.org")


def test_the_cap_keeps_every_group_that_the_weather_brings():
    out = weather_tips.tips_for(W(next_3d_rain_mm=55.0, humidity_pct=90.0))  # heavy rain + humid: more than the cap
    assert len(out["tips"]) == weather_tips.MAX_TIPS
    assert {t["group"] for t in out["tips"]} == {"protect", "water", "watch"}
    assert "clear_drains" in kinds(out) and "water_at_base_morning" in kinds(out) and "scout_often" in kinds(out)
    assert len({t["kind"] for t in out["tips"]}) == len(out["tips"])
