import { useState } from "react";
import type { EconInputs } from "../api";
import { useLang } from "../LanguageContext";
import { PlanIcon } from "../plan/icons";

const CATS = ["seeds", "seedlings", "fertilizer", "labour", "irrigation", "machinery", "land_preparation", "harvesting", "transport", "storage", "other"];
const today = () => new Date().toISOString().slice(0, 10);

interface MarketForm { id?: string; name: string; distance: string; transport: string; prices: { date: string; price: string }[] }
const s = (v: number | null | undefined) => (v == null ? "" : String(v));
const n = (v: string): number | null => (v.trim() === "" || Number.isNaN(Number(v)) ? null : Number(v));

/** The farmer's own assumptions for THIS farm. Empty means "not provided": nothing is defaulted and an empty cost is never counted as zero. */
export function InputsForm({ inputs, plantingDate, busy, error, onSave }: { inputs: EconInputs; plantingDate: string | null; busy: boolean; error: string | null; onSave: (body: unknown) => void }) {
  const { t } = useLang();
  const F = t.ec.form;
  const [area, setArea] = useState(s(inputs.area));
  const [unit, setUnit] = useState<"acre" | "hectare">(inputs.area_unit);
  const [yl, setYl] = useState(s(inputs.yield_low));
  const [yh, setYh] = useState(s(inputs.yield_high));
  const [ml, setMl] = useState(s(inputs.marketable_low_pct));
  const [mh, setMh] = useState(s(inputs.marketable_high_pct));
  const [dl, setDl] = useState(s(inputs.days_to_harvest_low));
  const [dh, setDh] = useState(s(inputs.days_to_harvest_high));
  const [costs, setCosts] = useState<Record<string, string>>(Object.fromEntries(Object.entries(inputs.costs).map(([k, v]) => [k, String(v)])));
  const [markets, setMarkets] = useState<MarketForm[]>(inputs.markets.map((m) => ({ id: m.id, name: m.name, distance: s(m.distance_km), transport: s(m.transport_per_quintal), prices: m.prices.map((p) => ({ date: p.date, price: String(p.price) })) })));

  const setMarket = (i: number, patch: Partial<MarketForm>) => setMarkets((ms) => ms.map((m, j) => (j === i ? { ...m, ...patch } : m)));

  function submit(e: React.FormEvent) {
    e.preventDefault();
    onSave({
      area: n(area), area_unit: unit, yield_low: n(yl), yield_high: n(yh), marketable_low_pct: n(ml), marketable_high_pct: n(mh), days_to_harvest_low: n(dl), days_to_harvest_high: n(dh),
      harvest_start: inputs.harvest_start, harvest_end: inputs.harvest_end,
      costs: Object.fromEntries(Object.entries(costs).filter(([, v]) => n(v) != null).map(([k, v]) => [k, n(v)])),
      markets: markets.filter((m) => m.name.trim()).map((m) => ({ id: m.id, name: m.name.trim(), distance_km: n(m.distance), transport_per_quintal: n(m.transport), prices: m.prices.filter((p) => n(p.price) != null && p.date).map((p) => ({ date: p.date, price: n(p.price) })) })),
    });
  }

  const field = "input !min-h-[2.75rem] !py-2 !text-base";
  const lab = "mb-1 block text-sm font-semibold text-ink";
  return (
    <form onSubmit={submit} className="space-y-5" data-testid="econ-form" noValidate>
      <section className="space-y-3">
        <h3 className="text-base font-extrabold text-leaf-800">{F.farmSize}</h3>
        <div className="grid grid-cols-2 gap-3">
          <div><label className={lab} htmlFor="ec-area">{F.area}</label><input id="ec-area" inputMode="decimal" className={field} value={area} onChange={(e) => setArea(e.target.value)} /></div>
          <div><label className={lab} htmlFor="ec-unit">{F.unit}</label>
            <select id="ec-unit" className={field} value={unit} onChange={(e) => setUnit(e.target.value as "acre" | "hectare")}>
              <option value="acre">{t.ec.areaUnit.acre}</option><option value="hectare">{t.ec.areaUnit.hectare}</option>
            </select></div>
        </div>
        <fieldset><legend className={lab}>{F.yieldRange(t.ec.unitOne[unit])}</legend>
          <div className="grid grid-cols-2 gap-3">
            <input aria-label={`${F.low}`} placeholder={F.low} inputMode="decimal" className={field} value={yl} onChange={(e) => setYl(e.target.value)} data-testid="ec-yield-low" />
            <input aria-label={`${F.high}`} placeholder={F.high} inputMode="decimal" className={field} value={yh} onChange={(e) => setYh(e.target.value)} data-testid="ec-yield-high" />
          </div></fieldset>
        <fieldset><legend className={lab}>{F.marketable}</legend>
          <div className="grid grid-cols-2 gap-3">
            <input aria-label={F.low} placeholder={F.low} inputMode="decimal" className={field} value={ml} onChange={(e) => setMl(e.target.value)} data-testid="ec-mkt-low" />
            <input aria-label={F.high} placeholder={F.high} inputMode="decimal" className={field} value={mh} onChange={(e) => setMh(e.target.value)} data-testid="ec-mkt-high" />
          </div><p className="hint">{F.marketableHelp}</p></fieldset>
        <fieldset><legend className={lab}>{F.days}</legend>
          <div className="grid grid-cols-2 gap-3">
            <input aria-label={F.low} placeholder={F.low} inputMode="numeric" className={field} value={dl} onChange={(e) => setDl(e.target.value)} />
            <input aria-label={F.high} placeholder={F.high} inputMode="numeric" className={field} value={dh} onChange={(e) => setDh(e.target.value)} />
          </div><p className="hint">{F.daysHelp(plantingDate ?? "")}</p></fieldset>
      </section>

      <section className="space-y-2">
        <h3 className="text-base font-extrabold text-leaf-800">{F.costs}</h3>
        <p className="hint !mt-0">{F.costsHelp}</p>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {CATS.map((c) => (
            <div key={c}><label className={lab} htmlFor={`ec-c-${c}`}>{t.ec.cat[c]}</label>
              <input id={`ec-c-${c}`} inputMode="decimal" className={field} value={costs[c] ?? ""} onChange={(e) => setCosts((x) => ({ ...x, [c]: e.target.value }))} data-testid={`ec-cost-${c}`} /></div>
          ))}
        </div>
      </section>

      <section className="space-y-3">
        <h3 className="text-base font-extrabold text-leaf-800">{F.markets}</h3>
        <p className="hint !mt-0">{F.marketsHelp}</p>
        {markets.map((m, i) => (
          <div key={m.id ?? `new${i}`} className="space-y-3 rounded-2xl bg-leaf-50 p-3" data-testid="ec-market-form">
            <div className="flex items-end gap-2">
              <div className="min-w-0 flex-1"><label className={lab} htmlFor={`ec-m-${i}`}>{F.marketName}</label><input id={`ec-m-${i}`} className={field} value={m.name} maxLength={60} onChange={(e) => setMarket(i, { name: e.target.value })} data-testid="ec-market-name" /></div>
              <button type="button" onClick={() => setMarkets((ms) => ms.filter((_, j) => j !== i))} aria-label={`${F.remove}: ${m.name}`} className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-white text-[#a63a30]"><PlanIcon name="close" size={20} /></button>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div><label className={lab}>{F.distanceKm}</label><input inputMode="decimal" className={field} value={m.distance} onChange={(e) => setMarket(i, { distance: e.target.value })} /></div>
              <div><label className={lab}>{F.transport}</label><input inputMode="decimal" className={field} value={m.transport} onChange={(e) => setMarket(i, { transport: e.target.value })} data-testid="ec-transport" /></div>
            </div>
            <p className="text-sm font-semibold">{F.prices}</p>
            {m.prices.map((p, k) => (
              <div key={k} className="grid grid-cols-[1fr_1fr_auto] items-end gap-2">
                <input type="date" aria-label={F.priceDate} max={today()} className={field} value={p.date} onChange={(e) => setMarket(i, { prices: m.prices.map((x, j) => (j === k ? { ...x, date: e.target.value } : x)) })} />
                <input inputMode="decimal" aria-label={F.pricePrice} placeholder={F.pricePrice} className={field} value={p.price} onChange={(e) => setMarket(i, { prices: m.prices.map((x, j) => (j === k ? { ...x, price: e.target.value } : x)) })} data-testid="ec-price" />
                <button type="button" onClick={() => setMarket(i, { prices: m.prices.filter((_, j) => j !== k) })} aria-label={F.remove} className="grid h-11 w-11 place-items-center rounded-full bg-white text-[#a63a30]"><PlanIcon name="close" size={18} /></button>
              </div>
            ))}
            {m.prices.length < 10 && <button type="button" onClick={() => setMarket(i, { prices: [...m.prices, { date: today(), price: "" }] })} className="pillbtn" data-testid="ec-add-price"><PlanIcon name="check" size={16} />{F.addPrice}</button>}
          </div>
        ))}
        {markets.length < 5 ? (
          <button type="button" onClick={() => setMarkets((ms) => [...ms, { name: "", distance: "", transport: "", prices: [{ date: today(), price: "" }] }])} className="pillbtn" data-testid="ec-add-market">{F.addMarket}</button>
        ) : <p className="hint">{F.tooMany}</p>}
      </section>

      {error && <p role="alert" className="rounded-2xl bg-[#fde3df] px-4 py-2 text-sm font-semibold text-[#7a1f14]">{error}</p>}
      <button className="btn-hero" disabled={busy} data-testid="ec-save">{busy ? t.ec.saving : t.ec.save}</button>
    </form>
  );
}
