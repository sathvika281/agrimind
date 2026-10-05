// Round 2 additions to the Result page: the plain verdict, the tap-questions that refine it, the follow-up comparison.
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, ApiError, newIdempotencyKey, type Analysis, type AnalysisResult } from "../api";
import { ErrorBox, SeverityBadge } from "../components";
import { friendlyDate } from "../copy";
import { useLang } from "../LanguageContext";
import { useStatus } from "../overview/StatusContext";

/** The earlier check this one refines or follows up (the farmer's own; fetched once, never polled). */
export function useParentCheck(a: Analysis | null) {
  const [parent, setParent] = useState<Analysis | null>(null);
  const pid = a?.parent_id ?? null;
  useEffect(() => {
    setParent(null);
    if (!pid) return;
    let current = true;
    api.analysis(pid).then((p) => current && setParent(p)).catch(() => undefined); // a missing parent just hides the extras
    return () => {
      current = false;
    };
  }, [pid]);
  return parent;
}

export function VerdictCard({ r, lang }: { r: AnalysisResult; lang: string }) {
  const { t } = useLang();
  const R = t.rf;
  if (!r.verdict) return null;
  const word = r.uncertainty_level ? R.confidence[r.uncertainty_level] : "";
  return (
    <section className="rounded-2xl border-2 border-leaf-600 bg-white p-5 shadow" aria-label={R.verdictTitle} data-testid="verdict-card">
      <p className="text-sm font-semibold text-mute">{R.verdictTitle}</p>
      <p lang={lang} className="mt-1 text-2xl font-extrabold leading-snug text-leaf-900">{r.verdict}</p>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {word && <span className="chip text-sm" data-testid="verdict-confidence">{word}</span>}
        <SeverityBadge severity={r.severity} />
      </div>
    </section>
  );
}

