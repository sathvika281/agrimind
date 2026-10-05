// Tests for the deterministic history answers (no browser, no model). Run: npm run test:insights
import assert from "node:assert/strict";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { buildSync } from "esbuild";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = buildSync({
  stdin: {
    contents: `export * from "./src/insights/answers"; export { en } from "./src/i18n/en"; export { te } from "./src/i18n/te";`,
    resolveDir: root, loader: "ts",
  },
  bundle: true, format: "esm", platform: "node", write: false,
});
const m = await import("data:text/javascript;base64," + Buffer.from(out.outputFiles[0].text).toString("base64"));
const { answer, profileAnswer, recordedItems, QUESTIONS, PROFILE_QUESTIONS, trendObservation, en, te } = m;

let passed = 0;
const test = (name, fn) => { try { fn(); passed++; console.log("PASS", name); } catch (e) { console.log("FAIL", name, "\n   ", e.message); process.exitCode = 1; } };
const fmt = (iso) => iso.slice(0, 10);
const chk = (id, issue, severity = "unknown", crop = "Tomato") => ({ analysis_id: id, at: `2026-08-${String(id).padStart(2, "0")}T09:00:00Z`, crop, issue, severity });
const ev = (c) => ({ analysis_id: c.analysis_id, at: c.at });
const base = (checks, extra = {}) => {
  const total = checks.length;
  return {
    farm_id: 1, level: total === 0 ? "none" : total === 1 ? "one" : total <= 3 ? "limited" : "enough", total,
    first_at: checks[0]?.at ?? null, last_at: checks.at(-1)?.at ?? null, latest: checks.at(-1) ?? null,
    severity_counts: { low: 0, medium: 0, high: 0, unknown: total }, unclear_count: 0, issues: [], recent: [...checks].reverse().slice(0, 8),
    trends: [], comparison: null, ...extra,
  };
};

test("0 checks: every question says there is nothing yet (no invented answer)", () => {
  const d = base([]);
  for (const q of QUESTIONS) {
    const a = answer(en.ins, d, q, fmt);
    assert.equal(a.insufficient, true, q);
    assert.deepEqual(a.evidence, [], q);
    assert.match(a.lines.join(" "), /No crop checks yet|at least two checks/, q);
  }
});

test("1 check: recurrence/frequency questions say AgriMind cannot establish a trend", () => {
  const c = chk(1, "Leaf spot");
  const d = base([c]);
  for (const q of ["recurring", "often"]) {
    const a = answer(en.ins, d, q, fmt);
    assert.equal(a.insufficient, true);
    assert.match(a.lines[0], /only one completed check .* cannot establish a historical trend/);
  }
  assert.match(answer(en.ins, d, "changed", fmt).lines[0], /at least two checks/);
  assert.equal(answer(en.ins, d, "recent", fmt).evidence[0].analysis_id, 1);
});

test("2-3 checks: recurring is 'cannot say'; comparison works and cites both checks", () => {
  const a1 = chk(1, "Leaf spot"), a2 = chk(2, "Leaf spot");
  const d = base([a1, a2], { comparison: { previous: a1, latest: a2, same_issue: true, comparable: true, same_crop: true, severity_changed: false } });
  assert.match(answer(en.ins, d, "recurring", fmt).lines[0], /only 2 completed checks/);
  const c = answer(en.ins, d, "changed", fmt);
  assert.match(c.lines[0], /same issue/);
  assert.deepEqual(c.evidence.map((e) => e.analysis_id), [1, 2]);
  assert.ok(!c.insufficient);
});

test("a change in issue and severity is reported using the stored values only", () => {
  const a1 = chk(1, "Leaf spot", "low"), a2 = chk(2, "Insect damage", "high");
  const d = base([a1, a2], { comparison: { previous: a1, latest: a2, same_issue: false, comparable: true, same_crop: true, severity_changed: true } });
  const t = answer(en.ins, d, "changed", fmt).lines.join(" ");
  assert.ok(t.includes('was "Leaf spot", now "Insect damage"') && t.includes("Low concern") && t.includes("Needs prompt attention"));
});

