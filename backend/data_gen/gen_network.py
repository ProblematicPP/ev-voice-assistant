"""Simulated road network for Bengaluru + the Mysuru/Tumakuru/Kolar corridors.

Coordinates are approximate real locations so the map looks plausible, but
distances, speeds, chargers and POIs are synthetic. No external map APIs.

Output: data/network.json
"""
import json
import math

from app.config import DATA_DIR

# id: (display name, lat, lon, elevation_m, aliases)
NODES = {
    "koramangala": ("Koramangala (Home)", 12.935, 77.624, 900, ["home", "house"]),
    "indiranagar": ("Indiranagar", 12.971, 77.641, 905, []),
    "mg_road": ("MG Road", 12.975, 77.606, 915, ["mg road", "city centre", "brigade road"]),
    "whitefield": ("Whitefield (Office)", 12.970, 77.750, 890, ["office", "work", "itpl"]),
    "electronic_city": ("Electronic City", 12.845, 77.660, 880, ["ecity", "e city"]),
    "hebbal": ("Hebbal", 13.035, 77.597, 910, []),
    "yelahanka": ("Yelahanka", 13.100, 77.596, 915, []),
    "devanahalli": ("Kempegowda Airport", 13.198, 77.706, 900, ["airport", "kia", "devanahalli"]),
    "chikkaballapur": ("Chikkaballapur", 13.435, 77.728, 915, ["nandi hills"]),
    "jayanagar": ("Jayanagar", 12.925, 77.583, 905, []),
    "banashankari": ("Banashankari", 12.925, 77.546, 890, []),
    "yeshwanthpur": ("Yeshwanthpur", 13.028, 77.540, 905, []),
    "kengeri": ("Kengeri", 12.912, 77.485, 830, []),
    "bidadi": ("Bidadi", 12.797, 77.388, 800, []),
    "ramanagara": ("Ramanagara", 12.722, 77.281, 750, ["ramanagaram"]),
    "channapatna": ("Channapatna", 12.652, 77.209, 730, []),
    "maddur": ("Maddur", 12.584, 77.044, 650, []),
    "mandya": ("Mandya", 12.524, 76.897, 680, []),
    "srirangapatna": ("Srirangapatna", 12.414, 76.704, 680, ["srirangapatnam"]),
    "mysuru": ("Mysuru", 12.296, 76.639, 770, ["mysore", "mysuru city"]),
    "nelamangala": ("Nelamangala", 13.097, 77.393, 880, []),
    "tumakuru": ("Tumakuru", 13.340, 77.101, 820, ["tumkur"]),
    "hoskote": ("Hoskote", 13.070, 77.798, 890, []),
    "kolar": ("Kolar", 13.137, 78.129, 850, []),
    "hosur": ("Hosur", 12.740, 77.825, 880, []),
}

# (a, b, road_type, avg_speed_kmh)
EDGES = [
    ("koramangala", "indiranagar", "city", 22), ("koramangala", "mg_road", "city", 20),
    ("koramangala", "jayanagar", "city", 22), ("koramangala", "electronic_city", "city", 30),
    ("indiranagar", "mg_road", "city", 20), ("indiranagar", "whitefield", "city", 24),
    ("mg_road", "hebbal", "city", 25), ("mg_road", "yeshwanthpur", "city", 22),
    ("mg_road", "jayanagar", "city", 20), ("hebbal", "yelahanka", "city", 35),
    ("yelahanka", "devanahalli", "highway", 65), ("devanahalli", "chikkaballapur", "highway", 70),
    ("hebbal", "yeshwanthpur", "city", 25), ("hebbal", "hoskote", "highway", 45),
    ("yeshwanthpur", "nelamangala", "highway", 50), ("nelamangala", "tumakuru", "highway", 85),
    ("whitefield", "hoskote", "city", 35), ("hoskote", "kolar", "highway", 85),
    ("electronic_city", "hosur", "highway", 60), ("jayanagar", "banashankari", "city", 22),
    ("banashankari", "kengeri", "city", 28), ("yeshwanthpur", "kengeri", "city", 30),
    ("kengeri", "bidadi", "highway", 80), ("bidadi", "ramanagara", "highway", 90),
    ("ramanagara", "channapatna", "highway", 90), ("channapatna", "maddur", "highway", 90),
    ("maddur", "mandya", "highway", 90), ("mandya", "srirangapatna", "highway", 85),
    ("srirangapatna", "mysuru", "highway", 55),
]

