"""Battery-Intelligence Core: the single entry point other modules call into.

Everything that needs to know "how healthy is the battery" or "how far can we
go" goes through BatteryCore - the assistant, the route planner, the
companion app and the REST API.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from app.battery_core import attribution
from app.battery_core.range_model import RangeModel, usable_kwh
from app.battery_core.soh_model import SOHModel
from app.config import DATA_DIR


class BatteryCore:
    def __init__(self):
        self.profile = json.loads((DATA_DIR / "vehicle_profile.json").read_text())
        self.bms = pd.read_csv(DATA_DIR / "vehicle_bms_history.csv")
        self.soh_model = SOHModel()
        self.range_model = RangeModel()
        self.soh_now = self.soh_model.current(self.bms)
        self._soh_trend = self.soh_model.trend(self.bms)
        self._edge_cache: dict = {}

    # -- SOH ------------------------------------------------------------------
    def soh(self) -> dict:
        last = self.bms.iloc[-1]
        return {
            "soh": round(self.soh_now, 4),
            "soh_pct": round(self.soh_now * 100, 1),
            "usable_kwh": round(usable_kwh(self.soh_now), 2),
            "nominal_kwh": self.profile["nominal_kwh"],
            "cycle_count": int(last["cycle"]),
            "internal_resistance_mohm": round(float(last["internal_resistance_mohm"]), 1),
            "fast_charge_ratio": round(float(last["fast_charge_ratio"]), 3),
            "trend": self._soh_trend,
            "model": {"type": "PyTorch MLP (10 BMS features)", **self.soh_model.metrics},
        }

    # -- Range ----------------------------------------------------------------
    def conditions(self, state) -> dict:
        return {
            "ambient_temp_c": state.ambient_temp_c,
            "hvac_mode": state.hvac_mode,
            "driving_style": state.driving_style,
            "payload_kg": state.payload_kg,
            "soh": self.soh_now,
        }

    def range(self, state, highway_share: float | None = None) -> dict:
        share = self.profile["highway_share"] if highway_share is None else highway_share
        out = self.range_model.range_breakdown(state.soc, self.conditions(state), share)
        out["soc_pct"] = round(state.soc * 100, 1)
        out["model"] = {"type": "PyTorch MLP (Wh/km)", **self.range_model.metrics}
        return out

    def range_km(self, state, highway_share: float | None = None, floor_soc: float = 0.0) -> float:
        share = self.profile["highway_share"] if highway_share is None else highway_share
        return self.range_model.range_km(state.soc, self.conditions(state), share, floor_soc)

    def explain_range(self, state, highway_share: float | None = None) -> dict:
        share = self.profile["highway_share"] if highway_share is None else highway_share
        return attribution.explain(self.range_model, state.soc, self.conditions(state), share)

    def usable_kwh(self) -> float:
        return usable_kwh(self.soh_now)

    # -- Per-edge energy for the route planner -------------------------------
    def edge_energy_kwh(self, edges: list[dict], node_elev: dict, cond: dict) -> dict:
        """kWh for every directed edge under the given conditions (cached)."""
        key = (round(cond["ambient_temp_c"], 1), cond["hvac_mode"], round(cond["driving_style"], 2),
               round(cond.get("payload_kg", 75)), round(cond["soh"], 3))
        if key in self._edge_cache:
            return self._edge_cache[key]
        rows, keys = [], []
        for e in edges:
            for a, b in ((e["from"], e["to"]), (e["to"], e["from"])):
                grad = (node_elev[b] - node_elev[a]) / max(e["distance_km"], 0.1)
                rows.append(self.range_model.segment_conditions(cond, e["road_type"], e["avg_speed_kmh"], grad))
                keys.append((a, b, e["distance_km"]))
        whkm = self.range_model.wh_per_km(rows)
        table = {(a, b): float(w * d / 1000) for (a, b, d), w in zip(keys, whkm)}
        self._edge_cache[key] = table
        return table

    def hvac_kw(self, mode: str, temp_c: float) -> float:
        # Rough HVAC draw for pre-cooling estimates (matches the training physics band)
        if mode == "ac":
            return float(np.clip(0.6 + 0.07 * (temp_c - 22), 0.4, 2.5))
        if mode == "heat":
            return float(np.clip(1.5 + 0.09 * (18 - temp_c), 0.8, 4.0))
        return 0.2 if mode == "fan" else 0.0
