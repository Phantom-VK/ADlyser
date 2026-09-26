"""The Groq transcript provider with a mocked client (no network, no audio)."""

from types import SimpleNamespace

import groq
import httpx
import pytest

from adlyser.cache import DiskCache
from adlyser.config import TranscribeConfig
from adlyser.errors import PerceptionError
from adlyser.perception.transcribe import RateLimited, make_chunks, transcribe_groq
from adlyser.schemas import SpeechSeg

CFG = TranscribeConfig(
    provider="groq", model="whisper-large-v3", chunk_s=600, chunk_min_s=30, max_chunk_mb=24
)


def raw(start, end, text, no_speech=0.0):
    return {"start": start, "end": end, "text": text, "no_speech_prob": no_speech}


class FakeGroq:
    """Answers each request with the scripted segments for that audio (or raises the scripted errors first)."""

    def __init__(self, by_audio, errors=()):
        self.by_audio, self.errors, self.calls = by_audio, list(errors), []
        self.audio = SimpleNamespace(transcriptions=SimpleNamespace(create=self.create))

    def create(self, **kw):
        name, data = kw["file"]
        self.calls.append({**kw, "file": (name, len(data))})
        if self.errors:
            raise self.errors.pop(0)
        return SimpleNamespace(model_dump=lambda: {"segments": self.by_audio[data]})


def limited(retry_after="7"):
    request = httpx.Request("POST", "https://api.groq.test/transcriptions")
    response = httpx.Response(429, headers={"retry-after": retry_after}, request=request)
    return groq.RateLimitError("rate limited", response=response, body=None)


def spans(*pairs):
    return [SpeechSeg(start=a, end=b) for a, b in pairs]


@pytest.fixture
def cache(tmp_path):
    return DiskCache(tmp_path)


def test_timestamps_are_shifted_by_the_chunk_offset(cache):
    client = FakeGroq({b"one": [raw(1, 3, "a")], b"two": [raw(2, 4, "b")]})
    speech = spans((0, 10), (600, 610))
    out = transcribe_groq([(0.0, b"one"), (600.0, b"two")], client, CFG, speech, cache)
    assert [(s.start, s.end, s.text) for s in out] == [(1, 3, "a"), (602, 604, "b")]


def test_the_request_is_greedy_bengali_verbose_json_with_the_configured_model(cache):
    client = FakeGroq({b"x": []})
    transcribe_groq([(0.0, b"x")], client, CFG, spans((0, 5)), cache)
    call = client.calls[0]
    assert (call["model"], call["temperature"], call["response_format"], call["language"]) == (
        "whisper-large-v3", 0, "verbose_json", "bn",
    )  # fmt: skip


def test_segments_that_do_not_overlap_vad_speech_are_dropped(cache):
    client = FakeGroq({b"x": [raw(1, 3, "kept"), raw(20, 22, "hallucinated"), raw(4.9, 5.05, "grazing")]})
    out = transcribe_groq([(0.0, b"x")], client, CFG, spans((0, 5)), cache)
    assert [s.text for s in out] == ["kept"]  # 0.1 s of overlap is below min_overlap_s


def test_the_vad_filter_works_in_video_time_not_chunk_time(cache):
    client = FakeGroq({b"x": [raw(1, 3, "in speech"), raw(50, 52, "in silence")]})
    out = transcribe_groq([(600.0, b"x")], client, CFG, spans((601, 604)), cache)
    assert [(s.start, s.text) for s in out] == [(601, "in speech")]


def test_segments_the_model_thinks_are_not_speech_are_dropped(cache):
    client = FakeGroq({b"x": [raw(1, 3, "sure", 0.1), raw(3, 5, "unsure", 0.5), raw(5, 7, "silence", 0.9)]})
    out = transcribe_groq([(0.0, b"x")], client, CFG, spans((0, 10)), cache)
    assert [s.text for s in out] == ["sure", "unsure"]  # 0.5 itself passes; only more than 0.5 is dropped


def test_empty_text_is_dropped(cache):
    out = transcribe_groq([(0.0, b"x")], FakeGroq({b"x": [raw(1, 3, "  ")]}), CFG, spans((0, 5)), cache)
    assert out == []


def test_the_same_audio_is_asked_once_then_read_from_the_cache(cache):
    client = FakeGroq({b"x": [raw(1, 3, "a")]})
    first = transcribe_groq([(0.0, b"x")], client, CFG, spans((0, 5)), cache)
    second = transcribe_groq([(0.0, b"x")], client, CFG, spans((0, 5)), cache)
    assert first == second and len(client.calls) == 1


def test_the_cache_is_keyed_by_the_audio_so_the_same_audio_at_another_offset_still_hits(cache):
    client = FakeGroq({b"x": [raw(1, 3, "a")]})
    transcribe_groq([(0.0, b"x")], client, CFG, spans((0, 5)), cache)
    later = transcribe_groq([(600.0, b"x")], client, CFG, spans((600, 605)), cache)
    assert [(s.start, s.end) for s in later] == [(601, 603)] and len(client.calls) == 1


