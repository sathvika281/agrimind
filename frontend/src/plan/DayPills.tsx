import { useRef } from "react";
import { useLang } from "../LanguageContext";
import { ACTIVITY_ICON, PlanIcon } from "./icons";
import { HOT_C, wxKind, type DayView } from "./planLogic";

const WX_ICON = { sun: "sun", partly: "partly", rain: "rain", storm: "storm" } as const;

/** The 5-day timeline: large tappable pills built from the real forecast. Tapping one switches the panel below in place. */
export function DayPills({ days, selected, onSelect, fmtDay }: { days: DayView[]; selected: string; onSelect: (d: string) => void; fmtDay: (iso: string) => { weekday: string; label: string } }) {
  const { t } = useLang();
  const U = t.fpl.ui;
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});
  function onKey(e: React.KeyboardEvent) {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    const i = days.findIndex((d) => d.date === selected);
    const next = days[Math.min(days.length - 1, Math.max(0, i + (e.key === "ArrowRight" ? 1 : -1)))];
    if (next) {
      e.preventDefault();
      onSelect(next.date);
      refs.current[next.date]?.focus();
    }
  }
  return (
    <div role="tablist" aria-label={t.fpl.forecastTitle} className="plan-glass grid gap-1.5 p-2" style={{ gridTemplateColumns: `repeat(${days.length}, minmax(0, 1fr))` }} onKeyDown={onKey} data-testid="day-pills">
      {days.map((d) => {
        const on = d.date === selected;
        const wx = wxKind(d.day);
        const hot = (d.day?.temp_max_c ?? 0) >= HOT_C;
        const f = d.date === "later" ? null : fmtDay(d.date);
        const acts = d.items.filter((i) => i.kind === "activity");
        const label = U.dayAria(f ? f.label : U.laterTab, wx ? U.wx[wx] : U.wx.none);
        return (
          <button
            key={d.date}
            ref={(el) => { refs.current[d.date] = el; }}
            type="button"
            role="tab"
            aria-selected={on}
            aria-label={label}
            tabIndex={on ? 0 : -1}
            onClick={() => onSelect(d.date)}
            data-testid="day-pill"
            data-date={d.date}
            data-selected={on}
            data-changed={d.changed}
            className={`relative flex min-h-[6rem] min-w-0 flex-col items-center justify-between gap-0.5 rounded-2xl px-1 py-2 text-center transition-all duration-150 ${on ? "plan-lime -translate-y-0.5 scale-[1.03] shadow-lg" : "text-white hover:bg-white/10"}`}
          >
            <span className="text-xs font-bold uppercase tracking-wider">{f ? f.weekday : U.laterTab}</span>
            {wx ? <PlanIcon name={WX_ICON[wx]} size={26} /> : <span className="grid h-[26px] place-items-center text-xs opacity-80">{d.date === "later" ? "…" : U.noForecast.split(" ")[0]}</span>}
            <span className={`text-base font-extrabold leading-none ${hot && !on ? "text-[#ffd166]" : ""}`}>{d.day?.temp_max_c != null ? `${Math.round(d.day.temp_max_c)}°` : "–"}</span>
            <span className="min-h-[12px] text-xs leading-none opacity-95">{d.day?.rain_mm != null && d.day.rain_mm >= 0.5 ? `${Math.round(d.day.rain_mm * 10) / 10}mm` : ""}</span>
            <span className="flex min-h-[14px] items-center justify-center gap-0.5">
              {acts.slice(0, 3).map((a) => <PlanIcon key={a.key} name={ACTIVITY_ICON[String(a.params.activity)] ?? "other"} size={13} />)}
            </span>
            {d.changed && <span aria-hidden="true" className="plan-pulse absolute -right-1 -top-2 grid h-5 w-5 place-items-center rounded-full bg-[#ffd166] text-[#4a3205] ring-2 ring-[#14472f]" data-testid="pill-changed"><PlanIcon name="refresh" size={12} /></span>}
          </button>
        );
      })}
    </div>
  );
}
