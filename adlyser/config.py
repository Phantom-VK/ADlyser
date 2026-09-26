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

ROOT = Path(__file__).resolve().parent.parent


class Endpoint(BaseModel):
    """One OpenAI-compatible model endpoint (provider swap = change these three fields)."""

    provider: str
    base_url: str
    model: str
    image_detail: Literal["low", "high", "auto"] = "low"


class LlmConfig(BaseModel):
    """LLM endpoints and call limits."""

    concurrency: int = 8
    timeout_s: float = 120
    vision: Endpoint
    text: Endpoint


class TranscribeConfig(BaseModel):
    """faster-whisper settings. Never assume a GPU."""

    model_size: str = "small"
    device: str = "cpu"
    compute_type: str = "int8"
    language: str = "bn"
    beam_size: int = 1


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
    min_spacing_s: float
    max_candidates: int
    allow_long_silence_without_cut: bool
    long_silence_s: float


class PacingConfig(BaseModel):
    """Pacing constraints for the solver."""

    max_breaks_per_hour: int
    min_gap_s: float
    ad_duration_s: float
    max_ad_load_pct: float


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
    deepseek_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("DEEPSEEK_API_KEY")
    )
    gemini_api_key: SecretStr | None = Field(default=None, validation_alias=AliasChoices("GEMINI_API_KEY"))

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
