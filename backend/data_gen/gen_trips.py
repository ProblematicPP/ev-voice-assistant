"""Synthetic trip-segment dataset for the range (Wh/km) model.

Output: data/trips.csv
"""
import numpy as np
import pandas as pd

from app.config import DATA_DIR
from data_gen.physics import wh_per_km

N_TRIPS = 24_000


def generate(seed: int = 11) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    n = N_TRIPS
    road = np.where(rng.random(n) < 0.55, "city", "highway")
    city = road == "city"
    speed = np.where(city, rng.uniform(10, 45, n), rng.uniform(50, 110, n))
    temp = np.clip(rng.normal(28, 7, n), 2, 46)
    hvac = np.array([
        rng.choice(["off", "fan", "ac", "heat"], p=p)
        for p in np.where(
            (temp > 26)[:, None], [[0.15, 0.15, 0.70, 0.00]],
            np.where((temp < 16)[:, None], [[0.25, 0.15, 0.00, 0.60]], [[0.45, 0.35, 0.15, 0.05]]),
        )
    ])
    style = np.clip(rng.beta(2.2, 2.5, n), 0, 1)
    gradient = rng.normal(0, 4, n)                  # metres climbed per km
    payload = rng.choice([0, 75, 150, 225, 300], n, p=[0.05, 0.45, 0.25, 0.15, 0.10]) + rng.uniform(0, 40, n)
    soh = rng.uniform(0.70, 1.0, n)

    target = wh_per_km(temp, hvac, style, speed, gradient, payload, road, soh, rng=rng)
    distance = np.where(city, rng.uniform(2, 25, n), rng.uniform(15, 150, n))

    return pd.DataFrame({
        "trip_id": np.arange(n),
        "distance_km": distance.round(2),
        "soc_start": rng.uniform(0.2, 1.0, n).round(3),
        "ambient_temp_c": temp.round(1),
        "hvac_mode": hvac,
        "driving_style": style.round(3),
        "avg_speed_kmh": speed.round(1),
        "gradient_m_per_km": gradient.round(2),
        "payload_kg": payload.round(0),
        "road_type": road,
        "soh": soh.round(4),
        "wh_per_km": target.round(2),
    })


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    df = generate()
    df.to_csv(DATA_DIR / "trips.csv", index=False)
    print(f"trips.csv: {len(df)} rows, Wh/km {df.wh_per_km.quantile(.05):.0f}-{df.wh_per_km.quantile(.95):.0f} (p5-p95)")


if __name__ == "__main__":
    main()
