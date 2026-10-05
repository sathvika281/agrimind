// Deterministic "read the result aloud" text. Pure (no DOM, no network, no AI call).
// Uses ONLY farmer-facing fields of the existing structured result, plus words from the dictionary of the
// language the result was written in. It never speaks keys, enum names or internal metadata.
import type { AnalysisResult } from "../api";
import { dictFor, type Lang } from "../i18n";

export const MAX_SPOKEN_CHARS = 900; // browsers cut off very long utterances; keep it short and useful

const clean = (s: unknown): string => (typeof s === "string" ? s.replace(/\s+/g, " ").trim() : "");
const sentence = (s: string): string => (/[.!?।…]$/.test(s) ? s : `${s}.`);
const nonEmpty = (xs: unknown): string[] => (Array.isArray(xs) ? xs.map(clean).filter(Boolean) : []);

/** "Possible leaf spot (fungal)" -> "Possible leaf spot, fungal": parentheses read badly aloud. */
const speakable = (s: string): string => s.replace(/\s*\(([^)]*)\)/g, ", $1").replace(/\s+,/g, ",");

export function buildSpeechText(result: AnalysisResult, lang: Lang): string {
  const t = dictFor(lang);
  const sp = t.speech;

  // Sections in priority order. Later ones are dropped first if the text would be too long.
  const sections: string[] = [];

  const issue = clean(result.likely_issue);
  if (issue) sections.push(`${sp.bestGuess} ${sentence(speakable(issue))}`);

  // Honest tone: say how sure we are, using the dictionary sentence for the level (never the raw value).
  const level = result.uncertainty_level;
  const certainty = level ? (t.uncertainty as Record<string, string>)[level] : undefined;
  if (certainty) sections.push(certainty);

  // Older (Phase 1/2) results have no immediate_actions: fall back to recommended_actions.
  const now = nonEmpty(result.immediate_actions);
  const doNow = (now.length ? now : nonEmpty(result.recommended_actions)).slice(0, 3);
  if (doNow.length) sections.push(`${sp.doNow} ${doNow.map(sentence).join(" ")}`);

  const watch = nonEmpty(result.monitoring_steps).slice(0, 2);
  if (watch.length) sections.push(`${sp.watch} ${watch.map(sentence).join(" ")}`);

  const help = clean(result.when_to_seek_help);
  if (help) sections.push(`${sp.help} ${sentence(help)}`);

  const precaution = nonEmpty(result.precautions)[0];
  if (precaution) sections.push(`${sp.precaution} ${sentence(precaution)}`);

  // Keep the issue and the actions; drop the least important sections from the end until it fits.
  const keepAtLeast = sections.length >= 3 ? 3 : sections.length;
  let text = sections.join(" ");
  const parts = [...sections];
  while (text.length > MAX_SPOKEN_CHARS && parts.length > keepAtLeast) {
    parts.pop();
    text = parts.join(" ");
  }
  if (text.length > MAX_SPOKEN_CHARS) {
    const cut = text.slice(0, MAX_SPOKEN_CHARS);
    const end = Math.max(cut.lastIndexOf(". "), cut.lastIndexOf("। "), cut.lastIndexOf("? "));
    text = end > 200 ? cut.slice(0, end + 1) : cut;
  }
  return text.trim();
}
