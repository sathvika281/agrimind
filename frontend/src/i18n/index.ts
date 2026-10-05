import { en, type Dict } from "./en";
import { te } from "./te";

export type Lang = "en" | "te";
export const LANGS: Lang[] = ["en", "te"];
export const STORAGE_KEY = "agrimind_language";
const DICTS: Record<Lang, Dict> = { en, te };

let active: Lang = "en";

/** Dictionary for the active language. Used by non-React code (API client, formatters). */
export function getDict(): Dict {
  return DICTS[active];
}
export function getLang(): Lang {
  return active;
}
export function dictFor(lang: Lang): Dict {
  return DICTS[lang];
}
export function setActiveLang(lang: Lang) {
  active = lang;
}

/** Safe read: anything unexpected (missing, corrupt, storage blocked) falls back to English. */
export function readSavedLang(): Lang {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    return v === "te" || v === "en" ? v : "en";
  } catch {
    return "en";
  }
}
export function saveLang(lang: Lang) {
  try {
    localStorage.setItem(STORAGE_KEY, lang);
  } catch {
    /* storage unavailable: the choice just isn't remembered */
  }
}
