"""Does the SOH approach work on REAL batteries? Validation on the NASA PCoE cells.

No cell is ever in both the training and the test side. Two tiers:
  classic  B0005/6/7/18 - the standard benchmark (24 degC, long clean ageing runs);
           leave-one-cell-out: train on 3 cells, test on the 4th, four times
  all      all 34 cells, 5 folds grouped by cell (includes 4 degC cells whose measured
           capacity also drops because of the cold, not only ageing - a harder test)

Compared on each held-out cell:
  zero-shot     the app's SOH model, trained only on synthetic cells, applied unchanged
  real          the same MLP architecture trained on the real training cells
  fine-tuned    the synthetic model fine-tuned on the real training cells
  cycle-only    baseline: linear fit of SOH on cycle count (what you'd get with no BMS signals)
  mean          baseline: predict the training cells' average SOH

Writes models/soh_nasa_metrics.json and ../results/nasa_soh_predictions.csv (per-cycle
predictions for the classic cells, for plotting).

Run from backend/:  python -m training.validate_soh_nasa   (needs data_gen.nasa_battery first)
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from app.battery_core.ageing import SOH_FEATURES
from app.battery_core.nn import TabularRegressor
from app.config import DATA_DIR, MODELS_DIR
from app.battery_core.soh_model import MODEL_PATH

CLASSIC = ["B0005", "B0006", "B0007", "B0018"]
RESULTS = Path(__file__).resolve().parents[2] / "results"


def errors(y, p) -> dict:
    y, p = np.asarray(y, float), np.asarray(p, float)
    return {"mae_pct_points": float(100 * np.mean(np.abs(p - y))),
            "rmse_pct_points": float(100 * np.sqrt(np.mean((p - y) ** 2))),
            "mape_pct": float(100 * np.mean(np.abs(p - y) / y))}


def train_real(tr: pd.DataFrame, seed=0) -> TabularRegressor:
    m = TabularRegressor(SOH_FEATURES, hidden=(64, 64, 32))
    m.fit(tr[SOH_FEATURES].to_numpy(), tr.soh.to_numpy(), epochs=250, lr=2e-3, batch_size=64, seed=seed,
          verbose=False)
    return m


def fine_tune(base: TabularRegressor, tr: pd.DataFrame, epochs=150, lr=5e-4, seed=0) -> TabularRegressor:
    """Continue training the synthetic model on real cells, keeping its feature scaling."""
    torch.manual_seed(seed)
    m = copy.deepcopy(base)
    X = torch.from_numpy(((tr[SOH_FEATURES].to_numpy(np.float32) - m.x_mean) / m.x_std).astype(np.float32))
    y = torch.from_numpy(((tr.soh.to_numpy(np.float32) - m.y_mean) / m.y_std).astype(np.float32))
    opt = torch.optim.AdamW(m.model.parameters(), lr=lr, weight_decay=1e-4)
    m.model.train()
    for _ in range(epochs):
        perm = torch.randperm(len(X))
        for i in range(0, len(X), 64):
            idx = perm[i:i + 64]
            opt.zero_grad()
            loss = torch.nn.functional.mse_loss(m.model(X[idx]), y[idx])
            loss.backward()
            opt.step()
    m.model.eval()
    return m


def evaluate(df: pd.DataFrame, folds: list[list[str]], synthetic: TabularRegressor) -> tuple[dict, pd.DataFrame]:
    preds = []
    for test_cells in folds:
        tr, te = df[~df.cell_id.isin(test_cells)], df[df.cell_id.isin(test_cells)]
        X = te[SOH_FEATURES].to_numpy()
        a, b = np.polyfit(tr.cycle, tr.soh, 1)
        out = te[["cell_id", "cycle", "soh"]].copy()
        out["zero_shot"] = np.clip(synthetic.predict(X), 0.2, 1.05)
        out["real"] = train_real(tr).predict(X)
        out["fine_tuned"] = fine_tune(synthetic, tr).predict(X)
        out["cycle_only"] = a * te.cycle + b
        out["mean"] = tr.soh.mean()
        preds.append(out)
    p = pd.concat(preds)
    methods = ["zero_shot", "real", "fine_tuned", "cycle_only", "mean"]
    summary = {m: errors(p.soh, p[m]) for m in methods}
    summary["per_cell_mae_pct_points"] = {
        cell: {m: round(100 * float(np.mean(np.abs(g[m] - g.soh))), 2) for m in methods}
        for cell, g in p.groupby("cell_id")}
    summary["cells"], summary["cycles"] = int(p.cell_id.nunique()), int(len(p))
    return summary, p


def main():
    df = pd.read_csv(DATA_DIR / "nasa_cycles.csv")
    synthetic = TabularRegressor.load(MODEL_PATH)

    classic = df[df.cell_id.isin(CLASSIC)]
    c_sum, c_pred = evaluate(classic, [[c] for c in CLASSIC], synthetic)

    cells = np.random.default_rng(0).permutation(sorted(df.cell_id.unique()))
    folds = [list(f) for f in np.array_split(cells, 5)]
    a_sum, _ = evaluate(df, folds, synthetic)

    out = {"dataset": "NASA Ames PCoE Li-ion Battery Aging (Saha & Goebel 2007), 18650 cells, 2 Ah rated",
           "label": "SOH = measured discharge capacity / 2.0 Ah",
           "classic_leave_one_cell_out": c_sum, "all_cells_5fold_by_cell": a_sum}
    (MODELS_DIR / "soh_nasa_metrics.json").write_text(json.dumps(out, indent=2))
    RESULTS.mkdir(exist_ok=True)
    c_pred.round(4).to_csv(RESULTS / "nasa_soh_predictions.csv", index=False)

    for name, s in (("Classic 4 cells, leave-one-cell-out", c_sum), ("All 34 cells, 5 folds by cell", a_sum)):
        print(f"\n{name} ({s['cells']} cells, {s['cycles']} cycles) - MAE / MAPE on held-out cells")
        for m in ("real", "fine_tuned", "zero_shot", "cycle_only", "mean"):
            e = s[m]
            print(f"  {m:11s} {e['mae_pct_points']:6.2f} %-pts   {e['mape_pct']:6.2f}%")


if __name__ == "__main__":
    main()
