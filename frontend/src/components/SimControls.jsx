import { useEffect, useRef, useState } from "react";
import { api } from "../api.js";

const SCENARIOS = [
  { id: "low_far_from_home", label: "Low battery, far from home" },
  { id: "hot_day_plugged_in", label: "Hot day, plugged in at home" },
  { id: "cold_morning", label: "Cold morning, aggressive driving" },
  { id: "full_battery", label: "Full battery" },
  { id: "road_trip", label: "Road trip, 74% charge" },
];

// Teleport targets for demos (real OSM places)
const LOCATIONS = ["koramangala", "whitefield", "indiranagar", "electronic_city", "kempegowda_airport", "kengeri",
  "ramanagara", "channapatna", "maddur", "mandya", "mysuru", "tumakuru", "kolar", "hassan", "chikkaballapur"];

/** Demo controls for the synthetic vehicle. Changes trigger proactive nudges server-side. */
export default function SimControls({ state, network }) {
  const v = state.vehicle;
  const [draft, setDraft] = useState({});
  const [error, setError] = useState("");
  const timer = useRef(null);

  // Forget local edits once the server state reflects them
  useEffect(() => setDraft({}), [v.soc, v.ambient_temp_c, v.driving_style, v.payload_kg]);

  const call = async (path, body) => {
    setError("");
    try { await api(path, { method: "POST", body }); } catch (e) { setError(e.message); }
  };
  const update = (patch, debounce = 0) => {
    setDraft((d) => ({ ...d, ...patch }));
    clearTimeout(timer.current);
    timer.current = setTimeout(() => call("/sim/update", patch), debounce);
  };
  const val = (k) => draft[k] ?? v[k];
  const places = Object.fromEntries((network?.places ?? []).map((p) => [p.id, p]));
  const placeNode = (id) => places[id]?.node;

  return (
    <div className="tab-body">
      <p className="muted" style={{ marginTop: 0 }}>
        Change the simulated car to trigger proactive nudges and re-planning. Scenarios reset everything else.
      </p>
      <h3>Scenarios</h3>
      <div className="scenarios">
        {SCENARIOS.map((s) => (
          <button key={s.id} className="btn small" onClick={() => call(`/sim/scenario/${s.id}`)}>{s.label}</button>
        ))}
        <button className="btn small" onClick={() => call("/sim/reset")}>Reset</button>
      </div>
      <h3>Vehicle state</h3>
      <div className="sim-grid">
        <label className="field">
          <span>Charge <span className="val">{Math.round(val("soc") * 100)}%</span></span>
          <input type="range" min="0.03" max="1" step="0.01" value={val("soc")}
            onChange={(e) => update({ soc: +e.target.value }, 350)} />
        </label>
        <label className="field">
          <span>Outside temperature <span className="val">{Math.round(val("ambient_temp_c"))} °C</span></span>
          <input type="range" min="0" max="46" step="1" value={val("ambient_temp_c")}
            onChange={(e) => update({ ambient_temp_c: +e.target.value }, 350)} />
        </label>
        <label className="field">
          <span title="0 = smooth, 1 = aggressive">Driving style <span className="val">{val("driving_style").toFixed(2)}</span></span>
          <input type="range" min="0" max="1" step="0.01" value={val("driving_style")}
            onChange={(e) => update({ driving_style: +e.target.value }, 350)} />
        </label>
        <label className="field">
          <span>Load <span className="val">{Math.round(val("payload_kg"))} kg</span></span>
          <input type="range" min="0" max="400" step="25" value={val("payload_kg")}
            onChange={(e) => update({ payload_kg: +e.target.value }, 350)} />
        </label>
        <label className="field">
          <span>Climate</span>
          <select value={v.hvac_mode} onChange={(e) => update({ hvac_mode: e.target.value })}>
            <option value="off">Off</option><option value="fan">Fan</option>
            <option value="ac">AC</option><option value="heat">Heater</option>
          </select>
        </label>
        <label className="field">
          <span>Location {v.driving && <span className="faint">(set by route)</span>}</span>
          <select value={LOCATIONS.find((id) => placeNode(id) === v.location) ?? ""} disabled={v.driving}
            onChange={(e) => e.target.value && update({ location: e.target.value })}>
            {!LOCATIONS.some((id) => placeNode(id) === v.location) && <option value="">{v.location_name}</option>}
            {LOCATIONS.filter((id) => places[id]).map((id) => <option key={id} value={id}>{places[id].name}</option>)}
          </select>
        </label>
        <label className="field" style={{ alignSelf: "center" }}>
          <span><input type="checkbox" checked={v.plugged_in} disabled={v.driving}
            onChange={(e) => update({ plugged_in: e.target.checked })} /> Plugged in</span>
        </label>
        <div className="field">
          <span>Drive forward {v.driving ? "along the route" : "around town"}</span>
          <div style={{ display: "flex", gap: 6 }}>
            {[10, 30, 60].map((km) => (
              <button key={km} className="btn small" onClick={() => call("/sim/drive", { km })}>+{km} km</button>
            ))}
          </div>
        </div>
      </div>

      {error && <p className="status bad" role="alert">{error}</p>}

      <h3>Event log</h3>
      {state.events.length === 0 && <p className="faint">Nothing yet. Routes, charging, nudges and simulated features appear here.</p>}
      {state.events.length > 0 && (
        <div className="events" aria-label="Vehicle event log">
          {state.events.map((e, i) => (
            <div key={i}><span className="k">{{ stub: "Stub", route: "Route", charge: "Charge", arrival: "Arrived", nudge: "Nudge" }[e.kind] ?? e.kind}</span>{e.message}</div>
          ))}
        </div>
      )}
    </div>
  );
}
