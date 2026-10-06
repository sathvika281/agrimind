import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { api, ApiError, type Analysis, type AnalysisResult, type Farm, type Weather, type WeatherRisk } from "../api";
import type { Dict } from "../i18n/en";
import { SeverityBadge } from "../components";
import { friendlyDate, shortIssue } from "../copy";
import { IconCopilot, IconDrop, IconWeather } from "../icons";
import { useLang } from "../LanguageContext";
import { levelOf, rainOutlook } from "./derive";
import { LEVEL_SWATCH } from "./FarmMap";
import { useStatus, type FarmWeather } from "./StatusContext";
import { WeatherTips } from "./WeatherTips";

function PanelHead({ title, right }: { title: string; right?: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-2 px-4 pb-1 pt-4">
      <h2 className="text-base font-extrabold text-ink">{title}</h2>
      {right}
    </div>
  );
}

const fmt = (n: number | null | undefined, unit = "") => (n == null ? "—" : `${Math.round(n * 10) / 10}${unit}`);

function Metric({ label, value, sub, icon, dark = false }: { label: string; value: ReactNode; sub?: string; icon?: ReactNode; dark?: boolean }) {
  return (
    <div className={`rounded-2xl px-3 py-3 ${dark ? "bg-leaf-900 text-white" : "bg-leaf-50"}`}>
      <div className={`micro flex items-center gap-1 ${dark ? "!text-white/80" : ""}`}>{icon}{label}</div>
      <div className={`text-xl font-extrabold leading-tight ${dark ? "text-white" : "text-ink"}`}>{value}</div>
      {sub && <div className={`text-xs ${dark ? "text-white/80" : "text-mute"}`}>{sub}</div>}
    </div>
  );
}

const versionFor = (a: Analysis, lang: string): AnalysisResult => a.translations?.[lang] ?? a.result;
const scriptLang = (r: AnalysisResult): "te" | "en" => (/[ఀ-౿]/.test(`${r.likely_issue} ${r.explanation}`) ? "te" : "en");

/** A small tag when the AI-written text on screen is in the other language (nothing is translated silently). */
function LangTag({ shown }: { shown: AnalysisResult }) {
  const { t, lang } = useLang();
  const from = scriptLang(shown);
  if (from === lang) return null;
  return <span className="chip" data-testid="lang-tag">{t.ov.writtenTag(t.result.langNames[from])}</span>;
}

// ---------------------------------------------------------------- Field intelligence (slim)
export function FieldPanel({ farm, analysis }: { farm: Farm; analysis?: Analysis; weather?: FarmWeather }) {
  const { t, lang } = useLang();
  const O = t.ov;
  const r = analysis ? versionFor(analysis, lang) : null;
  return (
    <section className="panel" aria-label={O.panelTitle}>
      <div className="space-y-2 p-4">
        <span className="tag-mint">{O.panelTitle}</span>
        <div>
          <h2 className="text-lg font-extrabold leading-tight text-ink">{farm.name}</h2>
          <p className="text-sm text-mute">{[analysis?.crop, farm.location].filter(Boolean).join(" · ") || "—"}</p>
        </div>
        <p className="text-sm">
          <span className="text-mute">{O.lastCheck}: </span>
          <span className="font-semibold">{analysis ? friendlyDate(analysis.created_at) : O.noCheck}</span>
        </p>
        {r && (
          <div className="flex flex-wrap items-center gap-1.5">
            <SeverityBadge severity={r.severity} />
            <LangTag shown={r} />
          </div>
        )}
        {r && <p lang={scriptLang(r)} className="text-sm text-ink/85">{shortIssue(r.likely_issue)}</p>}
      </div>
    </section>
  );
}

