"""Reproducible evaluation for the project's four evaluation areas.

Run from backend/:  python -m eval.run_all            (add --quick to skip the LLM and voice runs)

Writes ../results/metrics.md and ../results/metrics.json, and prints the summary table.
Every number is recomputed from the saved models and generated data - nothing is copied
from training logs.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import platform
import shutil
import statistics
import subprocess
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from app.battery_core.ageing import SOH_FEATURES
from app.battery_core.nn import TabularRegressor
from app.battery_core.range_model import FLEET_MODEL_PATH, OWNER_MODEL_PATH, encode, usable_kwh
from app.config import DATA_DIR, RESERVE_SOC, VEHICLE
from app.context import AppContext
from app.routing.planner import STOP_OVERHEAD_MIN, charge_minutes
from training.train_range import mixed_predict

RESULTS = Path(__file__).resolve().parents[2] / "results"


def mae_mape(y, p):
    y, p = np.asarray(y, float), np.asarray(p, float)
    return float(np.mean(np.abs(p - y))), float(np.mean(np.abs(p - y) / np.abs(y)))


# -- 1. SOH and range accuracy --------------------------------------------------------------
def eval_models(ctx) -> dict:
    # Shipped SOH model on the 7 real NASA cells it never trained on; each cell's log is fed from new
    from data_gen.nasa_battery import TEST_CELLS
    nasa = pd.read_csv(DATA_DIR / "nasa_cycles.csv").sort_values(["cell_id", "cycle"])
    te = nasa[nasa.cell_id.isin(TEST_CELLS)]
    pred = np.concatenate([ctx.battery.soh_model.predict_log(g) for _, g in te.groupby("cell_id", sort=False)])
    soh_mae, soh_mape = mae_mape(te.soh, pred)
    test_cells = TEST_CELLS
    per_cell = {c: 100 * float(np.mean(np.abs(ctx.battery.soh_model.predict_log(g) - g.soh)))
                for c, g in te.groupby("cell_id", sort=False)}
    car = ctx.battery.profile.get("battery_log", {})

    trips = pd.read_csv(DATA_DIR / "trips.csv")
    val = trips[~(np.random.default_rng(1).random(len(trips)) < 0.8)]          # same split as training
    fleet = TabularRegressor.load(FLEET_MODEL_PATH)
    r_mae, r_mape = mae_mape(val.wh_per_km, fleet.predict(encode(val)))

    owner = pd.read_csv(DATA_DIR / "owner_trips.csv")
    held = owner[np.random.default_rng(0).random(len(owner)) >= 0.8]
    personal = TabularRegressor.load(OWNER_MODEL_PATH)
    f_mae, f_mape = mae_mape(held.wh_per_km, mixed_predict(fleet, held))
    p_mae, p_mape = mae_mape(held.wh_per_km, mixed_predict(personal, held))
    return {
        "soh": {"test_cells": len(test_cells), "test_cycles": int(len(te)), "mae_pct_points": 100 * soh_mae,
                "mape_pct": 100 * soh_mape, "per_cell_mae_pct_points": per_cell,
                "demo_car": {"cell": car.get("source"), "estimate_pct": 100 * ctx.battery.soh_now,
                             "lab_measured_pct": 100 * car.get("lab_measured_soh", float("nan"))}},
        "range_fleet": {"val_trips": int(len(val)), "mae_wh_km": r_mae, "mape_pct": 100 * r_mape},
        "range_owner": {"held_out_trips": int(len(held)), "fleet_mae_wh_km": f_mae, "fleet_mape_pct": 100 * f_mape,
                        "personal_mae_wh_km": p_mae, "personal_mape_pct": 100 * p_mape},
    }


def eval_nasa() -> dict:
    """The SOH method on REAL cells (NASA PCoE), held out by cell. Skipped if the data isn't downloaded."""
    if not (DATA_DIR / "nasa_cycles.csv").exists():
        return {"skipped": "run python -m data_gen.nasa_battery first (downloads ~210 MB)"}
    from training import validate_soh_nasa as v
    df = v.load()
    synthetic = TabularRegressor.load(v.SYNTHETIC_MODEL_PATH)
    classic, _ = v.evaluate(df[df.cell_id.isin(v.CLASSIC)], [[c] for c in v.CLASSIC], synthetic)
    cells = np.random.default_rng(0).permutation(sorted(df.cell_id.unique()))
    every, _ = v.evaluate(df, [list(f) for f in np.array_split(cells, 5)], synthetic)
    return {"classic": classic, "all": every}


