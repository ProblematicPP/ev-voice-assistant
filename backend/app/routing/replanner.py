"""Mid-drive re-planning: add a detour / change destination from where the car is now."""
from __future__ import annotations

from app.routing.planner import RoutePlanner


def remaining_destinations(state) -> list[str]:
    plan = state.active_plan
    if not plan:
        return []
    done = state.progress.get("waypoints_done", 0)
    return plan["destinations"][done:]


def replan_with_stop(planner: RoutePlanner, state, cond: dict, stop_node: str) -> tuple[dict, dict | None]:
    """Insert `stop_node` before the final destination and re-plan from the current position."""
    old = state.active_plan
    remaining = remaining_destinations(state)
    dests = remaining[:-1] + [stop_node] + remaining[-1:] if remaining else [stop_node]
    new = planner.plan(state.location, dests, state.soc, cond)
    return new, _diff(old, new)


def replan_destination(planner: RoutePlanner, state, cond: dict, dest_node: str) -> tuple[dict, dict | None]:
    old = state.active_plan
    new = planner.plan(state.location, [dest_node], state.soc, cond)
    return new, _diff(old, new)


def _diff(old: dict | None, new: dict) -> dict | None:
    if not old or new["status"] == "infeasible" or "total_min" not in old.get("totals", {}):
        return None
    old_stops = {s["charger_id"] for s in old["stops"]}
    new_stops = {s["charger_id"] for s in new["stops"]}
    return {
        "added_charging_stops": [s["name"] for s in new["stops"] if s["charger_id"] not in old_stops],
        "removed_charging_stops": [s["name"] for s in old["stops"] if s["charger_id"] not in new_stops],
        "arrival_soc_before": old["totals"]["arrival_soc"],
        "arrival_soc_after": new["totals"]["arrival_soc"],
    }
