import type { FarmPlan, PlanItem } from "../api";
import { useLang } from "../LanguageContext";
import { ACTIVITY_ICON, KIND_ICON, PlanIcon } from "./icons";
import { bestMoveDay, tone } from "./planLogic";
import { detailText, shortText } from "./planText";

const DISC: Record<string, string> = {
  red: "bg-[#ff8a7a] text-[#4a0f08]",
  amber: "bg-[#ffd166] text-[#4a3205]",
  green: "bg-[#c8f169] text-[#0b2d20]",
  grey: "bg-white/80 text-[#0b2d20]",
};

/** THE decision: one thing that matters right now, in a few words, with the real number behind it. */
export function TodayCard({ plan, item, fmt, onWhy, onDone, onMove }: {
  plan: FarmPlan;
  item: PlanItem | null;
  fmt: (iso: string) => string;
  onWhy: (i: PlanItem) => void;
  onDone: (i: PlanItem) => void;
  onMove: (i: PlanItem, date: string) => void;
}) {
  const { t } = useLang();
  const U = t.fpl.ui;
  if (!item) return null;
  const start = plan.plan.generated_for;
  const tomorrow = new Date(new Date(start + "T00:00:00Z").getTime() + 86400000).toISOString().slice(0, 10);
  const eyebrow = !item.when || item.when === start ? U.today : item.when === tomorrow ? U.tomorrow : fmt(item.when);
  const isActivity = item.kind === "activity";
  const moveTo = isActivity && item.status === "reconsider" ? bestMoveDay(plan, item) : null;
  const routine = item.kind === "monitor_routine";
  const icon = isActivity ? ACTIVITY_ICON[String(item.params.activity)] ?? "other" : KIND_ICON[item.kind] ?? "info";
  const tn = tone(item.status);
  const headline = routine ? U.allGood : shortText(t, item, fmt);
  const detail = routine ? U.routineDetail : detailText(t, item, fmt);
  return (
    <section className="plan-glass plan-rise p-4" aria-label={headline} data-testid="today-card" data-key={item.key} data-status={item.status} data-tone={tn}>
      <div className="flex items-start gap-3">
        <span className={`grid h-14 w-14 shrink-0 place-items-center rounded-full ${DISC[tn]}`} data-testid="today-icon"><PlanIcon name={tn === "red" && !isActivity ? "hold" : icon} size={28} /></span>
        <div className="min-w-0 flex-1">
          <p className="text-xs font-semibold uppercase tracking-widest text-white/80" data-testid="today-eyebrow">{eyebrow}</p>
          <h2 className="break-words text-2xl font-extrabold uppercase leading-tight tracking-tight" data-testid="today-headline">{headline}</h2>
          {detail && <p className="mt-0.5 text-base text-white/90" data-testid="today-detail">{detail}</p>}
        </div>
      </div>
      <div className="mt-4 flex flex-wrap gap-2">
        {moveTo ? (
          <button type="button" className="plan-lime inline-flex min-h-[2.75rem] items-center gap-2 rounded-full px-5 text-base font-bold" onClick={() => onMove(item, moveTo)} data-testid="today-move">
            <PlanIcon name="arrow" size={18} />{U.moveTo(fmt(moveTo).split(",")[0])}
          </button>
        ) : (
          <button type="button" className="plan-lime inline-flex min-h-[2.75rem] items-center gap-2 rounded-full px-5 text-base font-bold" onClick={() => onDone(item)} data-testid="today-done">
            <PlanIcon name="check" size={18} />{isActivity ? U.done : U.gotIt}
          </button>
        )}
        <button type="button" className="inline-flex min-h-[2.75rem] items-center gap-2 rounded-full border border-white/40 px-5 text-base font-semibold text-white hover:bg-white/10" onClick={() => onWhy(item)} data-testid="today-why">
          <PlanIcon name="info" size={18} />{U.why}
        </button>
        {moveTo && isActivity && (
          <button type="button" className="inline-flex min-h-[2.75rem] items-center gap-2 rounded-full border border-white/40 px-5 text-base font-semibold text-white hover:bg-white/10" onClick={() => onDone(item)} data-testid="today-done">
            <PlanIcon name="check" size={18} />{U.done}
          </button>
        )}
      </div>
    </section>
  );
}
