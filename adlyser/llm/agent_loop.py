"""Bounded tool loop over JSON mode: tools may return frames, which go back in a user message.

The agent can only READ evidence through tools. Its decision is its typed final answer,
and code re-checks every rule afterwards.
"""

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from adlyser.cache import content_key
from adlyser.errors import AdlyserError, LlmError
from adlyser.llm.client import LLMClient, user_message
from adlyser.log import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class Tool:
    """A read-only tool: its OpenAI spec, a handler returning (text, frames), and the frame detail."""

    spec: dict[str, Any]
    run: Callable[[dict[str, Any]], Awaitable[tuple[str, list[bytes]]]]
    detail: str = "high"

    @property
    def name(self) -> str:
        """The tool name from its spec."""
        return self.spec["function"]["name"]


async def _call_tool(tool: Tool | None, name: str, raw_args: str) -> tuple[str, list[bytes], dict[str, Any]]:
    """Run one requested tool, turning any failure into text the model can read."""
    try:
        args = json.loads(raw_args or "{}")
        if tool is None:
            return f"error: unknown tool {name}", [], {"tool": name, "error": "unknown tool"}
        text, frames = await tool.run(args)
        return text, frames, {"tool": name, "args": args, "frames": len(frames)}
    except (ValueError, KeyError, TypeError, AdlyserError) as exc:
        return f"error: {exc}", [], {"tool": name, "error": str(exc)[:200]}


async def run_agent[T: BaseModel](
    client: LLMClient,
    prompt: str,
    messages: list[dict[str, Any]],
    tools: list[Tool],
    model: type[T],
    fallback: T,
    max_rounds: int,
) -> tuple[T, list[dict[str, Any]]]:
    """Run an agent: up to ``max_rounds`` tool rounds, then a final JSON answer (one retry, then fallback).

    :param client: the LLM client (its cache stores the final answer and the tool trace).
    :param prompt: prompt name, for logs, stats and the cache namespace.
    :param messages: the opening messages (schema already in the system prompt).
    :param tools: read-only tools the agent may call.
    :param model: the expected final output model.
    :param fallback: conservative value returned if the loop fails (never cached).
    :param max_rounds: most tool rounds; the last request is made without tools.
    :return: ``(answer, trace)`` where trace lists each tool call made.
    """
    key = content_key(
        client.endpoint.model,
        prompt,
        messages,
        model.model_json_schema(),
        max_rounds,
        [t.name for t in tools],
    )
    hit = client.cache.get(prompt, key)
    if hit is not None:
        try:
            client.stats[prompt]["cached"] += 1
            return model.model_validate(hit["answer"]), hit["trace"]
        except (ValidationError, KeyError, TypeError):
            client.stats[prompt]["cached"] -= 1
    by_name = {t.name: t for t in tools}
    convo = list(messages)
    trace: list[dict[str, Any]] = []
    rounds, retries = 0, 0
    while True:
        offer = [t.spec for t in tools] if rounds < max_rounds else None
        try:
            msg = (await client.chat(prompt, convo, tools=offer)).message
        except LlmError as exc:
            log.warning("agent_call_failed", extra={"prompt": prompt, "error": str(exc)[:200]})
            break
        if offer and msg.tool_calls:
            rounds += 1
            convo.append(msg.model_dump(exclude_none=True))
            frames: list[bytes] = []
            detail = "high"
            for call in msg.tool_calls:
                tool = by_name.get(call.function.name)
                text, imgs, entry = await _call_tool(tool, call.function.name, call.function.arguments)
                convo.append({"role": "tool", "tool_call_id": call.id, "content": text})
                frames += imgs
                detail = tool.detail if tool else detail
                trace.append(entry)
            if frames:
                convo.append(user_message("Frames returned by the tool, in order:", frames, detail))
            continue
        try:
            answer = model.model_validate(json.loads(msg.content or ""))
        except (ValidationError, json.JSONDecodeError) as exc:
            log.warning("agent_bad_output", extra={"prompt": prompt, "error": type(exc).__name__})
            if retries == 0:
                retries += 1
                continue
            break
        client.cache.set(prompt, key, {"answer": answer.model_dump(mode="json"), "trace": trace})
        return answer, trace
    client.stats[prompt]["fallbacks"] += 1
    log.error("agent_fallback", extra={"prompt": prompt})
    return fallback, trace
