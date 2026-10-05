import { useEffect } from "react";
import { Link } from "react-router-dom";
import { EmptyState, ErrorBox, Page, Spinner } from "../components";
import { useFarms } from "../FarmContext";
import { useLang } from "../LanguageContext";
import { WeatherCard } from "../overview/panels";
import { useStatus } from "../overview/StatusContext";

const STALE_MS = 10 * 60 * 1000;

/** The weather of EVERY farm, each for the place the farmer entered for that farm. */
export default function WeatherPage() {
  const { t } = useLang();
  const { farms, error } = useFarms();
  const { weatherByFarm, loadWeather } = useStatus();

  useEffect(() => {
    if (!farms) return;
    const now = Date.now();
    const need = farms.filter((f) => f.location.trim() && (!weatherByFarm[f.id] || now - weatherByFarm[f.id]!.at > STALE_MS)).map((f) => f.id);
    if (need.length) void loadWeather(need);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [farms]);

  if (error) return <ErrorBox message={error} />;
  if (!farms) return <Spinner />;
  return (
    <Page title={t.shell.nav.weather} back="/">
      {farms.length === 0 ? (
        <EmptyState title={t.dash.noFarm} action={<Link to="/farms/new" className="btn-hero">{t.dash.addFarm}</Link>} />
      ) : (
        <div className="grid grid-cols-[minmax(0,1fr)] items-start gap-4 lg:grid-cols-2" data-testid="weather-page">
          {farms.map((f) => (
            <WeatherCard key={f.id} farm={f} weather={weatherByFarm[f.id]} heading={f.location.trim() ? `${f.location.trim()} · ${f.name}` : f.name} anchor={false} />
          ))}
        </div>
      )}
    </Page>
  );
}
