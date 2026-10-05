import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api, ApiError, type EventKind, type FarmEvent } from "../api";
import { EmptyState, ErrorBox, Page, Spinner } from "../components";
import { useFarms } from "../FarmContext";
import { useLang } from "../LanguageContext";

const KINDS: EventKind[] = ["sowed", "irrigated", "fertilised", "sprayed", "weeded", "harvested", "other"];
const todayIso = () => new Date().toISOString().slice(0, 10);

/** The diary of ONE farm. Only the newest request for the farm on screen may update the state (no stale overwrite). */
export function useEvents(farmId: number | null) {
  const [state, setState] = useState<{ farmId: number; items: FarmEvent[] | null; error: string | null } | null>(null);
  const seq = useRef(0);
  const load = useCallback(async (id: number) => {
    const mine = ++seq.current;
    try {
      const items = await api.farmEvents(id);
      if (mine === seq.current) setState({ farmId: id, items, error: null });
    } catch (e) {
      if (mine === seq.current) setState({ farmId: id, items: null, error: e instanceof ApiError ? e.message : "" });
    }
  }, []);
  useEffect(() => {
    if (farmId != null) void load(farmId);
    return () => {
      seq.current++;
    };
  }, [farmId, load]);
  const cur = state && state.farmId === farmId ? state : null;
  return { items: cur?.items ?? null, error: cur?.error ?? null, loading: farmId != null && cur === null, reload: () => farmId != null && load(farmId), setItems: (fn: (x: FarmEvent[]) => FarmEvent[]) => setState((s) => (s && s.items ? { ...s, items: fn(s.items) } : s)) };
}

function DiaryBody({ farmId, farmName }: { farmId: number; farmName: string }) {
  const { t } = useLang();
  const D = t.dy;
  const { items, error, loading, reload, setItems } = useEvents(farmId);
  const [kind, setKind] = useState<EventKind>("irrigated");
  const [date, setDate] = useState(todayIso());
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const submitting = useRef(false);
  const fmt = (iso: string) => new Date(iso + "T00:00:00").toLocaleDateString(t.locale, { day: "numeric", month: "short", year: "numeric" });

  async function add(e: FormEvent) {
    e.preventDefault();
    if (submitting.current) return;
    setFormError(null);
    if (date > todayIso()) return setFormError(D.dateFuture);
    submitting.current = true;
    setBusy(true);
    try {
      const ev = await api.addFarmEvent(farmId, { kind, event_date: date || null, note: note.trim() || null });
      setItems((x) => [ev, ...x].sort((a, b) => (a.event_date < b.event_date ? 1 : a.event_date > b.event_date ? -1 : b.id - a.id)));
      setNote("");
    } catch (err) {
      setFormError(err instanceof ApiError && err.status === 409 ? D.full : D.saveError);
    } finally {
      submitting.current = false;
      setBusy(false);
    }
  }

  async function remove(ev: FarmEvent) {
    try {
      await api.deleteFarmEvent(farmId, ev.id);
      setItems((x) => x.filter((y) => y.id !== ev.id));
    } catch {
      setFormError(D.saveError);
    }
  }

  return (
    <Page title={D.title} back="/">
      <p className="-mt-3 mb-3 text-sm text-mute" data-testid="diary-sub">{D.sub} · {farmName}</p>
      <form onSubmit={add} className="card space-y-4" noValidate data-testid="diary-form">
        <ErrorBox message={formError} />
        <fieldset>
          <legend className="label">{D.whatDid}</legend>
          <div className="flex flex-wrap gap-2" role="radiogroup" aria-label={D.whatDid}>
            {KINDS.map((k) => (
              <button
                key={k}
                type="button"
                role="radio"
                aria-checked={kind === k}
                data-testid={`kind-${k}`}
                onClick={() => setKind(k)}
                className={`min-h-[2.75rem] rounded-full border-2 px-4 text-base font-semibold ${kind === k ? "border-leaf-800 bg-leaf-800 text-white" : "border-line bg-white text-ink hover:bg-leaf-50"}`}
              >
                {kind === k && <span aria-hidden>✓ </span>}
                {D.kinds[k]}
              </button>
            ))}
          </div>
        </fieldset>
        <div>
          <label htmlFor="d-date" className="label">{D.date}</label>
          <input id="d-date" type="date" className="input" value={date} min="2000-01-01" max={todayIso()} onChange={(e) => setDate(e.target.value)} disabled={busy} />
        </div>
        <div>
          <label htmlFor="d-note" className="label">{D.note}</label>
          <textarea id="d-note" rows={2} className="input" value={note} maxLength={300} aria-describedby="d-note-help" onChange={(e) => setNote(e.target.value)} disabled={busy} />
          <p id="d-note-help" className="hint">{D.noteHelp}</p>
        </div>
        <button className="btn-primary" disabled={busy}>{busy ? D.adding : D.add}</button>
      </form>

      <div className="mt-5" data-testid="diary-list">
        {loading && <Spinner />}
        {error !== null && !loading && !items && (
          <div role="alert" className="space-y-2">
            <ErrorBox message={error || D.loadError} />
            <button type="button" className="btn-secondary" onClick={() => void reload()}>{t.ins.retry}</button>
          </div>
        )}
        {items && items.length === 0 && <p className="text-base text-mute" data-testid="diary-empty">{D.empty}</p>}
        {items && items.length > 0 && (
          <ul className="divide-y divide-line rounded-panel border border-line bg-white">
            {items.map((ev) => (
              <li key={ev.id} className="flex items-center justify-between gap-3 px-4 py-2" data-testid="diary-item">
                <div className="min-w-0">
                  <p className="text-base font-semibold">{D.kinds[ev.kind] ?? ev.kind}</p>
                  <p className="micro">{fmt(ev.event_date)}</p>
                  {ev.note && <p className="break-words text-sm text-ink/80">{ev.note}</p>}
                </div>
                <button type="button" className="btn-sm-light w-auto shrink-0 px-4" aria-label={D.removeAria(D.kinds[ev.kind] ?? ev.kind, fmt(ev.event_date))} onClick={() => void remove(ev)}>
                  {D.remove}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Page>
  );
}

export default function Diary() {
  const { t } = useLang();
  const { farms, selected, error } = useFarms();
  if (error) return <ErrorBox message={error} />;
  if (!farms) return <Spinner />;
  if (!selected)
    return (
      <Page title={t.dy.title} back="/">
        <EmptyState title={t.dash.noFarm} action={<Link to="/farms/new" className="btn-hero">{t.dash.addFarm}</Link>} />
      </Page>
    );
  return <DiaryBody key={selected.id} farmId={selected.id} farmName={selected.name} />; // a farm switch can never carry a form over
}