/** The check is written in the other language: say so and offer ONE explicit, cached rewrite (never automatic). */
function WriteIn({ analysis, shown }: { analysis: Analysis; shown: AnalysisResult }) {
  const { t, lang } = useLang();
  const { replace } = useStatus();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const from = scriptLang(shown);
  if (from === lang || analysis.translations?.[lang]) return null;
  const toName = t.result.langNames[lang];
  async function run() {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      replace(await api.translateAnalysis(analysis.id, lang)); // same endpoint as the Result page; one call, stored on the server
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t.err.ai);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div role="note" className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border border-amber-300 bg-amber-50 px-3 py-1.5 text-sm text-amber-900" data-testid="write-in">
      <span>{t.ov.writtenIn(t.result.langNames[from])}</span>
      <button type="button" data-testid="write-in-button" className="btn-sm-light w-auto px-4" disabled={busy} onClick={() => void run()}>
        {error ? t.analyze.tryAgain : t.ov.writeBtn(toName)}
      </button>
      {busy && <span role="status" aria-live="polite" className="text-xs">{t.ov.writing(toName)}</span>}
      {error && <span role="alert" className="text-xs">{error}</span>}
    </div>
  );
}

export function LatestAdvice({ analysis }: { farm?: Farm; analysis?: Analysis }) {
  const { t, lang } = useLang();
  const O = t.ov;
  const r = analysis ? versionFor(analysis, lang) : null;
  const doNow = r ? (r.immediate_actions?.length ? r.immediate_actions : r.recommended_actions).slice(0, 2) : [];
  const L = r ? scriptLang(r) : lang;

  return (
    <section className="panel" aria-label={O.copilotTitle} data-testid="copilot">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-2.5">
        <div className="flex items-center gap-2.5">
          <span aria-hidden className="grid h-9 w-9 place-items-center rounded-md bg-leaf-800 text-mint-100"><IconCopilot /></span>
          <div className="leading-tight">
            <h2 className="text-base font-bold">{O.copilotTitle}{analysis ? <span className="font-normal text-mute"> · {analysis.crop}</span> : null}</h2>
          </div>
        </div>
      </div>

      <div className="space-y-3 p-4">
        {!analysis || !r ? (
          <div className="grid gap-3 sm:grid-cols-[1fr_auto] sm:items-center">
            <div>
              <p className="font-bold">{O.noCheckTitle}</p>
              <p className="text-sm text-mute">{O.noCheckBody}</p>
            </div>
            <Link to="/analyze" className="btn-sm-dark w-auto px-5">{O.runCheck}</Link>
          </div>
        ) : (
          <>
            <WriteIn analysis={analysis} shown={r} />
            <div lang={L} className="space-y-1">
              <div className="flex flex-wrap items-center gap-2">
                <p className="text-lg font-bold leading-snug" data-testid="advice-title">{r.verdict || r.likely_issue}</p>
                <SeverityBadge severity={r.severity} />
              </div>
            </div>
            {doNow.length > 0 && (
              <div lang={L}>
                <ol className="space-y-2" data-testid="advice-steps">{doNow.map((x, i) => <li key={i} className="flex items-start gap-3 rounded-2xl bg-leaf-50 px-3 py-2.5 text-sm font-medium"><span aria-hidden className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-[#c8f169] text-xs font-extrabold text-leaf-900">{i + 1}</span><span className="min-w-0">{x}</span></li>)}</ol>
              </div>
            )}
            <div className="flex flex-wrap gap-2">
              <Link to={`/analyses/${analysis.id}`} className="btn-sm-dark w-auto px-5">{O.openResult}</Link>
            </div>
          </>
        )}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------- Weather (REAL, Open-Meteo)
function riskText(W: Dict["wr"], k: WeatherRisk): string {
  const n = (v: number | null) => String(Math.round((v ?? 0) * 10) / 10);
  if (k.kind === "humid_wet") return W.humid_wet(n(k.humidity_pct), n(k.rain_mm));
  if (k.kind === "heavy_rain") return W.heavy_rain(n(k.rain_mm));
  if (k.kind === "hot_dry") return W.hot_dry(n(k.temp_max_c));
  return W.extreme_heat(n(k.temp_max_c));
}

export function WeatherCard({ farm, weather, heading, anchor = true, showTips = false, alerts }: { farm: Farm; weather?: FarmWeather; heading?: string; anchor?: boolean; showTips?: boolean; alerts?: ReactNode }) {
  const { t } = useLang();
  const O = t.ov;
  const w: Weather | null | undefined = weather?.weather;
  const out = rainOutlook(w);
  const upd = w?.fetched_at ? new Date(w.fetched_at).toLocaleTimeString(t.locale, { hour: "numeric", minute: "2-digit" }) : "";
  return (
    <section id={anchor ? "weather" : undefined} className="panel scroll-mt-4" aria-label={heading ?? O.weatherTitle} data-testid={anchor ? undefined : `weather-farm-${farm.id}`}>
      <PanelHead title={heading ?? O.weatherTitle} right={w ? <span className="tag-mint">{O.tagReal}{upd ? ` · ${upd}` : ""}</span> : undefined} />
      {!w ? (
        <p className="p-4 text-sm text-mute">{farm.location.trim() ? O.unavailable : O.noLocation}</p>
      ) : (
        <div className="space-y-3 p-4">
          <div className="grid grid-cols-2 gap-2">
            <Metric dark icon={<IconWeather />} label={O.now} value={fmt(w.temperature_c, "°C")} sub={`${O.humidity} ${fmt(w.humidity_pct, "%")} · ${O.wind} ${fmt(w.wind_kmh, " km/h")}`} />
            <Metric icon={<IconWeather />} label={O.today} value={`${fmt(w.temp_min_c)}–${fmt(w.temp_max_c, "°C")}`} />
            <Metric icon={<IconDrop />} label={O.past} value={w.past_3d_rain_mm == null ? t.wt.notAvailable : O.rainMm(fmt(w.past_3d_rain_mm))} />
            <Metric icon={<IconDrop />} label={O.next} value={O.rainMm(fmt(w.next_3d_rain_mm))} />
          </div>
          <p className="flex items-start gap-2 text-sm text-leaf-800">
            <IconDrop />
            <span>{out.kind === "rain" ? O.factRain(String(out.mm)) : out.kind === "dry" ? O.factDry : O.unavailable}</span>
          </p>
          {alerts}
          {showTips && <WeatherTips farmId={farm.id} version={String(weather?.at ?? "")} />}
          {weather?.risks && weather.risks.length > 0 && (
            <div className="rounded-md border border-amber-300 bg-amber-50 p-2.5 text-sm text-amber-900" data-testid="weather-risks">
              <p className="text-xs font-semibold">{t.wr.title}</p>
              <ul className="mt-1 space-y-1">
                {weather.risks.map((k) => (
                  <li key={k.kind} data-kind={k.kind}>{riskText(t.wr, k)}</li>
                ))}
              </ul>
              <p className="mt-1 text-xs text-amber-900/80">{t.wr.note}</p>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------- Farm profile (only what the farmer entered)
export function FarmProfileCard({ farm }: { farm: Farm }) {
  const { t } = useLang();
  const P = t.prof;
  const date = (iso: string) => new Date(iso).toLocaleDateString(t.locale, { day: "numeric", month: "long", year: "numeric" });
  const rows: [string, string | null | undefined][] = [
    [P.village, farm.location],
    [P.soil, farm.soil_type],
    [P.crop, farm.primary_crop],
    [P.irrigation, farm.irrigation_method ? P.irrigationOpts[farm.irrigation_method] ?? farm.irrigation_method : null],
    [P.season, farm.season ? P.seasonOpts[farm.season] ?? farm.season : null],
    [P.planting, farm.planting_date ? date(farm.planting_date) : null],
  ];
  return (
    <section className="panel" aria-label={P.title} data-testid="farm-profile-card">
      <div className="flex flex-wrap items-center justify-between gap-2 px-4 pb-1 pt-4">
        <div className="flex items-center gap-2">
          <h2 className="text-base font-extrabold">{P.title}</h2>
        </div>
      </div>
      <dl className="px-4 py-1">
        {rows.filter(([, value]) => !!value).map(([label, value]) => (
          <div key={label} className="flex items-baseline justify-between gap-3 border-b border-line py-1.5 last:border-b-0">
            <dt className="micro">{label}</dt>
            <dd className="min-w-0 break-words text-right text-sm font-semibold">{value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

/** Four REAL totals: farms, stored checks, farms whose latest check needs attention, newest check date. */
export function SummaryCards({ farms, analyses, needsAttention }: { farms: Farm[]; analyses: Analysis[]; needsAttention: number }) {
  const { t } = useLang();
  const O = t.ov;
  const Card = ({ label, value, id }: { label: string; value: ReactNode; id: string }) => (
    <div className="min-w-0 rounded-3xl bg-white px-4 py-3 shadow-[0_10px_28px_-18px_rgba(13,45,33,0.35)]" data-testid={id}>
      <div className="micro truncate">{label}</div>
      <div className="truncate text-2xl font-extrabold leading-tight text-ink">{value}</div>
    </div>
  );
  return (
    <section aria-label={O.farmsTitle} className="grid grid-cols-3 gap-3">
      <Card id="sum-farms" label={O.sumFarms} value={farms.length} />
      <Card id="sum-checks" label={O.sumChecks} value={analyses.length} />
      <Card id="sum-attention" label={O.sumAttention} value={needsAttention} />
    </section>
  );
}

/** The 5 newest stored checks across all farms; each opens its result. */
export function RecentChecks({ analyses }: { analyses: Analysis[] }) {
  const { t, lang } = useLang();
  const O = t.ov;
  const rows = analyses.slice(0, 3);
  return (
    <section className="panel min-w-0" aria-label={O.recentTitle} data-testid="recent-checks">
      <div className="flex items-center justify-between gap-2 px-4 pb-1 pt-4">
        <h2 className="text-base font-extrabold">{O.recentTitle}</h2>
      </div>
      {rows.length === 0 ? (
        <div className="grid gap-2 p-4 text-center">
          <p className="font-bold">{O.recentEmpty}</p>
          <p className="text-sm text-mute">{O.recentEmptyBody}</p>
          <Link to="/analyze" className="btn-sm-dark mx-auto w-auto px-5">{t.dash.checkCrop}</Link>
        </div>
      ) : (
        <ol className="divide-y divide-line">
          {rows.map((a) => {
            const lv = levelOf(a);
            return (
              <li key={a.id}>
                <Link to={`/analyses/${a.id}`} className="flex min-h-[3.25rem] items-center gap-3 px-4 py-2.5 hover:bg-ground">
                  <span aria-hidden className="h-3 w-3 shrink-0 rounded-sm" style={{ background: LEVEL_SWATCH[lv] }} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-semibold">{a.crop} — {shortIssue(versionFor(a, lang).likely_issue)}</span>
                    <span className="micro block truncate">{a.farm_name} · {friendlyDate(a.created_at)}</span>
                    <LangTag shown={versionFor(a, lang)} />
                  </span>
                </Link>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}

/** Every farm with its real latest status and stored-check count. Choosing one makes it the current farm. */
export function YourFarms({ farms, latest, analyses, selectedId, onSelect }: { farms: Farm[]; latest: Map<number, Analysis>; analyses: Analysis[]; selectedId: number; onSelect: (id: number) => void }) {
  const { t } = useLang();
  const O = t.ov;
  const counts = new Map<number, number>();
  for (const a of analyses) counts.set(a.farm_id, (counts.get(a.farm_id) ?? 0) + 1);
  return (
    <section className="panel min-w-0" aria-label={O.farmsTitle} data-testid="your-farms">
      <div className="flex items-center justify-between gap-2 px-4 pb-1 pt-4">
        <h2 className="text-base font-extrabold">{O.farmsTitle}</h2>
      </div>
      <ul className="max-h-[22rem] divide-y divide-line overflow-y-auto">
        {farms.map((f) => {
          const lv = levelOf(latest.get(f.id));
          const n = counts.get(f.id) ?? 0;
          const active = f.id === selectedId;
          return (
            <li key={f.id}>
              <button
                type="button"
                aria-pressed={active}
                aria-label={O.farmShowAria(f.name)}
                data-testid={`your-farm-${f.id}`}
                onClick={() => onSelect(f.id)}
                className={`flex min-h-[3rem] w-full items-center gap-3 px-3 py-2 text-left ${active ? "bg-leaf-50" : "hover:bg-ground"}`}
              >
                <span aria-hidden className="h-3 w-3 shrink-0 rounded-sm" style={{ background: LEVEL_SWATCH[lv] }} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-semibold">{f.name}</span>
                  <span className="micro block truncate">{[f.location, n ? O.farmChecks(n) : O.farmNoChecks].filter(Boolean).join(" · ")}</span>
                </span>
              </button>
            </li>
          );
        })}
      </ul>
      <div className="border-t border-line p-2">
        <Link to="/farms/new" className="btn-sm-light w-auto px-5">{O.addFarm}</Link>
      </div>
    </section>
  );
}