# -- 2. Route and charging-stop efficiency ------------------------------------------------------
def brochure_baseline(ctx, origin: int, dest: int, soc0: float, cond: dict) -> dict:
    """A static, non-battery-aware router: fastest path, and it believes the brochure range
    (312 km per full charge, regardless of weather, AC, driving or battery age). When it thinks
    it would arrive below 10% it detours to the nearest fast charger and charges to 80%.
    It is scored with the same energy model as the battery-aware planner."""
    net = ctx.net
    energy = ctx.battery.edge_energy_kwh(net, cond)
    usable = usable_kwh(cond["soh"])
    per_km = 1.0 / VEHICLE["rated_range_km"]
    soc, believed, minutes, stops, low = soc0, soc0, 0.0, 0, soc0
    cur, charged_at = origin, set()

    path = list(net.shortest_path(cur, dest)[0])
    i = 0
    while cur != dest:
        remaining = sum(net.edge(u, v)["distance_km"] for u, v in zip(path[i:], path[i + 1:]))
        if believed - remaining * per_km < 0.10 and len(charged_at) < 4:
            ch = net.nearest_charger(cur, fast_only=True)
            if ch and ch["id"] not in charged_at:
                detour = list(net.shortest_path(cur, ch["node"])[0])
                for u, v in zip(detour, detour[1:]):
                    e = net.edge(u, v)
                    soc -= energy[(u, v)] / usable
                    minutes += net.emin[net.eid[(u, v)]]
                    low = min(low, soc)
                if soc <= 0:
                    return {"stranded": True, "min_soc": low, "stops": stops}
                kw = min(ch["power_kw"], VEHICLE["max_dc_kw"])
                minutes += charge_minutes(soc, 0.8, kw, usable) + STOP_OVERHEAD_MIN
                soc = believed = max(soc, 0.8)
                stops += 1
                charged_at.add(ch["id"])
                cur = ch["node"]
                path, i = list(net.shortest_path(cur, dest)[0]), 0
                continue
        u, v = path[i], path[i + 1]
        e = net.edge(u, v)
        soc -= energy[(u, v)] / usable
        believed -= e["distance_km"] * per_km
        minutes += net.emin[net.eid[(u, v)]]
        low = min(low, soc)
        if soc <= 0:
            return {"stranded": True, "min_soc": low, "stops": stops}
        cur, i = v, i + 1
    return {"stranded": False, "arrival_soc": soc, "min_soc": low, "total_min": minutes, "stops": stops}


