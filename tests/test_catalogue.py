import json
from pathlib import Path

import pytest

from adlyser.agents.catalogue import normalise_catalogue, read_catalogue, slug, to_brands
from adlyser.errors import CatalogueError
from adlyser.schemas import NormalisedBrand, NormalisedCatalogue, SafetyTag

CATALOGUE = Path("catalogue/brands.json")


class FakeText:
    def __init__(self, reply):
        self.reply = reply
        self.messages = None

    async def chat_json(self, prompt, messages, model, fallback):
        self.messages = messages
        return self.reply if self.reply is not None else fallback


def nb(name, **kw):
    return NormalisedBrand(name=name, category="c", tagline="t", description="d", **kw)


def test_slug_is_a_stable_ascii_id():
    assert slug("Annapurna Rasoi") == "annapurna-rasoi"
    assert slug("  Sonar Tori  Pay! ") == "sonar-tori-pay"


def test_duplicate_names_get_unique_ids():
    brands = to_brands(NormalisedCatalogue(brands=[nb("Same"), nb("Same"), nb("Same")]))
    assert [b.id for b in brands] == ["same", "same-2", "same-3"]


def test_negative_tags_outside_the_taxonomy_are_rejected():
    with pytest.raises(ValueError):
        nb("X", negative_tags=["nudity"])


async def test_normaliser_keeps_the_raw_negative_text_and_the_tags():
    reply = NormalisedCatalogue(
        brands=[
            nb(
                "Annapurna Rasoi",
                negative_tags=[SafetyTag.DEATH_GRIEF, SafetyTag.MEDICAL_ILLNESS],
                negative_contexts_raw=["death", "funeral", "illness"],
            )
        ]
    )
    client = FakeText(reply)
    brands = await normalise_catalogue(client, "any format at all")
    assert brands[0].id == "annapurna-rasoi"
    assert brands[0].negative_contexts_raw == ["death", "funeral", "illness"]
    assert client.messages[1]["content"] == "any format at all"


async def test_a_failed_normaliser_call_gives_no_brands_so_every_slot_is_a_promo():
    assert await normalise_catalogue(FakeText(None), "raw") == []


def test_the_shipped_catalogue_has_eight_fictional_brands_and_a_food_brand_with_grief_contexts():
    raw = json.loads(CATALOGUE.read_text())
    assert len(raw) == 8
    food = next(b for b in raw if "meal" in b["sector"].lower() or "food" in b["sector"].lower())
    assert all(word in food["never_show_after"] for word in ("death", "funeral", "illness"))


def test_missing_or_empty_catalogue_raises(tmp_path):
    with pytest.raises(CatalogueError):
        read_catalogue(tmp_path / "nope.json")
    empty = tmp_path / "e.json"
    empty.write_text("  ")
    with pytest.raises(CatalogueError):
        read_catalogue(empty)
