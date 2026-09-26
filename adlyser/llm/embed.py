"""Sentence embeddings behind one function, so the model is a config value. Vectors are cached on disk."""

import asyncio
from typing import Any

import numpy as np

from adlyser.cache import DiskCache, content_key
from adlyser.log import get_logger

log = get_logger(__name__)


class Embedder:
    """Embeds texts with a sentence-transformers model, loaded lazily on the first cache miss."""

    def __init__(self, model_name: str, cache: DiskCache) -> None:
        """Create an embedder.

        :param model_name: sentence-transformers model id (e.g. ``BAAI/bge-m3``).
        :param cache: disk cache for the vectors.
        """
        self.model_name = model_name
        self.cache = cache
        self._model: Any = None

    def _encode(self, texts: list[str]) -> list[list[float]]:
        """Load the model if needed and encode ``texts`` to unit-length vectors."""
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # heavy import, only on a cache miss

            log.info("embed_model_load", extra={"model": self.model_name})
            self._model = SentenceTransformer(self.model_name, device="cpu")
        return self._model.encode(texts, normalize_embeddings=True).tolist()

    async def embed(self, texts: list[str]) -> np.ndarray:
        """Embed texts (unit-length rows), computing only the ones not cached.

        :param texts: the texts.
        :return: an array of shape ``(len(texts), dim)``.
        """
        keys = [content_key(self.model_name, t) for t in texts]
        vectors: dict[int, list[float]] = {}
        for i, key in enumerate(keys):
            hit = self.cache.get("embed", key)
            if hit is not None:
                vectors[i] = hit
        missing = [i for i in range(len(texts)) if i not in vectors]
        if missing:
            fresh = await asyncio.to_thread(self._encode, [texts[i] for i in missing])
            for i, vec in zip(missing, fresh, strict=True):
                vectors[i] = vec
                self.cache.set("embed", keys[i], vec)
        return np.array([vectors[i] for i in range(len(texts))], dtype=np.float32)
