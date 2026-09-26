from pathlib import Path
from types import SimpleNamespace

from adlyser.agents import reviewer
from adlyser.config import get_settings
from adlyser.errors import PerceptionError
from adlyser.schemas import Brand, Candidate, ReviewVerdict, SafetyTag, Scene, SpeechSeg, SweepResult

SETTINGS = get_settings()
SCENE = Scene(index=0, start=0, end=95, stretch_indices=[0], summary="a quiet street", dominant_activity="walking",
              activity_tags=[], safety_tags=[SafetyTag.ALCOHOL], unknown=False)  # fmt: skip
CAND = Candidate(t=100, silence_start=90, silence_end=110, kind="hard")
FOOD = Brand(id="food", name="Food", category="meals", tagline="t", description="ready meals",
             negative_tags=[SafetyTag.DEATH_GRIEF], negative_contexts_raw=["death", "funeral", "illness"])  # fmt: skip


class FakeClient:
    def __init__(self, reply=None):
        self.endpoint = SimpleNamespace(image_detail="low")
        self.reply, self.messages = reply, None

    async def chat_json(self, prompt, messages, model, fallback):
        self.messages = messages
        return self.reply or fallback


def frames_ok(monkeypatch):
    monkeypatch.setattr(reviewer, "extract_frames", lambda video, times, cfg, cache: [b"j"] * len(times))


async def test_sweep_sends_frames_across_the_whole_scene_and_the_current_tags(monkeypatch):
    frames_ok(monkeypatch)
    client = FakeClient(SweepResult(safety_tags=[SafetyTag.DEATH_GRIEF], evidence="funeral", confidence=0.8))
    out = await reviewer.sweep_scene(client, Path("v.mp4"), Path("f"), SCENE, SETTINGS)
    assert out.safety_tags == [SafetyTag.DEATH_GRIEF]
    content = client.messages[1]["content"]
    assert sum(p["type"] == "image_url" for p in content) == 10  # 95 s at one frame per 10 s
    assert "Current tags: alcohol" in content[0]["text"]


async def test_sweep_that_cannot_get_frames_has_zero_confidence(monkeypatch):
    def boom(*args):
        raise PerceptionError("no frame")

    monkeypatch.setattr(reviewer, "extract_frames", boom)
    out = await reviewer.sweep_scene(FakeClient(), Path("v.mp4"), Path("f"), SCENE, SETTINGS)
    assert out == reviewer.SWEEP_FAILED and out.confidence == 0.0


async def test_sweep_whose_call_fails_has_zero_confidence(monkeypatch):
    frames_ok(monkeypatch)
    out = await reviewer.sweep_scene(FakeClient(None), Path("v.mp4"), Path("f"), SCENE, SETTINGS)
    assert out.confidence == 0.0


async def test_review_gets_the_brand_raw_negative_text_the_speech_map_and_two_tools(monkeypatch):
    frames_ok(monkeypatch)
    seen = {}

    async def fake_run_agent(client, prompt, messages, tools, model, fallback, max_rounds):
        seen.update(text=messages[1]["content"][0]["text"], tools=[t.name for t in tools], rounds=max_rounds)
        return ReviewVerdict(decision="approve", reason="ok"), []

    monkeypatch.setattr(reviewer, "run_agent", fake_run_agent)
    verdict, _ = await reviewer.review_break(
        FakeClient(),
        Path("v.mp4"),
        Path("f"),
        [SpeechSeg(start=95, end=98)],
        1000.0,
        CAND,
        SCENE,
        SCENE,
        FOOD,
        SETTINGS,
    )
    assert verdict.decision == "approve"
    assert "death; funeral; illness" in seen["text"] and "Speech between" in seen["text"]
    assert seen["tools"] == ["look_closer", "speech_map"] and seen["rounds"] == SETTINGS.reviewer.tool_rounds


async def test_a_review_that_cannot_get_frames_vetoes_to_a_promo(monkeypatch):
    def boom(*args):
        raise PerceptionError("no frame")

    monkeypatch.setattr(reviewer, "extract_frames", boom)
    verdict, trace = await reviewer.review_break(
        FakeClient(), Path("v.mp4"), Path("f"), [], 1000.0, CAND, SCENE, SCENE, FOOD, SETTINGS
    )
    assert verdict.decision == "veto" and verdict.retry == "promo" and trace == []
