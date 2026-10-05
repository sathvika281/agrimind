import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../api";

interface State<T> {
  key: string;
  data: T | null;
  error: string | null;
}

/**
 * One read-only resource of ONE key (a farm id or a check id). Fetches when the key or `version` changes, never by
 * polling, and applies a response only if it is still the newest request for the key on screen, so a slow answer can't
 * show another farm's (or check's) data.
 */
export function useKeyedData<T>(key: string | null, version: string, fetcher: (key: string) => Promise<T>) {
  const [state, setState] = useState<State<T> | null>(null);
  const seq = useRef(0);
  const fetchRef = useRef(fetcher);
  fetchRef.current = fetcher;

  const load = useCallback(async (k: string) => {
    const mine = ++seq.current;
    try {
      const data = await fetchRef.current(k);
      if (mine === seq.current) setState({ key: k, data, error: null });
    } catch (e) {
      if (mine === seq.current) setState({ key: k, data: null, error: e instanceof ApiError ? e.message : "" });
    }
  }, []);

  useEffect(() => {
    if (key != null) void load(key);
    return () => {
      seq.current++;
    };
  }, [key, version, load]);

  const current = state && state.key === key ? state : null;
  return { data: current?.data ?? null, error: current?.error ?? null, loading: key != null && current === null, retry: () => key != null && void load(key) };
}
