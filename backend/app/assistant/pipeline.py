"""Conversation pipeline: text -> intent/tool calls (LLM) -> guarded router -> reply.

  user text
    -> LLM with tool schemas            (intent + entity extraction)
       | Ollama down / LLM answered in prose to a clear command
       -> fallback_parser                (rule-based intent)
    -> ToolRouter.execute               (battery guard runs inside every action)
    -> LLM phrases the reply from facts (template text if unavailable)
"""
from __future__ import annotations

import json
import logging

from app import simulation
from app.assistant import fallback_parser, responder
from app.assistant.llm import OllamaClient
from app.assistant.router import ToolRouter
from app.assistant.tools import TOOL_NAMES, TOOLS

log = logging.getLogger("assistant")
MAX_TOOL_CALLS = 3


class AssistantPipeline:
    def __init__(self, ctx):
        self.ctx = ctx
        self.router = ToolRouter(ctx)
        self.llm = OllamaClient()

    # -- prompt -------------------------------------------------------------------
    def system_prompt(self) -> str:
        st, net = self.ctx.state, self.ctx.net
        r = self.ctx.battery.range(st)
        plan = st.active_plan
        if plan:
            proj = simulation.remaining_projection(self.ctx)
            route = (f"driving to {plan['destination_names'][-1]}"
                     + (f" via chargers {', '.join(s['name'] for s in plan['stops'])}" if plan["stops"] else "")
                     + f"; projected arrival {proj['arrival_soc']:.0%}, {proj['remaining_km']:.0f} km left")
        else:
            route = "none (parked)" if not st.plugged_in else "none (parked, plugged in)"
        offer = st.pending_offer["text"] if st.pending_offer else "none"
        key = ["koramangala", "whitefield", "indiranagar", "electronic_city", "kempegowda_airport", "mysuru", "mandya",
               "tumakuru", "kolar", "hassan", "mangaluru", "hubballi", "belagavi", "nandi_hills", "chikkaballapur"]
        places = ", ".join(net.places[k]["name"] for k in key if k in net.places) + " and 1,000+ other Karnataka towns"
        return (
            "You are Volt, the voice assistant of an electric car in Bengaluru, India. You control navigation, "
            "climate and vehicle features through tools.\n"
            "RULES:\n"
            "1. For ANY request about destinations, navigation, range, battery, charging, AC/climate, cabin "
            "pre-cooling, cameras/driver assistance, cost or resale: call the matching tool. Never answer those "
            "from your own knowledge and never invent numbers.\n"
            "2. The tools check the battery before acting. Report their verdict faithfully.\n"
            "3. If there is a pending offer and the user says yes/no/sure/ok, call respond_to_offer.\n"
            "4. 'Take me to X' / 'navigate to X' / 'go to X' means navigate_to (it checks range itself). Use "
            "check_range_to only for questions like 'will I make it' or 'can I reach'. While driving, "
            "'also stop at X' / 'detour to X' means add_stop; 'go to X instead' means navigate_to.\n"
            "5. Pass place names exactly as the user said them (e.g. 'nearest McD', 'Mysore').\n"
            "6. Replies are read on a car screen: 1-3 short sentences, plain text.\n"
            f"CURRENT STATE: charge {st.soc:.0%}, personalized range {r['personalized_km']:.0f} km, "
            f"location {net.name(st.location)}, outside {st.ambient_temp_c:.0f} °C, climate {st.hvac_mode}, "
            f"active route: {route}. Pending offer: {offer}.\n"
            f"KNOWN PLACES: {places}."
        )

    # -- main entry ---------------------------------------------------------------
    async def handle(self, text: str) -> dict:
        st = self.ctx.state
        text = (text or "").strip()
        if not text:
            return {"reply": "I didn't catch that.", "source": "none", "tool_calls": []}

        source, results, reply = "fallback", [], None
        if await self.llm.available():
            try:
                reply, results = await self._llm_turn(text)
                source = "llm"
            except Exception as exc:                         # timeout, bad JSON, server gone
                log.warning("LLM turn failed, using fallback parser: %s", exc)
                self.llm.mark_unavailable()
                results, reply = [], None

        if source == "fallback":
            intent = fallback_parser.parse(text, st.pending_offer is not None, st.driving)
            if intent:
                results = [self.router.execute(*intent)]
                reply = responder.template_reply(results)
            else:
                reply = ("I can help with navigation, range, charging, climate and your battery. "
                         "Try 'Will I make it to Mysuru?' or 'Take me to the nearest McDonald's'.")

        st.chat_history += [{"role": "user", "content": text}, {"role": "assistant", "content": reply}]
        st.chat_history = st.chat_history[-12:]
        return {
            "reply": reply,
            "source": source,
            "tool_calls": [{"name": r["tool"], "args": r["args"], "ok": r["ok"],
                            "guard": r["guard"]["status"] if r.get("guard") else None} for r in results],
            "route_changed": any(r.get("route_changed") for r in results),
            "results": results,
        }

    async def _llm_turn(self, text: str) -> tuple[str, list[dict]]:
        st = self.ctx.state
        messages = [{"role": "system", "content": self.system_prompt()}, *st.chat_history[-6:],
                    {"role": "user", "content": text}]
        msg = await self.llm.chat(messages, tools=TOOLS)
        calls = [c for c in (msg.get("tool_calls") or []) if c.get("function", {}).get("name") in TOOL_NAMES]

        if not calls:
            # Safety net: the model chatted instead of acting on a clear command
            intent = fallback_parser.parse(text, st.pending_offer is not None, st.driving)
            if intent:
                calls = [{"function": {"name": intent[0], "arguments": intent[1]}}]
                msg = {"role": "assistant", "content": "", "tool_calls": calls}
            else:
                return responder.clean(msg.get("content")) or "Sorry, could you repeat that?", []

        results = []
        for c in calls[:MAX_TOOL_CALLS]:
            args = c["function"].get("arguments") or {}
            if isinstance(args, str):
                args = json.loads(args or "{}")
            results.append(self.router.execute(c["function"]["name"], args))

        # Second pass: let the LLM phrase a reply grounded in the tool facts
        follow = messages + [{"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls[:MAX_TOOL_CALLS]}]
        follow += [responder.tool_message(r) for r in results]
        follow.append({"role": "system", "content": responder.PHRASE_INSTRUCTION})
        try:
            final = await self.llm.chat(follow, tools=None, temperature=0.3)
            reply = responder.clean(final.get("content"))
        except Exception as exc:
            log.warning("phrasing failed, using template: %s", exc)
            reply = ""
        return reply or responder.template_reply(results), results