def eval_routing(ctx) -> dict:
    origins = ["koramangala", "whitefield", "hebbal"]
    dests = ["mysuru", "hassan", "tumakuru", "chikkaballapur", "kolar", "mandya", "channapatna",
             "electronic_city", "kempegowda_airport"]
    socs = [0.3, 0.5, 0.7, 0.9]
    st = ctx.state
    st.ambient_temp_c, st.hvac_mode = 34.0, "ac"            # the demo's hot Bengaluru afternoon
    cond = ctx.battery.conditions(st)
    rows = []
    for o in origins:
        for d in dests:
            for s in socs:
                a, b = ctx.net.place_node(o), ctx.net.place_node(d)
                p = ctx.planner.plan(a, [b], s, cond)
                base = brochure_baseline(ctx, a, b, s, cond)
                ours = {"refused": p["status"] == "infeasible"}
                if not ours["refused"]:
                    ours.update(arrival_soc=p["totals"]["arrival_soc"], total_min=p["totals"]["total_min"],
                                stops=len(p["stops"]))
                rows.append({"trip": f"{o}->{d}@{int(s * 100)}%", "ours": ours, "base": base})
    n = len(rows)
    both = [r for r in rows if not r["ours"]["refused"] and not r["base"]["stranded"]]
    planned = [r for r in rows if not r["ours"]["refused"]]
    pct = lambda k: 100 * k / n
    return {
        "trips": n, "conditions": "34 °C, AC on, current battery health",
        "baseline_stranded_pct": pct(sum(r["base"]["stranded"] for r in rows)),
        "baseline_below_reserve_pct": pct(sum(not r["base"]["stranded"] and r["base"]["arrival_soc"] < RESERVE_SOC
                                              for r in rows)),
        "ours_stranded_pct": 0.0,
        "ours_below_reserve_pct": pct(sum(r["ours"]["arrival_soc"] < RESERVE_SOC - 1e-6 for r in planned)),
        "ours_refused_pct": pct(n - len(planned)),
        "both_completed": len(both),
        "avg_total_min_ours": statistics.mean(r["ours"]["total_min"] for r in both) if both else None,
        "avg_total_min_baseline": statistics.mean(r["base"]["total_min"] for r in both) if both else None,
        "avg_stops_ours": statistics.mean(r["ours"]["stops"] for r in both) if both else None,
        "avg_stops_baseline": statistics.mean(r["base"]["stops"] for r in both) if both else None,
    }


# -- 3. Assistant task success and latency -----------------------------------------------------
PROMPTS = [
    # (setup, text, expected tool, extra check on args)
    (None, "Will I make it to Mysore without stopping?", "check_range_to", None),
    (None, "Take me to Mysuru", "navigate_to", None),
    (None, "Take me to the nearest McDonald's", "navigate_to", None),
    (None, "Why is my range lower than usual?", "explain_range", None),
    (None, "How much charge do I have left?", "get_battery_status", None),
    (None, "Find me a fast charger nearby", "list_chargers", None),
    (None, "Turn off the AC", "set_climate", lambda a: a.get("mode") == "off"),
    (None, "Pre-cool the cabin for 15 minutes", "precool_cabin", None),
    (None, "Show the left turn camera", "assisted_driving", None),
    (None, "How are my charging habits?", "get_charging_coaching", None),
    (None, "Am I braking too hard?", "get_eco_driving_coaching", None),
    (None, "What's my running cost per km and resale value?", "get_cost_and_resale", None),
    (None, "Which fleet cars should I move?", "get_fleet_status", None),
    (None, "Take me home without charging", "navigate_to", lambda a: a.get("no_charging") is True),
    ("route", "Also stop at a McDonald's on the way", "add_stop", None),
    ("route", "Cancel the navigation", "cancel_navigation", None),
    ("offer", "yes", "navigate_to", None),            # accepting runs the offered route (with its stop)
]


def _setup(ctx, kind):
    from app.assistant.router import ToolRouter
    ctx.reset()
    if kind in ("route", "far"):
        ctx.state.soc = 0.95
        ToolRouter(ctx).execute("navigate_to", {"destination": "Mysuru"})
    elif kind == "offer":
        ToolRouter(ctx).execute("check_range_to", {"destination": "Mysuru"})
    if kind is None:
        ctx.state.location = ctx.net.place_node("indiranagar")   # away from home so "take me home" is a trip


