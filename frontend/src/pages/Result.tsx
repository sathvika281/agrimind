import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError, type Analysis, type AnalysisResult, type Weather } from "../api";
import { ErrorBox, Page, SeverityBadge, Spinner } from "../components";
import { friendlyDate, photoTip, weatherRows } from "../copy";
import { DecisionPanel } from "../insights/DecisionPanel";
import { useLang } from "../LanguageContext";
import { PlanIcon } from "../plan/icons";
import { ListenButton } from "../voice/components";
import { BeforeNow } from "./InvestigationExtras";
import { LinkBlock, QuickQuestions, useParentCheck, VerdictCard } from "./ResultExtras";
import { WhyThisResult } from "./WhyThisResult";

function Bullets({ items, ordered = false }: { items: string[]; ordered?: boolean }) {
  if (ordered)
    return (
      <ol className="space-y-2" data-testid="steps">
        {items.map((x, i) => (
          <li key={i} className="flex items-start gap-3 rounded-2xl bg-white px-3 py-3 shadow-sm">
            <span aria-hidden className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-[#c8f169] text-sm font-extrabold text-leaf-900">{i + 1}</span>
            <span className="min-w-0 pt-0.5 text-base font-medium text-ink">{x}</span>
          </li>
        ))}
      </ol>
    );
  return (
    <ul className="space-y-1.5 text-base">
      {items.map((x, i) => (
        <li key={i} className="flex items-start gap-2"><span aria-hidden className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-leaf-500" /><span className="min-w-0">{x}</span></li>
      ))}
    </ul>
  );
}

const SECTION_ICON: Record<string, string> = { "🌿": "crop", "✅": "check", "👀": "inspect", "🧤": "warning", "📞": "info" };

/** A result block: round icon + short title. `fold` makes it a closed row that opens in place (details stay one tap away, not on screen). */
function Section({ title, icon, children, tone = "plain", fold = false }: { title: string; icon?: string; children: ReactNode; tone?: "plain" | "action" | "help"; fold?: boolean }) {
  const cls =
    tone === "action"
      ? "rounded-3xl bg-leaf-50 p-4 ring-2 ring-[#c8f169] sm:p-5"
      : tone === "help"
        ? "rounded-3xl bg-amber-50 p-4 ring-1 ring-amber-300 sm:p-5"
        : "card";
  const chip = icon ? <span aria-hidden className={`grid h-9 w-9 shrink-0 place-items-center rounded-full ${tone === "help" ? "bg-amber-200 text-amber-900" : "bg-leaf-800 text-[#c8f169]"}`}><PlanIcon name={SECTION_ICON[icon] ?? "info"} size={20} /></span> : null;
  if (fold)
    return (
      <details className={`plan-row ${cls}`}>
        <summary className="flex min-h-[2.75rem] cursor-pointer list-none items-center gap-3 py-0 text-base font-bold text-leaf-800 [&::-webkit-details-marker]:hidden">
          {chip}<span className="flex-1">{title}</span><span className="plan-chev text-mute"><PlanIcon name="chevron" size={20} /></span>
        </summary>
        <div className="mt-3 space-y-2">{children}</div>
      </details>
    );
  return (
    <section className={cls}>
      <h2 className="mb-3 flex items-center gap-3 text-lg font-bold text-leaf-800">{chip}{title}</h2>
      {children}
    </section>
  );
}

function WeatherSummary({ w }: { w: Weather }) {
  const { t } = useLang();
  const rows = weatherRows(w);
  const updated = w.fetched_at ? new Date(w.fetched_at).toLocaleTimeString(t.locale, { hour: "numeric", minute: "2-digit" }) : "";
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4 text-base text-gray-800">
      <p className="font-semibold">{t.result.weather}</p>
      <ul className="mt-1 space-y-0.5">
        {rows.map((r) => (
          <li key={r}>• {r}</li>
        ))}
      </ul>
      <p className="mt-1 text-sm text-gray-600">
        {w.location_name}
        {updated && ` · ${t.result.updated} ${updated}`}
      </p>
    </div>
  );
}

