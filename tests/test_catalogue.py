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


class PerRecordText:
    """Answers each record with a brand named after it; can fail one of them."""

    def __init__(self, fail_on=None):
        self.calls, self.fail_on = [], fail_on

    async def chat_json(self, prompt, messages, model, fallback):
        text = messages[1]["content"]
        self.calls.append(text)
        if self.fail_on and self.fail_on in text:
            return fallback
        name = json.loads(text)["brand"]
        return NormalisedCatalogue(brands=[nb(name)])


async def test_a_json_list_is_normalised_one_record_per_call():
    client = PerRecordText()
    raw = json.dumps([{"brand": "A"}, {"brand": "B"}, {"brand": "C"}])
    brands = await normalise_catalogue(client, raw)
    assert [b.id for b in brands] == ["a", "b", "c"] and len(client.calls) == 3


async def test_adding_a_brand_changes_only_that_records_call_text():
    first, second = PerRecordText(), PerRecordText()
    await normalise_catalogue(first, json.dumps([{"brand": "A"}, {"brand": "B"}]))
    await normalise_catalogue(second, json.dumps([{"brand": "A"}, {"brand": "B"}, {"brand": "Z"}]))
    assert set(first.calls) <= set(second.calls) and len(set(second.calls) - set(first.calls)) == 1


async def test_a_failed_record_omits_only_that_brand():
    client = PerRecordText(fail_on='"B"')
    brands = await normalise_catalogue(client, json.dumps([{"brand": "A"}, {"brand": "B"}, {"brand": "C"}]))
    assert [b.id for b in brands] == ["a", "c"]


async def test_csv_or_free_text_is_one_call_for_the_whole_text():
    client = FakeText(NormalisedCatalogue(brands=[nb("A"), nb("B")]))
    brands = await normalise_catalogue(client, "name,sector\nA,tea\nB,rides")
    assert [b.id for b in brands] == ["a", "b"]


async def test_a_failed_normaliser_call_gives_no_brands_so_every_slot_is_a_promo():
    assert await normalise_catalogue(FakeText(None), "raw") == []


def test_the_shipped_catalogue_has_twelve_brands_and_every_food_brand_avoids_grief_contexts():
    raw = json.loads(CATALOGUE.read_text())
    assert len(raw) == 12
    assert len({b["name"] for b in raw}) == 12
    food = [b for b in raw if b["category"] in ("Food", "Grocery")]
    assert food
    for brand in food:
        text = " ".join(brand["negative_contexts"]).lower()
        assert "funeral" in text and "illness" in text


def test_missing_or_empty_catalogue_raises(tmp_path):
    with pytest.raises(CatalogueError):
        read_catalogue(tmp_path / "nope.json")
    empty = tmp_path / "e.json"
    empty.write_text("  ")
    with pytest.raises(CatalogueError):
        read_catalogue(empty)
