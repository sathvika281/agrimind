import { useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api, ApiError, type Farm, type FarmPatch } from "../api";
import { EmptyState, ErrorBox, Page, Spinner } from "../components";
import { useFarms } from "../FarmContext";
import { useLang } from "../LanguageContext";

const IRRIGATION = ["rainfed", "drip", "sprinkler", "flood", "other"] as const;
const SEASONS = ["kharif", "rabi", "summer"] as const;
const todayIso = () => new Date().toISOString().slice(0, 10);

function Row({ label, value, testId }: { label: string; value?: string | null; testId: string }) {
  const { t } = useLang();
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5 border-b border-line py-2 last:border-b-0">
      <dt className="micro">{label}</dt>
      <dd className={`min-w-0 break-words text-sm ${value ? "font-semibold" : "text-mute"}`} data-testid={testId}>{value || t.prof.notProvided}</dd>
    </div>
  );
}

/** One farm's profile. Keyed by farm id by the page, so switching farms can never carry a form (or its values) over. */
function ProfileBody({ farm }: { farm: Farm }) {
  const { t, lang } = useLang();
  const P = t.prof;
  const { update } = useFarms();
  const [editing, setEditing] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submitting = useRef(false);
  const [f, setF] = useState({ name: "", location: "", soil: "", crop: "", irrigation: "", season: "", planting: "", notes: "" });

  const fmtDate = (iso: string) => new Date(iso).toLocaleDateString(t.locale, { day: "numeric", month: "long", year: "numeric" });
  const hasAny = !!(farm.primary_crop || farm.irrigation_method || farm.season || farm.planting_date || farm.notes || farm.soil_type || farm.location);

  function startEdit() {
    setF({
      name: farm.name, location: farm.location, soil: farm.soil_type, crop: farm.primary_crop ?? "", irrigation: farm.irrigation_method ?? "",
      season: farm.season ?? "", planting: farm.planting_date ?? "", notes: farm.notes ?? "",
    });
    setError(null);
    setSaved(false);
    setEditing(true);
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (submitting.current) return;
    setError(null);
    if (!f.name.trim()) return setError(P.needName);
    if (f.planting && f.planting > todayIso()) return setError(P.plantingHelp);
    const patch: FarmPatch = {
      name: f.name, location: f.location, soil_type: f.soil, primary_crop: f.crop || null,
      irrigation_method: (f.irrigation || null) as FarmPatch["irrigation_method"], season: (f.season || null) as FarmPatch["season"],
      planting_date: f.planting || null, notes: f.notes || null,
    };
    submitting.current = true;
    setBusy(true);
    try {
      update(await api.updateFarm(farm.id, patch)); // the id of the farm THIS form belongs to, whatever is selected now
      setEditing(false);
      setSaved(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : P.couldNotSave);
    } finally {
      submitting.current = false;
      setBusy(false);
    }
  }

  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((x) => ({ ...x, [k]: e.target.value }));

  return (
    <Page title={P.title} back="/farms">
      <p className="-mt-3 mb-3 text-sm text-mute" data-testid="prof-sub">{P.sub} · {farm.name}</p>
      {!editing ? (
        <section className="panel" aria-label={P.title}>
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-3 py-2">
            <div className="flex items-center gap-2">
              <h2 className="text-sm font-bold">{farm.name}</h2>
              <span className="tag-mint">{P.entered.split(".")[0].toUpperCase()}</span>
            </div>
            <button type="button" className="btn-sm-dark w-auto px-5" onClick={startEdit}>{P.edit}</button>
          </div>
          <div className="p-3">
            {saved && <p role="status" className="mb-2 text-sm font-semibold text-leaf-700" data-testid="prof-saved"><span aria-hidden>✔ </span>{P.saved}</p>}
            <p className="mb-2 text-xs text-mute">{P.entered}</p>
            {!hasAny && <p className="mb-2 text-sm" data-testid="prof-none">{P.none}</p>}
            <dl>
              <Row label={P.village} value={farm.location} testId="prof-location" />
              <Row label={P.soil} value={farm.soil_type} testId="prof-soil" />
              <Row label={P.crop} value={farm.primary_crop} testId="prof-crop" />
              <Row label={P.irrigation} value={farm.irrigation_method ? P.irrigationOpts[farm.irrigation_method] ?? farm.irrigation_method : null} testId="prof-irrigation" />
              <Row label={P.season} value={farm.season ? P.seasonOpts[farm.season] ?? farm.season : null} testId="prof-season" />
              <Row label={P.planting} value={farm.planting_date ? fmtDate(farm.planting_date) : null} testId="prof-planting" />
              <Row label={P.notes} value={farm.notes} testId="prof-notes" />
            </dl>
            {farm.context_updated_at && <p className="mt-2 text-xs text-mute">{P.recorded(fmtDate(farm.context_updated_at))}</p>}
          </div>
          <div className="flex flex-wrap gap-2 border-t border-line p-3">
            <Link to="/insights" className="btn-sm-light w-auto px-5">{P.openInsights}</Link>
          </div>
        </section>
      ) : (
        <form onSubmit={submit} className="card space-y-4" noValidate lang={lang} data-testid="prof-form">
          <ErrorBox message={error} />
          <div>
            <label htmlFor="p-name" className="label">{P.name}</label>
            <input id="p-name" className="input" value={f.name} onChange={set("name")} maxLength={120} disabled={busy} />
          </div>
          <div>
            <label htmlFor="p-location" className="label">{P.village}</label>
            <input id="p-location" className="input" value={f.location} onChange={set("location")} maxLength={200} disabled={busy} />
          </div>
          <div>
            <label htmlFor="p-soil" className="label">{P.soil}</label>
            <input id="p-soil" className="input" value={f.soil} onChange={set("soil")} maxLength={100} disabled={busy} />
          </div>
          <div>
            <label htmlFor="p-crop" className="label">{P.crop}</label>
            <input id="p-crop" className="input" list="crop-suggestions-p" value={f.crop} onChange={set("crop")} maxLength={100} autoComplete="off" aria-describedby="p-crop-help" disabled={busy} />
            <datalist id="crop-suggestions-p">{t.crops.map((c) => <option key={c.en} value={c.en} label={`${c.te} (${c.en})`} />)}</datalist>
            <p id="p-crop-help" className="hint">{P.cropHelp}</p>
          </div>
          <div>
            <label htmlFor="p-irrigation" className="label">{P.irrigation}</label>
            <select id="p-irrigation" className="input" value={f.irrigation} onChange={set("irrigation")} disabled={busy}>
              <option value="">{P.choose}</option>
              {IRRIGATION.map((k) => <option key={k} value={k}>{P.irrigationOpts[k]}</option>)}
            </select>
          </div>
          <div>
            <label htmlFor="p-season" className="label">{P.season}</label>
            <select id="p-season" className="input" value={f.season} onChange={set("season")} disabled={busy}>
              <option value="">{P.choose}</option>
              {SEASONS.map((k) => <option key={k} value={k}>{P.seasonOpts[k]}</option>)}
            </select>
          </div>
          <div>
            <label htmlFor="p-planting" className="label">{P.planting}</label>
            <input id="p-planting" type="date" className="input" value={f.planting} min="2000-01-01" max={todayIso()} onChange={set("planting")} aria-describedby="p-planting-help" disabled={busy} />
            <p id="p-planting-help" className="hint">{P.plantingHelp}</p>
          </div>
          <div>
            <label htmlFor="p-notes" className="label">{P.notes}</label>
            <textarea id="p-notes" rows={3} className="input" value={f.notes} onChange={set("notes")} maxLength={500} aria-describedby="p-notes-help" disabled={busy} />
            <p id="p-notes-help" className="hint">{P.notesHelp}</p>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <button className="btn-primary" disabled={busy}>{busy ? P.saving : P.save}</button>
            <button type="button" className="btn-secondary" onClick={() => setEditing(false)} disabled={busy}>{P.cancel}</button>
          </div>
        </form>
      )}
    </Page>
  );
}

export default function Profile() {
  const { t } = useLang();
  const { farms, selected, error } = useFarms();
  if (error) return <ErrorBox message={error} />;
  if (!farms) return <Spinner />;
  if (!selected)
    return (
      <Page title={t.prof.title} back="/farms">
        <EmptyState title={t.dash.noFarm} action={<Link to="/farms/new" className="btn-hero">{t.dash.addFarm}</Link>} />
      </Page>
    );
  return <ProfileBody key={selected.id} farm={selected} />;
}
