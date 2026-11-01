import { useEffect, useMemo, useState } from "react";
import { api, mins, pct } from "../api.js";

const BAND = {
  healthy: { label: "Healthy", cls: "ok" },
  worn: { label: "Worn", cls: "warn" },
  "near end of life": { label: "Near end of life", cls: "bad" },
};

/** Sequential one-hue scale: brand green mixed toward the surface; 0 recedes, peak is full brand. */
const heat = (v, max) => `color-mix(in srgb, var(--brand) ${Math.round(6 + 94 * Math.min(1, v / max))}%, var(--panel))`;

function Heatmap({ demand }) {
  const [hover, setHover] = useState(null);
  const [table, setTable] = useState(false);
  const max = Math.max(...demand.values.flat(), 0.5);
  return (
    <section className="fc-card fc-wide">
      <div className="fc-card-head">
        <div>
          <h2>Rental demand, next 24 hours</h2>
          <p>Forecast bookings per zone per hour from time of day, weekday and weather.</p>
        </div>
        <button className="btn small" onClick={() => setTable((t) => !t)} aria-pressed={table}>
          {table ? "Show heatmap" : "Show as table"}
        </button>
      </div>
      {table ? (
        <div className="fc-scroll">
          <table className="fc-table">
            <thead><tr><th>Zone</th>{demand.hours.map((h) => <th key={h} className="r">{h}</th>)}</tr></thead>
            <tbody>
              {demand.names.map((n, i) => (
                <tr key={n}><td>{n}</td>{demand.values[i].map((v, j) => <td key={j} className="r num">{v.toFixed(1)}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="fc-heat" role="img" aria-label="Demand heatmap, zones by hour" onMouseLeave={() => setHover(null)}>
          <div className="fc-heat-grid" style={{ gridTemplateColumns: `140px repeat(${demand.hours.length}, minmax(14px, 1fr))` }}>
            <span />
            {demand.hours.map((h, j) => <span key={h} className="fc-heat-hour">{j % 3 === 0 ? h.slice(0, 2) : ""}</span>)}
            {demand.names.map((n, i) => (
              <div key={n} className="fc-heat-row">
                <span className="fc-heat-zone">{n}</span>
                {demand.values[i].map((v, j) => (
                  <span key={j} className="fc-heat-cell" style={{ background: heat(v, max) }}
                    onMouseEnter={() => setHover({ zone: n, hour: demand.hours[j], v })} />
                ))}
              </div>
            ))}
          </div>
          <div className="fc-heat-foot">
            <span className="fc-heat-tip">
              {hover ? <><b>{hover.zone}</b> at {hover.hour}: <b className="num">{hover.v.toFixed(1)}</b> bookings expected</>
                : "Hover a cell for the forecast."}
            </span>
            <span className="fc-heat-legend">
              <span className="num">0</span>
              <i style={{ background: `linear-gradient(90deg, ${heat(0, 1)}, ${heat(1, 1)})` }} />
              <span className="num">{max.toFixed(1)} per hour</span>
            </span>
          </div>
        </div>
      )}
      <p className="fc-note">Model error on the last 21 days: {demand.model.mae_vs_true_rate?.toFixed(2)} bookings per
        zone-hour from the true rate, against {demand.model.baseline_mae_vs_true_rate?.toFixed(2)} for a
        zone-and-hour average.</p>
    </section>
  );
}

function Rebalance({ r }) {
  return (
    <section className="fc-card">
      <h2>Move idle cars</h2>
      <p>For the next {r.horizon_h} hours of forecast demand.</p>
      <div className="fc-saving">
        <span><b className="num">{r.expected_lost_before.toFixed(1)}</b> missed rentals expected now</span>
        <span><b className="num">{r.expected_lost_after.toFixed(1)}</b> after these moves</span>
        <span className="pill ok-pill">{r.reduction_pct}% fewer</span>
      </div>
      {r.moves.length ? (
        <ol className="fc-moves">
          {r.moves.map((m) => (
            <li key={m.vehicle_id}>
              <b>{m.vehicle_id}</b> {m.from_name} to {m.to_name}
              <span className="faint"> {m.drive_min} min drive, saves {m.lost_rentals_saved.toFixed(2)} rentals</span>
            </li>
          ))}
        </ol>
      ) : <p className="faint">Idle cars already match demand.</p>}
    </section>
  );
}

function Longevity({ L }) {
  if (!L) return (
    <section className="fc-card"><h2>Battery life</h2><p className="faint">Simulating a year of rentals…</p></section>
  );
  const h = L.health_aware, n = L.first_available;
  const max = Math.max(h.capacity_lost_pct_points, n.capacity_lost_pct_points);
  const rows = [
    { label: "Health-aware allocation", v: h.capacity_lost_pct_points, color: "var(--brand)" },
    { label: "First available car", v: n.capacity_lost_pct_points, color: "var(--ink-3)" },
  ];
  return (
    <section className="fc-card">
      <h2>Battery life</h2>
      <p>Average capacity lost over one simulated year of rentals.</p>
      <div className="fc-bars">
        {rows.map((r) => (
          <div key={r.label} className="fc-bar-row" title={`${r.label}: ${r.v} percentage points`}>
            <span>{r.label}</span>
            <span className="fc-bar-track"><i style={{ width: `${(100 * r.v) / max}%`, background: r.color }} /></span>
            <b className="num">{r.v.toFixed(1)} pts</b>
          </div>
        ))}
      </div>
      <p className="fc-big"><b className="num">+{L.battery_life_extension_pct}%</b> battery life with health-aware allocation</p>
      <p className="fc-note">{L.fast_charges_avoided.toLocaleString("en-IN")} fewer mid-trip fast charges;
        {" "}{h.below_70pct} packs below 70% health after a year instead of {n.below_70pct}.</p>
    </section>
  );
}

function Allocation({ alloc, onPlan, planFor }) {
  const [policy, setPolicy] = useState("health_aware");
  const rows = alloc[policy].assignments;
  return (
    <section className="fc-card fc-wide">
      <div className="fc-card-head">
        <div>
          <h2>Today's bookings</h2>
          <p>Long trips get the healthiest batteries; short city rentals take the worn ones.</p>
        </div>
        <div className="seg" role="group" aria-label="Allocation policy">
          <button aria-pressed={policy === "health_aware"} onClick={() => setPolicy("health_aware")}>Health-aware</button>
          <button aria-pressed={policy === "first_available"} onClick={() => setPolicy("first_available")}>First available</button>
        </div>
      </div>
      <p className="fc-note">Mid-trip fast charges: <b>{alloc.health_aware.fast_charges}</b> health-aware vs
        {" "}<b>{alloc.first_available.fast_charges}</b> first available.</p>
      <div className="fc-scroll">
        <table className="fc-table">
          <thead><tr><th>Booking</th><th>Trip</th><th className="r">km</th><th>Car</th><th className="r">Battery health</th>
            <th className="r">Fast charges</th><th /></tr></thead>
          <tbody>
            {rows.map((a) => (
              <tr key={a.booking_id} className={planFor === a.booking_id ? "sel" : ""}>
                <td>{a.booking_id}</td>
                <td>{a.kind === "long_haul" ? `Long trip${a.destination ? ` to ${a.destination[0].toUpperCase()}${a.destination.slice(1)}` : ""}` : "City"}</td>
                <td className="r num">{a.km}</td>
                <td>{a.vehicle_id ?? "None free"}</td>
                <td className="r num">{a.soh ? pct(a.soh) : "-"}</td>
                <td className="r num">{a.fast_charges ?? "-"}</td>
                <td>{a.kind === "long_haul" && policy === "health_aware" &&
                  <button className="btn small" onClick={() => onPlan(a.booking_id)}>Route</button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function RentalPlan({ plan, onClose }) {
  if (!plan) return null;
  const p = plan.plan;
  return (
    <section className="fc-card fc-wide fc-plan">
      <div className="fc-card-head">
        <div>
          <h2>{plan.booking_id}: {plan.assignment.vehicle_id} round trip</h2>
          <p>Planned on the same charging-aware route planner as the driver app, using this car's {pct(plan.assignment.soh)} battery health.</p>
        </div>
        <button className="btn small" onClick={onClose}>Close</button>
      </div>
      {p && p.status !== "infeasible" ? (
        <>
          <div className="fc-kpis small">
            <div><b className="num">{p.totals.distance_km} km</b><span>round trip</span></div>
            <div><b className="num">{mins(p.totals.total_min)}</b><span>driving and charging</span></div>
            <div><b className="num">{p.stops.length}</b><span>charging stops</span></div>
            <div><b className="num">{pct(p.totals.arrival_soc)}</b><span>back at the depot</span></div>
          </div>
          {p.stops.length > 0 && (
            <ul className="fc-moves">
              {p.stops.map((s) => (
                <li key={s.charger_id}><b>{s.name}</b><span className="faint"> {pct(s.arrive_soc)} to {pct(s.depart_soc)},
                  about {Math.round(s.charge_min)} min, ₹{s.cost_inr}</span></li>
              ))}
            </ul>
          )}
        </>
      ) : <p className="faint">No feasible plan for this booking.</p>}
    </section>
  );
}

export default function FleetConsole() {
  const [d, setD] = useState({});
  const [error, setError] = useState("");
  const [planFor, setPlanFor] = useState(null);
  const [plan, setPlan] = useState(null);

  useEffect(() => {
    const load = (key, path) => api(path).then((v) => setD((s) => ({ ...s, [key]: v }))).catch((e) => setError(e.message));
    load("overview", "/fleet/overview");
    load("alloc", "/fleet/allocation");
    load("demand", "/fleet/demand?hours=24");
    load("rebalance", "/fleet/rebalance");
    load("longevity", "/fleet/longevity");
  }, []);
  useEffect(() => {
    if (!planFor) return setPlan(null);
    api(`/fleet/rental/${planFor}/plan`).then(setPlan).catch((e) => setError(e.message));
  }, [planFor]);

  const vehicles = useMemo(() => [...(d.overview?.vehicles ?? [])].sort((a, b) => a.soh - b.soh), [d.overview]);
  if (error) return <div className="fleet"><p className="banner bad">Fleet data unavailable: {error}</p></div>;
  if (!d.overview) return <div className="fleet"><p className="faint">Loading fleet…</p></div>;
  const o = d.overview;

  return (
    <div className="fleet">
      <header className="fc-head">
        <div>
          <h1>Fleet console</h1>
          <p>Bengaluru rental fleet. Battery health on every car comes from the same battery model as the driver app.</p>
        </div>
      </header>

      <div className="fc-kpis">
        <div><b className="num">{o.count}</b><span>cars, {o.idle} idle</span></div>
        <div><b className="num">{pct(o.avg_soh)}</b><span>average battery health</span></div>
        <div><b className="num">{o.bands["near end of life"] ?? 0}</b><span>near end of life</span></div>
        {d.rebalance && <div><b className="num">{d.rebalance.moves.length}</b><span>moves suggested</span></div>}
      </div>

      <div className="fc-grid">
        {d.demand && <Heatmap demand={d.demand} />}
        {d.rebalance && <Rebalance r={d.rebalance} />}
        <Longevity L={d.longevity} />
        {d.alloc && <Allocation alloc={d.alloc} planFor={planFor} onPlan={(id) => setPlanFor(id === planFor ? null : id)} />}
        <RentalPlan plan={plan} onClose={() => setPlanFor(null)} />
        <section className="fc-card fc-wide">
          <h2>Cars by battery health</h2>
          <p>Remaining life is years until 70% health at each car's own charging habit.</p>
          <div className="fc-scroll">
            <table className="fc-table">
              <thead><tr><th>Car</th><th>Zone</th><th>Status</th><th className="r">Health</th><th>Band</th>
                <th className="r">Charge</th><th className="r">Range</th><th className="r">Years to 70%</th></tr></thead>
              <tbody>
                {vehicles.map((v) => (
                  <tr key={v.vehicle_id}>
                    <td>{v.vehicle_id}</td><td>{v.zone_name}</td><td>{v.status}</td>
                    <td className="r num">{pct(v.soh)}</td>
                    <td><span className={`band ${BAND[v.band].cls}`}><i aria-hidden="true" />{BAND[v.band].label}</span></td>
                    <td className="r num">{pct(v.soc)}</td><td className="r num">{v.range_km} km</td>
                    <td className="r num">{v.years_to_70pct}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </div>
  );
}
