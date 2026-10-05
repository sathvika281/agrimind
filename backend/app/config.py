import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings:
    """Read lazily from the environment so tests can override values."""

    @property
    def jwt_secret(self) -> str:
        secret = os.environ.get("JWT_SECRET", "")
        if len(secret) < 32:
            raise RuntimeError(
                "JWT_SECRET must be set to at least 32 random characters. See backend/.env.example."
            )
        return secret

    @property
    def database_url(self) -> str:
        return os.environ.get("DATABASE_URL") or "sqlite:///./agrimind.db"

    @property
    def cors_origins(self) -> list[str]:
        raw = os.environ.get("CORS_ORIGINS", "http://localhost:5173")
        return [o.strip() for o in raw.split(",") if o.strip() and o.strip() != "*"]

    @property
    def cookie_secure(self) -> bool:
        return os.environ.get("COOKIE_SECURE", "false").lower() == "true"

    @property
    def ai_provider(self) -> str:
        return os.environ.get("AI_PROVIDER", "demo").strip().lower()

    # --- Gemini (the only place these are read is the provider) ---
    @property
    def gemini_api_key(self) -> str:
        return os.environ.get("GEMINI_API_KEY", "").strip()

    @property
    def gemini_model(self) -> str:
        return os.environ.get("GEMINI_MODEL", "").strip() or "gemini-2.5-flash"

    # --- agentic investigation (LangGraph). Off by default: the legacy single-call pipeline stays the default. ---
    @property
    def agentic_analysis_enabled(self) -> bool:
        return os.environ.get("AGENTIC_ANALYSIS_ENABLED", "false").strip().lower() == "true"

    @property
    def knowledge_dir(self) -> Path:
        raw = os.environ.get("KNOWLEDGE_DIR", "")
        return Path(raw) if raw else BACKEND_DIR / "knowledge"

    # --- weather providers: OpenWeather (needs a key) first, Open-Meteo (no key) as the backup ---
    @property
    def openweather_api_key(self) -> str:
        return os.environ.get("OPENWEATHER_API_KEY", "").strip()

    @property
    def weather_provider(self) -> str:
        v = os.environ.get("WEATHER_PROVIDER", "auto").strip().lower()
        return v if v in ("auto", "openweather", "openmeteo") else "auto"

    # --- uploads ---
    @property
    def max_image_bytes(self) -> int:
        try:
            mb = float(os.environ.get("MAX_IMAGE_MB", "5"))
        except ValueError:
            mb = 5.0
        return int(max(0.1, mb) * 1024 * 1024)

    @property
    def uploads_dir(self) -> Path:
        raw = os.environ.get("UPLOADS_DIR", "")
        return Path(raw) if raw else BACKEND_DIR / "uploads"

    # --- rate limiting (in-process; generous defaults so normal use / demos never hit them) ---
    @staticmethod
    def _int(name: str, default: int) -> int:
        try:
            return max(1, int(os.environ.get(name, default)))
        except ValueError:
            return default

    @property
    def rate_limit_enabled(self) -> bool:
        return os.environ.get("RATE_LIMIT_ENABLED", "true").lower() != "false"

    @property
    def rl_login_per_email(self) -> int:  # failed+successful attempts per IP+email per 5 min
        return self._int("RL_LOGIN_PER_EMAIL", 15)

    @property
    def rl_login_per_ip(self) -> int:  # per IP per 5 min
        return self._int("RL_LOGIN_PER_IP", 100)

    @property
    def rl_register_per_ip(self) -> int:  # per IP per hour
        return self._int("RL_REGISTER_PER_IP", 50)

    @property
    def rl_analysis_per_user(self) -> int:  # per user per 10 min
        return self._int("RL_ANALYSIS_PER_USER", 40)

    @property
    def rl_weather_per_user(self) -> int:  # per user per 10 min (cached upstream, so cheap)
        return self._int("RL_WEATHER_PER_USER", 120)

    @property
    def log_level(self) -> str:
        return os.environ.get("LOG_LEVEL", "INFO").upper()

    token_hours: int = 12
    cookie_name: str = "agrimind_token"


settings = Settings()
