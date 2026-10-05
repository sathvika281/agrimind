"""Pure-ASGI middleware: request ids + access log + security headers, and an early body-size guard."""
import json
import logging
import re
import time
import uuid

from .config import settings
from .errors import default_code
from .logging_config import request_id_var

log = logging.getLogger("agrimind.http")

_RID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
_REQUEST_BODY_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
IMAGE_TOO_LARGE = "That image is too large. Please choose a smaller photo."
SMALL_BODY_LIMIT = 64 * 1024
MULTIPART_OVERHEAD = 256 * 1024


def _header(scope, name: bytes) -> str | None:
    for k, v in scope.get("headers", []):
        if k == name:
            return v.decode("latin-1")
    return None


async def _json_response(send, status: int, body: dict, extra_headers: list | None = None):
    raw = json.dumps(body).encode()
    headers = [(b"content-type", b"application/json"), (b"content-length", str(len(raw)).encode())]
    headers += extra_headers or []
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": raw})


class RequestContextMiddleware:
    """Outermost: assigns/validates X-Request-ID, adds headers, logs one access line, owns 500s."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        supplied = _header(scope, b"x-request-id")
        rid = supplied if supplied and _RID.match(supplied) else uuid.uuid4().hex
        token = request_id_var.set(rid)
        start = time.perf_counter()
        state = {"status": 500, "started": False}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                state["status"] = message["status"]
                state["started"] = True
                headers = list(message.get("headers", []))
                present = {k.lower() for k, _ in headers}
                headers.append((b"x-request-id", rid.encode()))
                for k, v in (
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"cache-control", b"no-store"),
                ):
                    if k not in present:
                        headers.append((k, v))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            log.exception("unhandled_error method=%s path=%s", scope["method"], scope["path"])
            if not state["started"]:
                state["status"] = 500
                await _json_response(
                    send_wrapper,
                    500,
                    {"detail": "Something went wrong. Please try again.", "code": "server_error", "request_id": rid},
                )
        finally:
            ms = (time.perf_counter() - start) * 1000
            # path only: never the query string, cookies or bodies
            log.info("request method=%s path=%s status=%s duration_ms=%.0f", scope["method"], scope["path"], state["status"], ms)
            request_id_var.reset(token)


class _BodyTooLarge(Exception):
    pass


class BodyLimitMiddleware:
    """Reject oversized request bodies early so huge uploads are never spooled to disk/memory."""

    def __init__(self, app):
        self.app = app

    @staticmethod
    def _limit(scope) -> int:
        if scope["path"] == "/analyses":
            return settings.max_image_bytes + MULTIPART_OVERHEAD
        return SMALL_BODY_LIMIT

    @staticmethod
    def _too_large(scope) -> tuple[str, str]:
        if scope["path"] == "/analyses":
            return IMAGE_TOO_LARGE, "image_too_large"
        return "Request too large.", default_code(413)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in _REQUEST_BODY_METHODS:
            return await self.app(scope, receive, send)

        limit = self._limit(scope)
        detail, code = self._too_large(scope)
        declared = _header(scope, b"content-length")
        if declared and declared.isdigit() and int(declared) > limit:
            return await _json_response(send, 413, {"detail": detail, "code": code})

        seen = 0
        state = {"started": False}

        async def counting_receive():
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > limit:
                    raise _BodyTooLarge()
            return message

        async def tracking_send(message):
            if message["type"] == "http.response.start":
                state["started"] = True
            await send(message)

        try:
            await self.app(scope, counting_receive, tracking_send)
        except _BodyTooLarge:
            if not state["started"]:
                await _json_response(send, 413, {"detail": detail, "code": code})
