import { useEffect, useRef, useState, type ChangeEvent, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, ApiError, newIdempotencyKey, type Analysis } from "../api";
import { friendlyDate } from "../copy";
import { useFarms } from "../FarmContext";
import { useStatus } from "../overview/StatusContext";
import { EmptyState, ErrorBox, Page, Spinner } from "../components";
import { ImageProblem } from "../imageUtils";
import { prepareImage } from "../imageUtils";
import { useLang } from "../LanguageContext";
import { VoiceControls } from "../voice/components";
import { appendTranscript } from "../voice/stt";
import { useVoiceInput } from "../voice/useVoiceInput";

// Loading wording depends ONLY on elapsed time; it never claims a backend step has finished.
const SECOND_MESSAGE_AFTER_MS = Number(import.meta.env.VITE_SECOND_MSG_AFTER_MS) || 5_000;
const SLOW_AFTER_MS = Number(import.meta.env.VITE_SLOW_AFTER_MS) || 20_000; // env overrides are for testing only

export default function Analyze() {
  const nav = useNavigate();
  const { t, lang } = useLang();
  const a = t.analyze;
  const { farms, selected, select, error: farmError } = useFarms();
  const { refresh } = useStatus();
  // "Re-check this crop": ?followup=<id> links the new check to one of the farmer's own earlier checks.
  const [params] = useSearchParams();
  const followId = Number(params.get("followup")) || null;
  const [earlier, setEarlier] = useState<Analysis | null>(null);
  const mounted = useRef(true); // false once the farmer has left this page
  const [crop, setCrop] = useState("");
  const [symptoms, setSymptoms] = useState("");
  const [image, setImage] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [preparing, setPreparing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [requestId, setRequestId] = useState("");
  const [retryable, setRetryable] = useState(false);
  const [busy, setBusy] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const submitting = useRef(false);
  const galleryInput = useRef<HTMLInputElement>(null);
  const cameraInput = useRef<HTMLInputElement>(null);
  // One idempotency key per logical attempt: reused by "Try again" so the server never creates a duplicate.
  const attempt = useRef<{ sig: string; key: string } | null>(null);
  // Voice only fills the problem box (appended, editable, never auto-submitted). Analysis is the normal text flow.
  const voice = useVoiceInput({ lang, onTranscript: (text) => setSymptoms((prev) => appendTranscript(prev, text)) });
  const voiceBusy = voice.state !== "idle"; // don't let a submit race an in-flight transcript

  // The farm's recorded main crop pre-fills an EMPTY crop box once per farm; the farmer can always change or clear it.
  const prefilledFor = useRef<number | null>(null);
  useEffect(() => {
    if (!selected || prefilledFor.current === selected.id) return;
    prefilledFor.current = selected.id;
    if (selected.primary_crop) setCrop((c) => c || selected.primary_crop!);
  }, [selected]);

  useEffect(() => {
    setEarlier(null);
    if (!followId) return;
    let current = true;
    api.analysis(followId).then((p) => {
      if (!current) return;
      setEarlier(p);
      select(p.farm_id); // the same farm
      setCrop(p.crop); // a follow-up is about the same crop
    }).catch(() => undefined); // not found / not yours: simply a normal new check
    return () => { current = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [followId]);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    if (!image) return setPreview(null);
    const url = URL.createObjectURL(image);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [image]);

  useEffect(() => {
    if (!busy) return setElapsed(0);
    const t1 = setTimeout(() => setElapsed(1), SECOND_MESSAGE_AFTER_MS);
    const t2 = setTimeout(() => setElapsed(2), SLOW_AFTER_MS);
    return () => {
      clearTimeout(t1);
      clearTimeout(t2);
    };
  }, [busy]);

  async function pickImage(e: ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    e.target.value = ""; // allow re-picking the same file
    if (!f) return;
    setError(null);
    setPreparing(true);
    try {
      setImage(await prepareImage(f)); // validated, and shrunk once if large (so retries send identical bytes)
    } catch (err) {
      setError(err instanceof ImageProblem ? err.message : a.photoUnsupported);
    } finally {
      setPreparing(false);
    }
  }

  async function run() {
    if (submitting.current || !selected) return;
    setError(null);
    setRequestId("");
    setRetryable(false);
    if (!crop.trim()) return setError(a.needCrop);
    if (!symptoms.trim() && !image) return setError(a.needProblem);

    // The language is part of the attempt: the same key + a different language would be a (correct) conflict.
    const sig = [selected.id, lang, earlier?.id ?? "", crop.trim(), symptoms.trim(), image ? `${image.name}:${image.size}:${image.lastModified}` : ""].join("|");
    if (!attempt.current || attempt.current.sig !== sig) attempt.current = { sig, key: newIdempotencyKey() };

    submitting.current = true;
    setBusy(true);
    try {
      const res = await api.createAnalysis({ farm_id: selected.id, crop, symptoms, image, language: lang, follow_up_of: earlier && earlier.farm_id === selected.id ? earlier.id : null }, attempt.current.key);
      // Only take the farmer to the result if they are still here; if they went elsewhere while it ran, leave them
      // there (no surprise jump) and just refresh the shared status so the Overview/history show the finished check.
      if (mounted.current) nav(`/analyses/${res.id}`, { replace: true });
      else void refresh();
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
        setRequestId(err.status >= 500 ? err.requestId : "");
        setRetryable(err.retryable); // never auto-resubmits: the farmer decides
      } else {
        setError(t.err.ai);
        setRetryable(true);
      }
      submitting.current = false;
      setBusy(false);
    }
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    void run();
  }

  if (farmError) return <ErrorBox message={farmError} />;
  if (!farms) return <Spinner />;

  if (!selected)
    return (
      <Page title={a.title} back="/">
        <EmptyState title={t.dash.noFarm} action={<Link to="/farms/new" className="btn-hero">{t.dash.addFarm}</Link>} />
      </Page>
    );

  const locked = busy || preparing;
  const msgs = image ? a.loadingPhoto : a.loading;
  const loadingText = elapsed >= 2 ? a.slow : msgs[elapsed];
  const where = [selected.name, selected.location].filter(Boolean).join(" · ");

  return (
    <Page title={a.title} back="/">
      <form onSubmit={submit} className="card space-y-5" noValidate>
        {earlier && earlier.farm_id === selected.id && (
          <div role="note" className="rounded-xl bg-leaf-50 px-4 py-3 text-base text-leaf-900" data-testid="followup-banner">
            <p className="font-semibold">{t.rf.followupBanner(friendlyDate(earlier.created_at))}</p>
            <Link to={`/analyses/${earlier.id}`} className="link-btn inline-flex min-h-[2.5rem] items-center">{t.rf.followupOpen}</Link>
            <p>{t.rf.followupHelp}</p>
          </div>
        )}
        <ErrorBox message={error} requestId={requestId} />
        {error && retryable && !busy && (
          <button type="button" className="btn-secondary" onClick={() => void run()}>
            {a.tryAgain}
          </button>
        )}

        <div className="rounded-xl bg-leaf-50 px-4 py-3">
          <p className="text-sm font-semibold uppercase tracking-wide text-gray-600">{a.checkingOn}</p>
          <p className="text-lg font-bold">{where}</p>
          {farms.length > 1 && (
            <div className="mt-2">
              <label htmlFor="farm" className="label">{a.changeFarm}</label>
              <select id="farm" className="input" value={selected.id} onChange={(e) => select(Number(e.target.value))} disabled={locked}>
                {farms.map((f) => (
                  <option key={f.id} value={f.id}>{f.name}</option>
                ))}
              </select>
            </div>
          )}
        </div>

        <div>
          <label htmlFor="crop" className="label">{a.cropLabel}</label>
          <input id="crop" className="input" list="crop-suggestions" placeholder={a.cropPh} value={crop} onChange={(e) => setCrop(e.target.value)} disabled={locked} autoComplete="off" />
          {/* Free text stays free: suggestions only fill in the English crop name; Telugu or mixed text is fine too. */}
          <datalist id="crop-suggestions">
            {t.crops.map((c) => (
              <option key={c.en} value={c.en} label={`${c.te} (${c.en})`} />
            ))}
          </datalist>
        </div>

        <div>
          <label htmlFor="symptoms" className="label">{a.problemLabel}</label>
          <textarea
            id="symptoms"
            rows={4}
            className="input"
            aria-describedby="symptoms-help"
            value={symptoms}
            onChange={(e) => setSymptoms(e.target.value)}
            disabled={locked}
          />
          <p id="symptoms-help" className="hint">{a.problemHelp}</p>
          <VoiceControls voice={voice} lang={lang} />
        </div>

        <div className="rounded-2xl border-2 border-dashed border-leaf-500 bg-leaf-50 p-4">
          <h2 className="text-lg font-bold text-leaf-800">{a.photoLabel} <span className="text-base font-normal text-gray-600">{a.optional}</span></h2>
          <p className="mb-3 text-base text-gray-700">{a.photoHint}</p>
          <input ref={cameraInput} id="photo-camera" type="file" accept="image/*" capture="environment" className="sr-only" tabIndex={-1} onChange={pickImage} disabled={locked} />
          <input ref={galleryInput} id="photo" data-testid="photo-input" type="file" accept="image/jpeg,image/png,image/webp" className="sr-only" tabIndex={-1} onChange={pickImage} disabled={locked} />
          {preview ? (
            <div className="space-y-3">
              <p className="text-lg font-bold text-leaf-700" role="status"><span aria-hidden>✔ </span>{a.photoAdded}</p>
              <img src={preview} alt={a.photoAlt} className="max-h-80 w-full rounded-xl border border-leaf-100 bg-white object-contain" />
              <div className="grid grid-cols-2 gap-3">
                <button type="button" className="btn-secondary" onClick={() => galleryInput.current?.click()} disabled={locked}>{a.changePhoto}</button>
                <button type="button" className="btn-secondary" onClick={() => setImage(null)} disabled={locked}>{a.removePhoto}</button>
              </div>
            </div>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2">
              <button type="button" className="btn-secondary" onClick={() => cameraInput.current?.click()} disabled={locked}>
                {preparing ? a.preparing : a.takePhoto}
              </button>
              <button type="button" className="btn-secondary" onClick={() => galleryInput.current?.click()} disabled={locked}>
                {a.choosePhoto}
              </button>
            </div>
          )}
        </div>

        <button className="btn-hero" disabled={locked || voiceBusy}>{busy ? a.checking : a.check}</button>
        {busy && (
          <div role="status" aria-live="polite" className="text-center">
            <Spinner label={loadingText} />
          </div>
        )}
      </form>
    </Page>
  );
}
