"""Core behaviour tests. Run from backend/:  python -m pytest -q
(requires generated data + trained models: see README)."""
import pytest

from app.assistant import fallback_parser
from app.battery_core import guard
from app.config import HARD_MIN_SOC, RESERVE_SOC
from app.context import AppContext


@pytest.fixture()
def ctx():
    return AppContext()


def test_soh_in_plausible_band(ctx):
    soh = ctx.battery.soh()
    assert 0.75 < soh["soh"] < 0.98
    assert soh["usable_kwh"] < soh["nominal_kwh"]


def test_range_is_personalized_not_linear(ctx):
    st = ctx.state
    st.hvac_mode, st.ambient_temp_c = "off", 25
    mild = ctx.battery.range_km(st)
    st.hvac_mode, st.ambient_temp_c = "ac", 40
    hot = ctx.battery.range_km(st)
    assert hot < mild * 0.9          # same SOC, different range


def test_attribution_sums_to_total_drop(ctx):
    ex = ctx.battery.explain_range(ctx.state)
    total = sum(c["km"] for c in ex["contributions"])
    assert abs((ex["current_km"] - ex["expected_km"]) - total) < 0.5


def test_short_trip_direct(ctx):
    p = ctx.planner.plan("koramangala", ["indiranagar"], 0.5, ctx.battery.conditions(ctx.state))
    assert p["status"] == "direct" and not p["stops"]
    assert guard.assess_plan(p).allow


def test_long_trip_gets_charging_stop(ctx):
    p = ctx.planner.plan("koramangala", ["mysuru"], 0.46, ctx.battery.conditions(ctx.state))
    assert p["status"] == "needs_charging" and p["stops"]
    for leg in p["legs"]:
        floor = HARD_MIN_SOC if leg["ends_at_charger"] else RESERVE_SOC
        assert leg["soc_arrive"] >= floor - 1e-6
    assert guard.assess_plan(p).status == "ok_with_charge_stop"


def test_infeasible_plan_is_blocked(ctx):
    p = ctx.planner.plan("mysuru", ["kolar"], 0.04, ctx.battery.conditions(ctx.state))
    assert p["status"] == "infeasible"
    assert not guard.assess_plan(p).allow


def test_router_never_activates_infeasible_route(ctx):
    from app.assistant.router import ToolRouter
    ctx.state.soc, ctx.state.location = 0.04, "mysuru"
    res = ToolRouter(ctx).execute("navigate_to", {"destination": "Kolar"})
    assert not res["ok"]
    assert ctx.state.active_plan is None


def test_mid_drive_replan_adds_stop(ctx):
    from app import simulation
    from app.assistant.router import ToolRouter
    r = ToolRouter(ctx)
    ctx.state.soc = 0.95
    assert r.execute("navigate_to", {"destination": "Mysuru"})["ok"]
    simulation.drive(ctx, 30)
    res = r.execute("add_stop", {"place": "McDonald's"})
    assert res["ok"]
    assert "McDonald" in " ".join(ctx.state.active_plan["destination_names"])


def test_precool_blocked_on_low_battery_unplugged(ctx):
    from app.assistant.router import ToolRouter
    ctx.state.soc, ctx.state.plugged_in = 0.15, False
    res = ToolRouter(ctx).execute("precool_cabin", {"minutes": 20})
    assert not res["ok"] and res["guard"]["status"] == "blocked_low_soc"


@pytest.mark.parametrize("text,tool", [
    ("take me to the nearest McD", "navigate_to"),
    ("will I make it to Mysore without stopping?", "check_range_to"),
    ("why is my range lower than usual", "explain_range"),
    ("turn off the AC", "set_climate"),
    ("pre-cool the car", "precool_cabin"),
    ("show the right camera", "assisted_driving"),
    ("how are my charging habits", "get_charging_coaching"),
])
def test_fallback_parser(text, tool):
    assert fallback_parser.parse(text)[0] == tool


def test_place_resolution(ctx):
    assert ctx.net.resolve("mysore", "koramangala")["node"] == "mysuru"
    assert ctx.net.resolve("nearest McD", "koramangala")["kind"] == "poi"
    assert ctx.net.resolve("home", "mysuru")["node"] == "koramangala"


@pytest.mark.parametrize("text,spoken", [
    ("about ₹1.67 per km", "about 1.67 rupees per kilometre"),
    ("worth ₹7.9 lakh", "worth 7.9 lakh rupees"),
    ("cost ₹1,395, 156 km", "cost 1,395 rupees, 156 kilometres"),
    ("27%→73% at 34 °C", "27 percent to 73 percent at 34 degrees"),
])
def test_tts_speakable(text, spoken):
    from app.assistant.tts import speakable
    assert speakable(text) == spoken


def test_cross_site_requests_refused():
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect
    from app.main import app
    c = TestClient(app)
    assert c.post("/api/sim/reset", headers={"Origin": "https://evil.example"}).status_code == 403
    assert c.post("/api/sim/reset", headers={"Origin": "http://localhost:5173"}).status_code == 200
    with pytest.raises(WebSocketDisconnect):
        with c.websocket_connect("/api/ws", headers={"Origin": "https://evil.example"}) as ws:
            ws.receive_text()
    with c.websocket_connect("/api/ws", headers={"Origin": "http://localhost:5173"}) as ws:
        assert '"state"' in ws.receive_text()


def test_audio_decode_is_capped():
    import io, wave
    import numpy as np
    from app.assistant.stt import decode_16k_mono
    from app.config import MAX_AUDIO_SECONDS
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:              # 60 s of silence, twice the cap
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(np.zeros(16000 * 60, dtype=np.int16).tobytes())
    assert len(decode_16k_mono(buf.getvalue())) == MAX_AUDIO_SECONDS * 16000
