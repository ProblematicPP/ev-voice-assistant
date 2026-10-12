"""Rule-based charging-habit coaching from the owner's charging history."""
from __future__ import annotations

import pandas as pd

from app.config import HOME_PEAK_TARIFF_INR, HOME_TARIFF_INR


def _nudge(id_, severity, title, message, evidence):
    return {"id": id_, "severity": severity, "title": title, "message": message, "evidence": evidence}


def coach(sessions: pd.DataFrame) -> list[dict]:
    if sessions.empty:
        return []
    df = sessions.copy()
    df["start"] = pd.to_datetime(df["start_ts"])
    now = df["start"].max()
    week = df[df.start > now - pd.Timedelta(days=7)]
    fortnight = df[df.start > now - pd.Timedelta(days=14)]
    out = []

    fast_week = int((week.charger_type == "dc_fast").sum())
    if fast_week >= 3:
        out.append(_nudge(
            "fast_charge_frequency", "warn", "Lots of fast charging this week",
            f"You've fast-charged {fast_week} times this week. Frequent DC charging heats the pack and "
            f"speeds up ageing - try a slow home charge tonight.",
            {"dc_fast_sessions_7d": fast_week}))

    full = fortnight[fortnight.soc_end >= 0.98]
    if len(full) >= 4:
        out.append(_nudge(
            "charge_to_100", "warn", "Charging to 100% often",
            f"{len(full)} of your last {len(fortnight)} charges went to 100%. For daily driving, set an 80% "
            f"limit and only charge full before long trips.",
            {"full_charges_14d": len(full), "sessions_14d": len(fortnight)}))

    deep = fortnight[fortnight.soc_start < 0.10]
    if len(deep) >= 2:
        out.append(_nudge(
            "deep_discharge", "info", "Running very low before charging",
            f"You started {len(deep)} charges below 10% in the last two weeks. Plugging in around 20-30% "
            f"is gentler on the battery.", {"deep_discharges_14d": len(deep)}))

    hot = week[(week.charger_type == "dc_fast") & (week.battery_temp_max_c > 40)]
    if len(hot):
        out.append(_nudge(
            "hot_fast_charge", "info", "Fast charging in the heat",
            f"{len(hot)} fast charges this week pushed the battery above 40 °C. When you can, fast-charge in "
            f"the morning or evening rather than mid-afternoon.",
            {"hot_sessions_7d": len(hot), "max_temp_c": float(hot.battery_temp_max_c.max())}))

    home = fortnight[fortnight.charger_type == "home_ac"]
    peak = home[home.start.dt.hour.between(18, 21)]
    if len(peak) >= 3:
        saving = peak.kwh.sum() * (HOME_PEAK_TARIFF_INR - HOME_TARIFF_INR)
        out.append(_nudge(
            "peak_hour_charging", "info", "Shift home charging off-peak",
            f"{len(peak)} home charges started in the 6-10 pm peak window. Scheduling them after 11 pm would "
            f"have saved about ₹{saving:.0f} over two weeks.",
            {"peak_sessions_14d": len(peak), "saving_inr": round(float(saving))}))

    if not out:
        out.append(_nudge("all_good", "ok", "Great charging habits",
                          "Mostly slow charging at sensible levels - keep it up.", {}))
    return out


def summary(sessions: pd.DataFrame) -> dict:
    df = sessions.copy()
    df["start"] = pd.to_datetime(df["start_ts"])
    df["week"] = df.start.dt.to_period("W").dt.start_time.dt.strftime("%Y-%m-%d")
    weekly = (df.pivot_table(index="week", columns="charger_type", values="kwh", aggfunc="sum", fill_value=0)
              .reset_index())
    for col in ("home_ac", "public_ac", "dc_fast"):
        if col not in weekly:
            weekly[col] = 0.0
    return {
        "sessions": len(df),
        "kwh_total": round(float(df.kwh.sum()), 1),
        "share_by_type": {k: round(float(v), 3) for k, v in
                          (df.groupby("charger_type").kwh.sum() / df.kwh.sum()).items()},
        "weekly_kwh": weekly[["week", "home_ac", "public_ac", "dc_fast"]].round(1).to_dict("records"),
    }
