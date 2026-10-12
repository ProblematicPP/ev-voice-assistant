"""Application context: wires the battery core, routing, companion and live state together."""
from __future__ import annotations

import pandas as pd

from app import simulation
from app.battery_core.core import BatteryCore
from app.companion import coaching, cost, resale
from app.config import DATA_DIR, VEHICLE
from app.routing.network import RoadNetwork
from app.routing.planner import RoutePlanner
from app.state import VehicleState


class AppContext:
    def __init__(self):
        self.battery = BatteryCore()
        self.net = RoadNetwork()
        self.planner = RoutePlanner(self.net, self.battery)
        self.sessions_hist = pd.read_csv(DATA_DIR / "charging_history.csv")
        self.trips = pd.read_csv(DATA_DIR / "owner_trips.csv")
        self.reset()

    def reset(self):
        self.state = VehicleState(driving_style=self.battery.profile["driving_style"],
                                  odometer_km=float(self.battery.profile["odometer_km"]))

    # -- data -----------------------------------------------------------------
    def sessions(self) -> pd.DataFrame:
        if not self.state.live_sessions:
            return self.sessions_hist
        return pd.concat([self.sessions_hist, pd.DataFrame(self.state.live_sessions)], ignore_index=True)

    def recent_fast_share(self, days: int = 30) -> float:
        s = self.sessions().copy()
        s["start"] = pd.to_datetime(s["start_ts"])
        s = s[s.start > s.start.max() - pd.Timedelta(days=days)]
        return float((s.charger_type == "dc_fast").mean()) if len(s) else 0.0

    # -- companion app ----------------------------------------------------------
    def companion(self) -> dict:
        soh = self.battery.soh()
        sessions = self.sessions()
        return {
            "battery": {k: soh[k] for k in ("soh_pct", "usable_kwh", "nominal_kwh", "cycle_count")},
            "range": self.battery.range(self.state),
            "coaching": coaching.coach(sessions),
            "charging_summary": coaching.summary(sessions),
            "cost": cost.cost_per_km(sessions, self.trips),
            "resale": resale.estimate(self.battery.profile, self.battery.soh_now, self.recent_fast_share()),
        }

    # -- UI snapshot ------------------------------------------------------------
    def snapshot(self) -> dict:
        st = self.state
        recent = self.sessions().tail(12).iloc[::-1].to_dict("records")
        return {
            "vehicle": {**st.public(), "location_name": self.net.name(st.location),
                        "home_node": VEHICLE["home_node"], "name": VEHICLE["name"]},
            "battery": self.battery.soh(),
            "range": self.battery.range(st),
            "route": st.active_plan,
            "route_projection": simulation.remaining_projection(self),
            "home": simulation.home_projection(self),
            "recent_charging": recent,
            "events": st.events[-12:][::-1],
            "pending_offer": st.pending_offer,
        }


_ctx: AppContext | None = None


def get_ctx() -> AppContext:
    global _ctx
    if _ctx is None:
        _ctx = AppContext()
    return _ctx
