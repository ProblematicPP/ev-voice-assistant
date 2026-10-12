"""Build the offline routing graph from raw OSM data (run osm_fetch first).

  * Ways are split at intersections into edges with real length and geometry.
  * Speeds come from OSM maxspeed or road class, reduced for city traffic.
  * Only the largest connected component is kept.
  * Places, chargers and POIs are snapped to the nearest road node.
  * Charger power/price missing in OSM are filled with clearly-flagged synthetic values.

Output: data/network.json            Data (c) OpenStreetMap contributors, ODbL.
Run from backend/:  python -m data_gen.build_osm_network
"""
import hashlib
import json
import math
import re
from collections import Counter

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

from app.config import DATA_DIR

RAW = DATA_DIR / "osm_raw"
PBF = RAW / "karnataka-latest.osm.pbf"
ROAD_RE = re.compile(r"^(motorway|trunk|primary|secondary)(_link)?$")
BLR_CENTER = (12.9716, 77.5946)
BLR_URBAN_KM = 18

DEFAULT_SPEED = {"motorway": 100, "trunk": 80, "primary": 60, "secondary": 50}

# Places the demo/tests rely on; used if OSM lacks them (approximate coordinates)
REQUIRED_PLACES = {
    "koramangala": ("Koramangala", 12.935, 77.624), "whitefield": ("Whitefield", 12.970, 77.750),
    "indiranagar": ("Indiranagar", 12.971, 77.641), "electronic_city": ("Electronic City", 12.845, 77.660),
    "jayanagar": ("Jayanagar", 12.925, 77.583), "hebbal": ("Hebbal", 13.035, 77.597),
    "yeshwanthpur": ("Yeshwanthpur", 13.028, 77.540), "kengeri": ("Kengeri", 12.912, 77.485),
    "bidadi": ("Bidadi", 12.797, 77.388), "ramanagara": ("Ramanagara", 12.722, 77.281),
    "channapatna": ("Channapatna", 12.652, 77.209), "maddur": ("Maddur", 12.584, 77.044),
    "mandya": ("Mandya", 12.524, 76.897), "srirangapatna": ("Srirangapatna", 12.414, 76.704),
    "mysuru": ("Mysuru", 12.296, 76.639), "tumakuru": ("Tumakuru", 13.340, 77.101),
    "kolar": ("Kolar", 13.137, 78.129), "hoskote": ("Hoskote", 13.070, 77.798),
    "nelamangala": ("Nelamangala", 13.097, 77.393), "devanahalli": ("Devanahalli", 13.247, 77.712),
    "kempegowda_airport": ("Kempegowda Airport", 13.199, 77.707),
    "chikkaballapur": ("Chikkaballapur", 13.435, 77.728), "nandi_hills": ("Nandi Hills", 13.370, 77.683),
    "hubballi": ("Hubballi", 15.364, 75.124),
}
ALIASES = {
    "koramangala": ["home", "house"], "whitefield": ["office", "work"],
    "kempegowda_airport": ["airport", "kia", "bengaluru airport", "bangalore airport", "blr airport"],
    "mysuru": ["mysore"], "bengaluru": ["bangalore", "blr"], "tumakuru": ["tumkur"],
    "mangaluru": ["mangalore"], "belagavi": ["belgaum"], "hubballi": ["hubli"],
    "kalaburagi": ["gulbarga"], "vijayapura": ["bijapur"], "shivamogga": ["shimoga"],
    "electronic_city": ["ecity", "e city"], "ramanagara": ["ramanagaram"],
}
# Scooter/e-bike charging and battery-swap networks - not usable by a car
TWO_WHEELER = ("ather", "ola hyper", "ola electric", "hero vida", "vida", "e:swap", "eswap", "swap",
               "yulu", "sun mobility", "bounce", "battery smart", "okinawa", "revolt", "simple energy")

POI_ALIASES = {
    "mcdonalds": ["mcd", "mcdonald", "mcdonalds", "mc donalds", "mac d", "macd"],
    "cafe": ["cafe", "coffee", "starbucks", "ccd"],
    "mall": ["mall", "shopping"],
}


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def hav_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    h = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * np.arcsin(np.sqrt(h))


