"""Weather / traffic / charger-availability providers and how the planner uses them."""
from datetime import datetime

import pytest

from app.inputs import Inputs, LiveWeather, SimulatedStations, SimulatedTraffic
from app.routing.planner import RoutePlanner

NIGHT, RUSH = datetime(2026, 11, 2, 2, 0), datetime(2026, 11, 2, 18, 30)


@pytest.fixture(scope="module")
def ctx():
    from app.context import AppContext
    return AppContext()


def planner(ctx, **kw):
    return RoutePlanner(ctx.net, ctx.battery, Inputs(**kw))


def mysuru(ctx, p, soc=0.46):
    return p.plan(ctx.home_node, [ctx.net.place_node("mysuru")], soc, ctx.battery.conditions(ctx.state))


class NoQueue(SimulatedStations):
    def status(self, charger, when):
        return {"available": charger["available"], "wait_min": 0.0}


def test_rush_hour_traffic_lengthens_eta_not_route(ctx):
    # Queues vary by hour and can change the charger choice; hold them fixed to isolate traffic
    night = mysuru(ctx, planner(ctx, clock=lambda: NIGHT, stations=NoQueue()))
    rush = mysuru(ctx, planner(ctx, clock=lambda: RUSH, stations=NoQueue()))
    assert rush["totals"]["traffic_delay_min"] > night["totals"]["traffic_delay_min"] == 0
    assert rush["totals"]["total_min"] > night["totals"]["total_min"]
    assert rush["totals"]["distance_km"] == night["totals"]["distance_km"]


def test_queue_wait_is_part_of_trip_time(ctx):
    p = mysuru(ctx, planner(ctx, clock=lambda: RUSH))
    t = p["totals"]
    assert all("wait_min" in s for s in p["stops"])
    parts = t["drive_min"] + t["traffic_delay_min"] + t["charge_min"] + t["wait_min"]
    assert abs(t["total_min"] - parts) <= 2          # each part is rounded on its own


def test_out_of_service_charger_is_avoided(ctx):
    first = mysuru(ctx, planner(ctx, clock=lambda: NIGHT))["stops"][0]["charger_id"]

    class Broken(SimulatedStations):
        def status(self, charger, when):
            return {"available": False, "wait_min": 0.0} if charger["id"] == first else super().status(charger, when)

    p = mysuru(ctx, planner(ctx, clock=lambda: NIGHT, stations=Broken()))
    assert p["stops"] and first not in {s["charger_id"] for s in p["stops"]}


def test_traffic_and_stations_are_deterministic():
    t, s = SimulatedTraffic(), SimulatedStations()
    assert t.factor(RUSH, urban=True) > t.factor(RUSH, urban=False) > 1.0 == t.factor(NIGHT, urban=True)
    ch = {"id": "x", "kind": "dc_fast"}
    assert s.status(ch, RUSH) == s.status(ch, RUSH)


def test_live_weather_falls_back_offline(monkeypatch):
    import httpx

    def down(*a, **k):
        raise httpx.ConnectError("offline")
    monkeypatch.setattr(httpx, "get", down)
    w = LiveWeather().current(12.97, 77.59, fallback_temp_c=31.0)
    assert w["temp_c"] == 31.0 and w["source"] == "simulated" and w["error"] == "offline"
