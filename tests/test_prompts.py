from adlyser.llm.prompts import (
    BRAND_RERANK,  # noqa: F401  (imported so a rename breaks here)
    CATALOGUE_NORMALISER,
    SAFETY_SWEEP,
    STRETCH_ANALYST,
    TAG_DEFINITIONS,
)
from adlyser.schemas import SafetyTag


def test_every_safety_tag_has_one_definition_and_only_the_taxonomy_is_defined():
    assert set(TAG_DEFINITIONS) == {t.value for t in SafetyTag}
    assert all(len(d) > 10 for d in TAG_DEFINITIONS.values())


def test_the_three_tagging_prompts_carry_the_same_definitions():
    for prompt in (STRETCH_ANALYST, SAFETY_SWEEP, CATALOGUE_NORMALISER):
        for tag, definition in TAG_DEFINITIONS.items():
            assert f"{tag} = {definition}" in prompt


def test_the_definitions_say_what_a_tag_is_not():
    sexual = TAG_DEFINITIONS["sexual_content"]
    assert "NOT" in sexual and "hugging" in sexual
    assert "NOT" in TAG_DEFINITIONS["strong_argument"]


def test_the_stretch_prompt_defines_titles_and_the_sweep_rejects_negative_cues():
    assert "is_titles" in STRETCH_ANALYST and "previously on" in STRETCH_ANALYST.lower()
    assert "nothing is visible" in SAFETY_SWEEP or "states nothing" in SAFETY_SWEEP


# ---- transcript labelling ---------------------------------------------------

from adlyser.llm.prompts import TRANSCRIPT_NOTE, boundary_text, stretch_text
from adlyser.schemas import Candidate, Stretch

STRETCH = Stretch(index=0, start=0, end=60)
CAND = Candidate(t=30, silence_start=29, silence_end=31, kind="hard")


def test_a_transcript_is_labelled_noisy_and_hint_only_and_may_only_add_evidence():
    for note in (
        "noisy auto transcript",
        "words may be wrong",
        "only as a hint",
        "never remove",
        "never raise",
    ):
        assert note in TRANSCRIPT_NOTE.lower()
    assert "add evidence" in TRANSCRIPT_NOTE
    assert TRANSCRIPT_NOTE in stretch_text(STRETCH, [1.0], "some words")
    assert TRANSCRIPT_NOTE in boundary_text(CAND, "before", "after", "some words")


def test_without_a_transcript_the_prompt_text_is_unchanged_so_the_cache_stays_valid():
    assert TRANSCRIPT_NOTE not in stretch_text(STRETCH, [1.0], "unavailable")
    assert TRANSCRIPT_NOTE not in boundary_text(CAND, "before", "after", "unavailable")
    assert stretch_text(STRETCH, [1.0], "unavailable").endswith("Transcript: unavailable")
