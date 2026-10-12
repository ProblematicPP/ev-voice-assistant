"""Speech-to-text with faster-whisper (local Whisper, CTranslate2 backend).

The model downloads once (~480 MB for small.en) to the Hugging Face cache on
first use. Audio from the browser (webm/opus) is decoded here with PyAV (ships
with faster-whisper) - no separate ffmpeg install needed. We decode ourselves
because faster-whisper's built-in decoder uses an argument newer PyAV removed.
"""
from __future__ import annotations

import io
import os
import logging
import threading

import av
import numpy as np

from app.config import WHISPER_COMPUTE, WHISPER_DEVICE, WHISPER_MODEL

log = logging.getLogger("stt")

# Biases recognition toward local place names and EV vocabulary
VOCAB_PROMPT = ("Mysuru, Mysore, Koramangala, Whitefield, Indiranagar, Channapatna, Maddur, Mandya, Bidadi, "
                "Kengeri, Tumakuru, Hosur, McDonald's, charger, fast charging, range, battery, AC, pre-cool.")

_model = None
_device = None
_lock = threading.Lock()


def _load(device: str, compute: str):
    from faster_whisper import WhisperModel
    log.info("Loading Whisper %s on %s (%s)...", WHISPER_MODEL, device, compute)
    model = WhisperModel(WHISPER_MODEL, device=device, compute_type=compute, cpu_threads=os.cpu_count() or 4)
    # Warm-up on 1 s of silence: surfaces missing CUDA DLLs now instead of on the first request
    list(model.transcribe(np.zeros(16000, dtype=np.float32), language="en", without_timestamps=True)[0])
    return model


def get_model():
    global _model, _device
    with _lock:
        if _model is None:
            want = WHISPER_DEVICE
            if want in ("auto", "cuda"):
                try:
                    from app.gpu import register_cuda_dlls
                    register_cuda_dlls()
                    _model, _device = _load("cuda", WHISPER_COMPUTE or "float16"), "cuda"
                except Exception as exc:
                    if want == "cuda":
                        raise
                    log.warning("GPU Whisper unavailable (%s) - falling back to CPU", exc)
            if _model is None:
                _model, _device = _load("cpu", WHISPER_COMPUTE or "int8"), "cpu"
        return _model


def device() -> str | None:
    return _device


def decode_16k_mono(audio: bytes) -> np.ndarray:
    """Any container/codec PyAV understands -> float32 PCM, 16 kHz mono."""
    resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
    chunks = []
    with av.open(io.BytesIO(audio)) as container:
        for frame in container.decode(audio=0):
            for out in resampler.resample(frame):
                chunks.append(out.to_ndarray().reshape(-1))
        for out in resampler.resample(None):            # flush
            chunks.append(out.to_ndarray().reshape(-1))
    if not chunks:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(chunks).astype(np.float32) / 32768.0


def transcribe(audio: bytes) -> dict:
    model = get_model()
    segments, info = model.transcribe(
        decode_16k_mono(audio), language="en", beam_size=1, vad_filter=False, without_timestamps=True,
        condition_on_previous_text=False, initial_prompt=VOCAB_PROMPT,
    )
    text = " ".join(s.text.strip() for s in segments).strip()
    return {"text": text, "duration_s": round(info.duration, 2)}


def is_loaded() -> bool:
    return _model is not None
