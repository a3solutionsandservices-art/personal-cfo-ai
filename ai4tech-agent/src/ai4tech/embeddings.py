"""Embedding adapters, used only for novelty similarity (PRD §10).

The default is a dependency-free, deterministic hashing embedder so novelty
works offline and in tests (the same text always maps to the same vector, so a
re-processed episode scores maximal similarity and is correctly suppressed).
Any hosted embedding endpoint can implement ``embed`` and be selected by
``models.embeddings`` in settings.yaml.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol

_WORD = re.compile(r"[a-z0-9]+")


class Embedder(Protocol):
    def embed(self, text: str) -> list[float]:  # pragma: no cover - protocol
        ...


class HashEmbedder:
    """Hashing bag-of-words embedder (the ``hash-256`` default).

    Maps each token to a bucket via a stable hash and L2-normalises the result.
    Not semantic, but monotonic in lexical overlap — enough to catch the same
    signal re-surfacing across runs (FR-SCO-3).
    """

    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for tok in _WORD.findall(text.lower()):
            h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
            vec[h % self.dim] += 1.0
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0:
            return vec
        return [v / norm for v in vec]


def make_embedder(name: str) -> Embedder:
    if name in ("hash-256", "hash", ""):
        return HashEmbedder(256)
    if name.startswith("hash-"):
        try:
            return HashEmbedder(int(name.split("-", 1)[1]))
        except ValueError:
            return HashEmbedder(256)
    # A real hosted embedder would be constructed here based on `name`.
    # Until one is wired, fall back to the deterministic default.
    return HashEmbedder(256)
