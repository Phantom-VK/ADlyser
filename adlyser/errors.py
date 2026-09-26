"""Exception hierarchy for ADlyser."""


class AdlyserError(Exception):
    """Base class for all ADlyser errors."""


class ConfigError(AdlyserError):
    """Configuration is missing or invalid."""


class PerceptionError(AdlyserError):
    """A measurement step (audio, VAD, cuts, transcript, frames) failed."""


class LlmError(AdlyserError):
    """An LLM call failed or returned unusable output."""


class CatalogueError(AdlyserError):
    """A brand catalogue could not be read or normalised."""


class EmitError(AdlyserError):
    """An output (VMAP, debug JSON, creative) could not be produced."""
