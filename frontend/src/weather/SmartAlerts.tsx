import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError, type Farm, type PlanItem, type WeatherAlertItem, type WeatherAlerts } from "../api";
import { useLang } from "../LanguageContext";
import { PlanIcon } from "../plan/icons";
import { shortText } from "../plan/planText";
import { Sheet } from "../plan/Sheet";

const ICON: Record<string, string> = { heavy_rain: "rain", thunderstorm: "storm", strong_wind: "wind", high_temperature: "sun", low_temperature: "temp", temperature_change: "temp" };
const SEV_DISC: Record<string, string> = { info: "bg-[#dbe7ef] text-[#1f4e6b]", watch: "bg-[#ffe3a3] text-[#5b3d00]", important: "bg-[#ffc48a] text-[#6b2d00]", severe: "bg-[#f4a39a] text-[#6e160d]" };
const SEV_CHIP: Record<string, string> = { info: "bg-[#e6eef3] text-[#1f4e6b]", watch: "bg-[#fff0c7] text-[#5b3d00]", important: "bg-[#ffe0c2] text-[#6b2d00]", severe: "bg-[#fde3df] text-[#7a1f14]" };
const kmh = (ms: number) => String(Math.round(ms * 3.6));
const n1 = (v: number) => String(Math.round(v * 10) / 10);

/** Smart farm alerts INSIDE the Weather page: the real forecast turned into a few farm-specific alerts, each with its reason, source, freshness and
 *  what it may mean for the Farm plan. The server evaluates (deterministic rules); this only presents, dismisses, and starts the EXISTING plan refresh. */
