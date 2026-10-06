import { useState } from "react";
import { Link } from "react-router-dom";
import { api, type FarmPlan, type PlanVersion } from "../api";
import { useLang } from "../LanguageContext";
import { PlanIcon, ACTIVITY_ICON, KIND_ICON } from "./icons";
import { tone } from "./planLogic";
import { itemText, shortText } from "./planText";

const scriptOf = (text: string): "te" | "en" => (/[ఀ-౿]/.test(text) ? "te" : "en");
const TONE_CHIP: Record<string, string> = { red: "bg-[#fde3df] text-[#7a1f14]", amber: "bg-[#fff0c7] text-[#5b3d00]", green: "bg-[#dff3e5] text-[#14573a]", grey: "bg-[#ecefed] text-[#3c4a43]" };

export function useDateFmt() {
  const { t } = useLang();
  return (iso: string) => new Date(iso + "T00:00:00").toLocaleDateString(t.locale, { weekday: "short", day: "numeric", month: "short" });
}

export function useDayParts() {
  const { t } = useLang();
  return (iso: string) => {
    const d = new Date(iso + "T00:00:00");
    return { weekday: d.toLocaleDateString(t.locale, { weekday: "short" }), label: d.toLocaleDateString(t.locale, { weekday: "long", day: "numeric", month: "short" }) };
  };
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-4 first:mt-0">
      <h3 className="mb-1 text-xs font-bold uppercase tracking-widest text-white/70">{title}</h3>
      {children}
    </section>
  );
}

/** Everything behind "Why?": the existing explanation, the real numbers, the crop evidence and the safety wording. */
export function WhyBody({ plan, itemKey, fmt }: { plan: FarmPlan; itemKey: string; fmt: (iso: string) => string }) {
  const { t } = useLang();
  const F = t.fpl;
  const U = F.ui;
  const it = plan.plan.items.find((i) => i.key === itemKey);
  if (!it) return null;
  const day = it.when ? plan.forecast.find((d) => d.date === it.when) : undefined;
  const c = plan.plan.concern;
  return (
    <div className="text-white" data-testid="why-body">
      <p className="text-base leading-relaxed" data-testid="why-sentence">{itemText(t, it, fmt)}</p>
      {day && (
        <Section title={`${U.weatherHeading} · ${fmt(day.date)}`}>
          <ul className="grid grid-cols-3 gap-2 text-center" data-testid="why-weather">
            <li className="rounded-2xl bg-white/10 p-2"><PlanIcon name="drop" size={18} /><p className="text-lg font-extrabold">{day.rain_mm != null ? Math.round(day.rain_mm * 10) / 10 : "–"}<span className="text-xs font-semibold"> mm</span></p><p className="text-xs text-white/75">{U.rain}</p></li>
            <li className="rounded-2xl bg-white/10 p-2"><PlanIcon name="temp" size={18} /><p className="text-lg font-extrabold">{day.temp_max_c != null ? `${Math.round(day.temp_max_c)}°` : "–"}</p><p className="text-xs text-white/75">{U.temp}</p></li>
            <li className="rounded-2xl bg-white/10 p-2"><PlanIcon name="chance" size={18} /><p className="text-lg font-extrabold">{day.rain_probability_pct != null ? `${Math.round(day.rain_probability_pct)}%` : "–"}</p><p className="text-xs text-white/75">{U.chance}</p></li>
          </ul>
        </Section>
      )}
      {it.check_id && (c.level === "possible" || c.level === "unclear") && (
        <Section title={U.cropHeading}>
          <p className="text-base" lang={scriptOf(c.issue)}>{c.level === "possible" && c.issue ? F.cropPossible(c.issue) : F.cropUnclear}</p>
          <Link to={`/analyses/${it.check_id}`} className="mt-1 inline-flex min-h-[2.75rem] items-center gap-1.5 text-base font-semibold text-[#c8f169] underline">
            <PlanIcon name="link" size={18} />{F.openCheck}
          </Link>
        </Section>
      )}
      {c.farmer_reported && F.farmerReported[c.farmer_reported] && it.reasons.includes("possible_problem") && <p className="mt-2 text-base">{F.farmerReported[c.farmer_reported]}</p>}
      {c.level === "possible" && plan.plan.sources.length > 0 && it.check_id && (
        <Section title={U.sourcesHeading}>
          <ul className="space-y-1 text-sm" data-testid="why-sources">
            {plan.plan.sources.map((s) => (
              <li key={s.url}><a href={s.url} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-[2.75rem] items-center font-semibold text-[#c8f169] underline">{s.title}</a> <span className="text-white/70">{s.institution}</span></li>
            ))}
          </ul>
        </Section>
      )}
      <p className="mt-4 border-t border-white/15 pt-3 text-sm text-white/75" data-testid="why-disclaimer">{F.disclaimer}</p>
    </div>
  );
}

/** What changed: before -> after for each affected step, and the real reason (numbers from the plan's own items). */
export function ChangesBody({ plan, fmt }: { plan: FarmPlan; fmt: (iso: string) => string }) {
  const { t } = useLang();
  const F = t.fpl;
  const U = F.ui;
  const c = plan.changes;
  const byKey = new Map(plan.plan.items.map((i) => [i.key, i]));
  const facts: string[] = [];
  if (c.reasons.includes("forecast_change")) {
    for (const i of plan.plan.items) {
      const mm = typeof i.params.rain_mm === "number" ? Math.round(i.params.rain_mm * 10) / 10 : null;
      const when = (typeof i.params.date === "string" ? i.params.date : i.when) ?? "";
      if (mm != null && when && (i.status === "hold" || i.status === "reconsider")) facts.push(U.rainFor(fmt(when), mm));
      if (typeof i.params.temp_max_c === "number" && i.status === "cool_hours" && when) facts.push(U.hotFor(fmt(when), Math.round(i.params.temp_max_c * 10) / 10));
    }
  }
  return (
    <div className="text-white" data-testid="changes-body">
      {c.items.length === 0 ? <p className="text-base">{U.noneChanged}</p> : (
        <ul className="space-y-3">
          {c.items.map((x) => {
            const it = byKey.get(x.key);
            const label = it ? shortText(t, it, fmt) : F.short[x.kind]?.({ when: "", activity: "" }) ?? x.kind;
            const icon = it?.kind === "activity" ? ACTIVITY_ICON[String(it.params.activity)] ?? "other" : KIND_ICON[x.kind] ?? "info";
            return (
              <li key={x.key} className="rounded-2xl bg-white/10 p-3" data-testid="change-row" data-change={x.change} data-key={x.key}>
                <p className="flex items-center gap-2 text-base font-semibold"><PlanIcon name={icon} size={20} />{label}</p>
                <p className="mt-1 flex flex-wrap items-center gap-2 text-sm">
                  <span className="text-white/70">{F.change[x.change]}</span>
                  {x.before && <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${TONE_CHIP[tone(x.before.status)]}`}>{U.before}: {F.status[x.before.status] ?? x.before.status}</span>}
                  {x.before && x.after && <PlanIcon name="arrow" size={16} />}
                  {x.after && <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${TONE_CHIP[tone(x.after.status)]}`}>{U.after}: {F.status[x.after.status] ?? x.after.status}</span>}
                </p>
              </li>
            );
          })}
        </ul>
      )}
      <section className="mt-4">
        <h3 className="mb-1 text-xs font-bold uppercase tracking-widest text-white/70">{U.whyHeading}</h3>
        <ul className="list-disc space-y-1 pl-5 text-base" data-testid="changes-why">
          {[...new Set(facts)].slice(0, 3).map((f) => <li key={f}>{f}</li>)}
          {c.reasons.map((r) => (F.reasons[r] ? <li key={r}>{F.reasons[r][0].toUpperCase() + F.reasons[r].slice(1)}</li> : null))}
        </ul>
      </section>
    </div>
  );
}

