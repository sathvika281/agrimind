import { api, type Patterns } from "../api";
import { Link } from "react-router-dom";
import { useLang } from "../LanguageContext";
import { useKeyedData } from "./useFarmData";

const scriptOf = (text: string): "te" | "en" => (/[ఀ-౿]/.test(text) ? "te" : "en");
/** Mirrors backend/app/services/patterns.py MIN_CHECKS (below this the server reports "not enough history"). */
export const PATTERN_MIN_CHECKS = 4;
const LABEL_STYLE: Record<string, string> = {
  strong: "border-leaf-700 bg-leaf-50 text-leaf-900",
  possible: "border-amber-300 bg-amber-50 text-amber-900",
  limited: "border-line bg-ground text-ink/80",
};

/** Recurring relationships already present in this farm's own records. Cautious wording, counts of real checks, no prediction. */
export function FarmPatterns({ farmId, version, embedded = false }: { farmId: number; version: string; embedded?: boolean }) {
  const { t } = useLang();
  const P = t.fp;
  const { data } = useKeyedData<Patterns>(String(farmId), version, (id) => api.farmPatterns(Number(id)));
  if (!data) return null;
  const Root = embedded ? "section" : "details";
  const Head = embedded ? "div" : "summary";
  return (
    <Root className="panel" data-testid="farm-patterns">
      <Head className={embedded ? "flex flex-wrap items-center gap-2 px-4 pt-4" : "flex min-h-[2.5rem] cursor-pointer items-center gap-2 px-3 py-2"}>
        <h2 className={embedded ? "text-base font-extrabold" : "text-sm font-bold"}>{P.title}</h2>
        <span className="tag-mint">{P.note}</span>
      </Head>
      <div className="space-y-3 px-4 pb-3 pt-1">
        {!data.enough ? (
          <div className="space-y-3" data-testid="patterns-guide">
            <p className="text-sm text-mute" data-testid="patterns-not-enough">{P.notEnough}</p>
            <div>
              <p className="text-sm font-extrabold text-leaf-800">{P.guide.progress(Math.min(data.total, PATTERN_MIN_CHECKS), PATTERN_MIN_CHECKS)}</p>
              <div className="mt-1 h-2.5 overflow-hidden rounded-full bg-line" role="progressbar" aria-valuemin={0} aria-valuemax={PATTERN_MIN_CHECKS} aria-valuenow={Math.min(data.total, PATTERN_MIN_CHECKS)}>
                <div className="h-2.5 rounded-full bg-[#9ad13a]" style={{ width: `${(Math.min(data.total, PATTERN_MIN_CHECKS) / PATTERN_MIN_CHECKS) * 100}%` }} />
              </div>
            </div>
            <p className="text-sm text-ink/85">{P.guide.body}</p>
            <Link to="/analyze" className="inline-flex min-h-[2.75rem] items-center rounded-full bg-[#c8f169] px-5 text-sm font-extrabold text-leaf-900 active:scale-95">{P.guide.cta}</Link>
          </div>
        ) : data.patterns.length === 0 ? (
          <p className="text-sm text-mute" data-testid="patterns-none">{P.none}</p>
        ) : (
          <>
            <p className="text-sm font-semibold" data-testid="patterns-noticed">{P.noticed}</p>
            <ul className="space-y-3">
              {data.patterns.map((p) => (
                <li key={p.issue} className="rounded-xl border border-line p-3" data-label={p.label}>
                  <div className="flex flex-wrap items-center gap-2">
                    <span lang={scriptOf(p.issue)} className="break-words text-base font-bold">{p.issue}</span>
                    <span className={`rounded-full border px-2.5 py-0.5 text-xs font-semibold ${LABEL_STYLE[p.label] ?? ""}`}>{P.label[p.label] ?? p.label}</span>
                  </div>
                  <ul className="mt-1 list-disc space-y-1 pl-5 text-sm">
                    <li>{p.recurring ? P.recurring(p.count, p.window) : P.similar}</li>
                    {p.environment.map((e) => <li key={e.kind}>{P.env(P.cond[e.kind] ?? e.kind, e.count, e.of)}</li>)}
                    {p.diary.map((d) => <li key={d.kind}>{P.diary(t.dy.kinds[d.kind] ?? d.kind, d.count, d.of)}</li>)}
                  </ul>
                </li>
              ))}
            </ul>
            <p className="text-xs text-mute">{P.caution}</p>
          </>
        )}
      </div>
    </Root>
  );
}
