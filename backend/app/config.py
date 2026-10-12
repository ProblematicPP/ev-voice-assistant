"""Central configuration: paths, vehicle constants, local model settings."""
import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_DIR / "data"
MODELS_DIR = BACKEND_DIR / "models"

# ---- Vehicle (generic 40 kWh compact EV, Bengaluru owner) -------------------
VEHICLE = {
    "name": "Demo EV (40 kWh)",
    "nominal_kwh": 40.0,
    "usable_fraction": 0.95,      # BMS keeps a top/bottom buffer
    "rated_range_km": 312,        # brochure range, used for the "naive" estimate
    "kerb_mass_kg": 1500,
    "max_ac_kw": 7.4,
    "max_dc_kw": 60.0,
    "purchase_price_inr": 1_500_000,
    "purchase_date": "2023-06-15",
    "home_node": "koramangala",
    "office_node": "whitefield",
}

# Guard thresholds (fraction of SOC)
RESERVE_SOC = 0.10        # plan to arrive with at least this much
HARD_MIN_SOC = 0.05       # never plan to arrive at a charger below this
COMFORT_SOC = 0.15        # "comfortable" arrival; below it we warn
DC_TARGET_SOC = 0.80      # default DC fast-charge target (taper above this)

# Grid / fuel prices for cost comparisons
HOME_TARIFF_INR = 7.5          # per kWh, off-peak
HOME_PEAK_TARIFF_INR = 9.5     # per kWh, 18:00-22:00
PETROL_INR_PER_L = 102.9
PETROL_CAR_KMPL = 15.0

# ---- Security: only the local UI may drive the assistant ---------------------
ALLOWED_ORIGINS = {"http://localhost:5173", "http://127.0.0.1:5173"}
MAX_AUDIO_BYTES = 5 * 1024 * 1024      # ~5 min of opus; push-to-talk clips are tiny
MAX_AUDIO_SECONDS = 30

# ---- Local models -----------------------------------------------------------
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3.5:4b")
OLLAMA_TIMEOUT_S = float(os.getenv("OLLAMA_TIMEOUT_S", "90"))

WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small.en")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "auto")         # auto = GPU if usable, else CPU
WHISPER_COMPUTE = os.getenv("WHISPER_COMPUTE", "")           # default: float16 on GPU, int8 on CPU

PIPER_VOICE = os.getenv("PIPER_VOICE", "en_US-lessac-medium")
