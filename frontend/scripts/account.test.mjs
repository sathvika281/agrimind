// Wording tests for the Account and Privacy text (en + te). No browser, no model.
// Run: npm run test:account
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
const render = (k, v) => (typeof v === "function" ? v("a@b.co") : v);

test("privacy sections match between en and te and have text", () => {
  assert.equal(en.pv.sections.length, te.pv.sections.length);
  for (const d of [en, te]) for (const s of d.pv.sections) { assert.ok(s.h.length > 2 && s.p.length >= 1); for (const x of s.p) assert.ok(x.length > 10); }
});

test("account keys all non-empty in en and te, no placeholders", () => {
  for (const d of [en, te]) {
    for (const [k, v] of Object.entries(d.ac)) { const s = String(render(k, v)); assert.ok(s.length > 1, `${d.locale} ac.${k}`); assert.ok(!/undefined|NaN|\[object|TODO/.test(s)); }
    assert.ok(String(d.pv.contact("a@b.co")).includes("a@b.co"));
  }
});

test("privacy never claims more than the app does (no legal guarantees, no selling, no analytics claims beyond 'none')", () => {
  const t = JSON.stringify(en.pv, render).toLowerCase();
  assert.ok(!/\b(gdpr|hipaa|certified|compliant|100% secure|guarantee|encrypted at rest|anonymi[sz]ed)\b/.test(t));
  assert.match(t, /does not sell/);
  assert.match(t, /not legal advice/);
  assert.match(t, /gemini/);
  assert.match(t, /open-meteo/);
  assert.match(t, /never sent/);
});

test("delete warning says it is permanent / removes data (en)", () => {
  assert.match(en.ac.deleteWarn.toLowerCase(), /permanent|cannot be undone|can't be undone/);
});

console.log(`${passed} passed`);
