"""Battery guard: every action the assistant can take passes through `check()` before it
executes. The LLM never decides feasibility - this module does.

`check(action, **context)` is the single entry point. It returns a GuardDecision:
  verdict        - "allow" | "modify" | "refuse"
                   (modify = allowed only with a change the guard made, e.g. a charging stop)
  allow          - may the action execute? (False only for "refuse")
  status         - machine-readable detail, e.g. "ok_with_charge_stop", "blocked_low_soc"
  reasons        - human-readable facts behind the verdict
  proposed_stop  - the charging stop that makes it work, when there is one

The assess_* functions below are the per-action rules `check()` dispatches to.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from app.config import COMFORT_SOC, DC_TARGET_SOC, HARD_MIN_SOC, RESERVE_SOC

MODIFY_STATUSES = {"ok_with_charge_stop"}


@dataclass
class GuardDecision:
    allow: bool
    status: str
    reasons: list[str] = field(default_factory=list)
    data: dict = field(default_factory=dict)
    action: str = ""
    proposed_stop: dict | None = None

    @property
    def verdict(self) -> str:
        if not self.allow:
            return "refuse"
        return "modify" if self.status in MODIFY_STATUSES else "allow"

    @property
    def reason(self) -> str:
        return " ".join(self.reasons)

    def to_dict(self):
        return {**asdict(self), "verdict": self.verdict, "reason": self.reason}


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


def assess_direct(plan: dict, explicit: bool) -> GuardDecision:
    """A route without charging stops. Below the reserve it still goes ahead, with a warning -
    the driver decides. `explicit` = the driver asked to skip charging; then we go as low as
    actually reaching the destination, otherwise only down to the hard floor."""
    arr = min(l["soc_arrive"] for l in plan["legs"])
    dest = plan["destination_names"][-1]
    if arr <= 0:
        return GuardDecision(False, "would_run_out", [f"Not enough charge to reach {dest} without charging."])
    if not explicit and arr < HARD_MIN_SOC:
        return GuardDecision(False, "below_hard_min", [f"Would reach {dest} with only {pct(arr)}."])
    if arr < RESERVE_SOC:
        return GuardDecision(True, "ok_below_reserve",
                             [f"Arrive with only {pct(arr)}, below the {pct(RESERVE_SOC)} reserve.",
                              "Very little margin for traffic, AC or detours - drive gently."])
    if arr < COMFORT_SOC:
        return GuardDecision(True, "ok_low_margin", [f"Arrive with {pct(arr)}.",
                             f"That's below the {pct(COMFORT_SOC)} comfort margin - drive gently."])
    return GuardDecision(True, "ok", [f"Arrive with {pct(arr)}."])


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


# -- single entry point ----------------------------------------------------------
ROUTE_ACTIONS = {"navigate", "add_stop", "detour", "change_destination"}


def _stop_summary(plan: dict, decision: GuardDecision) -> dict | None:
    if plan.get("stops"):
        s = plan["stops"][0]
        return {"name": s["name"], "node": s["node"], "arrive_soc": s["arrive_soc"], "depart_soc": s["depart_soc"],
                "charge_min": s["charge_min"], "cost_inr": s["cost_inr"]}
    alts = decision.data.get("reachable_chargers") or []
    if alts:
        a = alts[0]
        return {"name": a["name"], "node": a["node"], "arrive_soc": a["arrive_soc"], "distance_km": a["distance_km"]}
    return None


def check(action: str, **ctx) -> GuardDecision:
    """Judge one requested action against live battery state. Every executing tool calls this.

    action                         context
    navigate / add_stop / detour   plan (planner output); direct=True, explicit=bool for no-charging routes
    climate                        range_before_km, range_after_km, soc
    precool                        plugged_in, soc, kwh_needed, usable_kwh
    charge                         target_soc, charger_kind
    cancel_route, vehicle_feature  nothing - no battery impact, recorded for the audit trail
    no_change                      nothing - the request needs no action (e.g. already there)
    """
    if action in ROUTE_ACTIONS:
        plan = ctx["plan"]
        d = assess_direct(plan, ctx.get("explicit", False)) if ctx.get("direct") else assess_plan(plan)
        d.proposed_stop = _stop_summary(plan, d) if d.verdict != "allow" else None
    elif action == "climate":
        d = assess_climate_change(ctx["range_before_km"], ctx["range_after_km"], ctx["soc"])
    elif action == "precool":
        d = assess_precool(ctx["plugged_in"], ctx["soc"], ctx["kwh_needed"], ctx["usable_kwh"])
    elif action == "charge":
        d = assess_charge_target(ctx["target_soc"], ctx["charger_kind"])
    elif action in ("cancel_route", "vehicle_feature"):
        d = GuardDecision(True, "ok", ["No battery impact."])
    elif action == "no_change":
        d = GuardDecision(True, "ok", ["Nothing to change."])
    else:
        raise ValueError(f"guard has no rule for action '{action}'")
    d.action = action
    return d
