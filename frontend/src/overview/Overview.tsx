import { useEffect, useMemo, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { ErrorBox, EmptyState, Spinner } from "../components";
import { useFarms } from "../FarmContext";
import { useLang } from "../LanguageContext";
import { FarmMap, type Layer } from "./FarmMap";
import { FarmProfileCard, FieldPanel, LatestAdvice, RecentChecks, SummaryCards, WeatherCard, YourFarms } from "./panels";
import { MAX_FIELDS } from "./derive";
import { useStatus } from "./StatusContext";
import { ProactiveSection } from "../insights/ProactiveSection";
import { useProactive } from "../insights/useProactive";

function greetingKey(): "morning" | "afternoon" | "evening" {
  const h = new Date().getHours();
  return h < 12 ? "morning" : h < 17 ? "afternoon" : "evening";
}

export default function Overview() {
  const { t } = useLang();
  const O = t.ov;
  const { farms, selected, select, loading, error } = useFarms();
  const { analyses, latest, summary, weatherByFarm, loadWeather } = useStatus();
  const [layer, setLayer] = useState<Layer>("health");
  // Re-asks the server only when the farm changes or a check for THIS farm is added (never on a timer).
  const attentionVersion = useMemo(() => {
    const mine = (analyses ?? []).filter((a) => a.farm_id === selected?.id);
    return `${mine.length}:${mine[0]?.id ?? 0}`;
  }, [analyses, selected?.id]);
  const proactive = useProactive(selected?.id ?? null, attentionVersion);
  const { hash } = useLocation();

  // "Weather" in the sidebar links to #weather on this page.
  useEffect(() => {
    if (hash === "#weather" && selected) document.getElementById("weather")?.scrollIntoView();
  }, [hash, selected, analyses]);

  // The weather layer colours every farm, so load weather for all shown farms (cached on the server).
  useEffect(() => {
    if (layer === "weather" && farms) void loadWeather(farms.slice(0, MAX_FIELDS).map((f) => f.id));
  }, [layer, farms, loadWeather]);

  if (error) return <ErrorBox message={error} />;
  if (!farms || !analyses || loading) return <Spinner />;

  if (!selected)
    return (
      <div className="mx-auto max-w-xl space-y-6 py-6">
        <h1 className="text-3xl font-bold text-leaf-800">{t.dash.welcome}</h1>
        <p className="text-lg text-mute">{t.appTagline}. {t.dash.intro}</p>
        <EmptyState title={t.dash.noFarm} action={<Link to="/farms/new" className="btn-hero">{t.dash.addFarm}</Link>} />
      </div>
    );

  const fw = weatherByFarm[selected.id];
  const latestSel = latest.get(selected.id);

  return (
    <div className="mx-auto max-w-[1280px] space-y-5">
      {/* greeting + the one primary action */}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-3xl font-extrabold text-ink">{O.greeting[greetingKey()]}</h1>
          <p className="mt-1 text-base text-mute">{O.stateLine(selected.name, summary.needsAttention)}</p>
        </div>
        <Link to="/analyze" className="btn-sm-dark w-auto px-6">📷 {t.dash.checkCrop}</Link>
      </div>

      <SummaryCards farms={farms} analyses={analyses} needsAttention={summary.needsAttention} />

      <ProactiveSection data={proactive.data} loading={proactive.loading} error={proactive.error} retry={proactive.retry} farmName={selected.name} />

      {/* map + field panel */}
      <div className="grid grid-cols-[minmax(0,1fr)] gap-4 lg:grid-cols-2">
        <FarmMap
          farms={farms}
          latest={latest}
          selectedId={selected.id}
          onSelect={select}
          layer={layer}
          onLayer={setLayer}
          weatherByFarm={weatherByFarm}
        />
        <div className="grid min-w-0 grid-rows-[auto_1fr] gap-4">
          <FieldPanel farm={selected} analysis={latestSel} weather={fw} />
          <WeatherCard farm={selected} weather={fw} />
        </div>
      </div>

      <div className="grid grid-cols-[minmax(0,1fr)] gap-4 lg:grid-cols-2">
        <LatestAdvice farm={selected} analysis={latestSel} />
        <RecentChecks analyses={analyses} />
      </div>

      <div className="grid grid-cols-[minmax(0,1fr)] gap-4 lg:grid-cols-2">
        <YourFarms farms={farms} latest={latest} analyses={analyses} selectedId={selected.id} onSelect={select} />
        <FarmProfileCard farm={selected} />
      </div>
    </div>
  );
}
