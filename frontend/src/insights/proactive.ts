// Turns the server's proactive JSON into words (English / Telugu) and the Copilot answer. Pure (no React).
// The JSON is the ONLY source: no extra request, no analysis text, no model, nothing guessed.
// Wording stays historical ("latest stored check", "based on stored checks"), never a live-state claim.
import type { Proactive } from "../api";
import type { Dict } from "../i18n/en";
import type { Answer, DateFmt } from "./answers";

type PI = Dict["pi"];
type DS = Dict["ds"];

export interface ProactiveItemView {
  priority: "attention" | "important";
  title: string;
  issue: string;
  /** Up to 2 reasons on the card; all of them are in `allReasons` (Copilot). */
  reasons: string[];
  allReasons: string[];
  meta: string;
  next: string;
  analysisId: number;
}

const REASONS_ON_CARD = 2;
const HEADING_ORDER = ["latest_high", "repeated_high", "recurring", "more_frequent", "unresolved_verify"];

export function proactiveViews(pi: PI, ds: DS, d: Proactive, fmt: DateFmt): ProactiveItemView[] {
  return d.items.map((it) => {
    const allReasons = it.reasons.map((r) => {
      const f = pi.reason[r.kind];
      if (r.kind === "latest_high" || r.kind === "unresolved_verify") return f(fmt(r.dates[0]?.at ?? it.latest_at), "");
      if (r.kind === "more_frequent") return f(String(r.count ?? 0), String(r.earlier_count ?? 0));
      return f(String(r.count ?? 0), String(r.window ?? 0));
    });
    const top = HEADING_ORDER.find((k) => it.reasons.some((r) => r.kind === k)) ?? it.reasons[0].kind;
    return {
      priority: it.priority,
      title: pi.heading[top],
      issue: it.issue,
      reasons: allReasons.slice(0, REASONS_ON_CARD),
      allReasons,
      meta: `${pi.latestCheck(fmt(it.latest_at))} · ${pi.basedOn(it.evidence_count)}`,
      next: ds.action[it.actions[0]] ?? "",
      analysisId: it.analysis_id,
    };
  });
}

/** Copilot "What needs my attention?": the current items, their reasons, and the stored checks they rest on. */
export function proactiveAnswer(pi: PI, ds: DS, d: Proactive, fmt: DateFmt): Answer {
  if (!d.items.length) return { lines: [pi.ans.none], evidence: [], insufficient: false };
  const views = proactiveViews(pi, ds, d, fmt);
  const lines = [pi.ans.intro(views.length)];
  views.forEach((v) => lines.push(pi.ans.item(v.title, v.issue), ...v.allReasons, v.next));
  const seen = new Map<number, { analysis_id: number; at: string }>();
  for (const it of d.items) for (const r of it.reasons) for (const x of r.dates) seen.set(x.analysis_id, x);
  return { lines: lines.filter(Boolean), evidence: [...seen.values()], insufficient: false };
}
