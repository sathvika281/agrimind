"""Image storage abstraction. Local disk for the MVP; swap for object storage later.

Files live outside any static/public directory and are only served through the
authenticated, ownership-checked endpoint. Filenames are server-generated.
"""
import re
import uuid
from pathlib import Path
from typing import Protocol

from ..config import settings

_REF = re.compile(r"^[0-9a-f]{32}\.(jpg|png|webp)$")


class ImageStorage(Protocol):
    def save(self, data: bytes, ext: str) -> str: ...
    def read(self, ref: str) -> bytes | None: ...
    def delete(self, ref: str) -> None: ...


class LocalImageStorage:
    def _path(self, ref: str) -> Path | None:
        if not _REF.match(ref or ""):
            return None
        root = settings.uploads_dir.resolve()
        p = (root / ref).resolve()
        return p if p.parent == root else None

    def save(self, data: bytes, ext: str) -> str:
        if ext not in ("jpg", "png", "webp"):
            raise ValueError("unsupported extension")
        root = settings.uploads_dir
        root.mkdir(parents=True, exist_ok=True)
        ref = f"{uuid.uuid4().hex}.{ext}"
        path = self._path(ref)
        assert path is not None
        path.write_bytes(data)
        return ref

    def read(self, ref: str) -> bytes | None:
        p = self._path(ref)
        if p is None or not p.is_file():
            return None
        return p.read_bytes()

    def delete(self, ref: str) -> None:
        p = self._path(ref)
        if p is not None:
            p.unlink(missing_ok=True)

    def list_files(self) -> list[tuple[str, float]]:
        """(ref, mtime) for every well-formed upload file."""
        root = settings.uploads_dir
        if not root.is_dir():
            return []
        out = []
        for p in root.iterdir():
            if p.is_file() and _REF.match(p.name):
                out.append((p.name, p.stat().st_mtime))
        return out


storage: ImageStorage = LocalImageStorage()


def sweep_orphans(referenced: set[str], min_age_s: float = 3600, now: float | None = None) -> int:
    """Delete upload files that no analysis references and that are older than `min_age_s`
    (the age guard avoids racing an in-flight request). Covers a crash between writing the
    file and committing the row. Returns the number removed."""
    import time

    now = time.time() if now is None else now
    removed = 0
    for ref, mtime in storage.list_files():  # type: ignore[attr-defined]
        if ref not in referenced and now - mtime >= min_age_s:
            storage.delete(ref)
            removed += 1
    return removed
