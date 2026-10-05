// Deterministic answers to the history questions. Built ONLY from the insights the server derived from this farm's
// stored checks: no model call, no sample telemetry, nothing guessed. Pure (no React) so it can be tested in node.
import type { Dict } from "../i18n/en";
import type { Farm, InsightEvidence, Insights, InsightTrend } from "../api";

export type QuestionId = "recent" | "recurring" | "changed" | "often" | "attention";
export const QUESTIONS: QuestionId[] = ["recent", "recurring", "changed", "often", "attention"];
/** Questions about what the FARMER recorded (profile) rather than what the checks showed. */
export type ProfileQuestionId = "profile" | "cropIssues";
export const PROFILE_QUESTIONS: ProfileQuestionId[] = ["profile", "cropIssues"];

/** Farmer-entered values shown as "Label: value" (only those actually provided), or null when nothing was provided. */
export function recordedItems(P: Dict["prof"], farm: Farm, fmtLong: DateFmt): { label: string; value: string }[] {
  const items: { label: string; value: string }[] = [];
  if (farm.primary_crop) items.push({ label: P.crop, value: farm.primary_crop });
  if (farm.irrigation_method) items.push({ label: P.irrigation, value: P.irrigationOpts[farm.irrigation_method] ?? farm.irrigation_method });
  if (farm.season) items.push({ label: P.season, value: P.seasonOpts[farm.season] ?? farm.season });
  if (farm.planting_date) items.push({ label: P.planting, value: fmtLong(farm.planting_date) });
  if (farm.soil_type) items.push({ label: P.soil, value: farm.soil_type });
  if (farm.location) items.push({ label: P.village, value: farm.location });
  return items;
}

/** The two profile questions. Deterministic, from the farmer's own entries and the stored checks only. */
export function profileAnswer(I: Ins, P: Dict["prof"], d: Insights | null, farm: Farm, q: ProfileQuestionId, fmt: DateFmt, fmtLong: DateFmt): Answer {
  if (q === "profile") {
    const items = recordedItems(P, farm, fmtLong);
    if (!items.length) return { lines: [I.ans.profileMissing], evidence: [], insufficient: true };
    return { lines: [I.ans.profileIntro, ...items.map((i) => I.ans.profileItem(i.label, i.value))], evidence: [], insufficient: false };
  }
  const crop = farm.primary_crop?.trim();
  if (!crop) return { lines: [I.ans.cropNoCrop], evidence: [], insufficient: true };
  // recent checks whose crop matches what the farmer recorded (case-insensitive); nothing else is assumed
  const rows = (d?.recent ?? []).filter((c) => c.crop.trim().toLowerCase() === crop.toLowerCase());
  if (!rows.length) return { lines: [I.ans.cropNoChecks(crop)], evidence: [], insufficient: true };
  return {
    lines: [I.ans.cropIntro(crop), ...rows.slice(0, 5).map((c) => (c.issue ? I.ans.recentItem(fmt(c.at), c.crop, c.issue) : `${fmt(c.at)} · ${c.crop}: ${I.ans.recentUnclear}`))],
    evidence: rows.slice(0, 5).map((c) => ({ analysis_id: c.analysis_id, at: c.at })),
    insufficient: false,
  };
}

export interface Answer {
  lines: string[];
  /** The stored checks the answer rests on (the farmer can open each one). Empty when the answer is "not enough history". */
  evidence: InsightEvidence[];
  /** True when the answer is "AgriMind can't tell yet" (shown as uncertainty, not as a finding). */
  insufficient: boolean;
}

type Ins = Dict["ins"];
export type DateFmt = (iso: string) => string;

/** The sentence that says why there isn't enough history (or null when there is at least `min` checks). */
function notEnough(I: Ins, d: Insights, min: 2 | 4): string | null {
  if (d.total === 0) return I.ans.noChecks;
  if (d.total === 1) return I.ans.oneCheck;
  if (d.total < min) return I.ans.fewChecks(d.total);
  return null;
}

