import { useEffect, useRef, useState } from "react";
import { api, useLive } from "./api.js";
import { BatteryIcon, HomeIcon, InsightsIcon, MicIcon, RouteIcon } from "./icons.jsx";
import Home from "./screens/Home.jsx";
import Navigate from "./screens/Navigate.jsx";
import Volt from "./screens/Volt.jsx";
import Battery from "./screens/Battery.jsx";
import Insights from "./screens/Insights.jsx";
import SimDock from "./components/SimDock.jsx";
import FleetConsole from "./screens/FleetConsole.jsx";

const TABS = [
  { id: "home", label: "Home", icon: HomeIcon },
  { id: "trip", label: "Trip", icon: RouteIcon },
  { id: "volt", label: "Volt", icon: MicIcon },
  { id: "battery", label: "Battery", icon: BatteryIcon },
  { id: "ownership", label: "Ownership", icon: InsightsIcon },
];
const isTab = (id) => TABS.some((t) => t.id === id);

/** Active screen: URL hash (#battery, shareable) > remembered choice > Home. */
function useTab() {
  const [tab, setTab] = useState(() => {
    const hash = location.hash.slice(1);
    if (isTab(hash)) return hash;
    try { const saved = localStorage.getItem("volt-screen"); return isTab(saved) ? saved : "home"; } catch { return "home"; }
  });
  useEffect(() => {
    const onHash = () => isTab(location.hash.slice(1)) && setTab(location.hash.slice(1));
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  const choose = (id) => {
    setTab(id);
    history.replaceState(null, "", `#${id}`);
    try { localStorage.setItem("volt-screen", id); } catch { /* storage blocked */ }
  };
  return [tab, choose];
}

function BottomNav({ tab, onChange, alert }) {
  return (
    <nav className="bottom-nav" aria-label="Sections">
      {TABS.map(({ id, label, icon: I }) => (
        <button key={id} className={`nav-item ${id === "volt" ? "nav-volt" : ""} ${tab === id ? "active" : ""}`}
          aria-current={tab === id ? "page" : undefined} onClick={() => onChange(id)}>
          <span className="nav-icon"><I size={id === "volt" ? 26 : 22} />{alert[id] && <i className="nav-dot" />}</span>
          <span className="nav-label">{label}</span>
        </button>
      ))}
    </nav>
  );
}

/** Volt's reply pops up as a toast when it arrives while another screen is open. */
function useReplyToast(messages, tab) {
  const [toast, setToast] = useState(null);
  const seen = useRef(null);
  useEffect(() => {
    const last = messages.at(-1);
    if (!last || last.role === "user") return;
    if (seen.current === null) { seen.current = last.id; return; }
    if (last.id === seen.current) return;
    seen.current = last.id;
    if (tab === "volt") return;
    setToast(last);
    const t = setTimeout(() => setToast(null), 7000);
    return () => clearTimeout(t);
  }, [messages, tab]);
  useEffect(() => { if (tab === "volt") setToast(null); }, [tab]);
  return [toast, () => setToast(null)];
}

/** Top-level view: the driver's phone app (default) or the fleet operator's console (#fleet). */
function useView() {
  const [view, setView] = useState(() => (location.hash === "#fleet" ? "fleet" : "app"));
  const choose = (v) => {
    setView(v);
    let screen = "home";
    try { screen = localStorage.getItem("volt-screen") || "home"; } catch { /* storage blocked */ }
    history.replaceState(null, "", v === "fleet" ? "#fleet" : `#${screen}`);
  };
  return [view, choose];
}

function ViewSwitch({ view, onChange }) {
  return (
    <nav className="view-switch seg" aria-label="View">
      <button aria-pressed={view === "app"} onClick={() => onChange("app")}>Driver app</button>
      <button aria-pressed={view === "fleet"} onClick={() => onChange("fleet")}>Fleet console</button>
    </nav>
  );
}

export default function App() {
  const [view, setView] = useView();
  const live = useLive();
  const { state, messages } = live;
  const [network, setNetwork] = useState(null);
  const [health, setHealth] = useState(null);
  const [companion, setCompanion] = useState(null);
  const [explain, setExplain] = useState(null);
  const [tab, setTab] = useTab();
  const [toast, closeToast] = useReplyToast(messages, tab);

  useEffect(() => {
    api("/network").then(setNetwork).catch(() => {});
    const loadHealth = () => api("/health").then(setHealth).catch(() => setHealth(null));
    loadHealth();
    const t = setInterval(loadHealth, 15000);
    return () => clearInterval(t);
  }, []);

  // Companion data and the range breakdown depend on live state; refetch when it changes
  const v = state?.vehicle;
  const key = v ? [v.soc, v.ambient_temp_c, v.hvac_mode, v.payload_kg, v.driving_style, v.charging_habit, v.live_sessions.length].join("|") : "";
  useEffect(() => {
    if (!key) return;
    const t = setTimeout(() => {
      api("/companion").then(setCompanion).catch(() => {});
      api("/battery/explain").then(setExplain).catch(() => {});
    }, 250);
    return () => clearTimeout(t);
  }, [key]);

  // Open the map when a route is created or changed
  const routeKey = state?.route ? `${state.route.destinations.join(",")}|${state.route.stops.length}` : "";
  const lastRoute = useRef(null);
  const loaded = Boolean(state);
  useEffect(() => {
    if (!loaded) return;                       // the first snapshot is a baseline, not a change
    if (lastRoute.current !== null && routeKey && routeKey !== lastRoute.current) setTab("trip");
    lastRoute.current = routeKey;
  }, [routeKey, loaded]); // eslint-disable-line react-hooks/exhaustive-deps

  const alert = {
    trip: Boolean(state?.route_projection?.at_risk),
    ownership: (companion?.coaching ?? []).some((t) => t.severity === "warn"),
  };
  const props = { state, live, network, companion, explain, go: setTab };

  if (view === "fleet") {
    return (
      <>
        <ViewSwitch view={view} onChange={setView} />
        <FleetConsole />
      </>
    );
  }

  return (
    <>
    <ViewSwitch view={view} onChange={setView} />
    <div className="stage">
      <div className="device">
        <div className="app-screen">
          {!state ? (
            <div className="connecting" role="status">
              <span className="spinner" aria-hidden="true" />
              <p>Connecting to your car…</p>
            </div>
          ) : (
            <>
              <main className="screen" key={tab}>
                {tab === "home" && <Home {...props} />}
                {tab === "trip" && <Navigate {...props} />}
                {tab === "volt" && <Volt {...props} />}
                {tab === "battery" && <Battery {...props} />}
                {tab === "ownership" && <Insights {...props} />}
              </main>
              {toast && (
                <button className={`toast ${toast.role}`} onClick={() => { closeToast(); setTab("volt"); }}>
                  <b>{toast.role === "nudge" ? "Volt suggests" : "Volt"}</b>
                  <span>{toast.text}</span>
                </button>
              )}
              <BottomNav tab={tab} onChange={setTab} alert={alert} />
            </>
          )}
        </div>
      </div>
      <SimDock state={state} network={network} health={health} connected={live.connected} messages={messages} />
    </div>
    </>
  );
}
