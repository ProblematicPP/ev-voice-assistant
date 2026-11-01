# AI for Optimizing EVs: Volt and the battery-intelligence core

Final-year project, Dept. of AIML, AMC Engineering College.
**Project page:** https://problematicpp.github.io/ev-voice-assistant/

![Trip screen: a Bengaluru to Mysuru route on real OpenStreetMap roads, with an automatically chosen charging stop and the range ribbon](docs/images/trip.png)

One shared **battery-intelligence core** (PyTorch SOH, personalised range, RUL, Shapley range attribution
and a battery guard) feeds four consumers:

```
Voice assistant "Volt" ──┐
Companion app ───────────┤──► Battery-Intelligence Core  (backend/app/battery_core)
Route & charging planner ┤      SOH model · personalised range model · RUL / degradation
Fleet management ────────┘      Shapley attribution · battery guard (every action passes it)

Fed by: simulated OBD-II/CAN telemetry, charging history, weather (live Open-Meteo or simulated),
        simulated traffic and charger availability, OpenStreetMap chargers + demo chargers
```

Everything runs locally, with no API keys and no paid services. Live weather is optional and falls back
to the simulator offline. All battery, owner and fleet data is synthetic; roads, places and most charger
locations are real (OpenStreetMap).

A Volt turn:
```
mic ─► faster-whisper (STT, GPU) ─► Ollama qwen3.5:4b (tool call)  ── or the rule-based parser if Ollama is down
    ─► function router ─► battery guard ─► core / planner / companion / fleet
    ─► LLM phrases the reply from the tool's facts ─► Piper TTS
```

---

## 1. Prerequisites (Windows; macOS/Linux work with the usual path changes)

| Tool | Version | Install |
|---|---|---|
| Python | **3.12** | `uv` fetches it for you (below) |
| uv | any recent | `pip install uv` |
| Node.js | 18+ (tested on 24) | nodejs.org |
| Ollama | latest | `winget install Ollama.Ollama` or https://ollama.com/download |

ffmpeg is not needed. An NVIDIA GPU is optional and is used automatically when present.

## 2. Set up from a fresh clone

```powershell
git clone https://github.com/ProblematicPP/ev-voice-assistant.git
cd ev-voice-assistant\backend

# Python environment
uv venv --python 3.12 .venv
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
uv pip install --python .venv\Scripts\python.exe torch --index-url https://download.pytorch.org/whl/cpu

# Data: downloads the Karnataka OSM extract (~130 MB, once), builds the road graph, places demo
# chargers, and generates cells, trips, owner history and the rental fleet (~6-8 min)
.venv\Scripts\python.exe -m data_gen.generate_all

# Models (about 1 minute in total on CPU). Weights + scalers are saved in backend/models/
.venv\Scripts\python.exe -m training.train_soh       # SOH MLP, split by cell
.venv\Scripts\python.exe -m training.train_range     # fleet Wh/km MLP + owner fine-tune
.venv\Scripts\python.exe -m training.train_demand    # fleet demand forecaster

# Tests (~2 min)
.venv\Scripts\python.exe -m pytest -q

# Local LLM (~3.3 GB)
ollama pull qwen3.5:4b

# Frontend packages
cd ..\frontend
npm install
```

`backend/data/` and `backend/models/` are generated, not committed. Once trained, the app only loads the
saved weights; it never retrains at startup.

## 3. Run

```powershell
# Terminal 1: backend (API on :8000, docs at http://localhost:8000/docs)
cd backend
.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000

# Terminal 2: frontend (UI on :5173, proxies /api to the backend)
cd frontend
npm run dev
```

Open http://localhost:5173. On first start the backend downloads Whisper `small.en` (~480 MB) and the
Piper voice (~60 MB) once, and warms up the LLM (allow ~30-60 s before demoing).

- **Driver app** (the phone): Home, **Trip** (map, route, range ribbon), **Volt** (chat and voice), **Battery**,
  **Ownership**. Screens can be linked directly, e.g. `http://localhost:5173/#battery`.
