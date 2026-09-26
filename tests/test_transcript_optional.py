import pytest

from adlyser.config import get_settings
from adlyser.errors import PerceptionError
from adlyser.perception import measure as measure_mod
from adlyser.perception import transcribe as transcribe_mod
from adlyser.perception.transcribe import clip_timestamps
from adlyser.schemas import Perception, SpeechSeg, TranscriptSeg


@pytest.fixture
def settings(tmp_path):
    base = get_settings()
    return base.model_copy(update={"cache_dir": tmp_path})


def perception(speech=()):
    return Perception(
        video="v.mp4", fingerprint="f" * 8, duration_s=600, speech=list(speech), cuts=[], transcript=[]
    )


def test_disabled_never_loads_whisper_or_spawns_a_process(settings, monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("whisper must not be touched when transcribe.enabled is false")

    monkeypatch.setattr(transcribe_mod, "_load", boom)
    monkeypatch.setattr(measure_mod, "_transcribe_subprocess", boom)
    monkeypatch.setattr(measure_mod.subprocess, "run", boom)
    off = settings.model_copy(
        update={"transcribe": settings.transcribe.model_copy(update={"enabled": False})}
    )
    out = measure_mod.measure_transcript(perception([SpeechSeg(start=1, end=2)]), off)
    assert out.transcript == []
    assert "transcript" not in out.timings_s


def test_shipped_config_has_transcript_enabled():
    assert get_settings().transcribe.enabled is True


def test_enabled_transcribes_once_then_reads_the_cache(settings, monkeypatch):
    calls = []

    def fake(wav, speech):
        calls.append(speech)
        return [TranscriptSeg(start=1, end=2, text="hello")]

    monkeypatch.setattr(measure_mod, "_transcribe_subprocess", fake)
    local = {"enabled": True, "provider": "local"}
    on = settings.model_copy(update={"transcribe": settings.transcribe.model_copy(update=local)})
    p = perception([SpeechSeg(start=1, end=2)])
    first = measure_mod.measure_transcript(p, on)
    second = measure_mod.measure_transcript(p, on)
    assert [t.text for t in first.transcript] == ["hello"] == [t.text for t in second.transcript]
    assert len(calls) == 1


def test_clip_timestamps_merge_close_spans_and_keep_far_ones_apart():
    spans = [SpeechSeg(start=10, end=12), SpeechSeg(start=12.5, end=14), SpeechSeg(start=30, end=31)]
    assert clip_timestamps(spans, merge_gap_s=1.0) == [10, 14, 30, 31]


def test_clip_timestamps_of_no_speech_is_empty():
    assert clip_timestamps([], merge_gap_s=1.0) == []


def groq_on(settings):
    cfg = settings.transcribe.model_copy(update={"enabled": True, "provider": "groq"})
    return settings.model_copy(update={"transcribe": cfg})


def test_the_groq_provider_is_used_in_process_and_cached(settings, monkeypatch):
    calls = []

    def fake(wav, duration, cfg, speech, api_key, cache, wait_on_limit=False):
        calls.append((duration, wait_on_limit))
        return [TranscriptSeg(start=1, end=2, text="namaste")]

    def boom(*_a, **_k):
        raise AssertionError("the local whisper process must not start for the groq provider")

    monkeypatch.setattr(measure_mod, "transcribe_with_groq", fake)
    monkeypatch.setattr(measure_mod, "_transcribe_subprocess", boom)
    p = perception([SpeechSeg(start=1, end=2)])
    first = measure_mod.measure_transcript(p, groq_on(settings))
    second = measure_mod.measure_transcript(p, groq_on(settings))
    assert [t.text for t in first.transcript] == ["namaste"] == [t.text for t in second.transcript]
    assert calls == [(600, False)]  # a live run never waits out a rate limit


def test_precompute_can_ask_the_groq_provider_to_wait_out_a_rate_limit(settings, monkeypatch):
    seen = []

    def fake(wav, duration, cfg, speech, api_key, cache, wait_on_limit=False):
        seen.append(wait_on_limit)
        return []

    monkeypatch.setattr(measure_mod, "transcribe_with_groq", fake)
    measure_mod.measure_transcript(
        perception([SpeechSeg(start=1, end=2)]), groq_on(settings), wait_on_limit=True
    )
    assert seen == [True]


def test_a_rate_limited_live_run_raises_so_the_pipeline_carries_on_without_a_transcript(
    settings, monkeypatch
):
    def limited(*_a, **_k):
        raise transcribe_mod.RateLimited("rate limit", 30)

    monkeypatch.setattr(measure_mod, "transcribe_with_groq", limited)
    with pytest.raises(PerceptionError):
        measure_mod.measure_transcript(perception([SpeechSeg(start=1, end=2)]), groq_on(settings))
