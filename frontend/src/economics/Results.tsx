import { useState, type ReactNode } from "react";
import type { Economics, EconMarket, EconOption } from "../api";
import { useLang } from "../LanguageContext";
import { PlanIcon } from "../plan/icons";
import { dateFull, dateShort, inr, money, num, qty } from "./format";

export function Tag({ kind }: { kind: string }) {
  const { t } = useLang();
  const cls = kind === "demo" ? "bg-[#ffe3a3] text-[#5b3d00]" : kind === "calculated" ? "bg-leaf-100 text-leaf-800" : kind === "unavailable" ? "bg-[#ecefed] text-[#3c4a43]" : "bg-[#dff3e5] text-[#14573a]";
  return <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-bold ${cls}`} data-tag={kind}>{t.ec.sourceTag[kind] ?? kind}</span>;
}

/** A closed row that opens in place; the summary already carries the one number that matters. */
export function Fold({ icon, title, summary, children, testId, open = false }: { icon: string; title: string; summary?: ReactNode; children: ReactNode; testId: string; open?: boolean }) {
  return (
    <details className="panel plan-row" data-testid={testId} open={open}>
      <summary className="flex min-h-[3.5rem] cursor-pointer list-none items-center gap-3 px-4 py-2 [&::-webkit-details-marker]:hidden">
        <span aria-hidden className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-leaf-800 text-[#c8f169]"><PlanIcon name={icon} size={20} /></span>
        <span className="min-w-0 flex-1"><span className="block text-base font-extrabold text-leaf-800">{title}</span>{summary && <span className="block truncate text-sm text-mute">{summary}</span>}</span>
        <span className="plan-chev text-mute"><PlanIcon name="chevron" size={20} /></span>
      </summary>
      <div className="space-y-3 px-4 pb-4">{children}</div>
    </details>
  );
}

const Stat = ({ label, value, sub, tag }: { label: string; value: ReactNode; sub?: ReactNode; tag?: string }) => (
  <div className="min-w-0 rounded-2xl bg-leaf-50 px-3 py-2.5">
    <div className="micro">{label}</div>
    <div className="break-words text-lg font-extrabold leading-tight text-ink">{value}</div>
    {sub && <div className="text-xs text-mute">{sub}</div>}
    {tag && <div className="mt-1"><Tag kind={tag} /></div>}
  </div>
);

function Spark({ pts, label }: { pts: { date: string; price: number }[]; label: string }) {
  if (pts.length < 2) return null;
  const xs = pts.map((p) => new Date(p.date).getTime()), ys = pts.map((p) => p.price);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const px = (x: number) => (x1 === x0 ? 50 : 4 + ((x - x0) / (x1 - x0)) * 92), py = (y: number) => (y1 === y0 ? 20 : 34 - ((y - y0) / (y1 - y0)) * 28);
  return (
    <svg viewBox="0 0 100 40" role="img" aria-label={label} className="h-12 w-full text-leaf-700">
      <polyline fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" points={pts.map((p, i) => `${px(xs[i])},${py(p.price)}`).join(" ")} />
      {pts.map((p, i) => <circle key={i} cx={px(xs[i])} cy={py(p.price)} r="2" fill="currentColor" />)}
    </svg>
  );
}

export function Outlook({ r, onEdit }: { r: Economics; onEdit: () => void }) {
  const { t } = useLang();
  const E = t.ec, loc = t.locale;
  const rd = r.reading, o = r.outlook;
  const win = r.window.start && r.window.end ? `${dateShort(r.window.start, loc)} – ${dateShort(r.window.end, loc)}` : null;
  return (
    <section className="plan-hero photo-light p-5 sm:p-6" data-testid="econ-outlook" data-outlook={rd.outlook} aria-label={E.outlookTitle}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-bold uppercase tracking-widest text-white/85">{E.outlookTitle}</span>
        {r.demo && <span className="rounded-full bg-[#ffe3a3] px-2.5 py-0.5 text-xs font-extrabold text-[#5b3d00]" data-testid="demo-badge">{t.ec.sourceTag.demo}</span>}
      </div>
      {o ? (
        <>
          <p className="mt-2 text-sm text-white/85">{E.estMargin}</p>
          <p className="text-3xl font-extrabold leading-tight text-white sm:text-4xl" data-testid="econ-margin">{money(o.margin, loc)}</p>
          <p className="mt-1 text-sm text-white/90">{E.outlookLine[rd.outlook]}</p>
          <ul className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
            <li className="plan-glass px-3 py-2"><div className="text-xs text-white/90">{E.harvest}</div><div className="text-base font-extrabold" data-testid="econ-harvest">{win ?? "—"}</div></li>
            <li className="plan-glass px-3 py-2"><div className="text-xs text-white/90">{E.expectedProduction}</div><div className="text-base font-extrabold">{qty(r.production.production, loc)} q</div></li>
            <li className="plan-glass px-3 py-2"><div className="text-xs text-white/90">{E.breakeven}</div><div className="text-base font-extrabold" data-testid="econ-breakeven">{money(r.breakeven, loc)}</div></li>
            <li className="plan-glass px-3 py-2"><div className="text-xs text-white/90">{E.confidence}</div><div className="text-base font-extrabold" data-testid="econ-confidence">{E.level[rd.confidence.level]}</div></li>
          </ul>
          <p className="mt-3 text-sm text-white/90" data-testid="econ-confidence-why">{rd.confidence.reasons.map((x) => E.reason[x]).filter(Boolean).slice(0, 3).join(" · ")}</p>
        </>
      ) : (
        <>
          <p className="mt-2 text-2xl font-extrabold text-white">{E.outlookLine.insufficient}</p>
          <p className="mt-3 text-sm font-semibold text-white/90">{E.stillNeeded}</p>
          <ul className="mt-1 flex flex-wrap gap-2" data-testid="econ-missing">
            {rd.missing.map((k) => <li key={k} className="rounded-full bg-white/15 px-3 py-1 text-sm font-semibold">{E.missing[k] ?? k}</li>)}
          </ul>
          <button type="button" onClick={onEdit} className="mt-4 inline-flex min-h-[3rem] items-center rounded-full bg-[#c8f169] px-6 text-base font-extrabold text-leaf-900 active:scale-95" data-testid="econ-add-numbers">{E.edit}</button>
        </>
      )}
    </section>
  );
}

export function Findings({ r }: { r: Economics }) {
  const { t } = useLang();
  const E = t.ec, loc = t.locale, rd = r.reading;
  const best = rd.best_market;
  const bestText = best ? (best.reason === "best_net_value" ? E.best.best_net_value(best.name, inr(best.net_per_quintal ?? 0, loc)) : E.best.highest_price_transport_unknown(best.name)) : null;
  return (
    <div className="space-y-2" data-testid="econ-findings">
      {bestText && <p className="rounded-2xl bg-[#c8f169]/40 px-4 py-3 text-sm font-semibold text-leaf-900" data-testid="econ-best">{bestText}{best?.gap_per_quintal ? ` ${E.gap(inr(best.gap_per_quintal, loc))}` : ""}</p>}
      {rd.price_vs_breakeven && <p className="rounded-2xl bg-white px-4 py-3 text-sm shadow-sm">{E.vsBreakeven[rd.price_vs_breakeven]} <span className="text-mute">{E.breakevenNote}</span></p>}
      {rd.notes.map((k) => E.notes[k] && <p key={k} className={`rounded-2xl px-4 py-3 text-sm ${k === "crop_check_high_severity" ? "bg-amber-50 text-amber-900 ring-1 ring-amber-300" : "bg-white shadow-sm"}`} data-note={k}>{E.notes[k]}</p>)}
    </div>
  );
}

export function ProductionFold({ r }: { r: Economics }) {
  const { t } = useLang();
  const E = t.ec, loc = t.locale, p = r.production;
  return (
    <Fold icon="crop" title={E.sections.production} summary={p.production ? `${qty(p.production, loc)} q` : E.needsEstimate} testId="econ-production">
      <div className="grid grid-cols-2 gap-2">
        <Stat label={E.yieldLabel} value={p.yield ? `${qty(p.yield, loc)} q` : "—"} sub={E.perUnit(E.unitOne[p.unit])} tag={p.yield ? "farmer" : "unavailable"} />
        <Stat label={E.expectedProduction} value={p.production ? `${qty(p.production, loc)} q` : "—"} tag={p.production ? "calculated" : "unavailable"} />
        <Stat label={E.marketable} value={p.marketable ? `${qty(p.marketable, loc)} q` : "—"} sub={p.marketable_pct ? `${p.marketable_pct.low}–${p.marketable_pct.high}%` : undefined} tag={p.marketable ? "calculated" : "unavailable"} />
        <Stat label={E.harvest} value={r.window.start && r.window.end ? `${dateShort(r.window.start, loc)} – ${dateShort(r.window.end, loc)}` : E.harvestNA} sub={E.harvestSrc[r.window.source]} tag={r.window.source === "farmer" ? "farmer" : r.window.source === "unavailable" ? "unavailable" : "calculated"} />
      </div>
    </Fold>
  );
}

export function CostsFold({ r }: { r: Economics }) {
  const { t } = useLang();
  const E = t.ec, loc = t.locale, c = r.costs;
  const max = Math.max(1, ...c.items.map((i) => i.amount ?? 0));
  return (
    <Fold icon="warn" title={E.sections.costs} summary={c.total != null ? inr(c.total, loc) : E.needsEstimate} testId="econ-costs">
      <div className="grid grid-cols-2 gap-2">
        <Stat label={E.totalCost} value={c.total != null ? inr(c.total, loc) : "—"} tag={c.total != null ? "farmer" : "unavailable"} />
        <Stat label={E.perArea(E.unitOne[r.unit])} value={c.per_area != null ? inr(c.per_area, loc) : "—"} tag={c.per_area != null ? "calculated" : "unavailable"} />
        <Stat label={E.perQuintal} value={c.per_quintal ? money(c.per_quintal, loc) : "—"} tag={c.per_quintal ? "calculated" : "unavailable"} />
      </div>
      <ul className="space-y-1.5" data-testid="econ-cost-bars">
        {c.items.map((i) => (
          <li key={i.key} className="text-sm" data-included={i.included}>
            <div className="flex justify-between gap-2"><span>{E.cat[i.key]}</span><span className={i.included ? "font-semibold" : "text-mute"}>{i.included ? inr(i.amount ?? 0, loc) : E.notIncluded}</span></div>
            {i.included && <div className="mt-0.5 h-2 rounded-full bg-line"><div className="h-2 rounded-full bg-[#9ad13a]" style={{ width: `${((i.amount ?? 0) / max) * 100}%` }} /></div>}
          </li>
        ))}
      </ul>
      {c.total != null && !c.complete && <p className="rounded-2xl bg-amber-50 px-3 py-2 text-sm text-amber-900">{E.costsIncomplete}</p>}
    </Fold>
  );
}

function MarketCard({ m }: { m: EconMarket }) {
  const { t } = useLang();
  const E = t.ec, loc = t.locale;
  return (
    <li className="space-y-1 rounded-2xl bg-leaf-50 p-3" data-testid="econ-market" data-status={m.status}>
      <div className="flex flex-wrap items-center gap-2"><span className="text-base font-extrabold">{m.name}</span><Tag kind={m.source === "demo" ? "demo" : "quote"} />
        <span className={`rounded-full px-2 py-0.5 text-xs font-bold ${m.status === "fresh" ? "bg-[#dff3e5] text-[#14573a]" : "bg-[#fff0c7] text-[#5b3d00]"}`}>{E.freshness[m.status]}</span></div>
      {m.latest ? (
        <>
          <p className="text-lg font-extrabold">{inr(m.latest.price, loc)} <span className="text-sm font-normal text-mute">{E.perQ}</span></p>
          <p className="text-xs text-mute">{E.updated(dateFull(m.latest.date, loc), m.latest.age_days)}</p>
          {m.range && m.status !== "too_old" && <p className="text-sm">{E.recentRange}: {inr(m.range.low, loc)}–{inr(m.range.high, loc)} · {E.trend}: <b>{E.trendWord[m.trend]}</b></p>}
          {m.points && <Spark pts={m.points} label={`${m.name}: ${E.trend}`} />}
        </>
      ) : <p className="text-sm text-mute">{E.freshness.no_price}</p>}
    </li>
  );
}

export function MarketFold({ r }: { r: Economics }) {
  const { t } = useLang();
  const E = t.ec, loc = t.locale;
  const ref = r.markets.find((m) => m.id === r.outlook?.market_id) ?? r.markets.find((m) => m.status === "fresh" || m.status === "stale");
  return (
    <Fold icon="chance" title={E.sections.market} summary={ref?.latest ? `${ref.name}: ${inr(ref.latest.price, loc)} ${E.perQ}` : E.noMarket} testId="econ-market-section">
      {r.demo && <p className="rounded-2xl bg-[#ffe3a3] px-3 py-2 text-sm font-bold text-[#5b3d00]" data-testid="demo-note">{E.demoBanner}</p>}
      {r.markets.length === 0 ? <p className="text-sm text-mute">{E.noMarket}</p> : <ul className="space-y-2">{r.markets.map((m) => <MarketCard key={m.id} m={m} />)}</ul>}
      <p className="text-sm text-mute" data-testid="econ-noforecast">{E.noForecast}</p>
    </Fold>
  );
}

export function OptionsFold({ r }: { r: Economics }) {
  const { t } = useLang();
  const E = t.ec, loc = t.locale;
  const best = r.reading.best_market;
  return (
    <Fold icon="arrow" title={E.sections.options} summary={best ? best.name : E.noMarket} testId="econ-options">
      {r.options.length === 0 ? <p className="text-sm text-mute">{E.noMarket}</p> : (
        <ol className="space-y-2">
          {r.options.map((o: EconOption) => (
            <li key={o.id} className={`rounded-2xl p-3 ${o.rank === 1 ? "bg-[#c8f169]/40 ring-2 ring-[#9ad13a]" : "bg-leaf-50"}`} data-testid="econ-option" data-rank={o.rank ?? ""}>
              <div className="flex flex-wrap items-center gap-2"><span className="text-base font-extrabold">{o.name}</span>{o.distance_km != null && <span className="chip">{E.distance(o.distance_km)}</span>}<Tag kind={o.source === "demo" ? "demo" : "quote"} /></div>
              {o.complete ? (
                <div className="mt-1 grid grid-cols-2 gap-2 text-sm">
                  <div><div className="micro">{E.netPerQ}</div><div className="text-lg font-extrabold">{inr(o.net_per_quintal ?? 0, loc)}</div></div>
                  <div><div className="micro">{E.net}</div><div className="text-lg font-extrabold">{money(o.net_value, loc)}</div></div>
                </div>
              ) : <p className="mt-1 text-sm text-mute">{o.reason === "transport_missing" ? E.transportMissing : E.freshness[o.reason] ?? o.reason}</p>}
            </li>
          ))}
        </ol>
      )}
    </Fold>
  );
}

export function ScenarioFold({ r }: { r: Economics }) {
  const { t } = useLang();
  const E = t.ec, loc = t.locale, g = r.scenarios;
  const [p, setP] = useState(0), [y, setY] = useState(0), [c, setC] = useState(0);
  if (!g) return <Fold icon="refresh" title={E.sections.scenarios} summary={E.needsEstimate} testId="econ-scenarios"><p className="text-sm text-mute">{E.outlookLine.insufficient}</p></Fold>;
  const base = g.cells["0|0|0"], cell = g.cells[`${p}|${y}|${c}`];
  const seg = (label: string, vals: number[], cur: number, set: (n: number) => void, id: string) => (
    <div role="radiogroup" aria-label={label} data-testid={`seg-${id}`}>
      <p className="mb-1 text-sm font-bold">{label}</p>
      <div className="flex flex-wrap gap-1.5">
        {vals.map((v) => (
          <button key={v} type="button" role="radio" aria-checked={cur === v} onClick={() => set(v)} data-testid={`${id}-${v}`}
            className={`min-h-[2.75rem] rounded-full px-3 text-sm font-bold transition active:scale-95 ${cur === v ? "bg-leaf-800 text-[#c8f169]" : "border border-line bg-white text-ink hover:bg-leaf-50"}`}>{E.pct(v)}</button>
        ))}
      </div>
    </div>
  );
  const row = (label: string, a: string, b: string, key: string) => (
    <div className="grid grid-cols-[1.1fr_1fr_1fr] gap-2 border-b border-line py-1.5 text-sm last:border-0" data-row={key}><span className="text-mute">{label}</span><span>{a}</span><b data-testid={`case-${key}`}>{b}</b></div>
  );
  return (
    <Fold icon="refresh" title={E.sections.scenarios} summary={E.scenarioTitle} testId="econ-scenarios">
      <p className="text-sm text-mute">{E.scenarioNote}</p>
      {seg(E.price, g.price, p, setP, "price")}
      {seg(E.yieldW, g.yield, y, setY, "yield")}
      {seg(E.costW, g.cost, c, setC, "cost")}
      <div className="rounded-2xl bg-white p-3 shadow-sm">
        <div className="grid grid-cols-[1.1fr_1fr_1fr] gap-2 pb-1 text-xs font-bold uppercase tracking-wide text-mute"><span /><span>{E.base}</span><span>{E.thisCase}</span></div>
        {row(E.marketable, `${qty(base.marketable, loc)} q`, `${qty(cell.marketable, loc)} q`, "qty")}
        {row(E.revenue, money(base.revenue, loc), money(cell.revenue, loc), "revenue")}
        {row(E.cost, inr(base.cost, loc), inr(cell.cost, loc), "cost")}
        {row(E.estMargin, money(base.margin, loc), money(cell.margin, loc), "margin")}
        {row(E.breakeven, money(base.breakeven, loc), money(cell.breakeven, loc), "breakeven")}
      </div>
      {r.reading.drivers.length > 0 && (
        <div className="rounded-2xl bg-leaf-50 p-3" data-testid="econ-drivers">
          <p className="text-sm font-bold">{E.drivers}</p>
          <ol className="mt-1 space-y-0.5 text-sm">{r.reading.drivers.map((d) => <li key={d.factor}><b>{E.driverName[d.factor]}</b>: {E.swing(inr(d.swing, loc))}</li>)}</ol>
        </div>
      )}
    </Fold>
  );
}

export function AssumptionsFold({ r }: { r: Economics }) {
  const { t } = useLang();
  const E = t.ec, loc = t.locale, inp = r.inputs;
  const rows: [string, string, string][] = [
    [E.form.area, inp.area != null ? `${num(inp.area, loc)} ${E.areaUnit[inp.area_unit]}` : "—", inp.area != null ? "farmer" : "unavailable"],
    [E.yieldLabel, r.production.yield ? `${qty(r.production.yield, loc)} q ${E.perUnit(E.unitOne[inp.area_unit])}` : "—", r.production.yield ? "farmer" : "unavailable"],
    [E.form.marketable, r.production.marketable_pct ? `${r.production.marketable_pct.low}–${r.production.marketable_pct.high}%` : "—", r.production.marketable_pct ? "farmer" : "unavailable"],
    [E.totalCost, r.costs.total != null ? inr(r.costs.total, loc) : "—", r.costs.total != null ? "farmer" : "unavailable"],
    [E.marketTitle, r.markets.length ? String(r.markets.length) : "—", r.demo ? "demo" : r.markets.length ? "quote" : "unavailable"],
    [E.harvest, E.harvestSrc[r.window.source] ?? E.harvestNA, r.window.source === "unavailable" ? "unavailable" : r.window.source === "farmer" ? "farmer" : "calculated"],
    [E.breakeven, r.breakeven ? money(r.breakeven, loc) : "—", r.breakeven ? "calculated" : "unavailable"],
  ];
  return (
    <Fold icon="info" title={E.sections.assumptions} summary={E.disclaimer} testId="econ-assumptions">
      <ul className="divide-y divide-line">
        {rows.map(([k, v, tag]) => <li key={k} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm"><span>{k}</span><span className="flex items-center gap-2"><b>{v}</b><Tag kind={tag} /></span></li>)}
      </ul>
      <p className="text-sm text-mute">{E.export}</p>
      {r.reading.limitations.map((k) => <p key={k} className="text-sm">{E.limits[k]}</p>)}
    </Fold>
  );
}

export function PreparedFold({ r }: { r: Economics }) {
  const { t } = useLang();
  const E = t.ec;
  return (
    <Fold icon="history" title={E.sections.prepared} summary={`${r.steps.filter((s) => s.status === "ok").length}/${r.steps.length}`} testId="econ-prepared">
      <div data-testid="econ-context">
        <p className="text-sm font-bold">{E.contextTitle}</p>
        <ul className="mt-1 flex flex-wrap gap-2">
          {r.context.used.map((u) => <li key={u.source} className="chip" data-source={u.source}>{E.ctxSource[u.source]} · {E.ctxCount(u.count)}</li>)}
        </ul>
      </div>
      <ol className="space-y-1" data-testid="econ-steps">
        {r.steps.map((s) => (
          <li key={s.node} data-node={s.node} data-status={s.status} className="flex items-start gap-2 text-sm">
            <span aria-hidden className={s.status === "ok" ? "text-[#14573a]" : "text-mute"}>{s.status === "ok" ? "✓" : "○"}</span>
            <span><b>{E.stepName[s.node]}</b> <span className="text-mute">· {E.stepState[s.status]}{E.stepNote[s.note] ? ` · ${E.stepNote[s.note]}` : ""}</span></span>
          </li>
        ))}
      </ol>
      <p className="text-sm text-mute">{E.preparedNote}</p>
    </Fold>
  );
}
