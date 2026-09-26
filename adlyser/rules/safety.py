"""The hard safety block. Pure functions: no I/O, no LLM. A missing ad is never a violation."""

from collections.abc import Iterable

from adlyser.schemas import Blocked, Brand, SafetyTag, Scene, SweepRecord, SweepResult, TagEvidence

UNKNOWN_SCENE = "unknown_scene"


def blocking_tags(brand: Brand, before: Scene, after: Scene) -> list[str]:
    """Tags that block a brand: its negative tags intersected with the UNION of both scenes' tags.

    An unknown scene on either side blocks every brand.

    :param brand: the brand.
    :param before: the scene before the break.
    :param after: the scene after the break.
    :return: sorted blocking tags; empty means eligible.
    """
    if before.unknown or after.unknown:
        return [UNKNOWN_SCENE]
    seen = set(before.safety_tags) | set(after.safety_tags)
    return sorted(t.value for t in set(brand.negative_tags) & seen)


def split_brands(brands: list[Brand], before: Scene, after: Scene) -> tuple[list[Brand], list[Blocked]]:
    """Split brands into the eligible ones and the blocked ones (with the blocking tags).

    :param brands: the catalogue.
    :param before: the scene before the break.
    :param after: the scene after the break.
    :return: ``(eligible, blocked)``, both in catalogue order.
    """
    eligible: list[Brand] = []
    blocked: list[Blocked] = []
    for b in brands:
        tags = blocking_tags(b, before, after)
        if tags:
            blocked.append(Blocked(brand_id=b.id, tags=tags))
        else:
            eligible.append(b)
    return eligible, blocked


def add_sweep_tags(scene: Scene, found: Iterable[SafetyTag]) -> Scene:
    """Union sweep-found tags into a scene. Tags are only ever added, and ``unknown`` is unchanged.

    :param scene: the scene.
    :param found: tags the safety sweep saw.
    :return: a copy of the scene with the union of tags.
    """
    return scene.model_copy(update={"safety_tags": sorted(set(scene.safety_tags) | set(found))})


def apply_sweep(scene: Scene, sweep: SweepRecord) -> Scene:
    """Fold a safety sweep into a scene.

    Seen and unsure tags are both added (unsure counts as present; tags are never removed). A sweep that
    succeeded, covered the whole scene at the configured interval AND lost no tag to a bad citation clears
    ``unknown`` (dense evidence replaces sparse). Otherwise ``unknown`` stays as it was.

    :param scene: the scene.
    :param sweep: the sweep record for that scene.
    :return: the updated scene.
    """
    out = add_sweep_tags(scene, [*sweep.safety_tags, *sweep.unsure_tags])
    if sweep.ok and sweep.full_coverage and not sweep.dropped:
        out = out.model_copy(update={"unknown": False})
    return out


def _cited(item: TagEvidence, n_frames: int) -> bool:
    """A tag counts only if it cites at least one frame and every cited frame exists (numbered from 1)."""
    return bool(item.frames) and all(1 <= i <= n_frames for i in item.frames)


def validate_sweep(
    result: SweepResult, n_frames: int
) -> tuple[list[TagEvidence], list[TagEvidence], list[TagEvidence]]:
    """Keep only sweep tags that cite real frames.

    A tag with no frame citation, or with a frame number outside ``1..n_frames``, is dropped. A tag listed
    as both seen and unsure is kept as seen.

    :param result: the raw sweep output.
    :param n_frames: how many frames the sweep was given.
    :return: ``(seen, unsure, dropped)`` evidence lists.
    """
    seen = [e for e in result.safety_tags if _cited(e, n_frames)]
    seen_tags = {e.tag for e in seen}
    unsure = [e for e in result.unsure_tags if _cited(e, n_frames) and e.tag not in seen_tags]
    dropped = [e for e in [*result.safety_tags, *result.unsure_tags] if not _cited(e, n_frames)]
    return seen, unsure, dropped


def blocking_scenes(brands: list[Brand], before: Scene, after: Scene) -> list[int]:
    """Indices of the scenes around a break that block EVERY brand on their own (or are unknown).

    :param brands: the catalogue.
    :param before: the scene before the break.
    :param after: the scene after the break.
    :return: the culprit scene indices (may be empty when only the union of both scenes blocks).
    """

    def blocks_all(scene: Scene) -> bool:
        seen = set(scene.safety_tags)
        return scene.unknown or (bool(brands) and all(set(b.negative_tags) & seen for b in brands))

    return [s.index for s in (before, after) if blocks_all(s)]
