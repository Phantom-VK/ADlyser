"""Pydantic schemas that cross boundaries (LLM outputs, API, debug JSON)."""

from enum import StrEnum
from typing import Any, Literal

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


class NormalisedBrand(BaseModel):
    """CatalogueNormaliser output for one brand (the id is assigned by code)."""

    name: str
    category: str
    tagline: str
    description: str
    target_contexts: list[str] = Field(default_factory=list)
    negative_tags: list[SafetyTag] = Field(default_factory=list)
    negative_contexts_raw: list[str] = Field(default_factory=list)


class NormalisedCatalogue(BaseModel):
    """CatalogueNormaliser output: every brand found in the input."""

    brands: list[NormalisedBrand]


class Brand(NormalisedBrand, frozen=True):
    """A brand ready for matching. ``negative_tags`` drive the hard block; the raw text is kept for review."""

    id: str


class Blocked(BaseModel, frozen=True):
    """A brand that may not play at this break, and why (taxonomy tags, or ``unknown_scene``)."""

    brand_id: str
    tags: list[str]


class ShortlistEntry(BaseModel):
    """One shortlisted brand: embedding similarity, then the rerank fit and reason."""

    brand_id: str
    name: str
    similarity: float
    fit: float | None = None
    reason: str = ""


class BrandChoice(BaseModel):
    """BrandMatcher result for one break: the chosen brand (None = promo slot) and the evidence."""

    brand_id: str | None
    shortlist: list[ShortlistEntry]
    blocked: list[Blocked]
    reason: str


class RerankEntry(BaseModel):
    """One brand's fit for a scene, from the BrandMatcher rerank."""

    brand_id: str
    fit: float = Field(ge=0, le=1)
    reason: str


class Rerank(BaseModel):
    """BrandMatcher rerank output: best fit first."""

    ranked: list[RerankEntry]


class SweepResult(BaseModel):
    """Safety sweep output: every safety tag seen across the frames of one scene."""

    safety_tags: list[SafetyTag] = Field(default_factory=list)
    evidence: str
    confidence: float = Field(ge=0, le=1)


class ReviewVerdict(BaseModel):
    """BreakReviewer output: approve the break with its brand, or veto it and say what to try next."""

    decision: Literal["approve", "veto"]
    reason: str
    retry: Literal["next_brand", "next_candidate", "promo"] | None = None


class BoundaryVerdict(BaseModel):
    """BoundaryJudge output: is this candidate pause a real scene change, and how good a break?"""

    is_scene_change: bool
    break_score: float = Field(ge=0, le=1)
    reason: str


class Stretch(BaseModel, frozen=True):
    """The video between two consecutive candidate pauses (or the video edge)."""

    index: int
    start: float
    end: float


class Scene(BaseModel):
    """Stretches merged across non-scene-change candidates. Tags are the union over its stretches."""

    index: int
    start: float
    end: float
    stretch_indices: list[int]
    summary: str
    dominant_activity: str
    activity_tags: list[str]
    safety_tags: list[SafetyTag]
    unknown: bool


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


class BreakOption(BaseModel, frozen=True):
    """A confirmed scene change the pacing solver may turn into a break."""

    candidate: Candidate
    break_score: float


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


class BreakPlan(BaseModel):
    """One planned break as it moves through matching, sweep and review."""

    candidate: Candidate
    break_score: float
    before: int
    after: int
    status: Literal[
        "needs_brand", "needs_review", "approved", "promo", "dropped", "retry_brand", "retry_candidate"
    ]
    choice: BrandChoice | None = None
    review: ReviewVerdict | None = None
    review_trace: list[dict[str, Any]] = Field(default_factory=list)
    vetoed_brands: list[str] = Field(default_factory=list)
    history: list[str] = Field(default_factory=list)
    reason: str = ""


class CandidateRecord(BaseModel):
    """debug.json: what happened to one candidate pause, and why."""

    t: float
    silence_s: float
    kind: str
    is_scene_change: bool
    break_score: float
    boundary_reason: str
    status: Literal["not_scene_change", "below_min_score", "pacing_rejected", "selected", "vetoed"]
    reason: str


class StretchRecord(BaseModel):
    """debug.json: one stretch, its analysis and the tool calls the analyst made."""

    stretch: Stretch
    analysis: StretchAnalysis
    tool_trace: list[dict[str, Any]]


class SceneRecord(BaseModel):
    """debug.json: a scene and the tags the safety sweep added to it."""

    scene: Scene
    sweep_added: list[SafetyTag]
    sweep_evidence: str = ""
    sweep_confidence: float | None = None


class BlockedRecord(BaseModel):
    """debug.json: a blocked brand with the tag that blocked it."""

    brand_id: str
    name: str
    tags: list[str]


class BreakRecord(BaseModel):
    """debug.json: a break in the manifest (or dropped) with the whole decision trail."""

    break_id: str | None
    t: float
    break_score: float
    outcome: Literal["brand", "promo", "dropped"]
    brand_id: str | None
    brand_name: str | None
    before_scene: int
    after_scene: int
    shortlist: list[ShortlistEntry]
    blocked: list[BlockedRecord]
    sweep_added: dict[str, list[SafetyTag]]
    review: ReviewVerdict | None
    review_trace: list[dict[str, Any]]
    history: list[str]
    reason: str


class DebugReport(BaseModel):
    """debug.json: every decision with its evidence."""

    video: str
    duration_s: float
    funnel: Funnel
    candidates: list[CandidateRecord]
    stretches: list[StretchRecord]
    scenes: list[SceneRecord]
    breaks: list[BreakRecord]
    brands: list[Brand]
    llm_stats: dict[str, dict[str, int]]
    loops: int
    wall_s: float
