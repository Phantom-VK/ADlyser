"""OpenAI-compatible LLM client: JSON mode, Pydantic validation, one retry, cache, safe fallback."""

import asyncio
import base64
import json
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, TypeVar

import openai
from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from adlyser.cache import DiskCache, content_key
from adlyser.config import Endpoint, Settings
from adlyser.errors import LlmError
from adlyser.llm.prompts import FIX_JSON
from adlyser.log import get_logger

log = get_logger(__name__)
T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class ChatResult:
    """One raw chat completion."""

    message: Any
    ms: int
    prompt_tokens: int
    completion_tokens: int


def image_part(jpeg: bytes, detail: str = "low") -> dict[str, Any]:
    """Build an image content part from JPEG bytes.

    :param jpeg: encoded JPEG.
    :param detail: ``low``, ``high`` or ``auto``.
    :return: a chat-completions ``image_url`` content part.
    """
    url = "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()
    return {"type": "image_url", "image_url": {"url": url, "detail": detail}}


def _count_images(messages: list[dict[str, Any]]) -> int:
    """Count the image parts across chat messages."""
    return sum(
        1
        for m in messages
        if isinstance(m.get("content"), list)
        for part in m["content"]
        if part.get("type") == "image_url"
    )


def user_message(text: str, images: list[bytes] | None = None, detail: str = "low") -> dict[str, Any]:
    """Build a user message with text followed by images.

    :param text: the text part.
    :param images: JPEG frames, in order.
    :param detail: image detail level.
    :return: a chat message dict.
    """
    content: list[dict[str, Any]] = [{"type": "text", "text": text}]
    content += [image_part(img, detail) for img in images or []]
    return {"role": "user", "content": content}


class LLMClient:
    """Async client for one OpenAI-compatible endpoint."""

    def __init__(
        self,
        endpoint: Endpoint,
        api_key: str,
        cache: DiskCache,
        concurrency: int,
        timeout_s: float,
        temperature: float,
    ) -> None:
        """Create a client.

        :param endpoint: base_url + model.
        :param api_key: provider key (never logged).
        :param cache: disk cache for validated responses.
        :param concurrency: max in-flight calls.
        :param timeout_s: per-call timeout.
        :param temperature: sampling temperature for every call.
        """
        self.endpoint = endpoint
        self.temperature = temperature
        self.cache = cache
        self.stats: defaultdict[str, Counter[str]] = defaultdict(Counter)
        self._sem = asyncio.Semaphore(concurrency)
        self._client = AsyncOpenAI(
            base_url=endpoint.base_url, api_key=api_key or "missing", timeout=timeout_s
        )

    async def chat(
        self,
        prompt: str,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        json_mode: bool = True,
    ) -> ChatResult:
        """Send one chat completion and log its latency.

        :param prompt: prompt name, for logs.
        :param messages: chat messages.
        :param tools: optional tool definitions.
        :param json_mode: request ``json_object`` output (not allowed together with tools on some models).
        :return: the raw result.
        :raises LlmError: if the API call fails.
        """
        kwargs: dict[str, Any] = {
            "model": self.endpoint.model,
            "messages": messages,
            "temperature": self.temperature,
        }
        if tools:
            kwargs["tools"] = tools
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        start = time.perf_counter()
        try:
            async with self._sem:
                resp = await self._client.chat.completions.create(**kwargs)
        except openai.OpenAIError as exc:
            raise LlmError(f"{prompt}: {type(exc).__name__}: {exc}") from exc
        ms = int((time.perf_counter() - start) * 1000)
        usage = resp.usage
        self.stats[prompt].update(
            requests=1,
            ms=ms,
            images=_count_images(messages),
            in_tok=usage.prompt_tokens if usage else 0,
            out_tok=usage.completion_tokens if usage else 0,
        )
        result = ChatResult(
            message=resp.choices[0].message,
            ms=ms,
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
        )
        log.info(
            "llm_call",
            extra={
                "prompt": prompt,
                "model": self.endpoint.model,
                "ms": ms,
                "cached": False,
                "in_tok": result.prompt_tokens,
                "out_tok": result.completion_tokens,
            },
        )
        return result

    async def chat_json(
        self,
        prompt: str,
        messages: list[dict[str, Any]],
        model: type[T],
        fallback: T,
    ) -> T:
        """Get a Pydantic-validated JSON answer: cache, one retry, then the fallback.

        :param prompt: prompt name, for logs and cache namespace.
        :param messages: chat messages (the schema should already be in the system prompt).
        :param model: the expected output model.
        :param fallback: conservative value returned if both attempts fail (never cached).
        :return: a validated ``model`` instance.
        """
        key = content_key(self.endpoint.model, self.temperature, prompt, messages, model.model_json_schema())
        hit = self.cache.get(prompt, key)
        if hit is not None:
            try:
                out = model.model_validate(hit)
                self.stats[prompt]["cached"] += 1
                log.info(
                    "llm_call",
                    extra={
                        "prompt": prompt,
                        "model": self.endpoint.model,
                        "ms": 0,
                        "cached": True,
                    },
                )
                return out
            except ValidationError:
                pass
        nudge: list[dict[str, Any]] = []
        for attempt in (1, 2):
            try:
                result = await self.chat(prompt, [*messages, *nudge])
                raw = result.message.content or ""
                out = model.model_validate(json.loads(raw))
            except (LlmError, ValidationError, json.JSONDecodeError) as exc:
                if not isinstance(exc, LlmError):  # bad JSON: say so on the retry
                    nudge = [{"role": "assistant", "content": raw}, {"role": "user", "content": FIX_JSON}]
                log.warning(
                    "llm_bad_output",
                    extra={
                        "prompt": prompt,
                        "attempt": attempt,
                        "error": type(exc).__name__,
                    },
                )
                continue
            self.cache.set(prompt, key, out.model_dump(mode="json"))
            return out
        self.stats[prompt]["fallbacks"] += 1
        log.error("llm_fallback", extra={"prompt": prompt})
        return fallback

    async def list_models(self) -> list[str]:
        """List model ids the endpoint offers.

        :return: model ids.
        :raises LlmError: if the call fails.
        """
        try:
            page = await self._client.models.list()
        except openai.OpenAIError as exc:
            raise LlmError(f"models.list: {exc}") from exc
        return [m.id for m in page.data]


def make_clients(settings: Settings) -> tuple[LLMClient, LLMClient]:
    """Build the (vision, text) clients from settings.

    :param settings: loaded settings.
    :return: ``(vision_client, text_client)``.
    """
    cache = DiskCache(settings.cache_dir / "llm")
    llm = settings.llm

    def build(ep: Endpoint) -> LLMClient:
        return LLMClient(
            ep, settings.api_key(ep.provider), cache, llm.concurrency, llm.timeout_s, llm.temperature
        )

    return build(llm.vision), build(llm.text)
