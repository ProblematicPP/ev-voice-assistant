"""Download the Karnataka OpenStreetMap extract (one-time, ~130 MB).

Source: openstreetmap.fr state extracts (updated daily). Public Overpass servers
time out on a state-wide road query, so we use the extract file instead.
Data (c) OpenStreetMap contributors, ODbL.

Output: data/osm_raw/karnataka-latest.osm.pbf   (delete it to re-download)
Run from backend/:  python -m data_gen.osm_fetch
"""
import time

import httpx

from app.config import DATA_DIR

RAW = DATA_DIR / "osm_raw"
PBF = RAW / "karnataka-latest.osm.pbf"
URL = "https://download.openstreetmap.fr/extracts/asia/india/karnataka-latest.osm.pbf"


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    if PBF.exists() and PBF.stat().st_size > 10_000_000:
        print(f"{PBF.name}: cached ({PBF.stat().st_size / 1e6:.0f} MB)")
        return
    tmp = PBF.with_suffix(".part")
    t = time.time()
    with httpx.stream("GET", URL, timeout=60, follow_redirects=True) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        done = 0
        with open(tmp, "wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
                done += len(chunk)
                if total and done % (20 << 20) < (1 << 20):
                    print(f"  {done / 1e6:.0f}/{total / 1e6:.0f} MB")
    tmp.replace(PBF)
    print(f"{PBF.name}: {done / 1e6:.0f} MB in {time.time() - t:.0f}s")


if __name__ == "__main__":
    main()
