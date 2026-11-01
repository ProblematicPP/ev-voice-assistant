"""Application context: wires the battery core, routing, companion and live state together."""
from __future__ import annotations

import pandas as pd

from app import simulation
from app.battery_core.core import BatteryCore
from app import telemetry
from app.companion import coaching, cost, eco, resale
from app.config import DATA_DIR, VEHICLE
from app.inputs import Inputs
from app.routing.network import RoadNetwork
from app.routing.planner import RoutePlanner
from app.state import VehicleState


class AppContext:
    def __init__(self):
        self.battery = BatteryCore()
        self.net = RoadNetwork()
        self.inputs = Inputs()
        self.telemetry = telemetry.SimulatedCanBus()      # stands in for the OBD-II/CAN dongle (telemetry.ObdDongle)
        self._telemetry_history = None
        self._fleet = None
        self._longevity = None
        self.planner = RoutePlanner(self.net, self.battery, self.inputs)
        self.sessions_hist = pd.read_csv(DATA_DIR / "charging_history.csv")
        self.trips = pd.read_csv(DATA_DIR / "owner_trips.csv")
        self.reset()

    def reset(self):
        self.state = VehicleState(driving_style=self.battery.profile["driving_style"],
                                  odometer_km=float(self.battery.profile["odometer_km"]),
                                  location=self.home_node)

    @property
    def home_node(self) -> int:
        return self.net.place_node(VEHICLE["home_node"])

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

    def telemetry_history(self) -> dict:
        """Harsh-event summary over the owner's past trips, replayed through the simulated CAN logger."""
        if self._telemetry_history is None:
            events, km = [], 0.0
            for i, t in enumerate(self.trips.itertuples()):
                cond = {"driving_style": t.driving_style, "ambient_temp_c": t.ambient_temp_c}
                f = self.telemetry.frames(t.distance_km, cond, t.soc_start, t.highway_share, seed=i)
                events += telemetry.detect_events(f)
                km += t.distance_km
            self._telemetry_history = telemetry.summarize(events, km)
        return self._telemetry_history

    # -- fleet module (loaded on first use) -------------------------------------
    def fleet(self):
        if self._fleet is None:
            from app.fleet import FleetManager
            self._fleet = FleetManager(self)
        return self._fleet

    def fleet_longevity(self) -> dict:
        if self._longevity is None:
            self._longevity = self.fleet().longevity()
        return self._longevity

    def eco(self) -> dict:
        recent = (self.state.telemetry or {}).get("drive")
        return eco.coach(self.battery, self.state, self.telemetry_history(), recent)

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
            "resale": resale.estimate(self.battery, self.recent_fast_share()),
            "eco": self.eco(),
        }

    # -- UI snapshot ------------------------------------------------------------
    def snapshot(self) -> dict:
        st = self.state
        recent = self.sessions().tail(12).iloc[::-1].to_dict("records")
        return {
            "vehicle": {**st.public(), "location_name": self.net.name(st.location),
                        "home_node": self.home_node, "name": VEHICLE["name"],
                        "lat": self.net.coords(st.location)[0], "lon": self.net.coords(st.location)[1]},
            "battery": self.battery.soh(),
            "range": self.battery.range(st),
            "route": st.active_plan,
            "route_projection": simulation.remaining_projection(self),
            "home": simulation.home_projection(self),
            "recent_charging": recent,
            "events": st.events[-12:][::-1],
            "pending_offer": st.pending_offer,
            "inputs": {**self.inputs.describe(), "weather_now": st.weather},
        }


_ctx: AppContext | None = None


def get_ctx() -> AppContext:
    global _ctx
    if _ctx is None:
        _ctx = AppContext()
    return _ctx
