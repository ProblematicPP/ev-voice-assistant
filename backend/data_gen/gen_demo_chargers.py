"""Extra *demo* chargers, so the route planner has real choices to make in a demo.

OpenStreetMap only lists ~37 usable public chargers in Karnataka, which leaves most
routes with zero or one candidate. This adds randomly placed (seeded, so reproducible)
chargers at named places on the road graph: denser inside Bengaluru, sparser across
the state. They are flagged `demo: true` everywhere so they are never mistaken for
real OSM data.

Run from backend/:  python -m data_gen.gen_demo_chargers
"""
from __future__ import annotations

import json
import random

from app.config import DATA_DIR
from app.routing.network import hav_km

SEED = 7
N_BENGALURU = 20
N_STATE = 30
MIN_GAP_KM = {"bengaluru": 2.0, "state": 15.0}   # from any other charger
BLR = (12.82, 13.12, 77.45, 77.80)              # lat/lon box
# Intercity destinations always get one: these cities have several real chargers, but OSM lists
# none within reach, which made round trips from Bengaluru impossible to plan.
ANCHORS = ["mysuru", "hassan", "tumakuru", "mandya", "chikkaballapur", "kolar"]


def _in_blr(p):
    return BLR[0] <= p["lat"] <= BLR[1] and BLR[2] <= p["lon"] <= BLR[3]


def main():
    net = json.loads((DATA_DIR / "network.json").read_text(encoding="utf-8"))
    rng = random.Random(SEED)
    taken = [(c["lat"], c["lon"]) for c in net["chargers"] if c["lat"] is not None]
    nlat, nlon = net["nodes"]["lat"], net["nodes"]["lon"]

    city = [p for p in net["places"] if _in_blr(p) and p["kind"] in ("neighbourhood", "suburb", "quarter")]
    towns = [p for p in net["places"] if not _in_blr(p) and p["kind"] in ("town", "city")]
    out = []
    anchors = [next(p for p in net["places"] if p["id"] == a) for a in ANCHORS]
    for pool, n, gap in ((anchors, len(anchors), 5.0), (city, N_BENGALURU, MIN_GAP_KM["bengaluru"]),
                         (towns, N_STATE, MIN_GAP_KM["state"])):
        if pool is not anchors:
            rng.shuffle(pool)
        added = 0
        for p in pool:
            if added == n:
                break
            # Sit the charger on its road node (where routes actually go), not on the place label
            lat, lon = nlat[p["node"]], nlon[p["node"]]
            if hav_km(p["lat"], p["lon"], lat, lon) > (3.0 if pool is anchors else 1.0) or                     any(hav_km(lat, lon, la, lo) < gap for la, lo in taken):
                continue
            kind = rng.choices(["dc_fast", "public_ac"], weights=[4, 1])[0]
            kw = rng.choice([30, 50, 60, 120]) if kind == "dc_fast" else rng.choice([7.4, 22])
            price = rng.choice([17, 18, 19, 20, 21, 22]) if kind == "dc_fast" else rng.choice([11, 12, 13])
            out.append({"id": f"demo_{len(out) + 1:02d}", "node": p["node"], "name": "Demo charger",
                        "power_kw": kw, "price_per_kwh": float(price), "kind": kind, "available": True,
                        "lat": lat, "lon": lon, "operator": None, "demo": True,
                        "synthetic_fields": ["location", "power_kw", "price_per_kwh"]})
            taken.append((lat, lon))
            added += 1

    path = DATA_DIR / "demo_chargers.json"
    path.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"{len(out)} demo chargers -> {path.name}")


if __name__ == "__main__":
    main()
