"""Lightweight in-process sliding-window rate limiter (no Redis).

Per-process memory only: limits reset on restart and are not shared between workers.
X-Forwarded-For is deliberately NOT trusted (it is client-controlled), so behind a proxy
all clients share the proxy's address; in local dev through the Vite proxy that means one
shared IP, which is why the per-IP defaults are generous.
"""
import math
import threading
import time
from collections import deque

from .config import settings
from .errors import AppError

_MAX_KEYS = 10_000


class SlidingWindowLimiter:
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._hits: dict[str, deque] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window_s: float) -> int | None:
        """Record an attempt. Returns None if allowed, else seconds until it would be allowed."""
        now = self._clock()
        with self._lock:
            q = self._hits.setdefault(key, deque())
            while q and now - q[0] >= window_s:
                q.popleft()
            if len(q) >= limit:
                return max(1, math.ceil(window_s - (now - q[0])))
            q.append(now)
            if len(self._hits) > _MAX_KEYS:  # bound memory: drop the oldest-created key
                self._hits.pop(next(iter(self._hits)), None)
            return None

    def clear(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = SlidingWindowLimiter()


def _enforce(key: str, limit: int, window_s: float, message: str) -> None:
    if not settings.rate_limit_enabled:
        return
    retry = limiter.hit(key, limit, window_s)
    if retry is not None:
        raise AppError(429, message, "rate_limited", headers={"Retry-After": str(retry)})


def client_ip(request) -> str:
    return request.client.host if request.client else "unknown"


def check_login(ip: str, email: str) -> None:
    msg = "Too many login attempts. Please wait a few minutes and try again."
    _enforce(f"login-ip:{ip}", settings.rl_login_per_ip, 300, msg)
    _enforce(f"login-acct:{ip}:{email}", settings.rl_login_per_email, 300, msg)


def login_succeeded(ip: str, email: str) -> None:
    limiter.clear(f"login-acct:{ip}:{email}")


def check_register(ip: str) -> None:
    _enforce(f"register-ip:{ip}", settings.rl_register_per_ip, 3600, "Too many sign-ups from this device. Please try again later.")


def check_analysis(user_id: int) -> None:
    _enforce(
        f"analysis-user:{user_id}",
        settings.rl_analysis_per_user,
        600,
        "You've sent a lot of analyses in a short time. Please wait a few minutes and try again.",
    )


def check_weather(user_id: int) -> None:
    _enforce(f"weather-user:{user_id}", settings.rl_weather_per_user, 600, "Too many weather requests. Please wait a little and try again.")
