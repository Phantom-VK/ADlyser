from types import SimpleNamespace

from adlyser.cache import DiskCache
from adlyser.config import Endpoint
from adlyser.llm.agent_loop import Tool, run_agent
from adlyser.llm.client import ChatResult, LLMClient
from adlyser.schemas import BoundaryVerdict

FALLBACK = BoundaryVerdict(is_scene_change=False, break_score=0.0, reason="fallback")
GOOD = '{"is_scene_change": true, "break_score": 0.7, "reason": "closed"}'
MSGS = [{"role": "system", "content": "s"}, {"role": "user", "content": "hi"}]


def final(text):
    return ChatResult(SimpleNamespace(content=text, tool_calls=None), 1, 0, 0)


def wants(name, args='{"n": 2}', call_id="c1"):
    call = SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments=args))
    msg = SimpleNamespace(content=None, tool_calls=[call])
    msg.model_dump = lambda **kw: {"role": "assistant", "tool_calls": [{"id": call_id}]}
    return ChatResult(msg, 1, 0, 0)


def make(tmp_path, replies):
    """A real client whose chat() returns scripted results and records (messages, tools) per request."""
    ep = Endpoint(provider="deepseek", base_url="http://unused", model="m")
    client = LLMClient(ep, "k", DiskCache(tmp_path), concurrency=1, timeout_s=1, temperature=0.0)
    seen = []

    async def fake_chat(prompt, messages, **kwargs):
        seen.append((list(messages), kwargs.get("tools")))
        return replies.pop(0)

    client.chat = fake_chat
    return client, seen


def tool(record):
    spec = {"type": "function", "function": {"name": "peek", "parameters": {}}}

    async def run(args):
        record.append(args)
        return "2 frames follow", [b"a", b"b"]

    return Tool(spec=spec, run=run)


async def test_answer_without_tools(tmp_path):
    client, seen = make(tmp_path, [final(GOOD)])
    out, trace = await run_agent(client, "p", MSGS, [tool([])], BoundaryVerdict, FALLBACK, 2)
    assert out.is_scene_change and trace == [] and len(seen) == 1


async def test_tool_round_returns_frames_in_a_user_message(tmp_path):
    used = []
    client, seen = make(tmp_path, [wants("peek"), final(GOOD)])
    out, trace = await run_agent(client, "p", MSGS, [tool(used)], BoundaryVerdict, FALLBACK, 2)
    assert out.is_scene_change and used == [{"n": 2}]
    assert trace == [{"tool": "peek", "args": {"n": 2}, "frames": 2}]
    convo = seen[1][0]
    assert convo[-2] == {"role": "tool", "tool_call_id": "c1", "content": "2 frames follow"}
    last = convo[-1]
    assert last["role"] == "user" and sum(p["type"] == "image_url" for p in last["content"]) == 2


async def test_the_last_request_is_made_without_tools(tmp_path):
    client, seen = make(tmp_path, [wants("peek"), wants("peek", call_id="c2"), final(GOOD)])
    await run_agent(client, "p", MSGS, [tool([])], BoundaryVerdict, FALLBACK, 2)
    assert [offered is not None for _, offered in seen] == [True, True, False]


async def test_unknown_tool_is_reported_to_the_model_and_the_loop_continues(tmp_path):
    client, seen = make(tmp_path, [wants("nope"), final(GOOD)])
    out, trace = await run_agent(client, "p", MSGS, [tool([])], BoundaryVerdict, FALLBACK, 2)
    assert out.is_scene_change and trace[0]["error"] == "unknown tool"
    assert seen[1][0][-1]["content"].startswith("error: unknown tool")


async def test_bad_tool_arguments_do_not_crash(tmp_path):
    client, _ = make(tmp_path, [wants("peek", args="{not json"), final(GOOD)])
    out, trace = await run_agent(client, "p", MSGS, [tool([])], BoundaryVerdict, FALLBACK, 2)
    assert out.is_scene_change and "error" in trace[0]


async def test_one_retry_on_bad_json_then_fallback(tmp_path):
    client, seen = make(tmp_path, [final("nope"), final(GOOD)])
    out, _ = await run_agent(client, "p", MSGS, [], BoundaryVerdict, FALLBACK, 2)
    assert out.is_scene_change and len(seen) == 2
    client, seen = make(tmp_path / "b", [final("nope"), final("still nope")])
    out, _ = await run_agent(client, "p", MSGS, [], BoundaryVerdict, FALLBACK, 2)
    assert out == FALLBACK and client.stats["p"]["fallbacks"] == 1


async def test_answer_and_trace_are_cached(tmp_path):
    client, _ = make(tmp_path, [wants("peek"), final(GOOD)])
    await run_agent(client, "p", MSGS, [tool([])], BoundaryVerdict, FALLBACK, 2)
    client2, seen2 = make(tmp_path, [])
    out, trace = await run_agent(client2, "p", MSGS, [tool([])], BoundaryVerdict, FALLBACK, 2)
    assert out.is_scene_change and len(trace) == 1 and seen2 == []
