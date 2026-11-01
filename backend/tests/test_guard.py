"""The battery guard is the single gate for every action the assistant can take."""
import asyncio

import pytest

from app.assistant.router import ACTION_TOOLS, ToolRouter
from app.battery_core import guard
from app.context import AppContext

# One representative call per action tool (state is prepared so each one actually executes)
CALLS = {
    "navigate_to": {"destination": "Indiranagar"},
    "add_stop": {"place": "McDonald's"},
    "cancel_navigation": {},
    "start_charging": {"target_percent": 80},
    "set_climate": {"mode": "off"},
    "precool_cabin": {"minutes": 10},
    "assisted_driving": {"action": "turn_camera", "side": "left"},
}


@pytest.fixture(scope="module")
def shared():
    return AppContext()


@pytest.fixture()
def ctx(shared):
    shared.reset()
    return shared


@pytest.fixture()
def spy(monkeypatch):
    calls = []
    real = guard.check

    def wrapped(action, **kw):
        d = real(action, **kw)
        calls.append((action, d.verdict))
        return d
    monkeypatch.setattr(guard, "check", wrapped)
    return calls


def _prepare(ctx, tool):
    st = ctx.state
    if tool in ("add_stop", "cancel_navigation"):
        st.soc = 0.95
        ToolRouter(ctx).execute("navigate_to", {"destination": "Mysuru"})
    if tool == "start_charging":
        st.location = ctx.home_node            # home wallbox
    if tool == "precool_cabin":
        st.plugged_in = True


def test_every_action_tool_is_covered():
    assert set(CALLS) == ACTION_TOOLS


@pytest.mark.parametrize("tool", sorted(ACTION_TOOLS))
def test_action_consults_guard_before_executing(ctx, spy, tool):
    _prepare(ctx, tool)
    spy.clear()
    res = ToolRouter(ctx).execute(tool, CALLS[tool])
    assert res["ok"], res["say"]
    assert spy, f"{tool} ran without calling guard.check"
    assert res["guard"]["verdict"] in ("allow", "modify")


def test_refusal_leaves_the_car_untouched(ctx, monkeypatch):
    monkeypatch.setattr(guard, "check", lambda action, **kw: guard.GuardDecision(False, "refused_for_test", ["no"]))
    st = ctx.state
    before = (st.active_plan, st.hvac_mode, st.precooling)
    r = ToolRouter(ctx)
    assert not r.execute("navigate_to", {"destination": "Indiranagar"})["ok"]
    assert not r.execute("set_climate", {"mode": "heat"})["ok"]
    st.plugged_in = True
    assert not r.execute("precool_cabin", {"minutes": 10})["ok"]
    assert (st.active_plan, st.hvac_mode, st.precooling) == before


def test_action_without_verdict_is_rejected(ctx, monkeypatch):
    r = ToolRouter(ctx)
    monkeypatch.setattr(r, "t_set_climate", lambda mode="off": {"ok": True, "guard": None, "say": ""})
    with pytest.raises(RuntimeError, match="without a battery-guard check"):
        r.execute("set_climate", {"mode": "off"})


def test_verdicts_and_proposed_stop(ctx):
    net, cond = ctx.net, ctx.battery.conditions(ctx.state)
    home = net.place_node("koramangala")
    short = ctx.planner.plan(home, [net.place_node("indiranagar")], 0.5, cond)
    assert guard.check("navigate", plan=short).verdict == "allow"

    long = ctx.planner.plan(home, [net.place_node("mysuru")], 0.46, cond)
    d = guard.check("navigate", plan=long)
    assert d.verdict == "modify" and d.proposed_stop["name"] == long["stops"][0]["name"]
    assert "charging stop" in d.reason

    stuck = ctx.planner.plan(net.place_node("mysuru"), [net.place_node("kolar")], 0.04, cond)
    d = guard.check("navigate", plan=stuck)
    assert d.verdict == "refuse" and d.reason


def test_llm_path_goes_through_guard(ctx, spy):
    from tests.test_pipeline import FakeLLM, run
    from app.assistant.pipeline import AssistantPipeline
    pipe = AssistantPipeline(ctx)
    pipe.llm = FakeLLM({"role": "assistant", "content": "", "tool_calls": [
        {"function": {"name": "navigate_to", "arguments": {"destination": "Mysore"}}}]})
    spy.clear()
    run(pipe, "take me to mysore")
    assert ("navigate", "modify") in spy
