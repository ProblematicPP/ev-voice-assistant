import { inr, lakh, pct } from "../api.js";

export default function CompanionPanel({ companion }) {
  if (!companion) return <section className="panel"><h2>Companion app</h2><p className="muted">Loading…</p></section>;
  const { battery, range, coaching, cost, resale } = companion;
  return (
    <section className="panel">
      <h2>Companion app <small>owner view</small></h2>
      <div className="kv">
        <div><small>Battery health</small><strong>{battery.soh_pct}%</strong></div>
        <div><small>Your range now</small><strong>{Math.round(range.personalized_km)} km</strong></div>
        <div><small>Cost per km</small><strong>₹{cost.cost_per_km_inr.toFixed(2)}</strong></div>
        <div><small>Est. resale value</small><strong>{lakh(resale.estimated_value_inr)}</strong></div>
      </div>

      <h3>Charging coach</h3>
      <div className="tips">
        {coaching.map((t) => (
          <div key={t.id} className={`tip ${t.severity}`}>
            <div className="t">{t.title}</div>
            <p>{t.message}</p>
          </div>
        ))}
      </div>

      <h3>Running cost, last {cost.window_days} days</h3>
      <table className="simple">
        <tbody>
          <tr><td>Distance driven</td><td className="r">{cost.km_driven.toLocaleString("en-IN")} km</td></tr>
          <tr><td>Charging spend</td><td className="r">{inr(cost.charging_spend_inr)}</td></tr>
          {Object.entries(cost.by_charger_type).map(([k, v]) => (
            <tr key={k}>
              <td className="muted">{{ home_ac: "Home AC", dc_fast: "DC fast", public_ac: "Public AC" }[k]}: {v.kwh} kWh</td>
              <td className="r">₹{v.inr_per_kwh}/kWh</td>
            </tr>
          ))}
          <tr><td>Petrol car, same distance</td><td className="r">₹{cost.petrol_equivalent_per_km_inr}/km</td></tr>
          <tr><td><b>Saving vs petrol, per month</b></td><td className="r"><b>{inr(cost.monthly_saving_vs_petrol_inr)}</b></td></tr>
        </tbody>
      </table>

      <h3>Resale value and battery health</h3>
      <p className="muted" style={{ fontSize: 13.5, margin: "0 0 8px" }}>
        {resale.age_years} years, {resale.odometer_km.toLocaleString("en-IN")} km. Battery wear is
        costing about {inr(-resale.battery_health_impact_inr)} versus a pack at 100%.
      </p>
      <div className="projections">
        <div className="proj faint" style={{ fontSize: 12.5 }}>
          <span>In {resale.projection_years} years, if you keep…</span><span>SOH</span><span>Value</span>
        </div>
        {resale.projections.map((p) => (
          <div className="proj" key={p.label}>
            <span>{p.label} <span className="faint">({pct(p.fast_charge_share)} fast)</span></span>
            <span className="num">{(p.soh * 100).toFixed(1)}%</span>
            <span className="num"><b>{lakh(p.value_inr)}</b></span>
          </div>
        ))}
      </div>
      <p className="faint" style={{ fontSize: 12, marginBottom: 0 }}>{resale.disclaimer}</p>
    </section>
  );
}
