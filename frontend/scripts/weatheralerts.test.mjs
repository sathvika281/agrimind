// Smart weather alert wording (en + te): same shape, no placeholders, Telugu is Telugu, calm (no alarm words, no agronomic claims). Run: npm run test:weatheralerts
import assert from "node:assert/strict";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { buildSync } from "esbuild";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = buildSync({ stdin: { contents: `export { en } from "./src/i18n/en"; export { te } from "./src/i18n/te";`, resolveDir: root, loader: "ts" }, bundle: true, format: "esm", platform: "node", write: false });
const { en, te } = await import("data:text/javascript;base64," + Buffer.from(out.outputFiles[0].text).toString("base64"));
let passed = 0;
const test = (name, fn) => { try { fn(); passed++; console.log("PASS", name); } catch (e) { console.log("FAIL", name, "\n   ", e.message); process.exitCode = 1; } };
const TE = /[ఀ-౿]/;
const keys = (o, p = "") => Object.entries(o).flatMap(([k, v]) => (v && typeof v === "object" ? keys(v, p + k + ".") : [p + k]));
const strings = (d) => {
  const o = [];
  const walk = (v, p) => {
    if (typeof v === "string") o.push([p, v]);
    else if (typeof v === "function") o.push([p, String(v.length >= 3 ? v("1", "2", "3") : v.length === 2 ? v(true, 3) : v("5"))]);
    else if (v && typeof v === "object") for (const [k, x] of Object.entries(v)) walk(x, p + "." + k);
  };
  walk(d.wa, "wa");
  return o;
};

test("en and te have the same keys", () => assert.deepEqual(keys(en.wa).sort(), keys(te.wa).sort()));
test("no empty string and no placeholder leak (en + te)", () => {
  for (const d of [en, te]) for (const [p, s] of strings(d)) {
    assert.ok(s.trim().length > 0, `${d.locale} ${p} empty`);
    assert.ok(!/undefined|NaN|\[object|TODO/.test(s), `${d.locale} ${p}: ${s}`);
  }
});
test("Telugu texts contain Telugu script (provider names excepted)", () => {
  for (const [p, s] of strings(te)) { if (/^wa\.src\./.test(p) || /^wa\.stepNote\.(openweather)$/.test(p)) continue; assert.ok(TE.test(s), `te ${p}: ${s}`); }
});
test("every alert type, severity, value, step and note the server can send has text", () => {
  for (const d of [en, te]) {
    for (const k of ["heavy_rain", "thunderstorm", "strong_wind", "high_temperature", "low_temperature", "temperature_change"]) { assert.ok(d.wa.kind[k], `${d.locale} kind ${k}`); assert.ok(d.wa.matters[k], `${d.locale} matters ${k}`); assert.ok(d.wa.value[k], `${d.locale} value ${k}`); }
    for (const k of ["info", "watch", "important", "severe"]) assert.ok(d.wa.severity[k], `${d.locale} severity ${k}`);
    for (const k of ["weather_context", "forecast", "evaluate", "reconcile", "plan_check"]) assert.ok(d.wa.stepName[k], `${d.locale} step ${k}`);
    for (const k of ["location_resolved", "no_location", "openweather", "open-meteo", "unavailable", "no_plan", "forecast_unavailable", "forecast_stale", "forecast_no_location"]) assert.ok(d.wa.stepNote[k], `${d.locale} note ${k}`);
  }
});
test("calm wording: no alarm words and no claim about crop damage (en)", () => {
  for (const [p, s] of strings(en)) assert.ok(!/\b(danger|dangerous|emergency|disaster|destroy\w*|will (damage|ruin|kill)|crop loss|guarantee\w*)\b/i.test(s), `${p}: ${s}`);
  assert.match(en.wa.sub, /not what it will do to your crop/);
  assert.match(en.wa.planNote, /Farm plan decides what changes/);
});
test("empty state is calm and the freshness texts never claim currency they do not have", () => {
  assert.equal(en.wa.none, "No important weather events detected for your farm.");
  assert.match(en.wa.fresh.stale("5 h ago"), /may be outdated/);
  assert.match(en.wa.fresh.unavailable, /unavailable/);
  assert.equal(en.wa.ago(0), "just now");
});
console.log(`${passed} passed`);
