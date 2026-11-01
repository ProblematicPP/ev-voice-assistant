"""External inputs behind small interfaces: weather, traffic and charger availability.

Each provider has a `source` string and one or two methods. The simulated ones work
offline and deterministically; a real API can replace any of them by implementing
the same methods (see LiveWeather for one that does).
"""
from __future__ import annotations

import hashlib
import logging
import time
from datetime import datetime

import httpx

log = logging.getLogger("inputs")


def _hash01(*parts) -> float:
    """Deterministic pseudo-random number in [0, 1) from the given parts."""
    h = hashlib.sha256("|".join(map(str, parts)).encode()).digest()
    return int.from_bytes(h[:8], "big") / 2**64


# -- weather -----------------------------------------------------------------------
WMO = {0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "fog",
       51: "drizzle", 53: "drizzle", 55: "drizzle", 61: "rain", 63: "rain", 65: "heavy rain",
       80: "showers", 81: "showers", 82: "heavy showers", 95: "thunderstorm"}


class SimulatedWeather:
    """Uses whatever temperature the simulator is set to."""
    source = "simulated"

    def current(self, lat: float, lon: float, fallback_temp_c: float) -> dict:
        return {"temp_c": fallback_temp_c, "condition": None, "source": self.source}


class LiveWeather:
    """Open-Meteo current conditions (free, no API key). Falls back to the simulated value offline."""
    source = "open-meteo"
    URL = "https://api.open-meteo.com/v1/forecast"

    def __init__(self, ttl_s: float = 600, timeout_s: float = 4.0):
        self.ttl_s, self.timeout_s = ttl_s, timeout_s
        self._cache: dict = {}

    def current(self, lat: float, lon: float, fallback_temp_c: float) -> dict:
        key = (round(lat, 2), round(lon, 2))
        hit = self._cache.get(key)
        if hit and time.time() - hit[0] < self.ttl_s:
            return hit[1]
        try:
            r = httpx.get(self.URL, timeout=self.timeout_s, params={
                "latitude": lat, "longitude": lon, "current": "temperature_2m,weather_code"})
            r.raise_for_status()
            cur = r.json()["current"]
            out = {"temp_c": float(cur["temperature_2m"]), "condition": WMO.get(int(cur["weather_code"]), "unknown"),
                   "source": self.source}
        except Exception as exc:
            log.info("live weather unavailable (%s), using simulated temperature", exc)
            return {**SimulatedWeather().current(lat, lon, fallback_temp_c), "error": "offline"}
        self._cache[key] = (time.time(), out)
        return out


# -- traffic -----------------------------------------------------------------------
class SimulatedTraffic:
    """Bengaluru-style congestion by hour: city roads slow sharply at rush hour, highways much less.

    factor = travel time multiplier on free-flow OSM speeds.
    """
    source = "simulated"
    CITY = {range(8, 11): 1.55, range(17, 21): 1.7, range(11, 17): 1.2, range(21, 23): 1.1}
    HIGHWAY = {range(8, 11): 1.15, range(17, 21): 1.2}

    def factor(self, when: datetime, urban: bool) -> float:
        table = self.CITY if urban else self.HIGHWAY
        return next((f for hours, f in table.items() if when.hour in hours), 1.0)


# -- charger availability ----------------------------------------------------------
class SimulatedStations:
    """Per-charger queue and outages, stable within an hour, busier at peak times and for city DC chargers.

    status() -> {"available": bool, "wait_min": float}
    """
    source = "simulated"
    OUTAGE_RATE = 0.04

    def status(self, charger: dict, when: datetime) -> dict:
        if charger["kind"] == "home_ac":
            return {"available": True, "wait_min": 0.0}
        slot = when.strftime("%Y-%m-%d-%H")
        if _hash01("outage", charger["id"], when.date()) < self.OUTAGE_RATE:
            return {"available": False, "wait_min": 0.0}
        peak = 1.8 if when.hour in range(8, 11) or when.hour in range(17, 22) else 1.0
        base = 6.0 if charger["kind"] == "dc_fast" else 2.0
        wait = base * peak * _hash01("queue", charger["id"], slot) * 2
        return {"available": True, "wait_min": round(wait, 1)}


class Inputs:
    """The set of providers the app uses; swap any attribute for a real implementation."""

    def __init__(self, weather=None, traffic=None, stations=None, clock=datetime.now):
        self.weather = weather or LiveWeather()
        self.traffic = traffic or SimulatedTraffic()
        self.stations = stations or SimulatedStations()
        self.clock = clock

    def describe(self) -> dict:
        return {"weather": self.weather.source, "traffic": self.traffic.source, "stations": self.stations.source}
