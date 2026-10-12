"""Train the PyTorch SOH estimator on synthetic cell-cycling data.

Split is by cell (not by row) so validation cells are never seen in training -
the same protocol you'd use on the NASA dataset.

Run from backend/:  python -m training.train_soh
"""
import json

import numpy as np
import pandas as pd

from app.battery_core.ageing import SOH_FEATURES
from app.battery_core.nn import TabularRegressor
from app.config import DATA_DIR, MODELS_DIR


def metrics(y, p):
    err = p - y
    return {
        "mae": float(np.mean(np.abs(err))),
        "rmse": float(np.sqrt(np.mean(err**2))),
        "r2": float(1 - np.sum(err**2) / np.sum((y - y.mean()) ** 2)),
    }


def main():
    df = pd.read_csv(DATA_DIR / "cell_cycles.csv")
    cells = df.cell_id.unique()
    rng = np.random.default_rng(0)
    val_cells = set(rng.choice(cells, size=max(1, len(cells) // 5), replace=False))
    tr, va = df[~df.cell_id.isin(val_cells)], df[df.cell_id.isin(val_cells)]

    Xtr, ytr = tr[SOH_FEATURES].to_numpy(), tr.soh.to_numpy()
    Xva, yva = va[SOH_FEATURES].to_numpy(), va.soh.to_numpy()

    print(f"Training SOH model: {len(tr)} train rows / {len(va)} val rows "
          f"({len(val_cells)} held-out cells)")
    model = TabularRegressor(SOH_FEATURES, hidden=(64, 64, 32))
    model.fit(Xtr, ytr, Xva, yva, epochs=60, lr=2e-3)

    m = metrics(yva, model.predict(Xva))
    print(f"Held-out cells: MAE={m['mae'] * 100:.2f} %SOH  RMSE={m['rmse'] * 100:.2f}  R2={m['r2']:.3f}")
    model.save(MODELS_DIR / "soh_model.pt", metrics=m)
    (MODELS_DIR / "soh_metrics.json").write_text(json.dumps(m, indent=2))


if __name__ == "__main__":
    main()
