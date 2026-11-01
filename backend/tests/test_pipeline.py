"""LLM pipeline plumbing with a mocked Ollama (no server needed)."""
import asyncio

from app.assistant.pipeline import AssistantPipeline
from app.context import AppContext


class FakeLLM:
    """First call returns a tool call; second (phrasing) call returns prose."""

    def __init__(self, first):
        self.first = first
        self.calls = []

    async def available(self):
        return True

    def mark_unavailable(self):
        pass

    async def chat(self, messages, tools=None, temperature=0.1):
        self.calls.append({"messages": messages, "tools": tools})
        if tools:
            return self.first
        tool_msgs = [m for m in messages if m["role"] == "tool"]
        assert tool_msgs, "phrasing pass must receive tool results"
        return {"role": "assistant", "content": "Phrased: " + tool_msgs[0]["content"][:40]}


def run(pipe, text):
    return asyncio.run(pipe.handle(text))


def test_llm_tool_call_goes_through_guarded_router():
    ctx = AppContext()
    pipe = AssistantPipeline(ctx)
    pipe.llm = FakeLLM({"role": "assistant", "content": "", "tool_calls": [
        {"function": {"name": "navigate_to", "arguments": {"destination": "Mysore"}}}]})
    out = run(pipe, "take me to mysore")
    assert out["source"] == "llm"
    assert out["tool_calls"][0]["name"] == "navigate_to"
    assert out["tool_calls"][0]["guard"] == "ok_with_charge_stop"
    assert ctx.state.active_plan["stops"]              # guard + planner added a charging stop
    assert out["reply"].startswith("Phrased:")
    assert len(pipe.llm.calls) == 2


def test_safety_net_when_llm_answers_in_prose():
    ctx = AppContext()
    pipe = AssistantPipeline(ctx)
    pipe.llm = FakeLLM({"role": "assistant", "content": "Sure, Mysore is lovely!"})
    out = run(pipe, "will I make it to Mysore without stopping?")
    assert out["tool_calls"][0]["name"] == "check_range_to"   # rule parser forced the grounded tool


def test_hallucinated_arguments_are_dropped():
    ctx = AppContext()
    pipe = AssistantPipeline(ctx)
    pipe.llm = FakeLLM({"role": "assistant", "content": "", "tool_calls": [
        {"function": {"name": "set_climate", "arguments": {"mode": "off", "fan_speed": 3}}}]})
    out = run(pipe, "turn off the ac")
    assert out["tool_calls"][0]["ok"] and ctx.state.hvac_mode == "off"


def test_navigate_with_stop_on_the_way():
    ctx = AppContext()
    pipe = AssistantPipeline(ctx)
    pipe.llm = FakeLLM({"role": "assistant", "content": "", "tool_calls": [
        {"function": {"name": "navigate_to", "arguments": {"destination": "office", "stop_at": "McDonald's"}}}]})
    out = run(pipe, "take me to office with a stop at mcdonalds on the way")
    plan = ctx.state.active_plan
    assert out["tool_calls"][0]["ok"]
    assert len(plan["destinations"]) == 2 and "McDonald" in plan["destination_names"][0]
    assert len(plan["destination_coords"]) == 2      # the map draws a marker for the stop


class DownLLM:
    """Ollama not running (available() is False) or failing mid-request (chat raises)."""

    def __init__(self, reachable=False):
        self.reachable, self.marked = reachable, False

    async def available(self):
        return self.reachable and not self.marked

    def mark_unavailable(self):
        self.marked = True

    async def chat(self, *a, **k):
        raise ConnectionError("model crashed")


import pytest  # noqa: E402


@pytest.mark.parametrize("reachable", [False, True], ids=["ollama-down", "ollama-crashes"])
@pytest.mark.parametrize("text,tool,guard", [
    ("Will I make it to Mysore without stopping?", "check_range_to", "ok_with_charge_stop"),
    ("take me to the nearest McD", "navigate_to", "ok"),
    ("why is my range lower than usual", "explain_range", None),
    ("how are my charging habits", "get_charging_coaching", None),
])
def test_rule_based_fallback_end_to_end(reachable, text, tool, guard):
    ctx = AppContext()
    pipe = AssistantPipeline(ctx)
    pipe.llm = DownLLM(reachable)
    out = run(pipe, text)
    assert out["source"] == "fallback"
    call = out["tool_calls"][0]
    assert call["name"] == tool and call["ok"] and call["guard"] == guard
    assert out["reply"] and "Sorry" not in out["reply"]


@pytest.mark.parametrize("text,llm_tool,expected", [
    ("Take me to Mysuru", "check_range_to", "navigate_to"),
    ("take me to the nearest McD", "list_chargers", "navigate_to"),
    ("Will I make it to Mysore without stopping?", "check_range_to", "check_range_to"),   # a question stays a question
])
def test_clear_command_overrides_llm_lookup(text, llm_tool, expected):
    ctx = AppContext()
    pipe = AssistantPipeline(ctx)
    pipe.llm = FakeLLM({"role": "assistant", "content": "", "tool_calls": [
        {"function": {"name": llm_tool, "arguments": {"destination": "Mysuru"}}}]})
    out = run(pipe, text)
    assert out["tool_calls"][0]["name"] == expected
