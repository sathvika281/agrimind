"""Weather context from OpenWeather (API key) with Open-Meteo (no key) as the automatic backup.

Weather is optional evidence: nothing here may break or noticeably delay an analysis.
The router only calls try_weather(), which never raises.

Reliability: short split timeouts, one bounded retry for transient failures, and a hard
overall budget per fetch. Caching (in memory, thread-safe, size-bounded):
  - location -> coordinates: 24 h
  - "location not found":       10 min (transient failures are never cached)
  - weather per rounded lat/lon: 10 min; the context carries `fetched_at` so cached data
    is never presented as newer than it is.
"""
import contextvars
import dataclasses
import logging
import threading
import time
from datetime import datetime, timezone

import httpx

from ..config import settings
from . import http as http_helper
from .ai.base import WeatherContext

log = logging.getLogger("agrimind.weather")

# httpx/httpcore log every request URL at INFO, and OpenWeather accepts its key only as a query parameter, so these
# loggers must never emit request lines (the key would end up in the logs). Failures are logged by category only.
for _name in ("httpx", "httpcore"):
    logging.getLogger(_name).setLevel(logging.WARNING)

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
TIMEOUT = httpx.Timeout(connect=1.5, read=2.0, write=2.0, pool=2.0)
BUDGET_S = 4.0  # total time one weather fetch may take during an ANALYSIS (weather must never slow a check), retries included
ROUTE_BUDGET_S = 10.0  # the weather page/route is not on the analysis path, so it may wait longer (slow cloud networks)
LONG_TIMEOUT = httpx.Timeout(connect=4.0, read=6.0, write=4.0, pool=4.0)
_budget_var: contextvars.ContextVar[float] = contextvars.ContextVar("weather_budget", default=BUDGET_S)


def _timeout() -> httpx.Timeout:
    return TIMEOUT if _budget_var.get() <= BUDGET_S else LONG_TIMEOUT

COOLDOWN_S = 30  # after a transient failure, skip NEW weather fetches this long (cache hits still work)
COORD_TTL = 24 * 3600
MISSING_TTL = 600
WEATHER_TTL = 600
MAX_ENTRIES = 256

NOTE_UNAVAILABLE = (
    "Weather information could not be retrieved, so the analysis was performed without weather context."
)
NOTE_NO_LOCATION = "Weather information unavailable: the farm location could not be found."


class WeatherError(Exception):
    pass


class LocationNotFound(WeatherError):
    pass


def _num(v):
    return float(v) if isinstance(v, (int, float)) else None


def _sum(values) -> float | None:
    nums = [float(v) for v in values if isinstance(v, (int, float))]
    return round(sum(nums), 1) if nums else None


def _trend(past: float | None, nxt: float | None) -> str:
    parts = []
    if past is not None:
        parts.append(f"{past:g} mm of rain in the last 3 days" if past >= 1 else "little rain in the last 3 days")
    if nxt is not None:
        parts.append(f"about {nxt:g} mm of rain forecast over the next few days" if nxt >= 1 else "mostly dry in the next few days")
    return "; ".join(parts)


class _TTLCache:
    def __init__(self, clock):
        self._clock = clock
        self._d: dict = {}
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            item = self._d.get(key)
            if item is None:
                return None
            expires, value = item
            if self._clock() >= expires:
                self._d.pop(key, None)
                return None
            return value

    def put(self, key, value, ttl: float):
        with self._lock:
            self._d.pop(key, None)
            self._d[key] = (self._clock() + ttl, value)
            while len(self._d) > MAX_ENTRIES:  # drop oldest
                self._d.pop(next(iter(self._d)))


