import { useEffect, useRef, useState } from "react";
import { api, openOffer, useSpeaker } from "../api.js";
import { MicIcon, MuteIcon, SendIcon, SpeakerIcon } from "../icons.jsx";

const SUGGESTIONS = [
  "Will I make it to Mysuru without stopping?",
  "Take me to the nearest McDonald’s",
  "Why is my range lower than usual?",
  "How are my charging habits?",
  "Cool the cabin before I leave",
];

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

export default function Volt({ live }) {
  const { messages, send, busy, connected } = live;
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  const [transcribing, setTranscribing] = useState(false);
  const listRef = useRef(null);
  const speaker = useSpeaker(messages);
  const offer = openOffer(messages);

  const recorder = useRecorder(async (blob) => {
    setTranscribing(true);
    setError("");
    try {
      const form = new FormData();
      form.append("audio", blob, "speech.webm");
      const out = await api("/stt", { method: "POST", body: form });
      if (out.text) send(out.text, "voice");
      else setError("Didn’t catch that. Hold the mic button and speak a little longer.");
    } catch {
      setError("Voice input isn’t available right now. Type your request instead.");
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
      setError("Microphone access is blocked. Allow it in your browser’s site settings, or type instead.");
    }
  };

  return (
    <div className="volt">
      <header className="app-bar">
        <div>
          <h1>Volt</h1>
          <p>Your car assistant</p>
        </div>
        <button className="icon-btn" onClick={speaker.toggle} aria-pressed={speaker.enabled}
          aria-label={speaker.enabled ? "Mute spoken replies" : "Read replies aloud"}>
          {speaker.enabled ? <SpeakerIcon /> : <MuteIcon />}
        </button>
      </header>

      <div className="messages" ref={listRef} aria-live="polite">
        {messages.length === 0 && (
          <div className="chat-empty">
            <p>Ask about range, trips, charging or your battery. Volt checks your charge before acting.</p>
            <div className="suggestions">
              {SUGGESTIONS.map((s) => (
                <button key={s} className="suggestion" onClick={() => send(s)} disabled={!connected}>{s}</button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m) => (
          <div key={m.id} className={`msg ${m.role}`}>
            {m.role === "nudge" && <b className="msg-kicker">Volt suggests</b>}
            {m.text}
            {m === offer && (
              <div className="row-actions">
                <button className="btn primary small" onClick={() => send("yes")}>{m.offer}</button>
                <button className="btn ghost small" onClick={() => send("no")}>Not now</button>
              </div>
            )}
          </div>
        ))}
        {transcribing && <div className="typing">Listening back…</div>}
        {busy && <div className="typing" aria-label="Volt is replying"><i /><i /><i /></div>}
      </div>

      {(error || speaker.error) && <div className="banner bad slim" role="alert">{error || speaker.error}</div>}

      <form className="composer" onSubmit={submit}>
        <input value={text} onChange={(e) => setText(e.target.value)}
          placeholder={recorder.recording ? "Listening… tap the mic to finish" : "Message Volt"}
          aria-label="Message" enterKeyHint="send" />
        {text.trim() ? (
          <button className="round-btn send" disabled={!connected} aria-label="Send"><SendIcon size={20} /></button>
        ) : (
          <button type="button" className={`round-btn mic ${recorder.recording ? "recording" : ""}`} onClick={toggleMic}
            aria-label={recorder.recording ? "Stop and send" : "Speak to Volt"} disabled={transcribing || !connected}>
            <MicIcon size={20} />
          </button>
        )}
      </form>
    </div>
  );
}
