import os
import tempfile

# Must be set before the app is imported.
_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_tmp, 'test.db')}"
os.environ["UPLOADS_DIR"] = os.path.join(_tmp, "uploads")
os.environ["JWT_SECRET"] = "test-secret-" + "x" * 40
os.environ["AI_PROVIDER"] = "demo"
os.environ["COOKIE_SECURE"] = "false"
os.environ["MAX_IMAGE_MB"] = "1"
os.environ["GEMINI_API_KEY"] = ""  # empty (not unset) so load_dotenv never injects a real key into tests

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services import weather  # noqa: E402


class OfflineWeather:
    """Default weather client for tests: never touches the network."""

    def fetch(self, location):
        raise weather.WeatherError("offline (test)")


@pytest.fixture(autouse=True)
def _no_network_weather(monkeypatch):
    monkeypatch.setattr(weather, "client", OfflineWeather())
    monkeypatch.setattr(weather, "check_reachable", lambda: False)  # health probe never hits the network


SLEEPS: list[float] = []


@pytest.fixture(autouse=True)
def _fast_retries_and_clean_limiter(monkeypatch):
    """Retry backoff must not slow tests (sleeps are recorded), and rate-limit state must not leak."""
    from app import ratelimit
    from app.services import http as http_helper

    SLEEPS.clear()
    monkeypatch.setattr(http_helper, "_sleep", lambda s: SLEEPS.append(s))
    ratelimit.limiter.reset()
    yield
    ratelimit.limiter.reset()


@pytest.fixture()
def client():
    import shutil

    shutil.rmtree(os.environ["UPLOADS_DIR"], ignore_errors=True)
    Base.metadata.drop_all(engine)
    with TestClient(app) as c:  # lifespan creates tables
        yield c


def make_client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def register(client):
    def _register(email="farmer@example.com", password="password123"):
        c = make_client()
        r = c.post("/auth/register", json={"email": email, "password": password})
        assert r.status_code == 201, r.text
        return c

    return _register
