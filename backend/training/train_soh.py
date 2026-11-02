"""Train the PyTorch SOH estimator.

Two models, same architecture and the same 10 BMS features (resistance, voltages and peak
temperature as change since the cell was new - see app/battery_core/soh_model.py):

  models/soh_model.pt            SHIPPED. Trained on REAL cells (NASA PCoE ageing data).
                                 Split by cell: training cells, 5 validation cells (monitored
                                 during training) and 7 test cells (data_gen.nasa_battery.TEST_CELLS)
                                 scored once at the end and never trained on.
  models/soh_model_synthetic.pt  Trained on the synthetic NASA/CALCE-shaped cells. Kept only to
                                 show (training.validate_soh_nasa) that synthetic-trained weights
                                 do not transfer to real batteries.

Run from backend/:  python -m training.train_soh   (needs data_gen.nasa_battery and gen_cells first)
"""
import json

import numpy as np
import pandas as pd

from app.battery_core.ageing import SOH_FEATURES
from app.battery_core.nn import TabularRegressor
from app.battery_core.soh_model import MODEL_PATH, SYNTHETIC_MODEL_PATH, drift_features
from app.config import DATA_DIR, MODELS_DIR
from data_gen import nasa_battery


def metrics(y, p):
    err = p - y
    return {
        "mae": float(np.mean(np.abs(err))),
        "rmse": float(np.sqrt(np.mean(err**2))),
        "r2": float(1 - np.sum(err**2) / np.sum((y - y.mean()) ** 2)),
        "mape": float(np.mean(np.abs(err) / np.abs(y))),
    }


def split_cells(cells, seed=0, test_frac=0.20, val_frac=0.15):
    """Random split by cell for the synthetic cells."""
    rng = np.random.default_rng(seed)
    shuffled = rng.permutation(cells)
    n_test = max(1, round(len(cells) * test_frac))
    n_val = max(1, round(len(cells) * val_frac))
    return set(shuffled[n_test + n_val:]), set(shuffled[n_test:n_test + n_val]), set(shuffled[:n_test])


def fit(tr, va, epochs, batch_size):
    model = TabularRegressor(SOH_FEATURES, hidden=(64, 64, 32))
    model.fit(tr[SOH_FEATURES].to_numpy(), tr.soh.to_numpy(), va[SOH_FEATURES].to_numpy(), va.soh.to_numpy(),
              epochs=epochs, lr=2e-3, batch_size=batch_size, verbose=False)
    return model


def train_real():
    df = drift_features(pd.read_csv(DATA_DIR / "nasa_cycles.csv").sort_values(["cell_id", "cycle"]), by="cell_id")
    tr, va, te = nasa_battery.split(df)
    print(f"SOH model (shipped) on REAL NASA cells: {tr.cell_id.nunique()} train / {va.cell_id.nunique()} val / "
          f"{te.cell_id.nunique()} test cells ({len(tr)} / {len(va)} / {len(te)} cycles)")
    model = fit(tr, va, epochs=250, batch_size=64)
    m = metrics(te.soh.to_numpy(), model.predict(te[SOH_FEATURES].to_numpy()))
    m["val_mae"] = metrics(va.soh.to_numpy(), model.predict(va[SOH_FEATURES].to_numpy()))["mae"]
    m["per_test_cell_mae"] = {c: round(float(np.mean(np.abs(model.predict(g[SOH_FEATURES].to_numpy()) - g.soh))), 4)
                              for c, g in te.groupby("cell_id")}
    m.update({"data": "NASA PCoE Li-ion ageing (real cells)", "split": "fixed by cell",
              "test_cells": nasa_battery.TEST_CELLS, "val_cells": nasa_battery.VAL_CELLS})
    print(f"  held-out real test cells: MAE={m['mae'] * 100:.2f} %SOH  MAPE={m['mape'] * 100:.2f}%  R2={m['r2']:.3f}")
    for c, e in m["per_test_cell_mae"].items():
        print(f"    {c}: {e * 100:.2f} points")
    model.save(MODEL_PATH, metrics=m)
    (MODELS_DIR / "soh_metrics.json").write_text(json.dumps(m, indent=2))


def train_synthetic():
    df = drift_features(pd.read_csv(DATA_DIR / "cell_cycles.csv").sort_values(["cell_id", "cycle"]), by="cell_id")
    train_cells, val_cells, test_cells = split_cells(df.cell_id.unique())
    tr, va, te = (df[df.cell_id.isin(c)] for c in (train_cells, val_cells, test_cells))
    model = fit(tr, va, epochs=60, batch_size=256)
    m = metrics(te.soh.to_numpy(), model.predict(te[SOH_FEATURES].to_numpy()))
    m.update({"data": "synthetic cells", "test_cells": sorted(test_cells)})
    print(f"SOH model (synthetic, comparison only): held-out synthetic cells MAE={m['mae'] * 100:.2f} %SOH")
    model.save(SYNTHETIC_MODEL_PATH, metrics=m)


def main():
    train_real()
    train_synthetic()


if __name__ == "__main__":
    main()
