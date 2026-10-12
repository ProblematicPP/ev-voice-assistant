"""Offline road network built from OpenStreetMap (Karnataka).

Graph nodes are road intersections (integer ids). Named destinations
("places": towns, Bengaluru suburbs, the airport) are snapped to a node.
Shortest paths use scipy's C Dijkstra with cached single-source trees.
"""
from __future__ import annotations

import difflib
import json
import math
import re
from collections import OrderedDict

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree

from app.config import DATA_DIR


def _norm(text: str) -> str:
    text = text.lower().replace("'", "").replace("’", "")
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


FILLER = re.compile(
    r"\b(the|a|an|nearest|closest|nearby|near me|nearer|some|any|please|me|to|my|go|take|"
    r"drive|navigate|place|one|location|outlet|without stopping|stopping|stop|in|at)\b"
)


def hav_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    h = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * np.arcsin(np.sqrt(h))


class RoadNetwork:
    def __init__(self, path=DATA_DIR / "network.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("version") != 2:
            raise RuntimeError("network.json is the old synthetic format - run data_gen.build_osm_network")
        self.lat = np.array(data["nodes"]["lat"])
        self.lon = np.array(data["nodes"]["lon"])
        self.n = len(self.lat)
        E = data["edges"]
        self.eu = np.array([e[0] for e in E]); self.ev = np.array([e[1] for e in E])
        self.ekm = np.array([e[2] for e in E], dtype=float)
        self.espeed = np.array([e[3] for e in E], dtype=float)
        self.eroad = [e[4] for e in E]
        self.ename = [e[5] for e in E]
        self.egeom = [e[6] for e in E]
        self.emin = self.ekm / self.espeed * 60
        self.eid = {}
        for i, (u, v) in enumerate(zip(self.eu.tolist(), self.ev.tolist())):
            self.eid[(u, v)] = i
            self.eid[(v, u)] = i
        rows = np.r_[self.eu, self.ev]; cols = np.r_[self.ev, self.eu]
        self.time_graph = csr_matrix((np.r_[self.emin, self.emin], (rows, cols)), shape=(self.n, self.n))

        self.places = {p["id"]: p for p in data["places"]}
        self.place_at = {}
        for p in data["places"]:
            self.place_at.setdefault(p["node"], p)
        self.chargers = {c["id"]: c for c in data["chargers"]}
        self.pois = data["pois"]
        self._k = math.cos(math.radians(14.5))
        self._place_list = list(self.places.values())
        self._place_tree = cKDTree([[p["lat"], p["lon"] * self._k] for p in self._place_list])
        # OSM names are often just the brand ("McDonald's", "EV charging station"): add the area
        for item in [*self.pois, *self.chargers.values()]:
            if item.get("lat") is not None and len(item["name"].split()) <= 3:
                area = self._area(item["lat"], item["lon"])
                if area and area.lower() not in item["name"].lower():
                    item["name"] = f"{item['name']}, {area}"
        self.poi_aliases = data["poi_aliases"]
        self.source = data.get("source", "OpenStreetMap")

        self._trees: OrderedDict = OrderedDict()
        self._poi_kw: dict = {}
        self._pw: set | None = None

    # -- helpers --------------------------------------------------------------------
    @property
    def nodes(self):
        """Named places keyed by node id (validation / UI selectors)."""
        return {p["node"]: p for p in self.places.values()}

    def place_node(self, place_id: str) -> int:
        return self.places[place_id]["node"]

    def coords(self, node: int) -> tuple[float, float]:
        return float(self.lat[node]), float(self.lon[node])

    # -- graph search ---------------------------------------------------------------
    def tree(self, src: int):
        """Single-source fastest-path tree: (minutes array, predecessor array). LRU-cached."""
        src = int(src)
        if src in self._trees:
            self._trees.move_to_end(src)
            return self._trees[src]
        dist, pred = dijkstra(self.time_graph, directed=False, indices=src, return_predecessors=True)
        self._trees[src] = (dist, pred)
        if len(self._trees) > 256:
            self._trees.popitem(last=False)
        return dist, pred

    def path_from_tree(self, src: int, dst: int, pred) -> list[int]:
        if src == dst:
            return [src]
        path = [int(dst)]
        while path[-1] != src:
            p = pred[path[-1]]
            if p < 0:
                raise ValueError(f"no path {src}->{dst}")
            path.append(int(p))
        path.reverse()
        return path

    def shortest_path(self, a: int, b: int) -> tuple[tuple[int, ...], float, float]:
        """Fastest path a->b. Returns (nodes, distance_km, minutes)."""
        dist, pred = self.tree(a)
        if not np.isfinite(dist[b]):
            raise ValueError(f"no path {a}->{b}")
        path = self.path_from_tree(a, b, pred)
        km = float(sum(self.ekm[self.eid[(u, v)]] for u, v in zip(path, path[1:])))
        return tuple(path), km, float(dist[b])

    def edge(self, u: int, v: int) -> dict:
        i = self.eid[(u, v)]
        return {"from": u, "to": v, "distance_km": float(self.ekm[i]), "avg_speed_kmh": float(self.espeed[i]),
                "road_type": self.eroad[i], "name": self.ename[i]}

    def polyline(self, path: list[int]) -> list[list[float]]:
        """Road geometry along a node path, for drawing on the map."""
        pts: list[list[float]] = []
        for u, v in zip(path, path[1:]):
            i = self.eid[(u, v)]
            g = self.egeom[i] if self.eu[i] == u else self.egeom[i][::-1]
            pts.extend(g if not pts else g[1:])
        if not pts and path:
            pts = [list(self.coords(path[0]))]
        return pts

    # -- naming ---------------------------------------------------------------------
    def _area(self, la: float, lo: float) -> str | None:
        _, i = self._place_tree.query([la, lo * self._k])
        p = self._place_list[int(i)]
        if float(hav_km(la, lo, p["lat"], p["lon"])) > 6:
            return None
        return p["name"].replace(" (Home)", "").replace(" (Office)", "")

    def name(self, node: int) -> str:
        if node in self.place_at:
            return self.place_at[node]["name"]
        la, lo = self.coords(node)
        _, i = self._place_tree.query([la, lo * self._k])
        p = self._place_list[int(i)]
        km = float(hav_km(la, lo, p["lat"], p["lon"]))
        short = p["name"].replace(" (Home)", "").replace(" (Office)", "")
        return p["name"] if km < 1.5 else f"near {short}"

    # -- place resolution -------------------------------------------------------------
    def resolve(self, text, from_node: int, via: int | None = None) -> dict | None:
        """Turn free text ('nearest McD', 'mysore', 'home') into a concrete target."""
        if text is None or text == "":
            return None
        if isinstance(text, (int, np.integer)):
            return self._node_target(int(text))
        raw = _norm(str(text))
        if raw in self.places:
            return self._place_target(self.places[raw])
        if raw.isdigit() and int(raw) < self.n:
            return self._node_target(int(raw))
        q = re.sub(r"\s+", " ", FILLER.sub(" ", raw)).strip() or raw

        if re.search(r"\b(charger|charging|charge point|charging station|ev station)\b", raw):
            c = self.nearest_charger(from_node, fast_only="fast" in raw or "dc" in raw.split())
            if c:
                return {"kind": "charger", "node": c["node"], "name": c["name"], "charger_id": c["id"]}

        tokens = set(raw.split())
        for p in self.pois:                       # distinctive POI name, e.g. "phoenix", "orion"
            if self._poi_keywords(p) & tokens:
                return {"kind": "poi", "node": p["node"], "name": p["name"], "category": p["category"]}

        for cat, aliases in self.poi_aliases.items():
            if any(re.search(rf"\b{re.escape(a)}\b", raw) for a in aliases):
                in_place = self._match_place(q.replace(cat, " "), strict=True)
                poi = self.nearest_poi(cat, from_node, near=in_place, via=via)
                if poi:
                    return {"kind": "poi", "node": poi["node"], "name": poi["name"], "category": cat}

        place = self._match_place(q)
        return self._place_target(place) if place else None

    def _place_target(self, p):
        return {"kind": "node", "node": p["node"], "name": p["name"], "place_id": p["id"]}

    def _node_target(self, node):
        return {"kind": "node", "node": node, "name": self.name(node)}

    def _poi_keywords(self, poi: dict) -> set[str]:
        key = poi["name"]
        if key not in self._poi_kw:
            generic = {"of", "day", "the", "and", "mall", "cafe", "coffee", "restaurant", "store", "city",
                       "road", "main", "cross", "layout", "nagar", "center", "centre", "plaza", "india",
                       "family", "drive", "thru", "express"}
            for aliases in self.poi_aliases.values():
                generic |= {w for a in aliases for w in a.split()}
            generic |= set(self.poi_aliases)
            words = set(_norm(poi["name"]).split()) - generic - self._place_words()
            self._poi_kw[key] = {w for w in words if len(w) > 3}
        return self._poi_kw[key]

    def _place_words(self) -> set[str]:
        if self._pw is None:
            ws = set()
            for p in self.places.values():
                ws |= set(_norm(p["name"]).split()) | set(p["id"].split("_"))
                for a in p["aliases"]:
                    ws |= set(a.split())
            self._pw = ws
        return self._pw

    def _match_place(self, q: str, strict: bool = False) -> dict | None:
        q = q.strip()
        if not q:
            return None
        labels = {}
        for p in sorted(self.places.values(), key=lambda p: p["kind"] not in ("city", "town", "manual")):
            for label in [p["id"].replace("_", " "), _norm(p["name"]), *p["aliases"]]:
                labels.setdefault(label, p)
        for label in sorted(labels, key=len, reverse=True):    # "electronic city" before "city"
            if len(label) >= 3 and re.search(rf"\b{re.escape(label)}\b", q):
                return labels[label]
        if strict:
            return None
        for word in [q, *q.split()]:
            m = difflib.get_close_matches(word, list(labels), n=1, cutoff=0.8)
            if m:
                return labels[m[0]]
        return None

    def nearest_poi(self, category: str, from_node: int, near: dict | None = None,
                    via: int | None = None) -> dict | None:
        cands = [p for p in self.pois if p["category"] == category]
        if near is not None:
            close = [p for p in cands if hav_km(p["lat"], p["lon"], near["lat"], near["lon"]) < 15]
            cands = close or cands
        if not cands:
            return None
        d_from, _ = self.tree(from_node)
        d_via = self.tree(via)[0] if via is not None else None

        def cost(p):
            return d_from[p["node"]] + (d_via[p["node"]] if d_via is not None else 0.0)

        best = min(cands, key=cost)
        return best if np.isfinite(cost(best)) else None

    def nearest_charger(self, from_node: int, fast_only: bool = False, exclude_home=True) -> dict | None:
        cands = [c for c in self.chargers.values() if c["available"]
                 and not (exclude_home and c["kind"] == "home_ac")
                 and (not fast_only or c["kind"] == "dc_fast")]
        if not cands:
            return None
        d, _ = self.tree(from_node)
        return min(cands, key=lambda c: (d[c["node"]], -c["power_kw"]))

    def chargers_at(self, node: int) -> list[dict]:
        return [c for c in self.chargers.values() if c["node"] == node and c["available"]]

    def to_dict(self) -> dict:
        """What the UI needs (no edges - routes carry their own geometry)."""
        return {
            "places": [{k: p[k] for k in ("id", "name", "lat", "lon", "node", "kind")} for p in self.places.values()],
            "chargers": [c for c in self.chargers.values() if c["lat"] is not None],
            "pois": self.pois,
            "source": self.source,
            "home": self.places["koramangala"],
        }
