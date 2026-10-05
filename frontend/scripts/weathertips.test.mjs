// Wording tests for the weather tips (en + te). No browser, no model. Run: npm run test:weathertips
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
const TIP_KINDS = ["irrigate_cool_hours", "shade_seedlings", "avoid_midday_work", "mulch", "check_soil_before_irrigating", "clear_drains", "avoid_wet_field_work", "harvest_before_rain", "store_dry",
  "support_tall_plants", "water_at_base_morning", "keep_airflow", "remove_affected_leaves", "scout_often", "stake_and_tie", "shelter_seedlings", "cover_seedlings", "plan_irrigation", "regular_checks"];
const COND_KINDS = ["extreme_heat", "heavy_rain", "humid_wet", "hot_dry", "strong_wind", "cold_night", "dry_spell"];
const strings = (d) => [d.wt.title, d.wt.note, d.wt.conditionsTitle, d.wt.normal, d.wt.notAvailable, ...Object.values(d.wt.groups), ...Object.values(d.wt.tips), ...COND_KINDS.map((k) => d.wt.cond[k](42.5))];

test("every tip, condition and group the server can send has English and Telugu text", () => {
  for (const d of [en, te]) {
    for (const k of TIP_KINDS) assert.ok(d.wt.tips[k]?.length > 10, `${d.locale} tip ${k}`);
    for (const k of COND_KINDS) assert.ok(String(d.wt.cond[k](42.5)).includes("42.5"), `${d.locale} cond ${k} shows the real number`);
    for (const g of ["protect", "water", "watch"]) assert.ok(d.wt.groups[g]?.length > 3, `${d.locale} group ${g}`);
  }
  assert.deepEqual(Object.keys(te.wt.tips).sort(), Object.keys(en.wt.tips).sort());
});

test("Telugu strings are Telugu and have no placeholders", () => {
  for (const s of strings(te)) { assert.ok(TE.test(s), s); assert.ok(!/undefined|NaN|\[object|TODO/.test(s), s); }
});

test("tips are non-chemical: no pesticide, fungicide, product, dose or spray advice (en + te)", () => {
  for (const d of [en, te]) for (const raw of strings(d)) {
    const s = raw.replace(/non-chemical/gi, '').replace(/రసాయనరహిత/g, '');  // the disclaimer itself says what the tips are not
    assert.ok(!/\b(spray\w*|fungicide|pesticide|insecticide|herbicide|chemical|dose|dosage|mancozeb|neem|fertili[sz]er)\b|పిచికారీ|మందు|రసాయన(?!రహిత)/i.test(s), `${d.locale}: ${s}`);
    assert.ok(!/\d\s*(ml|g|kg|litre|liter)\b/i.test(s), s);
  }
});

test("no certainty or prediction claims; the note says they are rules of thumb", () => {
  for (const s of strings(en)) assert.ok(!/\b(will|guarantee|definitely|certainly|always)\b/i.test(s), s);
  assert.match(en.wt.note, /rules of thumb, not a prediction/);
  assert.match(en.wt.note, /non-chemical/);
});

console.log(`${passed} passed`);
