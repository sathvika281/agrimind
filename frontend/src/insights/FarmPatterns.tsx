import { api, type Patterns } from "../api";
import { useLang } from "../LanguageContext";
import { useKeyedData } from "./useFarmData";

const scriptOf = (text: string): "te" | "en" => (/[ఀ-౿]/.test(text) ? "te" : "en");
const LABEL_STYLE: Record<string, string> = {
  strong: "border-leaf-700 bg-leaf-50 text-leaf-900",
  possible: "border-amber-300 bg-amber-50 text-amber-900",
  limited: "border-line bg-ground text-ink/80",
};

/** Recurring relationships already present in this farm's own records. Cautious wording, counts of real checks, no prediction. */
export function FarmPatterns({ farmId, version }: { farmId: number; version: string }) {
  const { t } = useLang();
  const P = t.fp;
  const { data } = useKeyedData<Patterns>(String(farmId), version, (id) => api.farmPatterns(Number(id)));
  if (!data) return null;
  return (
    <details className="panel" data-testid="farm-patterns">
      <summary className="flex min-h-[2.5rem] cursor-pointer items-center gap-2 px-3 py-2">
        <h2 className="text-sm font-bold">{P.title}</h2>
        <span className="tag-mint">{P.note}</span>
      </summary>
      <div className="space-y-3 px-4 pb-3 pt-1">
        {!data.enough ? (
          <p className="text-sm text-mute" data-testid="patterns-not-enough">{P.notEnough}</p>
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
    </details>
  );
}
