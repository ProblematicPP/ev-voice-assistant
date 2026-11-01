"""Function-calling router: tool call -> battery guard -> execute -> structured result.

Every result has:
  ok      - did the action execute (or the query succeed)?
  facts   - the numbers the response generator may use (nothing else)
  say     - deterministic template reply (used when the LLM is unavailable)
  guard   - the guard's verdict, when one applied
"""
from __future__ import annotations

import inspect

from app import simulation
from app.assistant.stubs import assisted_driving, precooling
from app.battery_core import guard
from app.config import COMFORT_SOC, HARD_MIN_SOC, RESERVE_SOC
from app.routing import replanner


def _pct(x):
    return f"{x * 100:.0f}%"


def _mins(m):
    m = int(round(m))
    return f"{m // 60} h {m % 60} min" if m >= 60 else f"{m} min"


def result(tool, args, ok, say, facts=None, decision=None, route_changed=False):
    return {"tool": tool, "args": args, "ok": ok, "say": say, "facts": facts or {},
            "guard": decision.to_dict() if decision else None, "route_changed": route_changed}


# Tools that change the vehicle or route. Each must return a battery-guard verdict.
ACTION_TOOLS = {"navigate_to", "add_stop", "cancel_navigation", "start_charging", "set_climate",
                "precool_cabin", "assisted_driving"}


