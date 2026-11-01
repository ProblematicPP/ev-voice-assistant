"""Degradation projection and remaining useful life (RUL).

Takes today's ML-estimated SOH and advances the semi-empirical ageing model
(ageing.py) under a chosen charging habit. Only the *additional* fade from now on
is added, so the projection starts exactly at the SOH model's estimate.

Used by the companion (2-year resale projection), the fleet module (battery-aware
allocation) and the evaluation - always through BatteryCore.
"""
from __future__ import annotations

import numpy as np

from app.battery_core.ageing import cycle_stress, fade_from_stress

CYCLES_PER_YEAR = 226          # matches the owner's BMS history rate
EOL_SOH = 0.70                 # typical EV battery warranty threshold
FAST_C, SLOW_C = 1.25, 0.185   # charge C-rates of DC fast vs home AC sessions


def extra_fade(cum_stress0: float, n_cycles: int, fast_share: float, temp_c: float = 27.0,
               dod: float = 0.45) -> np.ndarray:
    """Additional capacity fade after each of the next n cycles (deterministic)."""
    charge_c = np.where(np.arange(n_cycles) % 100 < fast_share * 100, FAST_C, SLOW_C)
    cum = cum_stress0 + np.cumsum(cycle_stress(temp_c, charge_c, dod))
    return fade_from_stress(cum) - fade_from_stress(cum_stress0)


def project_soh(soh_now: float, cum_stress0: float, years: float, fast_share: float,
                temp_c: float = 27.0, dod: float = 0.45) -> float:
    n = int(CYCLES_PER_YEAR * years)
    if n <= 0:
        return soh_now
    return max(0.5, soh_now - float(extra_fade(cum_stress0, n, fast_share, temp_c, dod)[-1]))


def remaining_life(soh_now: float, cum_stress0: float, fast_share: float, eol: float = EOL_SOH,
                   temp_c: float = 27.0, dod: float = 0.45, max_years: float = 30.0) -> dict:
    """Cycles and years until SOH reaches `eol` under a steady charging habit."""
    n = int(CYCLES_PER_YEAR * max_years)
    soh = soh_now - extra_fade(cum_stress0, n, fast_share, temp_c, dod)
    hit = np.flatnonzero(soh <= eol)
    cycles = int(hit[0]) + 1 if len(hit) else n
    return {"eol_soh": eol, "cycles": cycles, "years": round(cycles / CYCLES_PER_YEAR, 1),
            "capped": not len(hit), "fast_charge_share": round(fast_share, 2)}


def trip_stress(depth: float, charge_c: float = SLOW_C, temp_c: float = 27.0) -> float:
    """Ageing stress from one discharge of `depth` (fraction of usable capacity) and its recharge."""
    return float(cycle_stress(temp_c, charge_c, min(max(depth, 0.0), 1.0)))


def soh_after(soh_now: float, cum_stress0: float, added_stress: float) -> float:
    """SOH once `added_stress` more ageing has accumulated on top of cum_stress0."""
    return max(0.5, soh_now - float(fade_from_stress(cum_stress0 + added_stress) - fade_from_stress(cum_stress0)))
