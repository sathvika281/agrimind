// Push-to-talk speech-to-text using the browser's SpeechRecognition (Web Speech API).
// No audio ever reaches AgriMind's server and nothing is stored. In Chrome/Edge the browser itself sends the
// audio to its vendor's speech service (needs internet). Not available in every browser (e.g. Firefox).
import type { Lang } from "../i18n";

export type VoiceError = "denied" | "no_mic" | "no_speech" | "network" | "lang_unsupported" | "unsupported" | "unavailable";

// Minimal shape of the browser object (the DOM lib does not ship these types).
export interface RecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  onstart: (() => void) | null;
  onresult: ((e: { resultIndex: number; results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal: boolean }> }) => void) | null;
  onerror: ((e: { error?: string }) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}
export type RecognitionCtor = new () => RecognitionLike;

export function getRecognitionCtor(): RecognitionCtor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

/** The selected AgriMind language decides the speech language. */
export function recognitionLang(lang: Lang): string {
  return lang === "te" ? "te-IN" : "en-IN";
}

/** Map browser error codes to our own categories. Returns null for "aborted" (our own cancel: not an error). */
export function mapRecognitionError(code: string | undefined): VoiceError | null {
  switch (code) {
    case "not-allowed":
      return "denied";
    case "audio-capture":
      return "no_mic";
    case "no-speech":
      return "no_speech";
    case "network":
      return "network";
    case "language-not-supported":
      return "lang_unsupported";
    case "aborted":
      return null;
    default: // service-not-allowed, bad-grammar, unknown...
      return "unavailable";
  }
}

/** Append a transcript to existing text without overwriting it; a single space is the separator. */
export function appendTranscript(existing: string, transcript: string): string {
  const add = transcript.trim();
  if (!add) return existing;
  const base = existing.replace(/\s+$/, "");
  return base ? `${base} ${add}` : add;
}
