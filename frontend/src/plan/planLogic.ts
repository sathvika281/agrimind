import type { FarmPlan, PlanDay, PlanItem } from "../api";

// The client mirrors the planning agent's named thresholds ONLY to suggest a "Move to <day>" target from the real forecast.
// The agent (backend/app/services/planning/agent.py) stays the source of truth; scripts/plan.test.mjs checks these stay equal.
export const SIGNIFICANT_RAIN_MM = 10;
export const WET_FIELD_PREV_DAY_MM = 25;
export const DRY_DAY_MM = 3;
export const HOT_C = 35;

export type Wx = "sun" | "partly" | "rain" | "storm";

export function wxKind(d: PlanDay | null | undefined): Wx | null {
  if (!d) return null;
  const r = d.rain_mm ?? 0;
  if (r >= SIGNIFICANT_RAIN_MM) return "storm";
  if (r >= DRY_DAY_MM) return "rain";
  if (r >= 1 || (d.rain_probability_pct ?? 0) >= 50) return "partly";
  return "sun";
}

export interface DayView {
  date: string; // YYYY-MM-DD, or "later" for steps beyond the forecast
  day: PlanDay | null;
  items: PlanItem[]; // that day's steps (never the standing "if conditions change" notes)
  changed: boolean; // touched by the last re-plan
}

const iso = (d: Date) => d.toISOString().slice(0, 10);
const addDays = (s: string, n: number) => iso(new Date(new Date(s + "T00:00:00Z").getTime() + n * 86400000));

/** The days to show: the real forecast days from today on, or just the next five dates when there is no forecast. */
export function buildDays(plan: FarmPlan): DayView[] {
  const start = plan.plan.generated_for;
  const real = plan.forecast.filter((d) => d.date >= start).sort((a, b) => a.date.localeCompare(b.date));
  const dates = real.length ? real.map((d) => d.date) : [0, 1, 2, 3, 4].map((n) => addDays(start, n));
  const touched = new Set<string>();
  if (plan.version > 1 && !plan.changes.reasons.includes("first_plan")) {
    for (const c of plan.changes.items) {
      if (c.after?.when) touched.add(c.after.when);
      if (c.before?.when) touched.add(c.before.when);
    }
  }
  const steps = plan.plan.items.filter((i) => i.section !== "if");
  const views: DayView[] = dates.map((date) => ({
    date,
    day: real.find((d) => d.date === date) ?? null,
    items: steps.filter((i) => i.when === date || (!i.when && date === dates[0])),
    changed: touched.has(date),
  }));
  const beyond = steps.filter((i) => i.when && !dates.includes(i.when));
  if (beyond.length) views.push({ date: "later", day: null, items: beyond, changed: false });
  return views;
}

const STATUS_RANK: Record<string, number> = { hold: 0, reconsider: 0, do_now: 1, cool_hours: 2, consider: 3, supported: 4, info: 5, unassessed: 6 };

/** The one thing that matters most right now (red first, then do-now, then amber), skipping what the farmer dismissed. */
export function pickToday(plan: FarmPlan, dismissed: Set<string>): PlanItem | null {
  const steps = plan.plan.items.filter((i) => i.section !== "if" && !dismissed.has(i.key));
  steps.sort((a, b) => (STATUS_RANK[a.status] ?? 9) - (STATUS_RANK[b.status] ?? 9) || (a.when ?? "").localeCompare(b.when ?? "") || a.key.localeCompare(b.key));
  return steps[0] ?? null;
}

export const tone = (status: string): "red" | "amber" | "green" | "grey" =>
  status === "hold" || status === "reconsider" ? "red" : status === "do_now" || status === "consider" || status === "cool_hours" ? "amber" : status === "supported" || status === "info" ? "green" : "grey";

/** The nearest day that the forecast supports for an activity (not heavy rain, not right after a very wet day, not hot). */
export function bestMoveDay(plan: FarmPlan, item: PlanItem): string | null {
  const from = typeof item.params.date === "string" ? item.params.date : item.when;
  if (!from) return null;
  const days = plan.forecast.filter((d) => d.date >= plan.plan.generated_for);
  const byDate = new Map(days.map((d) => [d.date, d]));
  const ok = (d: PlanDay) => {
    const prev = byDate.get(addDays(d.date, -1));
    return (d.rain_mm ?? 0) < SIGNIFICANT_RAIN_MM && (!prev || (prev.rain_mm ?? 0) < WET_FIELD_PREV_DAY_MM) && (d.temp_max_c ?? 0) < HOT_C;
  };
  const good = days.filter((d) => d.date !== from && ok(d));
  if (!good.length) return null;
  const dist = (d: PlanDay) => Math.abs(new Date(d.date).getTime() - new Date(from).getTime());
  const after = good.filter((d) => d.date > from);
  return (after.length ? after : good).sort((a, b) => dist(a) - dist(b))[0].date;
}
