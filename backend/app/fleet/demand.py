"""Rental-demand forecast: bookings per zone per hour from time and weather (PyTorch MLP)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.battery_core.nn import TabularRegressor
from app.config import MODELS_DIR

MODEL_PATH = MODELS_DIR / "demand_model.pt"
ZONES = ["koramangala", "indiranagar", "whitefield", "electronic_city", "kempegowda_airport", "hebbal",
         "jayanagar", "marathahalli", "yeshwanthpur", "hsr_layout", "yelahanka", "rajajinagar"]
FEATURES = ["hour_sin", "hour_cos", "dow_sin", "dow_cos", "weekend", "temp_c", "rain_mm"] + [f"z_{z}" for z in ZONES]


def encode(df: pd.DataFrame) -> np.ndarray:
    h, d = df.hour.to_numpy(float), df.dow.to_numpy(float)
    cols = [np.sin(2 * np.pi * h / 24), np.cos(2 * np.pi * h / 24), np.sin(2 * np.pi * d / 7),
            np.cos(2 * np.pi * d / 7), (d >= 5).astype(float), df.temp_c.to_numpy(float), df.rain_mm.to_numpy(float)]
    cols += [(df.zone == z).to_numpy(float) for z in ZONES]
    return np.stack(cols, 1)


class DemandModel:
    def __init__(self, path=MODEL_PATH):
        self.reg = TabularRegressor.load(path)
        self.metrics = getattr(self.reg, "metrics", {})

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        """Expected bookings per zone-hour (squared-error training on raw counts targets the mean rate)."""
        return np.clip(self.reg.predict(encode(df)), 0.0, None)

    def forecast(self, start: pd.Timestamp, hours: int, temp_c: float, rain_mm: float = 0.0) -> pd.DataFrame:
        """Zone x hour grid for the next `hours` hours with a flat weather assumption."""
        times = pd.date_range(start.floor("h"), periods=hours, freq="h")
        grid = pd.DataFrame([(z, t) for t in times for z in ZONES], columns=["zone", "time"])
        grid["hour"], grid["dow"] = grid.time.dt.hour, grid.time.dt.dayofweek
        diurnal = 5 * np.sin(np.pi * (grid.hour - 8) / 12)            # same shape as the training weather
        grid["temp_c"] = temp_c + diurnal - 5 * np.sin(np.pi * (start.hour - 8) / 12)
        grid["rain_mm"] = rain_mm
        grid["bookings"] = self.predict(grid)
        return grid
