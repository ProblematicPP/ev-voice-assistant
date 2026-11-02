"""Synthetic EV rental fleet for the fleet-management module.

Outputs:
  data/fleet_vehicles.csv   40 vehicles: zone, ageing stress, fast-charge habit, current charge
  data/fleet_bms.csv        each car's BMS log since new, replayed from a real held-out NASA cell
  data/fleet_demand.csv     180 days x 24 h x 12 zones of rental bookings with weather
  data/fleet_bookings.csv   today's booking requests (long-haul and short urban loops)

Demand follows hour-of-day and weekday patterns per zone, drops in heavy rain and
heat, and rises on weekends near leisure routes. All seeded and reproducible.
"""
from datetime import date, timedelta

import numpy as np
import pandas as pd

from app.battery_core.ageing import simulate_cycles
from app.config import DATA_DIR

ZONES = {  # place id -> (base bookings/hour at peak, character)
    "koramangala": (3.2, "mixed"), "indiranagar": (3.0, "nightlife"), "whitefield": (3.4, "office"),
    "electronic_city": (3.0, "office"), "kempegowda_airport": (2.6, "airport"), "hebbal": (1.8, "mixed"),
    "jayanagar": (1.6, "residential"), "marathahalli": (2.4, "office"), "yeshwanthpur": (1.5, "mixed"),
    "hsr_layout": (2.2, "residential"), "yelahanka": (1.1, "residential"), "rajajinagar": (1.3, "residential"),
}
LONG_HAUL = ["mysuru", "hassan", "tumakuru", "chikkaballapur", "mandya", "kolar", "channapatna", "ramanagara"]
N_VEHICLES = 40
IN_SERVICE_SOH = 0.70
DAYS = 180


def hour_profile(kind: str, hour: np.ndarray, weekend: np.ndarray) -> np.ndarray:
    h = hour.astype(float)
    morning = np.exp(-((h - 9) ** 2) / 4)
    evening = np.exp(-((h - 18.5) ** 2) / 5)
    night = np.exp(-((h - 22) ** 2) / 4)
    midday = np.exp(-((h - 13) ** 2) / 10)
    base = {
        "office": 1.0 * morning + 0.9 * evening + 0.15,
        "residential": 0.5 * morning + 0.6 * evening + 0.4 * midday + 0.1,
        "nightlife": 0.3 * morning + 0.7 * evening + 0.9 * night + 0.1,
        "airport": 0.6 + 0.3 * np.exp(-((h - 6) ** 2) / 6) + 0.3 * np.exp(-((h - 21) ** 2) / 6),
        "mixed": 0.6 * morning + 0.7 * evening + 0.3 * midday + 0.15,
    }[kind]
    # Weekends: office zones go quiet, leisure and residential pick up through the day
    weekend_mult = {"office": 0.35, "nightlife": 1.4, "residential": 1.3, "airport": 1.1, "mixed": 1.15}[kind]
    flat = 0.5 * midday + 0.4
    return np.where(weekend, weekend_mult * (0.5 * base + flat), base)


def weather_series(rng, days: int, start: date) -> pd.DataFrame:
    rows = []
    for d in range(days):
        day = start + timedelta(days=d)
        monsoon = day.month in (6, 7, 8, 9)
        t_mean = 27 + 4 * np.sin(2 * np.pi * (day.timetuple().tm_yday - 60) / 365) + rng.normal(0, 1.2)
        rain_day = rng.random() < (0.55 if monsoon else 0.1)
        for h in range(24):
            temp = t_mean + 5 * np.sin(np.pi * (h - 8) / 12) + rng.normal(0, 0.6)
            rain = float(rng.gamma(1.5, 3.0)) if rain_day and 14 <= h <= 22 and rng.random() < 0.5 else 0.0
            rows.append((day.isoformat(), h, day.weekday(), round(temp, 1), round(rain, 1)))
    return pd.DataFrame(rows, columns=["date", "hour", "dow", "temp_c", "rain_mm"])


