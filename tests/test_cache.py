from adlyser.cache import DiskCache, content_key


def test_key_is_stable_and_order_independent():
    assert content_key({"a": 1, "b": 2}) == content_key({"b": 2, "a": 1})
    assert content_key("x") != content_key("y")


def test_roundtrip_and_miss(tmp_path):
    cache = DiskCache(tmp_path)
    assert cache.get("ns", "k") is None
    cache.set("ns", "k", {"v": [1, 2]})
    assert cache.get("ns", "k") == {"v": [1, 2]}


def test_corrupt_entry_is_a_miss(tmp_path):
    cache = DiskCache(tmp_path)
    cache.set("ns", "k", {"v": 1})
    (tmp_path / "ns" / "k.json").write_text("{not json")
    assert cache.get("ns", "k") is None
