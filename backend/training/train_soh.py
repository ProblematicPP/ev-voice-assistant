"""Train the PyTorch SOH estimator on synthetic cell-cycling data.

Split is by cell (not by row): ~65% of cells train, ~15% validate (monitored during
training), ~20% are held out as the test set and only scored once at the end. No
cell appears in two splits - the protocol you'd use on the NASA dataset.

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
        "mape": float(np.mean(np.abs(err) / np.abs(y))),
    }


def split_cells(cells, seed=0, test_frac=0.20, val_frac=0.15):
    rng = np.random.default_rng(seed)
    shuffled = rng.permutation(cells)
    n_test = max(1, round(len(cells) * test_frac))
    n_val = max(1, round(len(cells) * val_frac))
    return set(shuffled[n_test + n_val:]), set(shuffled[n_test:n_test + n_val]), set(shuffled[:n_test])


def main():
    df = pd.read_csv(DATA_DIR / "cell_cycles.csv")
    train_cells, val_cells, test_cells = split_cells(df.cell_id.unique())
    tr, va, te = (df[df.cell_id.isin(c)] for c in (train_cells, val_cells, test_cells))

    print(f"Training SOH model: {len(train_cells)} train / {len(val_cells)} val / {len(test_cells)} test cells "
          f"({len(tr)} / {len(va)} / {len(te)} cycles)")
    model = TabularRegressor(SOH_FEATURES, hidden=(64, 64, 32))
    model.fit(tr[SOH_FEATURES].to_numpy(), tr.soh.to_numpy(), va[SOH_FEATURES].to_numpy(), va.soh.to_numpy(),
              epochs=60, lr=2e-3)

    val = metrics(va.soh.to_numpy(), model.predict(va[SOH_FEATURES].to_numpy()))
    m = metrics(te.soh.to_numpy(), model.predict(te[SOH_FEATURES].to_numpy()))
    m.update({"split": "by cell", "test_cells": sorted(test_cells), "val_mae": val["mae"],
              "n_train_cells": len(train_cells), "n_val_cells": len(val_cells), "n_test_cells": len(test_cells)})
    print(f"Held-out test cells: MAE={m['mae'] * 100:.2f} %SOH  MAPE={m['mape'] * 100:.2f}%  "
          f"RMSE={m['rmse'] * 100:.2f}  R2={m['r2']:.3f}")
    model.save(MODELS_DIR / "soh_model.pt", metrics=m)
    (MODELS_DIR / "soh_metrics.json").write_text(json.dumps(m, indent=2))


if __name__ == "__main__":
    main()
