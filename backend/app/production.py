"""Production safety checks. With APP_ENV=production the app REFUSES to start on unsafe settings.

Messages name the setting and what is wrong; they never print a secret value.
"""
import os
from urllib.parse import urlparse

PLACEHOLDERS = ("change-me", "changeme", "replace-me", "secret", "password", "example", "your-secret", "test-secret", "x" * 8)
MIN_SECRET_LEN = 48


def is_production() -> bool:
    return os.environ.get("APP_ENV", "").strip().lower() == "production"


def problems(env=None) -> list[str]:
    """Every reason the current environment is unsafe for production (empty list = fine)."""
    e = os.environ if env is None else env
    out: list[str] = []
    secret = e.get("JWT_SECRET", "")
    if len(secret) < MIN_SECRET_LEN:
        out.append(f"JWT_SECRET must be at least {MIN_SECRET_LEN} random characters in production.")
    elif any(p in secret.lower() for p in PLACEHOLDERS):
        out.append("JWT_SECRET looks like a placeholder; generate a real random value.")
    if e.get("COOKIE_SECURE", "false").lower() != "true":
        out.append("COOKIE_SECURE must be true in production (the site must be served over HTTPS).")
    for origin in [o.strip() for o in e.get("CORS_ORIGINS", "").split(",") if o.strip()]:
        parsed = urlparse(origin)
        if origin == "*" or parsed.scheme != "https":
            out.append("CORS_ORIGINS may only list https:// origins in production (or be empty for same-origin).")
            break
    provider = e.get("AI_PROVIDER", "demo").strip().lower()
    if provider == "gemini":
        if not e.get("GEMINI_API_KEY", "").strip():
            out.append("AI_PROVIDER=gemini needs GEMINI_API_KEY (set it in the server environment, never in the code).")
    elif provider == "demo":
        if e.get("ALLOW_DEMO_IN_PRODUCTION", "false").lower() != "true":
            out.append("AI_PROVIDER=demo would show built-in sample answers to real farmers; use gemini (or set ALLOW_DEMO_IN_PRODUCTION=true on purpose).")
    else:
        out.append("AI_PROVIDER must be gemini or demo.")
    if e.get("RATE_LIMIT_ENABLED", "true").lower() == "false":
        out.append("RATE_LIMIT_ENABLED must not be false in production.")
    return out


def validate_production() -> None:
    """Raise with a readable list if APP_ENV=production and any check fails. A no-op otherwise."""
    if not is_production():
        return
    bad = problems()
    if bad:
        raise RuntimeError("Refusing to start in production:\n - " + "\n - ".join(bad))
