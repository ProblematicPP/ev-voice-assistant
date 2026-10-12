"""Range-drop attribution: why is range lower than expected?

Uses exact Shapley values over a handful of human-meaningful factors. For each
factor we compare "current value" vs a reference value; every subset of
factors is evaluated through the trained range model (2^5 = 32 evaluations,
batched), so the contributions add up exactly to the total drop.
"""
from __future__ import annotations

from itertools import combinations
from math import factorial

import numpy as np

from app.battery_core.range_model import CITY_SPEED, HIGHWAY_SPEED, RangeModel, usable_kwh

# factor -> (condition key, reference value)
REFERENCE = {
    "weather": ("ambient_temp_c", 25.0),
    "climate_control": ("hvac_mode", "off"),
    "driving_style": ("driving_style", 0.40),
    "load": ("payload_kg", 75.0),
    "battery_age": ("soh", 1.0),
}

LABELS = {
    "weather": "Outside temperature",
    "climate_control": "AC / heater use",
    "driving_style": "Driving style",
    "load": "Passengers & luggage",
    "battery_age": "Battery ageing",
}


def _describe(factor: str, cond: dict) -> str:
    if factor == "weather":
        t = cond["ambient_temp_c"]
        return f"{t:.0f} °C outside" + (" (cold hurts battery efficiency)" if t < 18 else
                                         " (hot - cabin cooling works harder)" if t > 30 else "")
    if factor == "climate_control":
        return {"off": "climate off", "fan": "fan only", "ac": "AC on", "heat": "heater on"}[cond["hvac_mode"]]
    if factor == "driving_style":
        s = cond["driving_style"]
        word = "aggressive" if s > 0.65 else "brisk" if s > 0.5 else "smooth" if s < 0.3 else "moderate"
        return f"{word} acceleration/braking (score {s:.2f} vs 0.40 typical)"
    if factor == "load":
        return f"{cond.get('payload_kg', 75):.0f} kg on board"
    if factor == "battery_age":
        return f"SOH {cond['soh'] * 100:.0f}% - {100 - cond['soh'] * 100:.0f}% less usable capacity"
    return ""


def _short(factor: str, cond: dict) -> str:
    return {
        "weather": f"{cond['ambient_temp_c']:.0f} °C weather",
        "climate_control": {"ac": "AC on", "heat": "heater on", "fan": "fan", "off": "climate off"}[cond["hvac_mode"]],
        "driving_style": "brisk driving" if cond["driving_style"] > 0.5 else "driving style",
        "load": f"{cond.get('payload_kg', 75):.0f} kg load",
        "battery_age": f"battery at {cond['soh'] * 100:.0f}% health",
    }[factor]


def explain(model: RangeModel, soc: float, cond: dict, highway_share: float) -> dict:
    factors = list(REFERENCE)
    n = len(factors)
    subsets = [frozenset(c) for r in range(n + 1) for c in combinations(factors, r)]

    # Build every hybrid condition (factors in S at current value, others at reference)
    rows, soh_for = [], []
    for S in subsets:
        c = dict(cond)
        for f in factors:
            if f not in S:
                key, ref = REFERENCE[f]
                c[key] = ref
        soh_for.append(c["soh"])
        rows.append(model.segment_conditions(c, "city", CITY_SPEED))
        rows.append(model.segment_conditions(c, "highway", HIGHWAY_SPEED))
    whkm = model.wh_per_km(rows).reshape(-1, 2)
    mixed = (1 - highway_share) * whkm[:, 0] + highway_share * whkm[:, 1]
    rng_km = np.array([usable_kwh(s) * soc * 1000 / w for s, w in zip(soh_for, mixed)])
    value = dict(zip(subsets, rng_km))

    phi = {}
    for f in factors:
        total = 0.0
        for S in subsets:
            if f in S:
                continue
            w = factorial(len(S)) * factorial(n - len(S) - 1) / factorial(n)
            total += w * (value[S | {f}] - value[S])
        phi[f] = total

    expected = float(value[frozenset()])
    current = float(value[frozenset(factors)])
    contributions = sorted(
        ({"factor": f, "label": LABELS[f], "km": round(phi[f], 1), "detail": _describe(f, cond)} for f in factors),
        key=lambda x: x["km"],
    )
    drop = expected - current
    top = [c for c in contributions if c["km"] < -1.0][:3]
    if drop <= 1:
        summary = "Your range is right where it should be for this charge level."
    else:
        parts = [f"{_short(c['factor'], cond)} (-{-c['km']:.0f} km)" for c in top]
        summary = (f"You have about {current:.0f} km at {soc * 100:.0f}% instead of {expected:.0f} km "
                   f"(new pack, 25 °C, AC off, typical driving). Biggest factors: " + ", ".join(parts) + ".")
        gains = [c for c in contributions if c["km"] > 1.0]
        if gains:
            summary += f" {gains[0]['label']} is helping by {gains[0]['km']:.0f} km."
    return {
        "expected_km": round(expected, 1),
        "current_km": round(current, 1),
        "drop_km": round(drop, 1),
        "drop_pct": round(100 * drop / expected, 1) if expected else 0.0,
        "contributions": contributions,
        "reference": {k: v[1] for k, v in REFERENCE.items()},
        "method": "exact Shapley values over 5 factors (32 model evaluations)",
        "summary": summary,
    }
