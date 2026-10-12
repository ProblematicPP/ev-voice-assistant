"""Running-cost analysis: cost per km from charging spend vs distance driven."""
from __future__ import annotations

import pandas as pd

from app.config import PETROL_CAR_KMPL, PETROL_INR_PER_L


def cost_per_km(sessions: pd.DataFrame, trips: pd.DataFrame, days: int = 30) -> dict:
    s = sessions.copy()
    t = trips.copy()
    s["start"] = pd.to_datetime(s["start_ts"])
    t["start"] = pd.to_datetime(t["start_ts"])
    end = max(s.start.max(), t.start.max())
    s = s[s.start > end - pd.Timedelta(days=days)]
    t = t[t.start > end - pd.Timedelta(days=days)]

    km = float(t.distance_km.sum())
    spend = float(s.cost_inr.sum())
    by_type = s.groupby("charger_type").agg(kwh=("kwh", "sum"), cost=("cost_inr", "sum"))
    by_type["inr_per_kwh"] = by_type.cost / by_type.kwh
    per_km = spend / km if km else 0.0
    petrol_per_km = PETROL_INR_PER_L / PETROL_CAR_KMPL
    return {
        "window_days": days,
        "km_driven": round(km, 0),
        "charging_spend_inr": round(spend, 0),
        "cost_per_km_inr": round(per_km, 2),
        "petrol_equivalent_per_km_inr": round(petrol_per_km, 2),
        "monthly_saving_vs_petrol_inr": round((petrol_per_km - per_km) * km * 30 / days, 0),
        "by_charger_type": {
            k: {"kwh": round(float(r.kwh), 1), "cost_inr": round(float(r.cost), 0),
                "inr_per_kwh": round(float(r.inr_per_kwh), 1)}
            for k, r in by_type.iterrows()
        },
        "note": "Home charging is ~3x cheaper per kWh than DC fast charging.",
    }
