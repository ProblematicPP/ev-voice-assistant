"""Fleet management: the fourth consumer of the shared battery-intelligence core.

  * battery-aware allocation  healthy packs take long-haul rentals, worn packs take short urban loops
  * demand heatmap            PyTorch forecast of bookings per zone and hour (app/fleet/demand.py)
  * long-rental planning      the same charging-aware route planner the driver app uses
  * rebalancing               which idle cars to move where, and the lost rentals that saves
  * longevity                 one simulated year of allocations: health-aware vs first-available

Every SOH, range, ageing-stress and remaining-life number comes from BatteryCore.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy.stats import poisson

from app.battery_core.range_model import usable_kwh
from app.config import DATA_DIR
from app.fleet.demand import ZONES, DemandModel

DEPOT_SOC, RESERVE, FAST_FROM, FAST_TO = 0.90, 0.15, 0.15, 0.80
LONG_HAUL_SHARE = 0.85            # highway share of a long-haul rental
MIN_IDLE_SOC = 0.30               # below this an idle car must charge before it can be rented


class FleetManager:
    def __init__(self, ctx):
        self.ctx, self.core = ctx, ctx.battery
        self.vehicles = pd.read_csv(DATA_DIR / "fleet_vehicles.csv")
        bms = pd.read_csv(DATA_DIR / "fleet_bms.csv")
        self.vehicles["soh"] = [self.core.estimate_soh(bms[bms.vehicle_id == v]) for v in self.vehicles.vehicle_id]
        self.bookings = pd.read_csv(DATA_DIR / "fleet_bookings.csv")
        self.demand = DemandModel()
        self._whkm: dict = {}

    # -- battery numbers, all through the core -------------------------------------------
    def wh_per_km(self, soh: float, highway_share: float) -> float:
        key = (round(soh, 2), highway_share)
        if key not in self._whkm:
            cond = {**self.core.conditions(self.ctx.state), "soh": key[0]}
            self._whkm[key] = self.core.range_model.mixed_wh_per_km(cond, highway_share)
        return self._whkm[key]

    def range_km(self, soc: float, soh: float, highway_share: float = 0.0) -> float:
        return usable_kwh(soh) * soc * 1000 / self.wh_per_km(soh, highway_share)

    def rental_cost(self, soh: float, km: float, kind: str) -> dict:
        """Fast charges needed and ageing stress for one rental starting from a depot charge."""
        share = LONG_HAUL_SHARE if kind == "long_haul" else 0.0
        depth = km * self.wh_per_km(soh, share) / 1000 / usable_kwh(soh)      # fraction of usable capacity
        first = DEPOT_SOC - RESERVE
        n_fast = 0 if depth <= first else math.ceil((depth - first) / (FAST_TO - FAST_FROM))
        last = depth - n_fast * (FAST_TO - FAST_FROM)                        # slow depot recharge afterwards
        stress = n_fast * self.core.trip_stress(FAST_TO - FAST_FROM, fast=True) + self.core.trip_stress(last)
        return {"fast_charges": n_fast, "depth": round(depth, 3), "stress": stress}

    # -- overview ------------------------------------------------------------------------------
    def overview(self) -> dict:
        rows = []
        for v in self.vehicles.itertuples():
            rul = self.core.rul(v.fast_charge_share, soh_now=v.soh, cum_stress=v.cum_stress)
            rows.append({"vehicle_id": v.vehicle_id, "zone": v.zone, "zone_name": self.ctx.net.places[v.zone]["name"],
                         "status": v.status, "soc": v.soc,
                         "soh": round(v.soh, 3), "range_km": round(self.range_km(v.soc, v.soh)),
                         "years_to_70pct": rul["years"], "fast_charge_share": v.fast_charge_share,
                         "band": "healthy" if v.soh >= 0.85 else "worn" if v.soh >= 0.75 else "near end of life"})
        df = pd.DataFrame(rows)
        return {"vehicles": rows, "count": len(rows), "avg_soh": round(float(df.soh.mean()), 3),
                "idle": int((df.status == "idle").sum()),
                "bands": df.band.value_counts().to_dict()}

    # -- allocation ----------------------------------------------------------------------------
    def allocate(self, bookings: pd.DataFrame, policy: str = "health_aware", available=None, seed: int = 0) -> list[dict]:
        """Assign one vehicle per booking. available: vehicle_id -> soh (defaults to idle cars)."""
        if available is None:
            idle = self.vehicles[self.vehicles.status == "idle"]
            available = dict(zip(idle.vehicle_id, idle.soh))
        free = dict(available)
        if policy == "health_aware":
            # Longest rentals pick first and take the healthiest pack; short urban loops get the most worn
            order = bookings.sort_values(["kind", "km"], ascending=[True, False])     # "long_haul" < "urban"
        else:
            # Baseline: bookings in arrival order, each gets whichever car is first in the queue
            order = bookings
        rng = np.random.default_rng(seed)
        queue = list(rng.permutation(list(free))) if policy != "health_aware" else None
        out = []
        for b in order.itertuples():
            if not free:
                out.append({"booking_id": b.booking_id, "vehicle_id": None, "reason": "no idle vehicle"})
                continue
            if policy == "health_aware":
                pick = (max if b.kind == "long_haul" else min)(free, key=free.get)
            else:
                pick = next(v for v in queue if v in free)
            soh = free.pop(pick)
            cost = self.rental_cost(soh, b.km, b.kind)
            out.append({"booking_id": b.booking_id, "kind": b.kind, "km": b.km, "zone": b.zone,
                        "destination": b.destination if isinstance(b.destination, str) else None,
                        "vehicle_id": pick, "soh": round(soh, 3), **cost})
        return out

    def allocation_today(self) -> dict:
        res = {}
        for policy in ("health_aware", "first_available"):
            a = self.allocate(self.bookings, policy)
            res[policy] = {"assignments": a, "fast_charges": sum(x.get("fast_charges", 0) for x in a),
                           "stress": round(sum(x.get("stress", 0) for x in a), 2)}
        return res

    # -- long rentals use the shared planner ------------------------------------------------
    def plan_rental(self, booking_id: str) -> dict:
        b = self.bookings.set_index("booking_id").loc[booking_id]
        a = next(x for x in self.allocate(self.bookings) if x["booking_id"] == booking_id)
        if a["vehicle_id"] is None or not isinstance(b.destination, str):
            return {"booking_id": booking_id, "assignment": a, "plan": None}
        net = self.ctx.net
        cond = {**self.core.conditions(self.ctx.state), "soh": a["soh"]}
        home = net.place_node(b.zone)            # rentals come back to their zone: plan the round trip
        plan = self.ctx.planner.plan(home, [net.place_node(b.destination), home], DEPOT_SOC, cond)
        return {"booking_id": booking_id, "assignment": a, "plan": plan}

    # -- demand + rebalancing -----------------------------------------------------------------
    def heatmap(self, hours: int = 24, start: pd.Timestamp | None = None, rain_mm: float = 0.0) -> dict:
        start = start or pd.Timestamp(self.ctx.inputs.clock())
        g = self.demand.forecast(start, hours, self.ctx.state.ambient_temp_c, rain_mm)
        pivot = g.pivot_table(index="zone", columns="time", values="bookings").reindex(ZONES)
        return {"zones": ZONES, "names": [self.ctx.net.places[z]["name"] for z in ZONES],
                "hours": [t.strftime("%H:%M") for t in pivot.columns], "values": np.round(pivot.to_numpy(), 2).tolist(),
                "model": self.demand.metrics}

    @staticmethod
    def expected_lost(lam: float, supply: int) -> float:
        """E[max(0, demand - supply)] for Poisson demand: rentals turned away for lack of a car."""
        d = np.arange(supply + 1)
        return float(lam - supply + np.sum((supply - d) * poisson.pmf(d, lam)))

    def rebalance(self, horizon_h: int = 3, max_moves: int = 8, start: pd.Timestamp | None = None) -> dict:
        g = self.demand.forecast(start or pd.Timestamp(self.ctx.inputs.clock()), horizon_h, self.ctx.state.ambient_temp_c)
        lam = g.groupby("zone").bookings.sum().reindex(ZONES).fillna(0.0).to_dict()
        idle = self.vehicles[(self.vehicles.status == "idle") & (self.vehicles.soc >= MIN_IDLE_SOC)]
        supply = idle.zone.value_counts().reindex(ZONES).fillna(0).astype(int).to_dict()
        lost = lambda z, s: self.expected_lost(lam[z], s)
        before = sum(lost(z, supply[z]) for z in ZONES)
        net = self.ctx.net
        minutes = {z: net.tree(net.place_node(z))[0] for z in ZONES}
        moves = []
        for _ in range(max_moves):
            best = None
            for src in ZONES:
                if supply[src] == 0:
                    continue
                loss = lost(src, supply[src] - 1) - lost(src, supply[src])
                for dst in ZONES:
                    if dst == src:
                        continue
                    gain = lost(dst, supply[dst]) - lost(dst, supply[dst] + 1) - loss
                    drive = float(minutes[src][net.place_node(dst)])
                    score = gain - drive / 600            # small penalty: 10 min of driving ~ 0.017 rentals
                    if gain > 0.05 and (best is None or score > best[0]):
                        best = (score, src, dst, gain, drive)
            if best is None:
                break
            _, src, dst, gain, drive = best
            car = idle[(idle.zone == src) & ~idle.vehicle_id.isin([m["vehicle_id"] for m in moves])].iloc[0]
            supply[src] -= 1
            supply[dst] += 1
            moves.append({"vehicle_id": car.vehicle_id, "from": src, "to": dst, "drive_min": round(drive),
                          "from_name": net.places[src]["name"], "to_name": net.places[dst]["name"],
                          "lost_rentals_saved": round(gain, 2)})
        after = sum(lost(z, supply[z]) for z in ZONES)
        return {"horizon_h": horizon_h, "moves": moves, "expected_lost_before": round(before, 2),
                "expected_lost_after": round(after, 2),
                "reduction_pct": round(100 * (before - after) / before, 1) if before else 0.0,
                "demand_by_zone": {z: round(v, 2) for z, v in lam.items()}}

    # -- longevity: one simulated year -------------------------------------------------------
    def longevity(self, days: int = 365, bookings_per_day: float = 28.0, seed: int = 7) -> dict:
        rng = np.random.default_rng(seed)
        ids = list(self.vehicles.vehicle_id)
        soh0 = dict(zip(ids, self.vehicles.soh))
        cum0 = dict(zip(ids, self.vehicles.cum_stress))
        habit = dict(zip(ids, self.vehicles.fast_charge_share))
        result = {}
        days_bookings = []
        for _ in range(days):
            n = min(len(ids), int(rng.poisson(bookings_per_day)))
            long = rng.random(n) < 0.3
            days_bookings.append(pd.DataFrame({
                "booking_id": [f"D{i}" for i in range(n)], "zone": "koramangala", "destination": None,
                "kind": np.where(long, "long_haul", "urban"),
                "km": np.where(long, rng.uniform(140, 320, n), rng.uniform(12, 70, n)).round()}))
        start_soh = float(np.mean(list(soh0.values())))
        for policy in ("health_aware", "first_available"):
            added = dict.fromkeys(ids, 0.0)
            fast = 0
            for d, bk in enumerate(days_bookings):
                avail = {v: self.core.soh_after(soh0[v], cum0[v], added[v]) for v in ids}
                for a in self.allocate(bk, policy, available=avail, seed=d):
                    if a["vehicle_id"]:
                        added[a["vehicle_id"]] += a["stress"]
                        fast += a["fast_charges"]
            end = {v: self.core.soh_after(soh0[v], cum0[v], added[v]) for v in ids}
            rul = {v: self.core.rul(habit[v], soh_now=end[v], cum_stress=cum0[v] + added[v])["years"] for v in ids}
            avg_end = float(np.mean(list(end.values())))
            result[policy] = {"avg_soh_end": round(avg_end, 4),
                              "capacity_lost_pct_points": round(100 * (start_soh - avg_end), 2),
                              "min_soh_end": round(float(min(end.values())), 4),
                              "below_70pct": int(sum(s <= 0.70 for s in end.values())),
                              "avg_years_to_70pct": round(float(np.mean(list(rul.values()))), 2),
                              "fast_charges": fast}
        h, n = result["health_aware"], result["first_available"]
        # Packs age more slowly under health-aware allocation; at that rate they take this much longer
        # to lose the same capacity. (Average years-to-70% is also reported, but it is dominated by each
        # pack's own charging habit and counts packs already past 70% as zero.)
        result["battery_life_extension_pct"] = round(
            100 * (n["capacity_lost_pct_points"] / h["capacity_lost_pct_points"] - 1), 1)
        result["fast_charges_avoided"] = n["fast_charges"] - h["fast_charges"]
        result["days"] = days
        return result
