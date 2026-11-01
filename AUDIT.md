# Audit: "AI for Optimizing EVs" against the project spec

Branch `audit-and-gaps`, 2 Nov 2026.

**How each requirement was checked:**
- The full pytest suite.
- Every REST endpoint, called in-process.
- Volt driven through `/api/chat` with the real Ollama model (`qwen3.5:4b`) and with the LLM switched off.
- A voice round trip: Piper speaks a question, faster-whisper transcribes it.
- The frontend production build, plus headless-browser screenshots of every screen.
- `python -m eval.run_all`.

A requirement is **DONE** only if one of those runs exercised it.

Status key:
- **DONE**: works and was verified.
- **PARTIAL**: exists, but part of the spec is missing.
- **MISSING**: not built.
- **BROKEN**: built, but fails when run.

## Status table

"Before" is the status at the start of this audit; "Now" is after the gap-closing commits listed below.

| # | Requirement | Before | Now | Implemented in | Note |
|---|---|---|---|---|---|
| 1.1 | One shared battery core, four consumers | PARTIAL | DONE | `battery_core/core.py`, `context.py`, `fleet/` | Assistant, planner, companion and fleet all call `BatteryCore`. `test_only_the_core_owns_soh_and_ageing_logic` fails if any other module imports the SOH, ageing or degradation code. |
| 1.2 | Inputs: telemetry, charging history, weather & traffic, station data | PARTIAL | DONE | `telemetry.py`, `inputs/`, `data/charging_history.csv`, `routing/network.py` | |
| 2.1 | OSM Karnataka road graph with chargers | DONE | DONE | `data_gen/osm_fetch.py`, `build_osm_network.py`, `gen_demo_chargers.py` | 39,755 nodes; 37 OSM chargers + 56 seeded demo chargers (6 anchor intercity destinations OSM leaves empty). |
| 2.2 | Synthetic NASA/CALCE-style cells, trips, owner, charging (and fleet) data, one command | DONE | DONE | `data_gen/generate_all.py` | Every generator was re-run during this work. |
| 2.3 | Simulated OBD-II/CAN telemetry stream | MISSING | DONE | `telemetry.py` | `TelemetrySource` interface; `ObdDongle` hardware stub raises; `SimulatedCanBus` emits 1 Hz frames. Exposed at `/api/companion/telemetry`. |
| 2.4 | Weather / traffic / availability behind an interface; live weather allowed | MISSING | DONE | `inputs/__init__.py`, `api/sim.py` | Open-Meteo live weather (no key, offline fallback); simulated rush-hour traffic and charger queues/outages. |
| 3.1 | SOH MLP, 10 BMS features, split by cell, held-out error | PARTIAL | DONE | `battery_core/soh_model.py`, `training/train_soh.py` | 65/15/20 train/val/test by cell. Test cells: MAE 0.73 %-points SOH, MAPE 0.96% (`eval.run_all`). |
| 3.2 | Personalised range MLP from the owner's history; usable × SOH ÷ Wh/km; brochure range exposed | PARTIAL | DONE | `battery_core/range_model.py`, `training/train_range.py` | Fleet MLP fine-tuned on the owner's trips. On held-out owner trips MAE goes from 10.5 to 9.1 Wh/km (MAPE 7.7% → 6.4%). `naive_km` is the brochure figure. |
| 3.3 | RUL / degradation projection for the 2-year resale by habit | PARTIAL | DONE | `battery_core/degradation.py`, `core.rul/project_soh` | Years to 70% SOH. Feeds resale, the Battery screen, the fleet and the charging-habit slider. |
| 3.4 | Shapley attribution | DONE | DONE | `battery_core/attribution.py` | Exact over 5 factors; a test checks the factors sum to the total. |
| 3.5 | Battery guard: one function, allow / modify / refuse + reason + proposed stop | PARTIAL | DONE | `battery_core/guard.py` (`check`) | |
| 3.6 | Weights + scalers saved; inference without retraining | DONE | DONE | `models/*.pt` | `models/` is gitignored; the train scripts recreate it. |
| 4.1 | OSM routing, energy-aware edge costs | DONE | DONE | `routing/planner.py` | |
| 4.2 | Stop insertion: health, arrival charge, availability/queue, charge time, ₹ cost | PARTIAL | DONE | `routing/planner.py`, `inputs/` | Queue wait is part of the A* cost; chargers that are out of service are skipped. |
| 4.3 | Output fields + polyline | DONE | DONE | `planner._summarize` | Also traffic delay and wait time now. |
| 4.4 | Re-planning when a detour is added | BROKEN | DONE | `planner.plan` (waypoint retry) | Regression test at 46% charge; checked at 25–90%. |
| 4.5 | Honest about RL | MISSING | DONE | `README.md` §6 | "Graph search with learned energy costs; RL is not implemented." |
| 5.1 | faster-whisper STT, Piper TTS | DONE | DONE | `assistant/stt.py`, `tts.py` | Whisper on CUDA (RTX 4050) transcribes the question in 0.5 s; Piper synthesises it in 1.4 s. |
| 5.2 | Ollama `qwen3.5:4b`, tool calling, router to core / planner / companion / fleet | PARTIAL | DONE | `assistant/*`, `get_fleet_status` | 16 tools. |
| 5.3 | Rule-based fallback, tested explicitly | PARTIAL | DONE | `fallback_parser.py`, `tests/test_pipeline.py` | End-to-end tests with Ollama down and with Ollama crashing; 17/17 in the evaluation. |
| 5.4.1 | Context-aware command ("nearest McD") checked by the guard | DONE | DONE | `router.t_navigate_to`, `pipeline.py` | When the LLM picks only a lookup for a clear command, the command now wins. |
| 5.4.2 | Feasibility query with shortfall + proposed stop | DONE | DONE | `router.t_check_range_to` | The proposed stop is now the stop the offer actually takes. |
| 5.4.3 | Proactive nudges: loop + UI | DONE | DONE | `nudges.py`, `main._nudge_loop`, UI toast, Home card | |
| 5.4.4 | Mid-drive re-planning | BROKEN | DONE | see 4.4 | |
| 5.4.5 | Range-drop attribution question | DONE | DONE | `router.t_explain_range` | |
| 5.4.6 | Eco-driving coaching from telemetry | MISSING | DONE | `companion/eco.py`, `get_eco_driving_coaching`, Ownership screen | Harsh brakes/accelerations per 100 km; km gained by driving smoothly comes from the core. Includes a nudge after a harsh drive. |
| 5.5 | No action without the guard, with a test | PARTIAL | DONE | `router.ACTION_TOOLS`, `tests/test_guard.py` | Each action tool consults `guard.check`; a refusal changes nothing; an action that returns no verdict raises. |
| 6.1 | Companion screens: Chat, Trip, Battery, Ownership, Simulator | PARTIAL | DONE | `frontend/src/App.jsx`, `screens/`, `components/SimDock.jsx` | Home, Trip, Volt (chat), Battery, Ownership; the Simulator is the dock beside the phone. |
| 6.2 | Trip: map route, range ribbon, stop card, ETA/arrival/cost, suggested prompts | PARTIAL | DONE | `screens/Navigate.jsx`, `components/RangeRibbon.jsx`, `screens/Volt.jsx` | |
| 6.3 | Battery screen | DONE | DONE | `screens/Battery.jsx` | Plus years to 70%. |
| 6.4 | Ownership screen | DONE | DONE | `screens/Insights.jsx` | Plus a "Your driving" section. |
| 6.5 | Simulator incl. charging habit, live range / SOH / projection | PARTIAL | DONE | `SimControls.jsx`, `api/sim.py`, `context.fast_share` | The charging-habit slider drives RUL and the projection. Range responds to temperature, AC, style and load. The SOH estimate itself comes from the BMS log, so it doesn't move with the sliders (projected SOH does). |
| 6.6 | Fleet: allocation, demand model, charging-aware long rentals, rebalancing, longevity metric, UI | MISSING | DONE | `app/fleet/`, `training/train_demand.py`, `api/fleet.py`, `screens/FleetConsole.jsx` | |
| 7 | One evaluation command → `results/metrics.md` | MISSING | DONE | `backend/eval/run_all.py`, `results/` | |
| 8.1 | `AUDIT.md` | MISSING | DONE | this file | |
| 8.2 | Fresh clone runs from the README | PARTIAL | DONE on this laptop | `README.md`, `run.txt` | Every README step (install, generate, train, tests, eval, frontend build) ran on the development laptop. A clean-clone run was skipped at the owner's request (see "Fresh-clone check"). |
| 8.3 | `DEMO_SCRIPT.md` | MISSING | DONE | `DEMO_SCRIPT.md` | Rehearsed through the API with the LLM and with the rule-based fallback. |