- **Simulator** (the panel beside the phone, not part of the app): charge, temperature, AC, driving
  style, charging habit, location, one-click scenarios, "drive forward", live weather, system status and
  the last assistant turn (tool, arguments and guard verdict).
- **Fleet console** (switch at the top): demand heatmap, rebalancing moves, both allocation policies,
  round-trip rental routes and the battery-life result.

| Battery | Ownership | Fleet console |
|---|---|---|
| ![Battery screen](docs/images/battery.png) | ![Ownership screen](docs/images/ownership.png) | ![Fleet console](docs/images/fleet.png) |

## 4. Evaluate

```powershell
cd backend
.venv\Scripts\python.exe -m eval.run_all          # full run, ~4 min (needs Ollama for the LLM row)
.venv\Scripts\python.exe -m eval.run_all --quick  # skips the LLM and voice runs
```

This prints a table and writes [`results/metrics.md`](results/metrics.md) (plus `metrics.json`). It covers:

- SOH and range accuracy (MAE and MAPE on held-out cells and trips, fleet vs personalised)
- the battery-aware planner vs a static brochure-range baseline over 108 trips
- assistant task success and latency through the LLM and the fallback, plus voice timings and the GPU
- fleet battery longevity, demand-forecast error and rebalancing

Without an NVIDIA GPU the speech models run on CPU, and the report says so.

## 5. Demo

See [`DEMO_SCRIPT.md`](DEMO_SCRIPT.md) for the 5-minute review sequence and fallbacks.

## 6. How it works

### Battery-intelligence core (`backend/app/battery_core`)

| Piece | What it does |
|---|---|
| `soh_model.py` | MLP on 10 BMS cycle features. Cells split 65/15/20 into train/val/test **by cell**; held-out MAE ≈ 0.7-0.9 %-points SOH |
| `range_model.py` | MLP predicting Wh/km from weather, HVAC, driving style, speed, load and SOH. A fleet model is fine-tuned on the owner's own trips (`range_model_owner.pt`). Range = usable kWh × SOH × SOC ÷ Wh/km; the brochure figure (312 km × SOC) is exposed alongside |
| `degradation.py` | SOH projection and remaining useful life (years to 70%) under a charging habit; drives the 2-year resale projection and fleet longevity |
| `attribution.py` | Exact Shapley values over AC/heater, battery ageing, driving style, temperature and load (32 batched model calls) |
| `guard.py` | `check(action, ...)`: the single gate every action passes. Returns allow / modify / refuse, a reason and, when relevant, a proposed charging stop |
| `core.py` | `BatteryCore`, the only entry point. A test fails if any other module imports the SOH, ageing or degradation code directly |

### Route and charging-stop planner (`backend/app/routing`)

- **Roads:** fastest paths with Dijkstra on the real OSM graph.
- **Energy:** each road edge's kWh comes from the range model under live conditions.
- **Stop search:** charging stops are chosen by A* over (charger, target-SOC) states. A transition is allowed only if arrival charge stays above the safety floor. The cost is driving + charging + queue minutes, with the charge-time taper above 80%.
- **Output:** distance, duration including stops, traffic delay, arrival charge, stop name, charge time, ₹ cost and a polyline.
- **Mid-trip re-planning:** a detour re-plans from the current position.
- **Not reinforcement learning:** the deck cites DQN/RL-style stop selection as related work. This project uses graph search with learned energy costs; RL is not implemented.

### Volt (`backend/app/assistant`)

- **Speech:** faster-whisper STT (GPU when available), Piper TTS (CPU).
- **LLM:** Ollama `qwen3.5:4b` with native tool calling over 16 tools.
- **Safety nets:**
  - The rule-based parser takes over when Ollama is down or fails.
  - When the model answers a clear command in prose, the parser acts on it instead.
  - When the model picks only a lookup for a clear command (e.g. a range check for "take me to Mysuru"), the command wins.
