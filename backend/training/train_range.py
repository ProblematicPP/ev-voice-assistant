"""Train the PyTorch energy-consumption (Wh/km) model used for personalized range.

Two stages:
  1. Fleet model on many vehicles' synthetic trip segments (data/trips.csv).
  2. Personal model: the fleet weights fine-tuned on THIS owner's own trips
     (data/owner_trips.csv), so quirks the fleet can't know (roof carrier, tyre
     pressure, regen habits) show up in range. 20% of the owner's trips (random,
     seed 0) are held out for testing. A time-based split was tried first, but the
     newest 40 trips are all city commutes, so it measured a change of driving mix
     rather than personalisation.

Run from backend/:  python -m training.train_range
"""
import copy
import json

import numpy as np
import pandas as pd
import torch

from app.battery_core.nn import TabularRegressor
from app.battery_core.range_model import (CITY_SPEED, ENCODED_FEATURES, FLEET_MODEL_PATH, HIGHWAY_SPEED,
                                          OWNER_MODEL_PATH, encode)
from app.config import DATA_DIR, MODELS_DIR
from training.train_soh import metrics


def segment_rows(trips: pd.DataFrame, road: str, speed: float) -> pd.DataFrame:
    """Owner trips log only a highway share; represent each as a city and a highway segment."""
    return pd.DataFrame({
        "ambient_temp_c": trips.ambient_temp_c, "hvac_mode": trips.hvac_mode,
        "driving_style": trips.driving_style, "avg_speed_kmh": speed, "gradient_m_per_km": 0.0,
        "payload_kg": 75.0, "road_type": road, "soh": trips.soh,
    })


def mixed_predict(reg: TabularRegressor, trips: pd.DataFrame) -> np.ndarray:
    city = reg.predict(encode(segment_rows(trips, "city", CITY_SPEED)))
    hwy = reg.predict(encode(segment_rows(trips, "highway", HIGHWAY_SPEED)))
    h = trips.highway_share.to_numpy()
    return (1 - h) * city + h * hwy


def fine_tune(fleet: TabularRegressor, trips: pd.DataFrame, epochs=100, lr=2e-4, seed=0) -> TabularRegressor:
    """Fine-tune all layers on whole-trip Wh/km (city/highway mixture), keeping the fleet scaler."""
    torch.manual_seed(seed)
    reg = copy.deepcopy(fleet)
    norm = lambda X: torch.from_numpy(((X - reg.x_mean) / reg.x_std).astype(np.float32))
    xc = norm(encode(segment_rows(trips, "city", CITY_SPEED)))
    xh = norm(encode(segment_rows(trips, "highway", HIGHWAY_SPEED)))
    h = torch.tensor(trips.highway_share.to_numpy(), dtype=torch.float32)
    y = torch.tensor(trips.wh_per_km.to_numpy(), dtype=torch.float32)
    opt = torch.optim.AdamW(reg.model.parameters(), lr=lr, weight_decay=1e-3)
    to_whkm = lambda out: torch.exp(out * reg.y_std + reg.y_mean)       # model is trained in log space
    reg.model.train()
    for _ in range(epochs):
        opt.zero_grad()
        pred = (1 - h) * to_whkm(reg.model(xc)) + h * to_whkm(reg.model(xh))
        loss = torch.mean(((pred - y) / y) ** 2)
        loss.backward()
        opt.step()
    reg.model.eval()
    return reg


def train_fleet() -> tuple[TabularRegressor, dict]:
    df = pd.read_csv(DATA_DIR / "trips.csv")
    rng = np.random.default_rng(1)
    mask = rng.random(len(df)) < 0.8
    tr, va = df[mask], df[~mask]
    print(f"Fleet range model: {len(tr)} train / {len(va)} val trip segments")
    model = TabularRegressor(ENCODED_FEATURES, hidden=(64, 64), log_target=True)
    model.fit(encode(tr), tr.wh_per_km.to_numpy(), encode(va), va.wh_per_km.to_numpy(), epochs=50, lr=3e-3)
    m = metrics(va.wh_per_km.to_numpy(), model.predict(encode(va)))
    print(f"  fleet validation: MAE={m['mae']:.1f} Wh/km  MAPE={m['mape'] * 100:.1f}%  R2={m['r2']:.3f}")
    model.save(FLEET_MODEL_PATH, metrics=m)
    return model, m


def train_owner(fleet: TabularRegressor, fleet_m: dict) -> dict:
    trips = pd.read_csv(DATA_DIR / "owner_trips.csv")
    held_out = np.random.default_rng(0).random(len(trips)) >= 0.8
    tr, te = trips[~held_out], trips[held_out]
    print(f"Personal range model: fine-tune on {len(tr)} of the owner's trips, test on {len(te)} held-out trips")
    personal = fine_tune(fleet, tr)
    y = te.wh_per_km.to_numpy()
    before = metrics(y, mixed_predict(fleet, te))
    after = metrics(y, mixed_predict(personal, te))
    m = {**after, "fleet_model_on_owner_test": before, "fleet_validation": fleet_m,
         "owner_train_trips": len(tr), "owner_test_trips": len(te), "split": "owner trips, random 80/20 (seed 0)"}
    print(f"  owner test trips: fleet MAE={before['mae']:.1f} Wh/km (MAPE {before['mape'] * 100:.1f}%) -> "
          f"personal MAE={after['mae']:.1f} Wh/km (MAPE {after['mape'] * 100:.1f}%)")
    personal.save(OWNER_MODEL_PATH, metrics=m)
    return m


def main():
    fleet, fleet_m = train_fleet()
    m = train_owner(fleet, fleet_m)
    (MODELS_DIR / "range_metrics.json").write_text(json.dumps(m, indent=2))


if __name__ == "__main__":
    main()
