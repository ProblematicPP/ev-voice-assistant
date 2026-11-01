import { useState } from "react";
import { api } from "../api.js";
import { SlidersIcon } from "../icons.jsx";
import SimControls from "./SimControls.jsx";

/** Demo tooling that lives beside the phone, not inside the app: system status, assistant trace, simulator. */
export default function SimDock({ state, network, health, connected, messages }) {
  const [open, setOpen] = useState(true);
  const [weatherMsg, setWeatherMsg] = useState("");
  const liveWeather = async () => {
    setWeatherMsg("Fetching…");
    try { await api("/sim/weather/live", { method: "POST" }); setWeatherMsg(""); }
    catch (e) { setWeatherMsg(e.message); }
  };
  const w = state?.inputs?.weather_now;
  const lastReply = messages.findLast((m) => m.role === "assistant");
  const llm = health?.llm;
  return (
    <aside className={`sim-dock ${open ? "open" : ""}`} aria-label="Simulator">
      <button className="sim-toggle" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <SlidersIcon size={18} />Simulator
      </button>
      {open && (
        <div className="sim-body">
          <p className="sim-note">Demo controls for the simulated car. Not part of the app.</p>

          <h3>System</h3>
          <dl className="sys">
            <dt>Backend</dt>
            <dd className={connected ? "ok" : "bad"}>{connected ? "Connected" : "Not reachable on port 8000. Run uvicorn app.main:app --port 8000 in backend/"}</dd>
            <dt>Assistant</dt>
            <dd className={llm?.available ? "ok" : "warn"}>{llm ? (llm.available ? `LLM (${llm.model})` : "Rule-based parser (Ollama offline)") : "Unknown"}</dd>
            <dt>Map data</dt>
            <dd>{network ? `${network.chargers.length} chargers, including ${network.chargers.filter((c) => c.demo).length} demo` : "Loading"}</dd>
            <dt>Weather</dt>
            <dd>
              {w ? `Live, ${w.temp_c} °C ${w.condition ?? ""} (Open-Meteo)` : "Simulated (slider below)"}{" "}
              <button className="btn small" onClick={liveWeather} disabled={!connected}>Use live weather</button>
              {weatherMsg && <span className="faint"> {weatherMsg}</span>}
            </dd>
            <dt>Traffic</dt><dd>Simulated rush hours (adds to ETA)</dd>
            <dt>Chargers</dt><dd>Simulated queues and outages</dd>
          </dl>

          {lastReply?.tools?.length > 0 && (
            <>
              <h3>Last assistant turn</h3>
              <ul className="trace">
                {lastReply.tools.map((t, i) => (
                  <li key={i}>
                    <code>{t.name}</code>
                    <span>{Object.entries(t.args ?? {}).filter(([, v]) => v !== false && v !== "").map(([k, v]) => `${k}=${v}`).join(", ")}</span>
                    {t.guard && <span className={`guard ${t.ok ? "ok" : "bad"}`}>guard: {t.verdict ?? ""} ({t.guard})</span>}
                  </li>
                ))}
                <li className="faint">Parsed by {lastReply.source === "llm" ? "the LLM" : "the rule-based parser"}</li>
              </ul>
            </>
          )}

          {state && <SimControls state={state} network={network} />}
        </div>
      )}
    </aside>
  );
}