## What I added

One commit per gap on `audit-and-gaps`. The first two commits put this session's earlier, uncommitted
work (routing choices, demo chargers, phone-app UI) on the branch before the audit.

| Gap | Commit | What changed |
|---|---|---|
| 4.4 / 5.4.4 detour broken | `cc92dbd`, `10c97f8` | When a later leg can't be planned, the previous leg is re-planned to arrive with enough charge for it (plus a rounding margin). Regression test. |
| 3.5 / 5.5 single guard | `d3eaef4` | `guard.check()` returns an allow/modify/refuse verdict, a reason and a proposed stop; every action tool calls it; the router rejects actions without a verdict; `tests/test_guard.py`. |
| 5.3 fallback test | `07b9581` | End-to-end pipeline tests with Ollama down and with Ollama crashing. |
| 3.1 SOH split | `1ad2b66` | Train/val/test by cell; MAE and MAPE on the held-out test cells. |
| 3.2 personalised range | `3966e23` | The owner data carries a vehicle quirk; the fleet MLP is fine-tuned on the owner's trips and the core loads the personal model. |
| 3.3 RUL in core | `9192fb8` | `battery_core/degradation.py`; `BatteryCore.project_soh()` / `rul()`; resale calls the core. |
| 2.4 / 4.2 inputs | `ba62974` | Live weather (Open-Meteo), simulated traffic and charger queues/outages behind providers; the planner weighs queues and outages; the simulator gets a live-weather button. |
| 2.3 / 5.4.6 telemetry + eco | `96edc97` | Simulated CAN bus, harsh-event detection, eco coaching tool, nudge and UI. |
| 6.6 fleet backend | `f1d5461` | Fleet data generator, demand MLP, allocation, rebalancing, round-trip rental plans, one-year longevity, `/api/fleet/*`, Volt tool, architecture test. |
| 6.6 fleet UI | `7c367e3` | Fleet console with a driver/fleet switch. |
| 6.1 / 6.2 / 6.5 companion | `2717cb4` | Deck tab names, range ribbon on Trip, charging-habit slider. |
| 5.4.1 LLM tool choice | `ba93f09` | A clear command overrides an LLM lookup ("Take me to Mysuru" had been answered with a range check). |
| 7 evaluation | `5ae21c5` | `python -m eval.run_all` → `results/metrics.md`. |
| 5.4.2 consistency, README | `40790b5` | The range check names the stop its offer takes; README rewritten for the whole system, including the RL note (4.5). |
| 8.3 demo script | `25201ef` | `DEMO_SCRIPT.md`; `run.txt` updated. |

