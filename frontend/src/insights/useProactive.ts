import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, type Proactive } from "../api";
import { getDict } from "../i18n";

interface State {
  farmId: number;
  data: Proactive | null;
  error: string | null;
}

/**
 * "Needs your attention" for ONE farm. Fetches only when the farm changes, the page mounts, or `version`
 * (a new stored check) changes. Only the newest request for the farm on screen may update the state, so a slow
 * answer can never show another farm's items. No polling, no background work.
 */
export function useProactive(farmId: number | null, version: string) {
  const [state, setState] = useState<State | null>(null);
  const seq = useRef(0);

  const load = useCallback(async (id: number) => {
    const mine = ++seq.current;
    try {
      const data = await api.farmProactive(id);
      if (mine === seq.current) setState({ farmId: id, data, error: null });
    } catch (e) {
      if (mine === seq.current) setState({ farmId: id, data: null, error: e instanceof ApiError ? e.message : getDict().pi.loadError });
    }
  }, []);

  useEffect(() => {
    if (farmId != null) void load(farmId);
    return () => {
      seq.current++;
    };
  }, [farmId, version, load]);

  const current = state && state.farmId === farmId ? state : null;
  return {
    data: current?.data ?? null,
    error: current?.error ?? null,
    loading: farmId != null && current === null,
    retry: () => farmId != null && void load(farmId),
  };
}
