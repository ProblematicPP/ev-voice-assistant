# Final-review demo (5 minutes)

Order: Trip tab Mysore query → proactive nudge → mid-drive detour → Battery tab → Ownership tab → Fleet module.

Prompts are shown in **bold quotes**: say them with the mic button on the Volt screen, or type them.
Clicks are in *italics*. "Simulator" means the panel to the right of the phone.

## Before the panel arrives (5 minutes ahead)

1. Start Ollama, then the backend and frontend (README section 3). Wait about 60 s after the backend starts:
   it loads Whisper and Piper and warms up the LLM. Before that, the first reply can take a minute.
2. Open http://localhost:5173. In the Simulator's System section check: Backend *Connected*,
   Assistant *LLM (qwen3.5:4b)*.
3. *Simulator → Reset*. The car starts at Koramangala (home), 46% charge, 34 °C, AC on.
4. Click once anywhere on the page so the browser allows spoken replies.
   Check the speaker icon on the Volt screen is on.
5. Optional dry run: ask **"How much charge do I have left?"**, then *Reset* again.

## The demo

| # | Time | Do / say | What the panel should see |
|---|---|---|---|
| 1 | 0:00 | *Bottom bar → Trip*. Point out the range ribbon: about 79 km for today's heat, AC and this battery's health, against a 144 km brochure estimate. | One battery core: personalised range, not a fixed km-per-percent. |
| 2 | 0:20 | *Volt (centre button)* → **"Will I make it to Mysore without stopping?"** | "No… 148 km away… run out about 66 km short. A ~32-minute stop at *<charger>* fixes it. Want me to start that route?" |
| 3 | 0:45 | **"Yes"** | The app opens Trip: the route on real OSM roads, the orange charging stop, a total of about 3 h 10 min, about 15% on arrival, the ₹ cost, and the ribbon marking the stop and destination. |
| 4 | 1:15 | *Simulator → Drive forward +30 km.* Then set *Outside temperature 44 °C* and *Load 300 kg*. | **Proactive nudge**, unprompted and spoken: "Heads up: at 44 °C with AC on, you'd reach Mysuru at 7%… below the safe reserve. Re-plan with a charging stop?" It shows as a pop-up and on Home with Yes / Not now. |
| 5 | 1:45 | **"Yes"** (or tap the Yes button) | Re-plans from the current position with an extra top-up. The battery guard's verdict is shown in Simulator → *Last assistant turn* (`guard: modify`). |
| 6 | 2:10 | **"Also stop at a McDonald's on the way."** | **Mid-drive detour**: a McDonald's on the way is added and charging is recalculated. The green stop marker appears on the map. |
| 7 | 2:40 | *Bottom bar → Battery.* | SOH ≈ 77%, from the model reading a **real** battery's log (NASA cell B0007, never trained on); the simulator panel shows the lab-measured 87.5% beside it. Also usable kWh, cycles, % fast charging, years until 70%, the SOH trend, and the "Why 79 km and not 178 km" Shapley bars. |
| 8 | 3:00 | **"Why is my range lower today?"** | The answer quotes the same Shapley breakdown (AC, battery ageing, heat, driving style). |
| 9 | 3:20 | *Bottom bar → Ownership.* Then drag *Simulator → Charging habit* from about 30% to 80% fast. | ₹/km vs petrol and the monthly saving, driving and charging coach tips, and resale value. The 2-year projection ("Your current habit") and Battery's years-to-70% change live with the slider. |
| 10 | 3:50 | Optional: **"Am I braking too hard?"** | Eco-driving coaching from the simulated CAN telemetry: harsh brakes per 100 km and km gained by driving smoothly. |
| 11 | 4:05 | *Top switch → Fleet console.* | Demand heatmap (morning and evening peaks, airport busy round the clock), suggested moves with missed rentals saved, health-aware allocation: **11 cars below 70% after a year instead of 17**, about 6% slower battery ageing, and today's bookings (long trips get the healthiest packs). |
| 12 | 4:35 | *Today's bookings → Route* on a long trip (e.g. B013 to Hassan). | Round-trip rental plan on the same charging-aware planner, using that car's own battery health. |
| 13 | 4:50 | Close with `results/metrics.md` if asked for numbers. | Battery health on 7 unseen **real** cells: 4.8 points MAE. 0% vs 23% stranded against the brochure-range router. Assistant 17/17 tasks at ~3.5 s median. Fleet: 11 vs 17 cars below 70%. |

## Things that can misbehave, and what to do

| Symptom | Why | Fallback |
|---|---|---|
| The first reply takes a minute | The LLM is still warming up | Start 5 minutes early. If it happens live, keep talking over it. The reply always arrives. |
| One reply takes 20-30 s (seen once on "Yes" during rehearsal) | Occasional slow LLM turn on the laptop GPU | Wait, or switch to rule-based mode (next row). |
| The LLM is generally slow, or answers oddly | 4B model variance | *Quit Ollama from the tray*. Within ~20 s Volt switches to the rule-based parser: same tools, same guard, replies in about 0.1 s. Every prompt in this script works in that mode (tested). The Simulator's System line shows which mode is active. |
| The voice hears "Well I make it…" instead of "Will I make it…" | Whisper on a short clip | The LLM still understands it. In rule-based mode, type the prompt instead. |
| The charger named in step 2 differs from rehearsal | Simulated charger queues change by the hour, so the planner may pick a less busy one | Expected behaviour; the answer and the route always name the same charger. |
| No nudge in step 4 | The projected arrival must fall below 10% | Also set *Driving style* to about 0.9, or lower *Charge* by a few %. |
| Map is grey, but the route line and markers show | Map tiles need internet | Routing is offline; mention it. Use a phone hotspot if needed. |
| No spoken replies | The browser blocks audio until the page is clicked | Click the page once; check the speaker icon on the Volt screen. |
| Fleet "Battery life" says "Simulating…" | The first load runs a one-year simulation (~6 s) | Open the Fleet console once before the panel arrives. |
| Something got into a strange state | | *Simulator → Reset*, then restart from step 2. Scenarios also reset everything. |
| A panel member notices Battery says 77% but the simulator says the lab measured 87.5% | That's the model's real error on a battery it never trained on | Say so: the model estimates 4.8 points off on average across 7 unseen real cells, and this cell is one of its harder ones (it underestimates it). A real car only ever shows the estimate. |

Backup if the backend dies: restart it (`uvicorn app.main:app --port 8000`). It takes about 30 s to warm up, and the UI reconnects by itself.
