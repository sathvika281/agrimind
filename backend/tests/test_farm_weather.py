"""GET /farms/{id}/weather: real weather for a farm's saved location; owner-only; never fails the page."""
import httpx
import pytest

from app.services import weather
from tests.test_phase2 import WX, FakeWeather


def mkfarm(c, location="Guntur"):
    return c.post("/farms", json={"name": "F", "location": location, "soil_type": "Red soil"}).json()["id"]


def test_returns_weather_for_the_farm_location(register, monkeypatch):
    seen = {}

    class Spy(FakeWeather):
        def fetch(self, location):
            seen["loc"] = location
            return super().fetch(location)

    monkeypatch.setattr(weather, "client", Spy(wx=WX))
    c = register()
    r = c.get(f"/farms/{mkfarm(c, 'Tenali, Andhra Pradesh')}/weather")
    d = r.json()
    assert r.status_code == 200 and seen["loc"] == "Tenali, Andhra Pradesh"
    assert d["note"] is None and d["weather"]["temperature_c"] == 31.0 and d["weather"]["next_3d_rain_mm"] == 14.0


@pytest.mark.parametrize("exc", [weather.WeatherError("down"), weather.LocationNotFound("x"), httpx.ReadTimeout("slow"), RuntimeError("weird")])
def test_failures_are_a_clean_200_with_a_note_never_an_error_page(register, monkeypatch, exc):
    monkeypatch.setattr(weather, "client", FakeWeather(exc=exc))
    c = register()
    r = c.get(f"/farms/{mkfarm(c)}/weather")
    assert r.status_code == 200 and r.json()["weather"] is None and r.json()["note"]
    assert "Traceback" not in r.text and "weird" not in r.text


def test_farm_without_location_has_a_note(register):
    c = register()
    r = c.get(f"/farms/{mkfarm(c, '')}/weather")
    assert r.json()["weather"] is None and "no location" in r.json()["note"]


def test_owner_only_with_identical_404_and_auth_required(register, client, monkeypatch):
    monkeypatch.setattr(weather, "client", FakeWeather(wx=WX))
    a = register("a@example.com")
    b = register("b@example.com")
    fid = mkfarm(a)
    foreign, missing = b.get(f"/farms/{fid}/weather"), b.get("/farms/999999/weather")
    assert foreign.status_code == missing.status_code == 404 and foreign.json() == missing.json()
    assert "temperature" not in foreign.text
    client.cookies.clear()
    assert client.get(f"/farms/{fid}/weather").status_code == 401


def test_cached_weather_keeps_its_original_fetch_time(register, monkeypatch):
    import httpx as hx

    from tests.test_phase4 import FORECAST, geo_ok

    calls = []

    def handler(req):
        calls.append(1)
        return hx.Response(200, json=geo_ok() if "geocoding" in req.url.host else FORECAST)

    monkeypatch.setattr(weather, "client", weather.WeatherClient(http=hx.Client(transport=hx.MockTransport(handler))))
    c = register()
    fid = mkfarm(c)
    first = c.get(f"/farms/{fid}/weather").json()["weather"]
    n = len(calls)
    second = c.get(f"/farms/{fid}/weather").json()["weather"]
    assert len(calls) == n and second["fetched_at"] == first["fetched_at"] and first["fetched_at"]


def test_weather_endpoint_is_rate_limited(register, monkeypatch):
    monkeypatch.setenv("RL_WEATHER_PER_USER", "2")
    monkeypatch.setattr(weather, "client", FakeWeather(wx=WX))
    c = register()
    fid = mkfarm(c)
    assert [c.get(f"/farms/{fid}/weather").status_code for _ in range(2)] == [200, 200]
    r = c.get(f"/farms/{fid}/weather")
    assert r.status_code == 429 and "retry-after" in r.headers


def test_each_farm_gets_the_weather_of_its_own_place(register, monkeypatch):
    """Two farms in different places: each answer is fetched for, and only for, that farm's own location."""
    seen = []

    class PerPlace(FakeWeather):
        def fetch(self, location):
            seen.append(location)
            w = super().fetch(location)
            return w.model_copy(update={"temperature_c": 20.0 + len(location)}) if hasattr(w, "model_copy") else w

    monkeypatch.setattr(weather, "client", PerPlace(wx=WX))
    c = register()
    a, b = mkfarm(c, "Vijayawada"), mkfarm(c, "Guntur")
    ra, rb = c.get(f"/farms/{a}/weather"), c.get(f"/farms/{b}/weather")
    assert ra.status_code == rb.status_code == 200
    assert seen == ["Vijayawada", "Guntur"]
