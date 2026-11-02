"""Real cell-ageing data: NASA Ames PCoE Li-ion Battery Aging dataset (34 x 18650 cells, 2 Ah rated).

Downloads the public archive once (~210 MB), then turns every discharge cycle into the SAME
10 BMS features the SOH model uses, computed from the measured signals:

  cycle                     discharge cycle number for that cell
  ambient_temp_c            chamber temperature
  charge_c_rate             mean constant-current charging current of the preceding charge / 2 Ah
  fast_charge_ratio         running share of charges above 1C (always 0 here: NASA charged at 0.75C)
  depth_of_discharge        1.0 - every NASA discharge ran to the cut-off voltage
  discharge_c_rate          mean |discharge current| / 2 Ah
  internal_resistance_mohm  ohmic resistance Re from the latest impedance sweep (EIS), in mOhm
  v_mean, v_min             mean / minimum terminal voltage during the discharge
  t_max_c                   peak cell temperature during the discharge
  soh                       measured discharge capacity / 2.0 Ah   (the label)

Output: data/nasa_cycles.csv. Cycles with impossible readings (capacity outside 0.5-2.2 Ah, no
resistance measurement, sensor dropouts) are dropped and counted.

Source: B. Saha and K. Goebel (2007), "Battery Data Set", NASA Prognostics Data Repository,
NASA Ames Research Center. Public domain (US Government work).

Run from backend/:  python -m data_gen.nasa_battery
"""
from __future__ import annotations

import zipfile
from collections import Counter
from pathlib import Path

import httpx
import numpy as np
import pandas as pd
import scipy.io as sio

from app.config import DATA_DIR

URL = "https://phm-datasets.s3.amazonaws.com/NASA/5.+Battery+Data+Set.zip"
RAW = DATA_DIR / "nasa_raw"
RATED_AH = 2.0


def fetch() -> Path:
    """Download and unpack once; returns the folder holding the B00xx.mat files."""
    out = RAW / "extracted"
    if out.exists() and len(list(out.glob("B*.mat"))) >= 30:
        return out
    RAW.mkdir(parents=True, exist_ok=True)
    zpath = RAW / "battery.zip"
    if not zpath.exists() or zpath.stat().st_size < 100_000_000:
        print(f"Downloading NASA battery data (~210 MB) from {URL}")
        with httpx.stream("GET", URL, timeout=120, follow_redirects=True) as r:
            r.raise_for_status()
            with open(zpath, "wb") as f:
                for chunk in r.iter_bytes(1 << 20):
                    f.write(chunk)
    out.mkdir(exist_ok=True)
    with zipfile.ZipFile(zpath) as outer:          # the archive holds one zip per test campaign
        for name in outer.namelist():
            if name.endswith(".zip"):
                with outer.open(name) as inner, zipfile.ZipFile(inner) as z:
                    for member in z.namelist():
                        if member.endswith(".mat"):
                            (out / Path(member).name).write_bytes(z.read(member))
    return out


def cell_rows(path: Path, dropped: Counter) -> list[dict]:
    m = sio.loadmat(path, simplify_cells=True)
    cycles = m[path.stem]["cycle"]
    rows, last_charge_c, last_re, fast, n_charge, idx = [], None, None, 0, 0, 0
    for c in cycles:
        d = c["data"]
        if c["type"] == "charge":
            i = np.asarray(d["Current_measured"], float)
            cc = i[i > 0.5]                                   # constant-current phase
            if len(cc):
                last_charge_c = float(cc.mean()) / RATED_AH
                n_charge += 1
                fast += last_charge_c > 1.0
        elif c["type"] == "impedance":
            re = float(np.real(d.get("Re", np.nan)))
            if 0.01 < re < 0.5:                              # ohms; some sweeps are corrupt
                last_re = re
        elif c["type"] == "discharge":
            idx += 1
            cap = float(np.asarray(d.get("Capacity", np.nan)).ravel()[0]) if np.size(d.get("Capacity", [])) else np.nan
            v = np.asarray(d["Voltage_measured"], float)
            i = np.asarray(d["Current_measured"], float)
            t = np.asarray(d["Temperature_measured"], float)
            if not (0.5 < cap < 2.2):
                dropped["capacity outside 0.5-2.2 Ah"] += 1
                continue
            if last_re is None or last_charge_c is None:
                dropped["no impedance or charge measurement yet"] += 1
                continue
            if len(v) < 10 or v.min() < 1.0 or not np.isfinite(t).all():
                dropped["sensor dropout"] += 1
                continue
            rows.append({
                "cell_id": path.stem, "cycle": idx, "ambient_temp_c": float(c["ambient_temperature"]),
                "charge_c_rate": last_charge_c, "fast_charge_ratio": fast / max(n_charge, 1),
                "depth_of_discharge": 1.0, "discharge_c_rate": float(np.abs(i).mean()) / RATED_AH,
                "internal_resistance_mohm": last_re * 1000, "v_mean": float(v.mean()), "v_min": float(v.min()),
                "t_max_c": float(t.max()), "capacity_ah": cap, "soh": cap / RATED_AH,
            })
    return rows


def main():
    folder = fetch()
    dropped = Counter()
    rows = []
    for path in sorted(folder.glob("B*.mat")):
        rows += cell_rows(path, dropped)
    df = pd.DataFrame(rows)
    df.to_csv(DATA_DIR / "nasa_cycles.csv", index=False)
    print(f"nasa_cycles.csv: {len(df)} discharge cycles from {df.cell_id.nunique()} real cells, "
          f"SOH {df.soh.min():.2f}-{df.soh.max():.2f}, {df.ambient_temp_c.nunique()} temperatures")
    print(f"  dropped: {dict(dropped)}")


if __name__ == "__main__":
    main()
