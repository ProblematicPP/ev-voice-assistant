"""Train the PyTorch energy-consumption (Wh/km) model used for personalized range.

Run from backend/:  python -m training.train_range
"""
import json

import numpy as np
import pandas as pd

from app.battery_core.nn import TabularRegressor
from app.battery_core.range_model import ENCODED_FEATURES, encode
from app.config import DATA_DIR, MODELS_DIR
from training.train_soh import metrics


def main():
    df = pd.read_csv(DATA_DIR / "trips.csv")
    rng = np.random.default_rng(1)
    mask = rng.random(len(df)) < 0.8
    tr, va = df[mask], df[~mask]
    Xtr, ytr = encode(tr), tr.wh_per_km.to_numpy()
    Xva, yva = encode(va), va.wh_per_km.to_numpy()

    print(f"Training range model: {len(tr)} train / {len(va)} val trips")
    model = TabularRegressor(ENCODED_FEATURES, hidden=(64, 64), log_target=True)
    model.fit(Xtr, ytr, Xva, yva, epochs=50, lr=3e-3)

    m = metrics(yva, model.predict(Xva))
    m["mape"] = float(np.mean(np.abs(model.predict(Xva) - yva) / yva))
    print(f"Validation: MAE={m['mae']:.1f} Wh/km  MAPE={m['mape'] * 100:.1f}%  R2={m['r2']:.3f}")
    model.save(MODELS_DIR / "range_model.pt", metrics=m)
    (MODELS_DIR / "range_metrics.json").write_text(json.dumps(m, indent=2))


if __name__ == "__main__":
    main()
