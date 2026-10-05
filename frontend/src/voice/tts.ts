// Text-to-speech with the browser's built-in speechSynthesis. No audio is generated or stored by AgriMind.
import type { Lang } from "../i18n";

export type SpeakOutcome = "ok" | "unsupported" | "no_voice";

export function ttsSupported(): boolean {
  return typeof window !== "undefined" && "speechSynthesis" in window && "SpeechSynthesisUtterance" in window;
}

interface VoiceLike {
  lang: string;
}

/** Best matching voice for the language, or null. Telugu REQUIRES a Telugu voice (see startSpeaking). */
export function pickVoice<T extends VoiceLike>(voices: T[], lang: Lang): T | null {
  if (lang === "te") return voices.find((v) => /^te([-_]|$)/i.test(v.lang)) ?? null;
  return voices.find((v) => /^en[-_]in$/i.test(v.lang)) ?? voices.find((v) => /^en([-_]|$)/i.test(v.lang)) ?? null;
}

/** getVoices() is often empty until the browser has loaded them; wait briefly for 'voiceschanged'. */
export function loadVoices(timeoutMs = 1500): Promise<SpeechSynthesisVoice[]> {
  return new Promise((resolve) => {
    const synth = window.speechSynthesis;
    const now = synth.getVoices();
    if (now.length) return resolve(now);
    const done = () => {
      synth.removeEventListener?.("voiceschanged", done);
      resolve(synth.getVoices());
    };
    synth.addEventListener?.("voiceschanged", done);
    setTimeout(done, timeoutMs);
  });
}

export interface SpeakHandlers {
  onEnd?: () => void;
  onError?: () => void;
}

/**
 * Speak `text`. For Telugu, if the device has no Telugu voice we do NOT fall back to an English voice
 * (it would mispronounce Telugu badly): we report "no_voice" so the UI can say so and keep the text.
 * English may use the browser's default voice if no explicit English voice is listed.
 */
export async function startSpeaking(text: string, lang: Lang, handlers: SpeakHandlers = {}): Promise<SpeakOutcome> {
  if (!ttsSupported() || !text.trim()) return "unsupported";
  const voices = await loadVoices();
  const voice = pickVoice(voices, lang);
  if (lang === "te" && !voice) return "no_voice";

  const synth = window.speechSynthesis;
  synth.cancel(); // never overlap with a previous utterance
  const u = new SpeechSynthesisUtterance(text);
  u.lang = voice?.lang ?? (lang === "te" ? "te-IN" : "en-IN");
  if (voice) u.voice = voice;
  u.rate = 0.95;
  u.onend = () => handlers.onEnd?.();
  u.onerror = () => handlers.onError?.();
  synth.speak(u);
  return "ok";
}

export function stopSpeaking(): void {
  if (ttsSupported()) window.speechSynthesis.cancel();
}
