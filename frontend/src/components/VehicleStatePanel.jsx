import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { inr, pct } from "../api.js";

const TYPES = [
  { key: "home_ac", label: "Home AC", color: "var(--series-1)" },
  { key: "dc_fast", label: "DC fast", color: "var(--series-2)" },
  { key: "public_ac", label: "Public AC", color: "var(--series-3)" },
];
const axis = { fontSize: 11.5, fill: "var(--ink-3)" };

function SohTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return <div className="tooltip"><b>{p.date}</b>SOH {(p.soh * 100).toFixed(1)}% · cycle {p.cycle}</div>;
}

function ChargeTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="tooltip">
      <b>Week of {label}</b>
      {TYPES.map((t) => {
        const v = payload.find((p) => p.dataKey === t.key)?.value ?? 0;
        return <div key={t.key}><i className="swatch" style={{ background: t.color }} />{t.label}: {v} kWh</div>;
      })}
    </div>
  );
}

function Attribution({ explain }) {
  if (!explain) return null;
  const rows = explain.contributions.filter((c) => Math.abs(c.km) >= 0.5);
  const max = Math.max(...rows.map((c) => Math.abs(c.km)), 1);
  return (
    <>
      <h3>Why {Math.round(explain.current_km)} km and not {Math.round(explain.expected_km)} km</h3>
      <div className="bars" role="list">
        {rows.map((c) => (
          <div className="bar-row" key={c.factor} role="listitem" title={c.detail}>
            <span>{c.label}</span>
            <span className="bar-track">
              <span className={`bar-fill ${c.km < 0 ? "loss" : "gain"}`}
                style={{ width: `${(Math.abs(c.km) / max) * 100}%`, display: "block" }} />
            </span>
            <span className="v">{c.km > 0 ? "+" : ""}{Math.round(c.km)} km</span>
          </div>
        ))}
      </div>
      <p className="faint" style={{ fontSize: 12.5, margin: "8px 0 0" }}>
        Shapley attribution vs a new pack at 25 °C, AC off, typical driving.
      </p>
    </>
  );
}

export default function VehicleStatePanel({ state, companion, explain }) {
  const b = state.battery;
  const weekly = companion?.charging_summary?.weekly_kwh?.map((w) => ({ ...w, week: w.week.slice(5) })) ?? [];
  return (
    <section className="panel">
      <h2>Battery health <small>{b.model.type}, MAE {(b.model.mae * 100).toFixed(2)}% SOH</small></h2>
      <div className="kv">
        <div><small>State of health</small><strong>{b.soh_pct}%</strong></div>
        <div><small>Usable capacity</small><strong>{b.usable_kwh} kWh</strong></div>
        <div><small>Charge cycles</small><strong>{b.cycle_count}</strong></div>
        <div><small>Fast-charge share</small><strong>{pct(b.fast_charge_ratio)}</strong></div>
      </div>

      <h3>Estimated SOH since purchase</h3>
      <div className="chart-box">
        <ResponsiveContainer>
          <LineChart data={b.trend} margin={{ top: 6, right: 8, left: -14, bottom: 0 }}>
            <CartesianGrid stroke="var(--grid)" vertical={false} />
            <XAxis dataKey="date" tick={axis} tickFormatter={(d) => d.slice(0, 7)} minTickGap={40} stroke="var(--line)" />
            <YAxis tick={axis} domain={[0.8, 1]} tickFormatter={(v) => `${Math.round(v * 100)}%`} stroke="var(--line)" />
            <Tooltip content={<SohTooltip />} cursor={{ stroke: "var(--ink-3)", strokeDasharray: "3 3" }} />
            <Line type="monotone" dataKey="soh" stroke="var(--accent)" strokeWidth={2} dot={false} activeDot={{ r: 5 }} />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <Attribution explain={explain} />

      <h3>Charging energy per week</h3>
      <div className="chart-box">
        <ResponsiveContainer>
          <BarChart data={weekly} margin={{ top: 6, right: 8, left: -14, bottom: 0 }}>
            <CartesianGrid stroke="var(--grid)" vertical={false} />
            <XAxis dataKey="week" tick={axis} stroke="var(--line)" minTickGap={16} />
            <YAxis tick={axis} stroke="var(--line)" unit=" kWh" width={64} />
            <Tooltip content={<ChargeTooltip />} cursor={{ fill: "var(--panel-2)" }} />
            {TYPES.map((t, i) => (
              <Bar key={t.key} dataKey={t.key} stackId="a" fill={t.color} stroke="var(--panel)" strokeWidth={1}
                radius={i === TYPES.length - 1 ? [4, 4, 0, 0] : 0} />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="legend">
        {TYPES.map((t) => <span key={t.key}><i className="swatch" style={{ background: t.color }} />{t.label}</span>)}
      </div>

      <h3>Recent charging sessions</h3>
      <div style={{ overflowX: "auto" }}>
        <table className="simple">
          <thead><tr><th>When</th><th>Type</th><th className="r">SOC</th><th className="r">kWh</th><th className="r">Cost</th></tr></thead>
          <tbody>
            {state.recent_charging.slice(0, 6).map((s) => (
              <tr key={s.session_id}>
                <td>{s.start_ts.replace("T", " ").slice(5, 16)}</td>
                <td><span className={`type-pill ${s.charger_type}`}>{TYPES.find((t) => t.key === s.charger_type)?.label}</span></td>
                <td className="r">{pct(s.soc_start)} → {pct(s.soc_end)}</td>
                <td className="r">{s.kwh}</td>
                <td className="r">{inr(s.cost_inr)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
