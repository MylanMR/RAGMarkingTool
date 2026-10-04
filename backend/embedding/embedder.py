"""Embedding backends.

The pipeline only depends on the Embedder protocol, so the deterministic
HashingEmbedder used for development and tests can be swapped for a real
model (sentence-transformers, an embedding API, etc.) without touching the
marking or storage logic.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import List, Protocol


class Embedder(Protocol):
    dim: int

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        ...


class HashingEmbedder:
    """Deterministic, dependency-free bag-of-words hashing embedder.

    Texts sharing vocabulary land near each other under cosine similarity,
    which is enough to exercise storage and filtered retrieval end to end.
    It is a development stand-in, not a semantic model.
    """

    def __init__(self, dim: int = 384):
        if dim < 8:
            raise ValueError("embedding dimension must be at least 8")
        self.dim = dim

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> List[float]:
        if not text or not text.strip():
            raise ValueError("cannot embed empty text")
        vec = [0.0] * self.dim
        for token in re.findall(r"[a-z0-9]+", text.lower()):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vec[index] += sign
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0.0:
            # Text had no alphanumeric tokens; hash the raw text instead so
            # the embedding is still deterministic and non-zero.
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dim
            vec[index] = 1.0
            return vec
        return [v / norm for v in vec]


def get_embedder() -> Embedder:
    """FastAPI dependency for the configured embedder."""
    return HashingEmbedder()
