import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError, type FarmPlan, type PlanInputs, type PlanItem } from "../api";
import { EmptyState, ErrorBox, FarmChips, Page, Spinner } from "../components";
import { useFarms } from "../FarmContext";
import { useLang } from "../LanguageContext";
import { DayPanel } from "../plan/DayPanel";
import { DayPills } from "../plan/DayPills";
import { FieldBackdrop } from "../plan/FieldBackdrop";
import { FieldChips } from "../plan/FieldChips";
import { LayerTag } from "../plan/LayerTag";
import { PlanIcon } from "../plan/icons";
import { buildDays, pickToday, wxKind } from "../plan/planLogic";
import { ChangesBody, CropRow, HistoryRow, IfRows, QuietRow, useDateFmt, useDayParts, WhyBody } from "../plan/PlanView";
import { shortText } from "../plan/planText";
import { Sheet } from "../plan/Sheet";
import { TodayCard } from "../plan/TodayCard";

type SheetState = { kind: "why"; key: string } | { kind: "changes" } | null;

const clean = (i: PlanInputs): PlanInputs => ({
  activities: i.activities.map((a) => ({ id: a.id, kind: a.kind, date: a.date, note: a.note ?? "" })),
  field_condition: i.field_condition || "none",
});

/** Farm plan as a decision interface: the one thing that matters now, the next 5 days, the selected day's actions. Every change
 *  goes through the existing plan API (versions, diff and reasons are the server's); this page only presents and drives it. */
