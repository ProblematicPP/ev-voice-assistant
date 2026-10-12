"""Energy-aware route planner with automatic charging-stop selection.

Algorithm (per leg):
  1. Road graph: fastest path between any two nodes (Dijkstra on travel time).
  2. Energy: every directed edge gets a kWh cost from the trained range model
     under the *current* conditions (temperature, HVAC, driving style, SOH,
     gradient from node elevations).
  3. Charger graph: states are {origin, (charger, target SOC), destination}.
     A transition X->Y is allowed only if the SOC on arrival at Y stays above
     the safety floor. Cost = driving minutes + charging minutes at Y.
     Departure SOC from a charger is fixed by the state, so plain Dijkstra
     finds the time-optimal plan, including "no stop" when that's feasible.
  4. The last charging stop is trimmed to charge only as much as needed.
"""
from __future__ import annotations

import heapq
import itertools

from app.config import COMFORT_SOC, DC_TARGET_SOC, HARD_MIN_SOC, RESERVE_SOC, VEHICLE
from app.routing.network import RoadNetwork

STOP_OVERHEAD_MIN = 5.0
CHARGE_EFF = 0.92
TARGETS = (DC_TARGET_SOC, 1.0)


def charge_minutes(soc_from: float, soc_to: float, power_kw: float, usable: float) -> float:
    if soc_to <= soc_from:
        return 0.0
    to80 = max(0.0, min(soc_to, 0.8) - soc_from) * usable
    above = max(0.0, soc_to - max(soc_from, 0.8)) * usable
    return 60 * (to80 / power_kw + above / (power_kw * 0.35)) / CHARGE_EFF


