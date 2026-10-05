import { Link } from "react-router-dom";
import type { Analysis } from "../api";
import { SeverityBadge } from "../components";
import { friendlyDate, shortIssue } from "../copy";
import { useLang } from "../LanguageContext";

// The Overview now lives in src/overview/Overview.tsx; this file keeps the history-row component.
export { default } from "../overview/Overview";

export function AnalysisRow({ a }: { a: Analysis }) {
  const { t, lang } = useLang();
  const shown = a.translations?.[lang] ?? a.result; // use the version in the UI language when one exists
  return (
    <Link to={`/analyses/${a.id}`} className="card block min-h-[4.5rem] hover:border-leaf-500">
      <div className="text-xl font-bold text-leaf-800">
        {a.crop} — {shortIssue(shown.likely_issue)}
      </div>
      <div className="mt-1 text-base text-mute">{friendlyDate(a.created_at)}</div>
      <div className="mt-2 flex flex-wrap items-center gap-2 text-base text-mute">
        <span>{a.farm_name}</span>
        {a.has_image && <span className="rounded-full bg-leaf-100 px-2 py-0.5 text-sm font-semibold text-leaf-800">{t.history.photoIncluded}</span>}
        <SeverityBadge severity={a.result.severity} />
      </div>
    </Link>
  );
}