export default function FarmPlanPage() {
  const { t } = useLang();
  const F = t.fpl;
  const U = F.ui;
  const { farms, selected, loading: farmsLoading, error: farmError } = useFarms();
  const [state, setState] = useState<{ farmId: number; plan: FarmPlan | null; error: string | null } | null>(null);
  const [busy, setBusy] = useState(false);
  const [mutating, setMutating] = useState(false);
  const [sel, setSel] = useState<string | null>(null);
  const [sheet, setSheet] = useState<SheetState>(null);
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const [toast, setToast] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const seq = useRef(0);
  const fmt = useDateFmt();
  const dayParts = useDayParts();

  const refresh = useCallback(async (farmId: number) => {
    const mine = ++seq.current;
    setBusy(true);
    try {
      const plan = await api.planRefresh(farmId);
      if (mine === seq.current) setState({ farmId, plan, error: null });
    } catch (e) {
      if (mine === seq.current) setState({ farmId, plan: null, error: e instanceof ApiError ? e.message : F.loadError });
    } finally {
      if (mine === seq.current) setBusy(false);
    }
  }, [F.loadError]);

  useEffect(() => {
    setSel(null);
    setSheet(null);
    setDismissed(new Set());
    if (selected) void refresh(selected.id);
    return () => {
      seq.current++; // switching farm or leaving the page drops anything still in flight
    };
  }, [selected?.id, refresh]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!toast) return;
    const id = setTimeout(() => setToast(null), 4000);
    return () => clearTimeout(id);
  }, [toast]);

  if (farmError) return <ErrorBox message={farmError} />;
  if (farmsLoading || !farms) return <Spinner />;
  if (!selected) {
    return (
      <Page title={F.title} back="/">
        <EmptyState title={t.dash.noFarm} action={<Link to="/farms/new" className="btn-hero">{t.dash.addFarm}</Link>} />
      </Page>
    );
  }
  const cur = state && state.farmId === selected.id ? state : null; // never show another farm's plan while this one loads
  const plan = cur?.plan ?? null;

  async function mutate(fn: (i: PlanInputs) => PlanInputs, message?: string) {
    if (!plan || mutating) return;
    setMutating(true);
    setActionError(null);
    try {
      const next = await api.planInputs(selected!.id, clean(fn(plan.inputs)));
      setState({ farmId: selected!.id, plan: next, error: null });
      if (message) setToast(message);
    } catch (e) {
      setActionError(e instanceof ApiError && e.status !== 422 ? e.message : F.saveError);
    } finally {
      setMutating(false);
    }
  }
  const idOf = (i: PlanItem) => i.key.split(":")[1];
  const addActivity = (kind: string, date: string) => void mutate((i) => ({ ...i, activities: [...i.activities, { kind, date, note: "" }] }));
  const moveActivity = (i: PlanItem, date: string) => void mutate((inp) => ({ ...inp, activities: inp.activities.map((a) => (a.id === idOf(i) ? { ...a, date } : a)) }), U.moved(fmt(date)));
  const removeActivity = (i: PlanItem) => void mutate((inp) => ({ ...inp, activities: inp.activities.filter((a) => a.id !== idOf(i)) }));
  const done = (i: PlanItem) => (i.kind === "activity" ? removeActivity(i) : setDismissed((s) => new Set(s).add(i.key)));

  const days = plan ? buildDays(plan) : [];
  const view = days.find((d) => d.date === sel) ?? days[0];
  const today = plan ? pickToday(plan, dismissed) : null;
  const updated = !!plan && plan.version > 1 && !plan.changes.reasons.includes("first_plan") && plan.changes.items.length > 0;
  const day = view?.day ?? null;
  const dayLabel = view && view.date !== "later" ? dayParts(view.date).label : U.laterTab;
  const sheetItem = plan && sheet?.kind === "why" ? plan.plan.items.find((i) => i.key === sheet.key) ?? null : null;

  return (
    <div className="mx-auto max-w-3xl lg:max-w-6xl" data-testid="farm-plan">
     <div className="grid gap-5 lg:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)] lg:items-start">
      <div className="plan-hero p-3 sm:p-6 lg:sticky lg:top-4" data-testid="plan-hero">
        <FieldBackdrop photo="/img/plan.jpg" />
        <header className="flex items-center gap-2">
          <div className="min-w-0 flex-1">
            <LayerTag k="act" dark />
            <p className="truncate text-xs font-semibold uppercase tracking-widest text-white/80">{selected.name}</p>
            <h1 className="text-xl font-extrabold tracking-tight">{F.title}</h1>
          </div>
          {plan && <span className="rounded-full bg-white/15 px-3 py-1 text-xs font-semibold" data-testid="plan-version-chip">{F.version(plan.version)}</span>}
          <button type="button" onClick={() => void refresh(selected.id)} disabled={busy} aria-label={U.refreshAria} title={U.refreshAria} data-testid="plan-refresh"
            className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-white/15 hover:bg-white/25 disabled:opacity-60">
            <span className={busy ? "animate-spin" : ""}><PlanIcon name="refresh" size={22} /></span>
          </button>
        </header>

        <FarmChips />

        {!plan && !cur?.error && <div className="py-10"><Spinner /></div>}
        {cur?.error && <div className="mt-3"><ErrorBox message={cur.error} /></div>}

        {plan && (
          <div className="mt-3 space-y-3">
            {updated && (
              <button type="button" onClick={() => setSheet({ kind: "changes" })} data-testid="plan-updated-chip"
                className={`inline-flex min-h-[2.75rem] max-w-full items-center gap-2 whitespace-nowrap rounded-full bg-[#ffd166] px-4 text-xs font-bold uppercase tracking-wide text-[#4a3205] ${plan.changed ? "plan-pulse" : ""}`}>
                <PlanIcon name="refresh" size={18} />{U.updated} · {U.updatedBy[plan.changes.reasons[0]] ?? ""}
              </button>
            )}
            <TodayCard plan={plan} item={today} fmt={fmt} onWhy={(i) => setSheet({ kind: "why", key: i.key })} onDone={done} onMove={moveActivity} />
            {day && (
              <ul className="grid grid-cols-3 gap-2" data-testid="day-stats" aria-label={dayLabel}>
                <li className="plan-glass flex items-center gap-2 px-3 py-2"><PlanIcon name="temp" size={20} /><span><b className="block text-lg leading-none">{day.temp_max_c != null ? `${Math.round(day.temp_max_c)}°` : "–"}</b><span className="text-xs text-white/95">{U.temp}</span></span></li>
                <li className="plan-glass flex items-center gap-2 px-3 py-2"><PlanIcon name="drop" size={20} /><span><b className="block text-lg leading-none">{day.rain_mm != null ? `${Math.round(day.rain_mm * 10) / 10}mm` : "–"}</b><span className="text-xs text-white/95">{U.rain}</span></span></li>
                <li className="plan-glass flex items-center gap-2 px-3 py-2"><PlanIcon name="chance" size={20} /><span><b className="block text-lg leading-none">{day.rain_probability_pct != null ? `${Math.round(day.rain_probability_pct)}%` : "–"}</b><span className="text-xs text-white/95">{U.chance}</span></span></li>
              </ul>
            )}
            <DayPills days={days} selected={view?.date ?? ""} onSelect={setSel} fmtDay={dayParts} />
            {!plan.plan.forecast_available && <p className="text-sm text-white/85" data-testid="plan-no-forecast">{F.noForecast}</p>}
            {plan.forecast_source === "last_snapshot" && <p className="text-sm text-white/85" data-testid="plan-snapshot">{F.lastSnapshot}</p>}
            {!selected.location.trim() && <p className="text-sm text-[#ffd166]" data-testid="plan-no-location">{F.locationMissing}</p>}
          </div>
        )}
      </div>

      <div className="min-w-0 space-y-5">
      {toast && <p role="status" aria-live="polite" className="plan-rise -mt-2 rounded-full bg-leaf-800 px-4 py-2 text-center text-sm font-semibold text-white" data-testid="plan-toast">{toast}</p>}
      {actionError && <p role="alert" className="rounded-2xl bg-[#fde3df] px-4 py-2 text-sm font-semibold text-[#7a1f14]">{actionError}</p>}

      {plan && view && (
        <>
          <DayPanel view={view} days={days} plan={plan} fmt={fmt} label={dayLabel} onWhy={(i) => setSheet({ kind: "why", key: i.key })} onAdd={addActivity} onMove={moveActivity} onRemove={removeActivity} busy={mutating} />
          <FieldChips value={plan.inputs.field_condition} busy={mutating} onChange={(v) => void mutate((i) => ({ ...i, field_condition: v }))} />
          <section className="rounded-3xl bg-white px-4 shadow-sm" aria-label={U.rows.about} data-testid="plan-quiet">
            <QuietRow icon="crop" title={U.rows.crop} testId="row-crop"><CropRow plan={plan} /></QuietRow>
            <QuietRow icon="refresh" title={U.rows.ifChange} testId="row-if"><IfRows plan={plan} /></QuietRow>
            <HistoryRow farmId={selected.id} current={plan.version} />
            <QuietRow icon="info" title={U.rows.about} testId="row-about"><p>{F.horizonNote} {F.sub}</p><p className="mt-2 text-sm text-mute">{F.disclaimer}</p></QuietRow>
          </section>
        </>
      )}
      </div>
     </div>

      {plan && sheet?.kind === "why" && sheetItem && (
        <Sheet title={shortText(t, sheetItem, fmt)} onClose={() => setSheet(null)} testId="why-sheet"><WhyBody plan={plan} itemKey={sheetItem.key} fmt={fmt} /></Sheet>
      )}
      {plan && sheet?.kind === "changes" && (
        <Sheet title={U.whatChanged} onClose={() => setSheet(null)} testId="changes-sheet"><ChangesBody plan={plan} fmt={fmt} /></Sheet>
      )}
      <span className="sr-only" aria-hidden="true">{wxKind(day) ?? ""}</span>
    </div>
  );
}
