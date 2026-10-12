import { useEffect, useRef, useState } from "react";
import { pct } from "../api.js";

const HVAC = { off: "Climate off", fan: "Fan", ac: "AC on", heat: "Heater on" };

/** Range ribbon: one km scale carrying personalized range, brochure range and the active route. */
function RangeRibbon({ range, route, projection }) {
  const ref = useRef(null);
  const [W, setW] = useState(800);
  useEffect(() => {
    const ro = new ResizeObserver(([e]) => setW(Math.max(280, e.contentRect.width)));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  const personalized = range.personalized_km;
  const naive = range.naive_km;
  const routeKm = route ? route.totals.distance_km ?? 0 : 0;
  const maxKm = Math.max(naive, personalized, routeKm, 100) * 1.08;
  const x = (km) => (Math.min(km, maxKm) / maxKm) * W;
  const step = maxKm > 300 || W < 500 ? 100 : 50;
  const ticks = [];
  for (let k = 0; k <= maxKm; k += step) ticks.push(k);

  // Route markers: cumulative km at each charging stop and at the destination
  const markers = [];
  if (route && route.legs?.length) {
    let km = 0;
    route.legs.forEach((leg) => {
      km += leg.distance_km;
      if (leg.ends_at_charger) {
        const stop = route.stops.find((s) => s.node === leg.to);
        markers.push({ km, kind: "stop", label: stop?.name.split(" ")[0] ?? "Charge" });
      }
    });
    markers.push({ km, kind: "dest", label: route.destination_names.at(-1) });
  }

  return (
    <svg ref={ref} className="ribbon-svg" viewBox={`0 0 ${W} 86`} role="img"
      aria-label={`Personalized range ${Math.round(personalized)} km, brochure estimate ${Math.round(naive)} km`}>
      <defs>
        <pattern id="hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <line x1="0" y1="0" x2="0" y2="6" stroke="var(--ink-3)" strokeWidth="1.2" />
        </pattern>
      </defs>
      <rect x="0" y="22" width={W} height="26" rx="6" fill="var(--panel-2)" />
      <rect x="0" y="22" width={x(naive)} height="26" rx="6" fill="url(#hatch)" opacity="0.55" />
      <rect x="0" y="22" width={x(personalized)} height="26" rx="6" fill="var(--accent)" />
      {ticks.map((k) => (
        <g key={k}>
          <line x1={x(k)} x2={x(k)} y1="50" y2="56" stroke="var(--ink-3)" />
          <text x={x(k)} y="70" fontSize="12" fill="var(--ink-3)" textAnchor={k === 0 ? "start" : "middle"}
            style={{ fontFamily: "var(--font-num)" }}>{k} km</text>
        </g>
      ))}
      {markers.map((m, i) => (
        <g key={i}>
          <line x1={x(m.km)} x2={x(m.km)} y1="14" y2="50"
            stroke={m.kind === "stop" ? "var(--charge)" : "var(--ink)"} strokeWidth="3" />
          <text x={x(m.km)} y="10" fontSize="12.5" fontWeight="600" textAnchor="middle"
            fill={m.kind === "stop" ? "var(--charge)" : "var(--ink)"}>{m.label}</text>
        </g>
      ))}
      {projection && route && (
        <text x={W} y="84" fontSize="12" textAnchor="end" fill="var(--ink-2)">
          Live arrival estimate {pct(projection.arrival_soc)}
        </text>
      )}
    </svg>
  );
}

export default function VehicleHeader({ state, health, connected }) {
  const v = state.vehicle;
  const r = state.range;
  const llmOn = health?.llm?.available;
  return (
    <section className="panel">
      <div className="topbar">
        <div className="vehicle-line">
          <span><b>{v.location_name}</b></span>
          <span className="num">{v.ambient_temp_c.toFixed(0)} °C outside</span>
          <span>{HVAC[v.hvac_mode]}</span>
          <span>{v.plugged_in ? "Plugged in" : v.driving ? "Driving" : "Parked"}</span>
          <span className="num">Odometer {Math.round(v.odometer_km).toLocaleString("en-IN")} km</span>
        </div>
        <div className="chips">
          <span className={`chip ${connected ? "on" : "off"}`}><span className="dot" />{connected ? "Live" : "Reconnecting"}</span>
          <span className={`chip ${llmOn ? "on" : "off"}`} title={llmOn ? "" : "Using the rule-based parser"}>
            <span className="dot" />{llmOn ? `LLM ${health.llm.model}` : "LLM offline, rule-based mode"}
          </span>
        </div>
      </div>

      <div className="ribbon">
        <div className="ribbon-head">
          <div>
            <div className="big-range">{Math.round(r.personalized_km)}<span>km</span></div>
            <div className="muted" style={{ fontSize: 13.5, marginTop: 4 }}>Range for how you drive today</div>
          </div>
          <div className="ribbon-stat"><strong>{pct(v.soc)}</strong>Charge</div>
          <div className="ribbon-stat"><strong>{Math.round(r.city_km)} / {Math.round(r.highway_km)}</strong>City / highway km</div>
          <div className="ribbon-stat"><strong>{Math.round(r.naive_km)}</strong>Brochure estimate km</div>
          <div className="ribbon-stat"><strong>{r.wh_per_km}</strong>Wh/km now</div>
        </div>
        <RangeRibbon range={r} route={state.route} projection={state.route_projection} />
        <div className="ribbon-legend">
          <span><i className="swatch" style={{ background: "var(--accent)" }} />Personalized range (PyTorch model)</span>
          <span><i className="swatch" style={{ background: "repeating-linear-gradient(45deg, var(--ink-3) 0 1.5px, transparent 1.5px 4px)" }} />Naive SOC × brochure range</span>
          {state.route && <span><i className="swatch" style={{ background: "var(--charge)" }} />Charging stop on route</span>}
        </div>
      </div>
    </section>
  );
}
