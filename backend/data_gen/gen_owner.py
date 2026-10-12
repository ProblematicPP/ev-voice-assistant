"""Synthetic history for the single demo vehicle and its owner.

Simulates 90 days of driving + charging with a consistent SOC trace, plus the
pack's BMS cycle log since purchase.

Outputs:
  data/owner_trips.csv          the owner's recent trips (drives personalization)
  data/charging_history.csv     charging sessions (drives habit coaching / cost)
  data/vehicle_bms_history.csv  per-cycle BMS features since purchase (SOH model input)
  data/vehicle_profile.json     static vehicle + derived owner profile
"""
import json
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from app.battery_core.ageing import simulate_cycles
from app.config import DATA_DIR, HOME_PEAK_TARIFF_INR, HOME_TARIFF_INR, VEHICLE
from data_gen.gen_network import CHARGERS
from data_gen.physics import wh_per_km

DAYS = 90
CHARGER_BY_ID = {c[0]: c for c in CHARGERS}

# name, distance_km, highway_share, destination node
LONG_TRIPS = [("Mysuru weekend", 145, 0.85, "mysuru"), ("Airport drop", 38, 0.6, "devanahalli"),
              ("Nandi Hills", 62, 0.6, "chikkaballapur"), ("Tumakuru visit", 72, 0.75, "tumakuru")]


def _trip_energy(rng, km, hwy_share, temp, hvac, style, soh, payload=75):
    city = wh_per_km(temp, hvac, style, rng.uniform(18, 30), rng.normal(0, 1.5), payload, "city", soh, rng=rng)
    hwy = wh_per_km(temp, hvac, style, rng.uniform(65, 90), rng.normal(0, 1.5), payload, "highway", soh, rng=rng)
    whkm = float((1 - hwy_share) * city + hwy_share * hwy)
    return whkm, whkm * km / 1000


def _charge_minutes(kwh_needed, soc_start, soc_end, power_kw, usable):
    # Constant power to 80 %, then taper to ~35 % power
    to80 = max(0.0, min(soc_end, 0.8) - soc_start) * usable
    above = max(0.0, soc_end - max(soc_start, 0.8)) * usable
    return 60 * (to80 / power_kw + above / (power_kw * 0.35))


def simulate_owner(seed=21, soh=0.90, end_day: date | None = None):
    rng = np.random.default_rng(seed)
    end_day = end_day or date.today()
    start_day = end_day - timedelta(days=DAYS - 1)
    usable = VEHICLE["nominal_kwh"] * VEHICLE["usable_fraction"] * soh
    style_mu = 0.62
    soc = 0.85
    trips, sessions = [], []
    long_days = set(rng.choice(np.arange(5, DAYS - 3), size=6, replace=False).tolist())

    def charge(day, hour, charger_id, target):
        nonlocal soc
        cid, node, name, power, price, kind = CHARGER_BY_ID[charger_id]
        power = min(power, VEHICLE["max_dc_kw"] if kind == "dc_fast" else VEHICLE["max_ac_kw"])
        kwh = max(0.0, (target - soc) * usable) / 0.92        # charging losses
        if kwh < 1.0:
            return
        mins = _charge_minutes(kwh, soc, target, power, usable)
        start = datetime.combine(day, datetime.min.time()) + timedelta(hours=hour, minutes=int(rng.integers(0, 50)))
        if kind == "home_ac":
            # Starting before 22:00 bills the first hours at the peak tariff (simplified)
            peak_hours = max(0.0, min(22, start.hour + mins / 60) - start.hour) if 18 <= start.hour < 22 else 0.0
            peak_kwh = min(kwh, peak_hours * power)
            cost = peak_kwh * HOME_PEAK_TARIFF_INR + (kwh - peak_kwh) * HOME_TARIFF_INR
        else:
            cost = kwh * price
        amb = 24 + 8 * np.sin(np.pi * (start.hour - 8) / 12) + rng.normal(0, 1.5)
        bat_t = amb + (9 + power / 12 if kind == "dc_fast" else 3) + rng.normal(0, 1)
        sessions.append({
            "session_id": f"S{len(sessions) + 1:04d}",
            "start_ts": start.isoformat(timespec="minutes"),
            "end_ts": (start + timedelta(minutes=mins)).isoformat(timespec="minutes"),
            "charger_id": cid, "charger_name": name, "charger_type": kind, "power_kw": power,
            "soc_start": round(soc, 3), "soc_end": round(target, 3), "kwh": round(kwh, 2),
            "cost_inr": round(cost, 1), "location": node, "battery_temp_max_c": round(bat_t, 1),
        })
        soc = target

    def drive(day, hour, label, km, hwy_share, dest):
        nonlocal soc
        temp = 23 + 9 * np.sin(np.pi * (hour - 8) / 12) + rng.normal(0, 1.5)
        hvac = "ac" if temp > 27 or rng.random() < 0.3 else rng.choice(["off", "fan"])
        style = float(np.clip(rng.normal(style_mu, 0.08), 0, 1))
        whkm, kwh = _trip_energy(rng, km, hwy_share, temp, hvac, style, soh)
        soc_start = soc
        soc = max(0.03, soc - kwh / usable)
        trips.append({
            "trip_id": f"T{len(trips) + 1:04d}",
            "start_ts": (datetime.combine(day, datetime.min.time()) + timedelta(hours=hour)).isoformat(timespec="minutes"),
            "label": label, "destination": dest, "distance_km": round(km, 1),
            "highway_share": hwy_share, "ambient_temp_c": round(temp, 1), "hvac_mode": hvac,
            "driving_style": round(style, 3), "wh_per_km": round(whkm, 1), "energy_kwh": round(kwh, 2),
            "soc_start": round(soc_start, 3), "soc_end": round(soc, 3),
        })

    for d in range(DAYS):
        day = start_day + timedelta(days=d)
        busy_week = d >= DAYS - 7                    # recent week: lots of fast charging
        weekend = day.weekday() >= 5
        if d in long_days:
            label, km, hwy, dest = LONG_TRIPS[int(rng.integers(len(LONG_TRIPS)))]
            if soc < 0.9:
                charge(day - timedelta(days=0), 6, "home", 1.0)
            drive(day, 9, label, km, hwy, dest)
            if soc < 0.35:
                near = {"mysuru": "ch_mysuru", "devanahalli": "ch_airport", "tumakuru": "ch_tumakuru"}
                charge(day, 13, near.get(dest, "ch_kengeri"), 0.8)
            drive(day, 16, label + " (return)", km, hwy, "koramangala")
        elif weekend:
            for _ in range(int(rng.integers(1, 4))):
                drive(day, int(rng.integers(10, 20)), "Errand", rng.uniform(4, 18), 0.0, "koramangala")
        else:
            drive(day, 9, "Commute to office", rng.uniform(20, 24), 0.0, "whitefield")
            if busy_week and rng.random() < 0.75:
                charge(day, 13, rng.choice(["ch_indira", "ch_ecity"]), float(rng.choice([0.8, 0.9])))
            elif rng.random() < 0.15:
                charge(day, 10, "ch_wf", 0.8)
            drive(day, 18, "Commute home", rng.uniform(20, 24), 0.0, "koramangala")
            if rng.random() < 0.4:
                drive(day, 20, "Errand", rng.uniform(3, 12), 0.0, "koramangala")

        if soc < 0.25 and rng.random() < 0.5:
            charge(day, 21, rng.choice(["ch_indira", "ch_ecity"]), 0.8)
        elif soc < 0.55 or rng.random() < 0.2:
            target = 1.0 if rng.random() < 0.45 else 0.8
            charge(day, int(rng.choice([19, 20, 23])), "home", target)

    return pd.DataFrame(trips), pd.DataFrame(sessions), soc


