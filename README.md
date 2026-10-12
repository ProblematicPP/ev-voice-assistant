# Volt: a battery-grounded voice assistant for EVs (prototype)

**Project page:** https://problematicpp.github.io/ev-voice-assistant/

A single-vehicle, single-owner voice assistant whose every navigation/charging/energy action is checked
against a **battery-intelligence core** (PyTorch SOH + personalized range models) before it executes.
Everything runs locally on synthetic data: no API keys, no cloud.

```
Voice (browser mic) ─► faster-whisper (STT) ─► local LLM via Ollama (intent + tool call)
        ─► function router ─► BATTERY GUARD ─► battery core / route planner / companion logic
        ─► LLM phrases reply from tool facts ─► Piper text-to-speech (spoken + shown in the UI)
```

If Ollama isn't running, a rule-based intent parser takes over, so the demo never dead-ends.

---

## 1. Prerequisites (Windows)

| Tool | Version | Install |
|---|---|---|
| Python | **3.12** (not 3.14: some wheels lag) | `uv` fetches it for you (below), or python.org |
| uv | any recent | `pip install uv` |
| Node.js | 18+ (tested on 24) | nodejs.org |
| Ollama | latest | `winget install Ollama.Ollama` or https://ollama.com/download |

ffmpeg is **not** required (audio decoding uses PyAV, bundled with faster-whisper).
An NVIDIA GPU is optional; it is used automatically when present (see GPU use below).

## 2. Backend setup

```powershell
cd backend
uv venv --python 3.12 .venv
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
uv pip install --python .venv\Scripts\python.exe torch --index-url https://download.pytorch.org/whl/cpu

# Download the Karnataka OpenStreetMap extract (~130 MB, once), build the road graph,
# generate the synthetic battery/owner data (~6-8 minutes total), then train both models
.venv\Scripts\python.exe -m data_gen.generate_all
.venv\Scripts\python.exe -m training.train_soh
.venv\Scripts\python.exe -m training.train_range

# Tests (20 tests: planner, guard, attribution, parser, LLM plumbing with a mocked Ollama)
.venv\Scripts\python.exe -m pytest -q
```

## 3. Local LLM (Ollama)

```powershell
ollama pull qwen3.5:4b      # ~3.3 GB, fits the RTX 4050's 6 GB VRAM with room for Whisper
ollama serve                # usually already running as a background service after install
```

`qwen3.5:4b` has native tool calling; the backend disables its "thinking" mode for fast replies.
To use another model, e.g. `qwen2.5:7b`, set `$env:OLLAMA_MODEL = "qwen2.5:7b"` before starting the
backend. The backend warms the model up at startup, because the very first call compiles CUDA kernels
and can take over a minute.

Measured on an RTX 4050 laptop: the LLM generates ~43 tokens/s, a full assistant turn (tool choice,
guarded execution, phrased reply) takes ~4 s, and GPU speech-to-text takes ~0.5 s.

## 4. Run

Two terminals:

