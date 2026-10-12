"""Battery guard: every routing / charging / energy-consuming action passes here
before it executes. The LLM never decides feasibility - this module does.

Each check returns a GuardDecision:
  allow    - may the action execute?
  status   - machine-readable verdict
  reasons  - human-readable facts behind the verdict
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from app.config import COMFORT_SOC, DC_TARGET_SOC, HARD_MIN_SOC, RESERVE_SOC


@dataclass
class GuardDecision:
    allow: bool
    status: str
    reasons: list[str] = field(default_factory=list)
    data: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)


def pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def assess_plan(plan: dict) -> GuardDecision:
    """Verify a planned route against the SOC trace before activating it."""
    if plan["status"] == "infeasible":
        alts = plan.get("reachable_chargers", [])
        reasons = [f"Can't reach {plan['destination_names'][-1]} even with charging stops from "
                   f"{pct(plan['totals']['start_soc'])}."]
        if alts:
            reasons.append(f"Nearest reachable charger: {alts[0]['name']} ({alts[0]['distance_km']} km, "
                           f"arrive at {pct(alts[0]['arrive_soc'])}).")
        return GuardDecision(False, "infeasible", reasons, {"reachable_chargers": alts})

    low = [l for l in plan["legs"]
           if l["soc_arrive"] < (HARD_MIN_SOC if l.get("ends_at_charger") else RESERVE_SOC) - 1e-6]
    if low:  # planner bug guard - should never happen
        return GuardDecision(False, "unsafe_leg", [f"Leg to {low[0]['to']} arrives below reserve."])

    arr = plan["totals"]["arrival_soc"]
    reasons = [f"Arrive with {pct(arr)}."]
    if plan["stops"]:
        names = ", ".join(f"{s['name']} ({pct(s['arrive_soc'])}→{pct(s['depart_soc'])})" for s in plan["stops"])
        reasons.insert(0, f"Needs {len(plan['stops'])} charging stop(s): {names}.")
        return GuardDecision(True, "ok_with_charge_stop", reasons)
    if arr < COMFORT_SOC:
        reasons.append(f"That's below the {pct(COMFORT_SOC)} comfort margin - drive gently, consider a top-up.")
        return GuardDecision(True, "ok_low_margin", reasons)
    return GuardDecision(True, "ok", reasons)


def assess_climate_change(range_before_km: float, range_after_km: float, soc: float) -> GuardDecision:
    loss = range_before_km - range_after_km
    reasons = [f"Range {range_before_km:.0f} → {range_after_km:.0f} km ({-loss:+.0f} km)."]
    if soc < 0.12 and loss > 0:
        return GuardDecision(False, "blocked_low_soc",
                             reasons + ["Battery is critically low; keeping climate as-is to protect range."])
    return GuardDecision(True, "ok", reasons)


def assess_precool(plugged_in: bool, soc: float, kwh_needed: float, usable_kwh: float) -> GuardDecision:
    if plugged_in:
        return GuardDecision(True, "ok_grid_power", ["Car is plugged in - pre-cooling uses grid power, no range cost."])
    soc_cost = kwh_needed / usable_kwh
    if soc - soc_cost < 0.20:
        return GuardDecision(False, "blocked_low_soc",
                             [f"Not plugged in and only {pct(soc)} left; pre-cooling would use "
                              f"{pct(soc_cost)} of the battery."])
    return GuardDecision(True, "ok_battery_power", [f"Uses about {pct(soc_cost)} of battery (not plugged in)."])


def assess_charge_target(target_soc: float, charger_kind: str) -> GuardDecision:
    if charger_kind == "dc_fast" and target_soc > DC_TARGET_SOC:
        return GuardDecision(True, "ok_with_advice",
                             [f"Above {pct(DC_TARGET_SOC)} DC charging slows sharply and adds heat stress."])
    return GuardDecision(True, "ok", [])
