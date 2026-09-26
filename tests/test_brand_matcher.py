from types import SimpleNamespace

import numpy as np

from adlyser.agents.brand_matcher import match_brand, spread_brands
from adlyser.config import MatcherConfig
from adlyser.schemas import Brand, BrandChoice, Rerank, SafetyTag, Scene, ShortlistEntry

CFG = MatcherConfig(embed_model="x", shortlist_k=3, top_k=2, min_fit=0.3, max_per_brand=1)
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


async def test_a_failed_rerank_is_no_fit_and_cosine_similarity_is_never_used_as_fit():
    out = await match_brand(KeywordEmbedder(), FakeText(None), ALL, scene("travel"), scene("x"), set(), CFG)
    assert out.brand_id is None and out.kind == "no_fit" and "rerank" in out.reason
    assert out.shortlist and all(e.fit is None for e in out.shortlist)  # the trace still shows the shortlist


# ---- frequency cap ----------------------------------------------------------


def picked(*fits):
    """A brand choice whose shortlist has brands a, b, c ... with these fits (best first); the first is chosen."""
    entries = [
        ShortlistEntry(brand_id=name, name=name.upper(), similarity=0.5, fit=fit, reason="r")
        for name, fit in zip("abcd", fits, strict=False)
    ]
    return BrandChoice(
        kind="brand", brand_id=entries[0].brand_id, shortlist=entries, blocked=[], reason="best fit"
    )


def test_two_breaks_with_the_same_top_brand_give_the_second_the_runner_up():
    out = spread_brands([picked(0.9, 0.6), picked(0.8, 0.7)], {}, CFG)
    assert [c.brand_id for c, _ in out] == ["a", "b"]
    assert out[0][1] == "" and "A" in out[1][1] and "runner-up" in out[1][1]


def test_a_repeat_beats_a_promo_when_no_other_brand_fits_well_enough():
    out = spread_brands([picked(0.9, 0.2), picked(0.8, 0.1)], {}, CFG)
    assert [c.brand_id for c, _ in out] == ["a", "a"]
    assert out[1][1] == "repeat allowed: no alternative"


def test_a_repeat_is_allowed_when_the_shortlist_has_only_the_one_brand():
    out = spread_brands([picked(0.9), picked(0.9)], {}, CFG)
    assert [c.brand_id for c, _ in out] == ["a", "a"] and out[1][1] == "repeat allowed: no alternative"


def test_brands_used_by_breaks_already_placed_count_and_the_cap_is_configurable():
    out = spread_brands([picked(0.9, 0.6)], {"a": 1}, CFG)
    assert out[0][0].brand_id == "b"
    twice = CFG.model_copy(update={"max_per_brand": 2})
    assert spread_brands([picked(0.9, 0.6)], {"a": 1}, twice)[0][0].brand_id == "a"


def test_the_runner_up_must_itself_be_under_the_cap():
    out = spread_brands([picked(0.9, 0.8, 0.7)], {"a": 1, "b": 1}, CFG)
    assert out[0][0].brand_id == "c"


def test_choices_without_a_brand_pass_through_unchanged():
    none = BrandChoice(kind="blocked", brand_id=None, shortlist=[], blocked=[], reason="x")
    assert spread_brands([none, picked(0.9)], {}, CFG)[0][0] is none