```powershell
# Terminal 1: backend (API on :8000)
cd backend
.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000

# Terminal 2: frontend (UI on :5173; proxies /api to the backend)
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. API docs: http://localhost:8000/docs. The header shows whether the LLM is
connected or the assistant is in rule-based mode.

On first start the backend downloads the Whisper `small.en` model (~480 MB) and the Piper voice
`en_US-lessac-medium` (~60 MB) once, then preloads both in the background.

### GPU use

| Component | Device | Why |
|---|---|---|
| LLM (Ollama) | **GPU** automatically | Ollama detects CUDA itself; the 7B model fits in 6 GB VRAM |
| Speech-to-text (faster-whisper) | **GPU** if available, else CPU | `WHISPER_DEVICE=auto` tries CUDA float16 first and falls back to CPU int8. CUDA libraries come from pip (`nvidia-cublas-cu12`, `nvidia-cudnn-cu12`, in requirements.txt) and are registered at runtime by `app/gpu.py` |
| Text-to-speech (Piper) | CPU | Already much faster than real time; GPU would need `onnxruntime-gpu` for no audible gain |
| SOH / range models (PyTorch) | CPU | Tiny MLPs (5-7k parameters each): a GPU is *slower* here because copying each small batch to the card costs more than the maths. Training takes seconds on CPU |

Overrides: `$env:WHISPER_DEVICE = "cpu"` to force CPU, `$env:WHISPER_MODEL = "base.en"` for a smaller model.
`/api/health` reports which device Whisper actually loaded on.

## 5. Demo script (works in rule-based mode too)

| Say / do | Shows |
|---|---|
| "Will I make it to Mysore without stopping?" | Range query on the real 148 km road route → "no, ~48 km short", proposes a stop |
| "Yes" | AI route determiner: picks a real OSM charger (Magenta ChargeGrid), charges only to what's needed; route drawn on the map |
| Demo controls → **+30 km** | Simulated drive along the route |
| "Also stop at a McDonald's on the way" | Mid-drive re-plan: picks the detour-minimising McD, adds a charger if needed |
| Scenario **Road trip, 74% charge** → "Take me to Mysuru" → **+30 km** → set 40 °C and AC | Direct trip (arrive 16%) becomes unsafe → proactive nudge → "yes" re-plans with a short top-up |
| Scenario **Low battery, far from home** | Nudge: "18% left, 55 km from home - route via a charger?" |
| "Why is my range lower than usual?" | Shapley range-drop attribution (AC, heat, style, load, ageing) |
| "Take me to the nearest McD" | Context-aware command, range-checked before confirming |
| Scenario **Hot day, plugged in** → "yes" | Predictive pre-cooling **stub** (grid power, guard-checked) |
| "Show the left turn camera" | Assisted-driving **stub** |
| "How are my charging habits?" / "Cost per km and resale?" | Companion coaching, cost, SOH-driven resale |

## 6. Project layout

```
backend/
  app/
    battery_core/   ① Battery-Intelligence Core
      nn.py           PyTorch MLP regressor (shared)
      soh_model.py    SOH from 10 BMS features
      range_model.py  Wh/km model → personalized range
      attribution.py  exact Shapley range-drop explanation
      guard.py        feasibility checks every action must pass
      ageing.py       semi-empirical ageing model (data synthesis + SOH projection)
      core.py         BatteryCore facade other modules call
    routing/        OpenStreetMap road graph, energy-aware planner, mid-drive re-planner
    assistant/      ② STT, Ollama client, tool schemas, router, fallback parser, nudges, pipeline
      stubs/          assisted_driving.py, precooling.py: HARDWARE STUBS (future phase)
    companion/      ③ coaching, cost per km, resale estimate
    api/            FastAPI routers + WebSocket hub
    simulation.py   demo drive simulation
  data_gen/         osm_fetch.py + build_osm_network.py (real map), synthetic battery/owner data
                    generators (physics.py = ground truth for synthesis only)
  training/         train_soh.py, train_range.py
  data/, models/    generated outputs
  tests/
frontend/src/       React UI: assistant, range ribbon, route map, battery, companion, demo controls
```

## 7. Map data (OpenStreetMap)

`data_gen/osm_fetch.py` downloads the Karnataka extract from openstreetmap.fr, and
`data_gen/build_osm_network.py` turns it into a routing graph: major roads split at intersections,
speeds from `maxspeed` or road class (reduced inside Bengaluru for traffic), the largest connected
component kept, and towns, Bengaluru suburbs, the airport, car chargers (scooter and battery-swap
networks excluded) and POIs snapped to the nearest road. The UI draws it on OpenStreetMap tiles with
Leaflet; tiles need internet, routing does not.

Map data © OpenStreetMap contributors, available under the
[Open Database License](https://www.openstreetmap.org/copyright).

## 8. Datasets

| File | Rows | Purpose |
|---|---|---|
| `cell_cycles.csv` | ~30k cycles, 36 cells | NASA/CALCE-shaped ageing data → SOH model (split by cell) |
| `cell_timeseries.csv` | ~5k | raw V/I/T/SOC traces for sample cycles (illustrative) |
| `trips.csv` | 24k | trip segments with temp, HVAC, style, speed, gradient, load → Wh/km model |
| `vehicle_bms_history.csv` | ~750 cycles | the demo car's BMS log since purchase → current SOH |
| `owner_trips.csv`, `charging_history.csv` | 90 days | personalization (driving style, highway share), coaching, cost |
| `network.json` | 39,755 nodes, 49,435 km | **Real** Karnataka roads (motorway to secondary), 1,379 places, 37 car chargers, 371 POIs from OpenStreetMap |

Model results (held-out): SOH MAE ≈ 0.55 % SOH (R² 0.99); range MAPE ≈ 4.2 % (≈ the 5 % noise put into
the data). These numbers describe fit to *synthetic* data, not real-world accuracy.

## 9. Honest limitations

- All data is synthetic; the physics used to synthesize it is simplified.
- Assisted driving and pre-cooling are logging stubs, not vehicle integrations.
- Roads, places and charger locations are real (OpenStreetMap), but OSM maps only 37 car chargers in
  Karnataka and gives power/price for almost none: those values are estimated and flagged in the UI.
  Long trips (e.g. Bengaluru to Hubballi) can be reported unreachable because of these mapping gaps.
- Road speeds are estimated from road class and city traffic; OSM has no elevation, so hills are ignored.
- Voice replies use one English Piper voice; there is no Indian-English Piper voice yet.
