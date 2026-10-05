"""Data model of the local knowledge base: an audited source manifest and a chunk corpus.

knowledge/sources.json    every source considered, with provenance and whether it was INCLUDED (and why not)
knowledge/documents.jsonl one JSON chunk per line, each carrying its source metadata and a content hash
"""
from pydantic import BaseModel, Field


class SourceEntry(BaseModel):
    url: str
    title: str = ""
    institution: str = ""
    crop: str = ""  # lower-case crop name, or "" for general (crop-independent) material
    topics: list[str] = Field(default_factory=list)
    region: str = ""
    published: str | None = None  # publication/update date as stated by the source, if any
    retrieved_at: str = ""  # UTC ISO time the page was actually fetched
    included: bool = False
    reason: str = ""  # why it is (not) included
    content_hash: str = ""  # sha256 of the normalised text that was ingested
    update_available: bool = False  # the live page changed since ingestion; NOT applied automatically


class Chunk(BaseModel):
    id: str
    source_url: str
    title: str
    institution: str
    crop: str = ""
    topic: str = ""
    region: str = ""
    date: str | None = None
    retrieved_at: str = ""
    content_hash: str  # of this chunk's text (duplicate detection)
    text: str
