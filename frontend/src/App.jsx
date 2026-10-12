import { useEffect, useState } from "react";
import { api, useLive } from "./api.js";
import AssistantPanel from "./components/AssistantPanel.jsx";
import VehicleHeader from "./components/VehicleHeader.jsx";
import RoutePlanPanel from "./components/RoutePlanPanel.jsx";
import VehicleStatePanel from "./components/VehicleStatePanel.jsx";
import CompanionPanel from "./components/CompanionPanel.jsx";
import SimControls from "./components/SimControls.jsx";

export default function App() {
  const live = useLive();
  const { state } = live;
  const [network, setNetwork] = useState(null);
  const [health, setHealth] = useState(null);
  const [companion, setCompanion] = useState(null);
  const [explain, setExplain] = useState(null);

  useEffect(() => {
    api("/network").then(setNetwork).catch(() => {});
    const loadHealth = () => api("/health").then(setHealth).catch(() => setHealth(null));
    loadHealth();
    const t = setInterval(loadHealth, 15000);
    return () => clearInterval(t);
  }, []);

  // Companion + range explanation depend on live state; refetch when it changes
  const v = state?.vehicle;
  const key = v ? [v.soc, v.ambient_temp_c, v.hvac_mode, v.payload_kg, v.driving_style, v.live_sessions.length].join("|") : "";
  useEffect(() => {
    if (!key) return;
    const t = setTimeout(() => {
      api("/companion").then(setCompanion).catch(() => {});
      api("/battery/explain").then(setExplain).catch(() => {});
    }, 250);
    return () => clearTimeout(t);
  }, [key]);

  if (!state) {
    return (
      <div className="connecting">
        Connecting to the backend on port 8000. Start it with <code>uvicorn app.main:app --port 8000</code> in
        the backend folder.
      </div>
    );
  }

  return (
    <div className="app">
      <AssistantPanel live={live} health={health} />
      <main className="main">
        <VehicleHeader state={state} health={health} connected={live.connected} />
        <RoutePlanPanel state={state} network={network} />
        <div className="two-up">
          <VehicleStatePanel state={state} companion={companion} explain={explain} />
          <CompanionPanel companion={companion} />
        </div>
        <SimControls state={state} network={network} />
      </main>
    </div>
  );
}
