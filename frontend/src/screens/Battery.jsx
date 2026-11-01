import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { inr, pct } from "../api.js";

const TYPES = [
  { key: "home_ac", label: "Home", color: "var(--series-1)" },
  { key: "dc_fast", label: "Fast charger", color: "var(--series-2)" },
  { key: "public_ac", label: "Public AC", color: "var(--series-3)" },
];
const axis = { fontSize: 11, fill: "var(--ink-3)" };
const MONTH = new Intl.DateTimeFormat("en-IN", { month: "short", year: "2-digit" });
const WHEN = new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });

function SohTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return <div className="tooltip"><b>{p.date}</b>Health {(p.soh * 100).toFixed(1)}%</div>;
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

function RangeFactors({ explain }) {
  const rows = explain.contributions.filter((c) => Math.abs(c.km) >= 0.5);
  const max = Math.max(...rows.map((c) => Math.abs(c.km)), 1);
  return (
    <section className="block">
      <h2 className="section-title">Why {Math.round(explain.current_km)} km and not {Math.round(explain.expected_km)} km</h2>
      <p className="block-sub">Compared with a new battery on a mild day with the AC off.</p>
      <div className="bars" role="list">
        {rows.map((c) => (
          <div className="bar-row" key={c.factor} role="listitem" title={c.detail}>
            <span>{c.label}</span>
            <span className="bar-track">
              <span className={`bar-fill ${c.km < 0 ? "loss" : "gain"}`} style={{ width: `${(Math.abs(c.km) / max) * 100}%` }} />
            </span>
            <span className="v num">{c.km > 0 ? "+" : "−"}{Math.abs(Math.round(c.km))} km</span>
          </div>
        ))}
      </div>
    </section>
  );
}

export default function Battery({ state, companion, explain }) {
  const b = state.battery;
  const weekly = companion?.charging_summary?.weekly_kwh?.map((w) => ({ ...w, week: w.week.slice(5) })) ?? [];
  return (
    <div className="scroll">
      <header className="app-bar"><div><h1>Battery</h1></div></header>

      <section className="health">
        <div className="health-ring" style={{ "--p": b.soh_pct }}>
          <span className="num">{Math.round(b.soh_pct)}<small>%</small></span>
        </div>
        <div>
          <h2>Battery health</h2>
          <p>{b.usable_kwh} kWh usable today. At your current charging habits it stays above 70% for
            about {b.rul.years} more years.</p>
        </div>
      </section>
      <div className="stat-row">
        <div><strong className="num">{b.cycle_count}</strong><small>charge cycles</small></div>
        <div><strong className="num">{pct(b.fast_charge_ratio)}</strong><small>fast charging</small></div>
        <div><strong className="num">{state.range.wh_per_km}</strong><small>Wh per km now</small></div>
      </div>

      {explain && <RangeFactors explain={explain} />}

      <section className="block">
        <h2 className="section-title">Health since you bought it</h2>
        <div className="chart-box">
          <ResponsiveContainer>
            <LineChart data={b.trend} margin={{ top: 6, right: 6, left: -18, bottom: 0 }}>
              <CartesianGrid stroke="var(--grid)" vertical={false} />
              <XAxis dataKey="date" tick={axis} tickFormatter={(d) => MONTH.format(new Date(d))} minTickGap={36} stroke="var(--line)" />
              <YAxis tick={axis} domain={[0.8, 1]} tickFormatter={(v) => `${Math.round(v * 100)}%`} stroke="var(--line)" />
              <Tooltip content={<SohTooltip />} cursor={{ stroke: "var(--ink-3)", strokeDasharray: "3 3" }} />
              <Line type="monotone" dataKey="soh" stroke="var(--brand)" strokeWidth={2} dot={false} activeDot={{ r: 5 }}
                isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </section>

      <section className="block">
        <h2 className="section-title">Energy charged each week</h2>
        <div className="chart-box">
          <ResponsiveContainer>
            <BarChart data={weekly} margin={{ top: 6, right: 6, left: -18, bottom: 0 }}>
              <CartesianGrid stroke="var(--grid)" vertical={false} />
              <XAxis dataKey="week" tick={axis} stroke="var(--line)" minTickGap={14} />
              <YAxis tick={axis} stroke="var(--line)" width={40} />
              <Tooltip content={<ChargeTooltip />} cursor={{ fill: "var(--panel-2)" }} />
              {TYPES.map((t, i) => (
                <Bar key={t.key} dataKey={t.key} stackId="a" fill={t.color} stroke="var(--panel)" strokeWidth={1}
                  radius={i === TYPES.length - 1 ? [3, 3, 0, 0] : 0} />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="legend">
          {TYPES.map((t) => <span key={t.key}><i className="swatch" style={{ background: t.color }} />{t.label}</span>)}
          <span className="faint">kWh</span>
        </div>
      </section>

      <section className="block">
        <h2 className="section-title">Recent charging</h2>
        <ul className="list">
          {state.recent_charging.slice(0, 6).map((s) => (
            <li key={s.session_id}>
              <span className={`type-dot ${s.charger_type}`} aria-hidden="true" />
              <span className="list-main">
                <b>{TYPES.find((t) => t.key === s.charger_type)?.label}</b>
                <small>{WHEN.format(new Date(s.start_ts))}</small>
              </span>
              <span className="list-side">
                <b className="num">{pct(s.soc_start)} to {pct(s.soc_end)}</b>
                <small className="num">{s.kwh} kWh, {inr(s.cost_inr)}</small>
              </span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
