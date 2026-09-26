from pathlib import Path
from types import SimpleNamespace

from adlyser.agents import boundary_judge, stretch_analyst
from adlyser.config import get_settings
from adlyser.errors import PerceptionError
from adlyser.schemas import BoundaryVerdict, Candidate, Stretch, StretchAnalysis, TranscriptSeg

BASE = get_settings()
SETTINGS = BASE.model_copy(update={"stretch": BASE.stretch.model_copy(update={"tool_rounds": 0})})
STRETCH = Stretch(index=0, start=0, end=120)
CAND = Candidate(t=300, silence_start=298, silence_end=303, kind="black")
GOOD = StretchAnalysis(
    summary="a family dinner",
    dominant_activity="eating",
    setting="home",
    mood="warm",
    safety_tags=[],
    confidence=0.9,
)


class FakeClient:
    """Records the messages it gets and returns the model's value (or the fallback)."""

    def __init__(self, reply=None):
        self.endpoint = SimpleNamespace(image_detail="low")
        self.reply = reply
        self.messages = None

    async def chat_json(self, prompt, messages, model, fallback):
        self.messages = messages
        return self.reply or fallback


def frames_ok(monkeypatch, module, n):
    monkeypatch.setattr(module, "extract_frames", lambda video, times, cfg, cache: [b"jpg"] * len(times))


def frames_fail(monkeypatch, module):
    def boom(*args):
        raise PerceptionError("no frame")

    monkeypatch.setattr(module, "extract_frames", boom)


def parts(client):
    return client.messages[1]["content"]


async def test_stretch_analyst_sends_frames_and_says_transcript_unavailable(monkeypatch):
    frames_ok(monkeypatch, stretch_analyst, 4)
    client = FakeClient(GOOD)
    out, trace = await stretch_analyst.analyse_stretch(
        client, Path("v.mp4"), Path("f"), STRETCH, [], 1000.0, SETTINGS
    )
    assert out == GOOD and trace == []
    images = [p for p in parts(client) if p["type"] == "image_url"]
    assert len(images) == 4  # 120 s at one frame per 30 s
    assert "Transcript: unavailable" in parts(client)[0]["text"]


async def test_stretch_analyst_passes_the_transcript_when_there_is_one(monkeypatch):
    frames_ok(monkeypatch, stretch_analyst, 4)
    client = FakeClient(GOOD)
    seg = TranscriptSeg(start=10, end=12, text="hello there")
    await stretch_analyst.analyse_stretch(client, Path("v.mp4"), Path("f"), STRETCH, [seg], 1000.0, SETTINGS)
    assert "hello there" in parts(client)[0]["text"]


async def test_stretch_analyst_returns_unknown_when_frames_fail(monkeypatch):
    frames_fail(monkeypatch, stretch_analyst)
    out, _ = await stretch_analyst.analyse_stretch(
        FakeClient(GOOD), Path("v.mp4"), Path("f"), STRETCH, [], 1000.0, SETTINGS
    )
    assert out == stretch_analyst.UNKNOWN and out.confidence == 0.0


async def test_stretch_analyst_returns_unknown_when_the_call_falls_back(monkeypatch):
    frames_ok(monkeypatch, stretch_analyst, 4)
    out, _ = await stretch_analyst.analyse_stretch(
        FakeClient(None), Path("v.mp4"), Path("f"), STRETCH, [], 1000.0, SETTINGS
    )
    assert out.confidence == 0.0


async def test_boundary_judge_gets_four_frames_silence_and_cut_type(monkeypatch):
    frames_ok(monkeypatch, boundary_judge, 4)
    client = FakeClient(BoundaryVerdict(is_scene_change=True, break_score=0.8, reason="closed"))
    out = await boundary_judge.judge_boundary(
        client, Path("v.mp4"), Path("f"), CAND, GOOD, GOOD, [], 1000.0, SETTINGS
    )
    assert out.is_scene_change
    assert len([p for p in parts(client) if p["type"] == "image_url"]) == 4
    text = parts(client)[0]["text"]
    assert "5.0 s" in text and "black" in text and "Transcript: unavailable" in text


async def test_boundary_judge_is_not_a_break_when_frames_fail(monkeypatch):
    frames_fail(monkeypatch, boundary_judge)
    out = await boundary_judge.judge_boundary(
        FakeClient(), Path("v.mp4"), Path("f"), CAND, GOOD, GOOD, [], 1000.0, SETTINGS
    )
    assert out == boundary_judge.NOT_A_BREAK


async def test_stretch_analyst_uses_the_tool_loop_when_rounds_are_configured(monkeypatch):
    frames_ok(monkeypatch, stretch_analyst, 4)
    seen = {}

    async def fake_run_agent(client, prompt, messages, tools, model, fallback, max_rounds):
        seen.update(messages=messages, tools=[t.name for t in tools], rounds=max_rounds)
        return GOOD, [{"tool": "look_closer"}]

    monkeypatch.setattr(stretch_analyst, "run_agent", fake_run_agent)
    settings = BASE.model_copy(update={"stretch": BASE.stretch.model_copy(update={"tool_rounds": 2})})
    out, trace = await stretch_analyst.analyse_stretch(
        FakeClient(), Path("v.mp4"), Path("f"), STRETCH, [], 1000.0, settings
    )
    assert out == GOOD and trace == [{"tool": "look_closer"}]
    assert seen["tools"] == ["look_closer"] and seen["rounds"] == 2
    assert "look_closer" in seen["messages"][0]["content"]
    assert "(0s to 120s)" in seen["messages"][1]["content"][0]["text"]
