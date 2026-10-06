import type { Decision } from "../api";
import { useLang } from "../LanguageContext";
import { decisionView } from "./decision";
import { useDecision } from "./useDecision";

const ICON: Record<Decision["state"], string> = { no_actionable_evidence: "ℹ", verify: "🔍", monitor: "👁", seek_expert_help: "☎" };
const TONE: Record<Decision["state"], string> = {
  no_actionable_evidence: "border-line bg-ground text-ink",
  verify: "border-leaf-300 bg-leaf-50 text-leaf-900",
  monitor: "border-leaf-300 bg-leaf-50 text-leaf-900",
  seek_expert_help: "border-amber-300 bg-amber-50 text-amber-900",
};

interface CardProps {
  data: Decision | null;
  loading: boolean;
  error: string | null;
  retry: () => void;
  fold?: boolean; // closed row that opens in place (Result page)
}

/** Presentational: the compact "What to consider next (rule-based)" panel. Reads ONLY the decision JSON. */
export function DecisionCard({ data, loading, error, retry, fold = false }: CardProps) {
  const { t } = useLang();
  const ds = t.ds;
  const fmt = (iso: string) => new Date(iso).toLocaleDateString(t.locale, { day: "numeric", month: "short" });
  const long = (iso: string) => new Date(iso).toLocaleDateString(t.locale, { day: "numeric", month: "short", year: "numeric" });
  const v = data ? decisionView(ds, t.prof, data, fmt, long) : null;
  const Root = fold ? "details" : "section";
  const Head = fold ? "summary" : "div";
  return (
    <Root className={`panel ${fold ? "plan-row" : ""}`} aria-label={ds.title} data-testid="decision-panel" data-state={data?.state ?? (error ? "error" : "loading")}>
      <Head className={`flex flex-wrap items-center justify-between gap-2 px-4 py-3 ${fold ? "min-h-[3rem] cursor-pointer list-none [&::-webkit-details-marker]:hidden" : "border-b border-line"}`}>
        <h2 className="text-sm font-bold">{ds.title}</h2>
        {data && (
          <span className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-bold ${TONE[data.state]}`} data-testid="decision-state">
            <span aria-hidden>{ICON[data.state]}</span>
            {ds.state[data.state]}
          </span>
        )}
      </Head>
      <div className="space-y-2 p-4">
        {loading && <p role="status" aria-live="polite" className="text-sm text-mute">{t.loadingGeneric}</p>}
        {error && (
          <div role="alert" className="space-y-2 text-sm">
            <p>{error}</p>
            <button type="button" className="btn-secondary" onClick={retry}>{t.ins.retry}</button>
          </div>
        )}
        {v && data && (
          <dl className="space-y-2">
            <div>
              <dt className="micro">{ds.observedRow}</dt>
              <dd className="text-sm font-semibold" data-testid="decision-observed">{v.observed}</dd>
            </div>
            {v.evidence.length > 0 && (
              <div>
                <dt className="micro">{ds.evidenceRow}</dt>
                <dd><ul className="list-disc space-y-0.5 pl-5 text-sm" data-testid="decision-evidence">{v.evidence.map((l) => <li key={l}>{l}</li>)}</ul></dd>
              </div>
            )}
            <div>
              <dt className="micro">{ds.nextRow}</dt>
              <dd>
                {v.actions.length ? (
                  <ol className="list-decimal space-y-0.5 pl-5 text-sm font-semibold" data-testid="decision-actions">{v.actions.map((l) => <li key={l}>{l}</li>)}</ol>
                ) : (
                  <p className="text-sm text-mute" data-testid="decision-actions">{ds.noneNext}</p>
                )}
                {v.expertReason && <p className="mt-1 text-xs text-ink/80" data-testid="decision-expert">{v.expertReason}</p>}
              </dd>
            </div>
            <div>
              <dt className="micro">{ds.limitRow}</dt>
              <dd><ul className="list-disc space-y-0.5 pl-5 text-sm" data-testid="decision-limits">{v.limitations.map((l) => <li key={l}>{l}</li>)}</ul></dd>
            </div>
          </dl>
        )}
        <p className="border-t border-line pt-2 text-xs text-mute">{ds.note}</p>
      </div>
    </Root>
  );
}

/** Self-fetching version for one specific check (the Result page): described AS OF that check. */
export function DecisionPanel({ farmId, analysisId }: { farmId: number; analysisId: number }) {
  const { data, loading, error, retry } = useDecision(farmId, analysisId, "");
  return <DecisionCard data={data} loading={loading} error={error} retry={retry} fold />;
}
