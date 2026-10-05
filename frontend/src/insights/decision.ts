// Turns the server's rule-based decision JSON into words (English / Telugu) and Copilot answers. Pure (no React).
// It reads ONLY that JSON: never the model-written advice text. No model call, nothing guessed.
import type { Decision, Farm } from "../api";
import type { Dict } from "../i18n/en";
import type { Answer, DateFmt } from "./answers";

type DS = Dict["ds"];
export type DecisionQuestionId = "next" | "why";
export const DECISION_QUESTIONS: DecisionQuestionId[] = ["next", "why"];

export interface DecisionView {
  state: Decision["state"];
  observed: string;
  /** Up to 3 lines, most decision-relevant first (the full list is in Copilot "Why…"). */
  evidence: string[];
  allEvidence: string[];
  actions: string[];
  expertReason: string | null;
  /** Up to 2 lines; the universal no-treatment limitation is always first. */
  limitations: string[];
  allLimitations: string[];
  contextLine: string | null;
}

const EVIDENCE_MAX = 3;
const ACTIONS_MAX = 2;
const LIMITS_MAX = 2;

export function contextParts(t: { prof: Dict["prof"] }, d: Decision, fmtLong: DateFmt): string[] {
  const P = t.prof;
  const label: Record<string, string> = { primary_crop: P.crop, irrigation_method: P.irrigation, season: P.season, planting_date: P.planting, soil_type: P.soil, location: P.village };
  return d.context.map((c) => {
    const v = c.field === "irrigation_method" ? P.irrigationOpts[c.value] ?? c.value : c.field === "season" ? P.seasonOpts[c.value] ?? c.value : c.field === "planting_date" ? fmtLong(c.value) : c.value;
    return `${label[c.field]}: ${v}`;
  });
}

export function decisionView(ds: DS, P: Dict["prof"], d: Decision, fmt: DateFmt, fmtLong: DateFmt): DecisionView {
  const o = d.observed;
  const observed = !o ? ds.observedNone : !o.crop ? ds.cropMissing : o.unclear ? ds.observedUnclear(o.crop, fmt(o.checked_at)) : ds.observed(o.crop, o.issue, fmt(o.checked_at));
  const all: { key: string; line: string; priority: number }[] = [];
  const sevLabel = (s: string) => ds.sev[s] ?? s;
  for (const e of d.evidence) {
    if (e.kind === "this_check" && o && !o.unclear) all.push({ key: e.kind, priority: 0, line: o.input_type.includes("image") ? ds.evThisPhoto : ds.evThisText });
    else if (e.kind === "severity") all.push({ key: e.kind, priority: 2, line: e.value === "not_recorded" ? ds.evSeverityNone : ds.evSeverity(sevLabel(e.value ?? "")) });
    else if (e.kind === "history_same_issue") all.push({ key: e.kind, priority: 3, line: ds.evHistorySame(e.count ?? 0) });
    else if (e.kind === "history_isolated") all.push({ key: e.kind, priority: 3, line: ds.evHistoryIsolated });
    else if (e.kind === "history_insufficient") all.push({ key: e.kind, priority: 3, line: ds.evHistoryCount(e.count ?? 0) });
    else if (e.kind === "trend" && e.value && ds.trend[e.value]) all.push({ key: e.kind, priority: 1, line: ds.trend[e.value](e.count ?? 0, e.window ?? 0) });
  }
  all.sort((a, b) => a.priority - b.priority);
  const allEvidence = all.map((x) => x.line);
  const actions = d.actions.map((a) => ds.action[a]).filter(Boolean);
  const allLimitations = d.limitations.map((k) => ds.limit[k]).filter(Boolean);
  const parts = contextParts({ prof: P }, d, fmtLong);
  return {
    state: d.state,
    observed,
    evidence: allEvidence.slice(0, EVIDENCE_MAX),
    allEvidence,
    actions: actions.slice(0, ACTIONS_MAX),
    expertReason: d.expert_reason ? ds.expert[d.expert_reason] ?? null : null,
    limitations: allLimitations.slice(0, LIMITS_MAX),
    allLimitations,
    contextLine: parts.length ? ds.contextLine(parts.join(" · ")) : null,
  };
}

const evidenceDates = (d: Decision) => {
  const m = new Map<number, { analysis_id: number; at: string }>();
  for (const e of d.evidence) for (const x of e.dates) m.set(x.analysis_id, x);
  return [...m.values()];
};

/** The two decision questions, answered ONLY from the decision JSON. */
export function decisionAnswer(ds: DS, P: Dict["prof"], d: Decision, q: DecisionQuestionId, fmt: DateFmt, fmtLong: DateFmt): Answer {
  const v = decisionView(ds, P, d, fmt, fmtLong);
  if (q === "next") {
    const lines = [...(v.actions.length ? v.actions : [ds.noneNext]), ...(v.expertReason ? [v.expertReason] : []), v.allLimitations[0]].filter(Boolean) as string[];
    return { lines, evidence: evidenceDates(d), insufficient: d.state === "no_actionable_evidence" };
  }
  const lines = [ds.whyIntro, ...v.allEvidence, ...(v.expertReason ? [v.expertReason] : []), ...(v.contextLine ? [v.contextLine] : []), ...v.allLimitations];
  return { lines, evidence: evidenceDates(d), insufficient: d.state === "no_actionable_evidence" };
}

/** Used by the Insights Copilot: the farmer-visible crop context (kept in sync with the profile answers). */
export function farmHasContext(f: Farm): boolean {
  return !!(f.primary_crop || f.irrigation_method || f.season || f.planting_date || f.soil_type || f.location);
}
