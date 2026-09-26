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
