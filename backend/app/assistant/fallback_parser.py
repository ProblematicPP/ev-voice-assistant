"""Keyword/regex intent + entity parser.

Used (a) when Ollama isn't running, and (b) as a safety net when the LLM
replies in prose to something that clearly needed a tool.
Returns (tool_name, args) or None.
"""
from __future__ import annotations

import re

YES = re.compile(r"^\s*(yes|yeah|yep|yup|sure|ok|okay|do it|go ahead|please do|sounds good|alright|haan|ha)\b", re.I)
NO = re.compile(r"^\s*(no|nope|nah|not now|don'?t|cancel that|skip)\b", re.I)


def _after(text: str, *keys: str) -> str:
    for k in keys:
        m = re.search(rf"\b{k}\b\s+(.*)", text, re.I)
        if m:
            place = m.group(1)
            place = re.sub(r"\b(without (stopping|a stop|charging)|on the way|please|now|first|right now|"
                           r"on (one|this|a single) charge|and back|today)\b.*$", "", place, flags=re.I)
            place = re.sub(r"[?.!,]+$", "", place).strip()
            if place:
                return place
    return ""


def parse(text: str, has_pending_offer: bool = False, driving: bool = False):
    t = text.strip().lower()

    if has_pending_offer and len(t.split()) <= 6:
        if YES.search(t):
            return "respond_to_offer", {"accept": True}
        if NO.search(t):
            return "respond_to_offer", {"accept": False}

    if re.search(r"\b(will|would|can|could) (i|we) (make it|reach|get to|go)|enough (charge|battery|range)|"
                 r"without stopping|on (one|this|a single) charge|make it to", t):
        return "check_range_to", {"destination": _after(t, "make it to", "reach", "get to", "go to", "for", "to")}

    if re.search(r"\bwhy\b.*\b(range|battery|drain|low)|range.*(low|less|lower|drop|bad|worse)|lower than (usual|expected)", t):
        return "explain_range", {}

    if re.search(r"\b(cancel|stop|end)\b.*\b(navigation|route|trip|guidance)\b", t):
        return "cancel_navigation", {}

    if re.search(r"\b(pre-?cool|cool (down )?(the )?(car|cabin)|precondition)", t):
        mins = re.search(r"(\d+)\s*min", t)
        return "precool_cabin", {"minutes": int(mins.group(1)) if mins else 10}

    if re.search(r"\b(camera|blind ?spot|lane|park(ing)? (assist|view|mode)|cruise|turning (left|right)|"
                 r"turn (left|right))\b", t):
        side = "right" if "right" in t else "left"
        action = ("blind_spot" if "blind" in t else "lane_keep" if "lane" in t else
                  "parking_assist" if "park" in t else "adaptive_cruise" if "cruise" in t else "turn_camera")
        return "assisted_driving", {"action": action, "side": side}

    m = re.search(r"\b(ac|a\.c\.|air ?con\w*|heater|heating|fan|climate)\b", t)
    if m:
        word = m.group(1)
        off = re.search(r"\b(off|stop|disable|kill)\b", t)
        mode = "off" if off else "heat" if word.startswith("heat") else "fan" if word == "fan" else "ac"
        return "set_climate", {"mode": mode}

    if re.search(r"\b(start|begin) charging|charge (it |the car )?(to|up to) \d+", t):
        pct = re.search(r"(\d{2,3})\s*%?", t)
        return "start_charging", {"target_percent": int(pct.group(1)) if pct else 80}

    if driving and re.search(r"\b(add|also|detour|stop at|stop by|on the way|via|pit ?stop|quick stop)\b", t):
        return "add_stop", {"place": _after(t, "stop at", "stop by", "at", "to", "a", "add") or t}

    if re.search(r"\b(take me|navigate|go to|drive (me )?to|directions|route (me )?to|head to|let'?s go)\b", t):
        dest = _after(t, "take me to", "take me", "navigate to", "go to", "drive me to", "drive to",
                      "directions to", "route me to", "route to", "head to", "go")
        via = bool(re.search(r"via (a )?charg|charge on the way|with a charg", t))
        return "navigate_to", {"destination": dest, "via_charger": via}

    if re.search(r"\b(charger|charging station|charge point)s?\b", t):
        return "list_chargers", {"fast_only": "fast" in t}

    if re.search(r"\b(habits?|coach\w*|tips?|charging (behaviou?rs?|patterns?)|am i charging)\b", t):
        return "get_charging_coaching", {}

    if re.search(r"\b(cost|per km|resale|worth|value|saving|spend)\b", t):
        return "get_cost_and_resale", {}

    if re.search(r"\b(battery|soh|health|range|charge left|how much charge|percent|status|how far)\b", t):
        return "get_battery_status", {}

    return None
