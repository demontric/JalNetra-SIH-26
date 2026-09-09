"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, postVoiceQuery } from "@/lib/api";

export const VOICE_LANGUAGES = [
  { code: "en-IN", label: "English" },
  { code: "hi-IN", label: "हिन्दी (Hindi)" },
  { code: "ta-IN", label: "தமிழ் (Tamil)" },
  { code: "te-IN", label: "తెలుగు (Telugu)" },
  { code: "bn-IN", label: "বাংলা (Bengali)" },
  { code: "od-IN", label: "ଓଡ଼ିଆ (Odia)" },
  { code: "ml-IN", label: "മലയാളം (Malayalam)" },
  { code: "kn-IN", label: "ಕನ್ನಡ (Kannada)" },
];

type VoiceResult = {
  transcribed_text: string;
  answer: string;
  audio_base64?: string | null;
  audio_mime_type?: string | null;
  visual_trace?: unknown;
  execution_log?: unknown[];
  original_query?: string;
  translated_query?: string;
  voice_error?: string | null;
};

type VoiceInterfaceProps = {
  disabled?: boolean;
  inputLanguage: string;
  outputLanguage: string;
  latitude?: number;
  longitude?: number;
  history?: { role: string; text: string }[];
  onResult: (result: VoiceResult) => void;
  onStatus: (status: string) => void;
};

function MicIcon({ recording }: { recording: boolean }) {
  return <svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><rect x="9" y="2" width="6" height="12" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v4M8 22h8" />{recording && <circle cx="12" cy="8" r="1" fill="currentColor" stroke="none" />}</svg>;
}

export default function VoiceInterface({ disabled = false, inputLanguage, outputLanguage, latitude, longitude, history, onResult, onStatus }: VoiceInterfaceProps) {
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [recording, setRecording] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => () => {
    if (timeoutRef.current) clearTimeout(timeoutRef.current);
    recorderRef.current?.stream.getTracks().forEach((track) => track.stop());
  }, []);

  function stopRecording() {
    if (timeoutRef.current) clearTimeout(timeoutRef.current);
    recorderRef.current?.stop();
  }

  async function startRecording() {
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
      setError("This browser does not support microphone recording. Please type your question.");
      return;
    }

    try {
      setError("");
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? "audio/webm;codecs=opus"
        : "audio/webm";
      const uploadMimeType = "audio/webm";
      const recorder = new MediaRecorder(stream, { mimeType });
      chunksRef.current = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size) chunksRef.current.push(event.data);
      };
      recorder.onstop = async () => {
        setRecording(false);
        stream.getTracks().forEach((track) => track.stop());
        // Send the portable MIME type rather than the browser-specific codec tag.
        const recordingBlob = new Blob(chunksRef.current, { type: uploadMimeType });
        if (!recordingBlob.size) {
          setError("No audio was captured. Please try again.");
          return;
        }
        try {
          onStatus("Transcribing your voice request…");
          const result = await postVoiceQuery(recordingBlob, inputLanguage, outputLanguage, { latitude, longitude, history });
          onResult(result);
          onStatus(result.voice_error ? "Text answer ready; audio playback is unavailable." : "Voice answer ready");
          if (result.audio_base64) {
            const audio = new Audio(`data:${result.audio_mime_type || "audio/wav"};base64,${result.audio_base64}`);
            await audio.play();
          }
        } catch (requestError) {
          setError(requestError instanceof ApiError ? requestError.message : "Voice request failed. Please type your question.");
          onStatus("Voice processing unavailable; text input is still available.");
        }
      };
      recorderRef.current = recorder;
      recorder.start();
      setRecording(true);
      onStatus("Listening… tap Stop when you finish.");
      // Saaras synchronous STT accepts recordings of up to 30 seconds.
      timeoutRef.current = setTimeout(stopRecording, 29_000);
    } catch {
      setError("Microphone access was denied. Please type your question instead.");
    }
  }

  return (
    <div className="voice-control">
      <button type="button" onClick={recording ? stopRecording : startRecording} disabled={disabled} className={`mic-button ${recording ? "is-recording" : ""}`} aria-label={recording ? "Stop recording" : "Record a voice question"} title={recording ? "Stop recording" : "Speak your question"}><MicIcon recording={recording} /></button>
      {recording && <span className="recording-pulse" aria-label="Recording" />}
      {error && <span role="status" className="voice-error">{error}</span>}
    </div>
  );
}