export default function Result() {
  const { id } = useParams();
  const { t, lang } = useLang();
  const R = t.result;
  const [a, setA] = useState<Analysis | null>(null);
  const [error, setError] = useState<string | null>(null);
  // "Write this result again in the other language": explicit, one model call, then stored for instant switching.
  const [translating, setTranslating] = useState(false);
  const [slow, setSlow] = useState(false);
  const [trError, setTrError] = useState<string | null>(null);
  const parent = useParentCheck(a);
  const shownId = useRef<string | undefined>(id); // the check currently on screen (guards late translate answers)
  shownId.current = id;

  useEffect(() => {
    if (!translating) return setSlow(false);
    const t1 = setTimeout(() => setSlow(true), 20_000);
    return () => clearTimeout(t1);
  }, [translating]);

  async function translateTo(target: "en" | "te"): Promise<AnalysisResult | null> {
    if (!a || translating) return null;
    setTrError(null);
    setTranslating(true);
    try {
      const res = await api.translateAnalysis(a.id, target);
      if (String(res.id) === shownId.current) setA(res); // the page then shows the version matching the UI language
      return res.translations?.[target] ?? null;
    } catch (e) {
      if (String(a.id) === shownId.current) setTrError(e instanceof ApiError ? e.message : t.err.ai);
      return null;
    } finally {
      setTranslating(false);
    }
  }

  useEffect(() => {
    if (!id) return;
    // A different check must never show the previous one while it loads, and a late answer for an old id is dropped.
    let current = true;
    setA(null);
    setError(null);
    setTrError(null);
    api
      .analysis(id)
      .then((res) => current && setA(res))
      .catch((e) => current && setError(e instanceof ApiError && e.status === 404 ? R.notFound : e instanceof ApiError ? e.message : R.couldNotLoad));
    return () => {
      current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  // Opened in a language the check was not written in: write it in the app's language once (stored, so later opens are instant).
  // One automatic try per check and language; if it fails the explicit button below stays available.
  const autoTried = useRef(new Set<string>());
  useEffect(() => {
    if (!a || translating) return;
    const original: "en" | "te" = a.language === "te" && /[ఀ-౿]/.test(`${a.result.likely_issue} ${a.result.explanation}`) ? "te" : "en";
    const have = lang === original || !!a.translations?.[lang];
    const key = `${a.id}:${lang}`;
    if (have || autoTried.current.has(key)) return;
    autoTried.current.add(key);
    void translateTo(lang);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [a, lang, translating]);

  if (error)
    return (
      <Page title={R.myCheck} back="/history">
        <ErrorBox message={error} />
      </Page>
    );
  if (!a) return <Spinner />;

  // Which language is the ORIGINAL really in? (A "te" analysis whose text has no Telugu is English.)
  const originalLang: "en" | "te" = a.language === "te" && /[ఀ-౿]/.test(`${a.result.likely_issue} ${a.result.explanation}`) ? "te" : "en";
  // Stored versions of this same check; stored extra versions win over the original for their language.
  const versions: Record<string, AnalysisResult> = { [originalLang]: a.result, ...(a.translations ?? {}) };
  const haveForUi = !!versions[lang];
  const analysisLang: "en" | "te" = haveForUi ? lang : originalLang; // language of the text shown below
  const r = versions[analysisLang];
  // Older (Phase 1/2) results have no immediate_actions: fall back to recommended_actions.
  const doNow = r.immediate_actions && r.immediate_actions.length ? r.immediate_actions : r.recommended_actions;
  const watch = r.monitoring_steps ?? [];
  const questions = r.follow_up_questions ?? [];
  const alts = r.possible_alternatives ?? [];
  const why = [...(r.evidence_for ?? []).map((x) => ({ x, fits: true })), ...(r.evidence_against ?? []).map((x) => ({ x, fits: false }))];
  const tip = photoTip(r, !!a.has_image);
  const certainty = r.uncertainty_level ? t.uncertainty[r.uncertainty_level] : undefined;
  const hasMore = (r.observations?.length ?? 0) > 0 || why.length > 0 || alts.length > 0 || (r.unknowns?.length ?? 0) > 0;
  const target = R.langNames[lang];
  const shownIsRewrite = haveForUi && lang !== originalLang;

  return (
    <Page title={R.title(a.crop)} back="/history">
      <p className="mb-3 flex flex-wrap gap-2 text-sm font-semibold text-leaf-800">
        <span className="chip">{a.farm_name}</span>
        <span className="chip">{friendlyDate(a.created_at)}</span>
        {a.has_image && <span className="chip">{R.photoIncluded}</span>}
      </p>
      {!haveForUi && (
        <div role="note" className="mb-4 space-y-2 rounded-xl bg-gray-100 px-4 py-3 text-sm text-gray-800">
          <p lang={lang}>{originalLang === "en" ? R.noticeEnglish : R.noticeTelugu}</p>
          <p>{R.translateNote(target)}</p>
          <ErrorBox message={trError} />
          <button type="button" data-testid="translate-button" className="btn-secondary" disabled={translating} onClick={() => void translateTo(lang)}>
            {trError ? t.analyze.tryAgain : R.translateBtn(target)}
          </button>
          {translating && (
            <div role="status" aria-live="polite">
              <Spinner label={slow ? t.analyze.slow : R.translating(target)} />
            </div>
          )}
        </div>
      )}
      {shownIsRewrite && (
        <p role="note" data-testid="version-note" className="mb-4 rounded-lg bg-gray-100 px-3 py-2 text-sm text-gray-800">
          {R.versionNote(target)}
        </p>
      )}

      <ListenButton result={r} lang={analysisLang} translateTo={haveForUi ? undefined : { lang, run: () => translateTo(lang) }} />

      <div className="space-y-4">
        <LinkBlock a={a} r={r} parent={parent} />
        <VerdictCard r={r} lang={analysisLang} />
        <Section title={R.doNow} icon="✅" tone="action">
          <div lang={analysisLang}><Bullets items={doNow} ordered /></div>
        </Section>

        {r.when_to_seek_help && (
          <Section title={R.help} icon="📞" tone="help">
            <p lang={analysisLang} className="text-base">{r.when_to_seek_help}</p>
          </Section>
        )}

        <QuickQuestions key={a.id} a={a} r={r} lang={analysisLang} />

        <DecisionPanel farmId={a.farm_id} analysisId={a.id} />

        <WhyThisResult
          r={a.result}
          lang={originalLang}
          moreDetails={hasMore ? (
            <section className="rounded-2xl bg-leaf-50 p-3" data-testid="more-details">
              <h3 className="text-base font-extrabold text-leaf-800">{t.ur.evidenceTitle}</h3>
            <div lang={analysisLang} className="mt-3 space-y-4 text-base">
              {r.observations && r.observations.length > 0 && (
                <div>
                  <h3 className="font-bold">{R.noticed}</h3>
                  <Bullets items={r.observations} />
                </div>
              )}
              {why.length > 0 && (
                <div>
                  <h3 className="font-bold">{R.why}</h3>
                  <ul className="space-y-1">
                    {why.map((w, i) => (
                      <li key={i}>
                        <span aria-hidden>{w.fits ? "✔ " : "✖ "}</span>
                        <span className="font-semibold">{w.fits ? R.fits : R.notFit}</span>
                        {w.x}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {alts.length > 0 && (
                <div>
                  <h3 className="font-bold">{R.others}</h3>
                  <p className="text-gray-700">{R.otherNote}</p>
                  <ul className="mt-1 space-y-2">
                    {alts.map((x, i) => (
                      <li key={i}>
                        <span className="font-semibold">{x.possibility}</span>
                        {x.how_to_tell && <span className="block text-gray-700">{R.howTell}{x.how_to_tell}</span>}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {r.unknowns && r.unknowns.length > 0 && (
                <div>
                  <h3 className="font-bold">{R.unknowns}</h3>
                  <Bullets items={r.unknowns} />
                </div>
              )}
            </div>
            </section>
          ) : null}
        />

        <Section title={R.happening} icon="🌿" fold>
          <p className="text-base text-gray-700">{R.bestGuess}</p>
          <p lang={analysisLang} className="text-xl font-bold">{r.likely_issue}</p>
          <div className="mt-2"><SeverityBadge severity={r.severity} /></div>
          {certainty && <p className="mt-3 text-base text-gray-800">{certainty}</p>}
          <p lang={analysisLang} className="mt-2 text-base text-gray-800">{r.explanation}</p>
          <p lang={analysisLang} className="mt-2 text-base text-gray-700">{r.uncertainty}</p>
        </Section>

        {watch.length > 0 && (
          <Section title={R.watch} icon="👀" fold>
            <div lang={analysisLang}><Bullets items={watch} /></div>
          </Section>
        )}

        {r.precautions.length > 0 && (
          <Section title={R.precautions} icon="🧤" fold>
            <div lang={analysisLang}><Bullets items={r.precautions} /></div>
          </Section>
        )}

        {tip && (
          <div role="note" lang={analysisLang} className="rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-base text-amber-900">
            <span aria-hidden>📷 </span>
            {tip}
          </div>
        )}

        {questions.length > 0 && (
          <Section title={R.moreInfo} fold>
            <div lang={analysisLang}><Bullets items={questions} /></div>
          </Section>
        )}


        <BeforeNow a={a} />

        {a.weather ? <WeatherSummary w={a.weather} /> : <p className="px-1 text-sm text-gray-500">{R.weatherUnavailable}</p>}

        {a.has_image && (
          <details className="card">
            <summary className="text-base font-semibold">{R.yourPhoto}</summary>
            <img src={api.imageUrl(a.id)} alt={R.photoAlt} className="mt-3 max-h-64 w-full rounded-xl border border-leaf-100 object-contain" />
            <p className="mt-2 text-sm text-gray-600">{R.photoNote}</p>
          </details>
        )}

        {a.symptoms && (
          <details className="card">
            <summary className="text-base font-semibold">{R.toldUs}</summary>
            <p className="mt-2 text-base text-gray-700">{a.symptoms}</p>
          </details>
        )}

        <div role="note" className="rounded-xl border-2 border-amber-300 bg-amber-50 px-4 py-3 text-base text-amber-900">
          {R.disclaimer}
        </div>

        <Link to={`/analyze?followup=${a.id}`} className="btn-primary" data-testid="recheck-button">{t.rf.recheck}</Link>
        <Link to="/analyze" className="btn-secondary">{R.again}</Link>
        <Link to="/history" className="btn-secondary">{R.seePast}</Link>
      </div>
    </Page>
  );
}
