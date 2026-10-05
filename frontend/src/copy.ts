// Language-aware helpers. The words themselves live in src/i18n/{en,te}.ts.
// Backend values (severity, uncertainty_level, image_quality, error codes...) are only ever mapped to display text here.
import type { AnalysisResult } from "./api";
import { getDict, getLang } from "./i18n";

/** Strictly mirrors the backend severity values; "unknown" shows nothing. Only the label is translated. */
export const SEVERITY_STYLE: Record<string, { icon: string; cls: string }> = {
  low: { icon: "✔", cls: "bg-leaf-100 text-leaf-800 border-leaf-500" },
  medium: { icon: "!", cls: "bg-amber-100 text-amber-900 border-amber-500" },
  high: { icon: "⚠", cls: "bg-red-100 text-red-900 border-red-500" },
};

/** The text shown for a photo that is hard to read. Uses the model's guidance (written in the analysis language) when present. */
export function photoTip(r: AnalysisResult, hasImage: boolean): string | null {
  if (!hasImage) return null; // never imply a photo was looked at when none was sent
  const t = getDict();
  if (r.image_quality === "poor") return r.image_guidance || t.photoTip.poor;
  if (r.image_quality === "limited") return r.image_guidance || t.photoTip.limited;
  return null;
}

/** Farmer-friendly wording for API failures, in the active language. Never shows codes or technical detail. */
export function friendlyError(code: string, status: number, detail: string): string {
  const t = getDict();
  const te = getLang() === "te";
  switch (code) {
    case "ai_unavailable":
    case "ai_not_configured":
    case "ai_unsafe_output":
      return t.err.ai;
    case "timeout":
      return t.err.timeout;
    case "network":
      return t.err.network;
    case "idempotency_conflict":
      return t.err.conflict;
    case "storage_unavailable":
      return t.err.storage;
    case "image_too_large":
      return t.err.imageLarge;
    case "image_invalid":
      return t.err.imageInvalid;
    case "server_error":
      return t.err.server;
  }
  if (status === 429) return te ? t.err.rateGeneric : detail || t.err.rateGeneric;
  // English backend messages we recognise: translate them in Telugu, keep the original text in English.
  const k = t.err.known;
  const d = detail || "";
  const match: [string, string][] = [
    ["Incorrect email or password", k.badLogin],
    ["already exists", k.emailExists],
    ["Please log in", k.loginAgain],
    ["Farm not found", k.farmNotFound],
    ["Analysis not found", k.checkNotFound],
    ["valid email", k.email],
    ["at least 8 characters", k.pwShort],
    ["too long", k.pwLong],
    ["Farm name is required", k.farmName],
    ["enter the crop", k.crop],
    ["describe the problem", k.needInput],
  ];
  if (te) {
    for (const [needle, text] of match) if (d.includes(needle)) return text;
    if (status === 401) return t.err.session;
    return status >= 500 ? t.err.server : t.err.generic; // never show untranslated English to a Telugu user
  }
  if (status === 401) return d || t.err.session;
  return d || (status >= 500 ? t.err.server : t.err.generic);
}

export function friendlyDate(iso: string): string {
  const t = getDict();
  const d = new Date(/[zZ]|[+-]\d\d:\d\d$/.test(iso) ? iso : iso + "Z");
  const now = new Date();
  const time = d.toLocaleTimeString(t.locale, { hour: "numeric", minute: "2-digit" });
  const same = (a: Date, b: Date) => a.toDateString() === b.toDateString();
  if (same(d, now)) return `${t.date.today}, ${time}`;
  if (same(d, new Date(now.getTime() - 86_400_000))) return `${t.date.yesterday}, ${time}`;
  const date = d.toLocaleDateString(t.locale, { day: "numeric", month: "short", year: d.getFullYear() === now.getFullYear() ? undefined : "numeric" });
  return `${date}, ${time}`;
}

/** Short plain-language name for the main issue, for history titles (works for English and Telugu text). */
export function shortIssue(issue: string): string {
  const t = getDict();
  let s = issue.replace(/\(.*?\)/g, "").replace(/^possible\s+/i, "").trim();
  if (/^(cannot tell|unable to pinpoint)/i.test(s) || s.startsWith("ఈ వివరణతో సమస్య")) return t.history.notClear;
  if (s.length > 48) s = s.slice(0, 45).replace(/\s+\S*$/, "") + "…";
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : t.result.myCheck;
}

/** Weather rows built from numbers (so they are translated); the backend's English `trend` text is not used. */
export function weatherRows(w: {
  temperature_c: number | null;
  humidity_pct: number | null;
  past_3d_rain_mm: number | null;
  next_3d_rain_mm: number | null;
}): string[] {
  const t = getDict().result;
  const rows: string[] = [];
  if (w.temperature_c != null) rows.push(t.tempNow(Math.round(w.temperature_c)));
  if (w.humidity_pct != null) rows.push(w.humidity_pct >= 75 ? t.humHigh : w.humidity_pct <= 40 ? t.humLow : t.humMid);
  if (w.past_3d_rain_mm != null) rows.push(w.past_3d_rain_mm >= 1 ? t.rainPast(String(w.past_3d_rain_mm)) : t.rainLittle);
  if (w.next_3d_rain_mm != null) rows.push(w.next_3d_rain_mm >= 1 ? t.rainNext(String(w.next_3d_rain_mm)) : t.dryNext);
  return rows;
}
