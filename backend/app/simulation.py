"""Demo simulation: move the car along its active plan, consume energy, charge at stops.

Energy use comes from the battery core (trained range model) under the
*current* conditions, so changing AC/temperature mid-drive changes the outcome.
"""
from __future__ import annotations

from datetime import datetime

from app.battery_core.range_model import usable_kwh
from app.config import HARD_MIN_SOC, RESERVE_SOC, VEHICLE


def _record_charge(ctx, charger: dict, soc_from: float, soc_to: float):
    usable = ctx.battery.usable_kwh()
    kwh = max(0.0, soc_to - soc_from) * usable / 0.92
    now = datetime.now()
    ctx.state.live_sessions.append({
        "session_id": f"L{len(ctx.state.live_sessions) + 1:03d}",
        "start_ts": now.isoformat(timespec="minutes"), "end_ts": now.isoformat(timespec="minutes"),
        "charger_id": charger["id"], "charger_name": charger["name"], "charger_type": charger["kind"],
        "power_kw": charger["power_kw"], "soc_start": round(soc_from, 3), "soc_end": round(soc_to, 3),
        "kwh": round(kwh, 2), "cost_inr": round(kwh * charger["price_per_kwh"], 1),
        "location": charger["node"], "battery_temp_max_c": round(ctx.state.ambient_temp_c + 8, 1),
    })


def charge_now(ctx, target_soc: float) -> dict:
    st = ctx.state
    chargers = ctx.net.chargers_at(st.location)
    if not chargers:
        return {"ok": False, "reason": f"No charger at {ctx.net.name(st.location)}."}
    ch = max(chargers, key=lambda c: c["power_kw"])
    before = st.soc
    target = max(before, min(1.0, target_soc))
    _record_charge(ctx, ch, before, target)
    st.soc = target
    st.log("charge", f"Charged at {ch['name']}: {before:.0%} → {target:.0%}")
    return {"ok": True, "charger": ch["name"], "from": before, "to": target}


def drive(ctx, km: float) -> list[str]:
    """Advance the simulated car by `km`. Returns human-readable events."""
    st, net, bat = ctx.state, ctx.net, ctx.battery
    cond = bat.conditions(st)
    usable = usable_kwh(cond["soh"])
    events: list[str] = []

    if not st.active_plan:
        whkm = bat.range_model.mixed_wh_per_km(cond, highway_share=0.0)
        st.soc = max(0.01, st.soc - whkm * km / 1000 / usable)
        st.odometer_km += km
        events.append(f"Drove {km:.0f} km around {net.name(st.location)}.")
        return events

    energy = bat.edge_energy_kwh(net, cond)
    plan, prog = st.active_plan, st.progress
    remaining = km
    while remaining > 1e-6 and st.active_plan:
        leg = plan["legs"][prog["leg"]]
        path = leg["path"]
        if prog["node"] >= len(path) - 1:          # end of this leg
            _finish_leg(ctx, leg, events)
            if not st.active_plan:
                break
            continue
        u, v = path[prog["node"]], path[prog["node"] + 1]
        e = net.edge(u, v)
        left = e["distance_km"] - prog.get("edge_km", 0.0)
        step = min(remaining, left)
        st.soc = max(0.0, st.soc - energy[(u, v)] * step / e["distance_km"] / usable)
        st.odometer_km += step
        st.trip_km += step
        remaining -= step
        prog["edge_km"] = prog.get("edge_km", 0.0) + step
        if prog["edge_km"] >= e["distance_km"] - 1e-6:
            prog["node"] += 1
            prog["edge_km"] = 0.0
            st.location = v
        if st.soc <= 0.01:
            events.append("Battery depleted - car stopped (this is what the guard exists to prevent).")
            break
    # finish a leg we landed exactly on
    if st.active_plan:
        leg = plan["legs"][prog["leg"]]
        if prog["node"] >= len(leg["path"]) - 1:
            _finish_leg(ctx, leg, events)
    return events


def _finish_leg(ctx, leg: dict, events: list[str]):
    st, net = ctx.state, ctx.net
    plan, prog = st.active_plan, st.progress
    if leg.get("ends_at_charger"):
        stop = next(s for s in plan["stops"] if s["node"] == leg["to"] and s.get("done") is not True)
        stop["done"] = True
        ch = net.chargers[stop["charger_id"]]
        before = st.soc
        target = max(before, stop["depart_soc"])
        _record_charge(ctx, ch, before, target)
        st.soc = target
        msg = f"Charged at {stop['name']}: {before:.0%} → {target:.0%} ({stop['charge_min']:.0f} min)."
        st.log("charge", msg)
        events.append(msg)
    else:
        name = net.name(leg["to"])
        prog["waypoints_done"] += 1
        msg = f"Arrived at {name} with {st.soc:.0%}."
        st.log("arrival", msg)
        events.append(msg)
    prog["leg"] += 1
    prog["node"] = 0
    prog["edge_km"] = 0.0
    if prog["leg"] >= len(plan["legs"]):
        st.active_plan = None
        st.progress = {"leg": 0, "node": 0, "waypoints_done": 0}
        st.trip_km = 0.0


def remaining_projection(ctx) -> dict | None:
    """Re-simulate the rest of the active plan with *current* SOC and conditions."""
    st, net, bat = ctx.state, ctx.net, ctx.battery
    if not st.active_plan:
        return None
    cond = bat.conditions(st)
    energy = bat.edge_energy_kwh(net, cond)
    usable = usable_kwh(cond["soh"])
    plan, prog = st.active_plan, st.progress
    soc, min_soc, km, at_risk = st.soc, st.soc, 0.0, False
    for li in range(prog["leg"], len(plan["legs"])):
        leg = plan["legs"][li]
        path = leg["path"]
        start = prog["node"] if li == prog["leg"] else 0
        for i in range(start, len(path) - 1):
            e = net.edge(path[i], path[i + 1])
            frac = 1.0 - (prog.get("edge_km", 0.0) / e["distance_km"] if (li == prog["leg"] and i == start) else 0.0)
            soc -= energy[(path[i], path[i + 1])] * frac / usable
            km += e["distance_km"] * frac
        min_soc = min(min_soc, soc)
        # Arriving at a planned charger only needs the hard floor; the destination needs the reserve
        floor = HARD_MIN_SOC if leg.get("ends_at_charger") else RESERVE_SOC
        at_risk = at_risk or soc < floor - 0.005
        if leg.get("ends_at_charger"):
            stop = next(s for s in plan["stops"] if s["node"] == leg["to"])
            soc = max(soc, stop["depart_soc"])
    return {"arrival_soc": round(soc, 3), "min_soc": round(min_soc, 3), "at_risk": at_risk,
            "remaining_km": round(km, 1),
            "destination": plan["destination_names"][-1]}


def home_projection(ctx) -> dict:
    """Could we get home right now without charging?"""
    st, net, bat = ctx.state, ctx.net, ctx.battery
    nodes, km, mins = net.shortest_path(st.location, ctx.home_node)
    cond = bat.conditions(st)
    energy = bat.edge_energy_kwh(net, cond)
    kwh = sum(energy[(u, v)] for u, v in zip(nodes, nodes[1:]))
    return {"distance_km": round(km, 1), "arrival_soc": round(st.soc - kwh / bat.usable_kwh(), 3)}
