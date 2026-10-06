// Result-page investigation views: the competing explanations and the comparison with the previous check.
// Both only re-present data AgriMind already stored (the agents' coded evidence, two stored results); no model call.
import { Link } from "react-router-dom";
import type { Analysis, AnalysisResult, Comparison } from "../api";
import { api } from "../api";
import { SeverityBadge } from "../components";
import { useKeyedData } from "../insights/useFarmData";
import { useLang } from "../LanguageContext";

const scriptOf = (text: string): "te" | "en" => (/[ఀ-౿]/.test(text) ? "te" : "en");

/** Possible explanations, never a diagnosis and never a score. Shown only for investigations that produced candidates. */
export function Hypotheses({ r, lang, embedded = false }: { r: AnalysisResult; lang: string; embedded?: boolean }) {
  const { t } = useLang();
  const H = t.hy;
  const d = r.dossier;
  const items = d?.hypotheses ?? [];
  if (!d || items.length === 0) return null;
  const help = d.verify.filter((f) => t.dz.verify[f.kind]);
  const Root = embedded ? "section" : "details";
  return (
    <Root className={embedded ? "rounded-2xl bg-leaf-50 p-3" : "card"} data-testid="hypotheses">
      {embedded ? <h3 className="text-base font-extrabold text-leaf-800">{H.title}</h3> : <summary className="min-h-[2.5rem] cursor-pointer text-lg font-semibold text-leaf-800">{H.title}</summary>}
      <p className="mt-2 text-base text-mute">{H.note}</p>
      <ol className="mt-3 space-y-4">
        {items.map((h, i) => (
          <li key={i} className="rounded-xl border border-line p-3" data-rank={h.rank}>
            <p className="text-xs font-semibold text-mute">{h.rank === "better_supported" ? H.better : H.also}</p>
            <p lang={lang} className="text-lg font-bold">{h.label}</p>
            <p className="mt-2 text-sm font-semibold text-leaf-800">{H.supporting}</p>
            {h.supporting.length ? (
              <ul className="list-disc space-y-0.5 pl-5 text-base">
                {h.supporting.map((f) => { const fn = H.sup[f.kind]; return fn ? <li key={f.kind}>{fn(f.count ?? 0)}</li> : null; })}
              </ul>
            ) : <p className="text-base text-mute">{H.noSupport}</p>}
            {h.against_or_unknown.length > 0 && (
              <>
                <p className="mt-2 text-sm font-semibold text-leaf-800">{H.gaps}</p>
                <ul className="list-disc space-y-0.5 pl-5 text-base">
                  {h.against_or_unknown.map((f) => (H.gap[f.kind] ? <li key={f.kind}>{H.gap[f.kind]}</li> : null))}
                </ul>
              </>
            )}
            {h.how_to_tell && <p lang={lang} className="mt-2 text-base text-ink/90"><span className="font-semibold">{H.howTell}</span>{h.how_to_tell}</p>}
          </li>
        ))}
      </ol>
      {(help.length > 0 || (r.follow_up_questions ?? []).length > 0) && (
        <div className="mt-4">
          <h3 className="text-base font-bold text-leaf-800">{H.helpTitle}</h3>
          <ul className="mt-1 list-disc space-y-1 pl-5 text-base" data-testid="hypotheses-help">
            {help.map((f) => <li key={f.kind}>{t.dz.verify[f.kind]}</li>)}
            {(r.follow_up_questions ?? []).slice(0, 2).map((q, i) => <li key={`q${i}`} lang={lang}>{q}</li>)}
          </ul>
        </div>
      )}
    </Root>
  );
}

