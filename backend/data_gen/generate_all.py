"""Generate every synthetic dataset. Run from backend/:  python -m data_gen.generate_all"""
from data_gen import gen_cells, gen_network, gen_owner, gen_trips

if __name__ == "__main__":
    for mod in (gen_network, gen_cells, gen_trips, gen_owner):
        print(f"--- {mod.__name__}")
        mod.main()