def test_another_model_or_language_is_a_different_cache_entry(cache):
    client = FakeGroq({b"x": []})
    transcribe_groq([(0.0, b"x")], client, CFG, spans((0, 5)), cache)
    transcribe_groq(
        [(0.0, b"x")],
        client,
        CFG.model_copy(update={"model": "whisper-large-v3-turbo"}),
        spans((0, 5)),
        cache,
    )
    assert len(client.calls) == 2


def test_a_filter_change_does_not_need_new_requests(cache):
    client = FakeGroq({b"x": [raw(1, 3, "a", 0.6)]})
    assert transcribe_groq([(0.0, b"x")], client, CFG, spans((0, 5)), cache) == []
    looser = CFG.model_copy(update={"max_no_speech_prob": 0.7})
    assert len(transcribe_groq([(0.0, b"x")], client, looser, spans((0, 5)), cache)) == 1
    assert len(client.calls) == 1


def test_a_live_run_fails_fast_on_a_rate_limit_and_keeps_what_it_already_has(cache):
    client = FakeGroq({b"one": [raw(1, 3, "a")]}, errors=[])
    transcribe_groq([(0.0, b"one")], client, CFG, spans((0, 5)), cache)
    limited_client = FakeGroq({}, errors=[limited("42")])
    with pytest.raises(RateLimited) as caught:
        transcribe_groq(
            [(0.0, b"one"), (600.0, b"two")], limited_client, CFG, spans((0, 5), (600, 605)), cache
        )
    assert caught.value.retry_after_s == 42 and isinstance(caught.value, PerceptionError)
    assert len(limited_client.calls) == 1  # chunk one came from the cache, chunk two hit the limit


def test_precompute_waits_for_retry_after_and_retries(cache):
    client = FakeGroq({b"x": [raw(1, 3, "a")]}, errors=[limited("7")])
    slept = []
    out = transcribe_groq(
        [(0.0, b"x")], client, CFG, spans((0, 5)), cache, wait_on_limit=True, sleep=slept.append
    )
    assert slept == [7] and [s.text for s in out] == ["a"] and len(client.calls) == 2


def test_waiting_gives_up_after_the_configured_attempts(cache):
    client = FakeGroq({}, errors=[limited("1")] * 10)
    with pytest.raises(RateLimited):
        transcribe_groq(
            [(0.0, b"x")], client, CFG, spans((0, 5)), cache, wait_on_limit=True, sleep=lambda s: None
        )
    assert len(client.calls) == CFG.retry_attempts


def test_a_wait_is_capped_by_the_configured_maximum(cache):
    client = FakeGroq({b"x": []}, errors=[limited("99999")])
    slept = []
    transcribe_groq([(0.0, b"x")], client, CFG, spans((0, 5)), cache, wait_on_limit=True, sleep=slept.append)
    assert slept == [CFG.retry_max_wait_s]


def test_any_other_api_error_is_a_perception_error(cache):
    request = httpx.Request("POST", "https://api.groq.test/transcriptions")
    boom = groq.APIConnectionError(request=request)
    with pytest.raises(PerceptionError):
        transcribe_groq([(0.0, b"x")], FakeGroq({}, errors=[boom]), CFG, spans((0, 5)), cache)


# ---- chunking ---------------------------------------------------------------


def cutter(size=lambda length: 1000, log=None):
    def cut(start, length):
        if log is not None:
            log.append((start, length))
        return b"x" * size(length)

    return cut


def test_a_video_is_cut_into_chunk_windows_and_silent_windows_are_skipped():
    speech = spans((10, 20), (1300, 1310))  # windows 0-600 and 1200-1500 hold speech, 600-1200 does not
    log = []
    chunks = make_chunks(1500.0, speech, CFG, cutter(log=log))
    assert [(off, len(data)) for off, data in chunks] == [(0.0, 1000), (1200.0, 1000)]
    assert log == [(0.0, 600.0), (1200.0, 300.0)]  # the last window is what is left


def test_a_chunk_over_the_size_limit_is_halved():
    big = lambda length: 30_000_000 if length > 300 else 1000
    log = []
    chunks = make_chunks(600.0, spans((0, 600)), CFG, cutter(big, log))
    assert [off for off, _ in chunks] == [0.0, 300.0]
    assert log == [(0.0, 600.0), (0.0, 300.0), (300.0, 300.0)]


def test_halving_stops_at_the_minimum_chunk_length():
    tiny = CFG.model_copy(update={"max_chunk_mb": 0.0001})
    chunks = make_chunks(120.0, spans((0, 120)), tiny.model_copy(update={"chunk_s": 120}), cutter())
    assert len(chunks) == 4  # 120 -> 60 -> 30, then it stops


def test_the_shipped_defaults_keep_the_transcript_off_and_use_groq_large_v3():
    from adlyser.config import get_settings

    cfg = get_settings().transcribe
    assert cfg.enabled is False and cfg.provider == "groq" and cfg.model == "whisper-large-v3"
    assert TranscribeConfig().provider == "local" and TranscribeConfig().enabled is False
