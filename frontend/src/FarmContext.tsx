import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, ApiError, type Farm } from "./api";
import { useAuth } from "./AuthContext";
import { getDict } from "./i18n";

interface FarmState {
  farms: Farm[] | null;
  selected: Farm | null;
  loading: boolean;
  error: string | null;
  select: (id: number) => void;
  reload: () => Promise<void>;
  /** Replace one farm in memory with the server's saved copy (no refetch). */
  update: (farm: Farm) => void;
}

const Ctx = createContext<FarmState | null>(null);
const KEY = "agrimind.selectedFarm";

function readSaved(): number | null {
  try {
    const v = Number(localStorage.getItem(KEY));
    return Number.isFinite(v) && v > 0 ? v : null;
  } catch {
    return null;
  }
}

export function FarmProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const [farms, setFarms] = useState<Farm[] | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(readSaved());
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setFarms(await api.farms());
    } catch (e) {
      setError(e instanceof ApiError ? e.message : getDict().err.farmsLoad);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (user) void reload();
    else setFarms(null); // never keep another account's farms around
  }, [user, reload]);

  const update = useCallback((farm: Farm) => setFarms((fs) => (fs ? fs.map((f) => (f.id === farm.id ? farm : f)) : fs)), []);

  const select = useCallback((id: number) => {
    setSelectedId(id);
    try {
      localStorage.setItem(KEY, String(id));
    } catch {
      /* private mode: selection simply isn't remembered */
    }
  }, []);

  // The saved id is only trusted if it is one of THIS user's farms; otherwise use the newest farm.
  const selected = useMemo(() => {
    if (!farms || farms.length === 0) return null;
    return farms.find((f) => f.id === selectedId) ?? farms[0];
  }, [farms, selectedId]);

  const value = useMemo(() => ({ farms, selected, loading, error, select, reload, update }), [farms, selected, loading, error, select, reload, update]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useFarms(): FarmState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useFarms must be used inside FarmProvider");
  return v;
}
