"""Generate every dataset. Run from backend/:  python -m data_gen.generate_all

1. Download the Karnataka OpenStreetMap extract (~130 MB, once) and build the road graph.
2. Download NASA's real battery-ageing data (~210 MB, once); the demo car and the fleet replay
   real cells' BMS logs from it.
3. Place demo chargers, then synthesize battery-cycle, trip, owner-history and fleet data.
"""
from data_gen import (build_osm_network, gen_cells, gen_demo_chargers, gen_fleet, gen_owner, gen_trips,
                      nasa_battery, osm_fetch)

if __name__ == "__main__":
    for mod in (osm_fetch, build_osm_network, gen_demo_chargers, nasa_battery, gen_cells, gen_trips, gen_owner,
                gen_fleet):
        print(f"--- {mod.__name__}")
        mod.main()
