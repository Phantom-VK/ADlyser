import pytest

from adlyser.config import get_settings
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


def test_default_config_has_transcript_disabled():
    assert get_settings().transcribe.enabled is False


def test_enabled_transcribes_once_then_reads_the_cache(settings, monkeypatch):
    calls = []

    def fake(wav, speech):
        calls.append(speech)
        return [TranscriptSeg(start=1, end=2, text="hello")]

    monkeypatch.setattr(measure_mod, "_transcribe_subprocess", fake)
    on = settings.model_copy(update={"transcribe": settings.transcribe.model_copy(update={"enabled": True})})
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
