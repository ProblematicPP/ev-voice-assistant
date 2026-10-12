"""State-of-Health estimation from BMS cycle features (PyTorch MLP)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.battery_core.ageing import SOH_FEATURES
from app.battery_core.nn import TabularRegressor
from app.config import MODELS_DIR

MODEL_PATH = MODELS_DIR / "soh_model.pt"


class SOHModel:
    def __init__(self, path=MODEL_PATH):
        self.reg = TabularRegressor.load(path)
        self.metrics = getattr(self.reg, "metrics", {})

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        return np.clip(self.reg.predict(df[SOH_FEATURES].to_numpy()).astype(float), 0.5, 1.0)

    def current(self, bms: pd.DataFrame, window: int = 15) -> float:
        """Median over the last few cycles smooths out single-cycle sensor noise."""
        return float(np.median(self.predict(bms.tail(window))))

    def trend(self, bms: pd.DataFrame, points: int = 24) -> list[dict]:
        idx = np.linspace(0, len(bms) - 1, points).astype(int)
        sample = bms.iloc[idx]
        preds = self.predict(sample)
        return [
            {"date": d, "cycle": int(c), "soh": round(float(p), 4)}
            for d, c, p in zip(sample["date"], sample["cycle"], preds)
        ]
