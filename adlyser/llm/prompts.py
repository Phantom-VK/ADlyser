"""All prompts live here. Each system prompt gets its output schema appended by ``with_schema``."""

import json

from pydantic import BaseModel

from adlyser.schemas import Brand, Candidate, SafetyTag, Scene, SpeechSeg, Stretch, TranscriptSeg

_TAXONOMY = ", ".join(t.value for t in SafetyTag)

# One line per safety tag: what counts and what does not. The stretch analyst, the sweep and the catalogue
# normaliser all read these, so a tag means the same thing everywhere.
TAG_DEFINITIONS: dict[str, str] = {
    "death_grief": "a death, a dead body, or people grieving a loss; NOT a memory, a photo or a passing mention",
    "funeral_ritual": "a funeral, cremation, burial or mourning rite; NOT a wedding or a festive prayer",
    "violence": "people hitting, fighting or hurting each other, or threatening to; NOT a raised voice or a heated talk",
    "crime_weapons": "a crime being committed or a gun, knife or similar weapon in use or in view; NOT people only talking about a crime",
    "accident_injury": "a crash, a fall, or a visibly injured or bleeding person; NOT a healthy person mentioning an old injury",
    "medical_illness": "a hospital, sickbed, drip or treatment, or a visibly ill person; NOT a passing mention of a doctor",
    "alcohol": "alcohol being drunk, poured or prominently shown; NOT a bottle of water or a shelf in the background",
    "tobacco_drugs": "someone smoking or using tobacco or drugs; NOT a printed warning or a poster",
    "sexual_content": "nudity, sexual activity, explicit kissing or foreplay; NOT family affection, hugging, feeding or couples sitting together",
    "abuse_harassment": "one person abusing, bullying, stalking or harassing another; NOT an ordinary disagreement",
    "religion_sensitive": "religious conflict, mockery of a faith or a sacred rite shown in a controversial way; NOT a family prayer or a temple visit",
    "disaster": "a flood, fire, earthquake, riot or other mass emergency; NOT a candle or a cooking flame",
    "hunger_poverty": "visible destitution: begging, starvation or people living on the street; NOT a modest home or a simple meal",
    "strong_argument": "visible anger, shouting or confrontation between people; NOT animated talk",
}
_DEFINITIONS = "\n".join(f"  {tag} = {text}" for tag, text in TAG_DEFINITIONS.items())

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
  A tag applies only when what you see fits its definition, including the NOT part:
{_DEFINITIONS}
- is_titles: true only if the stretch is mostly opening or closing titles, a credit montage, a
  disclaimer or title card, or a "previously on" recap, and not story scenes. A stretch that mixes
  titles with story is false unless the titles clearly dominate. Otherwise false.
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


CATALOGUE_NORMALISER = f"""You convert a brand catalogue, in any format (JSON, CSV or free text),
into a fixed schema. Every brand in the input must appear exactly once in the output.

- name, category, tagline, description: copy or condense from the input.
- target_contexts: short phrases for the moments and activities where the brand fits.
- negative_contexts_raw: the input's own words about when the brand must NOT appear, split into
  short phrases. Copy them faithfully; never drop one.
- negative_tags: map EVERY negative context to the tags of this fixed list that it implies, and use
  only these exact values: {_TAXONOMY}. What each tag means:
{_DEFINITIONS}
  Map each phrase to the tags it directly names; do not add
  adjacent tags (e.g. "illness" -> medical_illness only; "mourning" -> death_grief, funeral_ritual,
  because mourning names both a death and its rites).
- Reply with JSON only."""

BRAND_RERANK = """You choose the best brand to advertise in a break in a Bengali TV drama.
You receive the scene the viewer just watched (what happens, its activity and mood) and a few
candidate brands that are already known to be safe for this break.

- Rank the brands from best to worst contextual fit with what the viewer just watched.
- fit: 0 to 1. Use a low value for a brand that does not fit the scene.
- reason: one short sentence that refers to the scene.
- Only use the brand ids you were given. Reply with JSON only."""

