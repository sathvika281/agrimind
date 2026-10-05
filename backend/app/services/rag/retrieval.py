"""Retrieval: BM25 lexical ranking + crop/topic metadata filtering, in plain Python.

No vector database, no embedding API and no model: ranking is a transparent term-statistics formula over the
local corpus, so a result can always be traced to the words that matched. An empty or missing corpus is a
normal state ("no knowledge base"), never an error.
"""
import json
import logging
import math
import re
from collections import Counter
from pathlib import Path

from ...config import settings
from .models import Chunk

log = logging.getLogger("agrimind.rag")

K1, B = 1.5, 0.75
MIN_SCORE = 1.0  # below this the match is too weak to cite
SATURATION = 6.0  # relevance = score / (score + SATURATION): a 0..1 display value, monotonic in the BM25 score
_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = frozenset("a an and are as at be by for from has have in is it its of on or that the this to was were with".split())


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall((text or "").lower()) if t not in _STOP and len(t) > 1]


class Index:
    def __init__(self, chunks: list[Chunk]):
        self.chunks = chunks
        self._tf = [Counter(tokenize(c.text + " " + c.title)) for c in chunks]
        self._len = [sum(tf.values()) for tf in self._tf]
        self._avg = (sum(self._len) / len(chunks)) if chunks else 0.0
        df: Counter = Counter()
        for tf in self._tf:
            df.update(tf.keys())
        n = len(chunks)
        self._idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}

    def __len__(self) -> int:
        return len(self.chunks)

    def search(self, query: str, crop: str = "", topic: str = "", k: int = 4) -> list[tuple[Chunk, float]]:
        """Top-k chunks for the query. A crop filter keeps chunks for that crop AND general (crop-less) ones."""
        q = tokenize(query)
        if not q or not self.chunks:
            return []
        crop_l, topic_l = crop.strip().lower(), topic.strip().lower()
        scored = []
        for i, c in enumerate(self.chunks):
            if crop_l and c.crop and c.crop.lower() != crop_l:
                continue
            if topic_l and topic_l not in c.topic.lower():
                continue
            tf, dl = self._tf[i], self._len[i]
            s = 0.0
            for t in set(q):
                f = tf.get(t, 0)
                if f:
                    s += self._idf.get(t, 0.0) * f * (K1 + 1) / (f + K1 * (1 - B + B * dl / (self._avg or 1)))
            if s >= MIN_SCORE:
                scored.append((c, s))
        scored.sort(key=lambda x: -x[1])
        return [(c, s) for c, s in scored[:k]]


def load_chunks(path: Path) -> list[Chunk]:
    """Read the corpus. Malformed lines are skipped (and counted in the log), never fatal."""
    if not path.exists():
        return []
    out, bad = [], 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            out.append(Chunk.model_validate(json.loads(line)))
        except Exception:  # noqa: BLE001
            bad += 1
    if bad:
        log.warning("knowledge corpus: %s malformed line(s) skipped", bad)
    return out


_cache: dict[str, tuple[float, Index]] = {}


def get_index(directory: Path | None = None) -> Index:
    """The index for the current corpus file, rebuilt only when the file changes."""
    path = (directory or settings.knowledge_dir) / "documents.jsonl"
    key = str(path)
    mtime = path.stat().st_mtime if path.exists() else -1.0
    hit = _cache.get(key)
    if hit and hit[0] == mtime:
        return hit[1]
    idx = Index(load_chunks(path))
    _cache[key] = (mtime, idx)
    return idx
