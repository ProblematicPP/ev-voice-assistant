"""PREDICTIVE PRE-COOLING - HARDWARE-DEPENDENT STUB (future phase).

!!! This is NOT a real implementation. !!!
A production version would command the HVAC controller through the telematics
unit, scheduled from the owner's predicted departure time. Here we only compute
the energy estimate (battery-core grounded) and return what it *would* do.
"""
from __future__ import annotations


def plan(minutes: int, target_c: float, ambient_c: float, plugged_in: bool, hvac_kw: float) -> dict:
    kwh = hvac_kw * minutes / 60.0 * 1.3          # pull-down from hot soak costs extra
    source = "plug (grid) power" if plugged_in else "the traction battery"
    return {
        "stub": True,
        "minutes": minutes,
        "target_c": target_c,
        "ambient_c": ambient_c,
        "energy_kwh": round(kwh, 2),
        "power_source": "grid" if plugged_in else "battery",
        "would_do": f"Would start cabin pre-cooling to {target_c:.0f} °C for {minutes} min using {source}.",
        "note": "Hardware-dependent stub - HVAC was not actually commanded.",
    }
