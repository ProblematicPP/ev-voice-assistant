import { inr, mins, pct } from "../api.js";

const BOUNDS = { latMin: 12.22, latMax: 13.5, lonMin: 76.55, lonMax: 78.22 };
const W = 640;
const H = Math.round(W * (BOUNDS.latMax - BOUNDS.latMin) / (BOUNDS.lonMax - BOUNDS.lonMin) * 1.03);
const LABELED = new Set(["koramangala", "whitefield", "mysuru", "mandya", "maddur", "channapatna", "ramanagara",
  "bidadi", "tumakuru", "kolar", "hosur", "devanahalli", "chikkaballapur", "nelamangala", "srirangapatna"]);

const project = (n) => [
  ((n.lon - BOUNDS.lonMin) / (BOUNDS.lonMax - BOUNDS.lonMin)) * W,
  ((BOUNDS.latMax - n.lat) / (BOUNDS.latMax - BOUNDS.latMin)) * H,
];

function RouteMap({ network, state }) {
  if (!network) return <div className="map" style={{ height: 280 }} />;
  const nodes = Object.fromEntries(network.nodes.map((n) => [n.id, n]));
  const route = state.route;
  const routeNodes = route?.route_nodes ?? [];
  const onRoute = new Set(routeNodes);
  const stopNodes = new Set((route?.stops ?? []).map((s) => s.node));
  const dest = route?.destinations?.at(-1);
  const here = state.vehicle.location;
  const pts = routeNodes.map((id) => project(nodes[id]).join(",")).join(" ");
  const short = (n) => (n.id === "koramangala" ? "Home" : n.id === "whitefield" ? "Office" : n.name.replace(/ \(.+\)/, ""));

  return (
    <svg className="map" viewBox={`0 0 ${W} ${H}`} role="img"
      aria-label={route ? `Route map to ${route.destination_names.at(-1)}` : "Road network map"}>
      {network.edges.map((e, i) => {
        const [x1, y1] = project(nodes[e.from]);
        const [x2, y2] = project(nodes[e.to]);
        return <line key={i} className={`edge ${e.road_type === "highway" ? "hwy" : ""}`} x1={x1} y1={y1} x2={x2} y2={y2} />;
      })}
      {routeNodes.length > 1 && <polyline className="route" points={pts} />}
      {network.chargers.filter((c) => c.kind !== "home_ac").map((c) => {
        const [x, y] = project(nodes[c.node]);
        return (
          <rect key={c.id} className={`charger ${stopNodes.has(c.node) ? "" : "idle"}`} x={x + 5} y={y - 13}
            width="8" height="8" rx="2"><title>{`${c.name}, ${c.power_kw} kW, ₹${c.price_per_kwh}/kWh`}</title></rect>
        );
      })}
      {network.nodes.map((n) => {
        const [x, y] = project(n);
        const cls = n.id === here ? "here" : n.id === dest ? "dest" : "";
        const label = LABELED.has(n.id) || onRoute.has(n.id) && (stopNodes.has(n.id) || n.id === dest) || n.id === here;
        return (
          <g key={n.id}>
            <circle className={`node ${cls}`} cx={x} cy={y} r={cls ? 6.5 : 3.5}><title>{n.name}</title></circle>
            {label && (
              <text x={x + 9} y={y + 4} className={cls || stopNodes.has(n.id) ? "strong" : ""}>{short(n)}</text>
            )}
          </g>
        );
      })}
    </svg>
  );
}

function Itinerary({ state, network }) {
  const route = state.route;
  const name = (id) => network?.nodes.find((n) => n.id === id)?.name.replace(/ \(.+\)/, "") ?? id;
  const done = state.vehicle.progress?.leg ?? 0;
  const items = [{ cls: "start", title: name(route.origin), sub: `Leave with ${pct(route.totals.start_soc)}` }];
  route.legs.forEach((leg, i) => {
    const legNote = `${leg.distance_km} km, ${mins(leg.drive_min)}, uses ${leg.energy_kwh} kWh`;
    if (leg.ends_at_charger) {
      const s = route.stops.find((st) => st.node === leg.to && st.arrive_soc === leg.soc_arrive) ??
        route.stops.find((st) => st.node === leg.to);
      items.push({
        cls: "stop", legNote, done: i < done, title: `Charge at ${s.name}`,
        sub: `${pct(s.arrive_soc)} → ${pct(s.depart_soc)} · ${Math.round(s.charge_min)} min · ${s.power_kw} kW · ${inr(s.cost_inr)}`,
      });
    } else {
      const isEnd = i === route.legs.length - 1;
      items.push({
        cls: isEnd ? "end" : "", legNote, done: i < done,
        title: route.destination_names[leg.waypoint_index] ?? name(leg.to),
        sub: `Arrive with ${pct(leg.soc_arrive)}`,
      });
    }
  });
  return (
    <ol className="itinerary">
      {items.map((it, i) => (
        <li key={i} className={it.cls} style={it.done ? { opacity: 0.5 } : undefined}>
          <span className="pin" />
          {it.legNote && <p className="leg-note" style={{ margin: "0 0 4px" }}>{it.legNote}</p>}
          <div className="title">{it.title}</div>
          <div className="sub">{it.sub}</div>
        </li>
      ))}
    </ol>
  );
}

export default function RoutePlanPanel({ state, network }) {
  const route = state.route;
  const proj = state.route_projection;
  const t = route?.totals;
  return (
    <section className="panel">
      <h2>
        Route and charging plan
        {route && (
          <span className={`status ${route.stops.length ? "warn" : t.arrival_soc < 0.15 ? "warn" : "ok"}`}>
            {route.stops.length ? `${route.stops.length} charging stop${route.stops.length > 1 ? "s" : ""}, auto-selected` : "No charging needed"}
          </span>
        )}
      </h2>
      <div className="route-grid">
        <RouteMap network={network} state={state} />
        <div>
          {route ? (
            <>
              <div className="totals">
                <div><small>Distance</small><strong>{t.distance_km} km</strong></div>
                <div><small>Total time</small><strong>{mins(t.total_min)}</strong></div>
                <div><small>Arrival charge</small><strong>{pct(proj?.arrival_soc ?? t.arrival_soc)}</strong></div>
                <div><small>Charging cost</small><strong>{inr(t.charging_cost_inr)}</strong></div>
              </div>
              <Itinerary state={state} network={network} />
              {proj?.at_risk && (
                <p className="status bad" role="alert">Conditions changed: this plan now dips to {pct(proj.min_soc)}. Ask Volt to re-plan.</p>
              )}
            </>
          ) : (
            <p className="muted">
              No active route. Ask “Take me to Mysuru” and Volt picks the route and any charging stops for you,
              or “Will I make it to Nandi Hills?” to check without starting navigation.
            </p>
          )}
        </div>
      </div>
    </section>
  );
}
