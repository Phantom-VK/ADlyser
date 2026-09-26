"""The hard safety block. Pure functions: no I/O, no LLM. A missing ad is never a violation."""

from collections.abc import Iterable

from adlyser.schemas import Blocked, Brand, SafetyTag, Scene, SweepResult

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


def apply_sweep(scene: Scene, sweep: SweepResult, min_confidence: float) -> Scene:
    """Fold a safety sweep into a scene: add its tags, and make the scene unknown if the sweep was unsure.

    A failed sweep has confidence 0, so the scene becomes unknown and blocks every brand.

    :param scene: the scene.
    :param sweep: the sweep result for that scene.
    :param min_confidence: below this the sweep cannot vouch for the scene.
    :return: the updated scene (tags only added).
    """
    out = add_sweep_tags(scene, sweep.safety_tags)
    return out.model_copy(update={"unknown": scene.unknown or sweep.confidence < min_confidence})
