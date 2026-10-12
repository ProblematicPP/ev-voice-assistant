"""Simulated road network: graph search, place-name resolution, POI lookup."""
from __future__ import annotations

import difflib
import heapq
import json
import re
from functools import lru_cache

from app.config import DATA_DIR


def _norm(text: str) -> str:
    text = text.lower().replace("'", "").replace("’", "")
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


FILLER = re.compile(
    r"\b(the|a|an|nearest|closest|nearby|near me|nearer|some|any|please|me|to|my|go|take|"
    r"drive|navigate|place|one|location|restaurant of|outlet|without stopping|stopping|stop)\b"
)


class RoadNetwork:
    def __init__(self, path=DATA_DIR / "network.json"):
        data = json.loads(path.read_text())
        self.nodes = {n["id"]: n for n in data["nodes"]}
        self.edges = data["edges"]
        self.chargers = {c["id"]: c for c in data["chargers"]}
        self.pois = data["pois"]
        self.poi_aliases = data["poi_aliases"]
        self.elev = {k: v["elevation_m"] for k, v in self.nodes.items()}
        self.adj: dict[str, list[dict]] = {k: [] for k in self.nodes}
        for e in self.edges:
            self.adj[e["from"]].append({**e, "to": e["to"]})
            self.adj[e["to"]].append({**e, "from": e["to"], "to": e["from"]})

    # -- graph search --------------------------------------------------------
    @lru_cache(maxsize=2048)
    def shortest_path(self, a: str, b: str) -> tuple[tuple[str, ...], float, float]:
        """Fastest path a->b. Returns (nodes, distance_km, minutes)."""
        if a == b:
            return (a,), 0.0, 0.0
        dist = {a: 0.0}
        prev: dict[str, str] = {}
        pq = [(0.0, a)]
        while pq:
            t, u = heapq.heappop(pq)
            if u == b:
                break
            if t > dist.get(u, float("inf")):
                continue
            for e in self.adj[u]:
                nt = t + e["distance_km"] / e["avg_speed_kmh"] * 60
                if nt < dist.get(e["to"], float("inf")):
                    dist[e["to"]] = nt
                    prev[e["to"]] = u
                    heapq.heappush(pq, (nt, e["to"]))
        if b not in dist:
            raise ValueError(f"no path {a}->{b}")
        path = [b]
        while path[-1] != a:
            path.append(prev[path[-1]])
        path.reverse()
        km = sum(self.edge(u, v)["distance_km"] for u, v in zip(path, path[1:]))
        return tuple(path), km, dist[b]

    def edge(self, u: str, v: str) -> dict:
        for e in self.adj[u]:
            if e["to"] == v:
                return e
        raise KeyError((u, v))

    def name(self, node: str) -> str:
        return self.nodes[node]["name"]

    # -- place resolution ----------------------------------------------------
    def resolve(self, text: str, from_node: str, via: str | None = None) -> dict | None:
        """Turn free text ('nearest McD', 'mysore', 'home') into a concrete target.

        With `via` (the current destination), brand/category matches minimise the detour.
        """
        if not text:
            return None
        raw = _norm(text)
        if raw in self.nodes:                                  # already a node id
            return self._node_target(raw)
        q = FILLER.sub(" ", raw)
        q = re.sub(r"\s+", " ", q).strip() or raw

        if re.search(r"\b(charger|charging|charge point|charging station|ev station)\b", raw):
            c = self.nearest_charger(from_node, fast_only="fast" in raw or "dc" in raw.split())
            if c:
                return {"kind": "charger", "node": c["node"], "name": c["name"], "charger_id": c["id"]}

        tokens = set(raw.split())
        for p in self.pois:                                    # specific POI by distinctive name
            if self._poi_keywords(p) & tokens:
                return {"kind": "poi", "node": p["node"], "name": p["name"], "category": p["category"]}

        for cat, aliases in self.poi_aliases.items():         # brand / category
            if any(re.search(rf"\b{re.escape(a)}\b", raw) for a in aliases):
                in_place = self._match_node(q.replace(cat, " "), strict=True)
                poi = self.nearest_poi(cat, from_node, in_node=in_place, via=via)
                if poi:
                    return {"kind": "poi", "node": poi["node"], "name": poi["name"], "category": cat}

        node = self._match_node(q)
        return self._node_target(node) if node else None

    def _poi_keywords(self, poi: dict) -> set[str]:
        generic = {"of", "day", "hub", "city"} | set(self.poi_aliases)
        for aliases in self.poi_aliases.values():
            generic |= {w for a in aliases for w in a.split()}
        for nid, n in self.nodes.items():
            generic |= set(nid.split("_")) | set(_norm(n["name"]).split()) | {w for a in n["aliases"] for w in a.split()}
        return set(_norm(poi["name"]).split()) - generic

    def _node_target(self, node):
        return {"kind": "node", "node": node, "name": self.name(node)}

    def _match_node(self, q: str, strict: bool = False) -> str | None:
        q = q.strip()
        if not q:
            return None
        names = {}
        for nid, n in self.nodes.items():
            for label in [nid.replace("_", " "), _norm(n["name"]), *n["aliases"]]:
                names[label] = nid
        for label, nid in names.items():                       # whole-word containment
            if re.search(rf"\b{re.escape(label)}\b", q):
                return nid
        if strict:
            return None
        for word in [q, *q.split()]:
            m = difflib.get_close_matches(word, list(names), n=1, cutoff=0.75)
            if m:
                return names[m[0]]
        return None

    def nearest_poi(self, category: str, from_node: str, in_node: str | None = None,
                    via: str | None = None) -> dict | None:
        cands = [p for p in self.pois if p["category"] == category and (in_node is None or p["node"] == in_node)]
        if not cands:
            return None

        def cost(p):
            t = self.shortest_path(from_node, p["node"])[2]
            return t + (self.shortest_path(p["node"], via)[2] if via else 0.0)

        return min(cands, key=cost)

    def nearest_charger(self, from_node: str, fast_only: bool = False, exclude_home=True) -> dict | None:
        cands = [c for c in self.chargers.values() if c["available"]
                 and not (exclude_home and c["kind"] == "home_ac")
                 and (not fast_only or c["kind"] == "dc_fast")]
        if not cands:
            return None
        return min(cands, key=lambda c: (self.shortest_path(from_node, c["node"])[2], -c["power_kw"]))

    def chargers_at(self, node: str) -> list[dict]:
        return [c for c in self.chargers.values() if c["node"] == node and c["available"]]

    def to_dict(self) -> dict:
        return {"nodes": list(self.nodes.values()), "edges": self.edges,
                "chargers": list(self.chargers.values()), "pois": self.pois}
