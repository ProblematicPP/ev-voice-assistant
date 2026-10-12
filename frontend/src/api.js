import { useCallback, useEffect, useRef, useState } from "react";

export async function api(path, options = {}) {
  const res = await fetch(`/api${path}`, {
    headers: options.body && !(options.body instanceof FormData) ? { "Content-Type": "application/json" } : {},
    ...options,
    body: options.body && !(options.body instanceof FormData) ? JSON.stringify(options.body) : options.body,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail ?? detail; } catch { /* not json */ }
    throw new Error(detail);
  }
  return res.json();
}

/**
 * Live connection to the backend: vehicle state snapshots, assistant replies
 * and proactive nudges all arrive over one WebSocket.
 */
export function useLive() {
  const [state, setState] = useState(null);
  const [messages, setMessages] = useState([]);
  const [connected, setConnected] = useState(false);
  const [busy, setBusy] = useState(false);
  const wsRef = useRef(null);

  const push = useCallback((m) => setMessages((prev) => [...prev, { id: crypto.randomUUID(), ...m }]), []);

  useEffect(() => {
    let closed = false;
    let retry;
    const connect = () => {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const ws = new WebSocket(`${proto}://${location.host}/api/ws`);
      wsRef.current = ws;
      ws.onopen = () => setConnected(true);
      ws.onclose = () => {
        setConnected(false);
        if (!closed) retry = setTimeout(connect, 1500);
      };
      ws.onmessage = (ev) => {
        const msg = JSON.parse(ev.data);
        if (msg.type === "state") setState(msg.state);
        else if (msg.type === "assistant") {
          setBusy(false);
          push({ role: "assistant", text: msg.reply, source: msg.source, tools: msg.tool_calls });
        } else if (msg.type === "nudge") {
          push({ role: "nudge", text: msg.text, offer: msg.offer });
        }
      };
    };
    connect();
    return () => {
      closed = true;
      clearTimeout(retry);
      wsRef.current?.close();
    };
  }, [push]);

  const send = useCallback((text, input = "text") => {
    const ws = wsRef.current;
    if (!text.trim() || !ws || ws.readyState !== WebSocket.OPEN) return false;
    push({ role: "user", text, input });
    setBusy(true);
    ws.send(JSON.stringify({ type: "user_text", text, input }));
    return true;
  }, [push]);

  return { state, messages, connected, busy, send, push };
}

export const pct = (x) => `${Math.round((x ?? 0) * 100)}%`;
export const inr = (x) => `₹${Math.round(x ?? 0).toLocaleString("en-IN")}`;
export const lakh = (x) => `₹${((x ?? 0) / 1e5).toFixed(1)} lakh`;
export const mins = (m) => {
  const v = Math.round(m ?? 0);
  return v >= 60 ? `${Math.floor(v / 60)} h ${v % 60} min` : `${v} min`;
};

async function synth(text) {
  const res = await fetch("/api/tts", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }),
  });
  if (!res.ok) throw new Error((await res.json()).detail ?? res.statusText);
  return URL.createObjectURL(await res.blob());
}

/** Speaks assistant replies and nudges via the backend's Piper TTS, one at a time. */
export function useSpeaker(messages) {
  const [enabled, setEnabled] = useState(() => {
    try { return localStorage.getItem("volt-voice") !== "off"; } catch { return true; }
  });
  const [speaking, setSpeaking] = useState(false);
  const [error, setError] = useState("");
  const spoken = useRef(new Set());
  const queue = useRef(Promise.resolve());
  const current = useRef(null);
  const primed = useRef(false);
  const enabledRef = useRef(enabled);
  enabledRef.current = enabled;

  const toggle = useCallback(() => {
    setEnabled((on) => {
      const next = !on;
      try { localStorage.setItem("volt-voice", next ? "on" : "off"); } catch { /* storage blocked */ }
      if (!next) current.current?.pause();
      return next;
    });
  }, []);

  useEffect(() => {
    // Don't read out history that existed before the page loaded
    if (!primed.current) {
      messages.forEach((m) => spoken.current.add(m.id));
      primed.current = true;
      return;
    }
    for (const m of messages) {
      if (spoken.current.has(m.id)) continue;
      spoken.current.add(m.id);
      if (!enabled || (m.role !== "assistant" && m.role !== "nudge")) continue;
      // Split into sentences: synthesis of sentence n+1 overlaps playback of sentence n
      const sentences = m.text.split(/(?<=[.!?])\s+/).map((x) => x.trim()).filter(Boolean);
      const fetchChain = { p: Promise.resolve() };
      const clips = sentences.map((text) => {
        fetchChain.p = fetchChain.p.then(() => synth(text));   // backend synthesises one at a time
        return fetchChain.p;
      });
      queue.current = queue.current.then(async () => {
        try {
          for (const clip of clips) {
            const url = await clip;
            if (!enabledRef.current) break;
            const audio = new Audio(url);
            current.current = audio;
            setSpeaking(true);
            await audio.play();
            await new Promise((done) => { audio.onended = done; audio.onpause = done; });
            URL.revokeObjectURL(url);
          }
          setError("");
        } catch (e) {
          setError(e.name === "NotAllowedError" ? "Click anywhere on the page once so the browser allows audio." : `Voice reply failed: ${e.message}`);
        } finally {
          setSpeaking(false);
        }
      });
    }
  }, [messages, enabled]);

  return { enabled, toggle, speaking, error };
}
