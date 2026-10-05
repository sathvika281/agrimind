import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, type Decision } from "../api";
import { getDict } from "../i18n";

interface State {
  key: string;
  data: Decision | null;
  error: string | null;
}

/**
 * Rule-based next-step guidance for ONE farm (and optionally ONE specific check). Fetches only when the farm,
 * the check or `version` (a new check was stored) changes. Only the newest request for the current key may
 * update the state, so a slow answer can never show another farm's or another check's guidance. No polling.
 */
export function useDecision(farmId: number | null, analysisId: number | null, version: string) {
  const key = `${farmId ?? ""}:${analysisId ?? "latest"}`;
  const [state, setState] = useState<State | null>(null);
  const seq = useRef(0);

  const load = useCallback(async (fid: number, aid: number | null, k: string) => {
    const mine = ++seq.current;
    try {
      const data = await api.farmDecision(fid, aid ?? undefined);
      if (mine === seq.current) setState({ key: k, data, error: null });
    } catch (e) {
      if (mine === seq.current) setState({ key: k, data: null, error: e instanceof ApiError ? e.message : getDict().ds.loadError });
    }
  }, []);

  useEffect(() => {
    if (farmId != null) void load(farmId, analysisId, key);
    return () => {
      seq.current++;
    };
  }, [farmId, analysisId, key, version, load]);

  const current = state && state.key === key ? state : null;
  return {
    data: current?.data ?? null,
    error: current?.error ?? null,
    loading: farmId != null && current === null,
    retry: () => farmId != null && void load(farmId, analysisId, key),
  };
}
