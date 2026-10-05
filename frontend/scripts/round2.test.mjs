// Wording tests for the clarity / refine / follow-up / diary / weather-hint text (en + te). No browser, no model.
// Run: npm run test:round2
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
const render = (k, v) => (typeof v === "function" ? v("12", "34", "56") : v);
const all = (d) => JSON.stringify([d.rf, d.dy, d.wr], render);

test("no dose / product / spraying instruction, no guarantee and no causal claim in the new text (en + te)", () => {
  for (const d of [en, te]) {
    const t = all(d).toLowerCase();
    assert.ok(!/\b(apply|dosage|dose|ml per|litres?|fungicide|pesticide|insecticide|guarantee|guaranteed|will cure|caused by|because of your)\b/.test(t), d.locale);
  }
});

test("weather hints are worded as possibilities and a general guide, never as a prediction or a cause", () => {
  for (const d of [en, te]) {
    for (const k of ["humid_wet", "heavy_rain", "hot_dry", "extreme_heat"]) {
      const s = d.wr[k]("12", "34");
      assert.ok(s.includes("12") || s.includes("34"), `${d.locale} ${k}: shows the real numbers`);
      assert.ok(!/undefined|NaN|\[object/.test(s));
    }
    assert.ok(d.wr.note.length > 10 && d.wr.title.length > 5);
  }
  assert.match(en.wr.humid_wet("90", "12"), /may favour/);
  assert.match(en.wr.note, /not a prediction/);
});

test("the diary note explanation says the note is never sent to the AI (en + te)", () => {
  assert.match(en.dy.noteHelp, /never your note/);
  assert.ok(/[ఀ-౿]/.test(te.dy.noteHelp) && te.dy.noteHelp.includes("AI"));
});

test("every diary kind, change status and confidence word exists in both languages and is non-empty", () => {
  for (const d of [en, te]) {
    for (const k of ["sowed", "irrigated", "fertilised", "sprayed", "weeded", "harvested", "other"]) assert.ok(d.dy.kinds[k].length > 1, `${d.locale} ${k}`);
    for (const k of ["better", "same", "worse", "unclear"]) assert.ok(d.rf.change[k].length > 1, `${d.locale} ${k}`);
    for (const k of ["low", "some", "high"]) assert.ok(d.rf.confidence[k].length > 1, `${d.locale} ${k}`);
  }
});

test("Telugu strings are Telugu and templates fill without undefined", () => {
  for (const f of [te.rf.refinedFrom("4 Oct"), te.rf.followupBanner("4 Oct"), te.rf.compareTitle("4 Oct"), te.dy.removeAria("x", "y"), te.wr.humid_wet("90", "12"), te.wr.heavy_rain("45"), te.wr.hot_dry("36"), te.wr.extreme_heat("41")]) {
    assert.ok(/[ఀ-౿]/.test(f) && !/undefined|NaN/.test(f), f);
  }
});

test("the comparison never claims more than 'unclear' allows: four fixed words only", () => {
  assert.deepEqual(Object.keys(en.rf.change).sort(), ["better", "same", "unclear", "worse"]);
  assert.deepEqual(Object.keys(te.rf.change).sort(), ["better", "same", "unclear", "worse"]);
});

console.log(`\n${passed} passed${process.exitCode ? ", SOME FAILED" : ""}`);
