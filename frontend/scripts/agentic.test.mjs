// Wording tests for the agentic investigation text (en + te). No browser, no model.
// Run: npm run test:agentic
import assert from "node:assert/strict";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { buildSync } from "esbuild";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = buildSync({
  stdin: { contents: `export { en } from "./src/i18n/en"; export { te } from "./src/i18n/te";`, resolveDir: root, loader: "ts" },
  bundle: true, format: "esm", platform: "node", write: false,
});
const { en, te } = await import("data:text/javascript;base64," + Buffer.from(out.outputFiles[0].text).toString("base64"));
let passed = 0;
const test = (name, fn) => { try { fn(); passed++; console.log("PASS", name); } catch (e) { console.log("FAIL", name, "\n   ", e.message); process.exitCode = 1; } };
const AGENTS = ["investigation", "crop_analysis", "farm_memory", "environment", "knowledge", "decision_support", "safety"];

test("every agent, status and note key exists in English and Telugu with real text", () => {
  for (const d of [en, te]) {
    for (const k of AGENTS) assert.ok(d.ag.agents[k]?.length > 3, `${d.locale} agent ${k}`);
    for (const k of ["ok", "skipped", "failed", "retry"]) assert.ok(d.ag.status[k]?.length > 1, `${d.locale} status ${k}`);
    for (const k of ["no_history", "no_weather", "no_knowledge_base", "fallback_to_crop_analysis", "kept_crop_analysis"]) assert.ok(d.ag.notes[k]?.length > 3, `${d.locale} note ${k}`);
    assert.ok(d.ag.checkedTitle.length > 3 && d.ag.sourcesTitle.length > 2 && d.ag.sourcesNote.length > 20);
  }
});

test("Telugu text is Telugu (no English fallbacks left in the new section)", () => {
  const t = JSON.stringify(te.ag);
  assert.ok(/[\u0C00-\u0C7F]/.test(t));
  for (const v of [...Object.values(te.ag.agents), ...Object.values(te.ag.status), ...Object.values(te.ag.notes)]) assert.ok(/[\u0C00-\u0C7F]/.test(v), v);
});

test("the wording makes no diagnosis, certainty or treatment claim", () => {
  const t = JSON.stringify(en.ag).toLowerCase();
  assert.ok(!/\b(diagnos(es|ed|is)? your|cure|guarantee|definitely|spray|dose|fungicide|pesticide)\b/.test(t));
  assert.match(en.ag.sourcesNote, /do not confirm a diagnosis/);
});

console.log(`${passed} passed`);