def extract(path=PBF) -> dict:
    """One pass over the PBF: major roads (with coordinates), chargers, POIs, places."""
    import osmium

    out = {"roads": [], "chargers": [], "pois": [], "places": []}

    def classify(tags) -> str | None:
        if tags.get("amenity") == "charging_station":
            return "chargers"
        brand = (tags.get("brand", "") + " " + tags.get("name", "")).lower()
        if "mcdonald" in brand or "starbucks" in brand or "coffee day" in brand or tags.get("shop") == "mall":
            return "pois"
        if tags.get("aeroway") == "aerodrome" and tags.get("iata"):
            return "places"
        return None

    class Handler(osmium.SimpleHandler):
        def node(self, n):
            tags = dict(n.tags)
            if not tags:
                return
            kind = classify(tags)
            place = tags.get("place")
            if kind is None and place in ("city", "town", "suburb", "neighbourhood", "quarter"):
                if place in ("city", "town") or (12.75 <= n.location.lat <= 13.30 and 77.35 <= n.location.lon <= 77.85):
                    kind = "places"
            if kind:
                out[kind].append({"type": "node", "id": n.id, "lat": n.location.lat, "lon": n.location.lon,
                                  "tags": tags})

        def way(self, w):
            tags = dict(w.tags)
            hw = tags.get("highway", "")
            if ROAD_RE.match(hw):
                pts = [(nd.ref, nd.location.lat, nd.location.lon) for nd in w.nodes if nd.location.valid()]
                if len(pts) >= 2:
                    out["roads"].append({"id": w.id, "tags": tags, "pts": pts})
                return
            kind = classify(tags)
            if kind:
                locs = [(nd.location.lat, nd.location.lon) for nd in w.nodes if nd.location.valid()]
                if locs:
                    out[kind].append({"type": "way", "id": w.id, "lat": sum(l[0] for l in locs) / len(locs),
                                      "lon": sum(l[1] for l in locs) / len(locs), "tags": tags})

    Handler().apply_file(str(path), locations=True)
    return out


_EXTRACT: dict | None = None
CACHE = RAW / "extract_cache.pkl"


def load(name):
    """Parsed extract, cached next to the PBF (parsing the PBF takes a few minutes)."""
    global _EXTRACT
    if _EXTRACT is None:
        import pickle
        if CACHE.exists() and CACHE.stat().st_mtime > PBF.stat().st_mtime:
            _EXTRACT = pickle.loads(CACHE.read_bytes())
        else:
            _EXTRACT = extract()
            CACHE.write_bytes(pickle.dumps(_EXTRACT))
    return _EXTRACT[name]


def parse_speed(tag: str | None) -> float | None:
    if not tag:
        return None
    m = re.match(r"(\d+)", tag)
    return float(m.group(1)) if m else None


