"""Train the fleet rental-demand forecaster (PyTorch MLP on zone, time and weather).

The last 21 days are held out. The baseline is the historical average for the same
zone, hour and weekday/weekend - what a dispatcher would use without a model.

Run from backend/:  python -m training.train_demand
"""
import json

import numpy as np
import pandas as pd

from app.battery_core.nn import TabularRegressor
from app.config import DATA_DIR, MODELS_DIR
from app.fleet.demand import FEATURES, MODEL_PATH, encode


def main():
    df = pd.read_csv(DATA_DIR / "fleet_demand.csv")
    cut = sorted(df.date.unique())[-21]
    tr, te = df[df.date < cut], df[df.date >= cut]
    print(f"Demand model: {len(tr)} train / {len(te)} test zone-hours (test = last 21 days)")
    # Raw counts with squared error estimate the mean booking rate; a log target was tried and
    # under-predicted (it estimates something closer to a geometric mean).
    model = TabularRegressor(FEATURES, hidden=(64, 64))
    model.fit(encode(tr), tr.bookings.to_numpy(), epochs=40, lr=3e-3, verbose=False)
    pred = np.clip(model.predict(encode(te)), 0, None)

    key = lambda d: [d.zone, d.hour, d.dow >= 5]
    base_tab = tr.groupby(key(tr)).bookings.mean()
    base = base_tab.reindex(pd.MultiIndex.from_arrays(key(te))).to_numpy()
    y = te.bookings.to_numpy()
    rainy = te.rain_mm.to_numpy() > 0
    mae = lambda p, m=slice(None): float(np.mean(np.abs(p[m] - y[m])))
    m = {"mae": mae(pred), "baseline_mae": mae(base), "mae_rainy_hours": mae(pred, rainy),
         "baseline_mae_rainy_hours": mae(base, rainy), "test_days": 21, "test_rows": int(len(te)),
         "mean_bookings_per_zone_hour": float(y.mean())}
    # Counts are Poisson, so even a perfect forecast has MAE ~0.85 against them. The synthetic data
    # also stores the true rate, which shows how close each forecast is to the real pattern.
    lam = te.expected.to_numpy()
    m["mae_vs_true_rate"] = float(np.mean(np.abs(pred - lam)))
    m["baseline_mae_vs_true_rate"] = float(np.mean(np.abs(base - lam)))
    print(f"  MAE {m['mae']:.3f} bookings/zone-hour vs baseline {m['baseline_mae']:.3f}; "
          f"rainy hours {m['mae_rainy_hours']:.3f} vs {m['baseline_mae_rainy_hours']:.3f}; "
          f"vs true rate {m['mae_vs_true_rate']:.3f} vs {m['baseline_mae_vs_true_rate']:.3f}")
    model.save(MODEL_PATH, metrics=m)
    (MODELS_DIR / "demand_metrics.json").write_text(json.dumps(m, indent=2))


if __name__ == "__main__":
    main()