/** Tap-answers that sharpen the result: one new linked check is made from them (the model runs once). */
export function QuickQuestions({ a, r, lang }: { a: Analysis; r: AnalysisResult; lang: string }) {
  const { t } = useLang();
  const R = t.rf;
  const nav = useNavigate();
  const { refresh } = useStatus();
  const qs = r.quick_questions ?? [];
  const [picked, setPicked] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submitting = useRef(false);
  const key = useRef<{ sig: string; key: string } | null>(null);
  if (!qs.length) return null;

  async function run() {
    if (submitting.current) return;
    const answers = qs.filter((q) => picked[q.question]).map((q) => ({ question: q.question, answer: picked[q.question] }));
    if (!answers.length) return setError(R.pickOne);
    setError(null);
    const sig = JSON.stringify([a.id, answers]);
    if (!key.current || key.current.sig !== sig) key.current = { sig, key: newIdempotencyKey() };
    submitting.current = true;
    setBusy(true);
    try {
      const res = await api.refineAnalysis(a.id, answers, lang, key.current.key);
      void refresh();
      nav(`/analyses/${res.id}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t.err.ai);
      submitting.current = false;
      setBusy(false);
    }
  }

  return (
    <section className="card space-y-4" aria-label={R.askTitle} data-testid="quick-questions">
      <div>
        <h2 className="text-xl font-bold text-leaf-800">{R.askTitle}</h2>
        <p className="text-base text-mute">{R.askNote}</p>
      </div>
      <ErrorBox message={error} />
      {qs.map((q) => (
        <fieldset key={q.question} className="space-y-2" lang={lang}>
          <legend className="text-lg font-semibold">{q.question}</legend>
          <div className="flex flex-wrap gap-2" role="radiogroup" aria-label={q.question}>
            {q.options.map((o) => {
              const on = picked[q.question] === o;
              return (
                <button
                  key={o}
                  type="button"
                  role="radio"
                  aria-checked={on}
                  disabled={busy}
                  onClick={() => setPicked((p) => ({ ...p, [q.question]: on ? "" : o }))}
                  className={`min-h-[2.75rem] rounded-full border-2 px-4 text-base font-semibold ${on ? "border-leaf-800 bg-leaf-800 text-white" : "border-line bg-white text-ink hover:bg-leaf-50"}`}
                >
                  {on && <span aria-hidden>✓ </span>}
                  {o}
                </button>
              );
            })}
          </div>
        </fieldset>
      ))}
      <button type="button" className="btn-primary" disabled={busy} onClick={() => void run()} data-testid="refine-button">
        {busy ? R.refining : R.refineBtn}
      </button>
    </section>
  );
}

/** "Refined from your check of …" note and, for follow-ups, the side-by-side comparison with the earlier photo. */
export function LinkBlock({ a, r, parent }: { a: Analysis; r: AnalysisResult; parent: Analysis | null }) {
  const { t } = useLang();
  const R = t.rf;
  if (!a.parent_id || !a.link_kind) return null;
  const date = parent ? friendlyDate(parent.created_at) : "";
  if (a.link_kind === "refine")
    return (
      <p role="note" className="rounded-xl bg-leaf-50 px-4 py-3 text-base text-leaf-900" data-testid="refined-note">
        {R.refinedFrom(date || "—")}{" "}
        <Link to={`/analyses/${a.parent_id}`} className="inline-flex min-h-[2.5rem] items-center font-semibold underline">{R.openEarlier}</Link>
      </p>
    );
  const ch = r.change;
  return (
    <section className="card space-y-3" aria-label={R.compareTitle(date)} data-testid="compare-block">
      <h2 className="text-xl font-bold text-leaf-800">{R.compareTitle(date || "—")}</h2>
      {ch && (
        <p className="text-lg" data-testid="change-status" data-status={ch.status}>
          <span aria-hidden>{ch.status === "better" ? "↗ " : ch.status === "worse" ? "↘ " : ch.status === "same" ? "→ " : "? "}</span>
          <span className="font-bold">{R.change[ch.status]}</span>
          {ch.note && <span className="text-gray-800"> — {ch.note}</span>}
        </p>
      )}
      {(parent?.has_image || a.has_image) && (
        <div className="grid grid-cols-2 gap-3">
          {parent?.has_image && (
            <figure>
              <img src={api.imageUrl(parent.id)} alt={R.earlier} className="aspect-square w-full rounded-xl border border-line object-cover" />
              <figcaption className="mt-1 text-sm text-mute">{R.earlier}{date ? ` · ${date}` : ""}</figcaption>
            </figure>
          )}
          {a.has_image && (
            <figure>
              <img src={api.imageUrl(a.id)} alt={R.now} className="aspect-square w-full rounded-xl border border-line object-cover" />
              <figcaption className="mt-1 text-sm text-mute">{R.now}</figcaption>
            </figure>
          )}
        </div>
      )}
      <Link to={`/analyses/${a.parent_id}`} className="link-btn inline-flex min-h-[2.5rem] items-center">{R.openEarlier}</Link>
    </section>
  );
}


/** The Investigation Dossier: which steps really ran, what was considered, why, what is unknown, what would verify it.
 *  Built from the agents' real outputs; shown only when the agentic investigation produced it. No reasoning text. */
export function HowChecked({ r }: { r: AnalysisResult }) {
  const { t } = useLang();
  const G = t.ag;
  const Z = t.dz;
  const steps = (r.agent_steps ?? []).filter((s) => G.agents[s.agent]);
  if (steps.length === 0) return null;
  const d = r.dossier;
  const h3 = "mt-4 text-base font-bold text-leaf-800";
  return (
    <details className="card" data-testid="how-checked">
      <summary className="min-h-[2.5rem] cursor-pointer text-lg font-semibold text-leaf-800">{Z.title}</summary>
      <h3 className={h3}>{Z.agentsTitle}</h3>
      <ul className="mt-1 space-y-1 text-base">
        {steps.map((s, i) => {
          const note = s.note ? G.notes[s.note] : "";
          const label = s.status === "skipped" ? `${Z.skipped}${note ? ` · ${note}` : ""}` : `${G.status[s.status] ?? s.status}${note ? ` · ${note}` : ""}`;
          return (
            <li key={i} data-agent={s.agent} data-status={s.status}>
              <span aria-hidden>{s.status === "skipped" ? "○ " : "✓ "}</span>
              <span className="font-semibold">{G.agents[s.agent]}</span>
              <span className="text-mute"> · {label}</span>
            </li>
          );
        })}
      </ul>
      {d && (
        <div data-testid="dossier">
          {d.evidence.length > 0 && (
            <>
              <h3 className={h3}>{Z.evidenceTitle}</h3>
              <ul className="mt-1 space-y-1 text-base" data-testid="dossier-evidence">
                {d.evidence.map((f) => {
                  const fn = Z.ev[f.kind];
                  return fn ? <li key={f.kind} data-used={String(!!f.used)}><span aria-hidden>{f.used ? "✓ " : "○ "}</span>{fn(f.count ?? 0, !!f.used)}</li> : null;
                })}
              </ul>
            </>
          )}
          {d.why.length > 0 && (
            <>
              <h3 className={h3}>{Z.whyTitle}</h3>
              <ul className="mt-1 list-disc space-y-1 pl-5 text-base" data-testid="dossier-why">
                {d.why.map((f) => { const fn = Z.why[f.kind]; return fn ? <li key={f.kind}>{fn(f.count ?? 0)}</li> : null; })}
              </ul>
            </>
          )}
          {(d.unknown.length > 0 || (r.unknowns ?? []).length > 0) && (
            <>
              <h3 className={h3}>{Z.unknownTitle}</h3>
              <ul className="mt-1 list-disc space-y-1 pl-5 text-base" data-testid="dossier-unknown">
                {d.unknown.map((f) => (Z.unknown[f.kind] ? <li key={f.kind}>{Z.unknown[f.kind]}</li> : null))}
                {(r.unknowns ?? []).slice(0, 3).map((u, i) => <li key={`u${i}`}>{u}</li>)}
              </ul>
            </>
          )}
          {d.verify.length > 0 && (
            <>
              <h3 className={h3}>{Z.verifyTitle}</h3>
              <ul className="mt-1 list-disc space-y-1 pl-5 text-base" data-testid="dossier-verify">
                {d.verify.map((f) => (Z.verify[f.kind] ? <li key={f.kind}>{Z.verify[f.kind]}</li> : null))}
              </ul>
            </>
          )}
        </div>
      )}
    </details>
  );
}

/** Trusted documents that were really retrieved and relied on. Shown only when there are some. */
export function SourcesBlock({ r }: { r: AnalysisResult }) {
  const { t } = useLang();
  const G = t.ag;
  const sources = r.sources ?? [];
  if (sources.length === 0) return null;
  return (
    <section className="card space-y-2" data-testid="sources">
      <h2 className="text-xl font-bold text-leaf-800">{G.sourcesTitle}</h2>
      <p className="text-base text-mute">{G.sourcesNote}</p>
      <ul className="space-y-2 text-base">
        {sources.map((s) => (
          <li key={s.url}>
            <a href={s.url} target="_blank" rel="noopener noreferrer" className="link-btn inline-flex min-h-[2.5rem] items-center font-semibold underline">{s.title}</a>
            <span className="block text-mute">{s.institution}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
