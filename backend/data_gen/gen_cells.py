"""Synthetic cell-cycling dataset shaped like NASA PCoE / CALCE ageing data.

Output:
  data/cell_cycles.csv        one row per (cell, cycle): features + soh target
  data/cell_timeseries.csv    raw V/I/T/SOC traces for a few sample cycles
"""
import numpy as np
import pandas as pd

from app.battery_core.ageing import cycle_timeseries, simulate_cycles
from app.config import DATA_DIR

N_CELLS = 36


def generate(seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    frames = []
    for cell in range(N_CELLS):
        n = int(rng.integers(400, 1300))
        temp = rng.uniform(10, 45)
        # Each cell has a usage "profile" with per-cycle jitter
        base_charge = rng.choice([0.5, 0.8, 1.2, 1.6, 2.0])
        fast_share = rng.uniform(0, 1)
        charge_c = np.where(rng.random(n) < fast_share, base_charge, rng.uniform(0.2, 0.7, n))
        charge_c = np.clip(charge_c + rng.normal(0, 0.05, n), 0.15, 2.2)
        dod = np.clip(rng.uniform(0.4, 1.0) + rng.normal(0, 0.05, n), 0.2, 1.0)
        dis_c = np.clip(rng.uniform(0.5, 2.0) + rng.normal(0, 0.05, n), 0.3, 2.5)
        temp_series = temp + rng.normal(0, 1.5, n)

        df, _ = simulate_cycles(n, temp_series, charge_c, dod, dis_c, rng=rng)
        df.insert(0, "cell_id", f"C{cell:03d}")
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def generate_timeseries(cycles: pd.DataFrame, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    out = []
    for cell in cycles["cell_id"].unique()[:3]:
        c = cycles[cycles.cell_id == cell]
        for idx in [0, len(c) // 2, len(c) - 1]:
            r = c.iloc[idx]
            ts = cycle_timeseries(r.soh, r.ambient_temp_c, r.charge_c_rate, r.depth_of_discharge,
                                  r.discharge_c_rate, rng=rng)
            ts.insert(0, "cycle", int(r.cycle))
            ts.insert(0, "cell_id", cell)
            out.append(ts)
    return pd.concat(out, ignore_index=True)


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cycles = generate()
    cycles.to_csv(DATA_DIR / "cell_cycles.csv", index=False)
    ts = generate_timeseries(cycles)
    ts.to_csv(DATA_DIR / "cell_timeseries.csv", index=False)
    print(f"cell_cycles.csv: {len(cycles)} rows, {cycles.cell_id.nunique()} cells, "
          f"SOH range {cycles.soh.min():.2f}-{cycles.soh.max():.2f}")
    print(f"cell_timeseries.csv: {len(ts)} rows")


if __name__ == "__main__":
    main()
