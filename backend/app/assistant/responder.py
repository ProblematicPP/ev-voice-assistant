"""Response generation: turn structured tool results into a short reply.

Primary: the LLM phrases the reply from the tool facts (natural wording).
Fallback: the router's deterministic template text (`say`).
"""
from __future__ import annotations

import json

PHRASE_INSTRUCTION = (
    "Now reply to the driver in 1-3 short sentences using ONLY the facts in the tool results above. "
    "Keep every number exactly as given (%, km, minutes, ₹). If the guard blocked an action, say so plainly "
    "and give the suggested alternative. If a tool asked a question (e.g. 'Want me to...?'), end with that question. "
    "No markdown, no lists, no emojis."
)


def tool_message(res: dict) -> dict:
    payload = {"ok": res["ok"], "summary": res["say"], "facts": res["facts"]}
    if res.get("guard"):
        payload["guard"] = {"status": res["guard"]["status"], "reasons": res["guard"]["reasons"]}
    return {"role": "tool", "tool_name": res["tool"], "content": json.dumps(payload, ensure_ascii=False, default=str)}


def template_reply(results: list[dict]) -> str:
    return " ".join(r["say"] for r in results if r.get("say")).strip() or "Done."


def clean(text: str) -> str:
    text = (text or "").strip()
    for ch in ("**", "__", "`", "#"):
        text = text.replace(ch, "")
    return " ".join(text.split())