test("enough checks with a recurring trend: the answer cites exactly the trend's evidence", () => {
  const cs = [1, 2, 3, 4, 5].map((i) => chk(i, i % 2 ? "Leaf spot" : "Other"));
  const tr = { kind: "recurring", issue: "Leaf spot", count: 3, window: 5, evidence: [cs[0], cs[2], cs[4]].map(ev) };
  const d = base(cs, { trends: [tr] });
  const a = answer(en.ins, d, "recurring", fmt);
  assert.match(a.lines[0], /"Leaf spot" appeared in 3 of the last 5 checks/);
  assert.deepEqual(a.evidence.map((e) => e.analysis_id), [1, 3, 5]);
  assert.equal(trendObservation(en.ins, tr), a.lines[0]);
});

test("enough checks but no pattern: says so instead of inventing one", () => {
  const cs = [1, 2, 3, 4].map((i) => chk(i, `Issue ${i}`));
  const d = base(cs);
  assert.equal(answer(en.ins, d, "recurring", fmt).lines[0], en.ins.ans.noRecurring);
  assert.equal(answer(en.ins, d, "often", fmt).lines[0], en.ins.ans.noRepeat);
});

test("'attention' with nothing supported = honest 'not enough information' and no action invented", () => {
  const d = base([chk(1, "Leaf spot", "unknown")]);
  const a = answer(en.ins, d, "attention", fmt);
  assert.equal(a.insufficient, true);
  assert.ok(a.lines[0].includes("doesn't have enough information to recommend a specific action"));
  assert.deepEqual(a.evidence, []);
});

test("'attention' uses a real rated latest check and the trend recommendations (generic, no chemicals/doses)", () => {
  const cs = [1, 2, 3, 4].map((i) => chk(i, "Leaf spot", i >= 3 ? "high" : "medium"));
  const tr = { kind: "repeated_high", issue: "Leaf spot", count: 2, window: 4, evidence: [cs[2], cs[3]].map(ev) };
  const a = answer(en.ins, base(cs, { trends: [tr] }), "attention", fmt);
  const t = a.lines.join(" ");
  assert.ok(t.includes("local agriculture officer") && t.includes('rated "Needs prompt attention"'));
  assert.ok(!/\b(spray|pesticide|fungicide|dose|dosage|ml|litre|liter|kg|fertili[sz]er|irrigat)/i.test(t));
  assert.deepEqual(a.evidence.map((e) => e.analysis_id).sort(), [3, 4]);
});

test("'often' reports the top issue with its own evidence", () => {
  const cs = [1, 2, 3].map((i) => chk(i, "Leaf spot"));
  const d = base(cs, { issues: [{ label: "Leaf spot", count: 3, last_seen: cs[2].at, evidence: cs.map(ev) }] });
  const a = answer(en.ins, d, "often", fmt);
  assert.match(a.lines[0], /"Leaf spot" is named most often: 3 of 3 checks/);
  assert.equal(a.evidence.length, 3);
});

