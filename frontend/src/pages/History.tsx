import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError, type Analysis } from "../api";
import { EmptyState, ErrorBox, Page, Spinner } from "../components";
import { useLang } from "../LanguageContext";
import { AnalysisRow } from "./Dashboard";

export default function History() {
  const { t } = useLang();
  const [items, setItems] = useState<Analysis[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .analyses()
      .then(setItems)
      .catch((e) => setError(e instanceof ApiError ? e.message : t.err.checksLoad));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <Page title={t.history.title} back="/">
      <ErrorBox message={error} />
      {!items && !error && <Spinner />}
      {items && items.length === 0 && (
        <EmptyState title={t.dash.noChecks} action={<Link to="/analyze" className="btn-primary">{t.dash.checkCrop}</Link>} />
      )}
      {items && items.length > 0 && (
        <ul className="space-y-3">
          {items.map((a) => (
            <li key={a.id}><AnalysisRow a={a} /></li>
          ))}
        </ul>
      )}
    </Page>
  );
}
