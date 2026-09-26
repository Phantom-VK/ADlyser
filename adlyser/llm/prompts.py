"""All prompts live here. Each system prompt gets its output schema appended by ``with_schema``."""

import json

from pydantic import BaseModel

from adlyser.schemas import Candidate, SafetyTag, Stretch, TranscriptSeg

_TAXONOMY = ", ".join(t.value for t in SafetyTag)

STRETCH_ANALYST = f"""You analyse one continuous stretch of a Bengali TV drama episode.
You receive frames spread evenly across the stretch (in time order) and, when available,
its transcript. Describe what happens in the WHOLE stretch, not just the last frame.

Rules:
- dominant_activity: the single main activity (e.g. cooking, eating, travel, office work,
  romance, celebration, shopping, commuting, study, argument, mourning).
- activity_tags: short lowercase activity words seen anywhere in the stretch.
- safety_tags: include EVERY tag from this fixed list that applies to ANYTHING in the stretch,
  even briefly. Only use these exact values: {_TAXONOMY}.
  Sensitive material earlier in the stretch still counts even if the last frames look neutral.
- confidence: 0 to 1. Use a low value if the frames are ambiguous, dark or you are guessing.
- Reply with JSON only."""

STRETCH_TOOLS = """

You may call the tool look_closer(t0, t1, n) to get n more frames (times in seconds from the start
of the episode). Use it only when the frames are ambiguous or a safety tag is uncertain, for example
whether a place is a hospital or a funeral. Then give your final JSON answer."""

BOUNDARY_JUDGE = """You judge a candidate ad-break point in a Bengali TV drama.
You receive 2 frames just BEFORE the cut and 2 frames just AFTER it, plus summaries of the
stretch before and after, the length of the silence around the cut, and the kind of cut
(hard = a shot cut, black = a fade to black, silence = no visual transition).
A transcript may be unavailable; judge from the frames and the summaries then.

- is_scene_change: true only if the story moves to a different scene, place, time or topic.
- break_score: 0 to 1. High = a natural place to pause (a scene has clearly closed, or a
  cliff-hanger beat). Low = the scene is mid-action or mid-conversation.
- reason: one short sentence.
- Reply with JSON only."""


def with_schema(system: str, model: type[BaseModel]) -> str:
    """Append the JSON schema of the expected output to a system prompt.

    :param system: the base system prompt.
    :param model: the Pydantic model the reply must match.
    :return: the prompt with the schema appended.
    """
    schema = json.dumps(model.model_json_schema(), ensure_ascii=False)
    return f"{system}\n\nRespond with a single JSON object matching this JSON schema:\n{schema}"


def clock(t: float) -> str:
    """Format seconds as m:ss (h:mm:ss from an hour).

    :param t: time in seconds.
    :return: a short clock string.
    """
    s = int(t)
    h, rest = divmod(s, 3600)
    return f"{h}:{rest // 60:02d}:{rest % 60:02d}" if h else f"{rest // 60}:{rest % 60:02d}"


def transcript_text(transcript: list[TranscriptSeg], t0: float, t1: float) -> str:
    """Transcript text overlapping ``[t0, t1]``, or ``unavailable`` when there is none.

    :param transcript: all transcript segments (empty when transcription is off).
    :param t0: window start in seconds.
    :param t1: window end in seconds.
    :return: the text for the prompt.
    """
    parts = [s.text.strip() for s in transcript if s.end > t0 and s.start < t1]
    return " ".join(parts) if parts else "unavailable"


def stretch_text(stretch: Stretch, times: list[float], transcript: str, with_seconds: bool = False) -> str:
    """User text for one StretchAnalyst call.

    :param stretch: the stretch being analysed.
    :param times: times of the attached frames, in order.
    :param transcript: transcript text for the stretch, or ``unavailable``.
    :param with_seconds: also give the stretch in raw seconds (needed to call ``look_closer``).
    :return: the text part of the user message.
    """
    stamps = ", ".join(clock(t) for t in times)
    span = f" ({stretch.start:.0f}s to {stretch.end:.0f}s)" if with_seconds else ""
    return (
        f"Stretch {clock(stretch.start)} to {clock(stretch.end)}{span}. "
        f"{len(times)} frames in time order, taken at {stamps}.\nTranscript: {transcript}"
    )


def boundary_text(cand: Candidate, before: str, after: str, transcript: str) -> str:
    """User text for one BoundaryJudge call.

    :param cand: the candidate pause.
    :param before: summary of the stretch before the cut.
    :param after: summary of the stretch after the cut.
    :param transcript: transcript around the cut, or ``unavailable``.
    :return: the text part of the user message.
    """
    return (
        f"Cut at {clock(cand.t)}. Frames: 2 before, then 2 after.\n"
        f"Silence around the cut: {cand.silence_s:.1f} s. Cut type: {cand.kind}.\n"
        f"Before: {before}\nAfter: {after}\nTranscript: {transcript}"
    )
