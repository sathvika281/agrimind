import type { PlanCtx, PlanItem } from "../api";
import type { Dict } from "../i18n/en";

const num = (v: unknown): number | undefined => (typeof v === "number" ? Math.round(v * 10) / 10 : undefined);

function ctxOf(t: Dict, it: PlanItem, fmt: (iso: string) => string): PlanCtx {
  return {
    when: it.when ? fmt(it.when) : "",
    rain: num(it.params.rain_mm),
    temp: num(it.params.temp_max_c),
    activity: t.fpl.act[String(it.params.activity ?? "")] ?? String(it.params.activity ?? ""),
    hot: !!it.params.hot,
  };
}

/** The dictionary key for a plan item: a planned activity's wording depends on its status and reason. */
export function textKey(it: PlanItem): string {
  if (it.kind === "activity") {
    const r = it.reasons[0];
    return it.status === "supported" ? "activity_supported" : r === "heavy_rain_that_day" ? "activity_heavy_rain" : r === "wet_after_rain" ? "activity_wet"
      : it.status === "cool_hours" ? "activity_hot" : r === "no_forecast" ? "activity_nofc" : "activity_beyond";
  }
  if (it.kind === "planting_window") return it.when ? "planting_best" : "planting_none";
  return it.kind;
}

/** The full explanation sentence (the existing wording, unchanged). Shown only on demand inside the "Why?" sheet. */
export function itemText(t: Dict, it: PlanItem, fmt: (iso: string) => string): string {
  const fn = t.fpl.item[textKey(it)];
  return fn ? fn(ctxOf(t, it, fmt)) : "";
}

/** The short headline (<= 6-7 words) for the main view. */
export function shortText(t: Dict, it: PlanItem, fmt: (iso: string) => string): string {
  const fn = t.fpl.short[textKey(it)];
  return fn ? fn(ctxOf(t, it, fmt)) : "";
}

/** One detail line carrying the real number behind a step ("Tue 7 Oct · 30 mm rain"), or "". */
export function detailText(t: Dict, it: PlanItem, fmt: (iso: string) => string): string {
  const U = t.fpl.ui;
  const c = ctxOf(t, it, fmt);
  const parts: string[] = [];
  if (it.kind === "activity" && c.activity) parts.push(c.activity);
  if (c.when) parts.push(c.when);
  if (c.rain != null) parts.push(U.rainMm(c.rain));
  else if (c.temp != null) parts.push(`${c.temp}°C`);
  else if (it.kind === "inspect_plants" || it.kind === "watch_spread") parts.push(U.possible);
  return parts.join(" · ");
}