def build_graph():
    ways = load("roads")
    coords = {}
    for w in ways:
        for ref, la, lo in w["pts"]:
            coords[ref] = (la, lo)
        w["nodes"] = [p[0] for p in w["pts"]]
    use = Counter()
    for w in ways:
        use.update(w["nodes"])
        use[w["nodes"][0]] += 1
        use[w["nodes"][-1]] += 1

    edges = {}            # (a, b) -> edge dict, keep fastest
    for w in ways:
        cls = w["tags"]["highway"].replace("_link", "")
        is_link = w["tags"]["highway"].endswith("_link")
        limit = parse_speed(w["tags"].get("maxspeed")) or DEFAULT_SPEED[cls] * (0.6 if is_link else 1)
        name = w["tags"].get("ref") or w["tags"].get("name") or ""
        seg = [w["nodes"][0]]
        for nid in w["nodes"][1:]:
            seg.append(nid)
            if use[nid] > 1 or nid == w["nodes"][-1]:
                pts = [coords[n] for n in seg if n in coords]
                if len(pts) >= 2:
                    lat = np.array([p[0] for p in pts]); lon = np.array([p[1] for p in pts])
                    km = float(hav_km(lat[:-1], lon[:-1], lat[1:], lon[1:]).sum())
                    if km > 0.005:
                        mid_lat, mid_lon = float(lat.mean()), float(lon.mean())
                        urban = float(hav_km(mid_lat, mid_lon, *BLR_CENTER)) < BLR_URBAN_KM
                        speed = min(limit, 90.0) * (0.45 if urban else 0.85)
                        a, b = seg[0], seg[-1]
                        key = (min(a, b), max(a, b))
                        t = km / speed
                        if key not in edges or t < edges[key]["km"] / edges[key]["speed"]:
                            geom = pts if a == key[0] else pts[::-1]
                            edges[key] = {"a": key[0], "b": key[1], "km": km, "speed": round(speed, 1),
                                          "name": name, "geom": thin(geom)}
                seg = [nid]

    # Index nodes, keep the largest connected component
    node_ids = sorted({n for k in edges for n in k})
    idx = {n: i for i, n in enumerate(node_ids)}
    ea = np.array([idx[e["a"]] for e in edges.values()]); eb = np.array([idx[e["b"]] for e in edges.values()])
    g = coo_matrix((np.ones(len(ea)), (ea, eb)), shape=(len(node_ids), len(node_ids)))
    _, labels = connected_components(g, directed=False)
    main = np.bincount(labels).argmax()
    keep_nodes = [n for n in node_ids if labels[idx[n]] == main]
    new = {n: i for i, n in enumerate(keep_nodes)}
    out_edges = []
    for e in edges.values():
        if e["a"] in new and e["b"] in new:
            road = "city" if e["speed"] < 45 else "highway"
            out_edges.append([new[e["a"]], new[e["b"]], round(e["km"], 3), e["speed"], road, e["name"],
                              [[round(p[0], 5), round(p[1], 5)] for p in e["geom"]]])
    lat = [round(coords[n][0], 6) for n in keep_nodes]
    lon = [round(coords[n][1], 6) for n in keep_nodes]
    return lat, lon, out_edges


def thin(pts, min_km=0.15):
    """Drop geometry points closer than min_km to the previous kept point (keeps ends)."""
    kept = [pts[0]]
    for p in pts[1:-1]:
        if float(hav_km(kept[-1][0], kept[-1][1], p[0], p[1])) >= min_km:
            kept.append(p)
    kept.append(pts[-1])
    return kept


class Snapper:
    def __init__(self, lat, lon):
        self.lat, self.lon = np.array(lat), np.array(lon)
        self.k = math.cos(math.radians(14.5))
        self.tree = cKDTree(np.c_[self.lat, self.lon * self.k])

    def __call__(self, la, lo):
        _, i = self.tree.query([la, lo * self.k])
        return int(i), float(hav_km(la, lo, self.lat[i], self.lon[i]))


def center(e):
    return (e["lat"], e["lon"]) if "lat" in e else (e["center"]["lat"], e["center"]["lon"])


def build_places(snap):
    places = {}
    for e in load("places"):
        t = e.get("tags", {})
        name = t.get("name:en") or t.get("name")
        if not name:
            continue
        la, lo = center(e)
        if t.get("aeroway") == "aerodrome":
            if t.get("iata") != "BLR":
                continue
            sid, name = "kempegowda_airport", "Kempegowda Airport"
        else:
            sid = slug(name)
        kind = t.get("place") or "airport"
        if sid in places and places[sid]["kind"] in ("city", "town"):
            continue
        places[sid] = {"id": sid, "name": name, "lat": la, "lon": lo, "kind": kind}
    for sid, (name, la, lo) in REQUIRED_PLACES.items():
        if sid not in places:
            places[sid] = {"id": sid, "name": name, "lat": la, "lon": lo, "kind": "manual"}
    out = []
    for p in places.values():
        node, dist = snap(p["lat"], p["lon"])
        if dist > 8:
            continue
        p["node"] = node
        p["aliases"] = ALIASES.get(p["id"], [])
        if p["id"] == "koramangala":
            p["name"] = "Koramangala (Home)"
        if p["id"] == "whitefield":
            p["name"] = "Whitefield (Office)"
        out.append(p)
    return sorted(out, key=lambda p: p["id"])


def _h(s: str) -> int:
    return int(hashlib.md5(s.encode()).hexdigest(), 16)


