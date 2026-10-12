"""FastAPI entry point.  Run from backend/:  uvicorn app.main:app --reload --port 8000"""
import asyncio
import contextlib
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import battery, companion, routes, sim, ws_assistant
from app.api.hub import hub
from app.assistant import stt, tts
from app.assistant.pipeline import AssistantPipeline
from app.config import OLLAMA_MODEL, PIPER_VOICE, WHISPER_MODEL
from app.context import get_ctx

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

pipeline = AssistantPipeline(get_ctx())


async def _nudge_loop():
    while True:
        await asyncio.sleep(8)
        if hub.clients:
            with contextlib.suppress(Exception):
                await hub.check_nudges()


def _preload_speech():
    """Load Whisper + Piper in the background so the first voice turn isn't slow."""
    for loader in (stt.get_model, tts.get_voice):
        try:
            loader()
        except Exception as exc:
            logging.getLogger("startup").warning("preload failed for %s: %s", loader.__module__, exc)


@contextlib.asynccontextmanager
async def lifespan(_app):
    task = asyncio.create_task(_nudge_loop())
    asyncio.get_running_loop().run_in_executor(None, _preload_speech)
    yield
    task.cancel()


app = FastAPI(title="EV Voice Assistant - Battery-Intelligence Core", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])
for r in (battery, companion, routes, sim, ws_assistant):
    app.include_router(r.router)


@app.get("/api/state")
def state():
    return get_ctx().snapshot()


@app.get("/api/health")
async def health():
    return {
        "ok": True,
        "llm": {"model": OLLAMA_MODEL, "available": await pipeline.llm.available()},
        "stt": {"model": WHISPER_MODEL, "loaded": stt.is_loaded(), "device": stt.device()},
        "tts": {"voice": PIPER_VOICE, "loaded": tts.is_loaded()},
    }
