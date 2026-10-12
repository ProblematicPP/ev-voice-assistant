import { useEffect, useRef, useState } from "react";
import { api, useSpeaker } from "../api.js";

const SUGGESTIONS = [
  "Will I make it to Mysore without stopping?",
  "Take me to the nearest McD",
  "Why is my range lower than usual?",
  "How are my charging habits?",
  "Pre-cool the cabin",
  "Show the left turn camera",
];

const TOOL_LABEL = {
  navigate_to: "navigate", check_range_to: "range check", add_stop: "add stop", cancel_navigation: "cancel route",
  get_battery_status: "battery status", explain_range: "range attribution", list_chargers: "chargers",
  start_charging: "charge", set_climate: "climate", precool_cabin: "pre-cool (stub)",
  assisted_driving: "driver assist (stub)", respond_to_offer: "offer reply",
  get_charging_coaching: "coaching", get_cost_and_resale: "cost & resale",
};

const GUARD_LABEL = {
  ok: "guard: ok", ok_low_margin: "guard: thin margin", ok_with_charge_stop: "guard: needs charging",
  infeasible: "guard: blocked", blocked_low_soc: "guard: blocked", ok_grid_power: "guard: grid power",
  ok_battery_power: "guard: battery power", ok_with_advice: "guard: advice",
};

function useRecorder(onAudio) {
  const [recording, setRecording] = useState(false);
  const recRef = useRef(null);

  const start = async () => {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const rec = new MediaRecorder(stream);
    const chunks = [];
    rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    rec.onstop = () => {
      stream.getTracks().forEach((t) => t.stop());
      onAudio(new Blob(chunks, { type: rec.mimeType || "audio/webm" }));
    };
    rec.start();
    recRef.current = rec;
    setRecording(true);
  };
  const stop = () => {
    recRef.current?.stop();
    setRecording(false);
  };
  return { recording, start, stop };
}

function MicIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
      strokeLinecap="round" aria-hidden="true">
      <rect x="9" y="3" width="6" height="12" rx="3" />
      <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
    </svg>
  );
}

export default function AssistantPanel({ live, health }) {
  const { messages, send, busy, connected } = live;
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  const [transcribing, setTranscribing] = useState(false);
  const listRef = useRef(null);
  const speaker = useSpeaker(messages);

  const recorder = useRecorder(async (blob) => {
    setTranscribing(true);
    setError("");
    try {
      const form = new FormData();
      form.append("audio", blob, "speech.webm");
      const out = await api("/stt", { method: "POST", body: form });
      if (out.text) send(out.text, "voice");
      else setError("No speech detected. Hold the mic a little longer and speak clearly.");
    } catch (e) {
      setError(`Voice input failed: ${e.message}`);
    } finally {
      setTranscribing(false);
    }
  });

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, busy, transcribing]);

  const submit = (e) => {
    e.preventDefault();
    if (send(text)) setText("");
  };

  const toggleMic = async () => {
    setError("");
    if (recorder.recording) return recorder.stop();
    try {
      await recorder.start();
    } catch {
      setError("Microphone access was blocked. Allow it in the browser's site settings, or type instead.");
    }
  };

  // Only the most recent nudge with an offer shows Yes/No buttons
  const lastOfferIdx = messages.findLastIndex((m) => m.role === "nudge" && m.offer);
  const answeredAfter = lastOfferIdx >= 0 && messages.slice(lastOfferIdx + 1).some((m) => m.role === "user");

  return (
    <aside className="panel assistant" aria-label="Voice assistant">
      <div className="assistant-head">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
          <h1>Volt</h1>
          <button className={`btn small ${speaker.enabled ? "primary" : ""}`} onClick={speaker.toggle}
            aria-pressed={speaker.enabled}>
            {speaker.enabled ? (speaker.speaking ? "Speaking…" : "Voice replies on") : "Voice replies off"}
          </button>
        </div>
        <p>Every action is checked against battery health and range before it runs.</p>
      </div>

      <div className="messages" ref={listRef} aria-live="polite">
        {messages.length === 0 && (
          <div className="empty-chat">
            Tap the mic or type a request. Try:
            <div className="suggestions">
              {SUGGESTIONS.map((s) => (
                <button key={s} className="suggestion" onClick={() => send(s)} disabled={!connected}>{s}</button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m, i) => (
          <div key={m.id} className={`msg ${m.role}`}>
            {m.role === "user" && m.input === "voice" && <span className="voice-note">Heard:</span>}
            {m.role === "nudge" && <strong style={{ display: "block", fontSize: 13 }}>Volt noticed</strong>}
            {m.text}
            {m.role === "assistant" && m.tools?.length > 0 && (
              <div className="meta">
                {m.tools.map((t, j) => (
                  <span key={j} className={`tool-tag ${t.guard === "infeasible" || t.guard?.startsWith("blocked") ? "blocked" : t.guard === "ok_with_charge_stop" ? "charge" : ""}`}>
                    {TOOL_LABEL[t.name] ?? t.name}{t.guard ? ` · ${GUARD_LABEL[t.guard] ?? t.guard}` : ""}
                  </span>
                ))}
                <span className="tool-tag">{m.source === "llm" ? "LLM" : "rule-based"}</span>
              </div>
            )}
            {m.role === "nudge" && m.offer && i === lastOfferIdx && !answeredAfter && (
              <div className="offer-actions">
                <button className="btn small primary" onClick={() => send("yes")}>Yes, {m.offer.toLowerCase()}</button>
                <button className="btn small" onClick={() => send("no")}>Not now</button>
              </div>
            )}
          </div>
        ))}
        {transcribing && <div className="typing">Transcribing your voice…</div>}
        {busy && <div className="typing">Checking the battery and planning…</div>}
      </div>

      {(error || speaker.error) && <div className="error-banner" role="alert">{error || speaker.error}</div>}
      {health && !health.llm?.available && messages.length === 0 && (
        <div className="error-banner" style={{ background: "var(--warn-soft)", color: "var(--warn)" }}>
          Ollama isn't reachable, so requests go through the rule-based parser. Start Ollama to enable the LLM.
        </div>
      )}

      <form className="composer" onSubmit={submit}>
        <button type="button" className={`btn mic ${recorder.recording ? "recording" : ""}`} onClick={toggleMic}
          aria-label={recorder.recording ? "Stop recording" : "Start voice input"} disabled={transcribing || !connected}>
          <MicIcon />
        </button>
        <input value={text} onChange={(e) => setText(e.target.value)}
          placeholder={recorder.recording ? "Listening… tap the mic again to send" : "Ask Volt…"}
          aria-label="Message" />
        <button className="btn primary" disabled={!text.trim() || !connected}>Send</button>
      </form>
    </aside>
  );
}