def simulate_bms_history(seed=5, fast_share=0.22):
    """Pack ageing since purchase: ~1.5 charge sessions every 2 days for ~3.3 years."""
    rng = np.random.default_rng(seed)
    days = (date.today() - date.fromisoformat(VEHICLE["purchase_date"])).days
    n = int(days * 0.62)
    temp = 27 + 4 * np.sin(np.linspace(0, days / 365 * 2 * np.pi, n)) + rng.normal(0, 1.5, n)
    charge_c = np.where(rng.random(n) < fast_share, 1.25, 0.185) + rng.normal(0, 0.03, n)
    dod = np.clip(rng.normal(0.45, 0.12, n), 0.15, 0.95)
    dis_c = np.clip(rng.normal(0.35, 0.05, n), 0.2, 0.8)
    df, state = simulate_cycles(n, temp, charge_c, dod, dis_c, rng=rng)
    df = df.drop(columns=["capacity_ah", "soh"])   # the car doesn't know its true SOH
    df.insert(0, "date", pd.date_range(end=pd.Timestamp(date.today()), periods=n).date.astype(str))
    return df, state, days


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    bms, ageing_state, age_days = simulate_bms_history()
    bms.to_csv(DATA_DIR / "vehicle_bms_history.csv", index=False)

    trips, sessions, final_soc = simulate_owner()
    trips.to_csv(DATA_DIR / "owner_trips.csv", index=False)
    sessions.to_csv(DATA_DIR / "charging_history.csv", index=False)

    km_total = trips.distance_km.sum()
    profile = {
        **VEHICLE,
        "odometer_km": round(age_days * 31.5),
        "bms_cycle_count": ageing_state.cycle,
        "ageing_state": {"cycle": ageing_state.cycle, "cum_stress": ageing_state.cum_stress,
                         "fast_cycles": ageing_state.fast_cycles},
        # Personalization derived from the owner's own trips
        "driving_style": round(float(np.average(trips.driving_style, weights=trips.distance_km)), 3),
        "highway_share": round(float((trips.distance_km * trips.highway_share).sum() / km_total), 3),
        "typical_wh_per_km": round(float((trips.energy_kwh.sum() * 1000) / km_total), 1),
        "soc_at_generation": round(final_soc, 3),
    }
    (DATA_DIR / "vehicle_profile.json").write_text(json.dumps(profile, indent=2))
    print(f"vehicle_bms_history.csv: {len(bms)} cycles")
    print(f"owner_trips.csv: {len(trips)} trips, {km_total:.0f} km")
    print(f"charging_history.csv: {len(sessions)} sessions "
          f"({(sessions.charger_type == 'dc_fast').sum()} DC fast)")
    print(f"owner driving_style={profile['driving_style']}, highway_share={profile['highway_share']}")


if __name__ == "__main__":
    main()
