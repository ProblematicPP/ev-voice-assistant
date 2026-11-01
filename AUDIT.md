# Audit: "AI for Optimizing EVs" against the project spec

Audited on 2 Nov 2026 on branch `audit-and-gaps`.

**How each requirement was checked:**
- `pytest`: 28 tests, all passing.
- The FastAPI app was run in-process and every REST endpoint was called.
- Volt was driven through `/api/chat` with the real Ollama model (`qwen3.5:4b`), then again with the LLM switched off.
- A voice round trip ran through `/api/tts` and then `/api/stt`.
- The frontend production build was run.

A requirement is **DONE** only if one of those runs exercised it.

Status key:
- **DONE**: works and was verified.
- **PARTIAL**: exists, but part of the spec is missing.
- **MISSING**: not built.
- **BROKEN**: built, but fails when run.

## Status table

| # | Requirement | Status | Implemented in | Note |
|---|---|---|---|---|
| 1.1 | One shared battery core, four consumers | PARTIAL | `app/battery_core/core.py` (`BatteryCore`), `app/context.py` | Assistant, planner and companion call the core. There is no fleet consumer. The resale projection calls the ageing physics from `companion/resale.py` instead of going through the core. |
| 1.2 | Inputs: telemetry, charging history, weather & traffic, station data | PARTIAL | `data/charging_history.csv`, `routing/network.py` | Charging history and station data are wired in. There is no telemetry stream, and weather and traffic are only manual simulator sliders. |
| 2.1 | OSM Karnataka extract to a road graph with chargers on it | DONE | `data_gen/osm_fetch.py`, `data_gen/build_osm_network.py`, `data/network.json` | 39,755 road nodes, 37 OSM chargers plus 50 seeded demo chargers. `test_route_follows_real_roads` passes. |
| 2.2 | Synthetic NASA/CALCE-style cells, trips, owner and charging data from one command | DONE | `data_gen/generate_all.py`, `gen_cells.py`, `gen_trips.py`, `gen_owner.py`, `physics.py` | Physics-based and seeded. Re-checked from a fresh clone at the end of the build (see below). |
| 2.3 | Simulated OBD-II/CAN telemetry stream | MISSING | none | `simulation.drive` moves the car, but no telemetry samples or events are emitted. |
| 2.4 | Weather / traffic / station availability behind a replaceable interface; live weather allowed | MISSING | none | Temperature is a slider. Traffic isn't modelled (OSM speeds only). Charger availability is a static flag. |
| 3.1 | SOH MLP on 10 BMS features, split by cell, error on held-out cells | PARTIAL | `battery_core/soh_model.py`, `ageing.py`, `training/train_soh.py` | The 10 features and the by-cell split are right. There is only a train/val split (no test set) and no MAPE. Val MAE is 0.55% SOH. |
| 3.2 | Personalised range MLP (Wh/km from the owner's own history); range = usable × SOH ÷ Wh/km; brochure range exposed | PARTIAL | `battery_core/range_model.py`, `training/train_range.py` | The formula and the brochure `naive_km` are right. The MLP is trained on fleet-wide synthetic trips; the owner's history only sets the driving-style input. |
| 3.3 | RUL / degradation projection feeding the 2-year resale projection by habit | PARTIAL | `companion/resale.py` (`project_soh`) | The habit projection works but lives in the companion, not the core. No RUL figure (cycles or years to end of life) is produced. |
| 3.4 | Shapley attribution of range vs brochure | DONE | `battery_core/attribution.py` | Exact Shapley values over 5 factors. `test_attribution_sums_to_total_drop` passes. |
| 3.5 | Battery guard: one function, allow / modify / refuse + reason + proposed stop | PARTIAL | `battery_core/guard.py` | There are six separate `assess_*` functions that return allow/deny plus a status. There is no single entry point, no verdict in that form, and driver assist skips the guard. |
| 3.6 | Weights and scalers saved; inference without retraining | DONE | `models/*.pt` (`nn.TabularRegressor.save/load`) | The checkpoints include the scaler stats. `models/` is gitignored, so a fresh clone recreates them with the train scripts. |
| 4.1 | Routing on the OSM graph with energy-aware edge costs | DONE | `routing/planner.py`, `BatteryCore.edge_energy_kwh` | Per-edge kWh comes from the range MLP under live conditions. |
| 4.2 | Stop insertion using battery health, arrival charge, availability/queue, charge time, ₹ cost | PARTIAL | `routing/planner.py` | Health, arrival charge, charge-time taper and cost are handled. There is no queue or wait time, and availability never changes. |
| 4.3 | Output: distance, duration incl. stop, arrival %, stop, charge time, cost, polyline | DONE | `planner._summarize` | Verified through `/api/route/plan`. |
| 4.4 | Re-planning mid-trip when a detour is added | BROKEN | `routing/replanner.py`, `planner.plan` | Navigating to Mysuru at 46% and then adding "a McDonald's on the way" returns *infeasible*. Each leg is planned greedily and the last charge is trimmed, so the car reaches the McDonald's near Maddur without enough charge for the next leg. It only works when the battery is high (the existing test uses 95%). |
| 4.5 | Honest about RL (deck cites DQN) | MISSING | `README.md` | The README doesn't say which algorithm is used, or that RL isn't implemented. |
| 5.1 | faster-whisper STT, Piper TTS | DONE | `assistant/stt.py`, `assistant/tts.py` | Piper said "Will I make it to Mysore…", Whisper transcribed it on CUDA (RTX 4050) in 0.4 s, and Piper synthesis took 3.0 s. |
| 5.2 | Ollama `qwen3.5:4b` with tool calling and a function router | PARTIAL | `assistant/llm.py`, `pipeline.py`, `router.py`, `tools.py` | Tool calls reach the core, planner and companion; there are no fleet tools. Replies take 3.6–12 s on the GPU. |
| 5.3 | Rule-based fallback, tested explicitly | PARTIAL | `assistant/fallback_parser.py` | The parser has unit tests, and the smoke run with the LLM off answered correctly in 0.2 s. No test runs the whole pipeline with the LLM unavailable. |
| 5.4.1 | Context-aware command ("nearest McD") cross-checked by the guard | DONE | `router.t_navigate_to` | With no active route, it navigates with the guard `ok`. With a route active, the LLM once picked `list_chargers`; that is flaky and noted in the demo script. |
| 5.4.2 | Feasibility query ("make it to Mysore without stopping?") | DONE | `router.t_check_range_to` | Answers "No… run out about 48 km short… 18-minute stop at Magenta ChargeGrid". |
| 5.4.3 | Proactive nudges, with a trigger loop and a UI surface | DONE | `assistant/nudges.py`, `main._nudge_loop`, `api/hub.py`, UI toast and offer card | "18% left, 55 km from home - route via a charger?" fires on the low-battery scenario. |
| 5.4.4 | Mid-drive re-planning with a detour | BROKEN | see 4.4 | Same bug as 4.4. |
| 5.4.5 | Range-drop attribution question | DONE | `router.t_explain_range` | Answered from the Shapley breakdown. |
| 5.4.6 | Eco-driving coaching from telemetry (harsh braking/acceleration) | MISSING | none | Only charging-habit coaching exists. |
| 5.5 | No action without the guard, with a test proving it | PARTIAL | `router.py`, `tests/test_core.py` | The only test covers infeasible navigation. `t_assisted_driving` and the query tools run without consulting the guard. |
| 6.1 | Companion tabs: Chat, Trip, Battery, Ownership, Simulator | PARTIAL | `frontend/src/App.jsx`, `screens/*` | The phone-app redesign named them Volt, Navigate, Battery, Insights, plus a Simulator dock outside the phone. The content matches; the labels don't match the deck. |
| 6.2 | Trip: route map, range ribbon (personalised vs brochure), stop card, ETA / arrival / cost, suggested prompts | PARTIAL | `screens/Navigate.jsx`, `screens/Volt.jsx` | Everything is there except the range ribbon, which was dropped in the redesign. |
| 6.3 | Battery tab | DONE | `screens/Battery.jsx` | SOH, usable kWh, cycles, % fast, SOH trend, Shapley chart, weekly energy by type, recent sessions. |
| 6.4 | Ownership tab | DONE | `screens/Insights.jsx`, `companion/*` | Health, ₹/km, resale value from SOH, coaching tips, 30-day cost vs petrol, 2-year projection by habit. |
| 6.5 | Simulator: SOC, temperature, AC, driving style, **charging habit** drive range / SOH / projection live | PARTIAL | `components/SimControls.jsx`, `api/sim.py` | There's no charging-habit input, and the projection doesn't respond to the simulator. |
| 6.6 | Fleet module: battery-aware allocation, demand-heatmap model, charging-aware long rentals, rebalancing, longevity metric, UI | MISSING | none | |
| 7 | One command for evaluation, writing `results/metrics.md` | MISSING | none | |
| 8.1 | `AUDIT.md` | DONE | this file | |
| 8.2 | Fresh clone runs with the README steps | PARTIAL | `README.md`, `run.txt` | The README predates the redesign, the demo chargers and the fleet/eval work. |
| 8.3 | `DEMO_SCRIPT.md` | MISSING | none | |

## Summary

- **Already solid:** the OSM road graph, the synthetic data pipeline, the SOH and range MLPs with saved weights, Shapley attribution, energy-aware routing with automatic charging stops, the speech stack (Whisper on GPU, Piper), LLM tool calling with a working fallback, proactive nudges, and the Battery and Ownership screens.
- **Broken (1):** adding a detour to a trip that needs a charging stop (4.4 / 5.4.4).
- **Missing:**
  - the fleet module (6.6)
  - the evaluation command (7)
  - the telemetry stream and eco-driving coaching (2.3, 5.4.6)
  - the weather / traffic / availability interface (2.4)
  - an honest note about RL (4.5)
  - `DEMO_SCRIPT.md` (8.3)
- **Partial:**
  - a single guard entry point (3.5, 5.5)
  - SOH test split and MAPE (3.1)
  - per-owner range personalisation (3.2)
  - RUL in the core (3.3)
  - charger queues (4.2)
  - an explicit fallback test (5.3)
  - deck tab names, the range ribbon and a charging-habit input (6.1, 6.2, 6.5)
  - the README (8.2)

## What I added

Filled in as each gap is closed; one commit per gap.
