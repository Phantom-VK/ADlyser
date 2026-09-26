"""CatalogueNormaliser: any catalogue format -> brands in the fixed schema (one text-model call)."""

import asyncio
import json
import re
from pathlib import Path

from adlyser.errors import CatalogueError
from adlyser.llm.client import LLMClient
from adlyser.llm.prompts import CATALOGUE_NORMALISER, with_schema
from adlyser.log import get_logger
from adlyser.schemas import Brand, NormalisedCatalogue, SafetyTag

log = get_logger(__name__)
EMPTY = NormalisedCatalogue(brands=[])


def slug(name: str) -> str:
    """Make a stable id from a brand name.

    :param name: the brand name.
    :return: a lowercase ascii id.
    """
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def to_brands(catalogue: NormalisedCatalogue, default_negative_tags: list[SafetyTag]) -> list[Brand]:
    """Give each brand a unique id and the default negative tags every brand must honour.

    A brand that states no negatives of its own would otherwise pass the hard block at every break, so the
    floor is unioned into its tags (and the brand is logged).

    :param catalogue: normalised brands.
    :param default_negative_tags: tags added to every brand's negative tags.
    :return: brands with unique ids, in input order.
    """
    brands: list[Brand] = []
    used: set[str] = set()
    for nb in catalogue.brands:
        base = slug(nb.name) or "brand"
        bid, n = base, 2
        while bid in used:
            bid, n = f"{base}-{n}", n + 1
        used.add(bid)
        if not nb.negative_tags:
            log.warning("brand_without_negatives", extra={"brand": nb.name})
        tags = sorted({*nb.negative_tags, *default_negative_tags})
        brands.append(Brand(id=bid, **{**nb.model_dump(), "negative_tags": tags}))
    return brands


async def _normalise_text(client: LLMClient, text: str) -> NormalisedCatalogue:
    """One normaliser call over some catalogue text (cached by content)."""
    messages = [
        {"role": "system", "content": with_schema(CATALOGUE_NORMALISER, NormalisedCatalogue)},
        {"role": "user", "content": text},
    ]
    return await client.chat_json("catalogue_normaliser", messages, NormalisedCatalogue, EMPTY)


async def normalise_catalogue(
    client: LLMClient, raw: str, default_negative_tags: list[SafetyTag]
) -> list[Brand]:
    """Normalise raw catalogue text. If a call fails its brands are omitted, so they are never placed.

    A JSON list is normalised one record per call, in parallel, each cached by its own content: adding a
    brand costs one small call. Any other format (CSV, free text) goes through one call for the whole text.

    :param client: the text client.
    :param raw: the catalogue file content, in any format.
    :param default_negative_tags: tags every brand gets on top of its own.
    :return: the normalised brands.
    """
    try:
        records = json.loads(raw)
    except json.JSONDecodeError:
        records = None
    if isinstance(records, list) and records and all(isinstance(r, dict) for r in records):
        parts = await asyncio.gather(
            *[_normalise_text(client, json.dumps(r, ensure_ascii=False, sort_keys=True)) for r in records]
        )
        return to_brands(
            NormalisedCatalogue(brands=[b for part in parts for b in part.brands]), default_negative_tags
        )
    return to_brands(await _normalise_text(client, raw), default_negative_tags)


def read_catalogue(path: Path) -> str:
    """Read the raw catalogue file.

    :param path: catalogue file.
    :return: its text.
    :raises CatalogueError: if it cannot be read or is empty.
    """
    try:
        raw = path.read_text()
    except OSError as exc:
        raise CatalogueError(f"cannot read catalogue {path}: {exc}") from exc
    if not raw.strip():
        raise CatalogueError(f"catalogue {path} is empty")
    return raw
