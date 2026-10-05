import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useLocation } from "react-router-dom";
import { api, type Analysis, type Weather, type WeatherRisk } from "../api";
import { useAuth } from "../AuthContext";
import { useFarms } from "../FarmContext";
import { latestByFarm, shouldFetchWeather, summarize, type Summary } from "./derive";

export interface FarmWeather {
  weather: Weather | null;
  note: string | null;
  /** Deterministic hints from the real forecast (the server computes them; [] when weather is unavailable). */
  risks?: WeatherRisk[];
  /** When this answer arrived (ms). Used only to space out a retry of an unavailable answer. */
  at: number;
}

interface StatusState {
  analyses: Analysis[] | null;
  latest: Map<number, Analysis>;
  summary: Summary;
  weatherByFarm: Record<number, FarmWeather | undefined>;
  weatherLoading: boolean;
  refresh: () => Promise<void>;
  /** Swap one stored check for its updated copy (e.g. after writing it in the other language). No refetch. */
  replace: (a: Analysis) => void;
  loadWeather: (farmIds: number[]) => Promise<void>;
}

const Ctx = createContext<StatusState | null>(null);
const EMPTY: Summary = { ok: 0, attention: 0, critical: 0, unrated: 0, none: 0, needsAttention: 0 };

/** REAL data for the header chips and the Overview: your checks and the farm's weather. Nothing is invented here. */
export function StatusProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const { farms, selected } = useFarms();
  const { pathname } = useLocation();
  const [analyses, setAnalyses] = useState<Analysis[] | null>(null);
  const [weatherByFarm, setWeatherByFarm] = useState<Record<number, FarmWeather | undefined>>({});
  const [weatherLoading, setWeatherLoading] = useState(false);
  const inflight = useRef(new Set<number>());
  // Bumped on every login/logout: a response that arrives after the account changed is dropped, never shown.
  const generation = useRef(0);
  const refreshSeq = useRef(0);

  const refresh = useCallback(async () => {
    const gen = generation.current;
    const seq = ++refreshSeq.current;
    try {
      const list = await api.analyses();
      // Only the newest request of the current account may update the state (no out-of-order overwrite).
      if (gen === generation.current && seq === refreshSeq.current) setAnalyses(list);
    } catch {
      /* keep what we have; pages show their own errors */
    }
  }, []);

  // Fresh data whenever the user logs in or moves between pages (one cheap list call).
  useEffect(() => {
    if (user) void refresh();
    else {
      generation.current++;
      inflight.current.clear();
      setAnalyses(null);
      setWeatherByFarm({}); // never keep another account's data
    }
  }, [user, pathname, refresh]);

  const replace = useCallback((a: Analysis) => setAnalyses((list) => (list ? list.map((x) => (x.id === a.id ? a : x)) : list)), []);

  const loadWeather = useCallback(async (ids: number[]) => {
    const todo = ids.filter((id) => !inflight.current.has(id));
    if (!todo.length) return;
    todo.forEach((id) => inflight.current.add(id));
    const gen = generation.current;
    setWeatherLoading(true);
    await Promise.all(
      todo.map(async (id) => {
        let entry: FarmWeather;
        try {
          const r = await api.farmWeather(id);
          entry = { weather: r.weather, note: r.note, risks: r.risks ?? [], at: Date.now() };
        } catch {
          entry = { weather: null, note: null, at: Date.now() };
        }
        inflight.current.delete(id);
        if (gen === generation.current) setWeatherByFarm((m) => ({ ...m, [id]: entry }));
      }),
    );
    if (gen === generation.current) setWeatherLoading(false);
  }, []);

  // The selected farm's weather is loaded (cached on the server; failures are non-fatal). An unavailable answer is
  // retried after a cooldown when the farm is selected again or the page changes — never by polling.
  useEffect(() => {
    if (!user || !selected) return;
    const e = weatherByFarm[selected.id];
    if (shouldFetchWeather(e, selected.location.trim() !== "", Date.now(), inflight.current.has(selected.id))) void loadWeather([selected.id]);
  }, [user, selected, weatherByFarm, pathname, loadWeather]);

  const latest = useMemo(() => latestByFarm(analyses ?? []), [analyses]);
  const summary = useMemo(() => (farms ? summarize(farms, latest) : EMPTY), [farms, latest]);

  const value = useMemo(
    () => ({ analyses, latest, summary, weatherByFarm, weatherLoading, refresh, replace, loadWeather }),
    [analyses, latest, summary, weatherByFarm, weatherLoading, refresh, replace, loadWeather],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useStatus(): StatusState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useStatus must be used inside StatusProvider");
  return v;
}
