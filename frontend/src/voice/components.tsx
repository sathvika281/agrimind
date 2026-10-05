import { useEffect, useRef, useState } from "react";
import type { AnalysisResult } from "../api";
import type { Lang } from "../i18n";
import { useLang } from "../LanguageContext";
import type { VoiceError } from "./stt";
import { buildSpeechText } from "./speechText";
import { startSpeaking, stopSpeaking } from "./tts";
import type { useVoiceInput } from "./useVoiceInput";

type Voice = ReturnType<typeof useVoiceInput>;

/** Push-to-talk microphone for the problem field. Typing is always available; this only fills the text box. */
export function VoiceControls({ voice, lang }: { voice: Voice; lang: Lang }) {
  const { t } = useLang();
  const v = t.voice;
  const { supported, state, interim, error, notice, start, stop } = voice;

  if (!supported) return <p className="hint" role="note">{v.errUnsupported}</p>;

  const recording = state === "starting" || state === "listening";
  const errors: Record<VoiceError, string> = {
    denied: v.errDenied,
    no_mic: v.errNoMic,
    no_speech: v.errNoSpeech,
    network: v.errNetwork,
    lang_unsupported: lang === "te" ? v.errTelugu : v.errUnavailable,
    unsupported: v.errUnsupported,
    unavailable: v.errUnavailable,
  };

  return (
    <div className="mt-3 space-y-2">
      <button
        type="button"
        data-testid="voice-button"
        aria-label={recording ? v.ariaStop : v.ariaStart}
        aria-pressed={recording}
        onClick={recording ? stop : start}
        disabled={state === "finalizing"}
        className={`btn min-h-[3.5rem] border-2 ${recording ? "border-red-600 bg-red-50 text-red-900" : "border-leaf-600 bg-white text-leaf-700 hover:bg-leaf-50"}`}
      >
        {recording ? v.stop : v.speak}
      </button>

      <div role="status" aria-live="polite" className="min-h-[1.5rem] text-base text-gray-800">
        {state === "listening" && (
          <span className="inline-flex items-center gap-2 font-semibold text-red-800">
            <span aria-hidden className="inline-block h-3 w-3 rounded-full bg-red-600 animate-pulse motion-reduce:animate-none" />
            {v.listening}
          </span>
        )}
        {state === "finalizing" && <span>{v.converting}</span>}
        {recording && interim && (
          <span className="mt-1 block text-gray-700">
            {v.hearing} <em>{interim}</em>
          </span>
        )}
        {state === "idle" && notice === "added" && <span className="text-leaf-800">{v.added}</span>}
        {state === "idle" && notice === "guard" && <span className="text-amber-900">{v.guard}</span>}
      </div>

      {error && (
        <div role="alert" className="rounded-xl border-2 border-red-300 bg-red-50 px-4 py-3 text-base text-red-900">
          <span aria-hidden>⚠ </span>
          {errors[error]}
        </div>
      )}
    </div>
  );
}

/** Reads the most important parts of the existing result aloud. TTS problems never affect the written result. */
export function ListenButton({ result, lang, translateTo }: { result: AnalysisResult; lang: Lang; translateTo?: { lang: Lang; run: () => Promise<AnalysisResult | null> } }) {
  const { t } = useLang();
  const v = t.voice;
  const [speaking, setSpeaking] = useState(false);
  const [unavailable, setUnavailable] = useState(false);
  const [preparing, setPreparing] = useState(false);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      stopSpeaking(); // never keep talking after leaving the result page
    };
  }, []);

  async function toggle() {
    if (speaking) {
      stopSpeaking();
      setSpeaking(false);
      return;
    }
    setUnavailable(false);
    // The result is not yet written in the app's language: write it (explicit, stored, same as the translate button), then read THAT.
    let toSpeak = result;
    let speakLang = lang;
    if (translateTo) {
      setPreparing(true);
      const tr = await translateTo.run();
      if (!alive.current) return;
      setPreparing(false);
      if (!tr) return setUnavailable(true);
      toSpeak = tr;
      speakLang = translateTo.lang;
    }
    const outcome = await startSpeaking(buildSpeechText(toSpeak, speakLang), speakLang, {
      onEnd: () => alive.current && setSpeaking(false),
      onError: () => alive.current && setSpeaking(false),
    });
    if (!alive.current) return stopSpeaking();
    if (outcome === "ok") setSpeaking(true);
    else setUnavailable(true); // no voice for this language on this device: say so, keep the text
  }

  return (
    <div className="mb-4">
      <button
        type="button"
        data-testid="listen-button"
        aria-label={speaking ? v.ariaStopListen : v.ariaListen}
        aria-pressed={speaking}
        onClick={toggle}
        disabled={preparing}
        className="btn-secondary"
      >
        {preparing ? "…" : speaking ? v.stopSpeaking : v.listen}
      </button>
      <div role="status" aria-live="polite" className="mt-1 text-sm text-gray-700">
        {speaking && v.speaking}
        {unavailable && <span className="text-amber-900">{v.playbackUnavailable}</span>}
      </div>
    </div>
  );
}