## Headline results (`results/metrics.md`)

- **SOH**: 0.73 %-points MAE (0.96% MAPE) on 7 unseen cells.
- **Range**: 6.4 Wh/km MAE (4.2% MAPE) fleet-wide. On held-out owner trips, the personalised model scores 9.1 Wh/km against the fleet model's 10.5.
- **Routing** (108 trips at 34 °C with AC):
  - the battery-aware planner strands 0% of trips, against 14.8% for a static brochure-range router;
  - 10.2% of the baseline's trips arrive below the reserve;
  - on trips both completed, the planner is about 5 minutes faster.
- **Assistant**: 17/17 tasks through the local LLM (median 3.6 s, p95 6.3 s, RTX 4050 Laptop GPU) and 17/17 through the fallback (median 0.05 s).
- **Fleet**:
  - health-aware allocation loses capacity 1.4× more slowly than first-available (**+40% battery life**), with 897 fewer fast charges a year;
  - the demand model is 33% closer to the true booking rate than a zone-and-hour average.

## Known limitations

These are documented in the README.
- All battery, owner and fleet data is synthetic.
- The routing and fleet comparisons are simulations.
- Hardware features are stubs.
- Charging-stop selection is graph search, not RL.
- On its own, the demand model doesn't beat the average baseline against *noisy hourly counts* (0.869 vs 0.861). It is better against the true rate and in rainy hours; both comparisons are reported.

## Fresh-clone check

Not done. The owner decided that running on the development laptop is enough. A clean-clone run was
started, got through package installation, and was stopped during data generation. Every README step
has run successfully on the development laptop, but a brand-new clone has not been tested end to end.
