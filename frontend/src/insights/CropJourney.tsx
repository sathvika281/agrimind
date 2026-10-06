import { useState } from "react";
import { Link } from "react-router-dom";
import { api, type Journey } from "../api";
import { SeverityBadge } from "../components";
import { useLang } from "../LanguageContext";
import { BeforeNowView } from "../pages/InvestigationExtras";
import { PlanIcon } from "../plan/icons";
import { useKeyedData } from "./useFarmData";

const scriptOf = (text: string): "te" | "en" => (/[ఀ-౿]/.test(text) ? "te" : "en");

/** Planting -> checks -> diary, in time order, from what AgriMind already stored. No growth stage is ever guessed. */
export function CropJourney({ farmId, version, embedded = false }: { farmId: number; version: string; embedded?: boolean }) {
  const { t } = useLang();
  const [cmp, setCmp] = useState<number | null>(null); // the check whose "before vs now" is open
  const J = t.jn;
  const { data } = useKeyedData<Journey>(String(farmId), version, (id) => api.farmJourney(Number(id)));
  if (!data) return null;
  const date = (iso: string) => new Date(iso).toLocaleDateString(t.locale, { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
  const lastCheck = [...data.items].reverse().find((i) => i.type === "check");
  const hasAny = data.items.length > 0 || !!data.planting_date;
  const firstCheck = data.items.find((i) => i.type === "check");
  const Root = embedded ? "section" : "details";
  const Head = embedded ? "div" : "summary";
  return (
    <Root className="panel" data-testid="crop-journey" {...(embedded ? {} : { open: data.items.length > 0 && data.items.length <= 8 })}>
      <Head className={embedded ? "flex flex-wrap items-center gap-2 px-4 pt-4" : "flex min-h-[2.5rem] cursor-pointer items-center gap-2 px-3 py-2"}>
        <h2 className={embedded ? "text-base font-extrabold" : "text-sm font-bold"}>{J.title}</h2>
        <span className="tag-mint">{J.note}</span>
      </Head>
      {!hasAny || !firstCheck ? (
        <div className="space-y-3 px-4 pb-4 pt-2">
          <p className="text-sm text-mute">{J.noChecks}</p>
          {embedded && <JourneyGuide hasPlanting={!!data.planting_date} hasDiary={data.items.some((i) => i.type === "diary")} hasCheck={!!firstCheck} />}
          {data.planting_date && (
            <p className="text-sm font-semibold" data-testid="journey-planting">{J.planting} <span className="micro">· {date(data.planting_date)}</span>{data.days_since_planting != null && <span className="text-mute"> · {J.plantedDay(data.days_since_planting)}</span>}</p>
          )}
        </div>
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
                  {embedded && it.analysis_id !== firstCheck?.analysis_id && (
                    <button type="button" aria-expanded={cmp === it.analysis_id} onClick={() => setCmp(cmp === it.analysis_id ? null : it.analysis_id ?? null)} data-testid="journey-compare"
                      className="inline-flex min-h-[2.75rem] items-center gap-1.5 rounded-full border border-line bg-white px-3 text-xs font-semibold text-leaf-800 hover:bg-leaf-50">
                      <PlanIcon name="arrow" size={16} />{t.bn.title}
                    </button>
                  )}
                </div>
                {embedded && cmp === it.analysis_id && it.analysis_id != null && <div className="mt-2"><BeforeNowView id={it.analysis_id} version={version} embedded /></div>}
              </li>
            ),
          )}
          {data.truncated && <li className="pl-4 text-xs text-mute">{J.truncated}</li>}
        </ol>
      )}
      {embedded && firstCheck && data.items.filter((i) => i.type === "check").length === 1 && (
        <p className="mx-4 mb-4 rounded-2xl bg-leaf-50 px-3 py-2 text-sm text-leaf-900" data-testid="journey-second">{J.guide.second}</p>
      )}
      {embedded && firstCheck && (!data.planting_date || !data.items.some((i) => i.type === "diary")) && (
        <div className="px-4 pb-4"><JourneyGuide hasPlanting={!!data.planting_date} hasDiary={data.items.some((i) => i.type === "diary")} hasCheck compact /></div>
      )}
    </Root>
  );
}

/** What fills the journey. Only the missing inputs are offered; each one is a real page that records real data. */
function JourneyGuide({ hasPlanting, hasDiary, hasCheck, compact = false }: { hasPlanting: boolean; hasDiary: boolean; hasCheck: boolean; compact?: boolean }) {
  const { t } = useLang();
  const G = t.jn.guide;
  const rows = [
    !hasCheck && { to: "/analyze", icon: "inspect", title: G.check, body: G.checkBody, primary: true },
    !hasDiary && { to: "/diary", icon: "history", title: G.diary, body: G.diaryBody, primary: false },
    !hasPlanting && { to: "/profile", icon: "sow", title: G.planting, body: G.plantingBody, primary: false },
  ].filter(Boolean) as { to: string; icon: string; title: string; body: string; primary: boolean }[];
  if (rows.length === 0) return null;
  return (
    <div className="space-y-2" data-testid="journey-guide">
      {!compact && <div><p className="text-base font-extrabold text-leaf-800">{G.title}</p><p className="text-xs text-mute">{G.sub}</p></div>}
      <ul className="grid gap-2 sm:grid-cols-3">
        {rows.map((r) => (
          <li key={r.to}>
            <Link to={r.to} className={`flex h-full min-h-[4.5rem] items-start gap-3 rounded-2xl p-3 transition active:scale-[0.98] ${r.primary ? "bg-[#c8f169] text-leaf-900" : "bg-leaf-50 text-leaf-900 hover:bg-leaf-100"}`}>
              <span aria-hidden className={`grid h-9 w-9 shrink-0 place-items-center rounded-full ${r.primary ? "bg-leaf-900 text-[#c8f169]" : "bg-leaf-800 text-[#c8f169]"}`}><PlanIcon name={r.icon} size={20} /></span>
              <span className="min-w-0"><span className="block text-sm font-extrabold">{r.title}</span><span className="block text-xs">{r.body}</span></span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