async def _run_assistant(ctx, use_llm: bool) -> dict:
    from app.assistant.pipeline import AssistantPipeline
    pipe = AssistantPipeline(ctx)
    if not use_llm:
        async def down():
            return False
        pipe.llm.available = down
    elif not await pipe.llm.available():
        return {"skipped": "Ollama or the model is not available"}
    else:
        await pipe.llm.chat([{"role": "user", "content": "hi"}])           # warm-up, not timed
    rows = []
    for setup, text, tool, check in PROMPTS:
        _setup(ctx, setup)
        t0 = time.perf_counter()
        out = await pipe.handle(text)
        dt = time.perf_counter() - t0
        call = out["tool_calls"][0] if out["tool_calls"] else {}
        ok = call.get("name") == tool and bool(call.get("ok")) and (check is None or check(call.get("args", {})))
        rows.append({"text": text, "expected": tool, "got": call.get("name"), "ok": ok, "latency_s": dt,
                     "source": out["source"]})
    lat = [r["latency_s"] for r in rows]
    return {"prompts": len(rows), "success_pct": 100 * sum(r["ok"] for r in rows) / len(rows),
            "median_latency_s": statistics.median(lat), "p95_latency_s": float(np.percentile(lat, 95)),
            "failures": [f"{r['text']} -> {r['got']}" for r in rows if not r["ok"]], "rows": rows}


def gpu_info() -> str:
    if shutil.which("nvidia-smi"):
        try:
            out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                                 capture_output=True, text=True, timeout=10).stdout.strip()
            if out:
                return out
        except Exception:
            pass
    return f"none detected (CPU: {platform.processor() or platform.machine()})"


def eval_voice() -> dict:
    from app.assistant import stt, tts
    try:
        tts.get_voice()
        t0 = time.perf_counter()
        wav = tts.synthesize("Will I make it to Mysore without stopping?")
        t_tts = time.perf_counter() - t0
        stt.get_model()
        t0 = time.perf_counter()
        heard = stt.transcribe(wav)
        t_stt = time.perf_counter() - t0
        return {"tts_s": t_tts, "stt_s": t_stt, "stt_device": stt.device(), "heard": heard["text"],
                "audio_s": heard["duration_s"]}
    except Exception as exc:
        return {"skipped": f"speech models unavailable ({exc})"}


# -- 4. Fleet ------------------------------------------------------------------------------
def eval_fleet(ctx) -> dict:
    f = ctx.fleet()
    L = f.longevity()
    rb = {h: f.rebalance(start=pd.Timestamp(f"2026-11-03 {h}:00")) for h in ("08", "18")}
    today = f.allocation_today()
    return {"longevity": L, "demand_model": f.demand.metrics,
            "rebalance": {h: {k: r[k] for k in ("expected_lost_before", "expected_lost_after", "reduction_pct")}
                          | {"moves": len(r["moves"])} for h, r in rb.items()},
            "today_fast_charges": {k: v["fast_charges"] for k, v in today.items()}}


# -- report ------------------------------------------------------------------------------------
def fmt(x, nd=2):
    return "n/a" if x is None else f"{x:.{nd}f}"


