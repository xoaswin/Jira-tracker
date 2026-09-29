// Push-to-talk for the assistant: record a short clip in the browser, send it
// to the backend (Groq Whisper), and hand back the text. Microphone access
// needs a secure context (the desktop app, or http://localhost), so callers
// hide the mic when ``supported`` is false.

import { useEffect, useRef, useState } from "react";

const MAX_RECORD_MS = 30_000;

export function useVoiceInput(onText: (text: string) => void) {
  const [recording, setRecording] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const recRef = useRef<MediaRecorder | null>(null);
  const timerRef = useRef<number | null>(null);
  const onTextRef = useRef(onText);
  onTextRef.current = onText;

  const supported =
    typeof window !== "undefined" &&
    window.isSecureContext &&
    !!navigator.mediaDevices?.getUserMedia &&
    typeof MediaRecorder !== "undefined";

  useEffect(() => () => recRef.current?.stop(), []);

  async function toggle() {
    if (recRef.current) {
      recRef.current.stop();
      return;
    }
    setError(null);
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      setError("Microphone unavailable. Allow mic access for this app.");
      return;
    }
    const mime = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
      ? "audio/webm;codecs=opus"
      : "audio/webm";
    const chunks: Blob[] = [];
    const rec = new MediaRecorder(stream, { mimeType: mime });
    rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    rec.onstop = async () => {
      if (timerRef.current) window.clearTimeout(timerRef.current);
      stream.getTracks().forEach((t) => t.stop());
      recRef.current = null;
      setRecording(false);
      if (!chunks.length) return;
      setBusy(true);
      try {
        const res = await fetch("/api/voice/transcribe", {
          method: "POST",
          headers: { "Content-Type": mime },
          body: new Blob(chunks, { type: mime }),
        });
        const body = await res.json().catch(() => ({}));
        if (!res.ok) setError(body.detail || "Transcription failed.");
        else if (!body.text) setError("Didn't catch that. Try again.");
        else onTextRef.current(body.text);
      } catch {
        setError("Couldn't reach the tracker backend.");
      } finally {
        setBusy(false);
      }
    };
    recRef.current = rec;
    rec.start();
    setRecording(true);
    timerRef.current = window.setTimeout(() => recRef.current?.stop(), MAX_RECORD_MS);
  }

  return { supported, recording, busy, error, toggle };
}
