"""Ingestion: approved sources -> text -> chunks -> corpus. Reproducible and provenance-preserving.

    sources.json (approved entries) -> fetch -> extract text -> quality checks -> chunk -> dedupe -> documents.jsonl

- Never fetches anything that is not an approved entry in sources.json; https only; size/time bounded.
- Duplicate pages (same normalised text) and duplicate chunks are never added twice (content hashes).
- A previously ingested page that changed upstream is NOT silently replaced: it is flagged `update_available`;
  with accept_updates=True the old chunks are moved to documents.archive.jsonl first (provenance kept).
- Inaccessible, malformed, too-short or non-agricultural pages are recorded with a reason and add nothing.
"""
import hashlib
import io
import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable

import httpx

from ...config import settings
from .models import Chunk, SourceEntry

log = logging.getLogger("agrimind.rag")

MAX_BYTES = 4_000_000
MIN_CHARS = 350
CHUNK_CHARS, OVERLAP_CHARS = 900, 150
USER_AGENT = "AgriMindKnowledgeBot/1.0 (agricultural decision-support research; contact: operator)"
_AGRI = re.compile(
    r"\b(crop|crops|disease|diseases|pest|pests|symptom|symptoms|leaf|leaves|fungal|fungus|bacterial|virus|insect|"
    r"nutrient|deficiency|soil|yield|seedling|plant|plants|infestation|spots?|wilt|blight|rot)\b", re.I)
MIN_AGRI_HITS = 6  # short single-topic pages (one disease) are fine; unrelated pages have ~0

Fetch = Callable[[str], tuple[str, bytes]]


class IngestError(Exception):
    """A page that cannot be used; the message is a short reason code stored in the manifest."""


def _reason(e: Exception) -> str:
    msg = str(e).lower()
    if "certificate" in msg or "ssl" in msg:
        return "tls_certificate_not_verifiable"  # never bypassed: an unverifiable site is simply not used
    if "getaddrinfo" in msg or "name or service not known" in msg:
        return "dns_not_resolved"
    return f"unreachable_{type(e).__name__}"


def default_fetch(url: str) -> tuple[str, bytes]:
    """https only, TLS always verified, size-capped. Transient failures (timeouts, resets, 5xx) get 3 attempts."""
    if not url.lower().startswith("https://"):
        raise IngestError("not_https")
    last = "unreachable"
    for attempt in range(3):
        try:
            with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(20.0), headers={"User-Agent": USER_AGENT}) as c:
                with c.stream("GET", url) as r:
                    if r.status_code >= 500:
                        last = f"http_{r.status_code}"
                        raise httpx.TransportError(last)
                    if r.status_code >= 400:
                        raise IngestError(f"http_{r.status_code}")
                    body = b""
                    for part in r.iter_bytes():
                        body += part
                        if len(body) > MAX_BYTES:
                            raise IngestError("too_large")
                    return r.headers.get("content-type", ""), body
        except IngestError:
            raise
        except httpx.HTTPError as e:
            last = _reason(e) if not str(e).startswith("http_") else str(e)
            if last == "dns_not_resolved":
                raise IngestError(last) from None
            time.sleep(1.5 * (attempt + 1))
    raise IngestError(last)


