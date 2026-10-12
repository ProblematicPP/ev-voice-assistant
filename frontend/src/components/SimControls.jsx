import { useEffect, useRef, useState } from "react";
import { api } from "../api.js";

const SCENARIOS = [
  { id: "low_far_from_home", label: "Low battery, far from home" },
  { id: "hot_day_plugged_in", label: "Hot day, plugged in at home" },
  { id: "cold_morning", label: "Cold morning, aggressive driving" },
  { id: "full_battery", label: "Full battery" },
  { id: "road_trip", label: "Road trip, 82% charge" },
];

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

  return (
    <section className="panel">
      <h2>Demo controls <small>synthetic vehicle state</small></h2>
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
          <span>Driving style <span className="val">{val("driving_style").toFixed(2)}</span> <span className="faint">(0 smooth, 1 aggressive)</span></span>
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
          <select value={v.location} disabled={v.driving} onChange={(e) => update({ location: e.target.value })}>
            {network?.nodes.map((n) => <option key={n.id} value={n.id}>{n.name}</option>)}
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

      <div className="scenarios">
        {SCENARIOS.map((s) => (
          <button key={s.id} className="btn small" onClick={() => call(`/sim/scenario/${s.id}`)}>{s.label}</button>
        ))}
        <button className="btn small" onClick={() => call("/sim/reset")}>Reset</button>
      </div>
      {error && <p className="status bad" role="alert">{error}</p>}

      {state.events.length > 0 && (
        <div className="events" aria-label="Vehicle event log">
          {state.events.map((e, i) => (
            <div key={i}><span className="k">{{ stub: "Stub", route: "Route", charge: "Charge", arrival: "Arrived", nudge: "Nudge" }[e.kind] ?? e.kind}</span>{e.message}</div>
          ))}
        </div>
      )}
    </section>
  );
}
