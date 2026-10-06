import type { FarmPlan, PlanItem } from "../api";
import { useLang } from "../LanguageContext";
import { ACTIVITY_ICON, KIND_ICON, PlanIcon } from "./icons";
import { tone, type DayView } from "./planLogic";
import { shortText } from "./planText";

const DOT: Record<string, string> = { red: "bg-[#c0392b]", amber: "bg-[#d9a233]", green: "bg-[#2f8f55]", grey: "bg-[#9aa59f]" };
const KINDS = ["sowing", "irrigation", "weeding", "harvest", "other"] as const;

/** The selected day: its steps as short rows (tap "?" for the reason) and one-tap icons to add an activity. */
export function DayPanel({ view, days, fmt, label, onWhy, onAdd, onMove, onRemove, busy }: {
  view: DayView;
  days: DayView[];
  plan: FarmPlan;
  fmt: (iso: string) => string;
  label: string;
  onWhy: (i: PlanItem) => void;
  onAdd: (kind: string, date: string) => void;
  onMove: (i: PlanItem, date: string) => void;
  onRemove: (i: PlanItem) => void;
  busy: boolean;
}) {
  const { t } = useLang();
  const U = t.fpl.ui;
  const real = days.filter((d) => d.date !== "later");
  const idx = real.findIndex((d) => d.date === view.date);
  const earlier = idx > 0 ? real[idx - 1].date : null;
  const later = idx >= 0 && idx < real.length - 1 ? real[idx + 1].date : null;
  const canAdd = view.date !== "later";
  return (
    <section className="plan-fade space-y-3" aria-label={label} role="tabpanel" data-testid="day-panel" data-date={view.date} key={view.date}>
      <h2 className="text-xs font-bold uppercase tracking-widest text-mute" aria-label={`${U.actions}: ${label}`}><span data-testid="day-label">{label}</span></h2>
      {view.items.length === 0 ? (
        <p className="rounded-2xl bg-white px-4 py-3 text-base text-mute shadow-sm" data-testid="day-empty">{U.nothingPlanned}</p>
      ) : (
        <ul className="space-y-2">
          {view.items.map((it) => {
            const isAct = it.kind === "activity";
            const icon = isAct ? ACTIVITY_ICON[String(it.params.activity)] ?? "other" : KIND_ICON[it.kind] ?? "info";
            return (
              <li key={it.key} className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-2xl bg-white px-3 py-2 shadow-sm" data-testid="day-action" data-key={it.key} data-kind={it.kind} data-status={it.status}>
                <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${DOT[tone(it.status)]}`} aria-hidden="true" />
                <span className="text-leaf-700"><PlanIcon name={icon} size={22} /></span>
                <span className="min-w-0 flex-1 break-words text-base font-semibold text-ink">{shortText(t, it, fmt)}</span>
                <button type="button" onClick={() => onWhy(it)} aria-label={`${U.why} ${shortText(t, it, fmt)}`} className="grid h-11 w-11 shrink-0 place-items-center rounded-full text-leaf-700 hover:bg-leaf-50" data-testid="action-why">
                  <PlanIcon name="info" size={22} />
                </button>
                {isAct && (
                  <div className="flex w-full items-center justify-end gap-1">
                    <button type="button" disabled={!earlier || busy} onClick={() => earlier && onMove(it, earlier)} aria-label={U.earlier} className="grid h-11 w-11 place-items-center rounded-full border border-line text-leaf-700 disabled:opacity-30" data-testid="action-earlier"><PlanIcon name="left" size={20} /></button>
                    <button type="button" disabled={!later || busy} onClick={() => later && onMove(it, later)} aria-label={U.later} className="grid h-11 w-11 place-items-center rounded-full border border-line text-leaf-700 disabled:opacity-30" data-testid="action-later"><PlanIcon name="right" size={20} /></button>
                    <button type="button" disabled={busy} onClick={() => onRemove(it)} aria-label={U.remove} className="grid h-11 w-11 place-items-center rounded-full border border-line text-[#a63a30]" data-testid="action-remove"><PlanIcon name="close" size={20} /></button>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {canAdd && (
        <div>
          <h3 className="mb-1.5 text-xs font-bold uppercase tracking-widest text-mute">{U.addActivity}</h3>
          <div className="grid grid-cols-5 gap-2" data-testid="add-activity">
            {KINDS.map((k) => (
              <button key={k} type="button" disabled={busy} onClick={() => onAdd(k, view.date)} data-testid={`add-${k}`}
                className="flex min-h-[4rem] min-w-0 flex-col items-center justify-center gap-1 rounded-2xl border border-leaf-200 bg-white px-1 py-2 text-leaf-800 shadow-sm transition active:scale-95 hover:border-leaf-500 disabled:opacity-50">
                <PlanIcon name={ACTIVITY_ICON[k]} size={24} />
                <span className="w-full truncate text-xs font-semibold">{t.fpl.act[k]}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
