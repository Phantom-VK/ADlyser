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


async def test_sweep_sends_frames_across_the_whole_scene_and_returns_seen_and_unsure_tags(monkeypatch):
    frames_ok(monkeypatch)
    reply = SweepResult(
        safety_tags=[SafetyTag.DEATH_GRIEF], unsure_tags=[SafetyTag.MEDICAL_ILLNESS], evidence="funeral"
    )
    client = FakeClient(reply)
    out = await reviewer.sweep_scene(client, Path("v.mp4"), Path("f"), SCENE, SETTINGS)
    assert (
        out.ok
        and out.safety_tags == [SafetyTag.DEATH_GRIEF]
        and out.unsure_tags == [SafetyTag.MEDICAL_ILLNESS]
    )
    content = client.messages[1]["content"]
    assert sum(p["type"] == "image_url" for p in content) == 10 == out.frames  # 95 s at one frame per 10 s
    assert out.full_coverage and "Current tags: alcohol" in content[0]["text"]


async def test_a_scene_longer_than_the_frame_cap_allows_is_a_capped_sweep(monkeypatch):
    frames_ok(monkeypatch)
    long_scene = SCENE.model_copy(
        update={"end": SETTINGS.reviewer.sweep_interval_s * (SETTINGS.reviewer.sweep_max_frames + 5)}
    )
    out = await reviewer.sweep_scene(
        FakeClient(SweepResult(evidence="e")), Path("v.mp4"), Path("f"), long_scene, SETTINGS
    )
    assert out.ok and not out.full_coverage and out.frames == SETTINGS.reviewer.sweep_max_frames


async def test_sweep_that_cannot_get_frames_is_not_ok(monkeypatch):
    def boom(*args):
        raise PerceptionError("no frame")

    monkeypatch.setattr(reviewer, "extract_frames", boom)
    out = await reviewer.sweep_scene(FakeClient(), Path("v.mp4"), Path("f"), SCENE, SETTINGS)
    assert not out.ok and out.safety_tags == [] and out.frames == 0


async def test_sweep_whose_call_fails_is_not_ok(monkeypatch):
    frames_ok(monkeypatch)
    out = await reviewer.sweep_scene(FakeClient(None), Path("v.mp4"), Path("f"), SCENE, SETTINGS)
    assert not out.ok


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
