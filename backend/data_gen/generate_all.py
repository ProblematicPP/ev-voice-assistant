"""Generate every dataset. Run from backend/:  python -m data_gen.generate_all

1. Download the Karnataka OpenStreetMap extract (~130 MB, once) and build the road graph.
2. Synthesize battery-cycle, trip and owner-history data.
"""
from data_gen import build_osm_network, gen_cells, gen_owner, gen_trips, osm_fetch

if __name__ == "__main__":
    for mod in (osm_fetch, build_osm_network, gen_cells, gen_trips, gen_owner):
        print(f"--- {mod.__name__}")
        mod.main()
