"""Pydantic schemas that cross boundaries (LLM outputs, API, debug JSON)."""

from enum import StrEnum
from typing import Literal

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


class SpeechSeg(BaseModel, frozen=True):
    """A span of detected speech, in seconds."""

    start: float
    end: float


class Cut(BaseModel, frozen=True):
    """A visual transition: a hard shot cut, or the middle of a fade to black."""

    t: float
    kind: Literal["hard", "black"]


class Candidate(BaseModel, frozen=True):
    """A pause where an ad break could go: a cut point inside real silence."""

    t: float
    silence_start: float
    silence_end: float
    kind: Literal["hard", "black", "silence"]

    @property
    def silence_s(self) -> float:
        """Length of the silence containing this cut point, in seconds."""
        return self.silence_end - self.silence_start


class Funnel(BaseModel):
    """How many candidates survive each filter (for tuning on counts, not content)."""

    silences: int
    long_enough: int
    with_cut: int
    in_window: int
    after_spacing_cap: int


class CandidateResult(BaseModel):
    """Candidates in time order plus the funnel that produced them."""

    candidates: list[Candidate]
    funnel: Funnel


class Word(BaseModel, frozen=True):
    """One transcribed word with timing."""

    start: float
    end: float
    text: str


class TranscriptSeg(BaseModel, frozen=True):
    """One transcript segment. The transcript is context for the AI, never a rule input."""

    start: float
    end: float
    text: str
    words: list[Word] = Field(default_factory=list)


class Perception(BaseModel):
    """Everything measured from one video (deterministic, cached)."""

    video: str
    fingerprint: str
    duration_s: float
    speech: list[SpeechSeg]
    cuts: list[Cut]
    transcript: list[TranscriptSeg]
    timings_s: dict[str, float] = Field(default_factory=dict)


class Creative(BaseModel, frozen=True):
    """An ad creative that a break plays."""

    ad_id: str
    title: str
    duration_s: float
    media_url: str
    width: int = 960
    height: int = 540
    mime_type: str = "video/mp4"


class AdBreakSpec(BaseModel, frozen=True):
    """One ad break to put in the VMAP manifest."""

    break_id: str
    time_s: float
    creative: Creative
