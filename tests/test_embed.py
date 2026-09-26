import numpy as np

from adlyser.cache import DiskCache
from adlyser.llm.embed import Embedder


class FakeModel:
    def __init__(self):
        self.encoded = []

    def encode(self, texts, normalize_embeddings=True):
        self.encoded.append(list(texts))
        return np.array([[float(len(t)), 1.0] for t in texts])


def embedder(tmp_path):
    emb = Embedder("m", DiskCache(tmp_path))
    emb._model = FakeModel()
    return emb


async def test_only_uncached_texts_are_encoded(tmp_path):
    emb = embedder(tmp_path)
    await emb.embed(["a", "bb"])
    out = await emb.embed(["bb", "ccc"])
    assert emb._model.encoded == [["a", "bb"], ["ccc"]]
    assert out.tolist() == [[2.0, 1.0], [3.0, 1.0]]


async def test_everything_cached_needs_no_model_at_all(tmp_path):
    first = embedder(tmp_path)
    await first.embed(["a"])
    second = Embedder("m", DiskCache(tmp_path))  # no model set: loading would fail
    assert (await second.embed(["a"])).tolist() == [[1.0, 1.0]]


async def test_preload_loads_the_model_once(tmp_path, monkeypatch):
    emb = Embedder("m", DiskCache(tmp_path))
    loads = []

    def fake_load():
        loads.append(1)
        emb._model = FakeModel()

    monkeypatch.setattr(emb, "_load", fake_load)
    await emb.preload()
    assert loads == [1]
