"""All prompts live here. Each system prompt gets its output schema appended by ``with_schema``."""

import json

from pydantic import BaseModel

from adlyser.schemas import SafetyTag

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

BOUNDARY_JUDGE = """You judge a candidate ad-break point in a Bengali TV drama.
You receive 2 frames just BEFORE the cut and 2 frames just AFTER it, plus summaries of the
stretch before and after.

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