class ToolRouter:
    def __init__(self, ctx):
        self.ctx = ctx

    def execute(self, name: str, args: dict | None) -> dict:
        handler = getattr(self, f"t_{name}", None)
        if handler is None:
            return result(name, args or {}, False, "Sorry, I can't do that yet.")
        # LLMs sometimes invent extra arguments - keep only the ones the handler accepts
        accepted = inspect.signature(handler).parameters
        args = {k: v for k, v in (args or {}).items() if v is not None and k in accepted}
        out = handler(**args)
        if name in ACTION_TOOLS and out["ok"] and out.get("guard") is None:
            # An action that changed the car without a guard verdict is a bug, never a reply
            raise RuntimeError(f"{name} executed without a battery-guard check")
        return out

    # -- helpers ---------------------------------------------------------------
    @property
    def st(self):
        return self.ctx.state

    def _cond(self):
        return self.ctx.battery.conditions(self.st)

    def _resolve(self, text, via=None):
        return self.ctx.net.resolve(text or "", self.st.location, via=via)

    def _plan_facts(self, plan, decision, note=None) -> dict:
        t = plan["totals"]
        return {
            "destination": plan["destination_names"][-1],
            "via": plan["destination_names"][:-1],
            "status": decision.status,
            "distance_km": t.get("distance_km"),
            "total_time": _mins(t["total_min"]) if "total_min" in t else None,
            "arrival_charge": _pct(t["arrival_soc"]) if "arrival_soc" in t else None,
            "charging_stops": [
                {"name": s["name"], "arrive": _pct(s["arrive_soc"]), "leave": _pct(s["depart_soc"]),
                 "minutes": round(s["charge_min"]), "cost_inr": s["cost_inr"]} for s in plan["stops"]
            ],
            "guard_reasons": decision.reasons,
            "why_this_charger": note,
            "current_charge": _pct(self.st.soc),
        }

    def _activate(self, plan):
        self.st.active_plan = plan
        self.st.progress = {"leg": 0, "node": 0, "waypoints_done": 0, "edge_km": 0.0}
        self.st.trip_km = 0.0
        self.st.plugged_in = False
        self.st.log("route", f"Navigating to {plan['destination_names'][-1]}"
                    + (f" via {', '.join(s['name'] for s in plan['stops'])}" if plan["stops"] else ""))

    def _route_say(self, plan, decision, prefix="") -> str:
        dest = plan["destination_names"][-1]
        t = plan["totals"]
        if decision.status == "infeasible":
            alts = decision.data.get("reachable_chargers") or []
            s = f"I can't get you to {dest} safely from {_pct(t['start_soc'])}."
            if alts:
                s += f" The closest charger I can reach is {alts[0]['name']}, {alts[0]['distance_km']} km away. Head there first?"
            return s
        if plan["stops"]:
            stops = "; ".join(f"{st['name']} (arrive {_pct(st['arrive_soc'])}, charge to {_pct(st['depart_soc'])}, "
                              f"~{st['charge_min']:.0f} min)" for st in plan["stops"])
            n = len(plan["stops"])
            return (f"{prefix}Routing to {dest} with {'a charging stop' if n == 1 else f'{n} charging stops'} at "
                    f"{stops}. Total {_mins(t['total_min'])}, arriving with {_pct(t['arrival_soc'])}.")
        s = f"{prefix}Navigating to {dest}: {t['distance_km']:.0f} km, {_mins(t['total_min'])}, arriving with {_pct(t['arrival_soc'])}."
        if decision.status == "ok_below_reserve":
            s = f"{prefix}Navigating to {dest} without charging: {t['distance_km']:.0f} km, {_mins(t['total_min'])}. "
            if t["arrival_soc"] < HARD_MIN_SOC:
                s += (f"Warning: you'll arrive with only {_pct(t['arrival_soc'])}, almost empty - traffic or AC "
                      f"could leave you stranded. Drive very gently.")
            else:
                s += (f"Warning: you'll arrive with only {_pct(t['arrival_soc'])}, below the {_pct(RESERVE_SOC)} "
                      f"reserve. Drive gently and go easy on the AC.")
        elif decision.status == "ok_low_margin":
            s += " That's a thin margin, so drive gently."
        return s

    # -- navigation ------------------------------------------------------------
    def t_navigate_to(self, destination: str = "", via_charger: bool = False, no_charging: bool = False,
                      stop_at: str = ""):
        nav = self._navigate(destination, via_charger, no_charging)
        if not stop_at or not nav["ok"] or not self.st.active_plan:
            return nav
        # "Take me to X with a stop at Y": route to X, then slot Y in along the way
        self.st.pending_offer = None
        stop = self.t_add_stop(stop_at)
        args = {**nav["args"], "stop_at": stop_at}
        if not stop["ok"]:
            return {**nav, "args": args, "say": f"{nav['say']} {stop['say']}",
                    "facts": {**nav["facts"], "stop_not_added": stop["say"]}}
        return {**stop, "tool": "navigate_to", "args": args, "route_changed": True}

    def _navigate(self, destination: str, via_charger: bool, no_charging: bool):
        args = {"destination": destination, "via_charger": via_charger, "no_charging": no_charging}
        target = self._resolve(destination)
        if not target:
            return result("navigate_to", args, False,
                          f"I couldn't find '{destination}' on the map. Try a place like Mysuru, Whitefield or the airport.")
        if target["node"] == self.st.location:
            return result("navigate_to", args, True, f"You're already at {target['name']}.",
                          {"destination": target["name"], "distance_km": 0}, guard.check("no_change"))

        cond = self._cond()
        if not via_charger:
            # Go where the driver asked. A charging stop is only forced in when skipping it would
            # leave the car below the hard floor (or out of charge, if they insisted on no charging).
            out = self._navigate_direct(target, args, cond, explicit=no_charging)
            if out:
                return out

        min_final = COMFORT_SOC if via_charger else RESERVE_SOC
        old = self.st.active_plan
        plan = self.ctx.planner.plan(self.st.location, [target["node"]], self.st.soc, cond, min_final)
        forced = False
        if via_charger and plan["status"] == "direct":
            # The battery would manage, but the driver asked to charge on the way - honour that
            via = self.ctx.planner.plan_via_charger(self.st.location, target["node"], self.st.soc, cond)
            if via:
                plan, forced = via, True
        diff = replanner.diff(old, plan)
        if target["kind"] != "node":
            plan["destination_names"][-1] = target["name"]
        decision = guard.check("navigate", plan=plan)
        if not decision.allow:
            alts = decision.data.get("reachable_chargers") or []
            if alts:
                self.st.pending_offer = {"text": f"Navigate to {alts[0]['name']} to charge?",
                                         "tool": "navigate_to", "args": {"destination": alts[0]["node"]}}
            return result("navigate_to", args, False, self._route_say(plan, decision),
                          self._plan_facts(plan, decision), decision)

        note = None if forced else self.ctx.planner.alternative_note(
            self.st.location, plan["destinations"], self.st.soc, cond, plan)
        self._activate(plan)
        facts = self._plan_facts(plan, decision, note)
        prefix = "Changing destination. " if old else ""
        if diff:
            facts["change"] = diff
        if forced:
            facts["note"] = "Charging stop added because the driver asked for one; the battery alone would also make it."
        elif via_charger and not plan["stops"]:
            facts["note"] = "No charger on the way could be found - going direct."
        return result("navigate_to", args, True, self._route_say(plan, decision, prefix), facts, decision, True)

    def _navigate_direct(self, target, args, cond, explicit):
        """Route with no charging stop. Returns None to let the caller plan one with charging instead."""
        old = self.st.active_plan
        try:
            if old:
                plan, diff = replanner.replan_destination(self.ctx.planner, self.st, cond, target["node"], direct=True)
            else:
                plan, diff = self.ctx.planner.plan_direct(self.st.location, [target["node"]], self.st.soc, cond), None
        except ValueError:   # no road path - the normal planner reports it
            return None
        if target["kind"] != "node":
            plan["destination_names"][-1] = target["name"]
        dest = plan["destination_names"][-1]
        decision = guard.check("navigate", plan=plan, direct=True, explicit=explicit)

        if not decision.allow:
            if not explicit:
                return None
            say = (f"I can't skip charging: {dest} is {plan['totals']['distance_km']:.0f} km away and you'd run out "
                   f"of charge before getting there.")
            charged = self.ctx.planner.plan(self.st.location, [target["node"]], self.st.soc, cond)
            if charged["stops"]:
                stop = charged["stops"][0]
                say += f" A {stop['charge_min']:.0f}-minute stop at {stop['name']} fixes it. Want that route?"
                self.st.pending_offer = {"text": f"Navigate to {dest} via {stop['name']}?",
                                         "tool": "navigate_to", "args": {"destination": target["node"]}}
            elif charged.get("reachable_chargers"):
                alt = charged["reachable_chargers"][0]
                say += f" The closest charger you can reach is {alt['name']}, {alt['distance_km']} km away. Head there first?"
                self.st.pending_offer = {"text": f"Navigate to {alt['name']} to charge?",
                                         "tool": "navigate_to", "args": {"destination": alt["node"]}}
            return result("navigate_to", args, False, say, self._plan_facts(plan, decision), decision)

        # The driver accepted a low arrival; don't nag about the reserve unless things get worse than planned
        plan["accepted_arrival_soc"] = plan["totals"]["arrival_soc"] if decision.status == "ok_below_reserve" else None
        self._activate(plan)
        facts = self._plan_facts(plan, decision)
        if diff:
            facts["change"] = diff
        say = self._route_say(plan, decision, "Changing destination. " if old else "")
        if decision.status == "ok_below_reserve":
            facts["warning"] = " ".join(decision.reasons)
            facts["charging_stop_offered"] = True
            say += " Say yes if you'd like a charging stop added."
            self.st.pending_offer = {"text": f"Add a charging stop on the way to {dest}?", "tool": "navigate_to",
                                     "args": {"destination": target["node"], "via_charger": True}}
        return result("navigate_to", args, True, say, facts, decision, True)

    def t_check_range_to(self, destination: str = "", without_stopping: bool = True):
        args = {"destination": destination}
        target = self._resolve(destination)
        if not target:
            return result("check_range_to", args, False, f"I couldn't find '{destination}' on the map.")
        bat, planner = self.ctx.battery, self.ctx.planner
        cond = self._cond()
        energy = bat.edge_energy_kwh(self.ctx.net, cond)
        prof = planner.path_profile(self.st.location, target["node"], energy)
        arrive = self.st.soc - prof["energy_kwh"] / bat.usable_kwh()
        name = target["name"]
        facts = {"destination": name, "distance_km": round(prof["distance_km"], 1),
                 "drive_time": _mins(prof["drive_min"]), "current_charge": _pct(self.st.soc),
                 "arrival_charge_without_stopping": _pct(max(arrive, 0)),
                 "reserve_floor": _pct(RESERVE_SOC), "conditions": f"{cond['ambient_temp_c']:.0f} °C, {cond['hvac_mode']}"}

        if arrive >= COMFORT_SOC:
            facts["verdict"] = "yes_comfortably"
            say = f"Yes. {name} is {prof['distance_km']:.0f} km away and you'd arrive with about {_pct(arrive)}."
            return result("check_range_to", args, True, say, facts)
        if arrive >= RESERVE_SOC:
            facts["verdict"] = "yes_tight"
            say = (f"Just about - you'd reach {name} ({prof['distance_km']:.0f} km) with only {_pct(arrive)}. "
                   f"I'd keep speeds moderate.")
            return result("check_range_to", args, True, say, facts)

        facts["verdict"] = "no"
        # What-if: would switching AC off be enough?
        if cond["hvac_mode"] in ("ac", "heat"):
            e2 = bat.edge_energy_kwh(self.ctx.net, {**cond, "hvac_mode": "off"})
            arr2 = self.st.soc - planner.path_profile(self.st.location, target["node"], e2)["energy_kwh"] / bat.usable_kwh()
            facts["arrival_with_climate_off"] = _pct(max(arr2, 0))
        plan = planner.plan(self.st.location, [target["node"]], self.st.soc, cond)
        decision = guard.check("navigate", plan=plan)
        if arrive <= 0:
            reach_km = prof["distance_km"] * self.st.soc / (self.st.soc - arrive)
            facts["would_run_out_km_short"] = round(prof["distance_km"] - reach_km)
            say = (f"No - {name} is {prof['distance_km']:.0f} km away and at today's consumption you'd run out "
                   f"about {prof['distance_km'] - reach_km:.0f} km short.")
        else:
            say = (f"No - {name} is {prof['distance_km']:.0f} km away and you'd arrive with only {_pct(arrive)}, "
                   f"below the {_pct(RESERVE_SOC)} reserve.")
        if plan["stops"]:
            st = plan["stops"][0]
            facts["suggested_stop"] = {"name": st["name"], "minutes": round(st["charge_min"]),
                                       "charge_to": _pct(st["depart_soc"])}
            say += f" One {st['charge_min']:.0f}-minute stop at {st['name']} fixes it. Want me to start that route?"
            self.st.pending_offer = {"text": f"Navigate to {name} via {st['name']}?", "tool": "navigate_to",
                                     "args": {"destination": target["node"], "via_charger": True}}
        return result("check_range_to", args, True, say, facts, decision)

    def t_add_stop(self, place: str = ""):
        args = {"place": place}
        if not self.st.active_plan:
            return self.t_navigate_to(place)
        final = replanner.remaining_destinations(self.st)[-1]
        target = self._resolve(place, via=final)
        if not target:
            return result("add_stop", args, False, f"I couldn't find '{place}'.")
        old_eta = self.st.active_plan["totals"].get("total_min", 0)
        plan, diff = replanner.replan_with_stop(self.ctx.planner, self.st, self._cond(), target["node"])
        plan["destination_names"][-2 if len(plan["destination_names"]) > 1 else -1] = target["name"]
        decision = guard.check("add_stop", plan=plan)
        facts = self._plan_facts(plan, decision)
        facts["added_stop"] = target["name"]
        facts["change"] = diff
        if not decision.allow:
            return result("add_stop", args, False,
                          f"Adding {target['name']} would leave you unable to finish the trip safely, so I've kept the "
                          f"current route.", facts, decision)
        self._activate(plan)
        say = f"Added {target['name']}. "
        if diff and diff["added_charging_stops"]:
            say += f"The detour means an extra charging stop ({', '.join(diff['added_charging_stops'])}). "
        say += self._route_say(plan, decision)
        facts["previous_total_min"] = old_eta
        return result("add_stop", args, True, say, facts, decision, True)

    def t_cancel_navigation(self):
        decision = guard.check("cancel_route")
        if not self.st.active_plan:
            return result("cancel_navigation", {}, True, "There's no active route.", decision=decision)
        dest = self.st.active_plan["destination_names"][-1]
        self.st.active_plan = None
        self.st.progress = {"leg": 0, "node": 0, "waypoints_done": 0}
        self.st.log("route", f"Navigation to {dest} cancelled")
        return result("cancel_navigation", {}, True, f"Navigation to {dest} cancelled.", decision=decision,
                      route_changed=True)

    # -- battery ---------------------------------------------------------------
    def t_get_battery_status(self):
        r = self.ctx.battery.range(self.st)
        soh = self.ctx.battery.soh()
        facts = {"charge": _pct(self.st.soc), "personalized_range_km": round(r["personalized_km"]),
                 "city_range_km": round(r["city_km"]), "highway_range_km": round(r["highway_km"]),
                 "brochure_naive_range_km": round(r["naive_km"]), "battery_health_soh": f"{soh['soh_pct']}%",
                 "usable_kwh": soh["usable_kwh"]}
        say = (f"You're at {_pct(self.st.soc)} with about {r['personalized_km']:.0f} km of range for how you drive "
               f"today. Battery health is {soh['soh_pct']:.0f}%.")
        return result("get_battery_status", {}, True, say, facts)

    def t_explain_range(self):
        ex = self.ctx.battery.explain_range(self.st)
        facts = {"expected_km": ex["expected_km"], "current_km": ex["current_km"], "drop_pct": ex["drop_pct"],
                 "factors": [{"factor": c["label"], "km": c["km"], "detail": c["detail"]}
                             for c in ex["contributions"] if abs(c["km"]) >= 1]}
        return result("explain_range", {}, True, ex["summary"], facts)

    def t_list_chargers(self, fast_only: bool = False):
        net, bat, planner = self.ctx.net, self.ctx.battery, self.ctx.planner
        energy = bat.edge_energy_kwh(net, self._cond())
        rows = []
        for c in net.chargers.values():
            if c["kind"] == "home_ac" or (fast_only and c["kind"] != "dc_fast"):
                continue
            p = planner.path_profile(self.st.location, c["node"], energy)
            arr = self.st.soc - p["energy_kwh"] / bat.usable_kwh()
            if arr >= 0.03:
                rows.append({"name": c["name"], "power_kw": c["power_kw"], "distance_km": round(p["distance_km"], 1),
                             "arrive": _pct(arr), "price_per_kwh": c["price_per_kwh"], "_t": p["drive_min"]})
        rows.sort(key=lambda r: r.pop("_t"))
        rows = rows[:4]
        if not rows:
            return result("list_chargers", {}, False, "No charger is reachable on the current charge.")
        top = rows[0]
        say = f"Closest is {top['name']}, {top['distance_km']:.0f} km away, {top['power_kw']:.0f} kW - you'd arrive with {top['arrive']}."
        if len(rows) > 1:
            say += f" Next: {rows[1]['name']} ({rows[1]['distance_km']:.0f} km)."
        return result("list_chargers", {"fast_only": fast_only}, True, say, {"chargers": rows})

    def t_start_charging(self, target_percent: int = 80):
        target = max(1, min(100, int(target_percent))) / 100
        chargers = self.ctx.net.chargers_at(self.st.location)
        if not chargers:
            return result("start_charging", {"target_percent": target_percent}, False,
                          f"There's no charger at {self.ctx.net.name(self.st.location)}.")
        ch = max(chargers, key=lambda c: c["power_kw"])
        decision = guard.check("charge", target_soc=target, charger_kind=ch["kind"])
        out = simulation.charge_now(self.ctx, target)
        say = f"Charged at {out['charger']} from {_pct(out['from'])} to {_pct(out['to'])}."
        if decision.status == "ok_with_advice":
            say += " " + decision.reasons[0]
        return result("start_charging", {"target_percent": target_percent}, True, say,
                      {"charger": out["charger"], "from": _pct(out["from"]), "to": _pct(out["to"])}, decision)

    # -- cabin -------------------------------------------------------------------
    def t_set_climate(self, mode: str = "off"):
        if mode not in ("off", "fan", "ac", "heat"):
            mode = "off"
        before = self.ctx.battery.range_km(self.st)
        prev = self.st.hvac_mode
        self.st.hvac_mode = mode
        after = self.ctx.battery.range_km(self.st)
        decision = guard.check("climate", range_before_km=before, range_after_km=after, soc=self.st.soc)
        if not decision.allow:
            self.st.hvac_mode = prev
            return result("set_climate", {"mode": mode}, False,
                          "Battery is critically low, so I'm keeping climate as is to protect range.", {}, decision)
        word = {"off": "Climate off", "fan": "Fan on", "ac": "AC on", "heat": "Heater on"}[mode]
        diff = after - before
        say = f"{word}. Range is now about {after:.0f} km ({diff:+.0f} km)."
        return result("set_climate", {"mode": mode}, True, say,
                      {"mode": mode, "range_before_km": round(before), "range_after_km": round(after)}, decision)

    def t_precool_cabin(self, minutes: int = 10, target_c: float = 24):
        bat = self.ctx.battery
        kw = bat.hvac_kw("ac", self.st.ambient_temp_c)
        stub = precooling.plan(int(minutes), float(target_c), self.st.ambient_temp_c, self.st.plugged_in, kw)
        decision = guard.check("precool", plugged_in=self.st.plugged_in, soc=self.st.soc,
                                kwh_needed=stub["energy_kwh"], usable_kwh=bat.usable_kwh())
        if not decision.allow:
            return result("precool_cabin", {"minutes": minutes}, False, decision.reasons[0], stub, decision)
        self.st.precooling = True
        self.st.log("stub", stub["would_do"], stub="precooling")
        say = stub["would_do"].replace("Would start", "Starting") + " " + decision.reasons[0]
        return result("precool_cabin", {"minutes": minutes}, True, say, stub, decision)

    def t_assisted_driving(self, action: str = "turn_camera", side: str = "left"):
        decision = guard.check("vehicle_feature")
        out = assisted_driving.trigger(action, side)
        self.st.log("stub", out["would_do"], stub="assisted_driving")
        return result("assisted_driving", {"action": action, "side": side}, True,
                      out["would_do"].replace("Would show", "Showing").replace("Would open", "Opening")
                      .replace("Would engage", "Engaging").replace("Would switch", "Switching")
                      .replace("Would enable", "Enabling"), out, decision)

    # -- offers ------------------------------------------------------------------
    def t_respond_to_offer(self, accept: bool = True):
        offer = self.st.pending_offer
        if not offer:
            return result("respond_to_offer", {"accept": accept}, False, "There's nothing waiting for an answer.")
        self.st.pending_offer = None
        if not accept:
            return result("respond_to_offer", {"accept": False}, True, "Okay, no change.")
        inner = self.execute(offer["tool"], offer["args"])
        inner["accepted_offer"] = offer["text"]
        return inner

    # -- companion ---------------------------------------------------------------
    def t_get_charging_coaching(self):
        from app.companion import coaching
        tips = coaching.coach(self.ctx.sessions())
        say = " ".join(t["message"] for t in tips[:2])
        return result("get_charging_coaching", {}, True, say, {"tips": [t["message"] for t in tips]})

    def t_get_eco_driving_coaching(self):
        e = self.ctx.eco()
        h = e["history"]
        say = (f"You average {h['harsh_brakes_per_100km']:.1f} harsh brakes and {h['harsh_accels_per_100km']:.1f} hard "
               f"accelerations per 100 km, about {e['events_vs_typical']:.0f} times a smooth driver. ")
        if e["range_gain_km"] >= 1:
            say += (f"Braking earlier so regen can recover energy, and pulling away gently, would add about "
                    f"{e['range_gain_km']:.0f} km at today's charge.")
        else:
            say += e["tips"][-1]["message"]
        facts = {"harsh_brakes_per_100km": h["harsh_brakes_per_100km"],
                 "harsh_accels_per_100km": h["harsh_accels_per_100km"], "km_analysed": h["km"],
                 "times_typical_driver": e["events_vs_typical"], "range_gain_if_smoother_km": e["range_gain_km"],
                 "last_drive": e["recent_drive"], "tips": [t["message"] for t in e["tips"]]}
        return result("get_eco_driving_coaching", {}, True, say, facts)

    def t_get_fleet_status(self):
        f = self.ctx.fleet()
        o, r = f.overview(), f.rebalance()
        worn = o["bands"].get("near end of life", 0)
        say = (f"The fleet has {o['count']} cars at {o['avg_soh'] * 100:.0f}% average battery health; {worn} are near "
               f"end of life and kept on short urban rentals. ")
        if r["moves"]:
            m = r["moves"][0]
            say += (f"Move {len(r['moves'])} idle car{'s' if len(r['moves']) > 1 else ''} for the next "
                    f"{r['horizon_h']} hours, starting with {m['vehicle_id']} from {m['from_name']} to {m['to_name']}. "
                    f"That cuts expected missed rentals from {r['expected_lost_before']:.1f} to {r['expected_lost_after']:.1f}.")
        else:
            say += "Idle cars are already where the demand is."
        facts = {"vehicles": o["count"], "avg_soh": o["avg_soh"], "health_bands": o["bands"],
                 "moves": r["moves"][:4], "expected_lost_before": r["expected_lost_before"],
                 "expected_lost_after": r["expected_lost_after"]}
        return result("get_fleet_status", {}, True, say, facts)

    def t_get_cost_and_resale(self):
        comp = self.ctx.companion()
        c, r = comp["cost"], comp["resale"]
        say = (f"You're spending about ₹{c['cost_per_km_inr']:.2f} per km versus ₹{c['petrol_equivalent_per_km_inr']:.1f} "
               f"for a petrol car. With battery health at {r['soh'] * 100:.0f}%, the car is worth roughly "
               f"₹{r['estimated_value_inr'] / 1e5:.1f} lakh.")
        if r["habit_value_gap_inr"] > 0:
            say += f" Slow-charging more could keep about ₹{r['habit_value_gap_inr'] / 1000:.0f}k extra value in two years."
        return result("get_cost_and_resale", {}, True, say,
                      {"cost_per_km_inr": c["cost_per_km_inr"], "petrol_per_km_inr": c["petrol_equivalent_per_km_inr"],
                       "resale_value_inr": r["estimated_value_inr"], "soh": r["soh"],
                       "value_gap_2y_inr": r["habit_value_gap_inr"]})
