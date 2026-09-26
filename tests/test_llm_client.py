from types import SimpleNamespace

import pytest

from adlyser.cache import DiskCache
from adlyser.config import Endpoint
from adlyser.errors import LlmError
from adlyser.llm.client import ChatResult, LLMClient
from adlyser.schemas import BoundaryVerdict

FALLBACK = BoundaryVerdict(is_scene_change=False, break_score=0.0, reason="fallback")
GOOD = '{"is_scene_change": true, "break_score": 0.7, "reason": "scene closed"}'


def make_client(tmp_path, replies):
    """Client whose chat() returns scripted replies (a str, or an Exception to raise)."""
    ep = Endpoint(provider="deepseek", base_url="http://unused", model="m")
    client = LLMClient(ep, "k", DiskCache(tmp_path), concurrency=1, timeout_s=1)
    calls = []

    async def fake_chat(prompt, messages, **kwargs):
        calls.append(prompt)
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return ChatResult(SimpleNamespace(content=reply), 1, 0, 0)

    client.chat = fake_chat
    return client, calls


MSGS = [{"role": "user", "content": "hi"}]


async def test_valid_reply_is_returned_and_cached(tmp_path):
    client, calls = make_client(tmp_path, [GOOD])
    first = await client.chat_json("p", MSGS, BoundaryVerdict, FALLBACK)
    second = await client.chat_json("p", MSGS, BoundaryVerdict, FALLBACK)
    assert first.break_score == 0.7 and second == first
    assert len(calls) == 1


async def test_one_retry_then_success(tmp_path):
    client, calls = make_client(tmp_path, ["not json", GOOD])
    out = await client.chat_json("p", MSGS, BoundaryVerdict, FALLBACK)
    assert out.is_scene_change is True and len(calls) == 2


@pytest.mark.parametrize("bad", ["not json", '{"is_scene_change": "maybe"}', LlmError("boom")])
async def test_two_failures_return_fallback_and_are_not_cached(tmp_path, bad):
    client, calls = make_client(tmp_path, [bad, bad])
    out = await client.chat_json("p", MSGS, BoundaryVerdict, FALLBACK)
    assert out == FALLBACK and len(calls) == 2
    client2, calls2 = make_client(tmp_path, [GOOD])
    assert (await client2.chat_json("p", MSGS, BoundaryVerdict, FALLBACK)).reason == "scene closed"
    assert len(calls2) == 1


async def test_stats_count_cache_hits_and_fallbacks(tmp_path):
    client, _ = make_client(tmp_path, [GOOD, "bad", "bad"])
    await client.chat_json("p", MSGS, BoundaryVerdict, FALLBACK)
    await client.chat_json("p", MSGS, BoundaryVerdict, FALLBACK)  # cache hit
    await client.chat_json("q", MSGS, BoundaryVerdict, FALLBACK)  # two bad replies
    assert client.stats["p"]["cached"] == 1
    assert client.stats["q"]["fallbacks"] == 1
