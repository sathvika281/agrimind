// Economics wording tests (en + te): same shape, no placeholders, Telugu is Telugu, and nothing promises profit or invents a forecast. Run: npm run test:economics
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

const strings = (d) => {
  const o = [];
  const walk = (v, p) => {
    if (typeof v === "string") o.push([p, v]);
    else if (typeof v === "function") o.push([p, String(v.length >= 2 ? v("Near market", 3) : v("acre"))]);
    else if (v && typeof v === "object") for (const [k, x] of Object.entries(v)) walk(x, p + "." + k);
  };
  walk(d.ec, "ec");
  walk(d.nav.econ, "nav.econ");
  walk(d.layer.decide, "layer.decide");
  return o;
};
const keys = (o, p = "") => Object.entries(o).flatMap(([k, v]) => (v && typeof v === "object" ? keys(v, p + k + ".") : [p + k]));

test("en and te have the same keys everywhere in ec", () => assert.deepEqual(keys(en.ec).sort(), keys(te.ec).sort()));

test("no string is empty and none has a placeholder leak (en + te)", () => {
  for (const d of [en, te]) for (const [p, s] of strings(d)) {
    assert.ok(s.trim().length > 0, `${d.locale} ${p} empty`);
    assert.ok(!/undefined|NaN|\[object|TODO/.test(s), `${d.locale} ${p}: ${s}`);
  }
});

test("Telugu texts contain Telugu script (ignoring numbers, symbols and unit marks)", () => {
  for (const [p, s] of strings(te)) {
    if (/^ec\.(sourceTag\.demo|pct)$/.test(p)) continue; // pct is a pure number formatter
    assert.ok(TE.test(s), `te ${p} has no Telugu: ${s}`);
  }
});

test("nothing promises profit, certainty or a forecast (en)", () => {
  for (const [p, s] of strings(en)) {
    const t = s.replace(/not a promise|not guaranteed|no price-forecast data|Not a promise/gi, "").replace(/unavailable: there is no price-forecast data/gi, "");
    assert.ok(!/\b(guarantee[sd]?|will earn|sure profit|definitely|certain(ly)?|always profit|forecast(ed)? price)\b/i.test(t), `${p}: ${s}`);
  }
  assert.match(en.ec.disclaimer, /not guaranteed/i);
  assert.match(en.ec.limits.estimate_not_promise, /not a promise/i);
});

test("every code the server's agent can emit has text (confidence reasons, notes, limits, steps, missing, drivers)", () => {
  for (const d of [en, te]) {
    for (const k of ["yield_farmer_estimate", "market_fresh", "market_stale", "inputs_missing", "costs_incomplete", "transport_unknown", "demo_data"]) assert.ok(d.ec.reason[k], `${d.locale} reason ${k}`);
    for (const k of ["trend_increasing", "trend_decreasing", "trend_stable", "trend_insufficient", "harvest_from_planting_date", "planting_from_diary", "crop_check_high_severity", "no_market_data"]) assert.ok(d.ec.notes[k], `${d.locale} note ${k}`);
    for (const k of ["estimate_not_promise", "actual_may_differ"]) assert.ok(d.ec.limits[k], `${d.locale} limit ${k}`);
    for (const k of ["economic_input", "production_calculation", "cost_calculation", "market_data", "market_analysis", "scenario_calculation", "economics_agent", "economic_result"]) assert.ok(d.ec.stepName[k], `${d.locale} step ${k}`);
    for (const k of ["area", "yield", "marketable", "costs", "market_price", "harvest_timing"]) assert.ok(d.ec.missing[k], `${d.locale} missing ${k}`);
    for (const k of ["price", "yield", "cost"]) assert.ok(d.ec.driverName[k], `${d.locale} driver ${k}`);
    for (const k of ["margin_positive", "margin_uncertain", "margin_negative", "insufficient"]) assert.ok(d.ec.outlookLine[k], `${d.locale} outlook ${k}`);
    for (const k of ["seeds", "seedlings", "fertilizer", "labour", "irrigation", "machinery", "land_preparation", "harvesting", "transport", "storage", "other"]) assert.ok(d.ec.cat[k], `${d.locale} cost ${k}`);
    for (const k of ["fresh", "stale", "too_old", "no_price"]) assert.ok(d.ec.freshness[k], `${d.locale} freshness ${k}`);
    for (const k of ["increasing", "decreasing", "stable", "insufficient_data"]) assert.ok(d.ec.trendWord[k], `${d.locale} trend ${k}`);
  }
});

test("the demo label is explicit and the economics nav name exists in both languages", () => {
  assert.match(en.ec.demoBanner, /DEMO DATA/);
  assert.match(en.ec.demoBanner, /not live prices/);
  assert.equal(en.nav.econ, "Economics");
  assert.ok(TE.test(te.nav.econ));
});

console.log(`${passed} passed`);
