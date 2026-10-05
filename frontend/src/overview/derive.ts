// Pure helpers for the Overview: farm health from REAL checks, deterministic field shapes, weather outlook.
import type { Analysis, Farm, Weather } from "../api";

export type Level = "ok" | "attention" | "critical" | "unrated" | "none";

/** Newest check per farm (works whatever the input order). */
export function latestByFarm(analyses: Analysis[]): Map<number, Analysis> {
  const out = new Map<number, Analysis>();
  for (const a of analyses) {
    const cur = out.get(a.farm_id);
    if (!cur || a.id > cur.id) out.set(a.farm_id, a);
  }
  return out;
}

/**
 * Health level of a farm = the REAL severity from its latest check.
 * none = never checked, unrated = checked but the check gave no rating ("unknown").
 */
export function levelOf(a?: Analysis | null): Level {
  if (!a) return "none";
  switch (a.result.severity) {
    case "low":
      return "ok";
    case "medium":
      return "attention";
    case "high":
      return "critical";
    default:
      return "unrated";
  }
}

export interface Summary {
  ok: number;
  attention: number;
  critical: number;
  unrated: number;
  none: number;
  needsAttention: number;
}

export function summarize(farms: Farm[], latest: Map<number, Analysis>): Summary {
  const s: Summary = { ok: 0, attention: 0, critical: 0, unrated: 0, none: 0, needsAttention: 0 };
  for (const f of farms) s[levelOf(latest.get(f.id))]++;
  s.needsAttention = s.attention + s.critical;
  return s;
}

/** Seeded PRNG so a farm always gets the same shape. */
export function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export const MAP_W = 640;
export const MAP_H = 400;
export const MAX_FIELDS = 6; // 3 x 2 grid

export interface Geometry {
  points: string; // SVG polygon points
  cx: number; // centroid, in map units
  cy: number;
}

/** An organic 8-point polygon inside grid cell `index` (3 columns x 2 rows), unique and stable per farm id. */
export function fieldGeometry(farmId: number, index: number): Geometry {
  const cols = 3;
  const rows = 2;
  const cw = MAP_W / cols;
  const ch = MAP_H / rows;
  const col = index % cols;
  const row = Math.floor(index / cols);
  const pad = 16;
  const x0 = col * cw + pad;
  const y0 = row * ch + pad;
  const w = cw - pad * 2;
  const h = ch - pad * 2;
  const r = mulberry32(farmId * 2654435761 + 97);
  const j = (amt: number) => (r() - 0.5) * 2 * amt;
  // clockwise: 4 corners + 4 edge midpoints, each nudged
  const pts: [number, number][] = [
    [x0 + j(10), y0 + j(10)],
    [x0 + w * 0.5 + j(14), y0 + j(8)],
    [x0 + w + j(10), y0 + j(10)],
    [x0 + w + j(8), y0 + h * 0.5 + j(14)],
    [x0 + w + j(10), y0 + h + j(10)],
    [x0 + w * 0.5 + j(14), y0 + h + j(8)],
    [x0 + j(10), y0 + h + j(10)],
    [x0 + j(8), y0 + h * 0.5 + j(14)],
  ];
  const cx = pts.reduce((s, p) => s + p[0], 0) / pts.length;
  const cy = pts.reduce((s, p) => s + p[1], 0) / pts.length;
  return { points: pts.map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" "), cx, cy };
}

export type Outlook = { kind: "rain" | "dry" | "unknown"; mm: number | null };

/** Rain outlook from REAL weather numbers only (next-few-days forecast). */
export function rainOutlook(w?: Pick<Weather, "next_3d_rain_mm"> | null): Outlook {
  if (!w || w.next_3d_rain_mm == null) return { kind: "unknown", mm: null };
  return w.next_3d_rain_mm >= 1 ? { kind: "rain", mm: w.next_3d_rain_mm } : { kind: "dry", mm: w.next_3d_rain_mm };
}

/** A failed/empty weather answer is retried at most once per cooldown, and only on a relevant event (farm
 *  selected or page changed) — never by polling. A farm with no saved location can't have weather: no retry. */
export const WEATHER_RETRY_MS = Number(import.meta.env?.VITE_WEATHER_RETRY_MS) || 60_000; // env override is for tests only

export function shouldFetchWeather(
  entry: { weather: unknown | null; at: number } | undefined,
  hasLocation: boolean,
  now: number,
  inFlight: boolean,
): boolean {
  if (inFlight) return false;
  if (entry === undefined) return true; // never asked
  if (entry.weather) return false; // have real data (the server caches and refreshes it itself)
  return hasLocation && now - entry.at >= WEATHER_RETRY_MS; // unavailable: allow one retry after the cooldown
}
