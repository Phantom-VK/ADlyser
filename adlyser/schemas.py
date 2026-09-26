"""Pydantic schemas that cross boundaries (LLM outputs, API, debug JSON)."""

from enum import StrEnum

from pydantic import BaseModel, Field


class SafetyTag(StrEnum):
    """Fixed brand-safety taxonomy (GARM-aligned). The hard block is a set intersection over this."""

    DEATH_GRIEF = "death_grief"
    FUNERAL_RITUAL = "funeral_ritual"
    VIOLENCE = "violence"
    CRIME_WEAPONS = "crime_weapons"
    ACCIDENT_INJURY = "accident_injury"
    MEDICAL_ILLNESS = "medical_illness"
    ALCOHOL = "alcohol"
    TOBACCO_DRUGS = "tobacco_drugs"
    SEXUAL_CONTENT = "sexual_content"
    ABUSE_HARASSMENT = "abuse_harassment"
    RELIGION_SENSITIVE = "religion_sensitive"
    DISASTER = "disaster"
    HUNGER_POVERTY = "hunger_poverty"
    STRONG_ARGUMENT = "strong_argument"


class StretchAnalysis(BaseModel):
    """StretchAnalyst output: what happens in the video between two candidate pauses."""

    summary: str
    dominant_activity: str
    activity_tags: list[str] = Field(default_factory=list)
    setting: str
    mood: str
    safety_tags: list[SafetyTag] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)


class BoundaryVerdict(BaseModel):
    """BoundaryJudge output: is this candidate pause a real scene change, and how good a break?"""

    is_scene_change: bool
    break_score: float = Field(ge=0, le=1)
    reason: str
