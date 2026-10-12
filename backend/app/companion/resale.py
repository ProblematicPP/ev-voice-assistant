"""Synthetic resale-value estimate driven by battery SOH, plus a 2-year projection
showing how charging habits change future SOH (and therefore value).

The depreciation formula is illustrative, not a market model.
"""
from __future__ import annotations

from datetime import date

import numpy as np

from app.battery_core.ageing import AgeingState, fade_from_stress, simulate_cycles

YEARLY_DEPRECIATION = 0.13
CYCLES_PER_YEAR = 226          # matches the owner's BMS history rate


def battery_factor(soh: float) -> float:
    """Buyers discount heavily as SOH approaches the 70% warranty threshold."""
    return 0.62 + 0.38 * float(np.clip((soh - 0.70) / 0.30, 0, 1))


def value_inr(price: float, age_years: float, odometer_km: float, soh: float) -> float:
    base = price * (1 - YEARLY_DEPRECIATION) ** age_years
    expected_km = 12_000 * age_years
    mileage = float(np.clip(1 - 0.0000025 * (odometer_km - expected_km), 0.85, 1.05))
    return base * mileage * battery_factor(soh)


def project_soh(soh_now: float, ageing: dict, years: float, fast_share: float, temp_c=27.0, dod=0.45) -> float:
    """Advance the ageing model and apply its *additional* fade to today's ML-estimated SOH."""
    n = int(CYCLES_PER_YEAR * years)
    start = AgeingState(ageing["cycle"], ageing["cum_stress"], ageing["fast_cycles"])
    charge_c = np.where(np.arange(n) % 100 < fast_share * 100, 1.25, 0.185)
    _, end = simulate_cycles(n, temp_c, charge_c, dod, 0.35, rng=None, start=start)
    extra = float(fade_from_stress(end.cum_stress) - fade_from_stress(start.cum_stress))
    return max(0.5, soh_now - extra)


def estimate(profile: dict, soh: float, recent_fast_share: float) -> dict:
    age = (date.today() - date.fromisoformat(profile["purchase_date"])).days / 365.25
    price, odo = profile["purchase_price_inr"], profile["odometer_km"]
    now = value_inr(price, age, odo, soh)
    perfect = value_inr(price, age, odo, 1.0)

    yrs = 2.0
    odo_future = odo + 12_000 * yrs
    scenarios = []
    for label, share in [("Mostly slow charging", 0.05), ("Current habits", recent_fast_share),
                         ("Fast charging most days", 0.60)]:
        s = project_soh(soh, profile["ageing_state"], yrs, share)
        scenarios.append({"label": label, "fast_charge_share": round(share, 2), "soh": round(s, 4),
                          "value_inr": round(value_inr(price, age + yrs, odo_future, s), -3)})
    return {
        "age_years": round(age, 1),
        "odometer_km": odo,
        "soh": round(soh, 4),
        "estimated_value_inr": round(now, -3),
        "battery_health_impact_inr": round(now - perfect, -3),
        "projection_years": yrs,
        "projections": scenarios,
        "habit_value_gap_inr": round(scenarios[0]["value_inr"] - scenarios[1]["value_inr"], -3),
        "disclaimer": "Synthetic estimate for demonstration - not a market valuation.",
    }
