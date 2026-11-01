import { inr, mins, openOffer, pct } from "../api.js";
import { BoltIcon, HomeIcon, OfficeIcon, PlugIcon, RouteIcon, SnowIcon, ThermoIcon } from "../icons.jsx";

const CLIMATE = { off: "Climate off", fan: "Fan on", ac: "AC on", heat: "Heater on" };

function greeting() {
  const h = new Date().getHours();
  return h < 5 ? "Good night" : h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
}

function status(v) {
  if (v.plugged_in) return `Charging at ${v.location_name}`;
  if (v.driving) return `Driving near ${v.location_name}`;
  return `Parked at ${v.location_name}`;
}

/** Range shown as a national-highway direction sign. */
function RangeSign({ state }) {
  const { range: r, home, vehicle: v } = state;
  const atHome = v.location === v.home_node;
  return (
    <section className="sign" aria-label={`Range ${Math.round(r.personalized_km)} kilometres`}>
      <div className="sign-face">
        <div className="sign-top">
          <span className="sign-range num">{Math.round(r.personalized_km)}<small>km</small></span>
          <span className="sign-caption">range for today’s weather and driving</span>
        </div>
        <div className="sign-bar" aria-hidden="true"><i style={{ width: pct(v.soc) }} /></div>
        <ul className="sign-rows">
          {!atHome && (
            <li><span>Home</span><span className="num">{Math.round(home.distance_km)} km</span>
              <em>{home.arrival_soc > 0 ? `arrive ${pct(home.arrival_soc)}` : "needs a charge"}</em></li>
          )}
          <li><span>City driving</span><span className="num">{Math.round(r.city_km)} km</span></li>
          <li><span>Highway</span><span className="num">{Math.round(r.highway_km)} km</span></li>
        </ul>
      </div>
    </section>
  );
}

function OfferCard({ offer, send }) {
  return (
    <section className="card offer" aria-label="Suggestion from Volt">
      <p>{offer.text}</p>
      <div className="row-actions">
        <button className="btn primary" onClick={() => send("yes")}>{offer.offer}</button>
        <button className="btn ghost" onClick={() => send("no")}>Not now</button>
      </div>
    </section>
  );
}

function TripCard({ state, go }) {
  const route = state.route;
  const proj = state.route_projection;
  const t = route.totals;
  return (
    <button className="card trip-card" onClick={() => go("trip")}>
      <span className="trip-card-head">
        <span>On the way to</span>
        {proj?.at_risk && <span className="pill bad">Re-plan needed</span>}
      </span>
      <strong>{route.destination_names.at(-1)}</strong>
      <span className="trip-card-stats">
        <span><b className="num">{proj?.remaining_km ?? t.distance_km} km</b> left</span>
        <span><b className="num">{mins(t.total_min)}</b> total</span>
        <span><b className="num">{pct(proj?.arrival_soc ?? t.arrival_soc)}</b> on arrival</span>
      </span>
      {route.stops.length > 0 && (
        <span className="trip-card-stop"><BoltIcon size={16} />Charging at {route.stops[0].name}</span>
      )}
    </button>
  );
}

export default function Home({ state, live, companion, go }) {
  const v = state.vehicle;
  const offer = openOffer(live.messages);
  const atHome = v.location === v.home_node;
  const send = (text) => live.send(text);
  const actions = [
    atHome
      ? { label: "Plan a trip", icon: RouteIcon, run: () => go("trip") }
      : { label: "Drive home", icon: HomeIcon, say: "Take me home" },
    { label: "Drive to office", icon: OfficeIcon, say: "Take me to the office" },
    { label: "Nearby chargers", icon: BoltIcon, say: "Show nearby chargers" },
    { label: "Cool the cabin", icon: SnowIcon, say: "Pre-cool the cabin" },
  ];

  return (
    <div className="scroll home">
      <header className="home-head">
        <h1>{greeting()}</h1>
        <p>{status(v)}</p>
      </header>

      <RangeSign state={state} />

      <div className="facts" role="list">
        <span role="listitem">{v.plugged_in ? <PlugIcon size={18} /> : <BoltIcon size={18} />}<b className="num">{pct(v.soc)}</b> charge</span>
        <span role="listitem"><ThermoIcon size={18} /><b className="num">{Math.round(v.ambient_temp_c)} °C</b> outside</span>
        <span role="listitem"><SnowIcon size={18} />{CLIMATE[v.hvac_mode]}</span>
      </div>

      {offer && <OfferCard offer={offer} send={send} />}
      {state.route && <TripCard state={state} go={go} />}

      <section className="block" aria-label="Quick actions">
        <h2 className="section-title">Quick actions</h2>
        <div className="actions">
          {actions.map(({ label, icon: I, say, run }) => (
            <button key={label} className="action" onClick={run ?? (() => send(say))} disabled={!run && !live.connected}>
              <span className="action-icon"><I /></span>{label}
            </button>
          ))}
        </div>
      </section>

      {companion && (
        <button className="card saving" onClick={() => go("ownership")}>
          <span>Saved this month compared with a petrol car</span>
          <strong className="num">{inr(companion.cost.monthly_saving_vs_petrol_inr)}</strong>
          <span className="faint">Running cost ₹{companion.cost.cost_per_km_inr.toFixed(2)} per km</span>
        </button>
      )}
    </div>
  );
}
