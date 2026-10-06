// Wording tests for the Farm plan text (en + te). No browser, no model. Run: npm run test:plan
import assert from "node:assert/strict";
import nodeFs from "node:fs";
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
const ITEM_KINDS = ["inspect_plants", "watch_spread", "recheck_crop", "ask_expert", "add_detail", "monitor_routine", "drain_field", "dry_field", "irrigation_hold", "reassess_after_rain", "irrigation_plan",
  "planting_best", "planting_none", "activity_supported", "activity_heavy_rain", "activity_wet", "activity_hot", "activity_beyond", "activity_nofc", "if_rain_arrives", "if_forecast_changes", "if_heat_arrives", "if_symptoms_spread"];
const ctx = { when: "Tue 7 Oct", rain: 25, temp: 38, activity: "Weeding", hot: true };
const all = (d) => {
  const o = [];
  const walk = (v) => {
    if (typeof v === "string") o.push(v);
    else if (typeof v === "function") { o.push(String(v.length === 0 ? v() : typeof v.length === "number" && /ctx|c\b/.test(v.toString().slice(0, 12)) ? v(ctx) : v.length >= 2 ? v("Tue 7 Oct", 3) : v(3))); }
    else if (v && typeof v === "object") Object.values(v).forEach(walk);
  };
  walk(d.fpl);
  for (const k of ITEM_KINDS) o.push(String(d.fpl.item[k](ctx)));
  o.push(d.fpl.updatedBecause("x"), d.fpl.cropPossible("Possible leaf spot"), d.fpl.rain(12), d.fpl.chance(40), d.fpl.sincePlanting(30), d.fpl.version(2), d.fpl.kept(3), d.fpl.steps(5), d.fpl.sincePlanting(1));
  return o;
};

test("every plan item kind, status, reason and activity the server can send has English and Telugu text", () => {
  for (const d of [en, te]) {
    for (const k of ITEM_KINDS) assert.ok(String(d.fpl.item[k](ctx)).length > 8, `${d.locale} item ${k}`);
    for (const k of ["do_now", "consider", "hold", "info", "reconsider", "supported", "cool_hours", "unassessed"]) assert.ok(d.fpl.status[k]?.length > 2, `${d.locale} status ${k}`);
    for (const k of ["forecast_change", "new_check", "farmer_edit", "first_plan"]) assert.ok(d.fpl.reasons[k]?.length > 5, `${d.locale} reason ${k}`);
    for (const k of ["sowing", "transplanting", "irrigation", "weeding", "harvest", "other"]) assert.ok(d.fpl.act[k]?.length > 2, `${d.locale} act ${k}`);
    for (const k of ["none", "waterlogged", "dry", "pests_seen", "wilting"]) assert.ok(d.fpl.field[k]?.length > 2, `${d.locale} field ${k}`);
    for (const k of ["added", "removed", "changed"]) assert.ok(d.fpl.change[k]?.length > 2, `${d.locale} change ${k}`);
  }
});

test("the banner sentence names the reason and the numbers/dates come through", () => {
  assert.equal(en.fpl.updatedBecause(en.fpl.reasons.forecast_change), "Your plan was updated because the weather forecast changed.");
  assert.match(en.fpl.item.irrigation_hold({ when: "Tue", rain: 25, activity: "" }), /hold irrigation, about 25 mm of rain/);
  assert.match(en.fpl.item.activity_heavy_rain({ when: "Tue", rain: 25, activity: "Weeding" }), /Consider moving it/);
  for (const d of [en, te]) assert.ok(d.fpl.item.irrigation_hold({ when: "D", rain: 25, activity: "" }).includes("25") && d.fpl.item.activity_hot({ when: "D", temp: 38, activity: "A" }).includes("38"));
});

test("Telugu is Telugu and has no placeholders", () => {
  for (const s of all(te)) { assert.ok(!/undefined|NaN|\[object|TODO/.test(s), s); }
  for (const k of ITEM_KINDS) assert.ok(TE.test(te.fpl.item[k](ctx)), `te ${k}`);
  for (const k of ["title", "sub", "noForecast", "changedTitle", "firstPlan", "upToDate", "disclaimer"]) assert.ok(TE.test(te.fpl[k]), k);
});

test("scope: no soil, market, price, profit, chemical, dose or diagnosis words (en + te)", () => {
  for (const d of [en, te]) for (const s of all(d)) {
    assert.ok(!/\b(soil|market|price|profit|spray\w*|fungicide|pesticide|insecticide|chemical|dose|dosage)\b|మట్టి|నేల రకం|మార్కెట్|ధర|లాభం|పిచికారీ|రసాయన/i.test(s.replace(/not a prescription/gi, "")), `${d.locale}: ${s}`);
  }
  assert.match(en.fpl.cropPossible("Possible leaf spot"), /not a confirmed diagnosis/);
});

test("no certainty or guarantee claims; suggestions are worded as consider/check", () => {
  for (const s of all(en)) assert.ok(!/\b(guarantee|definitely|certainly|always|will fail|will cause)\b/i.test(s), s);
  assert.match(en.fpl.item.planting_best(ctx), /Consider it/);
  assert.match(en.fpl.disclaimer, /not a prescription/);
});

test("fpl.short: every item kind has a headline of at most 7 words in en and te", () => {
  for (const d of [en, te]) for (const k of ITEM_KINDS) {
    const h = String(d.fpl.short[k](ctx)).trim();
    assert.ok(h.length > 2, `${d.locale} short ${k}`);
    assert.ok(h.split(/s+/).length <= 7, `${d.locale} short ${k}: ${h}`);
  }
  assert.deepEqual(Object.keys(en.fpl.short).sort(), Object.keys(te.fpl.short).sort());
});

test("fpl.ui: en and te have the same keys, all non-empty, and te is Telugu script", () => {
  const keys = (o, p = "") => Object.entries(o).flatMap(([k, v]) => (v && typeof v === "object" ? keys(v, p + k + ".") : [p + k]));
  assert.deepEqual(keys(en.fpl.ui).sort(), keys(te.fpl.ui).sort());
  for (const d of [en, te]) for (const [k, v] of Object.entries(d.fpl.ui)) {
    const text = typeof v === "function" ? String(v("Tue", 3)) : typeof v === "string" ? v : Object.values(v).join(" ");
    assert.ok(text.length > 0, `${d.locale} ui.${k}`);
  }
  assert.ok(TE.test(te.fpl.ui.why) && TE.test(te.fpl.ui.updated) && TE.test(te.fpl.short.irrigation_hold(ctx)));
});

test("planLogic.ts thresholds equal the planning agent's (agent.py is the source of truth)", () => {
  const fs = nodeFs;
  const py = fs.readFileSync(path.resolve(root, "../backend/app/services/planning/agent.py"), "utf8");
  const ts = fs.readFileSync(path.resolve(root, "src/plan/planLogic.ts"), "utf8");
  for (const n of ["SIGNIFICANT_RAIN_MM", "WET_FIELD_PREV_DAY_MM", "DRY_DAY_MM", "HOT_C"]) {
    const a = py.match(new RegExp(`^${n}\\s*=\\s*([0-9.]+)`, "m"));
    const b = ts.match(new RegExp(`export const ${n}\\s*=\\s*([0-9.]+)`));
    assert.ok(a && b, `${n} found in both`);
    assert.equal(Number(a[1]), Number(b[1]), n);
  }
});

console.log(`${passed} passed`);
