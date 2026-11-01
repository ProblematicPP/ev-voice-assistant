"""Eco-driving coaching from telemetry: harsh braking / acceleration and what smoothing out is worth.

The km gain comes from the battery core (same range model as everywhere else): range at
the owner's current driving-style score vs at a smooth score.
"""
from __future__ import annotations

from dataclasses import replace

from app.telemetry import harsh_rate_per_km

SMOOTH_STYLE = 0.40
TYPICAL_PER_100KM = round(100 * harsh_rate_per_km(SMOOTH_STYLE), 1)     # a smooth driver's event rate


def coach(core, state, history: dict, recent: dict | None) -> dict:
    """history / recent: telemetry.summarize() outputs for the owner's past trips and today's drive."""
    now_km = core.range_km(state)
    smooth_km = core.range_km(replace(state, driving_style=min(state.driving_style, SMOOTH_STYLE)))
    gain = max(0.0, smooth_km - now_km)
    rate = history["events_per_100km"]
    tips = []
    if history["harsh_brakes_per_100km"] >= 2 * TYPICAL_PER_100KM * 0.6:
        tips.append({"id": "harsh_braking", "severity": "warn", "title": "Brake earlier and lighter",
                     "message": f"{history['harsh_brakes_per_100km']:.1f} harsh brakes per 100 km. Lifting off "
                                f"earlier lets regenerative braking recover energy instead of wasting it as heat."})
    if history["harsh_accels_per_100km"] >= 2 * TYPICAL_PER_100KM * 0.4:
        tips.append({"id": "harsh_accel", "severity": "warn", "title": "Ease off at take-off",
                     "message": f"{history['harsh_accels_per_100km']:.1f} hard accelerations per 100 km. Pulling "
                                f"away gently from signals uses noticeably less energy in city traffic."})
    if gain >= 1:
        tips.append({"id": "smooth_gain", "severity": "info", "title": f"Smoother driving adds about {gain:.0f} km",
                     "message": f"At today's charge you'd get about {smooth_km:.0f} km instead of {now_km:.0f} km "
                                f"by driving as smoothly as a typical calm driver."})
    if not tips:
        tips.append({"id": "smooth_ok", "severity": "ok", "title": "Smooth driving",
                     "message": "Few harsh brakes or accelerations - your driving is easy on range and brakes."})
    return {"history": history, "recent_drive": recent, "typical_events_per_100km": TYPICAL_PER_100KM,
            "events_vs_typical": round(rate / TYPICAL_PER_100KM, 1) if TYPICAL_PER_100KM else None,
            "range_gain_km": round(gain, 1), "tips": tips}
