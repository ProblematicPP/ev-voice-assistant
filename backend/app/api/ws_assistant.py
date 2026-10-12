"""Assistant transport: WebSocket for chat + server-pushed nudges, REST for STT."""
import asyncio
import json
import logging

from fastapi import APIRouter, File, HTTPException, Response, UploadFile, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from app.api.hub import hub
from app.assistant import stt, tts
from app.context import get_ctx

router = APIRouter(prefix="/api", tags=["assistant"])
log = logging.getLogger("ws")
_lock = asyncio.Lock()   # one conversational turn at a time (single vehicle)


class ChatIn(BaseModel):
    text: str


async def run_turn(text: str, via: str = "text") -> dict:
    from app.main import pipeline
    async with _lock:
        out = await pipeline.handle(text)
    msg = {"type": "assistant", "user_text": text, "input": via,
           **{k: out[k] for k in ("reply", "source", "tool_calls", "route_changed")}}
    await hub.broadcast(msg)
    await hub.check_nudges()
    await hub.push_state()
    return msg


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await hub.connect(ws)
    try:
        await hub.send(ws, {"type": "state", "state": get_ctx().snapshot()})
        while True:
            data = json.loads(await ws.receive_text())
            if data.get("type") == "user_text":
                await run_turn(data.get("text", ""), data.get("input", "text"))
            elif data.get("type") == "ping":
                await hub.send(ws, {"type": "pong"})
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        log.exception("ws error: %s", exc)
    finally:
        hub.disconnect(ws)


@router.post("/chat")
async def chat(body: ChatIn):
    """REST alternative to the WebSocket (handy for testing with curl)."""
    return await run_turn(body.text)


@router.post("/stt")
async def speech_to_text(audio: UploadFile = File(...)):
    data = await audio.read()
    if len(data) < 1000:
        raise HTTPException(400, "Recording too short")
    try:
        return await asyncio.to_thread(stt.transcribe, data)
    except Exception as exc:
        log.exception("STT failed")
        raise HTTPException(500, f"Speech-to-text failed: {exc}") from exc


class TTSIn(BaseModel):
    text: str


@router.post("/tts")
async def text_to_speech(body: TTSIn):
    text = body.text.strip()[:600]
    if not text:
        raise HTTPException(400, "No text")
    try:
        wav = await asyncio.to_thread(tts.synthesize, text)
    except Exception as exc:
        log.exception("TTS failed")
        raise HTTPException(500, f"Text-to-speech failed: {exc}") from exc
    return Response(content=wav, media_type="audio/wav")