function Side({ title, c, id }: { title: string; c: Comparison["previous"]; id: string }) {
  const { t, lang } = useLang();
  const fmt = new Date(c.at).toLocaleDateString(t.locale, { day: "numeric", month: "short", year: "numeric" });
  return (
    <div className="min-w-0 rounded-xl border border-line p-3" data-testid={id}>
      <p className="text-xs font-semibold text-mute">{title} · {fmt}</p>
      <p lang={scriptOf(c.issue)} className="mt-1 break-words text-base font-bold">{c.issue || "—"}</p>
      <div className="mt-1 flex flex-wrap items-center gap-2">
        <SeverityBadge severity={c.severity} />
        {c.uncertainty_level !== "unknown" && <span className="chip">{t.jn.unc[c.uncertainty_level] ?? ""}</span>}
      </div>
      {id === "bn-previous" && (
        <Link to={`/analyses/${c.analysis_id}`} className="link-btn mt-1 inline-flex min-h-[2.5rem] items-center text-sm" aria-label={`${t.jn.open}: ${fmt}`} data-lang={lang}>{t.jn.open}</Link>
      )}
    </div>
  );
}

/** This check next to the previous relevant one, with qualitative changes and a direction only when evidence supports one. */
export function BeforeNow({ a }: { a: Analysis }) {
  const { t } = useLang();
  return (
    <BeforeNowView id={a.id} version={String(a.parent_id ?? "")} extra={<Link to="/insights?tab=journey" className="link-btn mt-2 inline-flex min-h-[2.75rem] items-center text-sm" data-testid="journey-link">{t.bn.journeyLink}</Link>} />
  );
}

/** Reused: the Result page (as a card) and the Crop Journey (per check, `embedded`). Same endpoint, same comparison logic. */
export function BeforeNowView({ id, version = "", embedded = false, extra }: { id: number; version?: string; embedded?: boolean; extra?: React.ReactNode }) {
  const { t } = useLang();
  const B = t.bn;
  const { data } = useKeyedData<Comparison | null>(String(id), version, (x) => api.analysisComparison(x));
  if (!data) return embedded ? <p className="rounded-xl bg-leaf-50 p-3 text-sm text-mute" data-testid="bn-none">{B.noEarlier}</p> : null;
  const c = data.compare;
  const changes: string[] = [];
  if (B.issue[c.issue]) changes.push(B.issue[c.issue]);
  if (c.severity.change !== "unknown" && B.sev[c.severity.change]) changes.push(B.sev[c.severity.change]);
  if (B.unc[c.uncertainty.change]) changes.push(B.unc[c.uncertainty.change]);
  if (c.model_change && B.model[c.model_change]) changes.push(B.model[c.model_change]);
  const obs = c.observations;
  const Root = embedded ? "section" : "details";
  return (
    <Root className={embedded ? "rounded-2xl bg-leaf-50 p-3" : "card"} data-testid="before-now">
      {embedded ? <h3 className="text-base font-extrabold text-leaf-800">{B.title}</h3> : <summary className="min-h-[2.5rem] cursor-pointer text-lg font-semibold text-leaf-800">{B.title}</summary>}
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <Side title={B.previous} c={data.previous} id="bn-previous" />
        <Side title={B.now} c={data.now} id="bn-now" />
      </div>
      <h3 className="mt-4 text-base font-bold text-leaf-800">{B.changedTitle}</h3>
      <ul className="mt-1 list-disc space-y-1 pl-5 text-base" data-testid="bn-changes">
        {changes.map((x) => <li key={x}>{x}</li>)}
        {obs.still_present.map((o, i) => <li key={`s${i}`}><span className="font-semibold">{B.stillPresent}: </span><span lang={scriptOf(o)}>{o}</span></li>)}
        {obs.new.map((o, i) => <li key={`n${i}`}><span className="font-semibold">{B.newObs}: </span><span lang={scriptOf(o)}>{o}</span></li>)}
        {obs.not_mentioned_now.map((o, i) => <li key={`g${i}`}><span className="font-semibold">{B.notNow}: </span><span lang={scriptOf(o)}>{o}</span></li>)}
      </ul>
      <p className="mt-3 text-base" data-testid="bn-direction" data-direction={c.direction}>
        <span className="font-bold text-leaf-800">{B.directionTitle}: </span>{B.direction[c.direction]}
      </p>
      <p className="mt-1 text-sm text-mute">{B.basis}</p>
      {extra}
    </Root>
  );
}
