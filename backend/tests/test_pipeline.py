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
