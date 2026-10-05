"""Discovery: validate candidate sources and record them in the audited manifest (sources.json).

The SEARCH for candidates is done by a person or by Claude with a web-search tool (this module has no search API
and never invents URLs). What this module does, for every candidate, is the part that must be reproducible:

    https? -> authoritative host? -> page really fetched? -> readable? -> real agricultural content? -> not a duplicate
    -> recorded (included or excluded, always WITH the reason and retrieval time)

Nothing is ingested here; `python -m app.rag.ingest` does that for the sources marked included.
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from ...config import settings
from .ingestion import Fetch, IngestError, check_quality, default_fetch, extract, read_manifest, sha, write_manifest
from .models import SourceEntry

# Host suffixes that qualify a source as institutional. Government (.gov.in/.nic.in), research (.res.in) and
# academic (.ac.in/.edu.in) domains of India, plus FAO as the one international body. Blogs, SEO farming sites,
# forums, social media and commercial product sites do not match and are excluded by construction.
AUTHORITATIVE_SUFFIXES = (".gov.in", ".nic.in", ".res.in", ".ac.in", ".edu.in", ".icar.org.in", ".fao.org")
# Individual ICAR institutes that publish on a plain .org.in / .in host (each one checked by hand before being listed here).
EXACT_HOSTS = ("icar.org.in", "icar.gov.in", "fao.org", "agricoop.nic.in", "cicr.org.in", "www.cicr.org.in")
EXCLUDED_HINTS = ("quora.", "reddit.", "facebook.", "youtube.", "wikipedia.", "blogspot.", "wordpress.", "medium.", "pinterest.")

_DATE = re.compile(r"(?:last\s+updated|updated\s+on|published(?:\s+on)?|date)\s*[:\-]?\s*([0-3]?\d[\s/\-.][A-Za-z0-9]{1,9}[\s/\-.]\d{2,4})", re.I)


def host_ok(url: str) -> str | None:
    """None if the host qualifies, else the reason code."""
    p = urlparse(url)
    if p.scheme != "https" or not p.hostname:
        return "not_https"
    h = p.hostname.lower()
    if any(x in h for x in EXCLUDED_HINTS):
        return "excluded_site_type"
    if not (h.endswith(AUTHORITATIVE_SUFFIXES) or h in EXACT_HOSTS):
        return "not_an_authoritative_domain"
    return None


def validate(candidate: dict, fetch: Fetch = default_fetch, known: dict[str, SourceEntry] | None = None,
             known_hashes: dict[str, str] | None = None) -> SourceEntry:
    """candidate: {url, institution, crop?, topics?, region?, title?}. Returns the manifest entry (included or not)."""
    url = str(candidate.get("url", "")).strip()
    e = SourceEntry(
        url=url, title=str(candidate.get("title", "")), institution=str(candidate.get("institution", "")).strip(),
        crop=str(candidate.get("crop", "")).strip().lower(), topics=[str(t) for t in candidate.get("topics", [])],
        region=str(candidate.get("region", "")),
        retrieved_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )

    def out(reason: str) -> SourceEntry:
        e.included, e.reason = False, reason
        return e

    if not e.institution:
        return out("institution_not_stated")
    bad = host_ok(url)
    if bad:
        return out(bad)
    if known and url in known and known[url].included:
        return known[url]
    try:
        ctype, body = fetch(url)
        title, text = extract(ctype, body)
        check_quality(text)
    except IngestError as err:
        return out(f"rejected:{err}")
    e.title = e.title or title or url
    h = sha(text)
    other = (known_hashes or {}).get(h)
    if other and other != url:
        return out(f"duplicate_of:{other}")
    m = _DATE.search(text[:4000])
    e.published = m.group(1) if m else None
    e.content_hash = ""  # set by ingestion, which is what actually stores the text
    e.included, e.reason = True, "verified: authoritative host, fetched, readable, agricultural content"
    return e


def discover(candidates: list[dict], directory: Path | None = None, fetch: Fetch = default_fetch) -> list[SourceEntry]:
    d = directory or settings.knowledge_dir
    path = d / "sources.json"
    entries = {e.url: e for e in read_manifest(path)}
    hashes = {e.content_hash: e.url for e in entries.values() if e.content_hash}
    for c in candidates:
        e = validate(c, fetch=fetch, known=entries, known_hashes=hashes)
        if e.url in entries and entries[e.url].included and entries[e.url] is not e:
            continue  # previously trusted entries are never overwritten here
        entries[e.url] = e
    out = list(entries.values())
    write_manifest(path, out)
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="python -m app.rag.discover", description="Validate candidate sources and update knowledge/sources.json.")
    ap.add_argument("candidates", help="JSON file: [{url, institution, crop?, topics?, region?, title?}, ...]")
    args = ap.parse_args(argv)
    items = json.loads(Path(args.candidates).read_text(encoding="utf-8"))
    res = discover(items)
    inc = [e for e in res if e.included]
    print(f"{len(inc)} included, {len(res) - len(inc)} excluded (of {len(res)} in the manifest)")
    for e in res:
        print(f"  {'INCLUDED ' if e.included else 'excluded '} {e.url}  [{e.reason}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
