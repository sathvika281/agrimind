import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, type Insights } from "../api";
import { getDict } from "../i18n";

interface State {
  farmId: number;
  data: Insights | null;
  error: string | null;
}

/**
 * History for ONE farm. Fetches only when the farm changes, the page mounts, or `version` changes (a new check
 * was stored) — never by polling and never because some unrelated UI state changed. A response is applied only
 * if it is still the newest request AND for the farm on screen, so a slow answer can't show another farm's history.
 */
export function useInsights(farmId: number | null, version: string) {
  const [state, setState] = useState<State | null>(null);
  const seq = useRef(0);

  const load = useCallback(async (id: number) => {
    const mine = ++seq.current;
    try {
      const data = await api.farmInsights(id);
      if (mine === seq.current) setState({ farmId: id, data, error: null });
    } catch (e) {
      if (mine === seq.current) setState({ farmId: id, data: null, error: e instanceof ApiError ? e.message : getDict().ins.loadError });
    }
  }, []);

  useEffect(() => {
    if (farmId != null) void load(farmId);
    return () => {
      seq.current++; // leaving the page or switching farm invalidates anything still in flight
    };
  }, [farmId, version, load]);

  // Never expose another farm's data while the new one loads.
  const current = state && state.farmId === farmId ? state : null;
  return {
    data: current?.data ?? null,
    error: current?.error ?? null,
    loading: farmId != null && current === null,
    retry: () => farmId != null && void load(farmId),
  };
}