export function trendObservation(I: Ins, t: InsightTrend): string {
  switch (t.kind) {
    case "recurring":
      return I.obs.recurring(t.issue, t.count, t.window);
    case "more_frequent":
      return I.obs.more_frequent(t.issue, t.count, t.earlier_count ?? 0);
    case "less_frequent":
      return I.obs.less_frequent(t.issue, t.count, t.earlier_count ?? 0);
    case "repeated_high":
      return I.obs.repeated_high(t.issue, t.count, t.window);
    case "stable":
      return I.obs.stable(t.issue);
  }
}

const uniq = (ev: InsightEvidence[]) => [...new Map(ev.map((e) => [e.analysis_id, e])).values()];

export function answer(I: Ins, d: Insights, q: QuestionId, fmt: DateFmt): Answer {
  const none = (line: string): Answer => ({ lines: [line], evidence: [], insufficient: true });
  switch (q) {
    case "recent": {
      if (d.total === 0) return none(I.ans.noChecks);
      const shown = d.recent.slice(0, 3);
      const lines = [I.ans.recentIntro, ...shown.map((c) => (c.issue ? I.ans.recentItem(fmt(c.at), c.crop, c.issue) : `${fmt(c.at)} · ${c.crop}: ${I.ans.recentUnclear}`))];
      return { lines, evidence: shown.map((c) => ({ analysis_id: c.analysis_id, at: c.at })), insufficient: false };
    }
    case "recurring": {
      const why = notEnough(I, d, 4);
      if (why) return none(why);
      const rec = d.trends.filter((t) => t.kind === "recurring");
      if (!rec.length) return { lines: [I.ans.noRecurring], evidence: [], insufficient: false };
      return { lines: rec.map((t) => trendObservation(I, t)), evidence: uniq(rec.flatMap((t) => t.evidence)), insufficient: false };
    }
    case "changed": {
      const c = d.comparison;
      if (!c) return none(I.cmpNeedTwo);
      const a = fmt(c.previous.at);
      const b = fmt(c.latest.at);
      const lines: string[] = [];
      if (!c.comparable) lines.push(I.cmpNotComparable);
      else if (c.same_issue) lines.push(I.cmpSame(a, b));
      else lines.push(I.cmpDiff(a, b, c.previous.issue, c.latest.issue));
      const from = I.sev[c.previous.severity];
      const to = I.sev[c.latest.severity];
      if (c.previous.severity === "unknown" && c.latest.severity === "unknown") lines.push(I.sev.unknown);
      else lines.push(c.severity_changed ? I.cmpSevChanged(from, to) : I.cmpSevSame(to));
      return { lines, evidence: [c.previous, c.latest].map((x) => ({ analysis_id: x.analysis_id, at: x.at })), insufficient: false };
    }
    case "often": {
      const why = notEnough(I, d, 2);
      if (why) return none(why);
      const top = d.issues[0];
      if (!top || top.count < 2) return { lines: [I.ans.noRepeat], evidence: [], insufficient: false };
      return { lines: [I.ans.oftenLine(top.label, top.count, d.total)], evidence: top.evidence, insufficient: false };
    }
    case "attention": {
      const lines: string[] = [];
      let evidence: InsightEvidence[] = [];
      if (d.total === 0) return none(I.ans.noChecks);
      for (const t of d.trends) {
        lines.push(trendObservation(I, t), `${I.reco[t.kind]}`);
        evidence = evidence.concat(t.evidence);
      }
      const l = d.latest;
      if (l && (l.severity === "high" || l.severity === "medium")) {
        lines.push(I.ans.attentionLatest(fmt(l.at), I.sev[l.severity], l.issue));
        evidence.push({ analysis_id: l.analysis_id, at: l.at });
      }
      if (!lines.length) return { lines: [I.ans.attentionNothing, I.ans.attentionNext], evidence: [], insufficient: true };
      return { lines, evidence: uniq(evidence), insufficient: false };
    }
  }
}
