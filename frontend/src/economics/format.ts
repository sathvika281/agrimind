import type { Rng } from "../api";

export const inr = (n: number, loc: string) => `₹${n.toLocaleString(loc)}`;
export const num = (n: number, loc: string) => n.toLocaleString(loc, { maximumFractionDigits: 1 });

/** "₹24,680–₹47,960" (or one figure when low == high). Never rounds beyond what the server already did. */
export function money(r: Rng | null | undefined, loc: string): string {
  if (!r) return "—";
  return r.low === r.high ? inr(r.low, loc) : `${inr(r.low, loc)}–${inr(r.high, loc)}`;
}

export function qty(r: Rng | null | undefined, loc: string): string {
  if (!r) return "—";
  return r.low === r.high ? num(r.low, loc) : `${num(r.low, loc)}–${num(r.high, loc)}`;
}

export const dateShort = (iso: string, loc: string) => new Date(iso + "T00:00:00").toLocaleDateString(loc, { day: "numeric", month: "short" });
export const dateFull = (iso: string, loc: string) => new Date(iso + "T00:00:00").toLocaleDateString(loc, { day: "numeric", month: "short", year: "numeric" });
