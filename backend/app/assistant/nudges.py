"""Proactive nudges: unprompted alerts derived from the live battery / route state.

Each rule returns (key, text, offer) where offer (optional) is a tool call the
user can accept with "yes". A nudge re-fires only if its key changes or after
the cooldown.
"""
from __future__ import annotations

import time

from app import simulation
from app.companion import coaching
from app.config import COMFORT_SOC, VEHICLE

COOLDOWN_S = 600


def _rules(ctx):
    st, bat = ctx.state, ctx.battery
    out = []

    # 1. Active route no longer safe under current conditions
    proj = simulation.remaining_projection(ctx)
    if proj and proj["at_risk"]:
        cond = bat.conditions(st)
        out.append((
            f"route_risk:{proj['destination']}:{round(proj['min_soc'], 2)}",
            f"Heads up: at {cond['ambient_temp_c']:.0f} °C with "
            f"{ {'ac': 'AC', 'heat': 'the heater', 'fan': 'the fan', 'off': 'climate'}[cond['hvac_mode']] } "
            f"{'off' if cond['hvac_mode'] == 'off' else 'on'}, you'd reach "
            f"{proj['destination']} at {max(proj['arrival_soc'], 0):.0%} (lowest point {max(proj['min_soc'], 0):.0%}) - "
            f"below the safe reserve. "
            f"Re-plan with a charging stop?",
            {"tool": "navigate_to", "args": {"destination": st.active_plan["destinations"][-1]},
             "text": f"Re-plan to {proj['destination']} with a charging stop"},
        ))

    # 2. Low battery, far from home, no charging planned
    if not st.plugged_in and st.location != VEHICLE["home_node"] and not (st.active_plan and st.active_plan["stops"]):
        home = simulation.home_projection(ctx)
        if st.soc < 0.25 and home["arrival_soc"] < COMFORT_SOC:
            out.append((
                f"low_far:{round(st.soc, 2)}",
                f"{st.soc:.0%} left, {home['distance_km']:.0f} km from home - route via a charger?",
                {"tool": "navigate_to", "args": {"destination": "home", "via_charger": True},
                 "text": "Route home via a charger"},
            ))

    # 3. Hot day, parked & plugged -> offer pre-cooling (hardware stub)
    if st.ambient_temp_c >= 32 and st.plugged_in and not st.precooling and not st.active_plan:
        out.append((
            "precool",
            f"It's {st.ambient_temp_c:.0f} °C outside. Pre-cool the cabin now using plug power, so it costs no range?",
            {"tool": "precool_cabin", "args": {"minutes": 10}, "text": "Pre-cool the cabin"},
        ))

    # 4. Range well below normal because of today's conditions (battery ageing excluded - it's constant)
    ex = bat.explain_range(st)
    situational = [c for c in ex["contributions"] if c["factor"] != "battery_age" and c["km"] < 0]
    drop = -sum(c["km"] for c in situational) / ex["expected_km"] if ex["expected_km"] else 0
    if drop >= 0.40 and st.soc > 0.15:
        top = situational[0]
        out.append((
            f"range_drop:{top['factor']}",
            f"Range is about {drop:.0%} lower than usual right now, mostly from {top['label']}. "
            f"Ask me 'why is my range low?' for the breakdown.",
            None,
        ))

    # 5. Charging habits
    tips = [t for t in coaching.coach(ctx.sessions()) if t["id"] == "fast_charge_frequency"]
    if tips and st.plugged_in:
        out.append(("coach_fast", tips[0]["message"], None))
    return out


def evaluate(ctx) -> list[dict]:
    st = ctx.state
    now = time.time()
    fresh = []
    for key, text, offer in _rules(ctx):
        family = key.split(":")[0]
        last_key, last_ts = st.nudge_log.get(family, (None, 0.0))
        if last_key == key and now - last_ts < COOLDOWN_S:
            continue
        st.nudge_log[family] = (key, now)
        if offer:
            st.pending_offer = offer
        st.log("nudge", text)
        fresh.append({"key": family, "text": text, "offer": offer["text"] if offer else None})
    return fresh
