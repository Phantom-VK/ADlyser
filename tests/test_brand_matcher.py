from types import SimpleNamespace

import numpy as np

from adlyser.agents.brand_matcher import match_brand
from adlyser.config import MatcherConfig
from adlyser.schemas import Brand, Rerank, SafetyTag, Scene

CFG = MatcherConfig(embed_model="x", shortlist_k=3, top_k=2, min_fit=0.3)
T = SafetyTag


class KeywordEmbedder:
    """Vectors from keyword counts, so similarity is predictable."""

    WORDS = ("cooking", "travel", "wedding")

    async def embed(self, texts):
        rows = np.array([[t.lower().count(w) + 0.01 for w in self.WORDS] for t in texts], dtype=np.float32)
        return rows / np.linalg.norm(rows, axis=1, keepdims=True)


class FakeText:
    """Returns a scripted rerank (or the fallback) and records the prompt."""

    def __init__(self, ranked=None):
        self.ranked = ranked
        self.prompt = None
        self.endpoint = SimpleNamespace(image_detail="low")

    async def chat_json(self, prompt, messages, model, fallback):
        self.prompt = messages[1]["content"]
        return Rerank.model_validate({"ranked": self.ranked}) if self.ranked is not None else fallback


def brand(bid, word, negatives=()):
    return Brand(
        id=bid,
        name=bid.title(),
        category=word,
        tagline="t",
        description=f"about {word}",
        target_contexts=[word],
        negative_tags=list(negatives),
        negative_contexts_raw=[],
    )


def scene(word, tags=(), unknown=False, index=0):
    return Scene(
        index=index,
        start=0,
        end=60,
        stretch_indices=[0],
        summary=f"people {word}",
        dominant_activity=word,
        activity_tags=[word],
        safety_tags=sorted(tags),
        unknown=unknown,
    )


FOOD = brand("food", "cooking", [T.DEATH_GRIEF])
RIDES = brand("rides", "travel")
RINGS = brand("rings", "wedding", [T.DEATH_GRIEF])
ALL = [FOOD, RIDES, RINGS]


def rank(*pairs):
    return [{"brand_id": b, "fit": f, "reason": "r"} for b, f in pairs]


async def test_picks_the_best_reranked_brand():
    client = FakeText(rank(("food", 0.9), ("rides", 0.2)))
    out = await match_brand(KeywordEmbedder(), client, ALL, scene("cooking"), scene("travel"), set(), CFG)
    assert out.brand_id == "food" and out.blocked == []
    assert out.shortlist[0].similarity > out.shortlist[-1].similarity or len(out.shortlist) == 1


async def test_blocked_brands_are_reported_with_the_tag_and_never_shown_to_the_reranker():
    client = FakeText(rank(("rides", 0.8)))
    out = await match_brand(
        KeywordEmbedder(), client, ALL, scene("cooking", {T.DEATH_GRIEF}), scene("travel"), set(), CFG
    )
    assert {(b.brand_id, tuple(b.tags)) for b in out.blocked} == {
        ("food", ("death_grief",)),
        ("rings", ("death_grief",)),
    }
    assert out.brand_id == "rides"
    assert "id=food" not in client.prompt and "id=rings" not in client.prompt


async def test_a_blocked_or_invented_brand_from_the_reranker_is_never_chosen():
    client = FakeText(rank(("food", 1.0), ("ghost", 0.95), ("rides", 0.5)))
    out = await match_brand(
        KeywordEmbedder(), client, ALL, scene("cooking", {T.DEATH_GRIEF}), scene("travel"), set(), CFG
    )
    assert out.brand_id == "rides"
    assert [e.brand_id for e in out.shortlist] == ["rides"]


async def test_tag_on_the_scene_after_blocks_too():
    out = await match_brand(
        KeywordEmbedder(),
        FakeText(rank(("rides", 0.8))),
        ALL,
        scene("travel"),
        scene("x", {T.DEATH_GRIEF}),
        set(),
        CFG,
    )
    assert {b.brand_id for b in out.blocked} == {"food", "rings"} and out.brand_id == "rides"


async def test_unknown_scene_gives_a_promo_slot_and_blocks_everyone():
    for before, after in [(scene("a", unknown=True), scene("b")), (scene("a"), scene("b", unknown=True))]:
        client = FakeText(rank(("food", 1.0)))
        out = await match_brand(KeywordEmbedder(), client, ALL, before, after, set(), CFG)
        assert (
            out.brand_id is None and out.kind == "blocked" and len(out.blocked) == 3 and client.prompt is None
        )


async def test_excluded_brands_are_skipped():
    client = FakeText(rank(("rides", 0.7), ("rings", 0.6)))
    out = await match_brand(KeywordEmbedder(), client, ALL, scene("cooking"), scene("travel"), {"food"}, CFG)
    assert "id=food" not in client.prompt and out.brand_id == "rides"


async def test_when_every_brand_is_blocked_the_kind_is_blocked_so_the_graph_can_try_another_break():
    out = await match_brand(
        KeywordEmbedder(), FakeText(rank()), [FOOD], scene("a", {T.DEATH_GRIEF}), scene("b"), set(), CFG
    )
    assert out.kind == "blocked" and out.brand_id is None


async def test_vetoed_brands_exhausting_the_pool_is_not_a_block():
    out = await match_brand(
        KeywordEmbedder(), FakeText(rank()), ALL, scene("a"), scene("b"), {"food", "rides", "rings"}, CFG
    )
    assert out.kind == "no_fit" and out.brand_id is None


async def test_no_eligible_brand_gives_no_brand():
    out = await match_brand(
        KeywordEmbedder(),
        FakeText(rank()),
        ALL,
        scene("cooking"),
        scene("x"),
        {"food", "rides", "rings"},
        CFG,
    )
    assert out.brand_id is None


async def test_a_poor_fit_gives_no_brand_and_is_not_a_block():
    out = await match_brand(
        KeywordEmbedder(), FakeText(rank(("food", 0.1))), ALL, scene("cooking"), scene("x"), set(), CFG
    )
    assert out.brand_id is None and out.kind == "no_fit" and out.reason.startswith("no brand fits")


async def test_rerank_failure_falls_back_to_embedding_order():
    out = await match_brand(KeywordEmbedder(), FakeText(None), ALL, scene("travel"), scene("x"), set(), CFG)
    assert out.brand_id == "rides" and out.shortlist[0].reason == "embedding similarity"
