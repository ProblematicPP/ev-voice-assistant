import { inr, mins, pct } from "../api.js";
import MapView from "./MapView.jsx";

function Itinerary({ route, progressLeg }) {
  const items = [{ cls: "start", title: route.origin_name, sub: `Leave with ${pct(route.totals.start_soc)}` }];
  route.legs.forEach((leg, i) => {
    const legNote = `${leg.distance_km} km, ${mins(leg.drive_min)}, ${leg.energy_kwh} kWh`;
    if (leg.ends_at_charger) {
      const s = route.stops.find((st) => st.node === leg.to && st.arrive_soc === leg.soc_arrive) ??
        route.stops.find((st) => st.node === leg.to);
      const est = s.synthetic_fields?.length ? " (power/price estimated)" : "";
      items.push({
        cls: "stop", legNote, done: i < progressLeg, title: `Charge at ${s.name}`,
        sub: `${pct(s.arrive_soc)} → ${pct(s.depart_soc)}, ${Math.round(s.charge_min)} min at ${s.power_kw} kW, ${inr(s.cost_inr)}${est}`,
      });
    } else {
      items.push({
        cls: i === route.legs.length - 1 ? "end" : "", legNote, done: i < progressLeg,
        title: route.destination_names[leg.waypoint_index] ?? leg.to_name,
        sub: `Arrive with ${pct(leg.soc_arrive)}`,
      });
    }
  });
  return (
    <ol className="itinerary">
      {items.map((it, i) => (
        <li key={i} className={it.cls} style={it.done ? { opacity: 0.5 } : undefined}>
          <span className="pin" />
          {it.legNote && <p className="leg-note">{it.legNote}</p>}
          <div className="title">{it.title}</div>
          <div className="sub">{it.sub}</div>
        </li>
      ))}
    </ol>
  );
}

export default function TripTab({ state, network }) {
  const route = state.route;
  const proj = state.route_projection;
  const t = route?.totals;
  return (
    <div className="tab-body">
      <MapView state={state} network={network} />
      <div className="trip-detail">
        {route ? (
          <>
            <div className="trip-head">
              <h3>To {route.destination_names.at(-1)}</h3>
              <span className={`status ${route.stops.length || t.arrival_soc < 0.15 ? "warn" : "ok"}`}>
                {route.stops.length
                  ? `${route.stops.length} charging stop${route.stops.length > 1 ? "s" : ""}, picked automatically`
                  : "No charging needed"}
              </span>
            </div>
            <div className="totals">
              <div><small>Distance</small><strong>{t.distance_km} km</strong></div>
              <div><small>Total time</small><strong>{mins(t.total_min)}</strong></div>
              <div><small>Arrival charge</small><strong>{pct(proj?.arrival_soc ?? t.arrival_soc)}</strong></div>
              <div><small>Charging cost</small><strong>{inr(t.charging_cost_inr)}</strong></div>
            </div>
            {proj?.at_risk && (
              <p className="status bad" role="alert">
                Conditions changed: this plan now dips to {pct(Math.max(proj.min_soc, 0))}. Ask Volt to re-plan.
              </p>
            )}
            <Itinerary route={route} progressLeg={state.vehicle.progress?.leg ?? 0} />
          </>
        ) : (
          <div className="empty-trip">
            <h3>No active route</h3>
            <p className="muted">
              Ask Volt “Take me to Mysuru” and it picks the roads and any charging stops for you, or ask
              “Will I make it to Nandi Hills?” to check without starting navigation.
            </p>
          </div>
        )}
        <p className="faint map-credit">
          Roads, places and charger locations from OpenStreetMap ({network?.chargers.length ?? "…"} car chargers in
          Karnataka). Charger power and prices are estimated where OpenStreetMap has no data.
        </p>
      </div>
    </div>
  );
}
