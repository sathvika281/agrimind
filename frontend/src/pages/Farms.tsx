import { Link, useNavigate } from "react-router-dom";
import { useFarms } from "../FarmContext";
import { EmptyState, ErrorBox, Page, Spinner } from "../components";
import { useLang } from "../LanguageContext";

export default function Farms() {
  const { t } = useLang();
  const nav = useNavigate();
  const { farms, selected, select, error } = useFarms();
  if (error) return <ErrorBox message={error} />;
  if (!farms) return <Spinner />;

  return (
    <Page title={t.farms.title} back="/">
      {farms.length === 0 ? (
        <EmptyState title={t.dash.noFarm} action={<Link to="/farms/new" className="btn-hero">{t.dash.addFarm}</Link>} />
      ) : (
        <>
          <p className="mb-3 text-base text-gray-700">{t.farms.choose}</p>
          <ul className="space-y-3">
            {farms.map((f) => {
              const active = selected?.id === f.id;
              const details = [f.location, f.soil_type && `${t.dash.soil}: ${f.soil_type}`].filter(Boolean).join(" · ");
              return (
                <li key={f.id} className={`card ${active ? "border-2 border-leaf-600" : ""}`}>
                  <p className="text-xl font-bold">{f.name}</p>
                  {details && <p className="text-base text-gray-700">{details}</p>}
                  <button type="button" className="btn-secondary mt-3" data-testid={`farm-profile-${f.id}`} onClick={() => { select(f.id); nav("/profile"); }} aria-label={`${t.prof.editLink}: ${f.name}`}>
                    {t.prof.editLink}
                  </button>
                  {active ? (
                    <p className="mt-2 text-base font-semibold text-leaf-700"><span aria-hidden>✔ </span>{t.farms.current}</p>
                  ) : (
                    <button type="button" className="btn-secondary mt-3" onClick={() => select(f.id)} aria-label={t.farms.useAria(f.name)}>
                      {t.farms.use}
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
          <Link to="/farms/new" className="btn-secondary mt-4">{t.dash.addAnother}</Link>
        </>
      )}
    </Page>
  );
}
