import { useState } from "react";
import { inr, mins, pct } from "../api.js";
import { BoltIcon, CloseIcon, HomeIcon, OfficeIcon, PinIcon } from "../icons.jsx";
import MapView from "../components/MapView.jsx";
import RangeRibbon from "../components/RangeRibbon.jsx";

function Itinerary({ route, progressLeg }) {
  const items = [{ cls: "start", title: route.origin_name, sub: `Leave with ${pct(route.totals.start_soc)}` }];
  route.legs.forEach((leg, i) => {
    const legNote = `${leg.distance_km} km, ${mins(leg.drive_min)}`;
    if (leg.ends_at_charger) {
      const s = route.stops.find((st) => st.node === leg.to && st.arrive_soc === leg.soc_arrive) ??
        route.stops.find((st) => st.node === leg.to);
      items.push({
        cls: "stop", legNote, done: i < progressLeg, title: s.name,
        sub: `Charge ${pct(s.arrive_soc)} to ${pct(s.depart_soc)}, about ${Math.round(s.charge_min)} min, ${inr(s.cost_inr)}`
          + (s.wait_min >= 1 ? `. Expect a ${Math.round(s.wait_min)} min wait.` : ""),
      });
    } else {
      items.push({
        cls: i === route.legs.length - 1 ? "end" : "via", legNote, done: i < progressLeg,
        title: route.destination_names[leg.waypoint_index] ?? leg.to_name,
        sub: `Arrive with ${pct(leg.soc_arrive)}`,
      });
    }
  });
  return (
    <ol className="itinerary">
      {items.map((it, i) => (
        <li key={i} className={`${it.cls} ${it.done ? "done" : ""}`}>
          <span className="pin" />
          {it.legNote && <p className="leg-note">{it.legNote}</p>}
          <div className="title">{it.title}</div>
          <div className="sub">{it.sub}</div>
        </li>
      ))}
    </ol>
  );
}

function WhereTo({ state, live, atHome }) {
  const [place, setPlace] = useState("");
  const go = (text) => live.send(text);
  const submit = (e) => {
    e.preventDefault();
    if (place.trim() && go(`Take me to ${place.trim()}`)) setPlace("");
  };
  return (
    <>
      <form className="where-to" onSubmit={submit}>
        <PinIcon size={20} />
        <input value={place} onChange={(e) => setPlace(e.target.value)} placeholder="Where to?"
          aria-label="Destination" enterKeyHint="go" />
      </form>
      <div className="place-chips">
        {!atHome && <button className="chip-btn" onClick={() => go("Take me home")}><HomeIcon size={18} />Home</button>}
        <button className="chip-btn" onClick={() => go("Take me to the office")}><OfficeIcon size={18} />Office</button>
        <button className="chip-btn" onClick={() => go("Take me to the nearest charger")}><BoltIcon size={18} />Nearest charger</button>
      </div>
      <RangeRibbon range={state.range} />
      <p className="sheet-hint">Volt checks your charge before every trip and adds a charging stop only when you need one.</p>
    </>
  );
}

function ActiveRoute({ state, live }) {
  const route = state.route;
  const proj = state.route_projection;
  const t = route.totals;
  return (
    <>
      <div className="route-head">
        <div>
          <span className="faint">To</span>
          <h2>{route.destination_names.at(-1)}</h2>
        </div>
        <button className="icon-btn" onClick={() => live.send("Cancel navigation")} aria-label="End route">
          <CloseIcon />
        </button>
      </div>
      <div className="totals">
        <div><strong className="num">{mins(t.total_min)}</strong>
          <small>{t.traffic_delay_min >= 1 ? `incl. ${Math.round(t.traffic_delay_min)} min traffic` : "total"}</small></div>
        <div><strong className="num">{t.distance_km} km</strong><small>distance</small></div>
        <div><strong className="num">{pct(proj?.arrival_soc ?? t.arrival_soc)}</strong><small>on arrival</small></div>
        {t.charging_cost_inr > 0 && <div><strong className="num">{inr(t.charging_cost_inr)}</strong><small>charging</small></div>}
      </div>
      {proj?.at_risk && (
        <div className="banner bad" role="alert">
          <p>Conditions have changed and this route now drops to {pct(Math.max(proj.min_soc, 0))}.</p>
          <button className="btn primary small" onClick={() => live.send("Re-plan my route with a charging stop")}>
            Add a charging stop
          </button>
        </div>
      )}
      <RangeRibbon range={state.range} route={route} />
      <Itinerary route={route} progressLeg={state.vehicle.progress?.leg ?? 0} />
    </>
  );
}

export default function Navigate({ state, live, network }) {
  const v = state.vehicle;
  return (
    <div className="navigate">
      <MapView state={state} network={network} />
      <section className="sheet" aria-label={state.route ? "Route" : "Plan a trip"}>
        <span className="sheet-handle" aria-hidden="true" />
        {state.route ? <ActiveRoute state={state} live={live} /> : <WhereTo state={state} live={live} atHome={v.location === v.home_node} />}
      </section>
    </div>
  );
}
