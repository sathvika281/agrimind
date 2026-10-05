import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Lang } from "../i18n";
import { getRecognitionCtor, mapRecognitionError, recognitionLang, type RecognitionLike, type VoiceError } from "./stt";

// "starting" = start() called, waiting for the browser to actually begin (e.g. permission prompt).
export type VoiceState = "idle" | "starting" | "listening" | "finalizing";
export type VoiceNotice = "added" | "guard" | null;

/** UI safety limit on one recording (not an assumption about speech quality). Overridable only for tests. */
export const MAX_LISTEN_MS = Number(import.meta.env.VITE_VOICE_MAX_MS) || 60_000;
const FINALIZE_WATCHDOG_MS = 5_000;

interface Options {
  lang: Lang;
  onTranscript: (text: string) => void;
  maxMs?: number;
}

export function useVoiceInput({ lang, onTranscript, maxMs = MAX_LISTEN_MS }: Options) {
  const [state, setState] = useState<VoiceState>("idle");
  const [interim, setInterim] = useState("");
  const [error, setError] = useState<VoiceError | null>(null);
  const [notice, setNotice] = useState<VoiceNotice>(null);
  const supported = useMemo(() => getRecognitionCtor() !== null, []);

  const rec = useRef<RecognitionLike | null>(null);
  const finals = useRef<string[]>([]);
  const interimRef = useRef("");
  const errRef = useRef<VoiceError | null>(null);
  const guardFired = useRef(false);
  const cancelled = useRef(false);
  const finished = useRef(true);
  const timers = useRef<{ guard?: ReturnType<typeof setTimeout>; watchdog?: ReturnType<typeof setTimeout> }>({});
  const deliver = useRef(onTranscript);
  deliver.current = onTranscript;

  const clearTimers = () => {
    clearTimeout(timers.current.guard);
    clearTimeout(timers.current.watchdog);
  };

  /** Runs exactly once per recording (onend, or the watchdog if onend never arrives). */
  const finish = useCallback(() => {
    if (finished.current) return;
    finished.current = true;
    clearTimers();
    rec.current = null;
    setState("idle");
    setInterim("");
    if (cancelled.current) return;
    // Keep everything already captured, including a trailing interim part if the browser never finalised it.
    const text = (finals.current.join(" ").trim() || interimRef.current.trim()).replace(/\s+/g, " ");
    if (text) {
      deliver.current(text);
      setNotice(guardFired.current ? "guard" : "added");
    } else if (!errRef.current) {
      setError("no_speech");
    }
  }, []);

  const stop = useCallback(() => {
    const r = rec.current;
    if (!r || finished.current) return;
    setState("finalizing"); // genuinely waiting for the recognizer to hand back its final text
    clearTimeout(timers.current.guard);
    try {
      r.stop();
    } catch {
      /* fall through to the watchdog */
    }
    timers.current.watchdog = setTimeout(() => {
      try {
        r.abort();
      } catch {
        /* ignore */
      }
      finish();
    }, FINALIZE_WATCHDOG_MS);
  }, [finish]);

  const cancel = useCallback(() => {
    cancelled.current = true;
    clearTimers();
    const r = rec.current;
    rec.current = null;
    finished.current = true;
    setState("idle");
    setInterim("");
    try {
      r?.abort();
    } catch {
      /* ignore */
    }
  }, []);

  const start = useCallback(() => {
    const Ctor = getRecognitionCtor();
    setError(null);
    setNotice(null);
    if (!Ctor) return setError("unsupported");
    if (rec.current) return; // already recording

    finals.current = [];
    interimRef.current = "";
    errRef.current = null;
    guardFired.current = false;
    cancelled.current = false;
    finished.current = false;
    setInterim("");

    const r = new Ctor();
    r.lang = recognitionLang(lang);
    r.continuous = true;
    r.interimResults = true;
    r.maxAlternatives = 1;
    r.onstart = () => setState((s) => (s === "starting" ? "listening" : s));
    r.onresult = (e) => {
      let live = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const res = e.results[i];
        const text = res[0]?.transcript ?? "";
        if (res.isFinal) finals.current.push(text.trim());
        else live += text;
      }
      interimRef.current = live;
      setInterim(live);
    };
    r.onerror = (e) => {
      const mapped = mapRecognitionError(e.error);
      if (!mapped) return; // our own abort
      errRef.current = mapped;
      setError(mapped);
    };
    r.onend = finish;

    rec.current = r;
    setState("starting");
    try {
      r.start();
    } catch {
      rec.current = null;
      finished.current = true;
      setState("idle");
      setError("unavailable");
      return;
    }
    timers.current.guard = setTimeout(() => {
      guardFired.current = true;
      stop(); // stop() (not abort) so already-recognised text is kept
    }, maxMs);
  }, [lang, maxMs, finish, stop]);

  // Leaving the page or switching language mid-recording must never leave a live microphone behind.
  useEffect(() => cancel, [cancel]);
  const firstLang = useRef(lang);
  useEffect(() => {
    if (firstLang.current !== lang) {
      firstLang.current = lang;
      cancel();
    }
  }, [lang, cancel]);

  return { supported, state, interim, error, notice, start, stop, clearError: () => setError(null) };
}
