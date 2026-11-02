# Evaluation results

Generated 2026-11-02 10:46 by `python -m eval.run_all`. Hardware: GPU NVIDIA GeForce RTX 4050 Laptop GPU, 6141 MiB.

## 1. SOH and range accuracy (held-out data)

| Model | Held-out set | MAE | MAPE |
|---|---|---|---|
| SOH MLP (10 BMS features) | 7 unseen cells (5965 cycles) | 0.73 %-points SOH | 0.96% |
| Range MLP, fleet | 4769 unseen trip segments | 6.4 Wh/km | 4.2% |
| Range MLP, fleet model on owner's trips | 54 held-out owner trips | 10.5 Wh/km | 7.7% |
| Range MLP, personalised (fine-tuned) | same 54 trips | 9.1 Wh/km | 6.4% |

### SOH on real batteries (NASA PCoE ageing data)

Same 10 BMS features, computed from the measured signals of real 18650 cells; SOH = measured capacity / 2.0 Ah. No cell is in both the training and test side.

| Held-out real cells | MLP trained on real cells | Synthetic model fine-tuned on real | Synthetic model, unchanged | Cycle count only | Average SOH |
|---|---|---|---|---|---|
| Classic 4 cells (B0005/6/7/18), leave-one-cell-out (579 cycles) | 2.74 pts (3.6%) | 3.46 pts (4.6%) | 15.20 pts (20.8%) | 4.23 pts (5.5%) | 7.92 pts (10.3%) |
| All 34 cells, 5 folds by cell (2459 cycles) | 6.56 pts (10.7%) | 7.60 pts (12.6%) | 17.25 pts (30.4%) | 12.37 pts (20.4%) | 12.43 pts (20.3%) |

MAE in SOH percentage points (MAPE in brackets). The method works on real cells; the app's synthetic-trained weights do not transfer to them, so a real deployment must train on real data.

## 2. Route and charging-stop efficiency

108 trips (3 Bengaluru origins x 9 destinations x 4 starting charges), 34 °C, AC on, current battery health. The baseline routes the fastest way and trusts the brochure range (312 km); both are scored with the same energy model, so this measures the value of being battery- and condition-aware inside the simulation.

| | Battery-aware planner | Static brochure-range baseline |
|---|---|---|
| Trips stranded (battery empty) | 0.0% | 14.8% |
| Arrived below the 10% reserve | 0.0% | 10.2% |
| Refused as infeasible (nearest charger offered) | 0.0% | 0% (it just drives) |
| Avg trip time, trips both completed (n=92) | 123 min | 103 min |
| Avg charging stops, same trips | 0.27 | 0.20 |

## 3. Assistant task success and latency

17 prompts covering every tool, run end to end through the pipeline (intent -> guard -> router -> reply).

| Path | Success | Median latency | p95 latency |
|---|---|---|---|
| Local LLM (Ollama, qwen3.5:4b) | 100% (17 prompts) | 3.84 s | 6.71 s |
| Rule-based fallback (no LLM) | 100% (17 prompts) | 0.01 s | 0.34 s |

Voice: Piper synthesised a 2.1 s question in 2.80 s; faster-whisper on cuda transcribed it in 1.08 s (heard: "Will I make it to Mysore without stopping?").

## 4. Fleet battery longevity

One simulated year (365 days) of rentals on the 40-car fleet, same bookings for both policies.

| | Health-aware allocation | First available car |
|---|---|---|
| Capacity lost (avg, %-points) | 4.40 | 6.17 |
| Average SOH after a year | 78.9% | 77.1% |
| Packs below 70% after a year | 11 | 13 |
| Mid-trip fast charges | 3,004 | 3,901 |

**Estimated battery-life extension: +40.2%** (capacity is lost 1.40x more slowly).

Demand forecast (last 21 days held out): 0.113 bookings/zone-hour from the true rate vs 0.169 for a zone-and-hour average; against noisy observed counts 0.869 vs 0.861.
Rebalancing (3-hour horizon): 08:00 expected missed rentals 27.11 -> 24.61 (9% fewer, 8 moves); 18:00 expected missed rentals 32.80 -> 30.71 (6% fewer, 8 moves).

All data is synthetic (see README). The routing and fleet comparisons are simulations, not field trials.
