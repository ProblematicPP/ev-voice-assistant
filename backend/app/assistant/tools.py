"""Tool (function) schemas exposed to the local LLM.

The LLM only picks a tool and fills arguments - feasibility and all numbers
come from the router -> battery guard -> battery core / planner.
"""


def _fn(name, description, properties=None, required=None):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties or {}, "required": required or []},
        },
    }


S = {"type": "string"}
B = {"type": "boolean"}

TOOLS = [
    _fn("navigate_to",
        "Start navigation to a place, brand or category (e.g. 'Mysuru', 'nearest McDonald's', 'airport', "
        "'home', 'nearest charger'). Automatically checks battery range and adds charging stops. "
        "Also use this to CHANGE the destination during a drive.",
        {"destination": {**S, "description": "Place name or POI as the user said it"},
         "via_charger": {**B, "description": "True if the user explicitly wants to charge on the way"}},
        ["destination"]),
    _fn("check_range_to",
        "Answer 'will I make it to X', 'can I reach X without stopping', 'enough charge for X'. "
        "Does not start navigation.",
        {"destination": S}, ["destination"]),
    _fn("add_stop",
        "Add a detour/stop during the current drive (e.g. 'also stop at a McDonald's on the way', "
        "'add a stop at Maddur'). Re-plans charging from the current position.",
        {"place": S}, ["place"]),
    _fn("cancel_navigation", "Stop / cancel the current navigation."),
    _fn("get_battery_status",
        "Current charge %, personalized remaining range, battery health (SOH) and usable capacity."),
    _fn("explain_range",
        "Explain WHY the range is lower than expected (weather, AC, driving style, load, battery ageing)."),
    _fn("list_chargers", "List nearby reachable chargers with arrival charge.",
        {"fast_only": {**B, "description": "Only DC fast chargers"}}),
    _fn("start_charging", "Start charging at the charger where the car currently is.",
        {"target_percent": {"type": "integer", "description": "Target state of charge, e.g. 80"}}),
    _fn("set_climate", "Turn AC / heater / fan on or off.",
        {"mode": {"type": "string", "enum": ["off", "fan", "ac", "heat"]}}, ["mode"]),
    _fn("precool_cabin", "Pre-cool the cabin before a drive (uses plug power if plugged in).",
        {"minutes": {"type": "integer"}, "target_c": {"type": "number"}}),
    _fn("assisted_driving",
        "Driver-assistance display/actions: turn camera, blind spot view, lane keep, parking assist, adaptive cruise.",
        {"action": {"type": "string",
                    "enum": ["turn_camera", "blind_spot", "lane_keep", "parking_assist", "adaptive_cruise"]},
         "side": {"type": "string", "enum": ["left", "right"]}},
        ["action"]),
    _fn("respond_to_offer",
        "The user answered yes/no to the assistant's pending suggestion (e.g. 'yes', 'sure', 'do it', 'no thanks').",
        {"accept": B}, ["accept"]),
    _fn("get_charging_coaching", "Feedback and tips on the owner's charging habits."),
    _fn("get_cost_and_resale", "Running cost per km, savings vs petrol, and battery-driven resale value."),
]

TOOL_NAMES = {t["function"]["name"] for t in TOOLS}