def parse_kw(tags: dict) -> float | None:
    vals = []
    for k, v in tags.items():
        if k.endswith(":output") or k == "charging_station:output":
            for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(kw|w)?", v.lower()):
                x = float(m.group(1))
                vals.append(x / 1000 if m.group(2) == "w" or x > 1000 else x)
    return max(vals) if vals else None


def build_chargers(snap, home_node):
    out, skipped = [], Counter()
    for e in load("chargers"):
        t = e.get("tags", {})
        label = " ".join([t.get("name", ""), t.get("operator", ""), t.get("brand", "")]).lower()
        if (any(k in label for k in TWO_WHEELER) or t.get("motorcar") == "no"
                or t.get("access") in ("private", "no")):
            skipped["two-wheeler/private"] += 1
            continue
        la, lo = center(e)
        node, dist = snap(la, lo)
        if dist > 2.0:
            skipped["far from major road"] += 1
            continue
        synthetic = []
        kw = parse_kw(t)
        h = _h(f"{e['type']}{e['id']}")
        if kw is None:
            kw = [60, 50, 30, 7.4, 22][h % 5]
            synthetic.append("power_kw")
        kind = "dc_fast" if kw >= 20 else "public_ac"
        price = None
        m = re.search(r"(\d+(?:\.\d+)?)", t.get("charge", ""))
        if m and "kwh" in t.get("charge", "").lower():
            price = float(m.group(1))
        if price is None:
            price = (18 + (h >> 4) % 7) if kind == "dc_fast" else (11 + (h >> 4) % 4)
            synthetic.append("price_per_kwh")
        name = t.get("name") or t.get("operator") or t.get("brand") or "EV charging station"
        out.append({"id": f"osm_{e['type'][0]}{e['id']}", "node": node, "name": name, "power_kw": kw,
                    "price_per_kwh": float(price), "kind": kind, "available": True,
                    "lat": la, "lon": lo, "operator": t.get("operator"), "synthetic_fields": synthetic})
    # The owner's private home wallbox is not in OSM
    out.append({"id": "home", "node": home_node, "name": "Home wallbox", "power_kw": 7.4, "price_per_kwh": 7.5,
                "kind": "home_ac", "available": True, "lat": None, "lon": None, "operator": None,
                "synthetic_fields": ["location", "power_kw", "price_per_kwh"]})
    return out, skipped


def build_pois(snap):
    out, seen = [], set()
    for e in load("pois"):
        t = e.get("tags", {})
        label = (t.get("brand", "") + " " + t.get("name", "")).lower()
        cat = ("mcdonalds" if "mcdonald" in label else "cafe" if ("starbucks" in label or "coffee day" in label)
               else "mall" if t.get("shop") == "mall" else None)
        if not cat or (e["type"], e["id"]) in seen:
            continue
        seen.add((e["type"], e["id"]))
        la, lo = center(e)
        node, dist = snap(la, lo)
        if dist > 3.0:
            continue
        name = t.get("name") or t.get("brand") or cat
        out.append({"name": name, "category": cat, "node": node, "lat": la, "lon": lo})
    return out


def main():
    lat, lon, edges = build_graph()
    snap = Snapper(lat, lon)
    places = build_places(snap)
    home = next(p["node"] for p in places if p["id"] == "koramangala")
    chargers, skipped = build_chargers(snap, home)
    pois = build_pois(snap)
    net = {
        "version": 2,
        "source": "OpenStreetMap contributors (ODbL), Karnataka, via Overpass API",
        "nodes": {"lat": lat, "lon": lon},
        "edges": edges,
        "places": places,
        "chargers": chargers,
        "pois": pois,
        "poi_aliases": POI_ALIASES,
    }
    path = DATA_DIR / "network.json"
    path.write_text(json.dumps(net, separators=(",", ":")), encoding="utf-8")
    total_km = sum(e[2] for e in edges)
    print(f"network.json: {len(lat)} nodes, {len(edges)} edges, {total_km:,.0f} km of road, "
          f"{len(places)} places, {len(chargers) - 1} public chargers "
          f"(skipped {dict(skipped)}), {len(pois)} POIs, {path.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
