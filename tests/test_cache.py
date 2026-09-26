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


def test_temp_paths_are_unique_and_sit_next_to_the_target(tmp_path):
    from adlyser.cache import unique_tmp

    target = tmp_path / "k.json"
    a, b = unique_tmp(target), unique_tmp(target)
    assert a != b and a.parent == b.parent == tmp_path and a.suffix == ".tmp" and a != target
