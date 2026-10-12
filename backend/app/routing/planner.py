"""Energy-aware route planner with automatic charging-stop selection (real OSM roads).

Algorithm (per leg):
  1. Roads: fastest paths via scipy Dijkstra over the OSM graph (cached trees).
  2. Energy: every edge gets a kWh cost from the trained range model under the
     *current* conditions (temperature, HVAC, driving style, SOH, speed, road type).
  3. Charger search: states are {origin, (charger, target SOC), destination}.
     A* over these states with lazy expansion - a road-graph search is only run
     from a state when it is popped. A transition is allowed only if the SOC on
     arrival stays above the safety floor. Cost = driving minutes + charging minutes.
     Only chargers inside a corridor around origin->destination are considered.
  4. The last charging stop is trimmed to charge only as much as needed.
"""
from __future__ import annotations

import heapq
import itertools

import numpy as np

from app.config import COMFORT_SOC, DC_TARGET_SOC, HARD_MIN_SOC, RESERVE_SOC, VEHICLE
from app.routing.network import RoadNetwork, hav_km

STOP_OVERHEAD_MIN = 5.0
CHARGE_EFF = 0.92
TARGETS = (DC_TARGET_SOC, 1.0)
MAX_ROAD_KMH = 90.0           # upper bound on edge speed -> admissible A* heuristic
CORRIDOR_DETOUR = 1.35
MAX_CANDIDATES = 120


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

    def _walk(self, src: int, dst: int, pred, energy) -> dict:
        nodes = self.net.path_from_tree(src, dst, pred)
        ids = [self.net.eid[(u, v)] for u, v in zip(nodes, nodes[1:])]
        return {"nodes": nodes, "distance_km": float(self.net.ekm[ids].sum()) if ids else 0.0,
                "drive_min": float(self.net.emin[ids].sum()) if ids else 0.0,
                "energy_kwh": float(energy.kwh[ids].sum()) if ids else 0.0}

    def path_profile(self, a: int, b: int, energy) -> dict:
        dist, pred = self.net.tree(a)
        if not np.isfinite(dist[b]):
            raise ValueError(f"no road path {a}->{b}")
        return self._walk(a, b, pred, energy)

    def _corridor(self, origin: int, dest: int, exclude) -> list[dict]:
        net = self.net
        oa, ob = net.coords(origin), net.coords(dest)
        direct = float(hav_km(*oa, *ob))
        out = []
        for c in net.chargers.values():
            if not c["available"] or c["id"] in exclude:
                continue
            ca = net.coords(c["node"])
            detour = float(hav_km(*oa, *ca) + hav_km(*ca, *ob))
            if detour <= CORRIDOR_DETOUR * direct + 25:
                out.append((detour, c))
        out.sort(key=lambda x: x[0])
        return [c for _, c in out[:MAX_CANDIDATES]]

    # -- single leg ----------------------------------------------------------
    def plan_leg(self, origin: int, dest: int, soc0: float, cond: dict,
                 min_arrival: float = RESERVE_SOC, exclude=frozenset()):
        net = self.net
        energy = self.battery.edge_energy_kwh(net, cond)
        usable = self.battery.usable_kwh()
        chargers = self._corridor(origin, dest, exclude)
        dest_ll = net.coords(dest)

        start, goal = ("O", None), ("D", None)
        states = [goal] + [(c["id"], t) for c in chargers for t in TARGETS]
        node_of = lambda s: origin if s == start else dest if s == goal else net.chargers[s[0]]["node"]
        dep_soc = lambda s: soc0 if s == start else s[1]
        h = lambda s: float(hav_km(*net.coords(node_of(s)), *dest_ll)) / MAX_ROAD_KMH * 60

        best = {start: 0.0}
        back: dict = {}
        tie = itertools.count()
        pq = [(h(start), next(tie), start)]
        done = set()
        while pq:
            _, _, s = heapq.heappop(pq)
            if s in done:
                continue
            done.add(s)
            if s == goal:
                break
            g = best[s]
            src = node_of(s)
            dist, pred = net.tree(src)
            budget = (dep_soc(s) - HARD_MIN_SOC) * usable
            for y in states:
                if y in done or y == s:
                    continue
                ny = node_of(y)
                if not np.isfinite(dist[ny]):
                    continue
                prof = self._walk(src, ny, pred, energy)
                if prof["energy_kwh"] > budget + 1e-9:
                    continue
                arr = dep_soc(s) - prof["energy_kwh"] / usable
                if y == goal:
                    if arr < min_arrival:
                        continue
                    step, extra = prof["drive_min"], None
                else:
                    if arr > y[1] - 0.1:
                        continue
                    ch = net.chargers[y[0]]
                    cmin = charge_minutes(arr, y[1], self._effective_kw(ch), usable)
                    step, extra = prof["drive_min"] + cmin + STOP_OVERHEAD_MIN, (arr, cmin)
                nt = g + step
                if nt < best.get(y, float("inf")):
                    best[y] = nt
                    back[y] = (s, prof, arr, extra)
                    heapq.heappush(pq, (nt + h(y), next(tie), y))

        if goal not in back:
            return None

        seq, s = [], goal
        while s != start:
            prev, prof, arr, extra = back[s]
            seq.append((prev, s, prof, arr, extra))
            s = prev
        seq.reverse()

        legs, stops, soc = [], [], soc0
        for prev, s, prof, arr, extra in seq:
            legs.append({
                "from": node_of(prev), "to": node_of(s), "to_name": net.name(node_of(s)), "path": prof["nodes"],
                "distance_km": round(prof["distance_km"], 1), "drive_min": round(prof["drive_min"], 1),
                "energy_kwh": round(prof["energy_kwh"], 2),
                "soc_depart": round(soc, 3), "soc_arrive": round(arr, 3),
                "ends_at_charger": s != goal,
            })
            if s != goal:
                ch = net.chargers[s[0]]
                stops.append({"charger_id": ch["id"], "name": ch["name"], "node": ch["node"],
                              "lat": ch["lat"], "lon": ch["lon"],
                              "power_kw": self._effective_kw(ch), "price_per_kwh": ch["price_per_kwh"],
                              "synthetic_fields": ch.get("synthetic_fields", []),
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
    def plan(self, origin: int, destinations: list[int], soc: float, cond: dict,
             min_final_soc: float = RESERVE_SOC, exclude=frozenset()) -> dict:
        usable = self.battery.usable_kwh()
        energy = self.battery.edge_energy_kwh(self.net, cond)
        all_legs, all_stops, cur, cur_soc = [], [], origin, soc
        for i, dest in enumerate(destinations):
            final = i == len(destinations) - 1
            min_arr = min_final_soc
            if not final:
                # Arrive at a waypoint with enough to reach a fast charger afterwards
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
            "origin_name": self.net.name(origin),
            "destinations": destinations,
            "destination_names": [self.net.name(d) for d in destinations],
            "legs": legs,
            "stops": stops,
            "route_nodes": route_nodes,
            "polyline": self.net.polyline(route_nodes),
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
        energy = self.battery.edge_energy_kwh(self.net, cond)
        usable = self.battery.usable_kwh()
        dist, pred = self.net.tree(origin)
        reachable = []
        for c in self.net.chargers.values():
            if c["kind"] == "home_ac" or not np.isfinite(dist[c["node"]]):
                continue
            p = self._walk(origin, c["node"], pred, energy)
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
            "polyline": [],
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
