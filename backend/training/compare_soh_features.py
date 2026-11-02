"""Why the shipped SOH model uses 'change since new' features: a fair comparison on real cells.

Both feature sets, same MLP, 3 training seeds, three held-out-by-cell protocols on NASA data:
the fixed 7-cell test split, classic B0005/6/7/18 leave-one-out, and all 34 cells in 5 folds.
Measured (2 Nov 2026): absolute 8.80 / 2.84 / 7.24, change-since-new 5.22 / 3.36 / 6.98 SOH points;
overall 6.29 vs 5.19. Absolute values do slightly better only when every cell was tested the same
way (the classic 4); across differently built and tested cells, drift from each cell's own start
generalises better.

Run from backend/:  python -m training.compare_soh_features   (~5 min)
"""
import numpy as np
import pandas as pd

from app.battery_core.ageing import SOH_FEATURES
from app.battery_core.nn import TabularRegressor
from app.battery_core.soh_model import drift_features
from app.config import DATA_DIR
from data_gen.nasa_battery import TEST_CELLS, VAL_CELLS

CLASSIC = ["B0005", "B0006", "B0007", "B0018"]
SEEDS = (0, 1, 2)


def protocols(cell_ids):
    folds = np.array_split(np.random.default_rng(0).permutation(sorted(cell_ids)), 5)
    return {
        "fixed 7 test cells": [(lambda d: d[~d.cell_id.isin(TEST_CELLS + VAL_CELLS)], TEST_CELLS)],
        "classic leave-one-out": [(lambda d, c=c: d[d.cell_id.isin(CLASSIC) & (d.cell_id != c)], [c])
                                  for c in CLASSIC],
        "all 34, 5 folds": [(lambda d, f=list(f): d[~d.cell_id.isin(f)], list(f)) for f in folds],
    }


def held_out_mae(d: pd.DataFrame, folds, seed: int) -> float:
    err, n = 0.0, 0
    for train_sel, test in folds:
        tr, te = train_sel(d), d[d.cell_id.isin(test)]
        m = TabularRegressor(SOH_FEATURES, hidden=(64, 64, 32))
        m.fit(tr[SOH_FEATURES].to_numpy(), tr.soh.to_numpy(), epochs=250, lr=2e-3, batch_size=64, seed=seed,
              verbose=False)
        err += np.abs(m.predict(te[SOH_FEATURES].to_numpy()) - te.soh.to_numpy()).sum()
        n += len(te)
    return 100 * err / n


def main():
    raw = pd.read_csv(DATA_DIR / "nasa_cycles.csv").sort_values(["cell_id", "cycle"])
    variants = {"absolute": raw, "change since new": drift_features(raw, by="cell_id")}
    plan = protocols(raw.cell_id.unique())
    overall = {}
    for vname, d in variants.items():
        means = []
        for pname, folds in plan.items():
            maes = [held_out_mae(d, folds, s) for s in SEEDS]
            means.append(np.mean(maes))
            print(f"{vname:18s} {pname:22s} {np.mean(maes):.2f}  (seeds {np.round(maes, 2)})", flush=True)
        overall[vname] = float(np.mean(means))
    for vname, v in overall.items():
        print(f"{vname}: overall mean {v:.2f} SOH points")


if __name__ == "__main__":
    main()