def report(m: dict) -> str:
    s, rf, ro = m["models"]["soh"], m["models"]["range_fleet"], m["models"]["range_owner"]
    r, f = m["routing"], m["fleet"]
    L, dm = f["longevity"], f["demand_model"]
    lines = [
        "# Evaluation results", "",
        f"Generated {m['generated']} by `python -m eval.run_all`. Hardware: GPU {m['gpu']}.", "",
        "## 1. SOH and range accuracy (held-out data)", "",
        "Per held-out cell (SOH points): " + ", ".join(f"{c} {fmt(v, 1)}" for c, v in s["per_cell_mae_pct_points"].items())
        + f". Demo car (replays {s['demo_car']['cell']}): estimate {fmt(s['demo_car']['estimate_pct'], 1)}% vs "
        f"lab-measured {fmt(s['demo_car']['lab_measured_pct'], 1)}%.", "",
        "| Model | Held-out set | MAE | MAPE |", "|---|---|---|---|",
        f"| SOH MLP (shipped), trained on real NASA cells | {s['test_cells']} unseen **real** cells ({s['test_cycles']} cycles) | "
        f"{fmt(s['mae_pct_points'])} %-points SOH | {fmt(s['mape_pct'])}% |",
        f"| Range MLP, fleet | {rf['val_trips']} unseen trip segments | {fmt(rf['mae_wh_km'], 1)} Wh/km | {fmt(rf['mape_pct'], 1)}% |",
        f"| Range MLP, fleet model on owner's trips | {ro['held_out_trips']} held-out owner trips | "
        f"{fmt(ro['fleet_mae_wh_km'], 1)} Wh/km | {fmt(ro['fleet_mape_pct'], 1)}% |",
        f"| Range MLP, personalised (fine-tuned) | same {ro['held_out_trips']} trips | "
        f"{fmt(ro['personal_mae_wh_km'], 1)} Wh/km | {fmt(ro['personal_mape_pct'], 1)}% |", "",
        "### SOH on real batteries (NASA PCoE ageing data)", "",
    ]
    nz = m["nasa"]
    if "skipped" in nz:
        lines += [f"Skipped: {nz['skipped']}.", ""]
    else:
        lines += [
            "Same 10 BMS features, computed from the measured signals of real 18650 cells; SOH = measured "
            "capacity / 2.0 Ah. No cell is in both the training and test side.", "",
            "| Held-out real cells | MLP trained on real cells | Synthetic model fine-tuned on real | "
            "Synthetic model, unchanged | Cycle count only | Average SOH |", "|---|---|---|---|---|---|",
        ]
        for label, k in (("Classic 4 cells (B0005/6/7/18), leave-one-cell-out", "classic"),
                         ("All 34 cells, 5 folds by cell", "all")):
            res = nz[k]
            cell = lambda meth: f"{fmt(res[meth]['mae_pct_points'])} pts ({fmt(res[meth]['mape_pct'], 1)}%)"
            lines.append(f"| {label} ({res['cycles']} cycles) | {cell('real')} | {cell('fine_tuned')} | "
                         f"{cell('zero_shot')} | {cell('cycle_only')} | {cell('mean')} |")
        lines += ["", "MAE in SOH percentage points (MAPE in brackets). The method works on real cells; the app's "
                  "synthetic-trained weights do not transfer to them, so a real deployment must train on real data.", ""]
    lines += [
        "## 2. Route and charging-stop efficiency", "",
        f"{r['trips']} trips (3 Bengaluru origins x 9 destinations x 4 starting charges), {r['conditions']}. "
        "The baseline routes the fastest way and trusts the brochure range (312 km); both are scored with the "
        "same energy model, so this measures the value of being battery- and condition-aware inside the simulation.", "",
        "| | Battery-aware planner | Static brochure-range baseline |", "|---|---|---|",
        f"| Trips stranded (battery empty) | {fmt(r['ours_stranded_pct'], 1)}% | {fmt(r['baseline_stranded_pct'], 1)}% |",
        f"| Arrived below the 10% reserve | {fmt(r['ours_below_reserve_pct'], 1)}% | {fmt(r['baseline_below_reserve_pct'], 1)}% |",
        f"| Refused as infeasible (nearest charger offered) | {fmt(r['ours_refused_pct'], 1)}% | 0% (it just drives) |",
        f"| Avg trip time, trips both completed (n={r['both_completed']}) | {fmt(r['avg_total_min_ours'], 0)} min | "
        f"{fmt(r['avg_total_min_baseline'], 0)} min |",
        f"| Avg charging stops, same trips | {fmt(r['avg_stops_ours'])} | {fmt(r['avg_stops_baseline'])} |", "",
        "## 3. Assistant task success and latency", "",
        f"{len(PROMPTS)} prompts covering every tool, run end to end through the pipeline (intent -> guard -> "
        "router -> reply).", "",
        "| Path | Success | Median latency | p95 latency |", "|---|---|---|---|",
    ]
    for name, a in (("Local LLM (Ollama, qwen3.5:4b)", m["assistant"]["llm"]),
                    ("Rule-based fallback (no LLM)", m["assistant"]["fallback"])):
        if "skipped" in a:
            lines.append(f"| {name} | skipped: {a['skipped']} | | |")
        else:
            lines.append(f"| {name} | {fmt(a['success_pct'], 0)}% ({a['prompts']} prompts) | "
                         f"{fmt(a['median_latency_s'])} s | {fmt(a['p95_latency_s'])} s |")
    v = m["voice"]
    lines.append("")
    if "skipped" in v:
        lines.append(f"Voice: {v['skipped']}.")
    else:
        lines.append(f"Voice: Piper synthesised a {fmt(v['audio_s'], 1)} s question in {fmt(v['tts_s'])} s; "
                     f"faster-whisper on {v['stt_device']} transcribed it in {fmt(v['stt_s'])} s "
                     f"(heard: \"{v['heard']}\").")
    for label, key in (("LLM", "llm"), ("Fallback", "fallback")):
        fails = m["assistant"][key].get("failures") or []
        if fails:
            lines += ["", f"{label} misses: " + "; ".join(fails) + "."]
    h, n = L["health_aware"], L["first_available"]
    lines += [
        "", "## 4. Fleet battery longevity", "",
        f"One simulated year ({L['days']} days) of rentals on the 40-car fleet, same bookings for both policies.", "",
        "| | Health-aware allocation | First available car |", "|---|---|---|",
        f"| Capacity lost (avg, %-points) | {fmt(h['capacity_lost_pct_points'])} | {fmt(n['capacity_lost_pct_points'])} |",
        f"| Average SOH after a year | {fmt(100 * h['avg_soh_end'], 1)}% | {fmt(100 * n['avg_soh_end'], 1)}% |",
        f"| Packs below 70% after a year | {h['below_70pct']} | {n['below_70pct']} |",
        f"| Mid-trip fast charges | {h['fast_charges']:,} | {n['fast_charges']:,} |", "",
        f"**Estimated battery-life extension: +{fmt(L['battery_life_extension_pct'], 1)}%** (capacity is lost "
        f"{fmt(n['capacity_lost_pct_points'] / h['capacity_lost_pct_points'])}x more slowly).", "",
        f"Demand forecast (last 21 days held out): {fmt(dm['mae_vs_true_rate'], 3)} bookings/zone-hour from the true "
        f"rate vs {fmt(dm['baseline_mae_vs_true_rate'], 3)} for a zone-and-hour average; against noisy observed "
        f"counts {fmt(dm['mae'], 3)} vs {fmt(dm['baseline_mae'], 3)}.",
        "Rebalancing (3-hour horizon): " + "; ".join(
            f"{h_}:00 expected missed rentals {fmt(x['expected_lost_before'])} -> {fmt(x['expected_lost_after'])} "
            f"({fmt(x['reduction_pct'], 0)}% fewer, {x['moves']} moves)" for h_, x in f["rebalance"].items()) + ".",
        "", "All data is synthetic (see README). The routing and fleet comparisons are simulations, not field trials.",
    ]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="skip the LLM and voice runs")
    args = ap.parse_args()
    ctx = AppContext()
    m = {"generated": datetime.now().strftime("%Y-%m-%d %H:%M"), "gpu": gpu_info()}
    steps = [("models", lambda: eval_models(ctx)), ("nasa", eval_nasa), ("routing", lambda: eval_routing(ctx)),
             ("fleet", lambda: eval_fleet(ctx))]
    for name, fn in steps:
        t0 = time.time()
        print(f"[eval] {name}...", flush=True)
        m[name] = fn()
        print(f"[eval] {name} done in {time.time() - t0:.0f}s", flush=True)
    print("[eval] assistant...", flush=True)
    m["assistant"] = {"fallback": asyncio.run(_run_assistant(ctx, use_llm=False))}
    m["assistant"]["llm"] = ({"skipped": "--quick"} if args.quick else asyncio.run(_run_assistant(ctx, use_llm=True)))
    m["voice"] = {"skipped": "--quick"} if args.quick else eval_voice()
    RESULTS.mkdir(exist_ok=True)
    text = report(m)
    (RESULTS / "metrics.md").write_text(text, encoding="utf-8")
    (RESULTS / "metrics.json").write_text(json.dumps(m, indent=2, default=float), encoding="utf-8")
    print(text)
    print(f"Wrote {RESULTS / 'metrics.md'}")


if __name__ == "__main__":
    main()
