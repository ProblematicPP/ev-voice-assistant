import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

// OSM names are user-contributed data: never inject them as raw HTML
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

/** Real OpenStreetMap map: chargers, active route with charging stops, and the car. */
export default function MapView({ state, network }) {
  const el = useRef(null);
  const map = useRef(null);
  const layers = useRef({});
  const route = state.route;
  const v = state.vehicle;

  useEffect(() => {
    const m = L.map(el.current, { zoomControl: true, attributionControl: true }).setView([v.lat, v.lon], 11);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(m);
    layers.current = {
      chargers: L.layerGroup().addTo(m),
      route: L.layerGroup().addTo(m),
      car: L.layerGroup().addTo(m),
    };
    map.current = m;
    const ro = new ResizeObserver(() => m.invalidateSize());   // tab switches change the size
    ro.observe(el.current);
    return () => { ro.disconnect(); m.remove(); };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // All public chargers from OSM
  useEffect(() => {
    if (!network) return;
    const g = layers.current.chargers;
    g.clearLayers();
    const amber = css("--charge");
    network.chargers.forEach((c) => {
      const est = c.synthetic_fields?.length ? " (estimated)" : "";
      L.circleMarker([c.lat, c.lon], { radius: 4, color: amber, weight: 2, fillColor: css("--panel"), fillOpacity: 1 })
        .bindTooltip(`<b>${esc(c.name)}</b><br>${esc(c.power_kw)} kW, ₹${esc(c.price_per_kwh)}/kWh${est}`)
        .addTo(g);
    });
  }, [network]);

  // Active route
  const routeKey = route ? `${route.destinations.join(",")}|${route.stops.map((s) => s.charger_id).join(",")}|${route.polyline.length}` : "none";
  useEffect(() => {
    const g = layers.current.route;
    g.clearLayers();
    if (!route || route.polyline.length < 2) return;
    const line = L.polyline(route.polyline, { color: css("--accent"), weight: 5, opacity: 0.9 }).addTo(g);
    route.stops.forEach((s) => {
      if (s.lat == null) return;
      L.circleMarker([s.lat, s.lon], { radius: 9, color: css("--panel"), weight: 3, fillColor: css("--charge"), fillOpacity: 1 })
        .bindTooltip(`<b>Charge: ${esc(s.name)}</b><br>${Math.round(s.arrive_soc * 100)}% → ${Math.round(s.depart_soc * 100)}%, ${Math.round(s.charge_min)} min`)
        .addTo(g);
    });
    const end = route.polyline[route.polyline.length - 1];
    L.circleMarker(end, { radius: 8, color: css("--panel"), weight: 3, fillColor: css("--ink"), fillOpacity: 1 })
      .bindTooltip(`<b>${esc(route.destination_names.at(-1))}</b>`).addTo(g);
    map.current.fitBounds(line.getBounds(), { padding: [32, 32] });
  }, [routeKey]); // eslint-disable-line react-hooks/exhaustive-deps

  // The car
  useEffect(() => {
    const g = layers.current.car;
    g.clearLayers();
    L.circleMarker([v.lat, v.lon], { radius: 8, color: css("--panel"), weight: 3, fillColor: css("--accent"), fillOpacity: 1 })
      .bindTooltip(`<b>Your car</b><br>${esc(v.location_name)}`).addTo(g);
    if (!route) map.current.setView([v.lat, v.lon], map.current.getZoom());
  }, [v.lat, v.lon]); // eslint-disable-line react-hooks/exhaustive-deps

  return <div ref={el} className="map-view" role="region" aria-label="Map" />;
}
