"""Ground-truth vehicle energy model used ONLY to synthesize training data.

The backend never calls this at runtime; it uses the PyTorch model trained on
the data this produces. Values are calibrated to land in a realistic band for
a compact EV (~110-200 Wh/km).
"""
import numpy as np

G = 9.81
CRR = 0.011
RHO_CDA = 1.2 * 0.70          # air density * (Cd * frontal area)
DRIVETRAIN_EFF = 0.88
REGEN_EFF = 0.60
J_PER_WH = 3600.0


def hvac_kw(mode, temp_c):
    mode, t = np.asarray(mode), np.asarray(temp_c, dtype=float)
    ac = np.clip(0.6 + 0.07 * (t - 22), 0.4, 2.5)
    heat = np.clip(1.5 + 0.09 * (18 - t), 0.8, 4.0)
    return np.select([mode == "ac", mode == "heat", mode == "fan"], [ac, heat, 0.2], 0.0)


def wh_per_km(temp_c, hvac_mode, style, speed_kmh, gradient_m_per_km, payload_kg,
              road_type, soh, kerb_kg=1500.0, rng=None):
    t = np.asarray(temp_c, float)
    s = np.asarray(style, float)
    v_kmh = np.asarray(speed_kmh, float)
    v = v_kmh / 3.6
    grad = np.asarray(gradient_m_per_km, float)
    m = kerb_kg + np.asarray(payload_kg, float)
    city = np.asarray(road_type) == "city"

    roll = CRR * m * G * 1000 / J_PER_WH                    # Wh/km
    aero = 0.5 * RHO_CDA * v**2 * 1000 / J_PER_WH
    climb = m * G * grad / J_PER_WH                          # +/- per km
    climb = np.where(climb > 0, climb / DRIVETRAIN_EFF, climb * REGEN_EFF)

    traction = (roll + aero) / DRIVETRAIN_EFF
    # Aggressive driving: harder acceleration, less coasting. Hurts more in stop-go.
    traction *= 1.0 + np.where(city, 0.30, 0.18) * (s - 0.3)
    stop_go = np.where(city, 18.0 + 30.0 * s, 0.0)

    aux_kw = 0.3 + hvac_kw(hvac_mode, t)
    aux = aux_kw * 1000 / np.maximum(v_kmh, 5.0)

    # Battery/drivetrain efficiency vs temperature and ageing (resistance losses)
    temp_pen = 1 + 0.012 * np.maximum(0, 20 - t) + 0.004 * np.maximum(0, t - 35)
    age_pen = 1 + 0.25 * (1 - np.asarray(soh, float))

    total = (traction + stop_go + climb) * temp_pen * age_pen + aux
    if rng is not None:
        total = total * rng.lognormal(0, 0.05, np.shape(total))
    return np.clip(total, 60, 400)
