import json
from pathlib import Path

import pytest

from adlyser.agents.catalogue import normalise_catalogue, read_catalogue, slug, to_brands
from adlyser.config import get_settings
from adlyser.errors import CatalogueError
from adlyser.llm.prompts import CATALOGUE_NORMALISER
from adlyser.schemas import NormalisedBrand, NormalisedCatalogue, SafetyTag

CATALOGUE = Path("catalogue/brands.json")
NO_FLOOR: list[SafetyTag] = []
FLOOR = [SafetyTag.DEATH_GRIEF, SafetyTag.FUNERAL_RITUAL]


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
    brands = to_brands(NormalisedCatalogue(brands=[nb("Same"), nb("Same"), nb("Same")]), NO_FLOOR)
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
    brands = await normalise_catalogue(client, "any format at all", NO_FLOOR)
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
    brands = await normalise_catalogue(client, raw, NO_FLOOR)
    assert [b.id for b in brands] == ["a", "b", "c"] and len(client.calls) == 3


async def test_adding_a_brand_changes_only_that_records_call_text():
    first, second = PerRecordText(), PerRecordText()
    await normalise_catalogue(first, json.dumps([{"brand": "A"}, {"brand": "B"}]), NO_FLOOR)
    await normalise_catalogue(second, json.dumps([{"brand": "A"}, {"brand": "B"}, {"brand": "Z"}]), NO_FLOOR)
    assert set(first.calls) <= set(second.calls) and len(set(second.calls) - set(first.calls)) == 1


async def test_a_failed_record_omits_only_that_brand():
    client = PerRecordText(fail_on='"B"')
    brands = await normalise_catalogue(
        client, json.dumps([{"brand": "A"}, {"brand": "B"}, {"brand": "C"}]), NO_FLOOR
    )
    assert [b.id for b in brands] == ["a", "c"]


async def test_csv_or_free_text_is_one_call_for_the_whole_text():
    client = FakeText(NormalisedCatalogue(brands=[nb("A"), nb("B")]))
    brands = await normalise_catalogue(client, "name,sector\nA,tea\nB,rides", NO_FLOOR)
    assert [b.id for b in brands] == ["a", "b"]


async def test_a_failed_normaliser_call_gives_no_brands_so_every_slot_is_a_promo():
    assert await normalise_catalogue(FakeText(None), "raw", NO_FLOOR) == []


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


# ---- default negative tags: the floor every brand gets ------------------------------------------


def test_the_floor_is_added_to_every_brand_and_keeps_the_brands_own_tags():
    brands = to_brands(
        NormalisedCatalogue(
            brands=[nb("Own", negative_tags=[SafetyTag.VIOLENCE, SafetyTag.DEATH_GRIEF]), nb("Bare")]
        ),
        FLOOR,
    )
    assert brands[0].negative_tags == [SafetyTag.DEATH_GRIEF, SafetyTag.FUNERAL_RITUAL, SafetyTag.VIOLENCE]
    assert brands[1].negative_tags == [SafetyTag.DEATH_GRIEF, SafetyTag.FUNERAL_RITUAL]


def test_a_brand_with_no_negatives_of_its_own_is_logged_as_a_wildcard(caplog):
    with caplog.at_level("WARNING"):
        to_brands(
            NormalisedCatalogue(brands=[nb("Bare"), nb("Own", negative_tags=[SafetyTag.VIOLENCE])]), FLOOR
        )
    messages = [r.getMessage() + str(getattr(r, "brand", "")) for r in caplog.records]
    assert any("Bare" in m for m in messages) and not any("Own" in m for m in messages)


def test_an_empty_floor_changes_nothing():
    assert to_brands(NormalisedCatalogue(brands=[nb("Bare")]), NO_FLOOR)[0].negative_tags == []


async def test_the_floor_reaches_brands_from_the_normaliser_in_both_paths():
    client = FakeText(NormalisedCatalogue(brands=[nb("Bare")]))
    assert (await normalise_catalogue(client, "free text", FLOOR))[0].negative_tags == FLOOR
    per_record = await normalise_catalogue(client, json.dumps([{"brand": "Bare"}]), FLOOR)
    assert per_record[0].negative_tags == FLOOR


def test_the_shipped_floor_is_grief_funeral_and_sexual_content():
    assert get_settings().catalogue.default_negative_tags == [
        SafetyTag.DEATH_GRIEF,
        SafetyTag.FUNERAL_RITUAL,
        SafetyTag.SEXUAL_CONTENT,
    ]


# ---- the normaliser maps only what a phrase names ------------------------------------------------


def test_the_normaliser_prompt_maps_each_phrase_to_the_tags_it_names_and_adds_nothing_adjacent():
    assert "inclusive" not in CATALOGUE_NORMALISER.lower()
    assert "directly names" in CATALOGUE_NORMALISER and "adjacent" in CATALOGUE_NORMALISER
