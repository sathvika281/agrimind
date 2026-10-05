import { Link } from "react-router-dom";
import type { Proactive } from "../api";
import { useLang } from "../LanguageContext";
import { proactiveViews } from "./proactive";

interface Props {
  data: Proactive | null;
  loading: boolean;
  error: string | null;
  retry: () => void;
  farmName: string;
}

const ICON = { attention: "!", important: "⚠" } as const;
const COLS = { 1: "lg:grid-cols-1", 2: "lg:grid-cols-2", 3: "lg:grid-cols-3" } as const;
const TONE = {
  attention: "border-amber-300 bg-amber-50 text-amber-900",
  important: "border-red-300 bg-red-50 text-red-900",
} as const;

/** Compact "Needs your attention": at most 3 items from the stored checks of the selected farm. Quiet when there is nothing. */
export function ProactiveSection({ data, loading, error, retry, farmName }: Props) {
  const { t } = useLang();
  const P = t.pi;
  const fmt = (iso: string) => new Date(iso).toLocaleDateString(t.locale, { day: "numeric", month: "short", year: "numeric" });
  const views = data ? proactiveViews(P, t.ds, data, fmt) : [];
  return (
    <section className="panel" aria-label={P.title} data-testid="proactive" data-state={error ? "error" : loading ? "loading" : data?.level ?? "none"}>
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-0.5 border-b border-line px-3 py-2">
        <h2 className="text-sm font-bold">{P.title}</h2>
        <span className="micro truncate">{P.forFarm(farmName)}</span>
      </div>
      {loading && <p role="status" aria-live="polite" className="px-3 py-2 text-sm text-mute">{t.loadingGeneric}</p>}
      {error && (
        <div role="alert" className="flex flex-wrap items-center gap-3 px-3 py-2 text-sm">
          <span>{error}</span>
          <button type="button" className="btn-sm-light w-auto px-4" onClick={retry}>{t.ins.retry}</button>
        </div>
      )}
      {data && views.length === 0 && <p className="px-3 py-2 text-sm text-mute" data-testid="proactive-none">{P.none}</p>}
      {views.length > 0 && (
        <ul className={`grid grid-cols-[minmax(0,1fr)] gap-2 p-2 ${COLS[Math.min(3, views.length) as 1 | 2 | 3]}`}>
          {views.map((v, i) => (
            <li key={`${v.analysisId}-${i}`} className="min-w-0 space-y-1 rounded-md border border-line bg-ground p-2.5" data-testid="proactive-item" data-priority={v.priority}>
              <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-bold ${TONE[v.priority]}`}>
                <span aria-hidden>{ICON[v.priority]}</span>
                {P.priority[v.priority]}
              </span>
              <h3 className="text-sm font-bold leading-snug">{v.title}</h3>
              <p className="break-words text-xs font-semibold text-ink/80">{v.issue}</p>
              <ul className="list-disc space-y-0.5 pl-4 text-xs">{v.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
              <p className="text-xs text-mute">{v.meta}</p>
              <p className="text-xs"><span className="micro">{P.nextStep}: </span>{v.next}</p>
              <Link to={`/analyses/${v.analysisId}`} className="btn-sm-light w-auto px-4" aria-label={`${P.details}: ${v.title}`}>{P.details}</Link>
            </li>
          ))}
        </ul>
      )}
      <p className="border-t border-line px-3 py-1.5 text-xs text-mute">{P.note}</p>
    </section>
  );
}
