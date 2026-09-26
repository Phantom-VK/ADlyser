"""BrandMatcher: hard block, embedding shortlist, one rerank call, hard block again."""

from typing import Protocol

import numpy as np

from adlyser.config import MatcherConfig
from adlyser.llm.client import LLMClient
from adlyser.llm.prompts import BRAND_RERANK, brand_lines, scene_line, with_schema
from adlyser.log import get_logger
from adlyser.rules.safety import blocking_tags, split_brands
from adlyser.schemas import Brand, BrandChoice, Rerank, Scene, ShortlistEntry

log = get_logger(__name__)


class Embeds(Protocol):
    """Anything that turns texts into unit-length vectors."""

    async def embed(self, texts: list[str]) -> np.ndarray:
        """Embed texts."""


def scene_query(scene: Scene) -> str:
    """Text that stands for a scene in the embedding space.

    :param scene: the scene the viewer just watched.
    :return: activity, activity tags and summary.
    """
    return f"{scene.dominant_activity}. {', '.join(scene.activity_tags)}. {scene.summary}"


def brand_text(brand: Brand) -> str:
    """Text that stands for a brand in the embedding space.

    :param brand: the brand.
    :return: category, description and target contexts.
    """
    return f"{brand.category}. {brand.description} Fits: {', '.join(brand.target_contexts)}"


async def match_brand(
    embedder: Embeds,
    client: LLMClient,
    brands: list[Brand],
    before: Scene,
    after: Scene,
    excluded: set[str],
    cfg: MatcherConfig,
) -> BrandChoice:
    """Choose the brand for one break, or a promo slot (``brand_id`` None).

    The hard block runs before the shortlist and again on the reranked result. Only brands that pass
    both are ever chosen, whatever the rerank says.

    :param embedder: the embedding function.
    :param client: the text client (rerank).
    :param brands: the whole catalogue.
    :param before: the scene before the break (what the viewer just watched).
    :param after: the scene after the break.
    :param excluded: brand ids already vetoed for this break.
    :param cfg: matcher settings.
    :return: the choice with its shortlist and blocked brands.
    """
    eligible, blocked = split_brands(brands, before, after)
    if before.unknown or after.unknown:
        return BrandChoice(brand_id=None, shortlist=[], blocked=blocked, reason="unknown scene: promo slot")
    pool = [b for b in eligible if b.id not in excluded]
    if not pool:
        return BrandChoice(
            brand_id=None, shortlist=[], blocked=blocked, reason="no eligible brand: promo slot"
        )

    vectors = await embedder.embed([scene_query(before), *(brand_text(b) for b in pool)])
    sims = vectors[1:] @ vectors[0]
    order = np.argsort(-sims, kind="stable")[: cfg.shortlist_k]
    shortlist = [
        ShortlistEntry(brand_id=pool[i].id, name=pool[i].name, similarity=float(sims[i])) for i in order
    ]
    by_id = {b.id: b for b in pool}

    text = f"Just watched: {scene_line(before)}\nComing next: {after.dominant_activity}. {after.summary}\n"
    text += f"Brands:\n{brand_lines([by_id[e.brand_id] for e in shortlist])}"
    messages = [
        {"role": "system", "content": with_schema(BRAND_RERANK, Rerank)},
        {"role": "user", "content": text},
    ]
    fallback = Rerank.model_validate(
        {
            "ranked": [
                {"brand_id": e.brand_id, "fit": max(0.0, e.similarity), "reason": "embedding similarity"}
                for e in shortlist
            ]
        }
    )
    ranked = (await client.chat_json("brand_rerank", messages, Rerank, fallback)).ranked

    known = {e.brand_id: e for e in shortlist}
    kept: list[ShortlistEntry] = []
    for r in ranked:
        entry = known.get(r.brand_id)
        if entry is None or blocking_tags(by_id[r.brand_id], before, after):
            continue  # unknown id or blocked after the rerank: never chosen
        kept.append(entry.model_copy(update={"fit": r.fit, "reason": r.reason}))
    kept = sorted(kept, key=lambda e: -(e.fit or 0.0))[: cfg.top_k]
    if kept and kept[0].fit is not None and kept[0].fit >= cfg.min_fit:
        return BrandChoice(brand_id=kept[0].brand_id, shortlist=kept, blocked=blocked, reason="best fit")
    return BrandChoice(
        brand_id=None, shortlist=kept, blocked=blocked, reason="no brand fits well: promo slot"
    )
