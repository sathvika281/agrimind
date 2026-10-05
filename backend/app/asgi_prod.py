"""Production entry: ONE process serves the API and the built website on the same origin.

  /api/*   -> the API (the /api prefix is stripped, so no route changes)
  /health  -> the API's health check (for the platform / uptime monitor)
  else     -> the website (hashed assets cached long, index.html never cached, single-page-app fallback)

Run:  uvicorn app.asgi_prod:app --host 0.0.0.0 --port 8000
The built website comes from FRONTEND_DIST (default: ../frontend/dist, in Docker: /app/frontend-dist).
"""
import json
import os
from pathlib import Path

from starlette.responses import FileResponse, Response

from .config import BACKEND_DIR, settings
from .main import app as api

DIST = Path(os.environ.get("FRONTEND_DIST") or (BACKEND_DIR.parent / "frontend" / "dist")).resolve()

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data:; "
    "font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'"
)
HSTS = "max-age=31536000; includeSubDomains"


def _site_headers() -> dict[str, str]:
    h = {
        "Content-Security-Policy": CSP,
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
        "Permissions-Policy": "camera=(self), microphone=(self), geolocation=()",
    }
    if settings.cookie_secure:
        h["Strict-Transport-Security"] = HSTS
    return h


def _file_for(path: str) -> Path | None:
    rel = path.lstrip("/")
    if not rel:
        return None
    p = (DIST / rel).resolve()
    if p.is_file() and DIST in p.parents:  # never outside the build folder
        return p
    return None


class ProductionApp:
    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.inner(scope, receive, send)  # lifespan etc. go to the API (it creates/migrates the database)
        path = scope["path"]
        if path == "/api" or path.startswith("/api/"):
            stripped = path[4:] or "/"
            scope = {**scope, "path": stripped, "raw_path": stripped.encode()}
            return await self._api(scope, receive, send)
        if path == "/health":
            return await self._api(scope, receive, send)
        if scope["method"] not in ("GET", "HEAD"):
            return await Response(json.dumps({"detail": "Not found.", "code": "not_found"}), 404, media_type="application/json")(scope, receive, send)
        return await self._site(path, scope, receive, send)

    async def _api(self, scope, receive, send):
        if not settings.cookie_secure:
            return await self.inner(scope, receive, send)

        async def with_hsts(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"strict-transport-security", HSTS.encode()))
                message = {**message, "headers": headers}
            await send(message)

        await self.inner(scope, receive, with_hsts)

    async def _site(self, path, scope, receive, send):
        headers = _site_headers()
        f = _file_for(path)
        if f is not None:
            headers["Cache-Control"] = "public, max-age=31536000, immutable" if "/assets/" in path else "public, max-age=3600"
            return await FileResponse(f, headers=headers)(scope, receive, send)
        index = DIST / "index.html"
        if "." in path.rsplit("/", 1)[-1]:  # a missing file (e.g. /missing.js), not an app route
            return await Response("Not found", 404, headers=headers)(scope, receive, send)
        if not index.is_file():
            return await Response("The website has not been built (frontend/dist is missing).", 503, headers=headers)(scope, receive, send)
        headers["Cache-Control"] = "no-cache"
        return await FileResponse(index, headers=headers)(scope, receive, send)


app = ProductionApp(api)
