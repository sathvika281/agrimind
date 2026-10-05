// Wording tests for the investigation features (dossier, hypotheses, before-vs-now, journey, patterns), en + te.
// No browser, no model. Run: npm run test:dossier
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
const TE = /[ఀ-౿]/;
// render every string AND call every function with sample numbers / words, so wording of generated sentences is checked too
const flat = (d) => {
  const o = [];
  const walk = (v) => {
    if (typeof v === "string") o.push(v);
    else if (typeof v === "function") {
      const n = v.length;  // call with arguments that match the signature, so generated sentences are real
      if (n <= 1) o.push(String(v(3)));
      else if (n === 2) { o.push(String(v(3, 6))); o.push(String(v(3, true))); }
      else o.push(String(v("humid, wet", 3, 4)));
    }
    else if (Array.isArray(v)) v.forEach(walk);
    else if (v && typeof v === "object") Object.values(v).forEach(walk);
  };
  [d.dz, d.hy, d.bn, d.jn, d.fp].forEach(walk);
  return o;
};

test("every key of the new sections exists in English and Telugu (shape parity)", () => {
  const keys = (v, p = "") => (v && typeof v === "object" && !Array.isArray(v) ? Object.entries(v).flatMap(([k, x]) => keys(x, `${p}.${k}`)) : [p]);
  for (const sec of ["dz", "hy", "bn", "jn", "fp"]) assert.deepEqual(keys(te[sec]).sort(), keys(en[sec]).sort(), sec);
});

test("Telugu strings contain Telugu and no placeholders / undefined", () => {
  for (const s of flat(te)) { assert.ok(!/undefined|NaN|\[object|TODO/.test(s), s); }
  for (const sec of ["dz", "hy", "bn", "fp"]) {
    for (const [k, v] of Object.entries(te[sec])) if (typeof v === "string") assert.ok(TE.test(v), `${sec}.${k}: ${v}`);
  }
});

test("no percentages, scores, predictions or certainty claims anywhere (en + te)", () => {
  for (const d of [en, te]) for (const raw of flat(d)) {
    const s = raw.replace(/not a prediction/gi, "");  // the disclaimer itself may name what it is not
    assert.ok(!/%|\bscore\b|\bpredict|\bforecast\b|\bwill (cause|fail|spread)|\bdefinitely|\bguarantee|\bcertainly/i.test(s), `${d.locale}: ${s}`);
  }
});

test("explanations are possibilities, not a diagnosis; patterns are relationships, not causes", () => {
  assert.match(en.hy.note, /not a diagnosis/);
  assert.match(en.hy.note, /not enough to confirm/);
  assert.match(en.fp.caution, /do not show that one thing caused another/);
  const all = flat(en).join(" ").toLowerCase();
  const mentionsDiagnosis = all.match(/diagnos\w*/g) ?? [];
  assert.ok(mentionsDiagnosis.length <= 1, "'diagnosis' only appears in the 'not a diagnosis' disclaimer");
  assert.match(en.fp.env("humid, wet", 3, 4), /alongside/);
  assert.match(en.dz.why.weather_consistent(), /consistent with/);
  assert.match(en.dz.why.weather_consistent(), /does not prove a cause/i);
});

test("directions and labels cover every backend value", () => {
  for (const d of [en, te]) {
    for (const k of ["improving", "worsening", "stable", "mixed", "unclear"]) assert.ok(d.bn.direction[k]?.length > 3, `${d.locale} direction ${k}`);
    for (const k of ["same", "different", "unclear"]) assert.ok(d.bn.issue[k]?.length > 3, `${d.locale} issue ${k}`);
    for (const k of ["strong", "possible", "limited"]) assert.ok(d.fp.label[k]?.length > 3, `${d.locale} label ${k}`);
    for (const k of ["current_observation", "history_match", "weather_consistent", "guidance_describes"]) assert.ok(d.hy.sup[k], `${d.locale} sup ${k}`);
    for (const k of ["no_history_match", "weather_less_likely", "no_guidance_match", "image_limited"]) assert.ok(d.hy.gap[k], `${d.locale} gap ${k}`);
    for (const k of ["observation", "history", "weather", "knowledge", "farm_context", "diary"]) assert.ok(d.dz.ev[k], `${d.locale} ev ${k}`);
    for (const k of ["humid_wet", "heavy_rain", "hot_dry", "extreme_heat"]) assert.ok(d.fp.cond[k], `${d.locale} cond ${k}`);
  }
});

console.log(`${passed} passed`);
