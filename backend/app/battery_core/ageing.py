"""Physics-inspired cell ageing simulator.

Used in two places:
  * data_gen/ - to synthesize NASA/CALCE-shaped cycling data for training
  * companion/resale - to project future SOH under different charging habits

This is a semi-empirical model, not an electrochemical one:
capacity fade ~ sqrt(stress-weighted cycles) + a late "knee", where stress grows
with temperature (Arrhenius-like), charge C-rate and depth of discharge.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

Q0_AH = 2.0          # nominal cell capacity (18650-like, as in the NASA set)
R0_MOHM = 55.0       # fresh internal resistance

SOH_FEATURES = [
    "cycle",
    "ambient_temp_c",
    "charge_c_rate",
    "fast_charge_ratio",
    "depth_of_discharge",
    "discharge_c_rate",
    "internal_resistance_mohm",
    "v_mean",
    "v_min",
    "t_max_c",
]


def cycle_stress(temp_c, charge_c, dod):
    """Relative ageing per cycle; 1.0 = 25 degC, 0.5C charge, 67% DoD."""
    temp_c, charge_c, dod = np.asarray(temp_c), np.asarray(charge_c), np.asarray(dod)
    return (
        np.exp(0.045 * (temp_c - 25.0))
        * (1.0 + 0.55 * np.maximum(0.0, charge_c - 0.5))
        * (0.6 + 0.6 * dod)
    )


def fade_from_stress(cum_stress):
    cum_stress = np.asarray(cum_stress, dtype=float)
    return 0.0034 * np.sqrt(cum_stress) + 0.00018 * np.maximum(0.0, cum_stress - 1100.0)


@dataclass
class AgeingState:
    cycle: int = 0
    cum_stress: float = 0.0
    fast_cycles: int = 0


def simulate_cycles(
    n_cycles: int,
    ambient_temp_c,
    charge_c_rate,
    dod,
    discharge_c_rate,
    rng: np.random.Generator | None = None,
    start: AgeingState | None = None,
) -> tuple[pd.DataFrame, AgeingState]:
    """Simulate n cycles. Scalar or per-cycle arrays accepted for the stress inputs.

    Returns one row per cycle with BMS-observable features plus the target `soh`.
    Pass rng=None for a deterministic (noise-free) projection.
    """
    start = start or AgeingState()
    noisy = rng is not None
    rng = rng or np.random.default_rng(0)

    def arr(x):
        a = np.asarray(x, dtype=float)
        return np.full(n_cycles, float(a)) if a.ndim == 0 else a[:n_cycles]

    temp, cc, d, dc = arr(ambient_temp_c), arr(charge_c_rate), arr(dod), arr(discharge_c_rate)
    stress = cycle_stress(temp, cc, d)
    cum = start.cum_stress + np.cumsum(stress)
    soh_true = 1.0 - fade_from_stress(cum)

    soh_obs = soh_true.copy()
    if noisy:
        # Capacity "regeneration" after rest periods (visible in the NASA data):
        # a small bump that decays over a few cycles.
        bumps = np.zeros(n_cycles)
        for i in np.flatnonzero(rng.random(n_cycles) < 0.02):
            amp = rng.uniform(0.004, 0.015)
            span = min(8, n_cycles - i)
            bumps[i : i + span] += amp * np.exp(-np.arange(span) / 2.5)
        soh_obs = soh_true + bumps + rng.normal(0, 0.003, n_cycles)
    soh_obs = np.clip(soh_obs, 0.5, 1.0)

    def noise(scale):
        return rng.normal(0, scale, n_cycles) if noisy else 0.0

    ir = R0_MOHM * (1 + 2.2 * (1 - soh_true)) * np.exp(-0.012 * (temp - 25)) + noise(1.5)
    current_a = dc * Q0_AH
    v_mean = 3.70 - 0.45 * (1 - soh_true) - 0.5 * current_a * ir / 1000 + 0.002 * (temp - 25) + noise(0.008)
    v_min = 2.70 + 0.9 * (1 - d) - 0.3 * (1 - soh_true) + noise(0.02)
    t_max = temp + 2.5 + 6 * dc**2 * (ir / R0_MOHM) + 3 * cc**2 + noise(0.6)

    fast = cc > 1.0
    fast_cum = start.fast_cycles + np.cumsum(fast)
    cycles = start.cycle + np.arange(1, n_cycles + 1)

    df = pd.DataFrame(
        {
            "cycle": cycles,
            "ambient_temp_c": temp,
            "charge_c_rate": cc,
            "fast_charge_ratio": fast_cum / cycles,
            "depth_of_discharge": d,
            "discharge_c_rate": dc,
            "internal_resistance_mohm": ir,
            "v_mean": v_mean,
            "v_min": v_min,
            "t_max_c": t_max,
            "capacity_ah": soh_obs * Q0_AH,
            "soh": soh_obs,
        }
    )
    end = AgeingState(int(cycles[-1]), float(cum[-1]), int(fast_cum[-1]))
    return df, end


def cycle_timeseries(soh: float, ambient_temp_c: float, charge_c: float, dod: float,
                     discharge_c: float, dt_s: float = 10.0, rng=None) -> pd.DataFrame:
    """One charge/discharge cycle as a time series (voltage, current, temp, SOC).

    Purely illustrative - shows the raw signal shape the per-cycle features come from.
    """
    rng = rng or np.random.default_rng(0)
    q = soh * Q0_AH
    ir = R0_MOHM * (1 + 2.2 * (1 - soh)) / 1000.0

    def ocv(s):
        return 3.0 + 1.05 * s + 0.15 * np.tanh(8 * (s - 0.1)) - 0.08 * np.exp(-30 * s)

    rows, t, soc, temp = [], 0.0, 1.0, ambient_temp_c
    i_dis = discharge_c * Q0_AH
    while soc > 1 - dod:                                   # constant-current discharge
        soc -= i_dis * dt_s / 3600 / q
        temp += (i_dis**2 * ir * 0.02 - 0.01 * (temp - ambient_temp_c)) * dt_s / 10
        rows.append((t, ocv(soc) - i_dis * ir, -i_dis, temp, soc, "discharge"))
        t += dt_s
    i_ch = charge_c * Q0_AH
    while soc < 0.999 and i_ch > 0.05 * Q0_AH:             # CC then CV charge
        v = ocv(soc) + i_ch * ir
        if v >= 4.2:
            i_ch *= 0.97
            v = 4.2
        soc = min(1.0, soc + i_ch * dt_s / 3600 / q)
        temp += (i_ch**2 * ir * 0.02 - 0.01 * (temp - ambient_temp_c)) * dt_s / 10
        rows.append((t, v, i_ch, temp, soc, "charge"))
        t += dt_s
    df = pd.DataFrame(rows, columns=["time_s", "voltage_v", "current_a", "temperature_c", "soc", "phase"])
    df["voltage_v"] += rng.normal(0, 0.003, len(df))
    df["temperature_c"] += rng.normal(0, 0.1, len(df))
    return df