SAFETY_SWEEP = f"""You are a brand-safety inspector for a Bengali TV drama. You receive frames spread
across ONE whole scene, numbered from 1 in time order. Report two lists, using only these exact tag
values: {_TAXONOMY}.

- safety_tags: tags that clearly apply to something visible in the scene, even briefly (a funeral or
  hospital insert of a few seconds still counts).
- unsure_tags: tags that might apply but you cannot tell (dark, blurry, partial). Unsure tags are
  treated as present, so list one only if a frame shows something that could really be it. An unsure
  tag needs a visible cue like any other: name what you can see. A cue that states nothing is visible
  ("no explicit content", "tone unclear", "nothing shows anger") is not a cue, so leave that tag out.
- A tag applies only when what you see fits its definition, including the NOT part:
{_DEFINITIONS}
- EVERY tag, in both lists, must be an object {{"tag": ..., "frames": [frame numbers], "cue": "what is visible"}}.
  A tag without frame numbers that show it is discarded.
- Tag only what is visible in the scene itself. Boilerplate text alone is NOT a cue: disclaimer cards,
  title cards, credits, statutory warnings (for example "smoking kills"), posters and captions do not
  count. A poster or sign in the background is not the scene showing that activity.
- The scene may already carry tags from an earlier pass. Report what you see, including tags already
  present. Never remove or argue against a tag.
- evidence: one short sentence summarising the scene.
- Reply with JSON only."""

BREAK_REVIEWER = """You are the final reviewer of one planned ad break in a Bengali TV drama.
You receive: frames around the break, the summaries and safety tags of the scene before and after,
the length of the silence, the speech map around the break, the chosen brand and, in the brand's own
words, when it must NOT appear.

- approve only if the break is a natural pause and the brand would not be insensitive here.
- veto if the moment feels mid-scene or mid-conversation, or if anything in the frames or summaries
  clashes with the brand's own words about when it must not appear.
- On a veto, retry says what to try next: next_brand (another brand may fit), next_candidate (this
  moment is a poor break for any ad) or promo (show a neutral house promo instead of a brand).
- You may call the tools to look closer at frames or read the speech map before you decide.
- Reply with JSON only."""


# Added to a user message only when a transcript exists, so runs without one keep their cached answers.
TRANSCRIPT_NOTE = (
    "The transcript is a noisy auto transcript, words may be wrong; use only as a hint. It may add "
    "evidence for a safety tag, but never remove or clear one, and never raise your confidence above "
    "what the frames show."
)

FIX_JSON = (
    "Your previous reply was not valid JSON for the schema. Reply again with only the corrected JSON object."
)


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
    note = "" if transcript == "unavailable" else f"\n{TRANSCRIPT_NOTE}"
    return (
        f"Stretch {clock(stretch.start)} to {clock(stretch.end)}{span}. "
        f"{len(times)} frames in time order, taken at {stamps}.{note}\nTranscript: {transcript}"
    )


def boundary_text(cand: Candidate, before: str, after: str, transcript: str) -> str:
    """User text for one BoundaryJudge call.

    :param cand: the candidate pause.
    :param before: summary of the stretch before the cut.
    :param after: summary of the stretch after the cut.
    :param transcript: transcript around the cut, or ``unavailable``.
    :return: the text part of the user message.
    """
    note = "" if transcript == "unavailable" else f"{TRANSCRIPT_NOTE}\n"
    return (
        f"Cut at {clock(cand.t)}. Frames: 2 before, then 2 after.\n"
        f"Silence around the cut: {cand.silence_s:.1f} s. Cut type: {cand.kind}.\n"
        f"Before: {before}\nAfter: {after}\n{note}Transcript: {transcript}"
    )


def brand_lines(brands: list[Brand]) -> str:
    """One line per brand for the rerank prompt.

    :param brands: the shortlisted brands.
    :return: text with id, name, category, description and target contexts.
    """
    return "\n".join(
        f"- id={b.id} | {b.name} ({b.category}): {b.description} Fits: {', '.join(b.target_contexts)}"
        for b in brands
    )


def scene_line(scene: Scene) -> str:
    """A short description of a scene for prompts.

    :param scene: the scene.
    :return: time range, activity, summary and tags.
    """
    tags = ", ".join(t.value for t in scene.safety_tags) or "none"
    return (
        f"{clock(scene.start)}-{clock(scene.end)} | activity: {scene.dominant_activity} | "
        f"{scene.summary} | safety tags: {tags}{' | UNKNOWN' if scene.unknown else ''}"
    )


def speech_text(speech: list[SpeechSeg], t0: float, t1: float) -> str:
    """The speech map inside ``[t0, t1]`` as text, for the reviewer and its ``speech_map`` tool.

    :param speech: all speech spans.
    :param t0: window start in seconds.
    :param t1: window end in seconds.
    :return: the clipped spans, or a note that there is no speech.
    """
    spans = [(max(s.start, t0), min(s.end, t1)) for s in speech if s.end > t0 and s.start < t1]
    if not spans:
        return f"No speech between {clock(t0)} and {clock(t1)}."
    body = "; ".join(f"{a:.1f}s-{b:.1f}s" for a, b in spans)
    return f"Speech between {clock(t0)} and {clock(t1)}: {body}."
