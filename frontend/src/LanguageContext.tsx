import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { dictFor, readSavedLang, saveLang, setActiveLang, type Lang } from "./i18n";
import type { Dict } from "./i18n/en";

interface LangState {
  lang: Lang;
  t: Dict;
  setLang: (l: Lang) => void;
}

const Ctx = createContext<LangState | null>(null);

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(() => {
    const l = readSavedLang();
    setActiveLang(l); // so non-React helpers (API errors, dates) match from the very first render
    return l;
  });

  const setLang = useCallback((l: Lang) => {
    setActiveLang(l);
    saveLang(l);
    setLangState(l); // only re-renders in place: no navigation, page/form/farm state is untouched
  }, []);

  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);

  const value = useMemo(() => ({ lang, t: dictFor(lang), setLang }), [lang, setLang]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useLang(): LangState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useLang must be used inside LanguageProvider");
  return v;
}