# id, node, name, power_kw, price_per_kwh (INR), kind
CHARGERS = [
    ("home", "koramangala", "Home wallbox", 7.4, 7.5, "home_ac"),
    ("ch_indira", "indiranagar", "Indiranagar EV Hub", 60, 21.0, "dc_fast"),
    ("ch_ecity", "electronic_city", "Electronic City Tech Park", 30, 18.0, "dc_fast"),
    ("ch_wf", "whitefield", "Whitefield Office Parking", 7.4, 12.0, "public_ac"),
    ("ch_kengeri", "kengeri", "Kengeri Metro Charge Point", 50, 19.5, "dc_fast"),
    ("ch_bidadi", "bidadi", "Bidadi Expressway Plaza", 120, 24.0, "dc_fast"),
    ("ch_maddur", "maddur", "Maddur Food Court Chargers", 60, 22.0, "dc_fast"),
    ("ch_mandya", "mandya", "Mandya Highway Charge", 30, 19.0, "dc_fast"),
    ("ch_mysuru", "mysuru", "Mysuru Ring Road Hub", 60, 20.0, "dc_fast"),
    ("ch_tumakuru", "tumakuru", "Tumakuru NH48 Charge", 50, 20.0, "dc_fast"),
    ("ch_airport", "devanahalli", "Airport P4 Fast Charge", 60, 23.0, "dc_fast"),
    ("ch_hoskote", "hoskote", "Hoskote Toll Plaza", 30, 19.0, "dc_fast"),
    ("ch_hosur", "hosur", "Hosur SIPCOT Charge", 30, 18.5, "dc_fast"),
]

# name, category/brand, node
POIS = [
    ("McDonald's Indiranagar", "mcdonalds", "indiranagar"),
    ("McDonald's Electronic City", "mcdonalds", "electronic_city"),
    ("McDonald's Maddur", "mcdonalds", "maddur"),
    ("McDonald's Mysuru", "mcdonalds", "mysuru"),
    ("Starbucks Indiranagar", "cafe", "indiranagar"),
    ("Cafe Coffee Day Channapatna", "cafe", "channapatna"),
    ("Kamat Upachar Bidadi", "restaurant", "bidadi"),
    ("Phoenix Marketcity", "mall", "whitefield"),
    ("Orion Mall", "mall", "yeshwanthpur"),
    ("Mall of Mysore", "mall", "mysuru"),
    ("Mysore Palace", "attraction", "mysuru"),
    ("Nandi Hills", "attraction", "chikkaballapur"),
    ("Apollo Hospital Jayanagar", "hospital", "jayanagar"),
]

POI_ALIASES = {
    "mcdonalds": ["mcd", "mcdonald", "mcdonalds", "mc donalds", "mac d", "macd", "mickey d"],
    "cafe": ["cafe", "coffee", "starbucks", "ccd"],
    "restaurant": ["restaurant", "food", "eat", "lunch", "dinner"],
    "mall": ["mall", "shopping"],
    "hospital": ["hospital", "clinic"],
    "attraction": ["palace", "sightseeing"],
}


def haversine_km(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def build() -> dict:
    nodes = [
        {"id": k, "name": v[0], "lat": v[1], "lon": v[2], "elevation_m": v[3], "aliases": v[4]}
        for k, v in NODES.items()
    ]
    edges = []
    for a, b, road, speed in EDGES:
        pa, pb = NODES[a], NODES[b]
        winding = 1.35 if road == "city" else 1.15
        edges.append({
            "from": a, "to": b, "road_type": road, "avg_speed_kmh": speed,
            "distance_km": round(haversine_km(pa[1:3], pb[1:3]) * winding, 1),
        })
    chargers = [
        {"id": c[0], "node": c[1], "name": c[2], "power_kw": c[3], "price_per_kwh": c[4],
         "kind": c[5], "available": True}
        for c in CHARGERS
    ]
    pois = [{"name": p[0], "category": p[1], "node": p[2]} for p in POIS]
    return {"nodes": nodes, "edges": edges, "chargers": chargers, "pois": pois, "poi_aliases": POI_ALIASES}


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    net = build()
    (DATA_DIR / "network.json").write_text(json.dumps(net, indent=2))
    print(f"network.json: {len(net['nodes'])} nodes, {len(net['edges'])} edges, "
          f"{len(net['chargers'])} chargers, {len(net['pois'])} POIs")


if __name__ == "__main__":
    main()
