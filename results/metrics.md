# Evaluation results

Generated 2026-11-02 11:25 by `python -m eval.run_all`. Hardware: GPU NVIDIA GeForce RTX 4050 Laptop GPU, 6141 MiB.

## 1. SOH and range accuracy (held-out data)

Per held-out cell (SOH points): B0007 6.2, B0027 12.3, B0031 0.7, B0036 3.7, B0043 2.3, B0047 7.1, B0055 4.2. Demo car (replays NASA PCoE cell B0007 (real; held out from SOH training)): estimate 77.1% vs lab-measured 87.5%.

| Model | Held-out set | MAE | MAPE |
|---|---|---|---|
| SOH MLP (shipped), trained on real NASA cells | 7 unseen **real** cells (645 cycles) | 4.77 %-points SOH | 6.52% |
| Range MLP, fleet | 4769 unseen trip segments | 6.4 Wh/km | 4.2% |
| Range MLP, fleet model on owner's trips | 54 held-out owner trips | 10.5 Wh/km | 7.7% |
| Range MLP, personalised (fine-tuned) | same 54 trips | 9.1 Wh/km | 6.4% |

### SOH on real batteries (NASA PCoE ageing data)

Same 10 BMS features, computed from the measured signals of real 18650 cells; SOH = measured capacity / 2.0 Ah. No cell is in both the training and test side.

| Held-out real cells | MLP trained on real cells | Synthetic model fine-tuned on real | Synthetic model, unchanged | Cycle count only | Average SOH |
|---|---|---|---|---|---|
| Classic 4 cells (B0005/6/7/18), leave-one-cell-out (579 cycles) | 3.34 pts (4.4%) | 5.93 pts (7.9%) | 18.62 pts (25.5%) | 4.23 pts (5.5%) | 7.92 pts (10.3%) |
| All 34 cells, 5 folds by cell (2459 cycles) | 7.21 pts (12.0%) | 8.71 pts (13.9%) | 25.76 pts (43.8%) | 12.37 pts (20.4%) | 12.43 pts (20.3%) |

MAE in SOH percentage points (MAPE in brackets). The method works on real cells; the app's synthetic-trained weights do not transfer to them, so a real deployment must train on real data.

## 2. Route and charging-stop efficiency

108 trips (3 Bengaluru origins x 9 destinations x 4 starting charges), 34 °C, AC on, current battery health. The baseline routes the fastest way and trusts the brochure range (312 km); both are scored with the same energy model, so this measures the value of being battery- and condition-aware inside the simulation.

| | Battery-aware planner | Static brochure-range baseline |
|---|---|---|
| Trips stranded (battery empty) | 0.0% | 23.1% |
| Arrived below the 10% reserve | 0.0% | 9.3% |
| Refused as infeasible (nearest charger offered) | 0.0% | 0% (it just drives) |
| Avg trip time, trips both completed (n=83) | 97 min | 92 min |
| Avg charging stops, same trips | 0.27 | 0.14 |

## 3. Assistant task success and latency

17 prompts covering every tool, run end to end through the pipeline (intent -> guard -> router -> reply).

| Path | Success | Median latency | p95 latency |
|---|---|---|---|
| Local LLM (Ollama, qwen3.5:4b) | 100% (17 prompts) | 3.52 s | 5.04 s |
| Rule-based fallback (no LLM) | 100% (17 prompts) | 0.01 s | 0.55 s |

Voice: Piper synthesised a 2.1 s question in 0.13 s; faster-whisper on cuda transcribed it in 0.15 s (heard: "Well I make it to Mysore without stopping.").

## 4. Fleet battery longevity

One simulated year (365 days) of rentals on the 40-car fleet, same bookings for both policies.

| | Health-aware allocation | First available car |
|---|---|---|
| Capacity lost (avg, %-points) | 5.46 | 5.81 |
| Average SOH after a year | 73.0% | 72.6% |
| Packs below 70% after a year | 11 | 17 |
| Mid-trip fast charges | 3,636 | 4,296 |

**Estimated battery-life extension: +6.4%** (capacity is lost 1.06x more slowly).

Demand forecast (last 21 days held out): 0.113 bookings/zone-hour from the true rate vs 0.169 for a zone-and-hour average; against noisy observed counts 0.869 vs 0.861.
Rebalancing (3-hour horizon): 08:00 expected missed rentals 27.25 -> 24.61 (10% fewer, 8 moves); 18:00 expected missed rentals 32.56 -> 30.74 (6% fewer, 6 moves).

All data is synthetic (see README). The routing and fleet comparisons are simulations, not field trials.
