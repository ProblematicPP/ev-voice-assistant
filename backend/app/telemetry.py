"""Vehicle telemetry: a simulated OBD-II / CAN stream and harsh-event detection.

TelemetrySource is the interface. Two implementations:
  ObdDongle        HARDWARE-DEPENDENT STUB. A real build would read PIDs (speed 0x0D,
                   etc.) from an ELM327/CAN dongle. Not implemented - raises.
  SimulatedCanBus  1 Hz frames (speed, acceleration, power, SOC, pack temperature)
                   for a stretch of driving. How often harsh accelerations and brakes
                   happen grows with the driving-style score.

detect_events() finds harsh events from the frames alone (acceleration thresholds
used by insurance telematics), so it would work unchanged on real data.
"""
from __future__ import annotations

import numpy as np
from scipy.signal import lfilter

HARSH_ACCEL_MS2 = 3.0        # ~0.3 g
HARSH_BRAKE_MS2 = -3.5       # ~0.36 g
CITY_KMH, HIGHWAY_KMH = 26.0, 75.0


def harsh_rate_per_km(style: float) -> float:
    """Expected harsh events per km: ~1 per 100 km for a smooth driver, ~8 at style 0.62, ~25 at 0.9."""
    return 0.01 + 0.68 * max(0.0, style - 0.3) ** 2


class TelemetrySource:
    source = "abstract"

    def frames(self, km: float, cond: dict, soc0: float, highway_share: float = 0.0, seed: int = 0) -> dict:
        raise NotImplementedError


class ObdDongle(TelemetrySource):
    """HARDWARE STUB: would stream live PIDs from an OBD-II / CAN dongle. Not connected in this project."""
    source = "obd-ii (stub)"

    def frames(self, *a, **k):
        raise NotImplementedError("No OBD-II/CAN dongle in this build - use SimulatedCanBus.")


class SimulatedCanBus(TelemetrySource):
    source = "simulated CAN bus"

    def frames(self, km: float, cond: dict, soc0: float, highway_share: float = 0.0, seed: int = 0,
               wh_per_km: float = 150.0, usable_kwh: float = 36.0) -> dict:
        """Arrays of 1 Hz frames covering `km` of driving."""
        rng = np.random.default_rng(seed)
        mean_kmh = (1 - highway_share) * CITY_KMH + highway_share * HIGHWAY_KMH
        n = max(2, int(km / mean_kmh * 3600))
        style = cond["driving_style"]
        # Smooth stop-and-go speed trace (random walk pulled toward the mean speed)
        # v[t] = 0.98 v[t-1] + 0.02 mean + a[t]  (AR(1), vectorised with lfilter)
        shocks = np.clip(rng.normal(0, 0.45 + 0.6 * style, n), -2.6, 2.4)   # normal driving stays under harsh
        drive = shocks + 0.02 * mean_kmh / 3.6
        speed = np.maximum(0.0, lfilter([1.0], [1.0, -0.98], drive, zi=[0.98 * mean_kmh / 3.6])[0])
        accel = np.diff(speed, prepend=mean_kmh / 3.6)
        # Inject harsh manoeuvres at a rate set by driving style
        k = rng.poisson(harsh_rate_per_km(style) * km)
        at = rng.choice(n, size=min(k, n), replace=False)
        brakes = rng.random(len(at)) < 0.6
        accel[at] = np.where(brakes, rng.uniform(-6.0, -3.6, len(at)), rng.uniform(3.1, 4.5, len(at)))
        dist_km = np.cumsum(speed) / 1000
        dist_km *= km / dist_km[-1] if dist_km[-1] > 0 else 1.0
        soc = soc0 - dist_km * wh_per_km / 1000 / usable_kwh
        power_kw = np.clip(speed * 3.6 * wh_per_km / 1000 + 0.012 * accel * speed * 3.6, -40, 120)
        pack_temp = cond["ambient_temp_c"] + 4 + np.cumsum(np.abs(power_kw)) / n / 6
        return {"t_s": np.arange(n), "speed_kmh": speed * 3.6, "accel_ms2": accel, "power_kw": power_kw,
                "soc": soc, "pack_temp_c": pack_temp, "odometer_km": dist_km, "source": self.source}


def detect_events(frames: dict) -> list[dict]:
    a, out = frames["accel_ms2"], []
    for i in np.flatnonzero((a >= HARSH_ACCEL_MS2) | (a <= HARSH_BRAKE_MS2)):
        out.append({"type": "harsh_brake" if a[i] < 0 else "harsh_accel", "accel_ms2": round(float(a[i]), 2),
                    "speed_kmh": round(float(frames["speed_kmh"][i]), 1), "km": round(float(frames["odometer_km"][i]), 2)})
    return out


def summarize(events: list[dict], km: float) -> dict:
    brakes = sum(e["type"] == "harsh_brake" for e in events)
    accels = len(events) - brakes
    per100 = lambda x: round(100 * x / km, 1) if km else 0.0
    return {"km": round(km, 1), "harsh_brakes": brakes, "harsh_accels": accels,
            "harsh_brakes_per_100km": per100(brakes), "harsh_accels_per_100km": per100(accels),
            "events_per_100km": per100(len(events))}


def downsample(frames: dict, keep: int = 120) -> list[dict]:
    """Last `keep` frames at an even stride, for the UI."""
    n = len(frames["t_s"])
    idx = np.linspace(max(0, n - keep * 10), n - 1, min(keep, n)).astype(int)
    keys = ("speed_kmh", "accel_ms2", "power_kw", "soc", "pack_temp_c")
    return [{k: round(float(frames[k][i]), 3) for k in keys} for i in idx]
