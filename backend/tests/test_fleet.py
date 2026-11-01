"""Fleet module: battery-aware allocation, demand, rebalancing, longevity - all on the shared core."""
import ast
from pathlib import Path

import pandas as pd
import pytest

from app.assistant import fallback_parser
from app.context import AppContext

APP = Path(__file__).resolve().parent.parent / "app"


@pytest.fixture(scope="module")
def ctx():
    return AppContext()


@pytest.fixture(scope="module")
def fleet(ctx):
    return ctx.fleet()


def test_only_the_core_owns_soh_and_ageing_logic():
    """No consumer may import the SOH model, ageing physics or degradation maths directly."""
    private = {"app.battery_core.soh_model", "app.battery_core.ageing", "app.battery_core.degradation"}
    offenders = []
    for py in APP.rglob("*.py"):
        if "battery_core" in py.parts:
            continue
        for node in ast.walk(ast.parse(py.read_text(encoding="utf-8"))):
            mod = node.module if isinstance(node, ast.ImportFrom) else None
            if mod in private:
                offenders.append(f"{py.relative_to(APP)} imports {mod}")
    assert not offenders, offenders


def test_vehicle_soh_comes_from_core(fleet, ctx):
    from app.config import DATA_DIR
    bms = pd.read_csv(DATA_DIR / "fleet_bms.csv")
    one = fleet.vehicles.iloc[0]
    assert one.soh == pytest.approx(ctx.battery.estimate_soh(bms[bms.vehicle_id == one.vehicle_id]))


def test_health_aware_gives_long_haul_the_healthiest_packs(fleet):
    a = [x for x in fleet.allocate(fleet.bookings, "health_aware") if x["vehicle_id"]]
    long = [x["soh"] for x in a if x["kind"] == "long_haul"]
    urban = [x["soh"] for x in a if x["kind"] == "urban"]
    assert min(long) > max(urban)
    today = fleet.allocation_today()
    assert today["health_aware"]["fast_charges"] <= today["first_available"]["fast_charges"]


def test_long_rental_uses_shared_planner_with_vehicle_soh(fleet):
    long_ids = fleet.bookings[fleet.bookings.kind == "long_haul"].booking_id
    plans = [fleet.plan_rental(b) for b in long_ids]
    assert all(p["plan"]["status"] != "infeasible" for p in plans)
    assert any(p["plan"]["stops"] for p in plans)                 # some round trips need a charge


def test_demand_forecast_follows_rush_hours(fleet):
    g = fleet.demand.forecast(pd.Timestamp("2026-11-03 00:00"), 24, temp_c=26)    # a Tuesday
    by_hour = g.groupby("hour").bookings.sum()
    assert (g.bookings >= 0).all()
    assert by_hour[9] > 2 * by_hour[3] and by_hour[18] > 2 * by_hour[3]


def test_expected_lost_rentals():
    from app.fleet import FleetManager
    assert FleetManager.expected_lost(2.0, 0) == pytest.approx(2.0)
    assert FleetManager.expected_lost(2.0, 3) < FleetManager.expected_lost(2.0, 1) < 2.0


def test_rebalancing_reduces_lost_rentals(fleet):
    r = fleet.rebalance(start=pd.Timestamp("2026-11-03 08:00"))
    assert r["moves"] and r["expected_lost_after"] < r["expected_lost_before"]


def test_health_aware_allocation_extends_battery_life(ctx):
    L = ctx.fleet_longevity()
    h, n = L["health_aware"], L["first_available"]
    assert h["capacity_lost_pct_points"] < n["capacity_lost_pct_points"]
    assert L["battery_life_extension_pct"] > 0 and L["fast_charges_avoided"] > 0


def test_volt_routes_fleet_questions():
    assert fallback_parser.parse("which cars should I move in the fleet?")[0] == "get_fleet_status"
