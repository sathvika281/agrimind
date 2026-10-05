import { Link } from "react-router-dom";
import { api, type Journey } from "../api";
import { SeverityBadge } from "../components";
import { useLang } from "../LanguageContext";
import { useKeyedData } from "./useFarmData";

const scriptOf = (text: string): "te" | "en" => (/[ఀ-౿]/.test(text) ? "te" : "en");

/** Planting -> checks -> diary, in time order, from what AgriMind already stored. No growth stage is ever guessed. */
export function CropJourney({ farmId, version }: { farmId: number; version: string }) {
  const { t } = useLang();
  const J = t.jn;
  const { data } = useKeyedData<Journey>(String(farmId), version, (id) => api.farmJourney(Number(id)));
  if (!data) return null;
  const date = (iso: string) => new Date(iso).toLocaleDateString(t.locale, { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
  const lastCheck = [...data.items].reverse().find((i) => i.type === "check");
  const hasAny = data.items.length > 0 || !!data.planting_date;
  return (
    <details className="panel" data-testid="crop-journey" open={data.items.length > 0 && data.items.length <= 8}>
      <summary className="flex min-h-[2.5rem] cursor-pointer items-center gap-2 px-3 py-2">
        <h2 className="text-sm font-bold">{J.title}</h2>
        <span className="tag-mint">{J.note}</span>
      </summary>
      {!hasAny ? (
        <p className="px-4 pb-3 text-sm text-mute">{J.noChecks}</p>
      ) : (
        <ol className="space-y-0 px-4 pb-3 pt-1">
          {data.planting_date && (
            <li className="relative border-l-2 border-line pb-3 pl-4" data-testid="journey-planting">
              <span aria-hidden className="absolute -left-[7px] top-1 h-3 w-3 rounded-full bg-leaf-800" />
              <p className="text-sm font-semibold">{J.planting} <span className="micro">· {date(data.planting_date)}</span></p>
              {data.days_since_planting != null && <p className="text-sm text-mute">{J.plantedDay(data.days_since_planting)}</p>}
            </li>
          )}
          {data.items.map((it, i) =>
            it.type === "diary" ? (
              <li key={`d${it.event_id ?? i}`} className="relative border-l-2 border-line pb-3 pl-4" data-testid="journey-diary">
                <span aria-hidden className="absolute -left-[6px] top-1.5 h-2.5 w-2.5 rounded-full bg-[#b6beb6]" />
                <p className="text-sm"><span className="font-semibold">{t.dy.kinds[it.kind ?? ""] ?? it.kind}</span> <span className="micro">· {date(it.at)}</span></p>
              </li>
            ) : (
              <li key={`c${it.analysis_id}`} className="relative border-l-2 border-line pb-3 pl-4" data-testid="journey-check" data-id={it.analysis_id}>
                <span aria-hidden className={`absolute -left-[7px] top-1 h-3 w-3 rounded-full ${it.analysis_id === lastCheck?.analysis_id ? "bg-leaf-800 ring-2 ring-leaf-200" : "bg-leaf-600"}`} />
                <p className="text-sm font-semibold">
                  {it.crop} <span className="micro">· {date(it.at)}</span>
                  {it.analysis_id === lastCheck?.analysis_id && <span className="ml-2 chip">{J.latest}</span>}
                  {it.link === "followup" && <span className="ml-2 chip">{J.followup}</span>}
                  {it.link === "refine" && <span className="ml-2 chip">{J.refined}</span>}
                </p>
                <p lang={scriptOf(it.issue ?? "")} className="break-words text-sm text-ink/90">{it.issue || "—"}</p>
                <div className="mt-0.5 flex flex-wrap items-center gap-2">
                  <SeverityBadge severity={it.severity} />
                  {it.uncertainty_level && J.unc[it.uncertainty_level] && <span className="micro">{J.unc[it.uncertainty_level]}</span>}
                  <Link to={`/analyses/${it.analysis_id}`} className="link-btn inline-flex min-h-[2.5rem] items-center text-sm" aria-label={`${J.open}: ${date(it.at)}`}>{J.open}</Link>
                </div>
              </li>
            ),
          )}
          {data.truncated && <li className="pl-4 text-xs text-mute">{J.truncated}</li>}
        </ol>
      )}
    </details>
  );
}
