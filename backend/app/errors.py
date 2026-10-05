"""Consistent API error model.

Every error body has `detail` (human text, unchanged from earlier phases) and `code`
(stable machine-readable string). 5xx bodies also carry `request_id` for support; 4xx
bodies deliberately do not, so equivalent failures (e.g. foreign vs missing resource)
stay byte-identical. The request id is always in the X-Request-ID response header.
"""
from fastapi import HTTPException

_DEFAULT_CODES = {
    400: "invalid_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    422: "invalid_request",
    429: "rate_limited",
    500: "server_error",
    502: "service_unavailable",
    503: "service_unavailable",
}


def default_code(status: int) -> str:
    return _DEFAULT_CODES.get(status, "server_error" if status >= 500 else "invalid_request")


class AppError(HTTPException):
    """HTTPException with an explicit machine-readable code."""

    def __init__(self, status_code: int, detail: str, code: str | None = None, headers: dict | None = None):
        super().__init__(status_code=status_code, detail=detail, headers=headers)
        self.code = code or default_code(status_code)
