"""Upload validation. Never trusts the filename or the declared MIME type alone."""
from dataclasses import dataclass

ALLOWED = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}
EXT_TO_MIME = {v: k for k, v in ALLOWED.items()}

MSG_UNSUPPORTED = "Please upload a supported image file (JPG, PNG or WebP)."
MSG_TOO_LARGE = "That image is too large. Please choose a smaller photo."
MSG_EMPTY = "That image file is empty. Please choose another photo."


class ImageError(Exception):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.message = message
        self.status = status


@dataclass
class ValidatedImage:
    data: bytes
    mime_type: str
    ext: str


def sniff_mime(data: bytes) -> str | None:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def validate_image(data: bytes, declared_mime: str | None, max_bytes: int) -> ValidatedImage:
    if not data:
        raise ImageError(MSG_EMPTY)
    if len(data) > max_bytes:
        raise ImageError(MSG_TOO_LARGE, 413)
    declared = (declared_mime or "").split(";")[0].strip().lower()
    if declared == "image/jpg":
        declared = "image/jpeg"
    detected = sniff_mime(data)
    # Content must be a real supported image, and the declared type must agree with it.
    if detected is None or declared not in ALLOWED or declared != detected:
        raise ImageError(MSG_UNSUPPORTED)
    return ValidatedImage(data=data, mime_type=detected, ext=ALLOWED[detected])