class RoutePlanner:
    def __init__(self, network: RoadNetwork, battery):
        self.net = network
        self.battery = battery

    # -- helpers -------------------------------------------------------------
    def _effective_kw(self, ch: dict) -> float:
        cap = VEHICLE["max_dc_kw"] if ch["kind"] == "dc_fast" else VEHICLE["max_ac_kw"]
        return min(ch["power_kw"], cap)

    def path_profile(self, a: str, b: str, energy: dict) -> dict:
        nodes, km, mins = self.net.shortest_path(a, b)
        kwh = sum(energy[(u, v)] for u, v in zip(nodes, nodes[1:]))
        return {"nodes": list(nodes), "distance_km": km, "drive_min": mins, "energy_kwh": kwh}

    # -- single leg ----------------------------------------------------------
    def plan_leg(self, origin: str, dest: str, soc0: float, cond: dict,
                 min_arrival: float = RESERVE_SOC, exclude: set[str] = frozenset()):
        energy = self.battery.edge_energy_kwh(self.net.edges, self.net.elev, cond)
        usable = self.battery.usable_kwh()
        chargers = [c for c in self.net.chargers.values() if c["available"] and c["id"] not in exclude]

        start, goal = ("O", None), ("D", None)
        states = [start, goal] + [(c["id"], t) for c in chargers for t in TARGETS]
        node_of = lambda s: origin if s == start else dest if s == goal else self.net.chargers[s[0]]["node"]
        dep_soc = lambda s: soc0 if s == start else s[1]

        best = {start: 0.0}
        back: dict = {}
        tie = itertools.count()
        pq = [(0.0, next(tie), start)]
        done = set()
        while pq:
            t, _, s = heapq.heappop(pq)
            if s in done:
                continue
            done.add(s)
            if s == goal:
                break
            for y in states:
                if y in done or y == start or y == s:
                    continue
                prof = self.path_profile(node_of(s), node_of(y), energy)
                arr = dep_soc(s) - prof["energy_kwh"] / usable
                if y == goal:
                    if arr < min_arrival:
                        continue
                    step = prof["drive_min"]
                    extra = None
                else:
                    if arr < HARD_MIN_SOC or arr > y[1] - 0.1:
                        continue
                    ch = self.net.chargers[y[0]]
                    cmin = charge_minutes(arr, y[1], self._effective_kw(ch), usable)
                    step = prof["drive_min"] + cmin + STOP_OVERHEAD_MIN
                    extra = (arr, cmin)
                nt = t + step
                if nt < best.get(y, float("inf")):
                    best[y] = nt
                    back[y] = (s, prof, arr, extra)
                    heapq.heappush(pq, (nt, next(tie), y))

        if goal not in back:
            return None

        # Reconstruct
        seq, s = [], goal
        while s != start:
            prev, prof, arr, extra = back[s]
            seq.append((prev, s, prof, arr, extra))
            s = prev
        seq.reverse()

        legs, stops, soc = [], [], soc0
        for prev, s, prof, arr, extra in seq:
            legs.append({
                "from": node_of(prev), "to": node_of(s), "path": prof["nodes"],
                "distance_km": round(prof["distance_km"], 1), "drive_min": round(prof["drive_min"], 1),
                "energy_kwh": round(prof["energy_kwh"], 2),
                "soc_depart": round(soc, 3), "soc_arrive": round(arr, 3),
                "ends_at_charger": s != goal,
            })
            if s != goal:
                ch = self.net.chargers[s[0]]
                stops.append({"charger_id": ch["id"], "name": ch["name"], "node": ch["node"],
                              "power_kw": self._effective_kw(ch), "price_per_kwh": ch["price_per_kwh"],
                              "arrive_soc": round(arr, 3), "depart_soc": s[1]})
                soc = s[1]

        if stops:  # charge only what the final stretch needs (+ comfort margin)
            last = stops[-1]
            need = legs[-1]["energy_kwh"] / usable + max(min_arrival, COMFORT_SOC)
            last["depart_soc"] = round(min(last["depart_soc"], max(last["arrive_soc"] + 0.05, need)), 3)
            legs[-1]["soc_depart"] = last["depart_soc"]
            legs[-1]["soc_arrive"] = round(last["depart_soc"] - legs[-1]["energy_kwh"] / usable, 3)
        for st in stops:
            kwh = (st["depart_soc"] - st["arrive_soc"]) * usable / CHARGE_EFF
            st["charge_kwh"] = round(kwh, 2)
            st["charge_min"] = round(charge_minutes(st["arrive_soc"], st["depart_soc"], st["power_kw"], usable)
                                     + STOP_OVERHEAD_MIN, 1)
            st["cost_inr"] = round(kwh * st["price_per_kwh"], 0)
        return {"legs": legs, "stops": stops}

    # -- multi-waypoint plan --------------------------------------------------
    def plan(self, origin: str, destinations: list[str], soc: float, cond: dict,
             min_final_soc: float = RESERVE_SOC, exclude: set[str] = frozenset()) -> dict:
        usable = self.battery.usable_kwh()
        energy = self.battery.edge_energy_kwh(self.net.edges, self.net.elev, cond)
        all_legs, all_stops, cur, cur_soc = [], [], origin, soc
        for i, dest in enumerate(destinations):
            final = i == len(destinations) - 1
            min_arr = min_final_soc
            if not final:
                # Arrive at a waypoint with enough to reach a charger afterwards
                ch = self.net.nearest_charger(dest, fast_only=True)
                if ch:
                    p = self.path_profile(dest, ch["node"], energy)
                    min_arr = max(RESERVE_SOC, p["energy_kwh"] / usable + HARD_MIN_SOC)
            leg = self.plan_leg(cur, dest, cur_soc, cond, min_arr, exclude)
            if leg is None:
                return self._infeasible(origin, destinations, soc, cond, failed_at=dest, legs=all_legs)
            for lg in leg["legs"]:
                lg["waypoint_index"] = i
            all_legs += leg["legs"]
            all_stops += leg["stops"]
            cur, cur_soc = dest, leg["legs"][-1]["soc_arrive"]
        return self._summarize(origin, destinations, soc, all_legs, all_stops)

    def _summarize(self, origin, destinations, soc, legs, stops) -> dict:
        drive = sum(l["drive_min"] for l in legs)
        charge = sum(s["charge_min"] for s in stops)
        route_nodes = [legs[0]["from"]]
        for l in legs:
            route_nodes += l["path"][1:]
        return {
            "status": "needs_charging" if stops else "direct",
            "origin": origin,
            "destinations": destinations,
            "destination_names": [self.net.name(d) for d in destinations],
            "legs": legs,
            "stops": stops,
            "route_nodes": route_nodes,
            "totals": {
                "distance_km": round(sum(l["distance_km"] for l in legs), 1),
                "drive_min": round(drive, 0),
                "charge_min": round(charge, 0),
                "total_min": round(drive + charge, 0),
                "energy_kwh": round(sum(l["energy_kwh"] for l in legs), 2),
                "charging_cost_inr": round(sum(s["cost_inr"] for s in stops), 0),
                "start_soc": round(soc, 3),
                "arrival_soc": legs[-1]["soc_arrive"],
            },
        }

    def _infeasible(self, origin, destinations, soc, cond, failed_at, legs) -> dict:
        energy = self.battery.edge_energy_kwh(self.net.edges, self.net.elev, cond)
        usable = self.battery.usable_kwh()
        reachable = []
        for c in self.net.chargers.values():
            p = self.path_profile(origin, c["node"], energy)
            arr = soc - p["energy_kwh"] / usable
            if arr >= HARD_MIN_SOC - 0.02:
                reachable.append((p["drive_min"], c, round(arr, 3), round(p["distance_km"], 1)))
        reachable.sort(key=lambda r: r[0])
        return {
            "status": "infeasible",
            "origin": origin,
            "destinations": destinations,
            "destination_names": [self.net.name(d) for d in destinations],
            "failed_at": failed_at,
            "legs": legs,
            "stops": [],
            "route_nodes": [origin],
            "reachable_chargers": [
                {"charger_id": c["id"], "name": c["name"], "node": c["node"], "arrive_soc": a,
                 "distance_km": km} for _, c, a, km in reachable[:3]
            ],
            "totals": {"start_soc": round(soc, 3)},
        }

    def alternative_note(self, origin, destinations, soc, cond, plan) -> str | None:
        """Why this charger? Compare against the best plan that avoids it."""
        if not plan.get("stops"):
            return None
        first = plan["stops"][0]
        alt = self.plan(origin, destinations, soc, cond, exclude={first["charger_id"]})
        if alt["status"] == "infeasible":
            return f"{first['name']} is the only charger that makes this trip work."
        diff = alt["totals"]["total_min"] - plan["totals"]["total_min"]
        alt_name = alt["stops"][0]["name"] if alt["stops"] else "no stop"
        if diff >= 1:
            return f"Picked {first['name']} ({first['power_kw']:.0f} kW): {diff:.0f} min faster than via {alt_name}."
        return f"Picked {first['name']} ({first['power_kw']:.0f} kW); {alt_name} is similar."
