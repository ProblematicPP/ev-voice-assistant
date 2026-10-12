"""Live single-vehicle session state (in memory; reset with POST /api/sim/reset)."""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field


@dataclass
class VehicleState:
    soc: float = 0.46
    location: str = "koramangala"
    ambient_temp_c: float = 34.0
    hvac_mode: str = "ac"
    payload_kg: float = 75.0
    driving_style: float = 0.62          # overwritten from the owner profile at startup
    plugged_in: bool = False
    precooling: bool = False
    odometer_km: float = 0.0

    active_plan: dict | None = None
    # leg index, node index within that leg's path, waypoints reached so far
    progress: dict = field(default_factory=lambda: {"leg": 0, "node": 0, "waypoints_done": 0})
    trip_km: float = 0.0

    pending_offer: dict | None = None    # proactive suggestion awaiting yes/no
    events: list[dict] = field(default_factory=list)   # stub actions, arrivals, charging
    live_sessions: list[dict] = field(default_factory=list)  # charging done during the demo
    chat_history: list[dict] = field(default_factory=list)
    nudge_log: dict = field(default_factory=dict)

    @property
    def driving(self) -> bool:
        return self.active_plan is not None

    def log(self, kind: str, message: str, **data):
        self.events.append({"ts": time.time(), "kind": kind, "message": message, **data})
        self.events = self.events[-50:]

    def public(self) -> dict:
        d = asdict(self)
        for k in ("chat_history", "nudge_log"):
            d.pop(k)
        d["driving"] = self.driving
        return d
