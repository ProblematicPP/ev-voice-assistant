import { useEffect, useRef, useState } from "react";

/** One km scale: personalised range (solid), brochure estimate (hatched) and the active route's stops. */
export default function RangeRibbon({ range, route }) {
  const ref = useRef(null);
  const [W, setW] = useState(320);
  useEffect(() => {
    const ro = new ResizeObserver(([e]) => setW(Math.max(240, e.contentRect.width)));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  const mine = range.personalized_km, brochure = range.naive_km;
  const routeKm = route?.totals.distance_km ?? 0;
  const maxKm = Math.max(brochure, mine, routeKm, 50) * 1.06;
  const x = (km) => (Math.min(km, maxKm) / maxKm) * W;
  const step = maxKm > 400 ? 200 : maxKm > 160 ? 100 : 50;
  const ticks = [];
  for (let k = 0; k <= maxKm; k += step) ticks.push(k);

  const marks = [];
  if (route?.legs?.length) {
    let km = 0;
    route.legs.forEach((leg) => {
      km += leg.distance_km;
      if (leg.ends_at_charger) marks.push({ km, kind: "stop" });
    });
    marks.push({ km, kind: "dest" });
  }

  return (
    <figure className="ribbon">
      <figcaption>
        <span><b className="num">{Math.round(mine)} km</b> for how you drive today</span>
        <span className="faint"><b className="num">{Math.round(brochure)} km</b> brochure estimate</span>
      </figcaption>
      <svg ref={ref} viewBox={`0 0 ${W} 54`} role="img" className="ribbon-svg"
        aria-label={`Personalised range ${Math.round(mine)} km against a brochure estimate of ${Math.round(brochure)} km${route ? `; route ${routeKm} km` : ""}`}>
        <defs>
          <pattern id="hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <line x1="0" y1="0" x2="0" y2="6" stroke="var(--ink-3)" strokeWidth="1.2" />
          </pattern>
        </defs>
        <rect x="0" y="12" width={W} height="18" rx="4" fill="var(--panel-2)" />
        <rect x="0" y="12" width={x(brochure)} height="18" rx="4" fill="url(#hatch)" opacity="0.6" />
        <rect x="0" y="12" width={x(mine)} height="18" rx="4" fill="var(--brand)" />
        {marks.map((m, i) => (
          <line key={i} x1={x(m.km)} x2={x(m.km)} y1="6" y2="36" strokeWidth="3" strokeLinecap="round"
            stroke={m.kind === "stop" ? "var(--charge)" : "var(--ink)"} />
        ))}
        {ticks.map((k) => (
          <text key={k} x={x(k)} y="50" fontSize="11" fill="var(--ink-3)" textAnchor={k === 0 ? "start" : "middle"}
            style={{ fontFamily: "var(--font-num)" }}>{k}</text>
        ))}
      </svg>
      <div className="ribbon-legend">
        <span><i className="swatch" style={{ background: "var(--brand)" }} />Your range</span>
        <span><i className="swatch hatch" />Brochure</span>
        {route && <span><i className="swatch" style={{ background: "var(--ink)" }} />Destination</span>}
        {route?.stops.length > 0 && <span><i className="swatch" style={{ background: "var(--charge)" }} />Charging stop</span>}
      </div>
    </figure>
  );
}
