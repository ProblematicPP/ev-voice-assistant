"""Minimal async client for a local Ollama server (native tool-calling via /api/chat)."""
from __future__ import annotations

import time

import httpx

from app.config import OLLAMA_MODEL, OLLAMA_TIMEOUT_S, OLLAMA_URL


class OllamaClient:
    def __init__(self, url: str = OLLAMA_URL, model: str = OLLAMA_MODEL):
        self.url = url.rstrip("/")
        self.model = model
        self._avail: tuple[float, bool] = (0.0, False)

    async def available(self) -> bool:
        """Cached 20 s so a missing server doesn't slow every turn."""
        ts, ok = self._avail
        if time.time() - ts < 20:
            return ok
        ok = False
        try:
            async with httpx.AsyncClient(timeout=1.5) as c:
                r = await c.get(f"{self.url}/api/tags")
                names = [m["name"] for m in r.json().get("models", [])]
                ok = any(n == self.model or n.startswith(self.model + ":") or n.split(":")[0] == self.model
                         for n in names)
        except Exception:
            ok = False
        self._avail = (time.time(), ok)
        return ok

    def mark_unavailable(self):
        self._avail = (time.time(), False)

    async def chat(self, messages: list[dict], tools: list[dict] | None = None, temperature: float = 0.1) -> dict:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "think": False,          # Qwen 3.x reasons by default; skip it for snappy tool calls
            "keep_alive": "30m",
            "options": {"temperature": temperature, "num_ctx": 4096},
        }
        if tools:
            payload["tools"] = tools
        async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT_S) as c:
            r = await c.post(f"{self.url}/api/chat", json=payload)
            r.raise_for_status()
            return r.json()["message"]