class _Text(HTMLParser):
    _SKIP = {"script", "style", "nav", "footer", "header", "noscript", "form", "aside", "svg"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip += 1
        if tag == "title":
            self._in_title = True
        if tag in ("p", "br", "li", "div", "h1", "h2", "h3", "h4", "tr"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.parts.append(data)


# AgriMind gives no pesticide, product, dose or spray advice, so the corpus does not store any: sentences about chemical
# treatment, doses and application are removed at ingestion (what remains is symptoms, biology, conditions, monitoring).
_DOSE = re.compile(
    r"@\s*\d|\d(?:\.\d+)?\s*(?:%|ppm|g|gm|kg|ml|l|lit|litres?|liters?|cc)\s*(?:/|per)\s*(?:l|lit|litres?|liters?|ha|hectare|acre|plant|kg|100|10|ac|gal)\b"
    r"|\b\d+(?:\.\d+)?\s*(?:ml|g|gm|kg)\b", re.I)
_TREATMENT = re.compile(
    r"\b(spray\w*|dust|dusting|drench|drenching|dipping|wettable|sulphur|sulfur|agrimycin|ppm|per cent|extract|fungicides?|insecticides?|pesticides?|acaricides?|bactericides?|"
    r"nematicides?|herbicides?|chemical control|seed treatment|seed dressing|soil application|foliar application|"
    r"mancozeb|carbendazim|chlorothalonil|dithane|bavistin|karathane|dinocap|imidacloprid|thiamethoxam|copper oxychloride|"
    r"streptocycline|monocrotophos|quinalphos|profenofos|acephate|chlorpyriphos|dimethoate|cypermethrin|metalaxyl|"
    r"propiconazole|hexaconazole|azoxystrobin|neem oil|neem seed kernel|nske|pseudomonas fluorescens|trichoderma)\b", re.I)


def strip_treatment(text: str) -> str:
    """Drop every sentence that talks about chemical/product treatment or contains a dose or concentration."""
    kept = []
    for line in text.split("\n"):
        sentences = re.split(r"(?<=[.!?;])\s+", line)
        keep = [x for x in sentences if not (_DOSE.search(x) or _TREATMENT.search(x))]
        if keep:
            kept.append(" ".join(keep))
    return "\n".join(kept)


def normalise(text: str) -> str:
    text = "\n".join(ln for ln in text.split("\n") if not _NAV.search(ln))  # the site's menu bar is not content
    return re.sub(r"[ \t\r\f\v]+", " ", re.sub(r"\n\s*\n+", "\n", text)).strip()


def extract(content_type: str, body: bytes) -> tuple[str, str]:
    """(title, text) from an HTML page or a PDF. Anything else, or an unreadable body, is an IngestError."""
    ct = content_type.lower()
    if "pdf" in ct or body[:5] == b"%PDF-":
        try:
            from pypdf import PdfReader  # optional dependency, only needed for PDF sources
        except ImportError:
            raise IngestError("pdf_support_not_installed") from None
        try:
            reader = PdfReader(io.BytesIO(body))
            text = "\n".join((p.extract_text() or "") for p in reader.pages[:60])
            title = str((reader.metadata or {}).get("/Title") or "")
        except Exception:  # noqa: BLE001
            raise IngestError("malformed_pdf") from None
        return title.strip(), normalise(strip_treatment(text))
    if "html" in ct or body.lstrip()[:15].lower().startswith((b"<!doctype", b"<html")):
        try:
            p = _Text()
            p.feed(_decode(body))
        except Exception:  # noqa: BLE001
            raise IngestError("malformed_html") from None
        return p.title.strip(), normalise(strip_treatment("".join(p.parts)))
    raise IngestError("unsupported_content_type")


def _decode(body: bytes) -> str:
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        return body.decode("cp1252", errors="replace")  # older institutional pages are Windows-1252


_NAV = re.compile(r"^\s*Home\b.*\|.*\bContact\b", re.I)


def check_quality(text: str) -> None:
    if len(text) < MIN_CHARS:
        raise IngestError("too_short")
    if len(_AGRI.findall(text)) < MIN_AGRI_HITS:
        raise IngestError("not_agricultural")


def chunk_text(text: str) -> list[str]:
    paras = [p.strip() for p in text.split("\n") if len(p.strip()) > 40]
    chunks, cur = [], ""
    for p in paras:
        if cur and len(cur) + len(p) > CHUNK_CHARS:
            chunks.append(cur)
            cur = cur[-OVERLAP_CHARS:].split(" ", 1)[-1] + " " + p
        else:
            cur = (cur + " " + p).strip()
    if cur:
        chunks.append(cur)
    out = []
    for c in chunks:  # a single over-long paragraph is split on length
        while len(c) > CHUNK_CHARS * 1.5:
            cut = c.rfind(" ", 0, CHUNK_CHARS)
            cut = cut if cut > 0 else CHUNK_CHARS
            out.append(c[:cut].strip())
            c = c[cut - OVERLAP_CHARS if cut > OVERLAP_CHARS else cut:].strip()
        if c:
            out.append(c)
    return [c for c in out if len(c) > 80]


def sha(text: str) -> str:
    return hashlib.sha256(" ".join(text.lower().split()).encode("utf-8")).hexdigest()


@dataclass
class Report:
    sources_ingested: int = 0
    sources_unchanged: int = 0
    chunks_added: int = 0
    duplicate_chunks: int = 0
    failures: dict[str, str] = field(default_factory=dict)  # url -> reason
    updates_available: list[str] = field(default_factory=list)


def read_manifest(path: Path) -> list[SourceEntry]:
    if not path.exists():
        return []
    return [SourceEntry.model_validate(x) for x in json.loads(path.read_text(encoding="utf-8"))]


def write_manifest(path: Path, entries: list[SourceEntry]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps([e.model_dump() for e in entries], indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _read_chunks(path: Path) -> list[Chunk]:
    if not path.exists():
        return []
    return [Chunk.model_validate(json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_chunks(path: Path, chunks: list[Chunk]) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text("".join(c.model_dump_json() + "\n" for c in chunks), encoding="utf-8")
    tmp.replace(path)


def ingest(directory: Path | None = None, fetch: Fetch = default_fetch, accept_updates: bool = False) -> Report:
    d = directory or settings.knowledge_dir
    manifest_path, corpus_path, archive_path = d / "sources.json", d / "documents.jsonl", d / "documents.archive.jsonl"
    entries = read_manifest(manifest_path)
    chunks = _read_chunks(corpus_path)
    seen_chunk_hashes = {c.content_hash for c in chunks}
    doc_hash_owner = {e.content_hash: e.url for e in entries if e.content_hash and e.included}
    report = Report()

    for e in entries:
        if not e.included:
            continue
        have = [c for c in chunks if c.source_url == e.url]
        try:
            ctype, body = fetch(e.url)
            title, text = extract(ctype, body)
            check_quality(text)
        except IngestError as err:
            report.failures[e.url] = str(err)
            e.reason = f"ingest_failed:{err}"
            continue
        h = sha(text)
        if have and e.content_hash == h:
            report.sources_unchanged += 1
            e.update_available = False
            continue
        if have and e.content_hash != h and not accept_updates:
            e.update_available = True
            report.updates_available.append(e.url)
            continue
        owner = doc_hash_owner.get(h)
        if owner and owner != e.url:
            e.included, e.reason = False, f"duplicate_of:{owner}"
            continue
        if have:  # an accepted update: keep the old version's provenance in the archive
            with archive_path.open("a", encoding="utf-8") as f:
                f.write("".join(c.model_dump_json() + "\n" for c in have))
            chunks = [c for c in chunks if c.source_url != e.url]
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for i, piece in enumerate(chunk_text(text)):
            ch = sha(piece)
            if ch in seen_chunk_hashes:
                report.duplicate_chunks += 1
                continue
            seen_chunk_hashes.add(ch)
            chunks.append(Chunk(
                id=hashlib.sha1(f"{e.url}#{i}".encode()).hexdigest()[:12], source_url=e.url, title=e.title or title, institution=e.institution,
                crop=e.crop, topic=", ".join(e.topics), region=e.region, date=e.published, retrieved_at=now, content_hash=ch, text=piece,
            ))
            report.chunks_added += 1
        e.content_hash, e.retrieved_at, e.update_available, e.reason = h, now, False, "ingested"
        doc_hash_owner[h] = e.url
        report.sources_ingested += 1

    d.mkdir(parents=True, exist_ok=True)
    _write_chunks(corpus_path, chunks)
    write_manifest(manifest_path, entries)
    return report


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="python -m app.rag.ingest", description="Fetch approved sources and build the local corpus.")
    ap.add_argument("--accept-updates", action="store_true", help="re-ingest pages that changed upstream (old chunks are archived)")
    args = ap.parse_args(argv)
    r = ingest(accept_updates=args.accept_updates)
    print(f"ingested {r.sources_ingested}, unchanged {r.sources_unchanged}, chunks added {r.chunks_added}, duplicate chunks skipped {r.duplicate_chunks}")
    for url, why in r.failures.items():
        print(f"  FAILED {url}: {why}")
    for url in r.updates_available:
        print(f"  UPDATE AVAILABLE (not applied) {url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
