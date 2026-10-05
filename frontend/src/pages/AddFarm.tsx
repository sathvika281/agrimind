import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError } from "../api";
import { useFarms } from "../FarmContext";
import { ErrorBox, Page } from "../components";
import { useLang } from "../LanguageContext";

export default function AddFarm() {
  const nav = useNavigate();
  const { t } = useLang();
  const f = t.addFarm;
  const { reload, select } = useFarms();
  const [name, setName] = useState("");
  const [location, setLocation] = useState("");
  const [soil, setSoil] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    setError(null);
    if (!name.trim()) return setError(f.needName);
    setBusy(true);
    try {
      // The values are stored exactly as typed (never translated); only the labels are translated.
      const farm = await api.createFarm({ name, location, soil_type: soil });
      await reload();
      select(farm.id); // the farm just added becomes the current farm
      nav("/", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : f.couldNotSave);
      setBusy(false);
    }
  }

  return (
    <Page title={f.title} back="/">
      <form onSubmit={submit} className="card space-y-4" noValidate>
        <ErrorBox message={error} />
        <div>
          <label htmlFor="name" className="label">{f.name}</label>
          <input id="name" className="input" placeholder={f.namePh} value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div>
          <label htmlFor="location" className="label">{f.village}</label>
          <input id="location" className="input" placeholder={f.villagePh} value={location} onChange={(e) => setLocation(e.target.value)} />
          <p className="hint">{f.villageHint}</p>
        </div>
        <div>
          <label htmlFor="soil" className="label">{f.soil}</label>
          <input id="soil" className="input" placeholder={f.soilPh} value={soil} onChange={(e) => setSoil(e.target.value)} />
        </div>
        <button className="btn-primary" disabled={busy}>{busy ? f.saving : f.save}</button>
      </form>
    </Page>
  );
}
