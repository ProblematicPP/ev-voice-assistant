"""State-of-Health estimation from BMS cycle features (PyTorch MLP trained on real NASA cells).

Resistance, voltage and temperature are fed to the model as their CHANGE since the battery was
new (mean of its first 5 logged cycles), not as absolute values. New cells of the same type
differ a lot (NASA's range from 28 to 135 mOhm), so an absolute reading can make a healthy cell
look worn; a BMS tracks drift from its own baseline instead. On held-out real cells this halved
the error (8.8 -> 4.5 SOH points, mean of 3 seeds). So the model takes a battery's log from the
start, not isolated cycles.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.battery_core.ageing import SOH_FEATURES
from app.battery_core.nn import TabularRegressor
from app.config import MODELS_DIR

MODEL_PATH = MODELS_DIR / "soh_model.pt"                      # shipped: trained on real NASA cells
SYNTHETIC_MODEL_PATH = MODELS_DIR / "soh_model_synthetic.pt"  # comparison only (does not transfer)

DRIFT_FEATURES = ["internal_resistance_mohm", "v_mean", "v_min", "t_max_c"]
BASELINE_CYCLES = 5


def drift_features(log: pd.DataFrame, by: str | None = None) -> pd.DataFrame:
    """Replace DRIFT_FEATURES with their change since the battery's first logged cycles.

    `log` must be ordered by cycle and start from the battery's first cycles. `by` names the
    battery-id column when the frame holds several batteries (e.g. "cell_id").
    """
    out = log.copy()
    if by is None:
        base = log[DRIFT_FEATURES].iloc[:BASELINE_CYCLES].mean()
        out[DRIFT_FEATURES] = log[DRIFT_FEATURES] - base
    else:
        first = log.groupby(by, sort=False)[DRIFT_FEATURES].transform(lambda s: s.iloc[:BASELINE_CYCLES].mean())
        out[DRIFT_FEATURES] = log[DRIFT_FEATURES] - first
    return out


class SOHModel:
    def __init__(self, path=MODEL_PATH):
        self.reg = TabularRegressor.load(path)
        self.metrics = getattr(self.reg, "metrics", {})

    def predict_log(self, log: pd.DataFrame) -> np.ndarray:
        """SOH for every cycle of one battery's log (ordered, starting from its first cycles)."""
        return np.clip(self.reg.predict(drift_features(log)[SOH_FEATURES].to_numpy()).astype(float), 0.3, 1.0)

    def current(self, log: pd.DataFrame, window: int = 15) -> float:
        """Median over the last few cycles smooths out single-cycle sensor noise."""
        return float(np.median(self.predict_log(log)[-window:]))

    def trend(self, log: pd.DataFrame, points: int = 24) -> list[dict]:
        preds = self.predict_log(log)
        idx = np.linspace(0, len(log) - 1, min(points, len(log))).astype(int)
        sample = log.iloc[idx]
        return [{"date": d, "cycle": int(c), "soh": round(float(p), 4)}
                for d, c, p in zip(sample["date"], sample["cycle"], preds[idx])]
