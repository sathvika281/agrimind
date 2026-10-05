"""Weather context from Open-Meteo (no API key).

Weather is optional evidence: nothing here may break or noticeably delay an analysis.
The router only calls try_weather(), which never raises.

Reliability: short split timeouts, one bounded retry for transient failures, and a hard
overall budget per fetch. Caching (in memory, thread-safe, size-bounded):
  - location -> coordinates: 24 h
  - "location not found":       10 min (transient failures are never cached)
  - weather per rounded lat/lon: 10 min; the context carries `fetched_at` so cached data
    is never presented as newer than it is.
"""
import dataclasses
import logging
import threading
import time
from datetime import datetime, timezone

import httpx

from . import http as http_helper
from .ai.base import WeatherContext

log = logging.getLogger("agrimind.weather")

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
TIMEOUT = httpx.Timeout(connect=1.5, read=2.0, write=2.0, pool=2.0)
BUDGET_S = 4.0  # total time one weather fetch may take, retries included
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
                "GET", url, params=params, client=self._http, timeout=TIMEOUT, retries=1,
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
        deadline = deadline if deadline is not None else http_helper._clock() + BUDGET_S
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
        deadline = http_helper._clock() + BUDGET_S  # deadlines use the HTTP helper's clock; self._clock is for cache TTLs only
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


client = WeatherClient()


def try_weather(location: str) -> tuple[WeatherContext | None, str | None]:
    """Never raises. Returns (weather, note); note explains why weather is missing."""
    if not location or not location.strip():
        return None, "Weather information unavailable: this farm has no location."
    try:
        return client.fetch(location), None
    except LocationNotFound:
        return None, NOTE_NO_LOCATION
    except Exception as e:  # noqa: BLE001 - weather must never break analysis
        log.warning("weather unavailable category=%s", type(e).__name__)
        return None, NOTE_UNAVAILABLE


# ---- health: cheap reachability probe, cached for 60 s ----
_health = {"ok": False, "at": -1e9}
_health_lock = threading.Lock()


def check_reachable() -> bool:
    with _health_lock:
        if time.monotonic() - _health["at"] < 60:
            return _health["ok"]
    try:
        http_helper.request_json(
            "GET", GEOCODE_URL, params={"name": "London", "count": 1},
            timeout=httpx.Timeout(2.0), retries=0, max_bytes=100_000, deadline=http_helper._clock() + 3.0,
        )
        ok = True
    except Exception:  # noqa: BLE001
        ok = False
    with _health_lock:
        _health.update(ok=ok, at=time.monotonic())
    return ok
