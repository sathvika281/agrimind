import type { ReactNode } from "react";
import type { AnalysisResult } from "../api";
import { useLang } from "../LanguageContext";
import { LayerTag } from "../plan/LayerTag";
import { PlanIcon } from "../plan/icons";
import { Hypotheses } from "./InvestigationExtras";
import { HowChecked, SourcesBlock } from "./ResultExtras";

/** UNDERSTAND: the investigation (real agent steps, evidence, why, unknowns, what would verify it), the competing possibilities and the
 *  sources, together under one question. Nothing here is new data: it re-presents the stored dossier. Shown only when there is something to show. */
export function WhyThisResult({ r, lang, moreDetails }: { r: AnalysisResult; lang: "en" | "te"; moreDetails: ReactNode }) {
  const { t } = useLang();
  const U = t.ur;
  const hasAgentic = (r.agent_steps ?? []).length > 0 || (r.dossier?.hypotheses ?? []).length > 0 || (r.sources ?? []).length > 0;
  if (!hasAgentic && !moreDetails) return null;
  return (
    <details className="panel plan-row" data-testid="why-result">
      <summary className="flex min-h-[3.5rem] cursor-pointer list-none items-center gap-3 px-4 py-3 [&::-webkit-details-marker]:hidden">
        <span aria-hidden className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-leaf-800 text-[#c8f169]"><PlanIcon name="inspect" size={22} /></span>
        <span className="min-w-0 flex-1">
          <LayerTag k="understand" />
          <span className="mt-1 block text-base font-extrabold text-leaf-800">{U.title}</span>
          <span className="block text-xs text-mute">{U.sub}</span>
        </span>
        <span className="plan-chev text-mute"><PlanIcon name="chevron" size={20} /></span>
      </summary>
      <div className="space-y-3 px-4 pb-4">
        <HowChecked r={r} embedded />
        <Hypotheses r={r} lang={lang} embedded />
        <SourcesBlock r={r} embedded />
        {moreDetails}
      </div>
    </details>
  );
}
