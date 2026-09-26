"""Settings loaded from config.yaml, overridable by env vars and .env."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, BaseModel, Field, SecretStr
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

from adlyser.schemas import SafetyTag

ROOT = Path(__file__).resolve().parent.parent


class Endpoint(BaseModel):
    """One OpenAI-compatible model endpoint (provider swap = change these three fields)."""

    provider: str
    base_url: str
    model: str
    image_detail: Literal["low", "high", "auto"] = "low"


class LlmConfig(BaseModel):
    """LLM endpoints and call limits."""

    temperature: float
    concurrency: int = 8
    timeout_s: float = 120
    vision: Endpoint
    text: Endpoint


class TranscribeConfig(BaseModel):
    """Transcript settings. Optional and off by default; never assume a GPU or a network."""

    enabled: bool = False
    provider: Literal["local", "groq"] = "local"
    # local (faster-whisper)
    clip_merge_gap_s: float = 1.0
    model_size: str = "small"
    device: str = "cpu"
    compute_type: str = "int8"
    language: str = "bn"
    beam_size: int = 1
    # groq (hosted whisper)
    model: str = "whisper-large-v3"
    chunk_s: float = 600  # audio is sent in windows of about this length
    chunk_min_s: float = 30  # a window over the size limit is halved, but never below this
    max_chunk_mb: float = 24  # the API takes 25 MB per file
    max_no_speech_prob: float = 0.5  # a segment the model itself thinks is not speech is dropped
    min_overlap_s: float = 0.2  # a segment needs this much VAD speech under it, or it is a hallucination
    request_timeout_s: float = 120
    retry_attempts: int = 3  # tries when waiting out a rate limit (precompute only)
    retry_max_wait_s: float = 3900  # never wait longer than this for one retry-after
    retry_default_wait_s: float = 60  # when the 429 carries no retry-after


class VadConfig(BaseModel):
    """Silero VAD settings."""

    threshold: float
    min_speech_ms: int
    min_silence_ms: int
    speech_pad_ms: int


class CutsConfig(BaseModel):
    """Shot-cut and black-frame detection settings."""

    adaptive_threshold: float
    min_scene_len_frames: int
    black_min_duration_s: float
    black_pixel_threshold: float
    black_scale_width: int


class CandidateConfig(BaseModel):
    """Candidate-pause rules (see rules/candidates.py)."""

    min_silence_s: float
    speech_guard_s: float
    skip_start_s: float
    skip_end_s: float
    skip_start_fraction: float
    skip_end_fraction: float
    min_spacing_s: float
    max_candidates: int
    allow_long_silence_without_cut: bool
    long_silence_s: float
    titles_scan_fraction: float  # a titles stretch counts if it starts in this fraction of the video ...
    titles_max_s: float  # ... and at most this many seconds from the start (or the end)


class PacingConfig(BaseModel):
    """Pacing constraints for the solver."""

    max_breaks_per_hour: int
    min_gap_s: float
    ad_duration_s: float
    max_ad_load_pct: float
    min_duration_for_break_s: float
    min_break_score: float


class FramesConfig(BaseModel):
    """How frames are pulled from the video for the vision model."""

    width: int
    jpeg_quality: int


class StretchConfig(BaseModel):
    """How many frames represent one stretch between candidates."""

    frame_interval_s: float
    min_frames: int
    max_frames: int
    tool_rounds: int


class BoundaryConfig(BaseModel):
    """Where the BoundaryJudge looks around a cut."""

    frame_offsets_s: list[float]


class ScenesConfig(BaseModel):
    """Scene-building settings."""

    min_confidence: float


class CatalogueConfig(BaseModel):
    """Where the raw brand catalogue lives, the brands added from the UI, and the merged file a run reads."""

    path: Path
    added_path: Path
    working_path: Path
    default_negative_tags: list[SafetyTag]


class ApiConfig(BaseModel):
    """Web API settings: uploads, thumbnails and progress streams."""

    uploads_dir: Path
    upload_max_mb: int
    upload_suffixes: list[str]
    frame_step_s: float
    large_frame_width: int
    events_poll_s: float


class MatcherConfig(BaseModel):
    """BrandMatcher settings."""

    embed_model: str
    shortlist_k: int
    top_k: int
    min_fit: float
    max_per_brand: int  # times one brand may run in an episode while another good fit exists


class ReviewerConfig(BaseModel):
    """BreakReviewer settings (safety sweep and veto loops)."""

    sweep_interval_s: float
    sweep_max_frames: int
    tool_rounds: int
    speech_window_s: float
    max_loops: int


class CreativesConfig(BaseModel):
    """Generated slate creatives (10 s title cards made with ffmpeg)."""

    duration_s: float
    width: int
    height: int
    font: str
    promo_title: str
    promo_subtitle: str


class Settings(BaseSettings):
    """Top-level settings."""

    model_config = SettingsConfigDict(
        yaml_file=ROOT / "config.yaml",
        env_file=ROOT / ".env",
        env_prefix="ADLYSER_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    videos_dir: Path
    data_dir: Path
    cache_dir: Path
    llm: LlmConfig
    transcribe: TranscribeConfig
    vad: VadConfig
    cuts: CutsConfig
    candidates: CandidateConfig
    pacing: PacingConfig
    frames: FramesConfig
    stretch: StretchConfig
    boundary: BoundaryConfig
    scenes: ScenesConfig
    catalogue: CatalogueConfig
    api: ApiConfig
    matcher: MatcherConfig
    reviewer: ReviewerConfig
    creatives: CreativesConfig
    deepseek_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("DEEPSEEK_API_KEY")
    )
    gemini_api_key: SecretStr | None = Field(default=None, validation_alias=AliasChoices("GEMINI_API_KEY"))
    groq_api_key: SecretStr | None = Field(default=None, validation_alias=AliasChoices("GROQ_API_KEY"))

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Priority: init > env > .env > config.yaml.

        :return: the ordered settings sources.
        """
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            YamlConfigSettingsSource(settings_cls),
        )

    def api_key(self, provider: str) -> str:
        """Return the API key for a provider, or an empty string if it needs none.

        :param provider: e.g. ``deepseek`` or ``gemini``.
        :return: the key value (never log it).
        """
        secret: SecretStr | None = getattr(self, f"{provider}_api_key", None)
        return secret.get_secret_value() if secret else ""


@lru_cache
def get_settings() -> Settings:
    """Load settings once.

    :return: the cached Settings instance.
    """
    return Settings()
