import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError, type Economics } from "../api";
import { EmptyState, ErrorBox, FarmChips, Page, Spinner } from "../components";
import { InputsForm } from "../economics/InputsForm";
import { AssumptionsFold, CostsFold, Findings, MarketFold, OptionsFold, Outlook, PreparedFold, ProductionFold, ScenarioFold } from "../economics/Results";
import { useFarms } from "../FarmContext";
import { useLang } from "../LanguageContext";
import { FieldBackdrop } from "../plan/FieldBackdrop";
import { LayerTag } from "../plan/LayerTag";
import { PlanIcon } from "../plan/icons";

/** Crop Economics & Selling Intelligence: its own page, its own feature. It reads the farm through the shared farm context (crop, planting date,
 *  checks, diary) and the farmer's own assumptions; every figure comes from the server's deterministic calculations. */
export default function EconomicsPage() {
  const { t } = useLang();
  const E = t.ec;
  const { farms, selected, loading: farmsLoading, error: farmError } = useFarms();
  const [state, setState] = useState<{ farmId: number; data: Economics | null; error: string | null } | null>(null);
  const [busy, setBusy] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const seq = useRef(0);
  const inputsRef = useRef<HTMLDetailsElement>(null);

  const load = useCallback(async (farmId: number) => {
    const mine = ++seq.current;
    try {
      const data = await api.economics(farmId);
      if (mine === seq.current) setState({ farmId, data, error: null });
    } catch (e) {
      if (mine === seq.current) setState({ farmId, data: null, error: e instanceof ApiError ? e.message : E.loadError });
    }
  }, [E.loadError]);

  useEffect(() => {
    setEditing(false);
    setSaveError(null);
    if (selected) void load(selected.id);
    return () => {
      seq.current++; // switching farm (or leaving) drops anything still in flight
    };
  }, [selected?.id, load]); // eslint-disable-line react-hooks/exhaustive-deps

  const hasSaved = !!state?.data && (state.data.inputs.area != null || state.data.inputs.markets.length > 0 || Object.keys(state.data.inputs.costs).length > 0 || state.data.inputs.yield_low != null);
  useEffect(() => {
    // the numbers form is open while the farmer is still entering them or asked to edit; once saved, the results lead
    if (inputsRef.current) inputsRef.current.open = editing || !hasSaved;
  }, [editing, hasSaved, state?.farmId]);

  if (farmError) return <ErrorBox message={farmError} />;
  if (farmsLoading || !farms) return <Spinner />;
  if (!selected)
    return (
      <Page title={E.title} back="/">
        <EmptyState title={t.dash.noFarm} action={<Link to="/farms/new" className="btn-hero">{t.dash.addFarm}</Link>} />
      </Page>
    );

  const cur = state && state.farmId === selected.id ? state : null; // never show another farm's economics while this one loads
  const r = cur?.data ?? null;

  async function save(body: unknown) {
    setBusy(true);
    setSaveError(null);
    try {
      const data = await api.saveEconomics(selected!.id, body);
      setState({ farmId: selected!.id, data, error: null });
      setEditing(false);
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (e) {
      setSaveError(e instanceof ApiError && e.status !== 422 ? e.message : E.saveError);
    } finally {
      setBusy(false);
    }
  }

  const area = r?.inputs.area != null ? `${r.inputs.area} ${E.areaUnit[r.inputs.area_unit]}` : null;
  return (
    <div className="mx-auto max-w-3xl space-y-4" data-testid="economics-page">
      <div className="page-banner !mb-0" data-testid="page-banner">
        <FieldBackdrop photo="/img/economics-market.jpg" />
        <span className="mb-1 self-start"><LayerTag k="decide" dark /></span>
        <h1 className="text-2xl font-extrabold tracking-tight text-white sm:text-3xl">{E.title}</h1>
        <p className="text-sm text-white/90" data-testid="econ-cropline">{r?.crop ? `${r.crop}${area ? ` • ${area}` : ""}` : E.noCrop}{r?.context.crop_source ? ` · ${E.cropFrom[r.context.crop_source]}` : ""}</p>
        <FarmChips />
      </div>

      {!r && !cur?.error && <Spinner />}
      {cur?.error && <ErrorBox message={cur.error} />}

      {r && (
        <>
          <Outlook r={r} onEdit={() => setEditing(true)} />
          <Findings r={r} />

          <details ref={inputsRef} className="panel plan-row" onToggle={(e) => setEditing((e.currentTarget as HTMLDetailsElement).open)} data-testid="econ-inputs">
            <summary className="flex min-h-[3.5rem] cursor-pointer list-none items-center gap-3 px-4 py-2 [&::-webkit-details-marker]:hidden">
              <span aria-hidden className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-[#c8f169] text-leaf-900"><PlanIcon name="sow" size={20} /></span>
              <span className="min-w-0 flex-1"><span className="block text-base font-extrabold text-leaf-800">{E.edit}</span><span className="block truncate text-sm text-mute">{E.editHint}</span></span>
              <span className="plan-chev text-mute"><PlanIcon name="chevron" size={20} /></span>
            </summary>
            <div className="px-4 pb-4">
              <InputsForm key={r.updated_at ?? "new"} inputs={r.inputs} plantingDate={r.context.planting_date} busy={busy} error={saveError} onSave={save} />
            </div>
          </details>

          <ProductionFold r={r} />
          <CostsFold r={r} />
          <MarketFold r={r} />
          <OptionsFold r={r} />
          <ScenarioFold r={r} />
          <AssumptionsFold r={r} />
          <PreparedFold r={r} />
          <p className="rounded-2xl bg-amber-50 px-4 py-3 text-sm text-amber-900 ring-1 ring-amber-300" role="note">{E.disclaimer}</p>
        </>
      )}
    </div>
  );
}