export function SmartAlerts({ farm }: { farm: Farm }) {
  const { t } = useLang();
  const W = t.wa;
  const [data, setData] = useState<{ farmId: number; value: WeatherAlerts | null; error: boolean } | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const seq = useRef(0);

  const load = useCallback(async () => {
    const mine = ++seq.current;
    try {
      const v = await api.weatherAlerts(farm.id);
      if (mine === seq.current) setData({ farmId: farm.id, value: v, error: false });
    } catch {
      if (mine === seq.current) setData({ farmId: farm.id, value: null, error: true });
    }
  }, [farm.id]);

  useEffect(() => {
    setOpen(null);
    void load();
    return () => {
      seq.current++; // a farm switch (or leaving) drops anything still in flight
    };
  }, [load]);

  useEffect(() => {
    if (!toast) return;
    const id = setTimeout(() => setToast(null), 4500);
    return () => clearTimeout(id);
  }, [toast]);

  const cur = data && data.farmId === farm.id ? data : null;
  const v = cur?.value ?? null;
  const dayLabel = (iso: string, today: string) => {
    const diff = Math.round((new Date(iso + "T00:00:00").getTime() - new Date(today + "T00:00:00").getTime()) / 86400000);
    return diff === 0 ? W.today : diff === 1 ? W.tomorrow : new Date(iso + "T00:00:00").toLocaleDateString(t.locale, { weekday: "long", day: "numeric", month: "short" });
  };
  const fmt = (iso: string) => new Date(iso + "T00:00:00").toLocaleDateString(t.locale, { weekday: "short", day: "numeric", month: "short" });
  const valueLine = (a: WeatherAlertItem): string => {
    const x = a.values;
    switch (a.type) {
      case "heavy_rain": return W.value.heavy_rain(n1(x.rain_mm));
      case "thunderstorm": return W.value.thunderstorm();
      case "strong_wind": return W.value.strong_wind(kmh(x.speed_ms ?? x.gust_ms ?? x.wind_ms ?? 0));
      case "high_temperature": return W.value.high_temperature(n1(x.temp_max_c));
      case "low_temperature": return W.value.low_temperature(n1(x.temp_min_c));
      default: return W.value.temperature_change(n1(x.previous_max_c), n1(x.temp_max_c));
    }
  };

  async function dismiss(a: WeatherAlertItem) {
    try {
      await api.dismissWeatherAlert(farm.id, a.id);
      setOpen(null);
      await load();
    } catch {
      setToast(W.loadError);
    }
  }
  async function refreshPlan() {
    if (busy) return;
    setBusy(true);
    try {
      const p = await api.planRefresh(farm.id);
      setToast(W.refreshed(p.changed, p.version));
      setOpen(null); // the answer is shown on the page; the sheet's job is done
      await load();
    } catch (e) {
      setToast(e instanceof ApiError ? e.message : W.refreshFailed);
    } finally {
      setBusy(false);
    }
  }

  const fr = v?.freshness;
  const freshLine = !fr ? "" : fr.state === "live" ? W.fresh.live(W.ago(fr.age_minutes ?? 0), W.src[fr.source ?? ""] ?? "") : fr.state === "stale" ? W.fresh.stale(W.ago(fr.age_minutes ?? 0))
    : fr.state === "no_location" ? W.fresh.noLocation : W.fresh.unavailable + (fr.last_known_at ? " " + W.fresh.lastKnown(new Date(fr.last_known_at).toLocaleString(t.locale, { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" })) : "");
  const sel = v?.alerts.find((a) => a.id === open) ?? null;

  return (
    <section className="space-y-2 rounded-2xl bg-white p-3 ring-1 ring-line" aria-label={W.title} data-testid="smart-alerts" data-farm={farm.id}>
      <div className="flex items-center gap-2">
        <span aria-hidden className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-leaf-800 text-[#c8f169]"><PlanIcon name="warn" size={18} /></span>
        <h3 className="text-base font-extrabold text-leaf-800">{W.title}</h3>
      </div>
      {!cur && <p role="status" className="text-sm text-mute">{W.loading}</p>}
      {cur?.error && <p role="alert" className="text-sm text-[#7a1f14]">{W.loadError}</p>}
      {v && (
        <>
          <p className={`text-xs ${fr?.state === "live" ? "text-mute" : "font-semibold text-amber-900"}`} data-testid="alerts-freshness" data-state={fr?.state}>{freshLine}</p>
          {toast && <p role="status" aria-live="polite" className="rounded-full bg-leaf-800 px-3 py-1.5 text-center text-sm font-semibold text-white" data-testid="alerts-toast">{toast}</p>}
          {v.alerts.length === 0 ? (
            fr?.state === "live" ? <p className="rounded-2xl bg-leaf-50 px-3 py-3 text-sm text-leaf-900" data-testid="alerts-none">{W.none}</p> : null
          ) : (
            <ul className="space-y-2" data-testid="alerts-list">
              {v.alerts.map((a) => {
                const affects = !!a.plan_impact && a.plan_impact.affected.length > 0;
                return (
                  <li key={a.id} className="rounded-2xl bg-leaf-50 p-3" data-testid="alert-card" data-type={a.type} data-severity={a.severity} data-status={a.status}>
                    <div className="flex items-start gap-3">
                      <span aria-hidden className={`grid h-11 w-11 shrink-0 place-items-center rounded-full ${SEV_DISC[a.severity]}`}><PlanIcon name={ICON[a.type] ?? "warn"} size={24} /></span>
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <p className="text-base font-extrabold leading-tight text-ink">{W.kind[a.type]}</p>
                          <span className={`rounded-full px-2 py-0.5 text-xs font-bold ${SEV_CHIP[a.severity]}`} data-testid="alert-severity">{W.severity[a.severity]}</span>
                          {a.status === "updated" && <span className="rounded-full bg-white px-2 py-0.5 text-xs font-semibold text-mute">{W.status.updated}</span>}
                        </div>
                        <p className="text-lg font-extrabold text-leaf-800" data-testid="alert-value">{valueLine(a)}</p>
                        <p className="text-sm text-mute">{farm.name} · {dayLabel(a.event_date, v.today)}</p>
                        {affects && <p className="mt-1 inline-flex items-center gap-1.5 rounded-full bg-[#fff0c7] px-2.5 py-1 text-xs font-bold text-[#5b3d00]" data-testid="alert-plan-chip"><PlanIcon name="refresh" size={14} />{W.planChip}</p>}
                        {a.plan_impact?.plan_may_be_outdated && <p className="mt-1 text-xs font-semibold text-amber-900">{W.planOutdated}</p>}
                      </div>
                    </div>
                    <div className="mt-2 flex flex-wrap gap-2">
                      <button type="button" onClick={() => setOpen(a.id)} className="pillbtn" data-testid="alert-why"><PlanIcon name="info" size={16} />{W.why}</button>
                      {affects && <Link to="/plan" className="pillbtn !bg-[#c8f169] !border-[#c8f169] font-extrabold text-leaf-900" data-testid="alert-review-plan">{W.reviewPlan}</Link>}
                    </div>
                  </li>
                );
              })}
            </ul>
          )}

          {v.recent.length > 0 && (
            <details className="plan-row rounded-2xl bg-leaf-50 px-3" data-testid="alerts-recent">
              <summary className="flex min-h-[2.75rem] cursor-pointer list-none items-center justify-between gap-2 text-sm font-bold text-leaf-800 [&::-webkit-details-marker]:hidden">{W.recent}<span className="plan-chev text-mute"><PlanIcon name="chevron" size={18} /></span></summary>
              <ul className="space-y-1 pb-3 text-sm">
                {v.recent.map((a) => <li key={a.id} className="flex flex-wrap justify-between gap-2"><span>{W.kind[a.type]} · {fmt(a.event_date)}</span><span className="text-mute">{W.resolved}</span></li>)}
              </ul>
            </details>
          )}

          <details className="plan-row rounded-2xl bg-leaf-50 px-3" data-testid="alerts-prepared">
            <summary className="flex min-h-[2.75rem] cursor-pointer list-none items-center justify-between gap-2 text-sm font-bold text-leaf-800 [&::-webkit-details-marker]:hidden">{W.prepared}<span className="plan-chev text-mute"><PlanIcon name="chevron" size={18} /></span></summary>
            <ol className="space-y-1 pb-2 text-sm" data-testid="alerts-steps">
              {v.steps.map((s) => {
                const note = s.node === "evaluate" && s.status === "ok" ? W.evalNote(s.note) : s.node === "reconcile" && s.status === "ok" ? W.reconNote(...(s.note.split("/") as [string, string, string]))
                  : s.node === "plan_check" && s.status === "ok" ? W.planVersion(s.note) : W.stepNote[s.note] ?? "";
                return <li key={s.node} data-node={s.node} data-status={s.status}><span aria-hidden>{s.status === "ok" ? "✓ " : "○ "}</span><b>{W.stepName[s.node]}</b> <span className="text-mute">· {W.stepState[s.status]}{note ? ` · ${note}` : ""}</span></li>;
              })}
            </ol>
            <p className="pb-3 text-xs text-mute">{W.preparedNote}</p>
          </details>
        </>
      )}

      {sel && v && (
        <Sheet title={W.kind[sel.type]} onClose={() => setOpen(null)} testId="alert-sheet">
          <div className="space-y-4 text-white" data-testid="alert-detail">
            <p className="text-2xl font-extrabold">{valueLine(sel)}</p>
            <section>
              <h3 className="mb-1 text-xs font-bold uppercase tracking-widest text-white/70">{W.whyAlert}</h3>
              <p className="text-base">{W.matters[sel.type]}</p>
              <dl className="mt-2 grid grid-cols-2 gap-2 text-sm">
                <div className="rounded-2xl bg-white/10 p-2"><dt className="text-white/70">{W.forecastDay}</dt><dd className="font-bold">{dayLabel(sel.event_date, v.today)} · {fmt(sel.event_date)}</dd></div>
                <div className="rounded-2xl bg-white/10 p-2"><dt className="text-white/70">{W.severityLabel}</dt><dd className="font-bold" data-testid="detail-severity">{W.severity[sel.severity]}</dd></div>
                <div className="rounded-2xl bg-white/10 p-2"><dt className="text-white/70">{W.sourceLabel}</dt><dd className="font-bold" data-testid="detail-source">{W.src[sel.source ?? ""] ?? "—"}</dd></div>
                <div className="rounded-2xl bg-white/10 p-2"><dt className="text-white/70">{W.updatedLabel}</dt><dd className="font-bold">{sel.forecast_fetched_at ? W.ago(Math.max(0, Math.round((Date.now() - new Date(sel.forecast_fetched_at).getTime()) / 60000))) : "—"}</dd></div>
              </dl>
            </section>
            <section>
              <h3 className="mb-1 text-xs font-bold uppercase tracking-widest text-white/70">{W.farmImpact}</h3>
              <p className="text-base">{W.farmLine(v.farm.name, v.farm.location)}{v.farm.crop ? ` ${W.cropLine(v.farm.crop)}` : ""}</p>
            </section>
            <section data-testid="detail-plan-impact">
              <h3 className="mb-1 text-xs font-bold uppercase tracking-widest text-white/70">{W.planImpact}</h3>
              {!sel.plan_impact?.has_plan ? <p className="text-base">{W.planNone}</p> : sel.plan_impact.affected.length === 0 ? <p className="text-base">{W.planNothing}</p> : (
                <>
                  <p className="text-base">{W.planItems(sel.plan_impact.affected.length)}</p>
                  <ul className="mt-1 space-y-1">
                    {sel.plan_impact.affected.map((it) => {
                      const pi: PlanItem = { key: it.key, kind: it.kind, section: "next", status: it.status ?? "consider", when: it.when, reasons: [], params: { activity: it.activity ?? "other" }, check_id: null };
                      const label = it.kind === "activity" ? `${t.fpl.act[it.activity ?? "other"] ?? it.activity}${it.when ? ` · ${fmt(it.when)}` : ""}` : shortText(t, pi, fmt);
                      return <li key={it.key} className="rounded-2xl bg-white/10 px-3 py-2 text-sm font-semibold" data-testid="affected-item">{label}</li>;
                    })}
                  </ul>
                </>
              )}
              {sel.plan_impact?.plan_may_be_outdated && <p className="mt-2 text-base text-[#ffd166]">{W.planOutdatedText}</p>}
              <p className="mt-2 text-sm text-white/75">{W.planNote}</p>
            </section>
            <div className="flex flex-wrap gap-2 pt-1">
              <Link to="/plan" className="inline-flex min-h-[2.75rem] items-center rounded-full bg-[#c8f169] px-5 text-sm font-extrabold text-leaf-900" data-testid="detail-view-plan">{W.viewPlan}</Link>
              {sel.plan_impact?.has_plan && <button type="button" aria-disabled={busy} onClick={() => void refreshPlan()} className={`inline-flex min-h-[2.75rem] items-center rounded-full bg-white/15 px-5 text-sm font-bold text-white ${busy ? "opacity-60" : ""}`} data-testid="detail-refresh-plan">{busy ? W.refreshing : W.refreshPlan}</button>}
              <button type="button" onClick={() => void dismiss(sel)} className="inline-flex min-h-[2.75rem] items-center rounded-full bg-white/15 px-5 text-sm font-bold text-white" data-testid="detail-dismiss">{W.dismiss}</button>
            </div>
          </div>
        </Sheet>
      )}
    </section>
  );
}
