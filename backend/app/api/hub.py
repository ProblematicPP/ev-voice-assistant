"""WebSocket fan-out: pushes state updates, nudges and assistant replies to the UI."""
from __future__ import annotations

import json
import logging

from fastapi import WebSocket

from app.assistant import nudges
from app.context import get_ctx

log = logging.getLogger("hub")


def to_json(obj) -> str:
    return json.dumps(obj, default=lambda o: float(o) if hasattr(o, "__float__") else str(o), ensure_ascii=False)


class Hub:
    def __init__(self):
        self.clients: set[WebSocket] = set()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.clients.add(ws)

    def disconnect(self, ws: WebSocket):
        self.clients.discard(ws)

    async def send(self, ws: WebSocket, msg: dict):
        await ws.send_text(to_json(msg))

    async def broadcast(self, msg: dict):
        dead = []
        data = to_json(msg)
        for ws in list(self.clients):
            try:
                await ws.send_text(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    async def push_state(self):
        await self.broadcast({"type": "state", "state": get_ctx().snapshot()})

    async def check_nudges(self):
        for n in nudges.evaluate(get_ctx()):
            await self.broadcast({"type": "nudge", **n})


hub = Hub()
