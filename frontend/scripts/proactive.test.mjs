// Tests for the proactive ("Needs your attention") wording and the Copilot answer. No browser, no model.
// Run: npm run test:proactive
import assert from "node:assert/strict";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { buildSync } from "esbuild";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = buildSync({
  stdin: { contents: `export * from "./src/insights/proactive"; export { en } from "./src/i18n/en"; export { te } from "./src/i18n/te";`, resolveDir: root, loader: "ts" },
  bundle: true, format: "esm", platform: "node", write: false,
});
const m = await import("data:text/javascript;base64," + Buffer.from(out.outputFiles[0].text).toString("base64"));
const { proactiveViews, proactiveAnswer, en, te } = m;

let passed = 0;
const test = (name, fn) => { try { fn(); passed++; console.log("PASS", name); } catch (e) { console.log("FAIL", name, "\n   ", e.message); process.exitCode = 1; } };
const fmt = (iso) => iso.slice(0, 10);
const ev = (id) => ({ analysis_id: id, at: `2026-08-0${id}T09:00:00Z` });
const item = (extra = {}) => ({ priority: "attention", issue: "Leaf spot", crop: "Tomato", reasons: [{ kind: "recurring", count: 3, window: 5, dates: [ev(1), ev(3), ev(5)] }], actions: ["inspect_plants"], expert_suggested: false, evidence_count: 3, latest_at: ev(5).at, analysis_id: 5, ...extra });
const data = (items) => ({ farm_id: 1, level: items.some((i) => i.priority === "important") ? "important" : items.length ? "attention" : "none", total_checks: 5, items });
const combined = item({
  priority: "important", expert_suggested: true, actions: ["consult_expert"],
  reasons: [{ kind: "latest_high", dates: [ev(5)] }, { kind: "recurring", count: 3, window: 5, dates: [ev(1), ev(3), ev(5)] }],
});

test("one issue = one card; the title follows the strongest reason; reasons are merged (max 2 on the card, all kept)", () => {
  const [v] = proactiveViews(en.pi, en.ds, data([combined]), fmt);
  assert.equal(v.title, en.pi.heading.latest_high);
  assert.equal(v.priority, "important");
  assert.equal(v.reasons.length, 2);
  assert.ok(v.reasons[0].includes("rated \"Needs prompt attention\"") && v.reasons[1].includes("3 of the last 5 stored checks"));
  assert.equal(v.next, en.ds.action.consult_expert);
  assert.ok(v.meta.includes("Latest stored check: 2026-08-05") && v.meta.includes("Based on 3 stored checks"));
});

test("reasons beyond two stay available for the Copilot (full evidence), not on the card", () => {
  const three = item({ reasons: [{ kind: "latest_high", dates: [ev(5)] }, { kind: "repeated_high", count: 2, window: 5, dates: [ev(2), ev(5)] }, { kind: "recurring", count: 3, window: 5, dates: [ev(1), ev(3), ev(5)] }] });
  const [v] = proactiveViews(en.pi, en.ds, data([three]), fmt);
  assert.equal(v.reasons.length, 2);
  assert.equal(v.allReasons.length, 3);
});

test("English and Telugu express identical facts for every reason kind", () => {
  const kinds = [
    { kind: "latest_high", dates: [ev(5)] }, { kind: "repeated_high", count: 2, window: 5, dates: [ev(2), ev(5)] }, { kind: "recurring", count: 3, window: 6, dates: [ev(1)] },
    { kind: "more_frequent", count: 3, earlier_count: 1, dates: [ev(1)] }, { kind: "unresolved_verify", dates: [ev(5)] },
  ];
  for (const r of kinds) {
    const d = data([item({ reasons: [r] })]);
    const [a] = proactiveViews(en.pi, en.ds, d, fmt), [b] = proactiveViews(te.pi, te.ds, d, fmt);
    assert.equal(a.allReasons.length, b.allReasons.length);
    for (const num of [r.count, r.window, r.earlier_count].filter((x) => x != null)) { assert.ok(a.allReasons[0].includes(String(num))); assert.ok(b.allReasons[0].includes(String(num))); }
    assert.ok(/[ఀ-౿]/.test(b.title) && /[ఀ-౿]/.test(b.allReasons[0]) && !/undefined|NaN|\[object/.test(b.allReasons[0] + b.title + b.meta + b.next));
    assert.ok(!/undefined|NaN/.test(a.allReasons[0] + a.title + a.meta + a.next));
  }
});

test("Copilot 'What needs my attention?': zero items -> the exact 'nothing needs attention' sentence, no evidence", () => {
  const a = proactiveAnswer(en.pi, en.ds, data([]), fmt);
  assert.deepEqual(a.lines, ["Nothing in the stored checks currently needs additional attention."]);
  assert.equal(a.evidence.length, 0);
});

test("Copilot answer for one and several items lists them with reasons, next step and the real checks they rest on", () => {
  const one = proactiveAnswer(en.pi, en.ds, data([combined]), fmt);
  assert.ok(one.lines[0].startsWith("1 item needs attention"));
  assert.ok(one.lines.some((l) => l.includes('"Leaf spot"')) && one.lines.includes(en.ds.action.consult_expert));
  assert.deepEqual(one.evidence.map((e) => e.analysis_id).sort(), [1, 3, 5]);
  const many = proactiveAnswer(en.pi, en.ds, data([combined, item({ issue: "Insect pest damage", analysis_id: 4, latest_at: ev(4).at, reasons: [{ kind: "more_frequent", count: 2, earlier_count: 0, dates: [ev(4)] }] })]), fmt);
  assert.ok(many.lines[0].startsWith("2 items need attention"));
  assert.deepEqual(many.evidence.map((e) => e.analysis_id).sort(), [1, 3, 4, 5]);
  const te1 = proactiveAnswer(te.pi, te.ds, data([combined]), fmt);
  assert.ok(/[ఀ-౿]/.test(te1.lines.join(" ")) && te1.evidence.length === 3);
  assert.equal(proactiveAnswer(te.pi, te.ds, data([]), fmt).lines[0], te.pi.ans.none);
});

test("wording is historical: no live-state claims, no causal claims, no treatment wording (en + te, incl. templates)", () => {
  const render = (k, v) => (typeof v === "function" ? v("x", "y", "z") : v);
  for (const dict of [en, te]) {
    const all = JSON.stringify(dict.pi, render).toLowerCase();
    assert.ok(!/(is spreading|still present|is affected|currently has|currently affected|currently spreading|your crop has|caused by|because of your|spray|dosage|fertili[sz]er|pesticide|guarantee)/.test(all), dict.locale);
  }
  assert.ok(en.pi.note.includes("no live view"));
  const all = JSON.stringify(en.pi, render).toLowerCase();
  assert.ok(all.includes("latest stored check") && all.includes("stored checks"));
});

test("the new question exists in both languages", () => {
  for (const dict of [en, te]) assert.ok(dict.ins.q.needs.length > 5);
});

console.log(`\n${passed} passed${process.exitCode ? ", SOME FAILED" : ""}`);
