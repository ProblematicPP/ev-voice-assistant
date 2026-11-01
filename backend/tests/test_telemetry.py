"""Simulated CAN telemetry, harsh-event detection and eco-driving coaching."""
import pytest

from app import simulation, telemetry
from app.assistant import fallback_parser, nudges
from app.assistant.router import ToolRouter
from app.context import AppContext


@pytest.fixture(scope="module")
def shared():
    return AppContext()


@pytest.fixture()
def ctx(shared):
    shared.reset()
    return shared


def rate(style, km=800):
    f = telemetry.SimulatedCanBus().frames(km, {"driving_style": style, "ambient_temp_c": 28}, 0.9, seed=3)
    return telemetry.summarize(telemetry.detect_events(f), km)["events_per_100km"]


def test_detector_finds_more_harsh_events_for_aggressive_drivers():
    assert rate(0.3) < rate(0.6) < rate(0.9)


def test_frames_look_like_a_can_log():
    f = telemetry.SimulatedCanBus().frames(10, {"driving_style": 0.5, "ambient_temp_c": 30}, 0.8, seed=1)
    assert len(f["t_s"]) > 600                                   # 1 Hz for ~23 min of city driving
    assert f["soc"][0] <= 0.8 and f["soc"][-1] < f["soc"][0]
    assert abs(f["odometer_km"][-1] - 10) < 1e-6


def test_obd_dongle_is_a_stub():
    with pytest.raises(NotImplementedError):
        telemetry.ObdDongle().frames(1, {}, 0.5)


def test_drive_logs_telemetry_and_nudges_on_harsh_braking(ctx):
    ctx.state.driving_style = 0.9
    simulation.drive(ctx, 40)
    drive = ctx.state.telemetry["drive"]
    assert drive["km"] == 40 and drive["harsh_brakes"] >= 2
    texts = [n["text"] for n in nudges.evaluate(ctx)]
    assert any("harsh brake" in t for t in texts)


def test_eco_coaching_tool_uses_core_range(ctx):
    assert fallback_parser.parse("am I braking too hard?")[0] == "get_eco_driving_coaching"
    assert fallback_parser.parse("how are my charging habits")[0] == "get_charging_coaching"
    res = ToolRouter(ctx).execute("get_eco_driving_coaching", {})
    assert res["ok"] and res["facts"]["harsh_brakes_per_100km"] > 0
    assert res["facts"]["range_gain_if_smoother_km"] > 0         # owner drives briskly (style ~0.62)