def demand(rng, weather: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for zone, (base, kind) in ZONES.items():
        w = weather.copy()
        weekend = (w.dow >= 5).to_numpy()
        lam = base * hour_profile(kind, w.hour.to_numpy(), weekend)
        lam *= np.where(w.rain_mm > 0, np.clip(1 - 0.06 * w.rain_mm, 0.45, 1.0), 1.0)    # rain keeps people in
        lam *= np.where(w.temp_c > 33, 0.85, 1.0)                                       # so does midday heat
        lam *= 1 + 0.15 * np.arange(len(w)) / len(w)                                    # slow growth
        w["zone"] = zone
        w["expected"] = np.round(lam, 4)        # true rate - only knowable because the data is synthetic
        w["bookings"] = rng.poisson(lam)
        frames.append(w)
    return pd.concat(frames, ignore_index=True)


def vehicles(rng):
    """Each car's BMS log is a REAL held-out NASA cell from new, cut at a random point of its life
    (so the SOH model never trained on it). The synthetic ageing run only supplies the
    accumulated stress used by the habit-based remaining-life formula."""
    from app.battery_core.ageing import SOH_FEATURES
    from data_gen.nasa_battery import TEST_CELLS
    cells = pd.read_csv(DATA_DIR / "nasa_cycles.csv")
    # A rental fleet retires packs below the usual 70% warranty threshold, so cars are cut at a point
    # where the lab measured >= 70%; cells that never measured that much (4 degC runs) are not used.
    in_service = [c for c in TEST_CELLS
                  if (np.flatnonzero(cells[cells.cell_id == c].sort_values("cycle").soh.to_numpy() >= IN_SERVICE_SOH)
                      >= 9).any()]
    rows, bms = [], []
    zones = list(ZONES)
    for i in range(N_VEHICLES):
        n = int(rng.integers(150, 1700))                          # cycles since the pack was new
        fast = float(rng.uniform(0.05, 0.75))
        temp = 27 + rng.normal(0, 2, n)
        charge_c = np.where(rng.random(n) < fast, 1.25, 0.185) + rng.normal(0, 0.03, n)
        dod = np.clip(rng.normal(0.55, 0.12, n), 0.15, 0.95)
        dis_c = np.clip(rng.normal(0.4, 0.06, n), 0.2, 0.9)
        df, state = simulate_cycles(n, temp, charge_c, dod, dis_c, rng=rng)
        vid = f"EV{i + 1:03d}"
        cell = in_service[i % len(in_service)]
        log = cells[cells.cell_id == cell].sort_values("cycle").reset_index(drop=True)
        ok = np.flatnonzero(log.soh.to_numpy() >= IN_SERVICE_SOH)
        ok = ok[ok >= 9]                                      # at least 10 cycles of history
        cut = int(rng.choice(ok)) + 1
        part = log.iloc[:cut]
        rec = part[SOH_FEATURES].copy()
        rec.insert(0, "vehicle_id", vid)
        bms.append(rec)
        rows.append({"vehicle_id": vid, "zone": zones[i % len(zones)], "cycles": state.cycle,
                     "battery_cell": cell, "lab_measured_soh": round(float(part.soh.iloc[-1]), 4),
                     "cum_stress": round(state.cum_stress, 2), "fast_charge_share": round(fast, 3),
                     "soc": round(float(rng.uniform(0.35, 0.95)), 2),
                     "status": "idle" if rng.random() < 0.8 else "rented"})
    return pd.DataFrame(rows), pd.concat(bms, ignore_index=True)


def bookings(rng, n=26):
    zones = list(ZONES)
    rows = []
    for i in range(n):
        long = rng.random() < 0.3
        dest = str(rng.choice(LONG_HAUL)) if long else None
        rows.append({"booking_id": f"B{i + 1:03d}", "zone": str(rng.choice(zones)),
                     "kind": "long_haul" if long else "urban",
                     "km": round(float(rng.uniform(140, 320) if long else rng.uniform(12, 70)), 0),
                     "destination": dest, "hours": int(rng.integers(8, 30) if long else rng.integers(2, 6))})
    return pd.DataFrame(rows)


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(31)
    start = date.today() - timedelta(days=DAYS)
    w = weather_series(rng, DAYS, start)
    d = demand(rng, w)
    d.to_csv(DATA_DIR / "fleet_demand.csv", index=False)
    v, bms = vehicles(rng)
    v.to_csv(DATA_DIR / "fleet_vehicles.csv", index=False)
    bms.to_csv(DATA_DIR / "fleet_bms.csv", index=False)
    b = bookings(rng)
    b.to_csv(DATA_DIR / "fleet_bookings.csv", index=False)
    print(f"fleet_demand.csv: {len(d)} rows ({d.bookings.sum()} bookings over {DAYS} days, {len(ZONES)} zones)")
    print(f"fleet_vehicles.csv: {len(v)} vehicles; fleet_bookings.csv: {len(b)} requests "
          f"({(b.kind == 'long_haul').sum()} long-haul)")


if __name__ == "__main__":
    main()
