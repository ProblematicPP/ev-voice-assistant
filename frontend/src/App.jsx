import { useEffect, useRef, useState } from "react";
import { api, useLive } from "./api.js";
import AssistantPanel from "./components/AssistantPanel.jsx";
import VehicleHeader from "./components/VehicleHeader.jsx";
import TripTab from "./components/TripTab.jsx";
import VehicleStatePanel from "./components/VehicleStatePanel.jsx";
import CompanionPanel from "./components/CompanionPanel.jsx";
import SimControls from "./components/SimControls.jsx";

const TABS = [
  { id: "trip", label: "Trip" },
  { id: "battery", label: "Battery" },
  { id: "ownership", label: "Ownership" },
  { id: "simulator", label: "Simulator" },
];

const isTab = (id) => TABS.some((t) => t.id === id);

/** Active tab: URL hash (#battery, shareable) > remembered choice > Trip. */
function useTab() {
  const [tab, setTab] = useState(() => {
    const hash = location.hash.slice(1);
    if (isTab(hash)) return hash;
    try { const saved = localStorage.getItem("volt-tab"); return isTab(saved) ? saved : "trip"; } catch { return "trip"; }
  });
  useEffect(() => {
    const onHash = () => isTab(location.hash.slice(1)) && setTab(location.hash.slice(1));
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  const choose = (id) => {
    setTab(id);
    history.replaceState(null, "", `#${id}`);
    try { localStorage.setItem("volt-tab", id); } catch { /* storage blocked */ }
  };
  return [tab, choose];
}

function TabBar({ tab, onChange, badges }) {
  const refs = useRef({});
  const onKey = (e, i) => {
    const d = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (!d) return;
    const next = TABS[(i + d + TABS.length) % TABS.length].id;
    onChange(next);
    refs.current[next]?.focus();
  };
  return (
    <div className="tabbar" role="tablist" aria-label="Sections">
      {TABS.map((t, i) => (
        <button key={t.id} ref={(el) => (refs.current[t.id] = el)} role="tab" id={`tab-${t.id}`}
          aria-selected={tab === t.id} aria-controls={tab === t.id ? `panel-${t.id}` : undefined} tabIndex={tab === t.id ? 0 : -1}
          className={`tab ${tab === t.id ? "active" : ""}`} onClick={() => onChange(t.id)} onKeyDown={(e) => onKey(e, i)}>
          {t.label}
          {badges[t.id] && <span className={`tab-badge ${badges[t.id].kind}`}>{badges[t.id].text}</span>}
        </button>
      ))}
    </div>
  );
}

export default function App() {
  const live = useLive();
  const { state } = live;
  const [network, setNetwork] = useState(null);
  const [health, setHealth] = useState(null);
  const [companion, setCompanion] = useState(null);
  const [explain, setExplain] = useState(null);
  const [tab, setTab] = useTab();

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

  // Jump to the Trip tab when the assistant creates or changes a route
  const routeKey = state?.route ? `${state.route.destinations.join(",")}|${state.route.stops.length}` : "";
  const lastRoute = useRef(null);
  const loaded = Boolean(state);
  useEffect(() => {
    if (!loaded) return;                       // the first snapshot is a baseline, not a change
    if (lastRoute.current !== null && routeKey && routeKey !== lastRoute.current) setTab("trip");
    lastRoute.current = routeKey;
  }, [routeKey, loaded]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!state) {
    return (
      <div className="connecting">
        Connecting to the backend on port 8000. Start it with <code>uvicorn app.main:app --port 8000</code> in
        the backend folder.
      </div>
    );
  }

  const warnTips = companion?.coaching.filter((t) => t.severity === "warn").length ?? 0;
  const badges = {
    trip: state.route ? (state.route_projection?.at_risk ? { kind: "bad", text: "at risk" } : { kind: "info", text: "active" }) : null,
    ownership: warnTips ? { kind: "warn", text: String(warnTips) } : null,
  };

  return (
    <div className="app">
      <AssistantPanel live={live} health={health} />
      <main className="main">
        <VehicleHeader state={state} health={health} connected={live.connected} />
        <section className="panel tabs-panel">
          <TabBar tab={tab} onChange={setTab} badges={badges} />
          {/* Only the active tab is mounted: the map and charts need a visible container to size themselves */}
          <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
            {tab === "trip" && <TripTab state={state} network={network} />}
            {tab === "battery" && <VehicleStatePanel state={state} companion={companion} explain={explain} />}
            {tab === "ownership" && <CompanionPanel companion={companion} />}
            {tab === "simulator" && <SimControls state={state} network={network} />}
          </div>
        </section>
      </main>
    </div>
  );
}