- **Proactive nudges:** checked every 8 s and pushed over the WebSocket, then shown and spoken in the UI. Triggers:
  - a route that is no longer safe
  - low charge far from home
  - pre-cooling on a hot day
  - an unusual range drop
  - harsh braking on the last drive
  - fast charging too often
- **Hardware stubs:** assisted driving, pre-cooling and the OBD-II dongle are stubs, clearly marked in code (`assistant/stubs/`, `telemetry.ObdDongle`).

### Companion and fleet

- **Companion** (`app/companion`): charging coach from the owner's sessions, eco-driving coach from
  telemetry, 30-day cost vs petrol, and resale value with a 2-year projection by charging habit.
- **Fleet** (`app/fleet`):
  - a 40-car synthetic rental fleet, each car's SOH estimated by the core from its own BMS log
  - battery-aware allocation (healthy packs take long trips, worn packs short city rentals)
  - a PyTorch demand forecaster (zone × hour × weather)
  - Poisson rebalancing that estimates missed rentals saved
  - round-trip rental routes on the shared planner
  - a one-year longevity simulation against a first-available baseline

### External inputs (`app/inputs`)

Small provider classes a real API can replace:
- `LiveWeather` uses Open-Meteo (free, no key) and falls back offline.
- `SimulatedTraffic` adds rush-hour delay to ETAs.
- `SimulatedStations` simulates charger queues and outages, which the planner weighs.

## 7. Layout

```
backend/
  app/
    battery_core/   shared core: nn, soh_model, range_model, degradation, attribution, guard, core
    routing/        OSM network, planner, mid-drive re-planner
    assistant/      STT, TTS, Ollama client, tools, router, fallback parser, nudges, pipeline, stubs/
    companion/      charging coach, eco coach, cost, resale
    fleet/          fleet manager + demand model
    inputs/         weather / traffic / charger-availability providers
    telemetry.py    simulated CAN bus + harsh-event detection (OBD-II dongle stub)
    api/            FastAPI routers + WebSocket hub
  data_gen/         OSM download + graph build, demo chargers, synthetic cells/trips/owner/fleet
  training/         train_soh, train_range, train_demand
  eval/             run_all (writes ../results/metrics.md)
  tests/            pytest suite
frontend/src/       React: phone app screens, fleet console, simulator dock
results/            evaluation output
```

## 8. Data

| File | Size | Purpose |
|---|---|---|
| `network.json` | 39,755 nodes | **Real** Karnataka roads, places, 37 OSM car chargers, POIs |
| `demo_chargers.json` | 56 | Seeded demo chargers, labelled as demo in the UI. Six anchor the intercity destinations (Mysuru, Hassan, …) where OSM lists none |
| `cell_cycles.csv` | ~30k cycles, 36 cells | NASA/CALCE-shaped ageing data → SOH model |
| `trips.csv` | 24k segments | fleet Wh/km training data |
| `vehicle_bms_history.csv` | ~770 cycles | the demo car's BMS log → current SOH |
| `owner_trips.csv`, `charging_history.csv` | 90 days | personal range fine-tune, coaching, cost |
| `fleet_*.csv` | 40 cars, 180 days × 24 h × 12 zones | fleet SOH, demand model, bookings |

## 9. Honest limitations

- All battery, owner, trip and fleet data is synthetic, from simplified physics. Accuracy figures describe
  fit to that data, not real-world accuracy. The routing and fleet comparisons are simulations.
- Hardware features (OBD-II/CAN, assisted-driving cameras, pre-cooling) are stubs.
- OSM has few Karnataka car chargers and almost no power/price data. Those values are estimated and flagged,
  and the demo chargers are invented to give the planner choices.
- No elevation data. Traffic and charger queues are simulated.
- Charging-stop selection is graph search, not reinforcement learning.
- One English Piper voice. The 4B LLM occasionally picks a different tool; the safety nets above catch the
  common cases, and every executed action still passes the battery guard.

Map data © OpenStreetMap contributors, [ODbL](https://www.openstreetmap.org/copyright).
Weather from [Open-Meteo](https://open-meteo.com/) (CC BY 4.0).