/** One quiet chevron row that opens in place. */
export function QuietRow({ icon, title, children, testId, onToggle }: { icon: string; title: string; children: React.ReactNode; testId: string; onToggle?: (open: boolean) => void }) {
  return (
    <details className="plan-row group border-b border-line last:border-0" data-testid={testId} onToggle={(e) => onToggle?.((e.currentTarget as HTMLDetailsElement).open)}>
      <summary className="flex min-h-[3rem] cursor-pointer list-none items-center gap-3 py-0 text-base font-semibold text-ink [&::-webkit-details-marker]:hidden">
        <span className="text-leaf-700"><PlanIcon name={icon} size={22} /></span>
        <span className="flex-1">{title}</span>
        <span className="plan-chev text-mute"><PlanIcon name="chevron" size={20} /></span>
      </summary>
      <div className="pb-3 pl-9 text-base text-ink/90">{children}</div>
    </details>
  );
}

export function CropRow({ plan }: { plan: FarmPlan }) {
  const { t } = useLang();
  const F = t.fpl;
  const c = plan.plan.concern;
  return (
    <div className="space-y-1.5">
      <div className="flex flex-wrap gap-1.5">
        {plan.plan.crop && <span className="chip">{plan.plan.crop}</span>}
        {plan.plan.days_since_planting != null && <span className="chip">{F.sincePlanting(plan.plan.days_since_planting)}</span>}
      </div>
      {c.level === "possible" && c.issue ? <p lang={scriptOf(c.issue)}>{F.cropPossible(c.issue)}</p> : c.level === "unclear" ? <p>{F.cropUnclear}</p> : c.level === "none" && !c.farmer_reported ? <p>{F.cropNone}</p> : null}
      {c.farmer_reported && F.farmerReported[c.farmer_reported] && <p>{F.farmerReported[c.farmer_reported]}</p>}
      {c.check_id && <Link to={`/analyses/${c.check_id}`} className="link-btn inline-flex min-h-[2.75rem] items-center text-sm">{F.openCheck}</Link>}
    </div>
  );
}

export function IfRows({ plan }: { plan: FarmPlan }) {
  const { t } = useLang();
  const fmt = useDateFmt();
  return (
    <ul className="list-disc space-y-1.5 pl-5">
      {plan.plan.items.filter((i) => i.section === "if").map((i) => <li key={i.key}>{itemText(t, i, fmt)}</li>)}
    </ul>
  );
}

export function HistoryRow({ farmId, current }: { farmId: number; current: number }) {
  const { t } = useLang();
  const F = t.fpl;
  const [items, setItems] = useState<PlanVersion[] | null>(null);
  const [loaded, setLoaded] = useState<number | null>(null);
  async function load(open: boolean) {
    if (!open || loaded === current) return;
    try {
      setItems(await api.planHistory(farmId));
      setLoaded(current);
    } catch {
      setItems([]);
    }
  }
  return (
    <QuietRow icon="history" title={t.fpl.ui.rows.history} testId="plan-history" onToggle={(o) => void load(o)}>
      <ul className="space-y-1.5">
        {(items ?? []).map((v) => (
          <li key={v.version} className="text-sm" data-testid="plan-version" data-version={v.version}>
            <span className="font-semibold">{F.version(v.version)}</span>
            <span className="text-mute"> · {new Date(v.created_at).toLocaleString(t.locale, { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" })} · {F.steps(v.items)}</span>
            <span className="block text-mute">{v.changes.reasons.map((r) => F.reasons[r]).filter(Boolean).join(F.and)}</span>
          </li>
        ))}
      </ul>
    </QuietRow>
  );
}