test("English and Telugu answers exist for every question and every history level, with no undefined/NaN", () => {
  const cs = [1, 2, 3, 4, 5, 6].map((i) => chk(i, i % 2 ? "Leaf spot" : "Other", i > 4 ? "high" : "medium"));
  const tr = ["recurring", "more_frequent", "less_frequent", "repeated_high", "stable"].map((kind) => ({ kind, issue: "Leaf spot", count: 3, window: 6, earlier_count: 1, severity: "medium", evidence: [ev(cs[0])] }));
  const datasets = [base([]), base([cs[0]]), base(cs.slice(0, 2), { comparison: { previous: cs[0], latest: cs[1], same_issue: false, comparable: true, same_crop: true, severity_changed: true } }), base(cs, { trends: tr, issues: [{ label: "Leaf spot", count: 3, last_seen: cs[4].at, evidence: [ev(cs[0])] }] })];
  for (const dict of [en, te]) {
    for (const d of datasets) for (const q of QUESTIONS) {
      const t = answer(dict.ins, d, q, fmt).lines.join(" ");
      assert.ok(t.length > 5 && !/undefined|NaN|\[object/.test(t), `${dict.locale} ${q} ${d.level}: ${t}`);
    }
    for (const k of tr) assert.ok(trendObservation(dict.ins, k).length > 5 && dict.ins.interp[k.kind] && dict.ins.reco[k.kind]);
  }
  assert.match(answer(te.ins, datasets[1], "recurring", fmt).lines[0], /[ఀ-౿]/);
});

test("no wording claims sensors/satellite/live data anywhere in the insights text", () => {
  const all = JSON.stringify([en.ins, te.ins], (k, v) => (typeof v === "function" ? v("x", 1, 2, 3) : v));
  assert.ok(!/\b(LIVE|REAL-TIME|MEASURED|DETECTED|CURRENT SENSOR VALUE)\b/.test(all));
  for (const d of [en, te]) assert.ok(d.ins.unknown.length >= 3 && d.ins.ans.basis.length > 10);
});

// ---------- Phase 10: farmer-recorded context ----------
const longFmt = (iso) => iso;
const farm = (extra = {}) => ({ id: 1, name: "F", location: "", soil_type: "", created_at: "2026-01-01T00:00:00Z", ...extra });

test("profile question lists ONLY what the farmer recorded, labelled; missing = 'hasn't been provided' (never a guess)", () => {
  const none = profileAnswer(en.ins, en.prof, null, farm(), "profile", fmt, longFmt);
  assert.equal(none.insufficient, true);
  assert.equal(none.lines[0], "That information hasn't been provided for this farm.");
  const some = profileAnswer(en.ins, en.prof, null, farm({ primary_crop: "Tomato", irrigation_method: "drip", soil_type: "Red soil" }), "profile", fmt, longFmt);
  const t = some.lines.join(" | ");
  assert.ok(t.includes("Main crop: Tomato") && t.includes("Irrigation: Drip") && t.includes("Soil type: Red soil"));
  assert.ok(!t.includes("Season") && !t.includes("Planting"), "unprovided fields must not appear");
  assert.equal(some.insufficient, false);
});

test("crop-issues question uses the recorded crop against REAL stored checks of that crop only", () => {
  const cs = [chk(1, "Leaf spot", "unknown", "Tomato"), chk(2, "Insect damage", "unknown", "Rice"), chk(3, "Leaf curl", "unknown", "tomato")];
  const d = base(cs);
  const a = profileAnswer(en.ins, en.prof, d, farm({ primary_crop: "Tomato" }), "cropIssues", fmt, longFmt);
  assert.ok(a.lines.join(" ").includes("Leaf spot") && a.lines.join(" ").includes("Leaf curl") && !a.lines.join(" ").includes("Insect damage"));
  assert.deepEqual(a.evidence.map((e) => e.analysis_id).sort(), [1, 3]);
  const noCheck = profileAnswer(en.ins, en.prof, d, farm({ primary_crop: "Chilli" }), "cropIssues", fmt, longFmt);
  assert.ok(noCheck.insufficient && noCheck.lines[0].includes("No stored checks for Chilli") && noCheck.evidence.length === 0);
  const noCrop = profileAnswer(en.ins, en.prof, d, farm(), "cropIssues", fmt, longFmt);
  assert.ok(noCrop.insufficient && noCrop.lines[0].includes("hasn't been provided"));
});

test("profile answers exist in Telugu and never print undefined", () => {
  const f = farm({ primary_crop: "టమాటా", irrigation_method: "drip", season: "kharif", planting_date: "2026-07-01", soil_type: "ఎర్ర నేల", location: "గుంటూరు" });
  const d = base([chk(1, "ఆకు మచ్చ", "unknown", "టమాటా")]);
  for (const q of PROFILE_QUESTIONS) for (const dict of [en, te]) for (const fm of [farm(), f]) {
    const t = profileAnswer(dict.ins, dict.prof, d, fm, q, fmt, longFmt).lines.join(" ");
    assert.ok(t.length > 5 && !/undefined|NaN|\[object/.test(t), `${dict.locale} ${q}: ${t}`);
  }
  assert.match(profileAnswer(te.ins, te.prof, d, f, "profile", fmt, longFmt).lines.join(" "), /[ఀ-౿]/);
  assert.equal(recordedItems(en.prof, farm(), longFmt).length, 0);
});

test("profile wording makes no causal claim and offers no dose/chemical advice", () => {
  const all = JSON.stringify([en.ins, en.prof, te.ins, te.prof], (k, v) => (typeof v === "function" ? v("x", "y", 3) : v));
  assert.ok(!/\b(caused by|because of your|due to your irrigation|dosage|spray|pesticide)\b/i.test(all));
});

console.log(`\n${passed} passed${process.exitCode ? ", SOME FAILED" : ""}`);
