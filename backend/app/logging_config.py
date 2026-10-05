"""Consistently formatted application logs with a per-request id.

Never log secrets, cookies, prompts or image bytes. This module only wires formatting;
callers are responsible for what they put in messages (categories, ids, durations).
"""
import logging
from contextvars import ContextVar

from .config import settings

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

_FORMAT = "%(asctime)s %(levelname)s %(name)s rid=%(request_id)s %(message)s"


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


def setup_logging() -> None:
    root = logging.getLogger("agrimind")
    if not any(getattr(h, "_agrimind", False) for h in root.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(_FORMAT))
        handler.addFilter(_RequestIdFilter())
        handler._agrimind = True  # type: ignore[attr-defined]
        root.addHandler(handler)
        root.propagate = False  # avoid duplicate lines under uvicorn
    root.setLevel(getattr(logging, settings.log_level, logging.INFO))
    # Our middleware logs one access line per request; httpx would log full URLs (incl. coordinates).
    logging.getLogger("uvicorn.access").disabled = True
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