class WeatherClient:
    def __init__(self, http: httpx.Client | None = None, clock=None):
        self._http = http
        self._clock = clock or time.monotonic
        self._coords = _TTLCache(self._clock)
        self._missing = _TTLCache(self._clock)
        self._wx = _TTLCache(self._clock)
        self._cooldown_until = 0.0

    def _get(self, url: str, params: dict, deadline: float) -> dict:
        if self._clock() < self._cooldown_until:
            raise WeatherError("cooldown")  # recent transient failure: don't make farmers wait again
        try:
            data, attempts = http_helper.request_json(
                "GET", url, params=params, client=self._http, timeout=_timeout(), retries=1,
                backoff=0.4, deadline=deadline, max_bytes=500_000,
            )
        except http_helper.HttpFailure as e:
            log.warning("weather request failed category=%s status=%s attempts=%s", e.category, e.status, e.attempts)
            if e.transient:
                self._cooldown_until = self._clock() + COOLDOWN_S
            raise WeatherError(e.category) from None
        if attempts > 1:
            log.info("weather request succeeded after retry attempts=%s", attempts)
        return data

    @staticmethod
    def _key(location: str) -> str:
        return " ".join(location.lower().split())

    def resolve_location(self, location: str, deadline: float | None = None) -> tuple[float, float, str]:
        key = self._key(location)
        cached = self._coords.get(key)
        if cached:
            return cached
        if self._missing.get(key):
            raise LocationNotFound(location)
        deadline = deadline if deadline is not None else http_helper._clock() + _budget_var.get()
        candidates = [location.strip()]
        first = location.split(",")[0].strip()
        if first and first not in candidates:
            candidates.append(first)
        for name in candidates:
            data = self._get(GEOCODE_URL, {"name": name, "count": 1, "language": "en", "format": "json"}, deadline)
            results = data.get("results") or []
            if results:
                r = results[0]
                label = ", ".join(x for x in (r.get("name"), r.get("admin1"), r.get("country")) if x)
                found = (float(r["latitude"]), float(r["longitude"]), label)
                self._coords.put(key, found, COORD_TTL)
                return found
        self._missing.put(key, True, MISSING_TTL)  # definitive "not found" only (errors raise above)
        raise LocationNotFound(location)

    def fetch(self, location: str) -> WeatherContext:
        deadline = http_helper._clock() + _budget_var.get()  # deadlines use the HTTP helper's clock; self._clock is for cache TTLs only
        lat, lon, label = self.resolve_location(location, deadline)
        cache_key = (round(lat, 2), round(lon, 2))
        cached = self._wx.get(cache_key)
        if cached is not None:
            return dataclasses.replace(cached)  # same fetched_at: never claimed fresher than it is
        data = self._get(
            FORECAST_URL,
            {
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m",
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
                "past_days": 3,
                "forecast_days": 4,
                "timezone": "auto",
            },
            deadline,
        )
        cur = data.get("current") or {}
        daily = data.get("daily") or {}
        if not cur:
            raise WeatherError("no current data")
        rain = daily.get("precipitation_sum") or []
        tmax = daily.get("temperature_2m_max") or []
        tmin = daily.get("temperature_2m_min") or []
        # daily arrays: 3 past days, today, 3 future days
        past = _sum(rain[0:3])
        nxt = _sum(rain[3:7])
        ctx = WeatherContext(
            location_name=label,
            temperature_c=_num(cur.get("temperature_2m")),
            humidity_pct=_num(cur.get("relative_humidity_2m")),
            precipitation_mm=_num(cur.get("precipitation")),
            wind_kmh=_num(cur.get("wind_speed_10m")),
            temp_min_c=_num(tmin[3]) if len(tmin) > 3 else None,
            temp_max_c=_num(tmax[3]) if len(tmax) > 3 else None,
            past_3d_rain_mm=past,
            next_3d_rain_mm=nxt,
            trend=_trend(past, nxt),
            fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        self._wx.put(cache_key, ctx, WEATHER_TTL)
        return dataclasses.replace(ctx)


OWM_GEO = "https://api.openweathermap.org/geo/1.0/direct"
OWM_NOW = "https://api.openweathermap.org/data/2.5/weather"
OWM_FORECAST = "https://api.openweathermap.org/data/2.5/forecast"
MS_TO_KMH = 3.6


class OpenWeatherClient(WeatherClient):
    """OpenWeather's FREE endpoints only (geocoding, current weather, 5-day/3-hour forecast).
    The free plan has no rain history, so `past_3d_rain_mm` stays None (never guessed)."""

    def __init__(self, key_fn=lambda: settings.openweather_api_key, http: httpx.Client | None = None, clock=None):
        super().__init__(http=http, clock=clock)
        self._key_fn = key_fn

    def _get(self, url: str, params: dict, deadline: float) -> dict:
        key = self._key_fn()
        if not key:
            raise WeatherError("no api key")
        return super()._get(url, {**params, "appid": key}, deadline)

    def resolve_location(self, location: str, deadline: float | None = None) -> tuple[float, float, str]:
        key = self._key(location)
        cached = self._coords.get(key)
        if cached:
            return cached
        if self._missing.get(key):
            raise LocationNotFound(location)
        deadline = deadline if deadline is not None else http_helper._clock() + _budget_var.get()
        candidates = [location.strip()]
        first = location.split(",")[0].strip()
        if first and first not in candidates:
            candidates.append(first)
        for name in candidates:
            data = self._get(OWM_GEO, {"q": name, "limit": 1}, deadline)
            if isinstance(data, list) and data:
                r = data[0]
                label = ", ".join(x for x in (r.get("name"), r.get("state"), r.get("country")) if x)
                found = (float(r["lat"]), float(r["lon"]), label)
                self._coords.put(key, found, COORD_TTL)
                return found
        self._missing.put(key, True, MISSING_TTL)
        raise LocationNotFound(location)

    def fetch(self, location: str) -> WeatherContext:
        deadline = http_helper._clock() + _budget_var.get()
        lat, lon, label = self.resolve_location(location, deadline)
        cache_key = (round(lat, 2), round(lon, 2))
        cached = self._wx.get(cache_key)
        if cached is not None:
            return dataclasses.replace(cached)
        q = {"lat": lat, "lon": lon, "units": "metric"}
        now = self._get(OWM_NOW, q, deadline)
        fc = self._get(OWM_FORECAST, q, deadline)
        main, wind = now.get("main") or {}, now.get("wind") or {}
        if not main:
            raise WeatherError("no current data")
        entries = [e for e in (fc.get("list") or []) if isinstance(e, dict) and isinstance(e.get("dt"), (int, float))]
        if not entries:
            raise WeatherError("no forecast data")
        tz = int((fc.get("city") or {}).get("timezone") or 0)  # seconds from UTC at the farm
        t0 = datetime.now(timezone.utc).timestamp()
        today = datetime.fromtimestamp(t0 + tz, timezone.utc).date()
        todays = [e for e in entries if datetime.fromtimestamp(e["dt"] + tz, timezone.utc).date() == today] or entries[:8]
        tmax = max((_num((e.get("main") or {}).get("temp_max")) for e in todays if _num((e.get("main") or {}).get("temp_max")) is not None), default=None)
        tmin = min((_num((e.get("main") or {}).get("temp_min")) for e in todays if _num((e.get("main") or {}).get("temp_min")) is not None), default=None)
        ahead = [e for e in entries if e["dt"] >= t0 - 3 * 3600][:24] or entries[:24]  # the next 24 three-hour blocks = 72 h
        nxt = _sum((e.get("rain") or {}).get("3h", 0) for e in ahead)
        if nxt is None:
            nxt = 0.0
        wind_ms = _num(wind.get("speed"))
        ctx = WeatherContext(
            location_name=label,
            temperature_c=_num(main.get("temp")),
            humidity_pct=_num(main.get("humidity")),
            precipitation_mm=_num((now.get("rain") or {}).get("1h", 0.0)),
            wind_kmh=round(wind_ms * MS_TO_KMH, 1) if wind_ms is not None else None,
            temp_min_c=tmin,
            temp_max_c=tmax,
            past_3d_rain_mm=None,
            next_3d_rain_mm=nxt,
            trend=_trend(None, nxt),
            fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        self._wx.put(cache_key, ctx, WEATHER_TTL)
        return dataclasses.replace(ctx)


class ChainClient:
    """The provider chain used by the app: OpenWeather first (only when a key is set), Open-Meteo as the backup.
    A place one provider can't find is tried with the next; it is "not found" only if every provider says so."""

    def __init__(self):
        self.openweather = OpenWeatherClient()
        self.openmeteo = WeatherClient()

    def active(self) -> list:
        mode, key = settings.weather_provider, settings.openweather_api_key
        if mode == "openmeteo" or not key:
            return [self.openmeteo]
        return [self.openweather] if mode == "openweather" else [self.openweather, self.openmeteo]

    def fetch(self, location: str) -> WeatherContext:
        not_found = 0
        last: Exception | None = None
        clients = self.active()
        for c in clients:
            try:
                return c.fetch(location)
            except LocationNotFound:
                not_found += 1
            except Exception as e:  # noqa: BLE001
                log.warning("weather provider failed provider=%s category=%s", "openweather" if c is self.openweather else "openmeteo", type(e).__name__)
                last = e
        if last is None and not_found == len(clients):
            raise LocationNotFound(location)
        raise last or WeatherError("unavailable")


client = ChainClient()


def try_weather(location: str, budget: float | None = None) -> tuple[WeatherContext | None, str | None]:
    """Never raises. Returns (weather, note); note explains why weather is missing.
    `budget` (seconds) overrides the short analysis budget; the weather page passes ROUTE_BUDGET_S."""
    if not location or not location.strip():
        return None, "Weather information unavailable: this farm has no location."
    token = _budget_var.set(budget if budget is not None else BUDGET_S)
    try:
        return client.fetch(location), None
    except LocationNotFound:
        return None, NOTE_NO_LOCATION
    except Exception as e:  # noqa: BLE001 - weather must never break analysis
        log.warning("weather unavailable category=%s", type(e).__name__)
        return None, NOTE_UNAVAILABLE
    finally:
        _budget_var.reset(token)


# ---- health: cheap reachability probe, cached for 60 s ----
_health = {"ok": False, "at": -1e9}
_health_lock = threading.Lock()


def check_reachable() -> bool:
    with _health_lock:
        if time.monotonic() - _health["at"] < 60:
            return _health["ok"]
    ok = False
    probes = []
    if settings.openweather_api_key and settings.weather_provider != "openmeteo":
        probes.append((OWM_GEO, {"q": "London", "limit": 1, "appid": settings.openweather_api_key}))
    if settings.weather_provider != "openweather" or not settings.openweather_api_key:
        probes.append((GEOCODE_URL, {"name": "London", "count": 1}))
    for url, params in probes:
        try:
            http_helper.request_json(
                "GET", url, params=params,
                timeout=httpx.Timeout(2.0), retries=0, max_bytes=100_000, deadline=http_helper._clock() + 3.0,
            )
            ok = True
            break
        except Exception:  # noqa: BLE001
            continue
    with _health_lock:
        _health.update(ok=ok, at=time.monotonic())
    return ok
