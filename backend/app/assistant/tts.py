"""Text-to-speech with Piper (local neural TTS, ONNX runtime).

The voice model (~60 MB) downloads once from Hugging Face on first use.
Synthesis runs well faster than real time on CPU, so no GPU is needed here.
"""
from __future__ import annotations

import io
import logging
import re
import threading
import wave

from app.config import PIPER_VOICE

log = logging.getLogger("tts")

_voice = None
_lock = threading.Lock()
_synth_lock = threading.Lock()   # one synthesis at a time on the shared ONNX session


def _voice_files(name: str) -> tuple[str, str]:
    """Download (or reuse cached) Piper voice files, e.g. en_US-lessac-medium."""
    from huggingface_hub import hf_hub_download

    lang, speaker, quality = name.split("-")
    base = f"{lang.split('_')[0]}/{lang}/{speaker}/{quality}/{name}"
    onnx = hf_hub_download("rhasspy/piper-voices", f"{base}.onnx")
    cfg = hf_hub_download("rhasspy/piper-voices", f"{base}.onnx.json")
    return onnx, cfg


def get_voice():
    global _voice
    with _lock:
        if _voice is None:
            from piper import PiperVoice
            onnx, cfg = _voice_files(PIPER_VOICE)
            log.info("Loading Piper voice %s", PIPER_VOICE)
            _voice = PiperVoice.load(onnx, config_path=cfg)
        return _voice


def speakable(text: str) -> str:
    """Make numbers/symbols read naturally."""
    # "₹7.9 lakh" -> "7.9 lakh rupees", "₹1.67" -> "1.67 rupees"
    text = re.sub(r"₹\s?(\d+(?:,\d+)*(?:\.\d+)?)(\s*lakh|k)?",
                  lambda m: f"{m.group(1)}{' thousand' if m.group(2) == 'k' else (m.group(2) or '')} rupees", text)
    text = text.replace("₹", "rupees ").replace("°C", " degrees").replace("%", " percent")
    text = re.sub(r"\bper km\b", "per kilometre", text)
    text = re.sub(r"\bkm\b", "kilometres", text)
    text = re.sub(r"\bkWh\b", "kilowatt hours", text)
    text = re.sub(r"\bkW\b", "kilowatt", text)
    text = re.sub(r"\bSOH\b", "battery health", text)
    text = text.replace("→", " to ").replace("~", "about ")
    return re.sub(r"\s+", " ", text).strip()


def synthesize(text: str) -> bytes:
    voice = get_voice()
    buf = io.BytesIO()
    with _synth_lock, wave.open(buf, "wb") as wf:
        if hasattr(voice, "synthesize_wav"):      # piper-tts >= 1.3
            voice.synthesize_wav(speakable(text), wf)
        else:                                      # older API
            voice.synthesize(speakable(text), wf)
    return buf.getvalue()


def is_loaded() -> bool:
    return _voice is not None
