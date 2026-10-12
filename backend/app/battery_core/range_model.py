"""Personalized range estimation.

The neural net predicts energy consumption (Wh/km) from driving conditions.
Range is then derived from usable energy:

    range_km = usable_kwh(SOH) * (SOC - floor) / Wh_per_km * 1000

so range responds to weather, HVAC, driving style, speed, terrain, payload
and battery age - not a fixed SOC -> km mapping.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.config import MODELS_DIR, VEHICLE
from app.battery_core.nn import TabularRegressor

HVAC_MODES = ["off", "fan", "ac", "heat"]
ROAD_TYPES = ["city", "highway"]
RAW_FEATURES = ["ambient_temp_c", "hvac_mode", "driving_style", "avg_speed_kmh",
                "gradient_m_per_km", "payload_kg", "road_type", "soh"]
NUMERIC = ["ambient_temp_c", "driving_style", "avg_speed_kmh", "gradient_m_per_km", "payload_kg", "soh"]
ENCODED_FEATURES = NUMERIC + [f"hvac_{m}" for m in HVAC_MODES] + [f"road_{r}" for r in ROAD_TYPES]

MODEL_PATH = MODELS_DIR / "range_model.pt"

# Speeds used to represent "typical" city / highway segments
CITY_SPEED, HIGHWAY_SPEED = 26.0, 75.0


def encode(df: pd.DataFrame) -> np.ndarray:
    X = df[NUMERIC].astype(float).to_numpy()
    hv = np.stack([(df["hvac_mode"] == m).to_numpy(float) for m in HVAC_MODES], 1)
    rd = np.stack([(df["road_type"] == r).to_numpy(float) for r in ROAD_TYPES], 1)
    return np.hstack([X, hv, rd])


def usable_kwh(soh: float) -> float:
    return VEHICLE["nominal_kwh"] * VEHICLE["usable_fraction"] * soh


class RangeModel:
    def __init__(self, path=MODEL_PATH):
        self.reg = TabularRegressor.load(path)
        self.metrics = getattr(self.reg, "metrics", {})

    def wh_per_km(self, rows: list[dict] | pd.DataFrame) -> np.ndarray:
        df = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
        return np.clip(self.reg.predict(encode(df)).astype(float), 60.0, 400.0)

    def segment_conditions(self, cond: dict, road_type: str, speed: float, gradient=0.0) -> dict:
        return {
            "ambient_temp_c": cond["ambient_temp_c"],
            "hvac_mode": cond["hvac_mode"],
            "driving_style": cond["driving_style"],
            "avg_speed_kmh": speed,
            "gradient_m_per_km": gradient,
            "payload_kg": cond.get("payload_kg", 75.0),
            "road_type": road_type,
            "soh": cond["soh"],
        }

    def mixed_wh_per_km(self, cond: dict, highway_share: float) -> float:
        city, hwy = self.wh_per_km([
            self.segment_conditions(cond, "city", CITY_SPEED),
            self.segment_conditions(cond, "highway", HIGHWAY_SPEED),
        ])
        return float((1 - highway_share) * city + highway_share * hwy)

    def range_km(self, soc: float, cond: dict, highway_share: float, floor_soc: float = 0.0) -> float:
        whkm = self.mixed_wh_per_km(cond, highway_share)
        return max(0.0, usable_kwh(cond["soh"]) * (soc - floor_soc) * 1000.0 / whkm)

    def range_breakdown(self, soc: float, cond: dict, highway_share: float) -> dict:
        city, hwy = self.wh_per_km([
            self.segment_conditions(cond, "city", CITY_SPEED),
            self.segment_conditions(cond, "highway", HIGHWAY_SPEED),
        ])
        kwh = usable_kwh(cond["soh"]) * soc
        mixed = (1 - highway_share) * city + highway_share * hwy
        return {
            "personalized_km": round(kwh * 1000 / mixed, 1),
            "city_km": round(kwh * 1000 / city, 1),
            "highway_km": round(kwh * 1000 / hwy, 1),
            "naive_km": round(VEHICLE["rated_range_km"] * soc, 1),
            "wh_per_km": round(float(mixed), 1),
            "city_wh_per_km": round(float(city), 1),
            "highway_wh_per_km": round(float(hwy), 1),
            "usable_kwh_now": round(kwh, 2),
        }
