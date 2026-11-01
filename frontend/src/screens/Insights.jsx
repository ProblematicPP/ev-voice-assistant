import { inr, lakh, pct } from "../api.js";

const TYPE_LABEL = { home_ac: "Home", dc_fast: "Fast charger", public_ac: "Public AC" };

export default function Insights({ companion }) {
  if (!companion) {
    return (
      <div className="scroll">
        <header className="app-bar"><div><h1>Ownership</h1></div></header>
        <p className="muted pad">Loading your driving and charging history…</p>
      </div>
    );
  }
  const { coaching, cost, resale, eco } = companion;
  return (
    <div className="scroll">
      <header className="app-bar"><div><h1>Ownership</h1><p>Last {cost.window_days} days</p></div></header>

      <section className="compare">
        <div>
          <small>Your EV</small>
          <strong className="num">₹{cost.cost_per_km_inr.toFixed(2)}</strong>
          <small>per km</small>
        </div>
        <div className="vs">
          <small>Petrol car</small>
          <strong className="num">₹{cost.petrol_equivalent_per_km_inr.toFixed(1)}</strong>
          <small>per km</small>
        </div>
        <p>You save about <b>{inr(cost.monthly_saving_vs_petrol_inr)}</b> a month.</p>
      </section>

      <section className="block">
        <h2 className="section-title">Your driving</h2>
        <div className="drive-stats">
          <div><strong className="num">{eco.history.harsh_brakes_per_100km}</strong><small>harsh brakes per 100 km</small></div>
          <div><strong className="num">{eco.history.harsh_accels_per_100km}</strong><small>hard starts per 100 km</small></div>
          <div><strong className="num">+{Math.round(eco.range_gain_km)} km</strong><small>if you drove smoothly</small></div>
        </div>
        <p className="block-sub">From {Math.round(eco.history.km).toLocaleString("en-IN")} km of driving. A smooth
          driver has about {eco.typical_events_per_100km} harsh events per 100 km.</p>
        <div className="tips">
          {eco.tips.filter((t) => t.id !== "smooth_gain").map((t) => (
            <div key={t.id} className={`tip ${t.severity}`}><b>{t.title}</b><p>{t.message}</p></div>
          ))}
        </div>
      </section>

      <section className="block">
        <h2 className="section-title">Charging tips</h2>
        <div className="tips">
          {coaching.map((t) => (
            <div key={t.id} className={`tip ${t.severity}`}>
              <b>{t.title}</b>
              <p>{t.message}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="block">
        <h2 className="section-title">Where your money went</h2>
        <ul className="list">
          <li><span className="list-main"><b>Distance driven</b></span><span className="list-side"><b className="num">{cost.km_driven.toLocaleString("en-IN")} km</b></span></li>
          {Object.entries(cost.by_charger_type).map(([k, v]) => (
            <li key={k}>
              <span className={`type-dot ${k}`} aria-hidden="true" />
              <span className="list-main"><b>{TYPE_LABEL[k]}</b><small className="num">{v.kwh} kWh</small></span>
              <span className="list-side"><b className="num">₹{v.inr_per_kwh}/kWh</b></span>
            </li>
          ))}
          <li><span className="list-main"><b>Total charging spend</b></span><span className="list-side"><b className="num">{inr(cost.charging_spend_inr)}</b></span></li>
        </ul>
      </section>

      <section className="block">
        <h2 className="section-title">Resale value</h2>
        <div className="resale">
          <strong className="num">{lakh(resale.estimated_value_inr)}</strong>
          <p>Estimated today, at {resale.age_years} years and {resale.odometer_km.toLocaleString("en-IN")} km.
            Battery wear accounts for {inr(-resale.battery_health_impact_inr)} of the drop.</p>
        </div>
        <p className="block-sub">In {resale.projection_years} years, depending on how you charge:</p>
        <ul className="list">
          {resale.projections.map((p) => (
            <li key={p.label}>
              <span className="list-main"><b>{p.label}</b><small>{pct(p.fast_charge_share)} fast charging, {(p.soh * 100).toFixed(1)}% health</small></span>
              <span className="list-side"><b className="num">{lakh(p.value_inr)}</b></span>
            </li>
          ))}
        </ul>
        <p className="fine">{resale.disclaimer}</p>
      </section>
    </div>
  );
}
